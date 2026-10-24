"""Sessions (step 5 spec §3): the frozen plan of a workout, its phases, and starting and reading one.

One session at a time can be running or paused. Every public method runs under the training days' lock and reads the
time from the shared clock, so sessions, training days and program writes never interleave.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from . import changes
from .clock import Clock
from .db import session
from .errors import NotFound, SessionError
from .models import SessionStatus, TrainingDay, TrainingDayStatus, WorkoutSession
from .people import MAX_PEOPLE, People
from .programs import Programs
from .schemas import (
    NextPhase,
    PhaseKind,
    ProgramOut,
    SessionParticipantOut,
    SessionPhase,
    SessionStation,
    SessionTotals,
    SessionView,
    StationRef,
)
from .training_days import TrainingDays

type Publish = Callable[[dict[str, Any]], None]

_ACTIVE = (SessionStatus.RUNNING, SessionStatus.PAUSED)


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


class Sessions:
    """Starts and reads sessions; S2 adds the tick and the commands."""

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
            with session(self._engine) as db_session:
                if self._active(db_session) is not None:
                    raise SessionError(409, "conflict", "A session is already running")
                if training_day_id is not None:
                    self._check_day(db_session, training_day_id, program_id)
                plan = build_plan(program, people)
                now = self._clock.now()
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
                return self._view(row, now)

    def current(self) -> SessionView | None:
        """Return the running or paused session, or None."""
        with self._training_days.lock:
            now = self._clock.now()
            with session(self._engine) as db_session:
                row = self._active(db_session)
                return None if row is None else self._view(row, now)

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
    def _active(db_session: Session) -> WorkoutSession | None:
        """Return the running or paused session, if there is one."""
        return db_session.scalar(
            select(WorkoutSession).where(WorkoutSession.status.in_(_ACTIVE))
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
            totals=SessionTotals(
                planned=sum(
                    entry.duration for entry in plan_phases if entry.kind != "countdown"
                ),
                rounds=plan.rounds,
                stations=len(plan.stations),
            ),
            started_at=row.started_at,
            ended_at=row.ended_at,
            rounds_completed=row.rounds_completed,
            time_trained=_time_trained(row, now),
            server_time=now,
        )


def _time_trained(row: WorkoutSession, now: datetime) -> float:
    """Return the active seconds: from `started_at` to the end, the open pause or now, less the pauses; 0 before it."""
    if row.started_at is None:
        return 0.0
    until = row.ended_at or row.paused_at or now
    return max(0.0, (until - row.started_at).total_seconds() - row.paused_seconds)
