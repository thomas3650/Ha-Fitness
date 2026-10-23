"""The Pydantic models REST and MCP share, so both expose one JSON schema."""

from datetime import datetime
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


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


# The limits of a search and of the change log; REST's query and MCP's argument share them.
SearchLimit = Annotated[int, Field(ge=1, le=100)]
ChangeLogLimit = Annotated[int, Field(ge=1, le=200)]

# A custom exercise's name and steps; the REST body and MCP's flat arguments share them.
CustomExerciseName = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
CustomExerciseSteps = Annotated[
    list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]],
    Field(min_length=1, max_length=10),
]


class NewCustomExercise(BaseModel):
    """A custom exercise to add (spec §3.4)."""

    model_config = ConfigDict(extra="forbid")

    name: CustomExerciseName
    steps: CustomExerciseSteps
    equipment: str | None = None
    body_part: str | None = None
    target: str | None = None


class HaPerson(BaseModel):
    """A `person.*` entity in Home Assistant."""

    entity_id: str
    friendly_name: str


class Person(BaseModel):
    """A person who trains, linked to an HA person (spec §4)."""

    id: int
    name: str
    person_entity_id: str


class NewPerson(BaseModel):
    """A person in a `set_people` list (spec §4)."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=40)
    ]
    person_entity_id: str


class PeopleUpdate(BaseModel):
    """Body of `PUT /api/v1/people`: the whole list, in colour order."""

    model_config = ConfigDict(extra="forbid")

    people: list[NewPerson]


class PeopleView(BaseModel):
    """Body of `GET /api/v1/people`; `ha_persons` is null and `ha_error` says why when HA can't be read."""

    people: list[Person]
    ha_persons: list[HaPerson] | None
    ha_error: str | None


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


Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEK_ORDER: tuple[Weekday, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class StationIn(BaseModel):
    """A station: the exercise by id or by a name only one exercise has; stored as the id."""

    model_config = ConfigDict(extra="forbid")

    exercise: str


class Music(BaseModel):
    """A program's music (spec §5.1), stored now and used in step 7; not checked against HA."""

    model_config = ConfigDict(extra="forbid")

    playlist: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    speaker: Annotated[str, StringConstraints(pattern=r"^media_player\.[a-z0-9_]+$")]
    volume: Annotated[int, Field(ge=0, le=100)] | None = None
    shuffle: bool = False


class ProgramDocument(BaseModel):
    """One program, as REST, MCP, storage and export use it (spec §5.1); defaults are filled in on write."""

    model_config = ConfigDict(extra="forbid")

    name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=60)
    ]
    active: bool = True
    weekdays: list[Weekday]
    stations: Annotated[list[StationIn], Field(min_length=1, max_length=15)]
    rounds: Annotated[int, Field(ge=1, le=10)] = 5
    work_seconds: Annotated[int, Field(ge=10, le=120)] = 45
    switch_seconds: Annotated[int, Field(ge=0, le=60)] = 15
    round_rest_seconds: Annotated[int, Field(ge=0, le=180)] = 60
    countdown_seconds: Literal[0, 5, 10] = 5
    music: Music | None = None

    @field_validator("weekdays")
    @classmethod
    def _week_order(cls, weekdays: list[Weekday]) -> list[Weekday]:
        """Refuse a weekday given twice; keep the rest in week order."""
        if len(set(weekdays)) != len(weekdays):
            raise ValueError("a weekday is given more than once")
        return sorted(weekdays, key=WEEK_ORDER.index)

    @model_validator(mode="after")
    def _active_needs_a_weekday(self) -> Self:
        """An active program needs at least one weekday."""
        if self.active and not self.weekdays:
            raise ValueError("an active program needs at least one weekday")
        return self


class ProgramActive(BaseModel):
    """Body of `PUT /api/v1/programs/{id}/active`."""

    model_config = ConfigDict(extra="forbid")

    active: bool


class ProgramOut(BaseModel):
    """A stored program (spec §5.2); `program` holds the station ids and is a writable document as it stands."""

    id: int
    program: ProgramDocument
    station_names: list[str]
    total_seconds: int
    created_at: datetime
    updated_at: datetime


class ProgramSummary(BaseModel):
    """A program in a list (spec §8 `list_programs`); `total_minutes` is rounded, a half minute up."""

    id: int
    name: str
    active: bool
    weekdays: list[Weekday]
    station_count: int
    rounds: int
    total_minutes: int
