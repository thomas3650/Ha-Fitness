"""Tests for the MCP tools (spec §8) and the `/mcp` endpoint (D26)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
import json
from typing import Any

from fastapi import FastAPI
import fastmcp
from fastmcp.client.transports import FastMCPTransport
from fastmcp.exceptions import ToolError
from mcp.types import LATEST_PROTOCOL_VERSION, Implementation
import pytest

from tests.conftest import FrozenClock, MakeApp, running
from tests.session_helpers import (
    SESSION,
    SESSIONS,
    create_small,
    ok,
    set_people,
    start,
    started_with_mcp,
)
from tests.test_people import ELIN, HA_PERSONS, HA_URL, THOMAS, TOKEN, FakeHa
from tests.test_scheduler import ZONE, local

type McpClient = fastmcp.Client[FastMCPTransport]

READ_TOOLS = {
    "search_exercises",
    "get_exercise",
    "list_programs",
    "get_program",
    "list_people",
    "list_speakers",
    "list_playlists",
    "get_change_log",
    "get_today",
    "get_session",
    "list_sessions",
    "get_stats",
    "get_setup",
}
DESTRUCTIVE_TOOLS = {
    "update_program",
    "delete_program",
    "set_people",
    "skip_training_day",
}
ADDING_TOOLS = {"create_program", "add_custom_exercise", "set_program_active"}
# Five library exercises, by id.
FIVE = ["0001", "0002", "0003", "0006", "0020"]


@asynccontextmanager
async def mcp_client(
    app: FastAPI, name: str = "claude-code"
) -> AsyncIterator[McpClient]:
    """Run the app's lifespan and yield an in-memory MCP client named `name`."""
    async with (
        running(app),
        fastmcp.Client(
            app.state.mcp, client_info=Implementation(name=name, version="1")
        ) as mcp_session,
    ):
        yield mcp_session


async def call(session: McpClient, tool: str, **arguments: Any) -> Any:
    """Call a tool and return its structured result; a list comes back under `result`."""
    result = await session.call_tool(tool, arguments)
    return result.structured_content


def _program(name: str = "Onsdag", **fields: Any) -> dict[str, Any]:
    """Return a minimal valid program document with the given name."""
    return {
        "name": name,
        "weekdays": ["wed"],
        "stations": [{"exercise": "0001"}],
        **fields,
    }


async def test_tool_names_are_exactly_the_spec_list(make_app: MakeApp) -> None:
    """The server has the twelve tools of spec §8, step 4's two, step 5's two, step 6's one, step 7's two, the website's `get_setup`, and no others."""
    async with mcp_client(make_app()) as session:
        names = {tool.name for tool in await session.list_tools()}
    assert names == READ_TOOLS | DESTRUCTIVE_TOOLS | ADDING_TOOLS
    assert len(names) == 20


async def test_annotations(make_app: MakeApp) -> None:
    """Reads are read-only; replacing, deleting and skipping are destructive; adding and switching are neither."""
    async with mcp_client(make_app()) as session:
        tools = {tool.name: tool for tool in await session.list_tools()}
    for name in READ_TOOLS:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is True, name
    for name in DESTRUCTIVE_TOOLS:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False, name
        assert annotations.destructive_hint is True, name
    assert "Ask the user first" in (tools["skip_training_day"].description or "")
    for name in ADDING_TOOLS:
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is False, name
        assert annotations.destructive_hint is False, name


async def test_write_descriptions_ask_for_a_yes(make_app: MakeApp) -> None:
    """Every write tool tells the model to show the change and get a yes first."""
    async with mcp_client(make_app()) as session:
        tools = {tool.name: tool for tool in await session.list_tools()}
    for name in DESTRUCTIVE_TOOLS | ADDING_TOOLS:
        description = tools[name].description or ""
        assert "get a yes before calling" in description, name


@pytest.mark.parametrize("name", ["create_program", "update_program"])
async def test_program_descriptions_keep_timings_and_ask_for_music(
    make_app: MakeApp, name: str
) -> None:
    """The program tools keep the default timings and always ask about music."""
    async with mcp_client(make_app()) as session:
        tools = {tool.name: tool for tool in await session.list_tools()}
    description = tools[name].description or ""
    # The break between stations stays 15 s unless the user asks otherwise.
    assert "switch_seconds" in description
    assert "15" in description
    assert "unless the user asks" in description
    assert "never make up timings" in description.lower()
    assert "When creating: keep" in description
    assert "didn't mention" in description
    # The playlist and the speaker are asked for; no music is an answer.
    assert "list_playlists" in description
    assert "list_speakers" in description
    assert "always ask" in description
    assert "no music" in description.lower()
    # The summary before the yes names the timings and the music.
    summary = description[description.index("Before the yes") :]
    for word in ("timings", "break", "rest", "music"):
        assert word in summary, word


async def test_argument_schema_is_the_apis(make_app: MakeApp) -> None:
    """`create_program` takes the API's program document, ranges included."""
    async with mcp_client(make_app()) as session:
        tools = {tool.name: tool for tool in await session.list_tools()}
    program = tools["create_program"].input_schema["properties"]["program"]
    assert program["properties"]["rounds"]["maximum"] == 10
    assert program["additionalProperties"] is False


async def test_create_and_list_programs_via_mcp(make_app: MakeApp) -> None:
    """A program made with `create_program` shows in `list_programs` as a summary."""
    stations = [{"exercise": exercise} for exercise in FIVE]
    async with mcp_client(make_app()) as session:
        created = await call(
            session, "create_program", program=_program(stations=stations)
        )
        listed = await call(session, "list_programs")
    assert created["program"]["rounds"] == 5
    # 5 stations x 5 rounds x (45 + 15) s + 4 x 60 s rest = 1740 s.
    assert created["total_seconds"] == 1740
    assert listed == {
        "result": [
            {
                "id": created["id"],
                "name": "Onsdag",
                "active": True,
                "weekdays": ["wed"],
                "station_count": 5,
                "rounds": 5,
                "total_minutes": 29,
            }
        ]
    }


@pytest.mark.parametrize(
    ("stations", "work_seconds", "switch_seconds", "minutes"),
    [
        # 150 s is 2.5 min: half a minute rounds up, to 3.
        (1, 120, 30, 3),
        # 210 s is 3.5 min: up to 4.
        (2, 90, 15, 4),
        # 100 s is 1.67 min.
        (1, 100, 0, 2),
    ],
)
async def test_total_minutes_rounds_half_up(
    make_app: MakeApp,
    stations: int,
    work_seconds: int,
    switch_seconds: int,
    minutes: int,
) -> None:
    """`total_minutes` is the length in whole minutes, a half minute rounded up."""
    document = _program(
        stations=[{"exercise": "0001"}] * stations,
        rounds=1,
        work_seconds=work_seconds,
        switch_seconds=switch_seconds,
    )
    async with mcp_client(make_app()) as session:
        await call(session, "create_program", program=document)
        listed = await call(session, "list_programs")
    assert listed["result"][0]["total_minutes"] == minutes


async def test_get_update_activate_and_delete_program(make_app: MakeApp) -> None:
    """The other program tools answer as REST does; delete answers `{"deleted": id}`."""
    async with mcp_client(make_app()) as session:
        created = await call(session, "create_program", program=_program())
        program_id = created["id"]
        assert await call(session, "get_program", program_id=program_id) == created
        assert created["equipment"] == []
        with_bells = await call(
            session,
            "create_program",
            program=_program(name="Bells", stations=[{"exercise": "0285"}]),
        )
        got = await call(session, "get_program", program_id=with_bells["id"])
        assert got["equipment"] == ["dumbbell"]
        await call(session, "delete_program", program_id=with_bells["id"])
        updated = await call(
            session,
            "update_program",
            program_id=program_id,
            program=_program(rounds=4),
        )
        assert updated["program"]["rounds"] == 4
        off = await call(
            session, "set_program_active", program_id=program_id, active=False
        )
        assert off["program"]["active"] is False
        deleted = await call(session, "delete_program", program_id=program_id)
        assert deleted == {"deleted": program_id}
        assert await call(session, "list_programs") == {"result": []}


async def test_unknown_exercise_error_has_close_matches(make_app: MakeApp) -> None:
    """An unknown station comes back as a tool error whose text is REST's detail as JSON."""
    async with mcp_client(make_app()) as session:
        with pytest.raises(ToolError) as error:
            await call(
                session,
                "create_program",
                program=_program(stations=[{"exercise": "3/4 sit-upp"}]),
            )
    detail = json.loads(str(error.value))
    assert detail["message"] == "Unknown exercise '3/4 sit-upp'"
    assert detail["station"] == 1
    assert {"id": "0001", "name": "3/4 sit-up"} in detail["close_matches"]


async def test_not_found_and_taken_are_tool_errors_with_rests_text(
    make_app: MakeApp,
) -> None:
    """Not found and a taken name come back with the same text as REST's detail."""
    async with mcp_client(make_app()) as session:
        with pytest.raises(ToolError, match=r"^Program 999 not found$"):
            await call(session, "get_program", program_id=999)
        await call(session, "create_program", program=_program())
        with pytest.raises(ToolError, match=r"^Program name 'onsdag' is taken$"):
            await call(session, "create_program", program=_program(name="onsdag"))


async def test_text_detail_is_not_json_quoted(make_app: MakeApp) -> None:
    """A rule broken with a text detail comes back as that text."""
    async with mcp_client(make_app()) as session:
        created = await call(
            session, "create_program", program=_program(active=False, weekdays=[])
        )
        with pytest.raises(ToolError) as error:
            await call(
                session, "set_program_active", program_id=created["id"], active=True
            )
    assert str(error.value) == (
        f"Program {created['id']} has no weekdays; give it one before switching it on"
    )


async def test_active_without_weekdays_names_the_weekday_rule(
    make_app: MakeApp,
) -> None:
    """Creating or updating an active program without weekdays tells Claude the field and the rule."""
    async with mcp_client(make_app()) as session:
        with pytest.raises(ToolError) as created:
            await call(
                session, "create_program", program=_program(weekdays=[], active=True)
            )
        program = await call(session, "create_program", program=_program())
        with pytest.raises(ToolError) as updated:
            await call(
                session,
                "update_program",
                program_id=program["id"],
                program=_program(weekdays=[], active=True),
            )
    for error in (created, updated):
        text = str(error.value)
        assert "program.weekdays" in text
        assert "an active program needs at least one weekday" in text


async def test_out_of_range_field_is_a_tool_error(make_app: MakeApp) -> None:
    """Argument validation names the field that is out of range."""
    async with mcp_client(make_app()) as session:
        with pytest.raises(ToolError, match="rounds"):
            await call(session, "create_program", program=_program(rounds=11))
        assert await call(session, "list_programs") == {"result": []}


async def test_change_log_client_is_mcp(make_app: MakeApp) -> None:
    """A write by the client `claude-code` is logged as `mcp:claude-code`, and `get_change_log` reads it."""
    async with mcp_client(make_app()) as session:
        await call(session, "create_program", program=_program())
        log = await call(session, "get_change_log", limit=1)
    assert len(log["result"]) == 1
    newest = log["result"][0]
    assert newest["client"] == "mcp:claude-code"
    assert newest["action"] == "program.created"
    assert newest["summary"] == "Created program Onsdag"


@pytest.mark.parametrize(
    ("name", "client"),
    [("", "mcp:unknown"), ("c" * 200, "mcp:" + "c" * 96)],
)
async def test_change_log_client_without_name_and_cut(
    make_app: MakeApp, name: str, client: str
) -> None:
    """A client without a name is `mcp:unknown`; a long name is cut to 100 characters in all."""
    async with mcp_client(make_app(), name=name) as session:
        await call(session, "create_program", program=_program())
        log = await call(session, "get_change_log")
    assert log["result"][0]["client"] == client


@pytest.mark.parametrize(
    ("tool", "limit"),
    [
        ("search_exercises", 0),
        ("search_exercises", 101),
        ("get_change_log", 0),
        ("get_change_log", 201),
    ],
)
async def test_limits_have_rests_bounds(
    make_app: MakeApp, tool: str, limit: int
) -> None:
    """The search limit is 1-100 and the change-log limit 1-200, as in REST."""
    arguments: dict[str, Any] = {"limit": limit}
    if tool == "search_exercises":
        arguments["query"] = ""
    async with mcp_client(make_app()) as session:
        with pytest.raises(ToolError, match="limit"):
            await call(session, tool, **arguments)


async def test_search_exercises_and_facets_via_mcp(make_app: MakeApp) -> None:
    """An empty search gives the facets; a search by name gives the matches and no facets."""
    async with mcp_client(make_app()) as session:
        empty = await call(session, "search_exercises", query="", limit=100)
        found = await call(session, "search_exercises", query="3/4 sit-up")
        filtered = await call(
            session, "search_exercises", query="", equipment="body weight", limit=3
        )
    assert len(empty["results"]) == 100
    assert "body weight" in empty["facets"]["equipment"]
    assert found["facets"] is None
    assert found["results"][0]["id"] == "0001"
    assert filtered["facets"] is None
    assert len(filtered["results"]) == 3
    assert all(r["equipment"] == "body weight" for r in filtered["results"])


async def test_get_setup_returns_the_stored_setup(make_app: MakeApp) -> None:
    """`get_setup` answers what `GET /setup` does: the defaults first, then the stored setup."""
    setup = {
        "equipment": ["dumbbell", "kettlebell"],
        "favourite_playlists": [{"uri": "library://playlist/1", "name": "Morgen"}],
        "default_speaker": "media_player.kitchen",
    }
    app = make_app()
    async with (
        running(app) as http_client,
        fastmcp.Client(
            app.state.mcp, client_info=Implementation(name="claude-code", version="1")
        ) as session,
    ):
        before = await call(session, "get_setup")
        stored = await http_client.put("/api/v1/setup", json=setup)
        assert stored.status_code == 200, stored.text
        after = await call(session, "get_setup")
        rest = (await http_client.get("/api/v1/setup")).json()
    assert before == {
        "equipment": ["body weight"],
        "favourite_playlists": [],
        "default_speaker": None,
    }
    assert after == rest
    assert after["equipment"] == ["body weight", "dumbbell", "kettlebell"]
    assert after["favourite_playlists"] == setup["favourite_playlists"]
    assert after["default_speaker"] == "media_player.kitchen"


async def test_search_exercises_household_matches_rest(make_app: MakeApp) -> None:
    """`search_exercises` with `household` answers what the REST search does, and leaves out other equipment."""
    app = make_app()
    async with (
        running(app) as http_client,
        fastmcp.Client(
            app.state.mcp, client_info=Implementation(name="claude-code", version="1")
        ) as session,
    ):
        stored = await http_client.put(
            "/api/v1/setup", json={"equipment": ["dumbbell"]}
        )
        assert stored.status_code == 200, stored.text
        household = await call(
            session, "search_exercises", query="fly", household=True, limit=100
        )
        rest = (
            await http_client.get(
                "/api/v1/exercises",
                params={"q": "fly", "household": "true", "limit": 100},
            )
        ).json()
        everything = await call(session, "search_exercises", query="fly", limit=100)
    assert household == rest
    assert household["results"]
    assert {r["equipment"] for r in household["results"]} <= {"body weight", "dumbbell"}
    assert len(everything["results"]) > len(household["results"])
    assert "cable" in {r["equipment"] for r in everything["results"]}


async def test_descriptions_point_to_the_household_setup(make_app: MakeApp) -> None:
    """The program tools and the search tell Claude to use the household's equipment and favourites."""
    async with mcp_client(make_app()) as session:
        tools = {tool.name: tool for tool in await session.list_tools()}
    for name in ("create_program", "update_program", "search_exercises"):
        description = tools[name].description or ""
        assert "get_setup" in description, name
        assert "household" in description, name
        assert "favourite playlists" in description, name
        assert "default speaker" in description, name


async def test_get_and_add_custom_exercise_via_mcp(make_app: MakeApp) -> None:
    """`add_custom_exercise` stores a custom exercise that `get_exercise` returns."""
    async with mcp_client(make_app()) as session:
        added = await call(
            session,
            "add_custom_exercise",
            name="  Kettlebell halo  ",
            steps=["Hold the bell", "Circle it round the head"],
            equipment="kettlebell",
        )
        fetched = await call(session, "get_exercise", exercise_id=added["id"])
        library = await call(session, "get_exercise", exercise_id="0001")
        with pytest.raises(
            ToolError, match=r"^Exercise name 'kettlebell halo' is taken$"
        ):
            await call(
                session, "add_custom_exercise", name="kettlebell halo", steps=["x"]
            )
        with pytest.raises(ToolError, match="steps"):
            await call(session, "add_custom_exercise", name="Halo", steps=[])
    assert added == fetched
    assert added["name"] == "Kettlebell halo"
    assert added["custom"] is True
    assert added["equipment"] == "kettlebell"
    assert added["body_part"] is None
    assert library["name"] == "3/4 sit-up"


async def test_list_people_via_mcp_with_fake_ha(make_app: MakeApp) -> None:
    """`set_people` stores the people and `list_people` shows them with HA's persons."""
    app = make_app(
        {"ha_url": HA_URL, "ha_token": TOKEN}, ha_transport=FakeHa().transport()
    )
    async with mcp_client(app) as session:
        people = await call(session, "set_people", people=[THOMAS, ELIN])
        view = await call(session, "list_people")
    assert [person["name"] for person in people["result"]] == ["Thomas", "Elin"]
    assert view["people"] == people["result"]
    assert view["ha_persons"] == HA_PERSONS
    assert view["ha_error"] is None


async def test_set_people_when_ha_is_down_is_a_tool_error(make_app: MakeApp) -> None:
    """Setting people while HA can't be reached fails with HA's error text and logs nothing."""
    ha = FakeHa()
    ha.down = True
    app = make_app({"ha_url": HA_URL, "ha_token": TOKEN}, ha_transport=ha.transport())
    async with mcp_client(app) as session:
        view = await call(session, "list_people")
        with pytest.raises(ToolError) as error:
            await call(session, "set_people", people=[THOMAS])
        log = await call(session, "get_change_log")
    assert view["ha_error"]
    assert str(error.value) == view["ha_error"]
    assert log == {"result": []}


async def test_http_mcp_endpoint_answers_initialize(make_app: MakeApp) -> None:
    """`POST /mcp` answers an initialize itself, with no redirect to `/mcp/`."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with running(make_app()) as http_client:
        response = await http_client.post("/mcp", json=body, headers=headers)
        health = await http_client.get("/api/v1/health")
    assert response.status_code == 200, response.text
    assert "HA Fitness" in response.text
    assert health.status_code == 200


@pytest.mark.parametrize("method", ["GET", "POST", "PUT", "PATCH", "DELETE"])
async def test_unknown_api_path_is_fastapis_json_404(
    make_app: MakeApp, method: str
) -> None:
    """The root MCP mount never answers under `/api`: an unknown path there is FastAPI's JSON 404."""
    async with running(make_app()) as http_client:
        response = await http_client.request(method, "/api/v1/nope")
        nested = await http_client.get("/api/v2/programs/1")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}
    assert nested.status_code == 404
    assert nested.json() == {"detail": "Not Found"}


async def test_get_today_tool_equals_rest(make_app: MakeApp) -> None:
    """`get_today` answers what `GET /today` does: here one due day and the next date."""
    clock = FrozenClock(local(2026, 10, 28, 9))  # a Wednesday
    app = make_app(settings_overrides={"timezone": ZONE}, clock=clock)
    async with (
        running(app) as http_client,
        fastmcp.Client(
            app.state.mcp, client_info=Implementation(name="claude-code", version="1")
        ) as session,
    ):
        await call(session, "create_program", program=_program(weekdays=["wed", "sat"]))
        today = await call(session, "get_today")
        rest = (await http_client.get("/api/v1/today")).json()
    assert today == rest
    assert [day["program_name"] for day in today["open"]] == ["Onsdag"]
    assert today["next"] == {"date": "2026-10-31", "programs": ["Onsdag"]}


async def test_skip_tool_logs_mcp_client(make_app: MakeApp) -> None:
    """`skip_training_day` closes the day and logs `mcp:claude-code`; a second skip is a tool error."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    app = make_app(settings_overrides={"timezone": ZONE}, clock=clock)
    async with mcp_client(app) as session:
        await call(session, "create_program", program=_program())
        [day] = (await call(session, "get_today"))["open"]
        skipped = await call(session, "skip_training_day", training_day_id=day["id"])
        assert (skipped["id"], skipped["status"]) == (day["id"], "skipped")
        assert (await call(session, "get_today"))["open"] == []
        [newest] = (await call(session, "get_change_log", limit=1))["result"]
        with pytest.raises(ToolError):
            await call(session, "skip_training_day", training_day_id=day["id"])
        with pytest.raises(ToolError):
            await call(session, "skip_training_day", training_day_id=999)
    assert newest["client"] == "mcp:claude-code"
    assert newest["action"] == "training_day.skipped"
    assert newest["target"] == f"training_day:{day['id']}"
    assert newest["summary"] == "Skipped Onsdag (2026-10-28)"


async def test_mcp_get_session_and_list_sessions(make_app: MakeApp) -> None:
    """`get_session` and `list_sessions` answer what `GET /session` and `GET /sessions` do; a bad limit is JSON."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started_with_mcp(clock, make_app) as (client, session):
        none = await call(session, "get_session")
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        running_view = await call(session, "get_session")
        rest_running = (await client.get(SESSION)).json()
        first = await ok(client, "end")
        clock.advance(timedelta(minutes=1))
        await start(client, program["id"], [thomas])
        second = await ok(client, "end")
        history = await call(session, "list_sessions")
        rest_history = (await client.get(SESSIONS)).json()
        one = await call(session, "list_sessions", limit=1)
        with pytest.raises(ToolError) as refused:
            await call(session, "list_sessions", limit=0)
    assert none == {"result": None}
    assert running_view == {"result": rest_running}
    assert history == rest_history
    assert history["counting_from"] is None
    assert [listed["id"] for listed in history["sessions"]] == [
        second["id"],
        first["id"],
    ]
    assert one == {**rest_history, "sessions": rest_history["sessions"][:1]}
    assert len(one["sessions"]) == 1
    detail = json.loads(str(refused.value))
    assert detail["code"] == "invalid"
    assert "limit" in detail["message"]


async def test_get_stats_tool_equals_rest(make_app: MakeApp) -> None:
    """`get_stats` answers what `GET /stats` does: here Thomas's done day and Elin's missed one."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started_with_mcp(clock, make_app) as (client, session):
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        [day] = (await client.get("/api/v1/today")).json()["open"]
        await start(client, program["id"], [thomas], day["id"])
        clock.advance(timedelta(minutes=2))
        await client.get(SESSION)
        stats = await call(session, "get_stats")
        rest = (await client.get("/api/v1/stats")).json()
    assert stats == rest
    assert [person["id"] for person in stats["people"]] == [thomas, elin]
    assert [person["all_time"]["done"] for person in stats["people"]] == [1, 0]
    assert [person["all_time"]["missed"] for person in stats["people"]] == [0, 1]
