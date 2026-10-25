"""The MCP tools (spec §8): thin, sync tools over the services, with the API's Pydantic types as arguments."""

from collections.abc import Iterator
from contextlib import contextmanager
import json
from typing import TypedDict

from fastmcp import Context, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import ToolAnnotations

from . import changes
from .errors import Conflict, Invalid, NotFound, SessionError, Unavailable
from .schemas import (
    ChangeEntry,
    ChangeLogLimit,
    CustomExerciseName,
    CustomExerciseSteps,
    Exercise,
    ExerciseSearch,
    NewCustomExercise,
    NewPerson,
    PeopleView,
    Person,
    PlaylistOut,
    ProgramDocument,
    ProgramOut,
    ProgramSummary,
    SearchLimit,
    SessionHistory,
    SessionView,
    SpeakerOut,
    Stats,
    TodayView,
    TrainingDayOut,
)
from .services import ServicesHolder

_READ = ToolAnnotations(read_only_hint=True)
# Replaces or removes what is stored.
_DESTRUCTIVE = ToolAnnotations(read_only_hint=False, destructive_hint=True)
# Adds, or changes something that can be changed back.
_ADDS = ToolAnnotations(read_only_hint=False, destructive_hint=False)

_PROGRAM_RULES = """\
The program document:
- name: 1-60 characters, unique ignoring case.
- weekdays: the days it is due, from mon, tue, wed, thu, fri, sat, sun; each day once. An active program needs at
  least one.
- active: true by default; false keeps the program but takes it off the schedule.
- stations: 1-15, each {"exercise": <exercise id, or a name only one exercise has>}; 5 stations is the usual choice.
  Find exercises with search_exercises. An exercise that can't be resolved fails with the station number and
  close_matches to pick from.
- rounds: 1-10, default 5.
- work_seconds: 10-120, default 45. switch_seconds: 0-60, default 15. round_rest_seconds: 0-180, default 60.
- countdown_seconds: 0, 5 or 10, default 5.
- Keep these defaults (work 45 s, the break between stations 15 s, the rest between rounds 60 s, the countdown 5 s)
  unless the user asks for another value. "The break" means switch_seconds. Never make up timings. When updating,
  leave the timing fields the user didn't mention as they are in get_program.
- music: optional {"playlist", "playlist_name", "speaker": "media_player.<name>", "volume": 0-100, "shuffle": false}.
  Pick the speaker from list_speakers and the playlist from list_playlists: "playlist" is its uri, which is played,
  and "playlist_name" (1-200 characters, optional) its name, which the screens show instead of the uri.
Omitted fields get their defaults.

Music: when creating a program, and when updating one that has no music, always ask the user which playlist
(list_playlists) and which speaker (list_speakers) to use. No music is a valid answer: then leave music out."""

_YES_PROGRAM = """\
Before the yes, show the user a summary of the program: the stations, the rounds, the timings (work, the break
between stations, the rest between rounds) and the music, or that there is none. Show it and get a yes before calling."""


class Deleted(TypedDict):
    """The answer of `delete_program`."""

    deleted: int


def _client(ctx: Context) -> str:
    """Return the change-log client: `mcp:<clientInfo name>` (`mcp:unknown`), at most 100 characters."""
    params = ctx.session.client_params
    name = params.client_info.name if params is not None else None
    return f"mcp:{name or 'unknown'}"[: changes.MAX_CLIENT_LENGTH]


@contextmanager
def _tool_errors() -> Iterator[None]:
    """Turn the services' errors into a `ToolError` with REST's `detail`: a text as it is, a dict as JSON.

    A `SessionError` sends its `{code, message}` as JSON.
    """
    try:
        yield
    except SessionError as error:
        raise ToolError(
            json.dumps(
                {"code": error.code, "message": error.message}, ensure_ascii=False
            )
        ) from error
    except Invalid as error:
        detail = error.detail
        text = (
            detail
            if isinstance(detail, str)
            else json.dumps(detail, ensure_ascii=False)
        )
        raise ToolError(text) from error
    except (NotFound, Conflict, Unavailable) as error:
        raise ToolError(str(error)) from error


def build_mcp(holder: ServicesHolder) -> FastMCP:
    """Build the MCP server; its tools read the services from `holder` at call time."""
    mcp = FastMCP("HA Fitness")

    @mcp.tool(annotations=_READ)
    def search_exercises(
        query: str,
        equipment: str | None = None,
        body_part: str | None = None,
        limit: SearchLimit = 20,
    ) -> ExerciseSearch:
        """Search the exercise library and the custom exercises by name.

        Every word of `query` must be in the name; names that start with it come first. `equipment` and `body_part`
        filter by an exact value. `limit` is 1-100, default 20. With an empty query and no filters the answer also
        has `facets`: the equipment and body-part values to filter by.
        """
        with _tool_errors():
            return holder.get().library.search_with_facets(
                query, equipment, body_part, limit
            )

    @mcp.tool(annotations=_READ)
    def get_exercise(exercise_id: str) -> Exercise:
        """Return one exercise by id, with its steps, secondary muscles and attribution."""
        with _tool_errors():
            return holder.get().library.get(exercise_id)

    @mcp.tool(annotations=_ADDS)
    def add_custom_exercise(
        ctx: Context,
        name: CustomExerciseName,
        steps: CustomExerciseSteps,
        equipment: str | None = None,
        body_part: str | None = None,
        target: str | None = None,
    ) -> Exercise:
        """Add a custom exercise for one the library doesn't have; it gets the id custom-<n>.

        `name` is 1-80 characters and must not be any exercise's name, ignoring case. `steps` are 1-10 short
        instructions. `equipment`, `body_part` and `target` are optional; use the library's values (see
        search_exercises' facets) so filters find it. Search first: add only what the library lacks. Show the
        exercise to the user and get a yes before calling.
        """
        new = NewCustomExercise(
            name=name,
            steps=steps,
            equipment=equipment,
            body_part=body_part,
            target=target,
        )
        with _tool_errors():
            return holder.get().library.add_custom(new, _client(ctx))

    @mcp.tool(annotations=_READ)
    def list_programs() -> list[ProgramSummary]:
        """List every program, by name, with its weekdays, station count, rounds and length in whole minutes."""
        with _tool_errors():
            return holder.get().programs.summaries()

    @mcp.tool(annotations=_READ)
    def get_program(program_id: int) -> ProgramOut:
        """Return one program: its document (station exercise ids), the station names, the equipment it needs and its length in seconds.

        `equipment` lists each kind of equipment once, in station order; body weight is left out.

        The `program` field is a valid document as it stands: change it and pass it to update_program. The one
        exception: a station whose exercise has left the library is named by its id, and update_program refuses the
        document until that station gets another exercise.
        """
        with _tool_errors():
            return holder.get().programs.get(program_id)

    @mcp.tool(
        annotations=_ADDS,
        description=f"""Create a training program.

{_PROGRAM_RULES}

{_YES_PROGRAM}""",
    )
    def create_program(ctx: Context, program: ProgramDocument) -> ProgramOut:
        with _tool_errors():
            return holder.get().programs.create(program, _client(ctx))

    @mcp.tool(
        annotations=_DESTRUCTIVE,
        description=f"""Replace a program's whole document.

Start from get_program's `program` and change what the user asked for; fields left out get their defaults, not the
old values.

{_PROGRAM_RULES}

{_YES_PROGRAM}""",
    )
    def update_program(
        ctx: Context, program_id: int, program: ProgramDocument
    ) -> ProgramOut:
        with _tool_errors():
            return holder.get().programs.replace(program_id, program, _client(ctx))

    @mcp.tool(annotations=_ADDS)
    def set_program_active(ctx: Context, program_id: int, active: bool) -> ProgramOut:
        """Switch a program on (on the schedule) or off (kept, but never due); switching on needs a weekday.

        Show the program to the user and get a yes before calling.
        """
        with _tool_errors():
            return holder.get().programs.set_active(program_id, active, _client(ctx))

    @mcp.tool(annotations=_DESTRUCTIVE)
    def delete_program(ctx: Context, program_id: int) -> Deleted:
        """Delete a program for good; set_program_active with false keeps it instead.

        Show the program to the user and get a yes before calling.
        """
        with _tool_errors():
            holder.get().programs.delete(program_id, _client(ctx))
        return {"deleted": program_id}

    @mcp.tool(annotations=_READ)
    def list_people() -> PeopleView:
        """List the people who train, in colour order, and Home Assistant's persons to link them to.

        When Home Assistant can't be read, `ha_persons` is null and `ha_error` says why.
        """
        with _tool_errors():
            return holder.get().people.list()

    @mcp.tool(annotations=_DESTRUCTIVE)
    def set_people(ctx: Context, people: list[NewPerson]) -> list[Person]:
        """Replace the people who train: 0-2, in colour order, each {"name", "person_entity_id"}.

        `name` is 1-40 characters. `person_entity_id` is a person.* entity from list_people's `ha_persons`, each one
        used once. A person whose entity id stays keeps their id and stats; one left out is removed. Show the people
        to the user and get a yes before calling.
        """
        with _tool_errors():
            return holder.get().people.set(people, _client(ctx))

    @mcp.tool(annotations=_READ)
    def list_speakers() -> list[SpeakerOut]:
        """List Music Assistant's speakers in Home Assistant, sorted by name: {"entity_id", "name", "available"}.

        A program's music.speaker is one of these entity ids. `available` is false while the speaker can't be
        reached. An empty list means Music Assistant has no players, or isn't installed.
        """
        with _tool_errors():
            return holder.get().music.speakers()

    @mcp.tool(annotations=_READ)
    def list_playlists(search: str | None = None) -> list[PlaylistOut]:
        """List the playlists in Music Assistant's library, sorted by name: {"name", "uri"}; `search` filters by name.

        A program's music.playlist is the uri and music.playlist_name the name. An empty list means no playlist
        matched, or Music Assistant has no speakers.
        """
        with _tool_errors():
            return holder.get().music.playlists(search)

    @mcp.tool(annotations=_READ)
    def get_change_log(limit: ChangeLogLimit = 20) -> list[ChangeEntry]:
        """Return the newest writes, newest first: when, by which client, what and a one-line summary.

        `limit` is 1-200, default 20.
        """
        with _tool_errors():
            return changes.recent(holder.get().engine, limit)

    @mcp.tool(annotations=_READ)
    def get_today() -> TodayView:
        """Return today's open training days, due (today) or late (an earlier date), and the next date a program trains.

        Each open day has its id, program, date, state, station count, rounds and length in whole minutes. `next` is
        null when no program is active. `week` counts this local week, Monday to Sunday: `planned` is its training
        days, past, today's and still to come, and `done` is those trained.
        """
        with _tool_errors():
            return holder.get().training_days.today_view()

    @mcp.tool(annotations=_DESTRUCTIVE)
    def skip_training_day(ctx: Context, training_day_id: int) -> TrainingDayOut:
        """Skip an open training day on purpose: it closes as skipped and never asks again.

        Take the id from get_today; only an open day can be skipped. Ask the user first: show the day and
        get a yes before calling.
        """
        with _tool_errors():
            return holder.get().training_days.skip(training_day_id, _client(ctx))

    @mcp.tool(annotations=_READ)
    def get_session() -> SessionView | None:
        """Return the running or paused workout session, else the one finished under 5 minutes ago, else null.

        Read-only: the workout runs on the tablet, and no tool starts or steers it.
        """
        with _tool_errors():
            return holder.get().sessions.current()

    @mcp.tool(annotations=_READ)
    def list_sessions(limit: int = 20) -> SessionHistory:
        """Return the finished sessions, newest first, and `counting_from`, the date the counting starts (or null).

        `limit` is 1-100, default 20. Each session's `feeling` is how the workout felt, rated on the tablet just after
        it completed: `too_easy`, `just_right`, `too_hard`, or null when not rated.
        """
        with _tool_errors():
            return holder.get().sessions.finished(limit)

    @mcp.tool(annotations=_READ)
    def get_stats() -> Stats:
        """Return each person's stats, in people order: the streak, and the totals for this month and all time.

        Totals: `done` (days done plus extra sessions), `extra` (of done, the extra sessions), `missed`, `skipped`
        and `time_trained` in whole seconds. The streak counts the latest dates on which every training day was done;
        a missed or skipped day ends it, and extra sessions don't count. `month` is the current local month,
        `YYYY-MM`; `counting_from` is the date counting starts (null before the first counted session, when every
        number is 0).
        """
        with _tool_errors():
            return holder.get().stats.view()

    return mcp
