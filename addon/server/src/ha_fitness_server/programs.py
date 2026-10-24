"""The training programs (spec §5): stored as one document each, stations resolved to exercise ids."""

import builtins
from datetime import UTC, datetime
import json
from typing import TYPE_CHECKING, Any

from sqlalchemy import Engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import changes
from .db import session
from .errors import Conflict, Invalid, NotFound
from .library.service import Library
from .models import ACTIVE_SESSION_STATUSES, Program as ProgramRow, WorkoutSession
from .schemas import ProgramDocument, ProgramOut, ProgramSummary, StationIn

if TYPE_CHECKING:
    from .training_days import TrainingDays

_NAME_KEY_CLASH = "UNIQUE constraint failed: programs.name_key"
# Fields an update summary names without their values.
_NAMED_ONLY = frozenset({"stations", "music", "weekdays"})


def total_seconds(document: ProgramDocument) -> int:
    """Return the length of a program: S * R * (W + switch) + (R - 1) * round rest (design §3.1)."""
    stations = len(document.stations)
    rounds = document.rounds
    per_station = document.work_seconds + document.switch_seconds
    return stations * rounds * per_station + (rounds - 1) * document.round_rest_seconds


def total_minutes(document: ProgramDocument) -> int:
    """Return the length of a program in whole minutes, a half minute rounded up."""
    return (total_seconds(document) + 30) // 60


def _change(field: str, old: Any, new: Any) -> str:
    """Describe one changed top-level field: `rounds 5 → 4`, or only the name for lists and music."""
    if field in _NAMED_ONLY:
        return field
    return f"{field} {_value(old)} → {_value(new)}"


def _value(value: Any) -> str:
    """Show a field value in a summary: strings as they are, other values as JSON."""
    return value if isinstance(value, str) else json.dumps(value)


def _update_summary(name: str, old: dict[str, Any], new: dict[str, Any]) -> str:
    """Return `Updated program <name>`, then the top-level fields that differ.

    The fields shown with values come first, then the ones only named, each in document order (spec §6's
    `rounds 5 → 4, stations`).
    """
    differ = [field for field, value in new.items() if old.get(field) != value]
    differ.sort(key=lambda field: field in _NAMED_ONLY)
    changed = [_change(field, old.get(field), new[field]) for field in differ]
    summary = f"Updated program {name}"
    return f"{summary}: {', '.join(changed)}" if changed else summary


class Programs:
    """Lists, stores and changes programs; the library resolves and names the stations.

    Each write runs under the training days' lock. They reconcile before it, so a write just after midnight acts on
    the new date; their hook runs in the write's session before the commit; and they reconcile after it (step 4 spec
    §3.3).
    """

    def __init__(
        self, engine: Engine, library: Library, training_days: TrainingDays
    ) -> None:
        """Use `engine` for the programs, `library` for their exercises and `training_days` to keep days in step."""
        self._engine = engine
        self._library = library
        self._training_days = training_days

    def _out(self, row: ProgramRow) -> ProgramOut:
        """Turn a row into a `ProgramOut`, with the station names looked up now.

        A stored exercise that has left the library is named by its id and adds no equipment.
        """
        document = ProgramDocument.model_validate(row.document)
        names: builtins.list[str] = []
        equipment: dict[str, None] = {}
        for station in document.stations:
            try:
                exercise = self._library.get(station.exercise)
            except NotFound:
                names.append(station.exercise)
                continue
            names.append(exercise.name)
            if exercise.equipment and exercise.equipment.lower() != "body weight":
                equipment.setdefault(exercise.equipment)
        return ProgramOut(
            id=row.id,
            program=document,
            station_names=names,
            equipment=list(equipment),
            total_seconds=total_seconds(document),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _resolved(self, document: ProgramDocument) -> dict[str, Any]:
        """Return the document to store, each station's exercise resolved to its id; raise `Invalid` if one can't be."""
        stations = [
            StationIn(exercise=self._library.resolve(station.exercise, index).id)
            for index, station in enumerate(document.stations, start=1)
        ]
        return document.model_copy(update={"stations": stations}).model_dump(
            mode="json"
        )

    def list(self) -> builtins.list[ProgramOut]:
        """Return every program, by name, ignoring case."""
        with session(self._engine) as db_session:
            rows = db_session.scalars(select(ProgramRow).order_by(ProgramRow.name_key))
            return [self._out(row) for row in rows]

    def summaries(self) -> builtins.list[ProgramSummary]:
        """Return every program as a summary, by name; `total_minutes` is rounded, a half minute up."""
        return [
            ProgramSummary(
                id=out.id,
                name=out.program.name,
                active=out.program.active,
                weekdays=out.program.weekdays,
                station_count=len(out.program.stations),
                rounds=out.program.rounds,
                total_minutes=total_minutes(out.program),
            )
            for out in self.list()
        ]

    def get(self, program_id: int) -> ProgramOut:
        """Return one program; raise `NotFound` if there is none."""
        with session(self._engine) as db_session:
            return self._out(self._row(db_session, program_id))

    @staticmethod
    def _row(db_session: Session, program_id: int) -> ProgramRow:
        """Return the program's row; raise `NotFound` if there is none."""
        row = db_session.get(ProgramRow, program_id)
        if row is None:
            raise NotFound(f"Program {program_id} not found")
        return row

    @staticmethod
    def _snapshot(row: ProgramRow) -> ProgramRow:
        """Return a detached copy of a row as it is now, never added to a session, for the hook's `before`."""
        return ProgramRow(
            id=row.id,
            name=row.name,
            name_key=row.name_key,
            active=row.active,
            document=row.document,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    @staticmethod
    def _refuse_in_session(db_session: Session, program_id: int) -> None:
        """Raise `Conflict` when a running or paused session, extra or not, is of this program (step 5 spec §3.4).

        The program id is in the session's frozen plan.
        """
        active = db_session.scalars(
            select(WorkoutSession).where(
                WorkoutSession.status.in_(ACTIVE_SESSION_STATUSES)
            )
        )
        if any(row.plan["program_id"] == program_id for row in active):
            raise Conflict("A session for this program is running")

    @staticmethod
    def _taken(name: str) -> Conflict:
        """Return the error for a name already in use."""
        return Conflict(f"Program name '{name}' is taken")

    def create(self, document: ProgramDocument, client: str) -> ProgramOut:
        """Store a new program and log it; raise `Invalid` for a station that can't be resolved, `Conflict` for a taken name."""
        stored = self._resolved(document)
        now = datetime.now(UTC)
        with self._training_days.lock:
            self._training_days.reconcile_now()
            out = self._create(document, stored, now, client)
            self._training_days.reconcile_now()
            return out

    def _create(
        self,
        document: ProgramDocument,
        stored: dict[str, Any],
        now: datetime,
        client: str,
    ) -> ProgramOut:
        """Store and log a new program, in one transaction."""
        try:
            with session(self._engine) as db_session:
                row = ProgramRow(
                    name=document.name,
                    name_key=document.name.casefold(),
                    active=document.active,
                    document=stored,
                    created_at=now,
                    updated_at=now,
                )
                db_session.add(row)
                db_session.flush()
                changes.record(
                    db_session,
                    client=client,
                    action="program.created",
                    target=f"program:{row.id}",
                    summary=f"Created program {document.name}",
                )
                self._training_days.on_program_written(db_session, None, row)
                return self._out(row)
        except IntegrityError as error:
            if _NAME_KEY_CLASH not in str(error.orig):
                raise
            raise self._taken(document.name) from error

    def replace(
        self, program_id: int, document: ProgramDocument, client: str
    ) -> ProgramOut:
        """Replace a program's whole document and log the fields that changed.

        Raise `NotFound`, `Invalid` for a station that can't be resolved, or `Conflict` for a name another program has
        or for `active: false` while a session of the program is active.
        """
        stored = self._resolved(document)
        with self._training_days.lock:
            self._training_days.reconcile_now()
            out = self._replace(program_id, document, stored, client)
            self._training_days.reconcile_now()
            return out

    def _replace(
        self,
        program_id: int,
        document: ProgramDocument,
        stored: dict[str, Any],
        client: str,
    ) -> ProgramOut:
        """Replace and log a program's document, in one transaction."""
        try:
            with session(self._engine) as db_session:
                row = self._row(db_session, program_id)
                if not document.active:
                    self._refuse_in_session(db_session, program_id)
                before = self._snapshot(row)
                # The log row and the update share the write's transaction, so a name clash at the flush rolls back both.
                changes.record(
                    db_session,
                    client=client,
                    action="program.updated",
                    target=f"program:{program_id}",
                    summary=_update_summary(document.name, row.document, stored),
                )
                row.name = document.name
                row.name_key = document.name.casefold()
                row.active = document.active
                row.document = stored
                row.updated_at = datetime.now(UTC)
                db_session.flush()
                self._training_days.on_program_written(db_session, before, row)
                return self._out(row)
        except IntegrityError as error:
            if _NAME_KEY_CLASH not in str(error.orig):
                raise
            raise self._taken(document.name) from error

    def set_active(self, program_id: int, active: bool, client: str) -> ProgramOut:
        """Switch a program on or off.

        Raise `NotFound`, `Invalid` when switching on one without weekdays, or `Conflict` when switching off one whose
        session is active.
        """
        with self._training_days.lock:
            self._training_days.reconcile_now()
            out = self._set_active(program_id, active, client)
            self._training_days.reconcile_now()
            return out

    def _set_active(self, program_id: int, active: bool, client: str) -> ProgramOut:
        """Switch and log a program, in one transaction."""
        with session(self._engine) as db_session:
            row = self._row(db_session, program_id)
            if not active:
                self._refuse_in_session(db_session, program_id)
            before = self._snapshot(row)
            if active and not row.document["weekdays"]:
                raise Invalid(
                    f"Program {program_id} has no weekdays; give it one before switching it on"
                )
            # A new dict, as the JSON column doesn't track changes inside the old one.
            row.document = {**row.document, "active": active}
            row.active = active
            row.updated_at = datetime.now(UTC)
            changes.record(
                db_session,
                client=client,
                action="program.activated" if active else "program.deactivated",
                target=f"program:{program_id}",
                summary=f"{'Activated' if active else 'Deactivated'} program {row.name}",
            )
            self._training_days.on_program_written(db_session, before, row)
            return self._out(row)

    def delete(self, program_id: int, client: str) -> None:
        """Delete a program for good and log it; raise `NotFound`, or `Conflict` while a session of it is active."""
        with self._training_days.lock:
            self._training_days.reconcile_now()
            self._delete(program_id, client)
            self._training_days.reconcile_now()

    def _delete(self, program_id: int, client: str) -> None:
        """Delete and log a program, in one transaction; its open days go first."""
        with session(self._engine) as db_session:
            row = self._row(db_session, program_id)
            self._refuse_in_session(db_session, program_id)
            self._training_days.on_program_written(
                db_session, self._snapshot(row), None
            )
            db_session.delete(row)
            changes.record(
                db_session,
                client=client,
                action="program.deleted",
                target=f"program:{program_id}",
                summary=f"Deleted program {row.name}",
            )
