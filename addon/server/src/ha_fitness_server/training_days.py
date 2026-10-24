"""Training days and the scheduler (step 4 spec §3.3): which program asks to be trained on which local date."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
import logging
import threading
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Engine, delete, exists, select, update
from sqlalchemy.orm import Session

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
    Week,
)

_LOGGER = logging.getLogger(__name__)

type Publish = Callable[[dict[str, Any]], None]

# The scheduler's one row in `scheduler_state` (migration 0002).
_STATE_ID = 1


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
    """

    def __init__(
        self, engine: Engine, clock: Clock, timezone: ZoneInfo, publish: Publish
    ) -> None:
        """Use `engine`, the local dates of `timezone` at `clock`'s time, and `publish` for push messages."""
        self._engine = engine
        self._clock = clock
        self._timezone = timezone
        self._publish = publish
        self.lock = threading.RLock()
        self._published: TodayView | None = None
        # Called after every `today` check, changed or not: a people change leaves `today` alone but not the stats.
        self.on_change: Callable[[], None] = lambda: None

    def local_date(self, moment: datetime) -> date:
        """Return the local date of an aware `moment`."""
        return moment.astimezone(self._timezone).date()

    def local_today(self) -> date:
        """Return the local date now."""
        return self.local_date(self._clock.now())

    def reconcile_now(self) -> None:
        """Reconcile up to and including the local date now."""
        with self.lock:
            self.reconcile(self.local_today())

    def reconcile(self, today: date) -> None:
        """Handle each date from the day after the last handled one up to today, and today again (spec §3.3).

        The first run starts at today. The events go out after the commit, then `today` if it changed.
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
            for message in events:
                self._publish(message)
            self._publish_today()

    def _handle(
        self, db_session: Session, programs: list[ProgramRow], day: date, today: date
    ) -> list[dict[str, Any]]:
        """Apply rules 1 and 2 of spec §3.3 to one date; return the events, `due` only for a day made for today."""
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
        if not db_session.scalar(select(exists().where(TrainingDay.date == day))):
            return events
        # A day whose session is running or paused stays open (step 5 spec §3.4).
        earlier = db_session.scalars(
            select(TrainingDay)
            .where(
                TrainingDay.status == TrainingDayStatus.OPEN,
                TrainingDay.date < day,
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

    def publish_today(self) -> None:
        """Publish `today` if it changed; for writes elsewhere that close a day, after their commit."""
        with self.lock:
            self._publish_today()

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

    def _publish_today(self) -> None:
        """Publish `today` when what `/today` returns differs from what was published last, then call `on_change`.

        The write has committed by now, so an error in `on_change` (the stats) is logged and swallowed: it never
        turns the write into a failure.
        """
        view = self._build_view(self.local_today())
        if view != self._published:
            self._published = view
            self._publish({"type": "today", "data": view.model_dump(mode="json")})
        try:
            self.on_change()
        except Exception:
            _LOGGER.exception("Updating the stats after a change failed")

    def _build_view(self, today: date) -> TodayView:
        """Build the body of `GET /today` for `today` (spec §3.5), without reconciling."""
        with session(self._engine) as db_session:
            rows = db_session.execute(
                select(TrainingDay, ProgramRow)
                .join(ProgramRow, TrainingDay.program_id == ProgramRow.id)
                .where(TrainingDay.status == TrainingDayStatus.OPEN)
            ).all()
            active = list(
                db_session.scalars(select(ProgramRow).where(ProgramRow.active))
            )
            week = self._week(db_session, active, today)
        open_days = [self._open_day(day, program, today) for day, program in rows]
        open_days.sort(key=lambda day: (day.program_name.casefold(), day.id))
        return TodayView(
            date=today, open=open_days, next=self._next(active, today), week=week
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
    def _next(active: list[ProgramRow], today: date) -> NextTraining | None:
        """Return the first date after today on which an active program trains; null when none is active."""
        for offset in range(1, 8):
            day = today + timedelta(days=offset)
            names = sorted(
                (p.name for p in active if _trains_on(p, day)), key=str.casefold
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
            self.reconcile_now()
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
            self._publish(event)
            self._publish_today()
            return out

    def upsert_open(self, program_id: int, day: date) -> TrainingDayOut:
        """Dev only: make an open day for a program on today or a past date, or reopen the one there is.

        Raise `NotFound` for an unknown program, and `Invalid` for a date after today: an open day there would break
        "open days share one date".
        """
        with self.lock:
            self.reconcile_now()
            if day > self.local_today():
                raise Invalid(f"{day.isoformat()} is after today")
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
            self._publish_today()
            return out

    def delete_date(self, day: date) -> None:
        """Dev only: remove every training day of `day`, open or closed."""
        with self.lock:
            self.reconcile_now()
            with session(self._engine) as db_session:
                db_session.execute(delete(TrainingDay).where(TrainingDay.date == day))
            self._publish_today()

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
