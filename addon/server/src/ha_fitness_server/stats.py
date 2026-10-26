"""The stats per person (stats spec §3), computed from the training days, the sessions and their participants.

Stats are never stored. A household has at most a few hundred days and sessions a year, so everything is computed
from the logs on each call.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
import logging
from typing import Any

from sqlalchemy import Engine, select

from .db import session
from .errors import Unavailable
from .models import (
    AppState,
    Person as PersonRow,
    SessionParticipant,
    TrainingDay,
    TrainingDayStatus,
    WorkoutSession,
)
from .schemas import PersonStats, Stats, Totals
from .sessions import Sessions, time_trained
from .training_days import TrainingDays

_LOGGER = logging.getLogger(__name__)

# The app's one row in `app_state` (migration 0003).
_APP_STATE_ID = 1


@dataclass
class _Counted:
    """A counted session: its day, whether it is an extra session, the local date it started, its time and people."""

    training_day_id: int | None
    started: date
    seconds: int
    people: set[int] = field(default_factory=set)
    extra: bool = False


@dataclass
class _Tally:
    """Totals while counting."""

    done: int = 0
    extra: int = 0
    missed: int = 0
    skipped: int = 0
    time_trained: int = 0

    def add(self, outcome: str) -> None:
        """Count one outcome of a day: `done`, `missed` or `skipped`."""
        if outcome == "done":
            self.done += 1
        elif outcome == "skipped":
            self.skipped += 1
        else:
            self.missed += 1

    def out(self) -> Totals:
        """Return the totals as the schema."""
        return Totals(
            done=self.done,
            extra=self.extra,
            missed=self.missed,
            skipped=self.skipped,
            time_trained=self.time_trained,
        )


@dataclass
class _Logs:
    """What the stats are computed from, read in one transaction."""

    counting_from: date | None
    today: date
    days: list[TrainingDay]
    sessions: list[_Counted]
    people: list[PersonRow]


def _streak(outcomes: dict[date, list[str]]) -> int:
    """Count the dates, newest first, on which every counted day was done, up to the first that wasn't (§3.2)."""
    streak = 0
    for day in sorted(outcomes, reverse=True):
        if any(outcome != "done" for outcome in outcomes[day]):
            break
        streak += 1
    return streak


class StatsService:
    """Computes `Stats` (stats spec §3) under the training days' lock; the training days publish them on a change (§4)."""

    def __init__(
        self, engine: Engine, training_days: TrainingDays, sessions: Sessions
    ) -> None:
        """Use `engine`, the training days (their lock and local dates) and the sessions (for the tick)."""
        self._engine = engine
        self._training_days = training_days
        self._sessions = sessions
        self._published: Stats | None = None

    def messages_if_changed(self, today: date) -> list[dict[str, Any]]:
        """Return a `stats` message for the date `today` when they differ from the last ones published, else none.

        What it returns counts as published. The training days call it after each change with the date of the `today`
        they built, and publish what it returns in their batch, after `today`. It is the one memory of what was
        published. The connect snapshot (`view()`) leaves it alone, except that any failed computation forgets it: a
        client that connected during the failure got no `stats`, so the first good computation after it is published
        even when the numbers are the same. An error is raised for the caller to log.
        """
        with self._training_days.lock:
            try:
                stats = self.compute(today)
            except Exception:
                self._published = None
                raise
            if stats == self._published:
                return []
            self._published = stats
            return [{"type": "stats", "data": stats.model_dump(mode="json")}]

    def view(self, today: date | None = None) -> Stats:
        """Tick the session, then compute; without `today`, reconcile between: the lifespan's order (stats spec §4).

        All under the lock. `today` is the date the caller's request already reconciled (the connect snapshot): the
        stats are computed for it and nothing reconciles again, so one request uses one date (#79).

        A failed computation is logged with its exception, forgets what was published (see `messages_if_changed`) and
        is raised as `Unavailable`: REST answers 503, MCP a tool error, and the connect snapshot leaves the stats out.
        The reconcile's stats hook has usually failed and logged just before, so a failed read logs twice.
        """
        with self._training_days.lock:
            self._sessions.current()
            if today is None:
                today = self._training_days.reconcile_now()
            try:
                return self.compute(today)
            except Exception as error:
                self._published = None
                _LOGGER.exception("Computing the stats failed")
                raise Unavailable(
                    "The stats are unavailable: they can't be computed right now"
                ) from error

    def compute(self, today: date) -> Stats:
        """Compute the stats for the date `today` from what is stored now, without ticking or reconciling."""
        with self._training_days.lock:
            logs = self._read(today)
        return Stats(
            counting_from=logs.counting_from,
            month=f"{logs.today.year:04d}-{logs.today.month:02d}",
            people=[self._person(person, logs) for person in logs.people],
        )

    def _read(self, today: date) -> _Logs:
        """Read the days, the counted sessions with their participants, and the people: one query each.

        The days aren't joined to the programs: a deleted program leaves closed days with a null `program_id`. A
        session whose day is gone counts as an extra session (§3.1).
        """
        with session(self._engine) as db_session:
            counting_from = db_session.get_one(AppState, _APP_STATE_ID).counting_from
            days = list(db_session.scalars(select(TrainingDay)))
            rows = db_session.execute(
                select(WorkoutSession, SessionParticipant.person_id)
                .join(
                    SessionParticipant,
                    SessionParticipant.session_id == WorkoutSession.id,
                )
                .where(WorkoutSession.counted)
            ).all()
            people = list(
                db_session.scalars(select(PersonRow).order_by(PersonRow.position))
            )
        day_ids = {day.id for day in days}
        counted: dict[int, _Counted] = {}
        for row, person_id in rows:
            entry = counted.get(row.id)
            if entry is None:
                # A counted session has trained a round, so it has started and finished.
                assert row.started_at is not None
                assert row.ended_at is not None
                entry = _Counted(
                    training_day_id=row.training_day_id,
                    started=self._training_days.local_date(row.started_at),
                    seconds=time_trained(row, row.ended_at),
                    extra=row.training_day_id not in day_ids,
                )
                counted[row.id] = entry
            entry.people.add(person_id)
        return _Logs(
            counting_from=counting_from,
            today=today,
            days=days,
            sessions=list(counted.values()),
            people=people,
        )

    def _person(self, person: PersonRow, logs: _Logs) -> PersonStats:
        """Return one person's stats (§3.1 to §3.3)."""
        month = (logs.today.year, logs.today.month)
        added = (
            None
            if person.added_at is None
            else self._training_days.local_date(person.added_at)
        )
        all_time, this_month = _Tally(), _Tally()
        outcomes: dict[date, list[str]] = defaultdict(list)
        done_by: dict[int, set[int]] = defaultdict(set)
        for counted in logs.sessions:
            if not counted.extra and counted.training_day_id is not None:
                done_by[counted.training_day_id] |= counted.people
            if person.id not in counted.people:
                continue
            tallies = [all_time]
            if (counted.started.year, counted.started.month) == month:
                tallies.append(this_month)
            for tally in tallies:
                tally.time_trained += counted.seconds
                if counted.extra:
                    tally.done += 1
                    tally.extra += 1
        for day in logs.days:
            if day.status == TrainingDayStatus.OPEN:
                continue
            # Every done day counts; a missed or skipped day from `counting_from` on.
            if day.status != TrainingDayStatus.DONE and (
                logs.counting_from is None or day.date < logs.counting_from
            ):
                continue
            if day.status == TrainingDayStatus.DONE and person.id in done_by[day.id]:
                outcome = "done"
            elif day.status == TrainingDayStatus.SKIPPED:
                outcome = "skipped"
            else:
                outcome = "missed"
            # Before the date a person was added, only the days they did count for them.
            if added is not None and day.date < added and outcome != "done":
                continue
            outcomes[day.date].append(outcome)
            all_time.add(outcome)
            if (day.date.year, day.date.month) == month:
                this_month.add(outcome)
        return PersonStats(
            id=person.id,
            name=person.name,
            person_entity_id=person.person_entity_id,
            streak=_streak(outcomes),
            all_time=all_time.out(),
            this_month=this_month.out(),
        )
