"""The database tables (spec §10).

Names are compared through `name_key`, the `str.casefold()` of the name. Times are stored in UTC and come back
timezone-aware.
"""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Dialect, MetaData, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

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


class Person(Base):
    """A person who trains, linked to an HA person."""

    __tablename__ = "people"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String)
    person_entity_id: Mapped[str] = mapped_column(String, unique=True)
    position: Mapped[int]


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
