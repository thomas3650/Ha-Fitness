"""Sessions (step 5 spec §3): the frozen plan of a workout, its phases, and starting and reading one.

One session at a time can be running or paused. Every public method runs under the training days' lock and reads the
time from the shared clock, so sessions, training days and program writes never interleave.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import math
from typing import Any, cast, get_args

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from . import changes
from .clock import Clock
from .db import session
from .errors import NotFound, SessionError
from .models import (
    ACTIVE_SESSION_STATUSES,
    AppState,
    SessionParticipant,
    SessionStatus,
    TrainingDay,
    TrainingDayStatus,
    WorkoutSession,
)
from .people import MAX_PEOPLE, People
from .programs import Programs
from .schemas import (
    Feeling,
    NextPhase,
    PhaseKind,
    ProgramOut,
    SessionHistory,
    SessionParticipantOut,
    SessionPhase,
    SessionStation,
    SessionTotals,
    SessionView,
    StationRef,
)
from .training_days import TrainingDays

type Publish = Callable[[dict[str, Any]], None]

COMMANDS = ("pause", "resume", "next", "previous", "end")
# How a completed session can feel (UI refresh spec §3.3), from the `Feeling` type so the two match.
FEELINGS: tuple[str, ...] = get_args(Feeling.__value__)
# `GET /session` keeps a finished view this long (spec §3.5).
FINISHED_VIEW_KEPT = timedelta(minutes=5)
# The tick writes `last_tick_at` at least this often (spec §3.2).
TICK_WRITE = timedelta(seconds=5)
# `previous` restarts a work phase once it has run this many seconds; before, it goes back one (spec §3.3).
RESTART_AFTER = 3
# A session paused this long is ended (spec §3.2's pause limit).
PAUSE_LIMIT = timedelta(minutes=30)
MAX_HISTORY = 100
# The app's one row in `app_state` (migration 0003).
_APP_STATE_ID = 1
# The events of a finish; any of them may change `today` or the stats.
_FINISH_EVENTS = frozenset({"done", "session_completed", "session_ended"})


class PlanStation(BaseModel):
    """A station of the plan: the exercise id and its name at the start."""

    exercise_id: str
    name: str


class PlanParticipant(BaseModel):
    """A participant of the plan: the person's id and name at the start."""

    id: int
    name: str


class Plan(BaseModel):
    """The plan of a session, frozen at the start (step 5 spec §3.1) and stored as JSON."""

    program_id: int
    program_name: str
    stations: list[PlanStation]
    rounds: int
    work_seconds: int
    switch_seconds: int
    round_rest_seconds: int
    countdown_seconds: int
    participants: list[PlanParticipant]


@dataclass(frozen=True)
class Phase:
    """One phase of a plan.

    Participant `p` is at station `(p + current_offset) mod S` and goes to `(p + next_offset) mod S` next;
    `next_offset` is None when no work phase follows the one `current_offset` names.
    """

    kind: PhaseKind
    round: int
    interval: int
    duration: int
    current_offset: int
    next_offset: int | None


def build_plan(program: ProgramOut, participants: Sequence[tuple[int, str]]) -> Plan:
    """Freeze a program and its participants, given as (id, name) in people order, into a plan."""
    document = program.program
    return Plan(
        program_id=program.id,
        program_name=document.name,
        stations=[
            PlanStation(exercise_id=station.exercise, name=name)
            for station, name in zip(
                document.stations, program.station_names, strict=True
            )
        ],
        rounds=document.rounds,
        work_seconds=document.work_seconds,
        switch_seconds=document.switch_seconds,
        round_rest_seconds=document.round_rest_seconds,
        countdown_seconds=document.countdown_seconds,
        participants=[
            PlanParticipant(id=person_id, name=name) for person_id, name in participants
        ],
    )


def phases(plan: Plan) -> list[Phase]:
    """Return the phases of a plan (spec §3.1), each with the station offsets of its `current` and `next`.

    Every phase names the first work phase at or after it: a work phase itself, a countdown, switch or rest the one
    it leads to. Interval i (from 1) works at offset i - 1.
    """
    station_count = len(plan.stations)
    # (kind, round, interval, duration, the work offset of a work phase)
    raw: list[tuple[PhaseKind, int, int, int, int | None]] = []
    if plan.countdown_seconds:
        raw.append(("countdown", 1, 1, plan.countdown_seconds, None))
    for round_number in range(1, plan.rounds + 1):
        last_round = round_number == plan.rounds
        for interval in range(1, station_count + 1):
            raw.append(
                ("work", round_number, interval, plan.work_seconds, interval - 1)
            )
            last = last_round and interval == station_count
            if plan.switch_seconds and not last:
                raw.append(
                    ("switch", round_number, interval, plan.switch_seconds, None)
                )
        if plan.round_rest_seconds and not last_round:
            raw.append(
                ("rest", round_number, station_count, plan.round_rest_seconds, None)
            )
    work = [index for index, entry in enumerate(raw) if entry[4] is not None]
    result: list[Phase] = []
    for index, (kind, round_number, interval, duration, _offset) in enumerate(raw):
        named = next(position for position, at in enumerate(work) if at >= index)
        current = raw[work[named]][4]
        following = raw[work[named + 1]][4] if named + 1 < len(work) else None
        assert current is not None
        result.append(Phase(kind, round_number, interval, duration, current, following))
    return result


def _station(plan: Plan, participant: int, offset: int) -> StationRef:
    """Return the station participant `participant` (from 0) is at for a work offset."""
    number = (participant + offset) % len(plan.stations)
    station = plan.stations[number]
    return StationRef(
        number=number + 1, exercise_id=station.exercise_id, name=station.name
    )


def _rounds_behind(plan_phases: list[Phase], index: int) -> int:
    """Return the number of rounds whose last work phase is before phase `index`."""
    last_work: dict[int, int] = {}
    for position, phase in enumerate(plan_phases):
        if phase.kind == "work":
            last_work[phase.round] = position
    return sum(1 for position in last_work.values() if position < index)


def _totals(plan: Plan, plan_phases: list[Phase]) -> SessionTotals:
    """Return the totals of a plan: the countdown is left out of `planned`."""
    return SessionTotals(
        planned=sum(
            entry.duration for entry in plan_phases if entry.kind != "countdown"
        ),
        rounds=plan.rounds,
        stations=len(plan.stations),
    )


def _session_message(view: SessionView) -> dict[str, Any]:
    """Return the `session` push message for a view."""
    return {"type": "session", "data": view.model_dump(mode="json")}


def _event(name: str, view: SessionView, **extra: Any) -> dict[str, Any]:
    """Return a session event (spec §3.5): the session's id, program name and day, and `extra`."""
    return {
        "type": "event",
        "event": name,
        "session": {
            "id": view.id,
            "program_name": view.program_name,
            "training_day_id": view.training_day_id,
            **extra,
        },
    }


def _phase_event(view: SessionView) -> dict[str, Any]:
    """Return the `phase_changed` event for a view of a running or paused session."""
    assert view.phase is not None
    return _event("phase_changed", view, phase=view.phase.model_dump(mode="json"))


class Sessions:
    """Starts, ticks, steers, finishes and reads sessions (spec §3.2 to §3.5).

    Every public method runs under the training days' lock and ticks first, so a command just after a deadline acts
    on the phase that is current then. Push messages go out after the commit, still under the lock.
    """

    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        training_days: TrainingDays,
        programs: Programs,
        people: People,
        publish: Publish,
    ) -> None:
        """Use `engine`, `clock`, the training days (and their lock), the programs, the people and `publish`."""
        self._engine = engine
        self._clock = clock
        self._training_days = training_days
        self._programs = programs
        self._people = people
        self._publish = publish
        # The finished session whose view `GET /session` still shows; the loop pushes `session: null` when it goes,
        # unless a new session has started, which sends its own view.
        self._shown: int | None = None

    def start(
        self,
        program_id: int,
        participants: list[int],
        training_day_id: int | None,
        client: str,
    ) -> SessionView:
        """Freeze the plan and start at phase 0; log it (spec §3.3).

        Raise `SessionError`: 404 `not_found` for an unknown program, person or day; 409 `conflict` while a session
        is running or paused, for an inactive program, or a day that isn't open or is another program's; 422
        `invalid` for an empty list, more than two, duplicates, or more people than stations.
        """
        with self._training_days.lock:
            self._training_days.reconcile_now()
            self._check_list(participants)
            program = self._program(program_id)
            people = self._participants(participants)
            station_count = len(program.program.stations)
            if len(people) > station_count:
                raise SessionError(
                    422,
                    "invalid",
                    f"{len(people)} participants, but {program.program.name} has {station_count} station(s)",
                )
            now = self._clock.now()
            self._tick_alone(now)
            messages: list[dict[str, Any]] = []
            with session(self._engine) as db_session:
                if self._active(db_session) is not None:
                    raise SessionError(409, "conflict", "A session is already running")
                if training_day_id is not None:
                    self._check_day(db_session, training_day_id, program_id)
                plan = build_plan(program, people)
                first = phases(plan)[0]
                row = WorkoutSession(
                    plan=plan.model_dump(mode="json"),
                    training_day_id=training_day_id,
                    status=SessionStatus.RUNNING,
                    counted=False,
                    phase_index=0,
                    phase_started_at=now,
                    paused_at=None,
                    paused_seconds=0.0,
                    last_tick_at=now,
                    started_at=now if first.kind == "work" else None,
                    ended_at=None,
                    rounds_completed=0,
                    revision=1,
                )
                db_session.add(row)
                db_session.flush()
                names = ", ".join(name for _id, name in people)
                changes.record(
                    db_session,
                    client=client,
                    action="session.started",
                    target=f"session:{row.id}",
                    summary=f"Started session of {plan.program_name} for {names}",
                )
                view = self._view(row, now)
                messages += [_session_message(view), _event("session_started", view)]
            self._send(messages)
            return view

    def tick(self, now: datetime | None = None) -> float | None:
        """Move the session on to `now` (the clock's time by default) and publish the change; for the session loop.

        It also ends a session paused too long, and publishes `session: null` once a finished view's 5 minutes are
        over. It returns the seconds until the running session's phase deadline, or None when nothing runs.
        """
        with self._training_days.lock:
            moment = self._clock.now() if now is None else now
            wait: float | None = None
            with session(self._engine) as db_session:
                messages = self._tick(db_session, moment)
                row = self._active(db_session)
                if row is not None and row.status == SessionStatus.RUNNING:
                    duration = phases(Plan.model_validate(row.plan))[
                        row.phase_index
                    ].duration
                    deadline = row.phase_started_at + timedelta(seconds=duration)
                    wait = max(0.0, (deadline - moment).total_seconds())
                elif row is None and self._shown is not None:
                    shown = db_session.get(WorkoutSession, self._shown)
                    if (
                        shown is None
                        or shown.ended_at is None
                        or moment - shown.ended_at >= FINISHED_VIEW_KEPT
                    ):
                        messages.append({"type": "session", "data": None})
                        self._shown = None
            self._send(messages)
            return wait

    def recover(self) -> None:
        """At the start: pause a session still running after a crash at its `last_tick_at` (spec §3.2).

        The time the add-on was down then counts as a pause, and the pause limit applies at once. A finished view still
        inside its 5 minutes gets its `session: null` from the loop.
        """
        with self._training_days.lock:
            now = self._clock.now()
            messages: list[dict[str, Any]] = []
            with session(self._engine) as db_session:
                row = self._active(db_session)
                if row is not None and row.status == SessionStatus.RUNNING:
                    row.status = SessionStatus.PAUSED
                    row.paused_at = row.last_tick_at
                    messages += self._changed(row, now, phase_changed=False)
                messages += self._tick(db_session, now)
                # Only a view still inside its 5 minutes needs a null later; the tick's own finish may be older.
                last = self._last_finished(db_session)
                self._shown = (
                    last.id
                    if last is not None
                    and last.ended_at is not None
                    and now - last.ended_at < FINISHED_VIEW_KEPT
                    else None
                )
            self._send(messages)

    def pause_for_shutdown(self) -> None:
        """At shutdown: tick, then pause a running session now (spec §3.2), so the next start resumes from here."""
        with self._training_days.lock:
            now = self._clock.now()
            self._tick_alone(now)
            with session(self._engine) as db_session:
                row = self._active(db_session)
                messages = (
                    self._pause(row, now)
                    if row is not None and row.status == SessionStatus.RUNNING
                    else []
                )
            self._send(messages)

    def current(self) -> SessionView | None:
        """Tick, then return the running or paused session, else the last one finished under 5 minutes ago, else None."""
        with self._training_days.lock:
            now = self._clock.now()
            self._tick_alone(now)
            with session(self._engine) as db_session:
                row = self._active(db_session)
                if row is not None:
                    view: SessionView | None = self._view(row, now)
                else:
                    last = self._last_finished(db_session)
                    recent = (
                        last is not None
                        and last.ended_at is not None
                        and now - last.ended_at < FINISHED_VIEW_KEPT
                    )
                    view = (
                        self._finished_view(db_session, last, now)
                        if recent and last is not None
                        else None
                    )
            return view

    def finished(self, limit: int = 20) -> SessionHistory:
        """Tick, then return up to `limit` finished sessions, newest first, and `counting_from` (spec §3.5).

        Raise `SessionError` 422 `invalid` for a limit outside 1 to 100.
        """
        if not 1 <= limit <= MAX_HISTORY:
            raise SessionError(
                422, "invalid", f"limit must be from 1 to {MAX_HISTORY}, got {limit}"
            )
        with self._training_days.lock:
            now = self._clock.now()
            self._tick_alone(now)
            with session(self._engine) as db_session:
                rows = db_session.scalars(
                    select(WorkoutSession)
                    .where(WorkoutSession.status.not_in(ACTIVE_SESSION_STATUSES))
                    .order_by(WorkoutSession.ended_at.desc(), WorkoutSession.id.desc())
                    .limit(limit)
                )
                sessions = [self._finished_view(db_session, row, now) for row in rows]
                state = db_session.get_one(AppState, _APP_STATE_ID)
                return SessionHistory(
                    counting_from=state.counting_from, sessions=sessions
                )

    def command(self, name: str, client: str) -> SessionView:
        """Tick, then run `pause`, `resume`, `next`, `previous` or `end` (spec §3.3) and return the view.

        Raise `SessionError`: 404 `not_found` for another name, 409 `conflict` when the command isn't allowed now.
        """
        if name not in COMMANDS:
            raise SessionError(404, "not_found", f"Unknown session command {name}")
        with self._training_days.lock:
            now = self._clock.now()
            self._tick_alone(now)
            messages: list[dict[str, Any]] = []
            with session(self._engine) as db_session:
                row = self._active(db_session)
                if row is None:
                    raise SessionError(409, "conflict", "No session is running")
                if name == "pause":
                    messages += self._pause(row, now)
                elif name == "resume":
                    messages += self._resume(row, now)
                elif name == "next":
                    messages += self._next(db_session, row, now, client)
                elif name == "previous":
                    messages += self._previous(row, now)
                else:
                    messages += self._finish(
                        db_session, row, now, now, SessionStatus.ENDED, client
                    )
                view = self._any_view(db_session, row, now)
            self._send(messages)
            return view

    def feel(self, feeling: str, client: str) -> SessionView:
        """Tick, then rate the completed session of the finished view (UI refresh spec §3.3) and return its view.

        A later call replaces the rating. Raise `SessionError`: 422 `invalid` for a value not in `FEELINGS`, 409
        `conflict` unless there is no running or paused session and the last finished one is completed and ended
        under `FINISHED_VIEW_KEPT` ago.
        """
        if feeling not in FEELINGS:
            raise SessionError(
                422,
                "invalid",
                f"feeling must be one of {', '.join(FEELINGS)}, got {feeling}",
            )
        with self._training_days.lock:
            now = self._clock.now()
            self._tick_alone(now)
            with session(self._engine) as db_session:
                if self._active(db_session) is not None:
                    raise SessionError(
                        409, "conflict", "A session is still in progress"
                    )
                row = self._last_finished(db_session)
                if (
                    row is None
                    or row.ended_at is None
                    or now - row.ended_at >= FINISHED_VIEW_KEPT
                ):
                    raise SessionError(409, "conflict", "No session has just finished")
                if row.status != SessionStatus.COMPLETED:
                    raise SessionError(
                        409, "conflict", "Only a completed session can be rated"
                    )
                row.feeling = feeling
                row.revision += 1
                plan = Plan.model_validate(row.plan)
                changes.record(
                    db_session,
                    client=client,
                    action="session.feeling",
                    target=f"session:{row.id}",
                    summary=f"Rated session of {plan.program_name} as {feeling}",
                )
                db_session.flush()
                view = self._finished_view(db_session, row, now)
            self._send([_session_message(view)])
            return view

    def _tick_alone(self, now: datetime) -> None:
        """Tick in a transaction of its own and publish it, so a refused command after it can't undo the tick."""
        with session(self._engine) as db_session:
            messages = self._tick(db_session, now)
        self._send(messages)

    def _send(self, messages: list[dict[str, Any]]) -> None:
        """Publish the messages of a committed change, then `today` and the stats if a session finished.

        A finish can close a day (`done`), count an extra session or set `counting_from`, so each finish goes through
        `publish_today`, which also checks the stats.
        """
        for message in messages:
            self._publish(message)
        if any(message.get("event") in _FINISH_EVENTS for message in messages):
            self._training_days.publish_today()

    def _tick(self, db_session: Session, now: datetime) -> list[dict[str, Any]]:
        """Move the running session on by chaining each phase's start from the one before (spec §3.2).

        Several phases may pass; it returns one `session` message and one `phase_changed` event for the phase it ends
        on, or the finish's messages when the last work phase passed. It writes `last_tick_at` every 5 s and at every
        change. A session paused for `PAUSE_LIMIT` is ended at the limit, with the client `addon`.
        """
        row = self._active(db_session)
        if row is None:
            return []
        if row.paused_at is not None:
            limit = row.paused_at + PAUSE_LIMIT
            if now < limit:
                return []
            return self._finish(
                db_session, row, limit, now, SessionStatus.ENDED, "addon"
            )
        plan_phases = phases(Plan.model_validate(row.plan))
        moved = False
        while True:
            phase = plan_phases[row.phase_index]
            deadline = row.phase_started_at + timedelta(seconds=phase.duration)
            if now < deadline:
                break
            if row.phase_index == len(plan_phases) - 1:
                return self._finish(
                    db_session, row, deadline, now, SessionStatus.COMPLETED, "addon"
                )
            self._enter(row, plan_phases, row.phase_index + 1, deadline)
            moved = True
        if moved:
            return self._changed(row, now, phase_changed=True)
        if now - row.last_tick_at >= TICK_WRITE:
            row.last_tick_at = now
        return []

    def _changed(
        self, row: WorkoutSession, now: datetime, *, phase_changed: bool
    ) -> list[dict[str, Any]]:
        """Record a change of a running or paused session; return its `session` message, and `phase_changed`."""
        row.revision += 1
        row.last_tick_at = now
        view = self._view(row, now)
        messages = [_session_message(view)]
        if phase_changed:
            messages.append(_phase_event(view))
        return messages

    @staticmethod
    def _enter(
        row: WorkoutSession, plan_phases: list[Phase], index: int, at: datetime
    ) -> None:
        """Start phase `index` at `at`; the first work phase entered sets `started_at`."""
        row.phase_index = index
        row.phase_started_at = at
        if plan_phases[index].kind == "work" and row.started_at is None:
            row.started_at = at
        row.rounds_completed = _rounds_behind(plan_phases, index)

    def _pause(self, row: WorkoutSession, now: datetime) -> list[dict[str, Any]]:
        """Pause a running session."""
        if row.status != SessionStatus.RUNNING:
            raise SessionError(409, "conflict", "The session is already paused")
        row.status = SessionStatus.PAUSED
        row.paused_at = now
        return self._changed(row, now, phase_changed=False)

    def _resume(self, row: WorkoutSession, now: datetime) -> list[dict[str, Any]]:
        """Resume a paused session: the phase's start moves on by the pause, and the counted part adds to the pauses."""
        if row.paused_at is None:
            raise SessionError(409, "conflict", "The session isn't paused")
        row.paused_seconds += _counted_pause(row, now)
        row.phase_started_at += now - row.paused_at
        row.paused_at = None
        row.status = SessionStatus.RUNNING
        return self._changed(row, now, phase_changed=False)

    def _next(
        self, db_session: Session, row: WorkoutSession, now: datetime, client: str
    ) -> list[dict[str, Any]]:
        """Go to the start of the next work phase; on the last work phase, complete the session."""
        plan_phases = phases(Plan.model_validate(row.plan))
        following = [
            index
            for index in range(row.phase_index + 1, len(plan_phases))
            if plan_phases[index].kind == "work"
        ]
        if not following:
            return self._finish(
                db_session, row, now, now, SessionStatus.COMPLETED, client
            )
        self._enter(row, plan_phases, following[0], row.paused_at or now)
        return self._changed(row, now, phase_changed=True)

    def _previous(self, row: WorkoutSession, now: datetime) -> list[dict[str, Any]]:
        """Go to the start of this work phase, or of the one before (spec §3.3's 3 s rule); restart the first."""
        plan_phases = phases(Plan.model_validate(row.plan))
        at = row.paused_at or now
        phase = plan_phases[row.phase_index]
        ran = (at - row.phase_started_at).total_seconds()
        earlier = [
            index
            for index in range(row.phase_index)
            if plan_phases[index].kind == "work"
        ]
        if (phase.kind == "work" and ran >= RESTART_AFTER) or not earlier:
            target = row.phase_index
        else:
            target = earlier[-1]
        self._enter(row, plan_phases, target, at)
        return self._changed(row, now, phase_changed=True)

    def _finish(
        self,
        db_session: Session,
        row: WorkoutSession,
        at: datetime,
        now: datetime,
        status: SessionStatus,
        client: str,
    ) -> list[dict[str, Any]]:
        """Complete or end a session at `at` (spec §3.4) and log it; return its messages.

        An open pause is closed first. It stores the participants, sets `counting_from` once, and a counted session
        with a training day closes the day as done.
        """
        plan = Plan.model_validate(row.plan)
        plan_phases = phases(plan)
        if row.paused_at is not None:
            row.paused_seconds += _counted_pause(row, at)
            row.paused_at = None
        completed = status == SessionStatus.COMPLETED
        row.status = status
        row.ended_at = at
        row.rounds_completed = (
            plan.rounds if completed else _rounds_behind(plan_phases, row.phase_index)
        )
        row.counted = row.rounds_completed >= 1
        row.revision += 1
        row.last_tick_at = now
        for position, person in enumerate(plan.participants):
            db_session.add(
                SessionParticipant(
                    session_id=row.id,
                    position=position,
                    person_id=person.id,
                    name=person.name,
                )
            )
        messages: list[dict[str, Any]] = []
        done: dict[str, Any] | None = None
        if row.counted:
            state = db_session.get_one(AppState, _APP_STATE_ID)
            if state.counting_from is None:
                state.counting_from = self._training_days.local_date(at)
            if row.training_day_id is not None:
                done = self._training_days.close_done(
                    db_session, row.training_day_id, at
                )
        names = ", ".join(person.name for person in plan.participants)
        rounds = f"{row.rounds_completed} of {plan.rounds} rounds"
        changes.record(
            db_session,
            client=client,
            action=f"session.{status.value}",
            target=f"session:{row.id}",
            summary=(
                f"{'Completed' if completed else 'Ended'} session of {plan.program_name} for {names}"
                f" ({rounds}{'' if row.counted else ', not counted'})"
            ),
        )
        db_session.flush()
        self._shown = row.id
        view = self._finished_view(db_session, row, now)
        messages.append(_session_message(view))
        if completed:
            messages.append(_event("session_completed", view))
        else:
            messages.append(_event("session_ended", view, counted=row.counted))
        if done is not None:
            messages.append(done)
        return messages

    @staticmethod
    def _check_list(participants: list[int]) -> None:
        """Refuse an empty list, more than two people, or a person given twice, as 422 `invalid`."""
        if not participants:
            raise SessionError(422, "invalid", "At least one participant is needed")
        if len(participants) > MAX_PEOPLE:
            raise SessionError(
                422,
                "invalid",
                f"At most {MAX_PEOPLE} participants, got {len(participants)}",
            )
        if len(set(participants)) != len(participants):
            raise SessionError(422, "invalid", "A participant is given more than once")

    def _program(self, program_id: int) -> ProgramOut:
        """Return the program; 404 when there is none, 409 when it is switched off."""
        try:
            program = self._programs.get(program_id)
        except NotFound as error:
            raise SessionError(404, "not_found", str(error)) from error
        if not program.program.active:
            raise SessionError(
                409, "conflict", f"Program {program.program.name} isn't active"
            )
        return program

    def _participants(self, participants: list[int]) -> list[tuple[int, str]]:
        """Return the participants as (id, name) in people order; 404 for an id no person has."""
        stored = self._people.stored()
        known = {person.id for person in stored}
        for person_id in participants:
            if person_id not in known:
                raise SessionError(404, "not_found", f"Person {person_id} not found")
        return [
            (person.id, person.name) for person in stored if person.id in participants
        ]

    @staticmethod
    def _check_day(db_session: Session, day_id: int, program_id: int) -> None:
        """Refuse an unknown day (404), and a closed day or another program's (409)."""
        day = db_session.get(TrainingDay, day_id)
        if day is None:
            raise SessionError(404, "not_found", f"Training day {day_id} not found")
        if day.status != TrainingDayStatus.OPEN:
            raise SessionError(
                409,
                "conflict",
                f"Training day {day_id} is {day.status.value}, not open",
            )
        if day.program_id != program_id:
            raise SessionError(
                409,
                "conflict",
                f"Training day {day_id} belongs to another program",
            )

    @staticmethod
    def _last_finished(db_session: Session) -> WorkoutSession | None:
        """Return the session that finished last, if any."""
        return db_session.scalar(
            select(WorkoutSession)
            .where(WorkoutSession.ended_at.is_not(None))
            .order_by(WorkoutSession.ended_at.desc(), WorkoutSession.id.desc())
            .limit(1)
        )

    @staticmethod
    def _active(db_session: Session) -> WorkoutSession | None:
        """Return the running or paused session, if there is one."""
        return db_session.scalar(
            select(WorkoutSession).where(
                WorkoutSession.status.in_(ACTIVE_SESSION_STATUSES)
            )
        )

    def _any_view(
        self, db_session: Session, row: WorkoutSession, now: datetime
    ) -> SessionView:
        """Return the view of a session: the live one while it runs or is paused, else the finished one."""
        if row.status in ACTIVE_SESSION_STATUSES:
            return self._view(row, now)
        return self._finished_view(db_session, row, now)

    @staticmethod
    def _finished_view(
        db_session: Session, row: WorkoutSession, now: datetime
    ) -> SessionView:
        """Build the view of a finished session: participants from its stored rows; no phase, next phase or stations."""
        plan = Plan.model_validate(row.plan)
        participants = db_session.scalars(
            select(SessionParticipant)
            .where(SessionParticipant.session_id == row.id)
            .order_by(SessionParticipant.position)
        )
        return SessionView(
            id=row.id,
            revision=row.revision,
            status=row.status.value,
            counted=row.counted,
            program_name=plan.program_name,
            training_day_id=row.training_day_id,
            participants=[
                SessionParticipantOut(id=person.person_id, name=person.name)
                for person in participants
            ],
            phase=None,
            next_phase=None,
            stations=None,
            totals=_totals(plan, phases(plan)),
            started_at=row.started_at,
            ended_at=row.ended_at,
            rounds_completed=row.rounds_completed,
            time_trained=time_trained(row, now),
            server_time=now,
            feeling=cast(Feeling | None, row.feeling),
        )

    @staticmethod
    def _view(row: WorkoutSession, now: datetime) -> SessionView:
        """Build the view of a running or paused session at `now` (spec §3.5)."""
        plan = Plan.model_validate(row.plan)
        plan_phases = phases(plan)
        phase = plan_phases[row.phase_index]
        ends = row.phase_started_at + timedelta(seconds=phase.duration)
        paused = row.paused_at is not None
        following = (
            plan_phases[row.phase_index + 1]
            if row.phase_index + 1 < len(plan_phases)
            else None
        )
        return SessionView(
            id=row.id,
            revision=row.revision,
            status=row.status.value,
            counted=row.counted,
            program_name=plan.program_name,
            training_day_id=row.training_day_id,
            participants=[
                SessionParticipantOut(id=person.id, name=person.name)
                for person in plan.participants
            ],
            phase=SessionPhase(
                index=row.phase_index,
                kind=phase.kind,
                round=phase.round,
                interval=phase.interval,
                duration=phase.duration,
                ends_at=None if paused else ends,
                remaining=(
                    (ends - row.paused_at).total_seconds()
                    if row.paused_at is not None
                    else None
                ),
            ),
            next_phase=(
                None
                if following is None
                else NextPhase(kind=following.kind, duration=following.duration)
            ),
            stations=[
                SessionStation(
                    current=_station(plan, participant, phase.current_offset),
                    next=(
                        None
                        if phase.next_offset is None
                        else _station(plan, participant, phase.next_offset)
                    ),
                )
                for participant in range(len(plan.participants))
            ],
            totals=_totals(plan, plan_phases),
            started_at=row.started_at,
            ended_at=row.ended_at,
            rounds_completed=row.rounds_completed,
            time_trained=time_trained(row, now),
            server_time=now,
            feeling=None,
        )


def _counted_pause(row: WorkoutSession, until: datetime) -> float:
    """Return the seconds of the open pause up to `until` that count: only those after `started_at` (spec §3.2)."""
    if row.paused_at is None or row.started_at is None:
        return 0.0
    since = max(row.paused_at, row.started_at)
    return max(0.0, (until - since).total_seconds())


def time_trained(row: WorkoutSession, now: datetime) -> int:
    """Return the whole active seconds: from `started_at` to the end, the open pause or now, less the pauses; 0 before it."""
    if row.started_at is None:
        return 0
    until = row.ended_at or row.paused_at or now
    return max(
        0, math.floor((until - row.started_at).total_seconds() - row.paused_seconds)
    )
