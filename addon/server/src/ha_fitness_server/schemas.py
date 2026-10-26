"""The Pydantic models REST and MCP share, so both expose one JSON schema."""

import datetime as dt
from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    StringConstraints,
    ValidationInfo,
    field_validator,
)
from pydantic_core import PydanticCustomError


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


class SpeakerOut(BaseModel):
    """A Music Assistant player in Home Assistant (music spec §4.3)."""

    entity_id: str
    name: str
    available: bool


class PlaylistOut(BaseModel):
    """A playlist in Music Assistant's library (music spec §4.3): `uri` is what a program's music plays."""

    name: str
    uri: str


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


# A speaker: a media player's entity id (spec §5.1); `Sessions.start` checks a start's speaker against it too.
SPEAKER_PATTERN = r"^media_player\.[a-z0-9_]+$"


class Music(BaseModel):
    """A program's music (spec §5.1; music spec §4.1); not checked against HA when written.

    `playlist` is what is played; `playlist_name` is the name the screens show, null for none.
    """

    model_config = ConfigDict(extra="forbid")

    playlist: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)
    ]
    playlist_name: (
        Annotated[
            str,
            StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
        ]
        | None
    ) = None
    speaker: Annotated[str, StringConstraints(pattern=SPEAKER_PATTERN)]
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
    def _week_order(
        cls, weekdays: list[Weekday], info: ValidationInfo
    ) -> list[Weekday]:
        """Refuse a weekday given twice, and none for an active program; keep the rest in week order.

        The weekday rule sits here, not on the model, so its error is at `weekdays` (D65). `active` is declared
        first; when it is itself invalid it is missing here and has its own error.
        """
        if len(set(weekdays)) != len(weekdays):
            raise ValueError("a weekday is given more than once")
        if info.data.get("active") and not weekdays:
            raise PydanticCustomError(
                "weekday_needed",
                "Value error, an active program needs at least one weekday",
            )
        return sorted(weekdays, key=WEEK_ORDER.index)


class ProgramActive(BaseModel):
    """Body of `PUT /api/v1/programs/{id}/active`."""

    model_config = ConfigDict(extra="forbid")

    active: bool


class ProgramOut(BaseModel):
    """A stored program (spec §5.2); `program` holds the station ids and is a writable document as it stands."""

    id: int
    program: ProgramDocument
    station_names: list[str]
    equipment: list[str]
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


class TrainingDayOut(BaseModel):
    """A stored training day (step 4 spec §3.1); `program_id` is null after the program is deleted."""

    id: int
    program_id: int | None
    program_name: str
    date: dt.date
    status: Literal["open", "done", "missed", "skipped"]
    created_at: datetime
    closed_at: datetime | None


class OpenDay(BaseModel):
    """An open training day in `GET /today`: due on its date, late after; the program fields are as it is now."""

    id: int
    program_id: int
    program_name: str
    date: dt.date
    state: Literal["due", "late"]
    station_count: int
    rounds: int
    total_minutes: int


class NextTraining(BaseModel):
    """The first date after today on which an active program trains, with those programs' names."""

    date: dt.date
    programs: list[str]


class UpcomingTraining(BaseModel):
    """An active program's next training after today, with the program's fields (today-ahead spec §2.2.1).

    `startable` is false while the program has an open day, or a done day dated today or later (§2.2.2).
    """

    program_id: int
    program_name: str
    date: dt.date
    station_count: int
    rounds: int
    total_minutes: int
    startable: bool


class Week(BaseModel):
    """The local week, Monday to Sunday, in the today view (UI refresh spec §3.1)."""

    done: int
    planned: int


class TodayView(BaseModel):
    """Body of `GET /api/v1/today` (step 4 spec §3.5, `week` UI refresh spec §3.1, `upcoming` today-ahead spec §2.2).

    `upcoming` has one entry per active program, by date, then program name ignoring case.
    """

    date: dt.date
    open: list[OpenDay]
    next: NextTraining | None
    week: Week
    upcoming: list[UpcomingTraining]


def _utc_millis(moment: datetime) -> str:
    """Write an aware time as UTC ISO with milliseconds: `2026-10-28T08:00:05.000Z`."""
    return (
        moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )


# A time in the session view (step 5 spec §3.5): UTC ISO with milliseconds in JSON.
UtcMillis = Annotated[
    datetime, PlainSerializer(_utc_millis, return_type=str, when_used="json")
]

PhaseKind = Literal["countdown", "work", "switch", "rest"]


class NewSession(BaseModel):
    """Body of `POST /api/v1/session`; the participant rules are the service's, so a bad list has the session shape."""

    model_config = ConfigDict(extra="forbid")

    program_id: int
    participants: list[int]
    training_day_id: int | None = None
    # Starts the program's next training early, from its upcoming date (today-ahead spec §2.2.3); the service refuses
    # it together with `training_day_id`, so that error has the session shape too.
    date: dt.date | None = None
    # Overrides the program's speaker for this session (music spec §4.2); the service checks the pattern.
    speaker: str | None = None


class SessionParticipantOut(BaseModel):
    """A participant of a session, with the name frozen at the start."""

    id: int
    name: str


class SessionPhase(BaseModel):
    """The current phase; `ends_at` is set while running, `remaining` (seconds) while paused."""

    index: int
    kind: PhaseKind
    round: int
    interval: int
    duration: int
    ends_at: UtcMillis | None
    remaining: float | None


class NextPhase(BaseModel):
    """The phase after the current one."""

    kind: PhaseKind
    duration: int


class StationRef(BaseModel):
    """A station of the plan: its number from 1, and its exercise."""

    number: int
    exercise_id: str
    name: str


class SessionStation(BaseModel):
    """Where one participant is now and goes next (step 5 spec §3.1); `next` is null when no work phase follows."""

    current: StationRef
    next: StationRef | None


class SessionTotals(BaseModel):
    """`planned` is the seconds of every work, switch and rest phase; the countdown is left out."""

    planned: int
    rounds: int
    stations: int


# How a completed session felt (UI refresh spec §3.3); `sessions.FEELINGS` lists the same values.
type Feeling = Literal["too_easy", "just_right", "too_hard"]


class SessionView(BaseModel):
    """A session as `GET /api/v1/session` and the push channel give it (step 5 spec §3.5).

    `phase`, `next_phase` and `stations` are null for a finished session in history.
    """

    id: int
    revision: int
    status: Literal["running", "paused", "completed", "ended"]
    counted: bool
    program_name: str
    training_day_id: int | None
    participants: list[SessionParticipantOut]
    phase: SessionPhase | None
    next_phase: NextPhase | None
    stations: list[SessionStation] | None
    totals: SessionTotals
    started_at: UtcMillis | None
    ended_at: UtcMillis | None
    rounds_completed: int
    time_trained: int
    server_time: UtcMillis
    # How a completed session felt; null on a live view and on a finished one not rated (UI refresh spec §3.3).
    feeling: Feeling | None
    # The program's music frozen at the start, with the start's speaker; null without music (music spec §4.2).
    music: Music | None


class FeelingIn(BaseModel):
    """Body of `POST /api/v1/session/feeling`; any text, so the service answers an unknown value with `{code, message}`."""

    model_config = ConfigDict(extra="forbid")

    feeling: str


class SessionHistory(BaseModel):
    """Body of `GET /api/v1/sessions`: the finished sessions, newest first, and the date counting starts from."""

    counting_from: dt.date | None
    sessions: list[SessionView]


class Totals(BaseModel):
    """One person's numbers over a period (stats spec §3.4); `extra` is the part of `done` from extra sessions."""

    done: int
    extra: int
    missed: int
    skipped: int
    time_trained: int


class PersonStats(BaseModel):
    """One person's stats: the streak is all time only (stats spec §3.2)."""

    id: int
    name: str
    person_entity_id: str
    streak: int
    all_time: Totals
    this_month: Totals


class Stats(BaseModel):
    """Body of `GET /api/v1/stats` (stats spec §3.4): `month` is the add-on's local month as `YYYY-MM`."""

    counting_from: dt.date | None
    month: str
    people: list[PersonStats]
