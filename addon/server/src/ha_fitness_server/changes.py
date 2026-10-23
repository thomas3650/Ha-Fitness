"""The change log: one row per successful write (spec §6)."""

from datetime import UTC, datetime

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from .db import session as open_session
from .models import ChangeLogEntry
from .schemas import ChangeEntry

# A change-log client (`rest:<User-Agent>`, `mcp:<clientInfo name>`) is cut to this many characters (spec §6).
MAX_CLIENT_LENGTH = 100


def record(
    db_session: Session, *, client: str, action: str, target: str, summary: str
) -> None:
    """Add a row in the write's own session, so a write that fails logs nothing."""
    db_session.add(
        ChangeLogEntry(
            at=datetime.now(UTC),
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
