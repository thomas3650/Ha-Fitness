"""The change log: one row per successful write (spec §6)."""

from datetime import datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .db import session as open_session
from .models import ChangeLogEntry
from .schemas import ChangeEntry

# A change-log client (`rest:<User-Agent>`, `mcp:<clientInfo name>`) is cut to this many characters (spec §6).
MAX_CLIENT_LENGTH = 100


def record(
    db_session: Session,
    *,
    at: datetime,
    client: str,
    action: str,
    target: str,
    summary: str,
) -> None:
    """Add a row stamped `at` in the write's own session, so a write that fails logs nothing.

    `at` is the write's own read of the injected clock, the instant it stamps everything else with.
    """
    db_session.add(
        ChangeLogEntry(
            at=at,
            client=client,
            action=action,
            target=target,
            summary=summary,
        )
    )


def recent(engine: Engine, limit: int = 20) -> list[ChangeEntry]:
    """Return the newest `limit` rows, newest first."""
    with open_session(engine) as db_session:
        rows = db_session.scalars(
            select(ChangeLogEntry).order_by(ChangeLogEntry.id.desc()).limit(limit)
        )
        return [
            ChangeEntry(
                at=row.at,
                client=row.client,
                action=row.action,
                target=row.target,
                summary=row.summary,
            )
            for row in rows
        ]
