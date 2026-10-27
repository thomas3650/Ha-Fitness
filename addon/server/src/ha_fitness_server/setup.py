"""The household setup (website spec §2.4, D63): equipment, favourite playlists and the default speaker."""

from sqlalchemy import Engine

from . import changes
from .clock import Clock
from .db import session
from .errors import Invalid
from .library.service import Library
from .models import SetupRow
from .schemas import Setup

# The setup's one row.
_ROW_ID = 1


class SetupService:
    """Reads and writes the setup, one JSON document; the library says which equipment there is."""

    def __init__(self, engine: Engine, library: Library, clock: Clock) -> None:
        """Use `engine` for the setup, `library` to check its equipment and `clock` to stamp the change log."""
        self._engine = engine
        self._library = library
        self._clock = clock

    def get(self) -> Setup:
        """Return the setup; the defaults while none is stored."""
        with session(self._engine) as db_session:
            row = db_session.get(SetupRow, _ROW_ID)
            return Setup() if row is None else Setup.model_validate(row.document)

    def set(self, setup: Setup, client: str) -> Setup:
        """Store the setup and log it; raise `Invalid` for equipment no library or custom exercise has."""
        known = set(self._library.facets()["equipment"])
        unknown = [value for value in setup.equipment if value not in known]
        if unknown:
            raise Invalid(
                f"Unknown equipment: {', '.join(unknown)}",
                code="equipment_unknown",
                field="equipment",
            )
        document = setup.model_dump(mode="json")
        with session(self._engine) as db_session:
            # A merge stores the row whether or not migration 0006's is there.
            db_session.merge(SetupRow(id=_ROW_ID, document=document))
            changes.record(
                db_session,
                at=self._clock.now(),
                client=client,
                action="setup.updated",
                target="setup",
                summary="Updated the setup",
            )
        return setup
