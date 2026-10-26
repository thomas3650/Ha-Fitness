"""The database tables (spec §10).

Names are compared through `name_key`, the `str.casefold()` of the name. Times are stored in UTC and come back
timezone-aware.
"""

import datetime as dt
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import (
    JSON,
    Date,
    DateTime,
    Dialect,
    Enum,
    Float,
    ForeignKey,
    MetaData,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from .schemas import CreatedBy

# Named constraints and indexes, so later SQLite batch migrations can refer to them.
NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class UtcDateTime(TypeDecorator[datetime]):
    """A datetime stored in UTC; SQLite would otherwise return naive values."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Store an aware datetime as naive UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("naive datetime")
        return value.astimezone(UTC).replace(tzinfo=None)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Return the stored UTC value as an aware datetime."""
        if value is None:
            return None
        return value.replace(tzinfo=UTC)


class Base(DeclarativeBase):
    """The base of all tables."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Program(Base):
    """A training program; `document` is the program document of spec §5.1."""

    __tablename__ = "programs"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    name_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    active: Mapped[bool]
    document: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # `claude` (an MCP write) or `you` (any other); null for a program from before migration 0006 with no log row.
    created_by: Mapped[CreatedBy | None] = mapped_column(String(16))


class Person(Base):
    """A person who trains, linked to an HA person; ids are never reused, so history stays with its person."""

    __tablename__ = "people"
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    person_entity_id: Mapped[str] = mapped_column(String, unique=True)
    position: Mapped[int]
    # Null for the people from before migration 0004: they count from the start (stats spec §3.1).
    added_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SetupRow(Base):
    """The household setup's one row (website spec §2.4); `document` is a `Setup`."""

    __tablename__ = "setup"

    id: Mapped[int] = mapped_column(primary_key=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)


class CustomExercise(Base):
    """An exercise added through chat; its id is `custom-<number>`."""

    __tablename__ = "custom_exercises"

    number: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    name_key: Mapped[str] = mapped_column(String, unique=True, index=True)
    document: Mapped[dict[str, Any]] = mapped_column(JSON)


class ChangeLogEntry(Base):
    """One write through REST or MCP; rows are never changed."""

    __tablename__ = "change_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(UtcDateTime)
    client: Mapped[str] = mapped_column(String)
    action: Mapped[str] = mapped_column(String)
    target: Mapped[str] = mapped_column(String)
    summary: Mapped[str] = mapped_column(String)


class TrainingDayStatus(StrEnum):
    """The stored status of a training day (spec §3.1); "due" and "late" are derived, never stored."""

    OPEN = "open"
    DONE = "done"
    MISSED = "missed"
    SKIPPED = "skipped"


class TrainingDay(Base):
    """One program on one local date; `program_name` is a copy, so history keeps the name after a delete."""

    __tablename__ = "training_days"
    # AUTOINCREMENT: an id is never reused after a delete, since the card and the service skip by id.
    __table_args__ = (
        UniqueConstraint("program_id", "date"),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    program_id: Mapped[int | None] = mapped_column(
        ForeignKey("programs.id", ondelete="SET NULL")
    )
    program_name: Mapped[str] = mapped_column(String)
    date: Mapped[dt.date] = mapped_column(Date, index=True)
    status: Mapped[TrainingDayStatus] = mapped_column(
        Enum(
            TrainingDayStatus,
            native_enum=False,
            length=16,
            values_callable=lambda members: [member.value for member in members],
        )
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)


class SchedulerState(Base):
    """The scheduler's one row: `last_date` is the last fully handled local date, null until the first run."""

    __tablename__ = "scheduler_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    last_date: Mapped[dt.date | None] = mapped_column(Date)


class SessionStatus(StrEnum):
    """The status of a session (step 5 spec §3.2): `running` or `paused` while active, then `completed` or `ended`."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ENDED = "ended"


# "A session is active": running or paused. One session at a time can be.
ACTIVE_SESSION_STATUSES = (SessionStatus.RUNNING, SessionStatus.PAUSED)


class WorkoutSession(Base):
    """One workout (step 5 spec §3.2); `plan` is frozen at the start, so later edits change nothing here.

    Called `WorkoutSession` so it never clashes with SQLAlchemy's `Session`.
    """

    __tablename__ = "sessions"
    # AUTOINCREMENT: an id is never reused, since history and the cards refer to sessions by id.
    __table_args__ = {"sqlite_autoincrement": True}

    id: Mapped[int] = mapped_column(primary_key=True)
    plan: Mapped[dict[str, Any]] = mapped_column(JSON)
    training_day_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_days.id", ondelete="SET NULL")
    )
    status: Mapped[SessionStatus] = mapped_column(
        Enum(
            SessionStatus,
            native_enum=False,
            length=16,
            values_callable=lambda members: [member.value for member in members],
        ),
        index=True,
    )
    counted: Mapped[bool]
    phase_index: Mapped[int]
    phase_started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    paused_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    paused_seconds: Mapped[float] = mapped_column(Float)
    last_tick_at: Mapped[datetime] = mapped_column(UtcDateTime)
    started_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    rounds_completed: Mapped[int]
    revision: Mapped[int]
    # How the workout felt (`too_easy`, `just_right`, `too_hard`); null until rated (migration 0005).
    feeling: Mapped[str | None] = mapped_column(String(16))


class SessionParticipant(Base):
    """One person in a session, in order; no foreign key to `people`, so history keeps a removed person's name."""

    __tablename__ = "session_participants"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("sessions.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(primary_key=True)
    person_id: Mapped[int]
    name: Mapped[str] = mapped_column(String)


class AppState(Base):
    """The app's one row: `counting_from` is the local date of the first counted session, null until then."""

    __tablename__ = "app_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    counting_from: Mapped[dt.date | None] = mapped_column(Date)
