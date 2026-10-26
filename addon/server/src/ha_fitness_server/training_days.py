"""Training days and the scheduler (step 4 spec §3.3): which program asks to be trained on which local date."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
import threading
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, delete, exists, or_, select, update
from sqlalchemy.orm import Session, aliased

from . import changes
from .clock import Clock
from .db import session
from .errors import Conflict, Invalid, NotFound
from .models import (
    ACTIVE_SESSION_STATUSES,
    Program as ProgramRow,
    SchedulerState,
    TrainingDay,
    TrainingDayStatus,
    WorkoutSession,
)
from .programs import total_minutes
from .schemas import (
    WEEK_ORDER,
    NextTraining,
    OpenDay,
    ProgramDocument,
    TodayView,
    TrainingDayOut,
    UpcomingTraining,
    Week,
)
from .settings import DEFAULT_LATE_DAYS

_LOGGER = logging.getLogger(__name__)

# Publishes one batch of push messages, in order; a batch reaches each subscriber whole (push.py).
type Publish = Callable[[list[dict[str, Any]]], None]

# The scheduler's one row in `scheduler_state` (migration 0002).
_STATE_ID = 1

# How many days after today `upcoming` and `next` look (today-ahead spec §2.2.1, §2.2.9).
_DAYS_AHEAD = 14


def _trains_on(program: ProgramRow, day: date) -> bool:
    """Return whether an active program has the weekday of `day`."""
    return program.active and WEEK_ORDER[day.weekday()] in program.document["weekdays"]


def _event(name: str, day: TrainingDay) -> dict[str, Any]:
    """Return the push message for one state change of a training day (spec §3.6)."""
    return {
        "type": "event",
        "event": name,
        "training_day": {
            "id": day.id,
            "program_id": day.program_id,
            "program_name": day.program_name,
            "date": day.date.isoformat(),
        },
    }


def _in_session(day_id: Any) -> Any:
    """Return the condition "a running or paused session is for the day `day_id`" (a column or an id)."""
    return exists().where(
        WorkoutSession.training_day_id == day_id,
        WorkoutSession.status.in_(ACTIVE_SESSION_STATUSES),
    )


def _out(day: TrainingDay) -> TrainingDayOut:
    """Turn a row into a `TrainingDayOut`."""
    return TrainingDayOut(
        id=day.id,
        program_id=day.program_id,
        program_name=day.program_name,
        date=day.date,
        status=day.status.value,
        created_at=day.created_at,
        closed_at=day.closed_at,
    )


class TrainingDays:
    """Makes and closes training days, and builds what `/today` returns.

    One re-entrant lock serialises every public method and every program write, which calls in here too. The writes
    here (a skip and the dev routes) reconcile first, so they act on the date now, and publish `today` after.

    A request reads the clock's date once, in its reconcile, and carries that date into its own checks and into the
    `today` and `stats` it publishes (#79). A change that doesn't reconcile (a session's finish, by a command or the
    session loop) publishes them for the date reconciled last: a later date's days aren't made until a reconcile.
    """

    def __init__(
        self,
        engine: Engine,
        clock: Clock,
        timezone: ZoneInfo,
        publish: Publish,
        late_days: int = DEFAULT_LATE_DAYS,
    ) -> None:
        """Use `engine`, the local dates of `timezone` at `clock`'s time, and `publish` for push messages.

        A late day stays open at most `late_days` days after its date (spec §2.1 of the today-ahead spec).
        """
        self._engine = engine
        self._late_days = late_days
        self._clock = clock
        self._timezone = timezone
        self._publish = publish
        self.lock = threading.RLock()
        self._published: TodayView | None = None
        # The date the last reconcile handled; None until the first one.
        self._reconciled: date | None = None
        # Called after every `today` check, changed or not, with the date `today` was built for: a people change leaves
        # `today` alone but not the stats. It returns the messages to publish after `today` in the same batch (the
        # stats for that date, if they changed).
        self.on_change: Callable[[date], list[dict[str, Any]]] = lambda _today: []

    def local_date(self, moment: datetime) -> date:
        """Return the local date of an aware `moment`."""
        return moment.astimezone(self._timezone).date()

    def local_today(self) -> date:
        """Return the local date now."""
        return self.local_date(self._clock.now())

    def reconcile_now(self) -> date:
        """Reconcile up to and including the local date now; return that date.

        A write that reconciles first publishes its own `today` for this date too: the clock may pass midnight between.
        """
        with self.lock:
            today = self.local_today()
            self.reconcile(today)
            return today

    def reconcile(self, today: date) -> None:
        """Handle each date from the day after the last handled one up to today, and today again (spec §3.3).

        The first run starts at today. The events go out after the commit, then `today` if it changed, as one batch:
        a long catch-up can't drop a subscriber that keeps up (push.py).
        """
        with self.lock:
            events: list[dict[str, Any]] = []
            with session(self._engine) as db_session:
                state = db_session.get_one(SchedulerState, _STATE_ID)
                start = (
                    today
                    if state.last_date is None
                    else min(state.last_date + timedelta(days=1), today)
                )
                programs = list(
                    db_session.scalars(select(ProgramRow).where(ProgramRow.active))
                )
                day = start
                while day <= today:
                    events += self._handle(db_session, programs, day, today)
                    day += timedelta(days=1)
                if state.last_date is None or state.last_date < today:
                    state.last_date = today
            self._reconciled = today
            self._publish_today(events, today)

    def _handle(
        self, db_session: Session, programs: list[ProgramRow], day: date, today: date
    ) -> list[dict[str, Any]]:
        """Make one date's training days and close the late days that are over; return the events.

        Rule 1 of spec §3.3 makes the days; today-ahead spec §2.1 closes them. `due` goes out only for a day made for
        today.
        """
        events: list[dict[str, Any]] = []
        now = self._clock.now()
        for program in programs:
            if not _trains_on(program, day):
                continue
            made = db_session.scalar(
                select(
                    exists().where(
                        TrainingDay.program_id == program.id, TrainingDay.date == day
                    )
                )
            )
            if made:
                continue
            created = TrainingDay(
                program_id=program.id,
                program_name=program.name,
                date=day,
                status=TrainingDayStatus.OPEN,
                created_at=now,
            )
            db_session.add(created)
            db_session.flush()
            if day == today:
                events.append(_event("due", created))
        # A late day closes once its program has a training day after it, up to `day`, or once its days are up
        # (today-ahead spec §2.1.1). A day whose session is running or paused stays open (step 5 spec §3.4).
        later = aliased(TrainingDay)
        trains_again = exists().where(
            later.program_id == TrainingDay.program_id,
            later.date > TrainingDay.date,
            later.date <= day,
        )
        days_up = TrainingDay.date < day - timedelta(days=self._late_days)
        earlier = db_session.scalars(
            select(TrainingDay)
            .where(
                TrainingDay.status == TrainingDayStatus.OPEN,
                TrainingDay.date < day,
                or_(trains_again, days_up),
                ~_in_session(TrainingDay.id),
            )
            .order_by(TrainingDay.date, TrainingDay.id)
        )
        for missed in earlier:
            missed.status = TrainingDayStatus.MISSED
            missed.closed_at = now
            events.append(_event("missed", missed))
        db_session.flush()
        return events

    def reconciled_date(self) -> date:
        """Return the date the last reconcile handled; the local date now before the first reconcile."""
        with self.lock:
            # Only reached by the startup `recover()`, before the first reconcile, when no client is subscribed yet.
            return self.local_today() if self._reconciled is None else self._reconciled

    def publish_today(self) -> None:
        """Publish `today` if it changed, then the stats if they changed, as one batch, for `reconciled_date()`.

        For writes elsewhere that close or make a day (a session's finish or early start), after their commit. Not the
        clock's date: just after midnight, before a reconcile has made the new date's days, a `today` for the new date
        would show the old date's days.
        """
        with self.lock:
            self._publish_today(None, self.reconciled_date())

    def close_done(
        self, db_session: Session, day_id: int, at: datetime
    ) -> dict[str, Any] | None:
        """Close an open day as done in the caller's session (step 5 spec §3.4); return its `done` event.

        A day that is gone or no longer open is left as it is, and there is no event.
        """
        day = db_session.get(TrainingDay, day_id)
        if day is None or day.status != TrainingDayStatus.OPEN:
            return None
        day.status = TrainingDayStatus.DONE
        day.closed_at = at
        db_session.flush()
        return _event("done", day)

    def open_early(self, db_session: Session, program_id: int, day: date) -> int:
        """Make a program's day on a date after today, open, in the caller's session; return its id.

        For a session started early (today-ahead spec §2.2.4); the caller has checked the date against `upcoming_for`.
        """
        program = db_session.get_one(ProgramRow, program_id)
        row = TrainingDay(
            program_id=program_id,
            program_name=program.name,
            date=day,
            status=TrainingDayStatus.OPEN,
            created_at=self._clock.now(),
        )
        db_session.add(row)
        db_session.flush()
        return row.id

    def settle_uncounted(
        self, db_session: Session, day_id: int, today: date
    ) -> dict[str, Any] | None:
        """Settle the open day of a session that ended uncounted on the date `today`, in the caller's session.

        Today-ahead spec §2.2.6: a day dated after today was made early and is removed. A day made early whose
        date is today now (the session crossed midnight) stays as today's due day; its `due` event is returned, as
        reconcile sent none. Other days are left as they are.
        """
        day = db_session.get(TrainingDay, day_id)
        if day is None or day.status != TrainingDayStatus.OPEN:
            return None
        if day.date > today:
            db_session.delete(day)
            db_session.flush()
            return None
        if day.date == today and self.local_date(day.created_at) < day.date:
            return _event("due", day)
        return None

    def _publish_today(self, events: list[dict[str, Any]] | None, today: date) -> None:
        """Publish `events`, then `today` if it changed, then what `on_change` returns, as one batch.

        `today` and the stats are built for the date `today`. A reconcile passes the date it handled: the clock may have
        passed midnight since, and a `today` for that new date would show the old date's days.

        `today` goes out when what `/today` returns differs from what was published last. The write has committed by
        now, so an error in `on_change` (the stats) is logged and swallowed: it never turns the write into a failure,
        and the rest of the batch still goes out.
        """
        batch = list(events or [])
        view = self._build_view(today)
        if view != self._published:
            self._published = view
            batch.append({"type": "today", "data": view.model_dump(mode="json")})
        try:
            batch += self.on_change(today)
        except Exception:
            _LOGGER.exception("Updating the stats after a change failed")
        if batch:
            self._publish(batch)

    def _build_view(self, today: date) -> TodayView:
        """Build the body of `GET /today` for `today` (spec §3.5), without reconciling.

        `open` is sorted by date, then program name ignoring case, then id. It leaves out a day dated after today, made
        by a session started early (today-ahead spec §2.2.4).
        """
        with session(self._engine) as db_session:
            rows = db_session.execute(
                select(TrainingDay, ProgramRow)
                .join(ProgramRow, TrainingDay.program_id == ProgramRow.id)
                .where(
                    TrainingDay.status == TrainingDayStatus.OPEN,
                    TrainingDay.date <= today,
                )
            ).all()
            active = list(
                db_session.scalars(select(ProgramRow).where(ProgramRow.active))
            )
            week = self._week(db_session, active, today)
            upcoming = [
                entry
                for program in active
                if (entry := self.upcoming_for(db_session, program.id, today))
                is not None
            ]
            next_training = self._next(db_session, active, today)
        open_days = [self._open_day(day, program, today) for day, program in rows]
        open_days.sort(key=lambda day: (day.date, day.program_name.casefold(), day.id))
        upcoming.sort(key=lambda entry: (entry.date, entry.program_name.casefold()))
        return TodayView(
            date=today,
            open=open_days,
            next=next_training,
            week=week,
            upcoming=upcoming,
        )

    @staticmethod
    def upcoming_for(
        db_session: Session, program_id: int, today: date
    ) -> UpcomingTraining | None:
        """Return a program's next training after today in the caller's session (today-ahead spec §2.2.1, §2.2.2).

        That is the first date in the next 14 days on which the program trains and has no done, missed or skipped
        day; an open day there doesn't move it. An open day dated after today (made by a session started early) pins
        it to that date, even if the program's weekdays changed since (§2.2.4, §2.2.7). `startable` is false while the
        program has an open day of any date, or a done day dated today or later. None for an unknown or inactive
        program. Neither locks nor reconciles.
        """
        program = db_session.get(ProgramRow, program_id)
        if program is None or not program.active:
            return None
        days = db_session.execute(
            select(TrainingDay.date, TrainingDay.status).where(
                TrainingDay.program_id == program_id,
                or_(
                    TrainingDay.status == TrainingDayStatus.OPEN,
                    TrainingDay.date >= today,
                ),
            )
        ).all()
        closed = {day for day, status in days if status != TrainingDayStatus.OPEN}
        startable = not any(
            status == TrainingDayStatus.OPEN
            or (status == TrainingDayStatus.DONE and day >= today)
            for day, status in days
        )
        early = [
            day
            for day, status in days
            if status == TrainingDayStatus.OPEN and day > today
        ]
        candidates = (
            today + timedelta(days=offset) for offset in range(1, _DAYS_AHEAD + 1)
        )
        found = (
            min(early)
            if early
            else next(
                (
                    day
                    for day in candidates
                    if _trains_on(program, day) and day not in closed
                ),
                None,
            )
        )
        if found is None:
            return None
        document = ProgramDocument.model_validate(program.document)
        return UpcomingTraining(
            program_id=program.id,
            program_name=program.name,
            date=found,
            station_count=len(document.stations),
            rounds=document.rounds,
            total_minutes=total_minutes(document),
            startable=startable,
        )

    @staticmethod
    def _week(db_session: Session, active: list[ProgramRow], today: date) -> Week:
        """Return the week of `today`, Monday to Sunday (UI refresh spec §3.1).

        `planned` is the training days dated in the week, any status, plus the days the active programs will still
        make from tomorrow to Sunday; `done` is the week's days with status done.
        """
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
        days = list(
            db_session.execute(
                select(
                    TrainingDay.program_id, TrainingDay.date, TrainingDay.status
                ).where(TrainingDay.date >= monday, TrainingDay.date <= sunday)
            ).all()
        )
        made = {(program_id, day) for program_id, day, _ in days}
        planned = len(days)
        day = today + timedelta(days=1)
        while day <= sunday:
            planned += sum(
                1
                for program in active
                if _trains_on(program, day) and (program.id, day) not in made
            )
            day += timedelta(days=1)
        done = sum(1 for _, _, status in days if status == TrainingDayStatus.DONE)
        return Week(done=done, planned=planned)

    @staticmethod
    def _open_day(day: TrainingDay, program: ProgramRow, today: date) -> OpenDay:
        """Return an open day with the program's fields as it is now."""
        document = ProgramDocument.model_validate(program.document)
        return OpenDay(
            id=day.id,
            program_id=program.id,
            program_name=day.program_name,
            date=day.date,
            state="due" if day.date >= today else "late",
            station_count=len(document.stations),
            rounds=document.rounds,
            total_minutes=total_minutes(document),
        )

    @staticmethod
    def _next(
        db_session: Session, active: list[ProgramRow], today: date
    ) -> NextTraining | None:
        """Return the first date after today on which an active program trains and isn't done there yet.

        It looks 14 days ahead (today-ahead spec §2.2.9), so it is null only when no program is active.
        """
        last = today + timedelta(days=_DAYS_AHEAD)
        done = {
            (program_id, day)
            for program_id, day in db_session.execute(
                select(TrainingDay.program_id, TrainingDay.date).where(
                    TrainingDay.status == TrainingDayStatus.DONE,
                    TrainingDay.date > today,
                    TrainingDay.date <= last,
                )
            )
        }
        for offset in range(1, _DAYS_AHEAD + 1):
            day = today + timedelta(days=offset)
            names = sorted(
                (
                    p.name
                    for p in active
                    if _trains_on(p, day) and (p.id, day) not in done
                ),
                key=str.casefold,
            )
            if names:
                return NextTraining(date=day, programs=names)
        return None

    def today_view(self) -> TodayView:
        """Reconcile, then return the body of `GET /today`."""
        with self.lock:
            today = self.local_today()
            self.reconcile(today)
            return self._build_view(today)

    def in_range(self, start: date, end: date) -> list[TrainingDayOut]:
        """Reconcile, then return the training days from `start` to `end`, both included, by date, then name ignoring case."""
        with self.lock:
            self.reconcile(self.local_today())
            with session(self._engine) as db_session:
                days = list(
                    db_session.scalars(
                        select(TrainingDay).where(
                            TrainingDay.date >= start, TrainingDay.date <= end
                        )
                    )
                )
        days.sort(key=lambda day: (day.date, day.program_name.casefold(), day.id))
        return [_out(day) for day in days]

    def skip(self, day_id: int, client: str) -> TrainingDayOut:
        """Close an open day as skipped and log it (spec §3.4).

        Raise `NotFound`, or `Conflict` for a closed day or one whose session is running or paused.
        """
        with self.lock:
            today = self.reconcile_now()
            with session(self._engine) as db_session:
                day = db_session.get(TrainingDay, day_id)
                if day is None:
                    raise NotFound(f"Training day {day_id} not found")
                if day.status != TrainingDayStatus.OPEN:
                    raise Conflict(
                        f"Training day {day_id} is {day.status.value}, not open"
                    )
                if db_session.scalar(select(_in_session(day_id))):
                    raise Conflict(f"A session for training day {day_id} is running")
                day.status = TrainingDayStatus.SKIPPED
                day.closed_at = self._clock.now()
                changes.record(
                    db_session,
                    client=client,
                    action="training_day.skipped",
                    target=f"training_day:{day_id}",
                    summary=f"Skipped {day.program_name} ({day.date.isoformat()})",
                )
                db_session.flush()
                event = _event("skipped", day)
                out = _out(day)
            self._publish_today([event], today)
            return out

    def upsert_open(self, program_id: int, day: date) -> TrainingDayOut:
        """Dev only: make an open day for a program on today or a past date, or reopen the one there is.

        Raise `NotFound` for an unknown program, and `Invalid` for a date after today: an open day there would show
        as due (today-ahead spec §2.1.7).
        """
        with self.lock:
            today = self.reconcile_now()
            if day > today:
                raise Invalid(
                    f"{day.isoformat()} is after today; an open day there would show as due"
                )
            with session(self._engine) as db_session:
                program = db_session.get(ProgramRow, program_id)
                if program is None:
                    raise NotFound(f"Program {program_id} not found")
                row = db_session.scalar(
                    select(TrainingDay).where(
                        TrainingDay.program_id == program_id, TrainingDay.date == day
                    )
                )
                if row is None:
                    row = TrainingDay(
                        program_id=program_id,
                        program_name=program.name,
                        date=day,
                        created_at=self._clock.now(),
                    )
                    db_session.add(row)
                row.status = TrainingDayStatus.OPEN
                row.closed_at = None
                db_session.flush()
                out = _out(row)
            self._publish_today(None, today)
            return out

    def delete_date(self, day: date) -> None:
        """Dev only: remove every training day of `day`, open or closed."""
        with self.lock:
            today = self.reconcile_now()
            with session(self._engine) as db_session:
                db_session.execute(delete(TrainingDay).where(TrainingDay.date == day))
            self._publish_today(None, today)

    def on_program_written(
        self, db_session: Session, before: ProgramRow | None, after: ProgramRow | None
    ) -> None:
        """Keep open days in step with a program write, inside its session and before its commit (spec §3.3).

        Switching off and deleting remove the program's open days; a rename renames them. Closed days stay as they
        are; on delete the database sets their `program_id` to null.
        """
        with self.lock:
            if before is None:
                return
            open_days = (
                TrainingDay.program_id == before.id,
                TrainingDay.status == TrainingDayStatus.OPEN,
            )
            if after is None or not after.active:
                db_session.execute(delete(TrainingDay).where(*open_days))
            elif after.name != before.name:
                db_session.execute(
                    update(TrainingDay)
                    .where(*open_days)
                    .values(program_name=after.name)
                )
