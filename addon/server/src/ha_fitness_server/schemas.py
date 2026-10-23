"""The Pydantic models REST and MCP share, so both expose one JSON schema."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class ExerciseSummary(BaseModel):
    """An exercise in a search result; custom exercises may leave the classification empty."""

    id: str
    name: str
    equipment: str | None
    body_part: str | None
    target: str | None
    custom: bool


class Exercise(ExerciseSummary):
    """One exercise with its steps; `attribution` is set for library exercises, null for custom ones."""

    steps: list[str]
    secondary_muscles: list[str]
    attribution: str | None


class Facets(BaseModel):
    """The values a search can filter by."""

    equipment: list[str]
    body_part: list[str]


class ExerciseSearch(BaseModel):
    """A search result; `facets` only when the query and the filters are empty."""

    results: list[ExerciseSummary]
    facets: Facets | None


class NewCustomExercise(BaseModel):
    """A custom exercise to add (spec §3.4)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    steps: Annotated[
        list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]],
        Field(min_length=1, max_length=10),
    ]
    equipment: str | None = None
    body_part: str | None = None
    target: str | None = None


class ChangeEntry(BaseModel):
    """One row of the change log (spec §6)."""

    at: datetime
    client: str
    action: str
    target: str
    summary: str


class ExerciseCounts(BaseModel):
    """How many library and custom exercises there are."""

    library: int
    custom: int


class MediaState(BaseModel):
    """The state of the media download (spec §3.2): `idle` before it starts, then `downloading`, `done` or `failed`."""

    state: Literal["idle", "downloading", "done", "failed"]
    present: int
    total: int


class LibraryStatus(BaseModel):
    """Body of `GET /api/v1/library`."""

    exercises: ExerciseCounts
    media: MediaState
