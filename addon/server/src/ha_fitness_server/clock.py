"""The clock: the one source of the current time, so tests can freeze it."""

from datetime import UTC, datetime
from typing import Protocol


class Clock(Protocol):
    """Gives the current time."""

    def now(self) -> datetime:
        """Return the current time, aware and in UTC."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        """Return the system's current time, aware and in UTC."""
        return datetime.now(UTC)
