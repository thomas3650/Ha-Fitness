"""Tests for how a workout felt (UI refresh spec §3.3): `POST /api/v1/session/feeling` on a completed finished view.

Through REST, the websocket and MCP on a frozen clock in Copenhagen time, on the program `SMALL` (its phases are in
`tests/session_helpers.py`). A session completes by moving the clock to its end and reading `GET /session`.
"""

from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
import httpx

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    AGENT,
    CHANGES,
    PROGRAMS,
    SESSION,
    SESSIONS,
    SMALL_END,
    SMALL_STARTS,
    WS,
    at,
    create_small,
    current,
    make_session_app,
    ok,
    set_people,
    start,
    started,
    started_with_mcp,
    tc_program,
    tc_setup,
    tc_start,
    ws_connect,
    ws_session,
)
from tests.test_mcp import call
from tests.test_people import THOMAS
from tests.test_scheduler import local

WEDNESDAY_9 = local(2026, 10, 28, 9)
FEELING = f"{SESSION}/feeling"
KEPT = timedelta(minutes=5)


async def _feel(client: httpx.AsyncClient, feeling: Any) -> httpx.Response:
    """Rate the current session as `test-agent`."""
    return await client.post(FEELING, json={"feeling": feeling}, headers=AGENT)


async def _completed(client: httpx.AsyncClient, clock: FrozenClock) -> dict[str, Any]:
    """Set Thomas, start `SMALL` now and let it complete; return the finished view."""
    [thomas] = await set_people(client, THOMAS)
    program = await create_small(client, "Lille")
    begin = clock.now()
    await start(client, program["id"], [thomas])
    clock.set(at(begin, SMALL_END))
    view: dict[str, Any] = await current(client)
    assert view["status"] == "completed"
    return view


def _refused(response: httpx.Response, status: int, code: str) -> None:
    """Assert the session routes' `{code, message}` refusal."""
    assert response.status_code == status, response.text
    detail = response.json()["detail"]
    assert detail["code"] == code
    assert detail["message"]


async def test_feeling_sets_and_changes(make_app: MakeApp) -> None:
    """A completed view takes a feeling; a second call replaces it, and `revision` rises each time."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        finished = await _completed(client, clock)
        first = await _feel(client, "too_easy")
        shown_first = await current(client)
        second = await _feel(client, "too_hard")
        shown_second = await current(client)
    assert finished["feeling"] is None
    assert first.status_code == 200, first.text
    assert first.json()["feeling"] == "too_easy"
    assert first.json()["revision"] == finished["revision"] + 1
    assert shown_first["feeling"] == "too_easy"
    assert second.status_code == 200, second.text
    assert second.json()["feeling"] == "too_hard"
    assert second.json()["revision"] == finished["revision"] + 2
    assert shown_second == {**second.json(), "server_time": shown_second["server_time"]}


def test_feeling_pushes_session(make_app: MakeApp) -> None:
    """A rating pushes one `session` message with the feeling and the new revision."""
    clock = FrozenClock(WEDNESDAY_9)
    app = make_session_app(clock, make_app, {"session_tick_max": 0.05})
    with TestClient(app) as tc:
        thomas, program_id = tc_setup(tc)
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            assert ws.receive_json()["event"] == "session_started"
            clock.set(at(WEDNESDAY_9, SMALL_END))
            completed = ws_session(ws.receive_json())
            # An extra session's finish: its event, then the stats (the first counted session); `today` is unchanged.
            assert ws.receive_json()["event"] == "session_completed"
            assert ws.receive_json()["type"] == "stats"
            response = tc.post(FEELING, json={"feeling": "just_right"}, headers=AGENT)
            pushed = ws_session(ws.receive_json())
            # A program created after the rating pushes its own messages; the next one isn't a second `session`.
            tc_program(tc, "Næste")
            after = ws.receive_json()
    assert response.status_code == 200, response.text
    assert pushed == response.json()
    assert pushed["feeling"] == "just_right"
    assert pushed["revision"] == completed["revision"] + 1
    assert after["type"] != "session", after


async def test_feeling_adds_a_change_log_row(make_app: MakeApp) -> None:
    """A rating adds a change-log row naming the session, the program and the feeling."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        finished = await _completed(client, clock)
        response = await _feel(client, "too_hard")
        listed = await client.get(CHANGES, params={"limit": 100})
    assert response.status_code == 200, response.text
    rows = [row for row in listed.json() if row["action"] == "session.feeling"]
    assert len(rows) == 1
    assert rows[0]["client"] == "rest:test-agent"
    assert rows[0]["target"] == f"session:{finished['id']}"
    assert rows[0]["summary"] == "Rated session of Lille as too_hard"


async def test_feeling_refused_without_a_finished_view(make_app: MakeApp) -> None:
    """With no session, a running one or a paused one, a rating is 409 `conflict`."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        none = await _feel(client, "just_right")
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        running_refused = await _feel(client, "just_right")
        await ok(client, "pause")
        paused_refused = await _feel(client, "just_right")
        view = await current(client)
    _refused(none, 409, "conflict")
    _refused(running_refused, 409, "conflict")
    _refused(paused_refused, 409, "conflict")
    assert view["status"] == "paused"
    assert view["feeling"] is None


async def test_feeling_refused_for_ended_sessions(make_app: MakeApp) -> None:
    """An ended session, counted or not, takes no rating: 409 `conflict`, and nothing is stored."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        not_counted = await ok(client, "end")
        not_counted_refused = await _feel(client, "too_easy")
        clock.advance(timedelta(minutes=1))
        begin = clock.now()
        await start(client, program["id"], [thomas])
        clock.set(at(begin, SMALL_STARTS[6] + 1))
        counted = await ok(client, "end")
        counted_refused = await _feel(client, "too_easy")
        history = (await client.get(SESSIONS)).json()
    assert not_counted["counted"] is False
    assert counted["counted"] is True
    _refused(not_counted_refused, 409, "conflict")
    _refused(counted_refused, 409, "conflict")
    assert [view["feeling"] for view in history["sessions"]] == [None, None]


async def test_feeling_refused_after_five_minutes(make_app: MakeApp) -> None:
    """Once the finished view's 5 minutes are over, a rating is 409 `conflict` and nothing is stored."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        finished = await _completed(client, clock)
        clock.set(at(WEDNESDAY_9, SMALL_END) + KEPT - timedelta(seconds=1))
        inside = await _feel(client, "too_easy")
        clock.set(at(WEDNESDAY_9, SMALL_END) + KEPT)
        late = await _feel(client, "too_hard")
        history = (await client.get(SESSIONS)).json()
    assert inside.status_code == 200, inside.text
    _refused(late, 409, "conflict")
    [stored] = history["sessions"]
    assert stored["id"] == finished["id"]
    assert stored["feeling"] == "too_easy"
    assert stored["revision"] == finished["revision"] + 1


async def test_feeling_unknown_value_is_invalid(make_app: MakeApp) -> None:
    """A value outside the three is 422 `invalid` in the `{code, message}` shape, and nothing is stored."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        finished = await _completed(client, clock)
        unknown = await _feel(client, "great")
        view = await current(client)
    _refused(unknown, 422, "invalid")
    assert view["feeling"] is None
    assert view["revision"] == finished["revision"]


async def test_feeling_body_with_an_extra_key_is_refused(make_app: MakeApp) -> None:
    """A body with a key besides `feeling` gets FastAPI's own 422 list, and nothing is stored."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        finished = await _completed(client, clock)
        response = await client.post(
            FEELING, json={"feeling": "too_easy", "note": "hard"}, headers=AGENT
        )
        view = await current(client)
    assert response.status_code == 422, response.text
    assert isinstance(response.json()["detail"], list)
    assert view["feeling"] is None
    assert view["revision"] == finished["revision"]


async def test_feeling_in_history_and_mcp_list_sessions(make_app: MakeApp) -> None:
    """`GET /sessions` and MCP `list_sessions` show the feeling: set on one session, null on another."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started_with_mcp(clock, make_app) as (client, mcp_session):
        rated = await _completed(client, clock)
        response = await _feel(client, "just_right")
        clock.advance(timedelta(minutes=10))
        program = (await client.get(PROGRAMS)).json()[0]
        await start(client, program["id"], [rated["participants"][0]["id"]])
        unrated = await ok(client, "end")
        rest = (await client.get(SESSIONS)).json()
        mcp = await call(mcp_session, "list_sessions")
    assert response.status_code == 200, response.text
    assert [(view["id"], view["feeling"]) for view in rest["sessions"]] == [
        (unrated["id"], None),
        (rated["id"], "just_right"),
    ]
    assert mcp == rest
