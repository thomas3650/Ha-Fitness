"""The exercise library service: search, lookup, resolution and custom exercises (spec §3.4, §3.5).

Library exercises come from `exercises.json`, loaded once; custom exercises live in the database. Names are compared
with `str.casefold()`.
"""

import difflib
from importlib import resources
import json
import re
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.exc import IntegrityError

from ha_fitness_server import changes
from ha_fitness_server.db import session
from ha_fitness_server.errors import Conflict, Invalid, NotFound
from ha_fitness_server.models import CustomExercise
from ha_fitness_server.schemas import Exercise, ExerciseSummary, NewCustomExercise

from . import ATTRIBUTION
from .media import MediaFiles

CUSTOM_PREFIX = "custom-"
MAX_CLOSE_MATCHES = 5
CLOSE_MATCH_CUTOFF = 0.5
# Canonical custom ids only: ASCII digits, no leading zero.
_CUSTOM_ID = re.compile(rf"{CUSTOM_PREFIX}([1-9][0-9]*)", re.ASCII)
_NAME_KEY_CLASH = "UNIQUE constraint failed: custom_exercises.name_key"
_SUMMARY_FIELDS = set(ExerciseSummary.model_fields)


def _load_records() -> list[dict[str, Any]]:
    """Read the built-in exercise records from the package."""
    text = (
        resources.files("ha_fitness_server.library")
        .joinpath("exercises.json")
        .read_text("utf-8")
    )
    records: list[dict[str, Any]] = json.loads(text)
    return records


def _library_exercises(records: list[dict[str, Any]]) -> list[Exercise]:
    """Turn the built-in records into `Exercise`s."""
    return [
        Exercise(
            id=record["id"],
            name=record["name"],
            equipment=record["equipment"],
            body_part=record["body_part"],
            target=record["target"],
            custom=False,
            steps=record["steps"],
            secondary_muscles=record["secondary_muscles"],
            attribution=ATTRIBUTION,
        )
        for record in records
    ]


def _custom_exercise(row: CustomExercise) -> Exercise:
    """Turn a stored custom exercise into an `Exercise`."""
    document: dict[str, Any] = row.document
    return Exercise(
        id=f"{CUSTOM_PREFIX}{row.number}",
        name=row.name,
        equipment=document.get("equipment"),
        body_part=document.get("body_part"),
        target=document.get("target"),
        custom=True,
        steps=document["steps"],
        secondary_muscles=[],
        attribution=None,
    )


def _sort_key(exercise: Exercise) -> tuple[str, str]:
    """Order by name, then id, so a shared name always sorts the same way."""
    return (exercise.name.casefold(), exercise.id)


class Library:
    """The library and custom exercises, searched and looked up together."""

    def __init__(self, engine: Engine) -> None:
        """Load the built-in exercises; custom ones are read from `engine` per call."""
        self._engine = engine
        records = _load_records()
        self._library = _library_exercises(records)
        self._media = {
            record["id"]: MediaFiles(record["id"], record["gif"], record["thumbnail"])
            for record in records
        }
        self._by_id = {exercise.id: exercise for exercise in self._library}
        self._library_names = {exercise.name.casefold() for exercise in self._library}

    def _customs(self) -> list[Exercise]:
        """Return every custom exercise."""
        with session(self._engine) as db_session:
            rows = db_session.scalars(
                select(CustomExercise).order_by(CustomExercise.number)
            )
            return [_custom_exercise(row) for row in rows]

    def _all(self) -> list[Exercise]:
        """Return library and custom exercises, sorted by name."""
        return sorted([*self._library, *self._customs()], key=_sort_key)

    def search(
        self,
        query: str = "",
        equipment: str | None = None,
        body_part: str | None = None,
        limit: int = 20,
    ) -> list[ExerciseSummary]:
        """Return the exercises whose name has every word of `query`; names that start with it first."""
        needle = query.strip().casefold()
        words = needle.split()
        found = [
            exercise
            for exercise in self._all()
            if all(word in exercise.name.casefold() for word in words)
            and (equipment is None or exercise.equipment == equipment)
            and (body_part is None or exercise.body_part == body_part)
        ]
        # A stable sort keeps the name order within each group.
        found.sort(key=lambda exercise: not exercise.name.casefold().startswith(needle))
        return [
            ExerciseSummary.model_validate(exercise.model_dump(include=_SUMMARY_FIELDS))
            for exercise in found[:limit]
        ]

    def facets(self) -> dict[str, list[str]]:
        """Return the equipment and body-part values to filter by, sorted."""
        exercises = [*self._library, *self._customs()]
        return {
            "equipment": sorted({e.equipment for e in exercises if e.equipment}),
            "body_part": sorted({e.body_part for e in exercises if e.body_part}),
        }

    def get(self, exercise_id: str) -> Exercise:
        """Return one exercise by id; raise `NotFound` if there is none."""
        exercise = self._by_id.get(exercise_id) or self._get_custom(exercise_id)
        if exercise is None:
            raise NotFound(f"Exercise '{exercise_id}' not found")
        return exercise

    def _get_custom(self, exercise_id: str) -> Exercise | None:
        """Return the custom exercise with this id, or `None`; only the canonical `custom-<n>` counts."""
        match = _CUSTOM_ID.fullmatch(exercise_id)
        if match is None:
            return None
        with session(self._engine) as db_session:
            row = db_session.get(CustomExercise, int(match[1]))
            return None if row is None else _custom_exercise(row)

    def resolve(self, ref: str, station: int) -> Exercise:
        """Return the exercise a station names by id or by a name only one exercise has.

        Otherwise raise `Invalid` with the 1-based `station` and the close matches (spec §3.5).
        """
        by_id = self._by_id.get(ref) or self._get_custom(ref)
        if by_id is not None:
            return by_id
        exercises = self._all()
        key = ref.casefold()
        named = [exercise for exercise in exercises if exercise.name.casefold() == key]
        if len(named) == 1:
            return named[0]
        if named:
            message = f"Exercise name '{ref}' is shared; give the id"
            matches = named
        else:
            message = f"Unknown exercise '{ref}'"
            close = difflib.get_close_matches(
                key,
                [exercise.name.casefold() for exercise in exercises],
                n=MAX_CLOSE_MATCHES,
                cutoff=CLOSE_MATCH_CUTOFF,
            )
            matches = [
                exercise
                for name in dict.fromkeys(close)
                for exercise in exercises
                if exercise.name.casefold() == name
            ]
        raise Invalid(
            {
                "message": message,
                "station": station,
                "close_matches": [
                    {"id": exercise.id, "name": exercise.name}
                    for exercise in matches[:MAX_CLOSE_MATCHES]
                ],
            }
        )

    def add_custom(self, new: NewCustomExercise, client: str) -> Exercise:
        """Store a custom exercise as `custom-<n>` and log it; raise `Conflict` if the name is taken."""
        name_key = new.name.casefold()
        taken = Conflict(f"Exercise name '{new.name}' is taken")
        if name_key in self._library_names:
            raise taken
        try:
            with session(self._engine) as db_session:
                # SQLite assigns `number`: v1 has no deletes, so it counts up in the order added.
                row = CustomExercise(
                    name=new.name,
                    name_key=name_key,
                    document=new.model_dump(exclude={"name"}),
                )
                db_session.add(row)
                db_session.flush()
                changes.record(
                    db_session,
                    client=client,
                    action="exercise.added",
                    target=f"exercise:{CUSTOM_PREFIX}{row.number}",
                    summary=f"Added custom exercise {new.name}",
                )
                return _custom_exercise(row)
        except IntegrityError as error:
            if _NAME_KEY_CLASH not in str(error.orig):
                raise
            raise taken from error

    def media_files(self) -> list[MediaFiles]:
        """Return the media of every library exercise."""
        return list(self._media.values())

    def media_of(self, exercise_id: str) -> MediaFiles | None:
        """Return a library exercise's media; `None` for a custom or unknown id."""
        return self._media.get(exercise_id)

    def counts(self) -> dict[str, int]:
        """Return how many library and custom exercises there are."""
        with session(self._engine) as db_session:
            custom = db_session.scalar(select(func.count()).select_from(CustomExercise))
        return {"library": len(self._library), "custom": custom or 0}
