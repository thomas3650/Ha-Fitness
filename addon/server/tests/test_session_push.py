"""Tests for the session's push messages (step 5 spec §3.5): the loop, the events, the pause limit and the null push.

Through the websocket with `TestClient` alone, on a frozen clock in Copenhagen time, on the program `SMALL` (its
phases are in `tests/session_helpers.py`). The session loop wakes every 0.05 s here, so a test that only moves the
clock sees what the loop pushes. `receive_json()` has no timeout, so every test asserts on the exact next message.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient
from ha_fitness_server import __version__

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    AGENT,
    SESSION,
    SMALL_END,
    SMALL_STARTS,
    TODAY,
    WS,
    at,
    make_session_app,
    tc_program,
    tc_setup,
    tc_start,
    ws_connect,
    ws_session,
)
from tests.test_scheduler import local

WEDNESDAY_9 = local(2026, 10, 28, 9)
FAST = 0.05
LIMIT = timedelta(minutes=30)
KEPT = timedelta(minutes=5)


@contextmanager
def _client(
    make_app: MakeApp, clock: FrozenClock, tick_max: float = FAST
) -> Iterator[TestClient]:
    """Run a session app with the session loop waking at least every `tick_max` seconds."""
    app = make_session_app(clock, make_app, {"session_tick_max": tick_max})
    with TestClient(app) as tc:
        yield tc


def _day(tc: TestClient, program_id: int) -> int:
    """Return the id of the program's open day."""
    [day_id] = [
        day["id"]
        for day in tc.get(TODAY).json()["open"]
        if day["program_id"] == program_id
    ]
    return int(day_id)


def _ok(tc: TestClient, command: str) -> dict[str, Any]:
    """Send a session command; it must succeed. Return the view."""
    response = tc.post(f"{SESSION}/{command}", headers=AGENT)
    assert response.status_code == 200, response.text
    view: dict[str, Any] = response.json()
    return view


def _event(message: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    """Return a session event as (event, its `session` part); fail on another message."""
    assert message["type"] == "event", message
    return message["event"], message["session"]


def test_ws_session_after_today_on_connect(make_app: MakeApp) -> None:
    """On connect `session` follows `today`: null without a session, else the same view `GET /session` returns."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        with tc.websocket_connect(WS) as ws:
            assert ws.receive_json() == {
                "type": "hello",
                "version": __version__,
                "api_version": 1,
            }
            assert ws.receive_json()["type"] == "today"
            assert ws.receive_json() == {"type": "session", "data": None}
        tc_start(tc, program_id, thomas)
        with tc.websocket_connect(WS) as ws:
            message = ws_connect(ws)
            view = tc.get(SESSION).json()
    assert message == {"type": "session", "data": view}
    assert view["status"] == "running"


def test_loop_wakes_at_deadline(make_app: MakeApp) -> None:
    """With no request, the loop moves the session on at the countdown's deadline: `session`, then `phase_changed`."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            first = tc_start(tc, program_id, thomas)
            assert ws_session(ws.receive_json()) == first
            assert _event(ws.receive_json())[0] == "session_started"
            clock.set(at(WEDNESDAY_9, SMALL_STARTS[1]))
            moved = ws_session(ws.receive_json())
            event, part = _event(ws.receive_json())
    assert first["phase"]["kind"] == "countdown"
    assert (moved["phase"]["index"], moved["phase"]["kind"]) == (1, "work")
    assert moved["revision"] == first["revision"] + 1
    assert event == "phase_changed"
    assert part["phase"] == moved["phase"]


def test_ws_events_session_started_completed_ended_done(make_app: MakeApp) -> None:
    """A day's session: completed by the loop with `done`, `today` and `stats`; an extra one: ended, not counted."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        day_id = _day(tc, program_id)
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            tc_start(tc, program_id, thomas, day_id)
            begun = ws_session(ws.receive_json())
            started_event = _event(ws.receive_json())
            clock.set(at(WEDNESDAY_9, SMALL_END))
            completed = ws_session(ws.receive_json())
            completed_event = _event(ws.receive_json())
            done = ws.receive_json()
            today = ws.receive_json()
            stats = ws.receive_json()
            tc_start(tc, program_id, thomas)
            extra = ws_session(ws.receive_json())
            assert _event(ws.receive_json())[0] == "session_started"
            _ok(tc, "end")
            ended = ws_session(ws.receive_json())
            ended_event = _event(ws.receive_json())
    assert started_event == (
        "session_started",
        {"id": begun["id"], "program_name": "Lille", "training_day_id": day_id},
    )
    assert completed["status"] == "completed"
    assert completed_event == (
        "session_completed",
        {"id": begun["id"], "program_name": "Lille", "training_day_id": day_id},
    )
    assert done["type"] == "event"
    assert done["event"] == "done"
    assert done["training_day"]["id"] == day_id
    assert today["type"] == "today"
    assert today["data"]["open"] == []
    assert stats["type"] == "stats"
    assert stats["data"]["counting_from"] == "2026-10-28"
    assert ended["status"] == "ended"
    assert ended_event == (
        "session_ended",
        {
            "id": extra["id"],
            "program_name": "Lille",
            "training_day_id": None,
            "counted": False,
        },
    )


def test_pause_limit_ends_after_30_minutes_on_ws(make_app: MakeApp) -> None:
    """The loop ends a session paused for 30 minutes: its finished view, then `session_ended`; `GET /session` agrees."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            _ok(tc, "pause")
            paused = ws_session(ws.receive_json())
            clock.set(WEDNESDAY_9 + LIMIT)
            ended = ws_session(ws.receive_json())
            event, part = _event(ws.receive_json())
            read = tc.get(SESSION).json()
    assert paused["status"] == "paused"
    assert ended["status"] == "ended"
    assert ended == {**read, "server_time": ended["server_time"]}
    assert (event, part["counted"]) == ("session_ended", False)


def test_null_push_after_finished_window(make_app: MakeApp) -> None:
    """The loop sends `session: null` once the finished view's 5 minutes are over; a new session cancels it."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            clock.set(at(WEDNESDAY_9, 1))
            first = _ok(tc, "end")
            assert ws_session(ws.receive_json())["status"] == "ended"
            assert _event(ws.receive_json())[0] == "session_ended"
            clock.set(at(WEDNESDAY_9, 1) + KEPT)
            null = ws.receive_json()
            # A second session, finished and followed by a third before its window ends: no null while that one runs.
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            second_end = clock.now() + timedelta(seconds=1)
            clock.set(second_end)
            _ok(tc, "end")
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            _ok(tc, "pause")
            ws_session(ws.receive_json())
            clock.set(second_end + KEPT + timedelta(seconds=1))
            resumed = _ok(tc, "resume")
            after = ws.receive_json()
    assert first["status"] == "ended"
    assert null == {"type": "session", "data": None}
    assert after == {"type": "session", "data": resumed}


def test_command_after_the_last_deadline_keeps_the_completion(
    make_app: MakeApp,
) -> None:
    """`end` just after the last deadline is a 409, but the tick's completion before it stays and is pushed.

    The loop waits an hour here, so only the command's own tick can complete the session. A skip of another day
    then pushes `skipped`: the completion's messages, and the `stats` of its first counted session, must come before
    it.
    """
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock, tick_max=3600) as tc:
        thomas, program_id = tc_setup(tc)
        other_day = _day(tc, tc_program(tc, "Anden"))
        with tc.websocket_connect(WS) as ws:
            ws_connect(ws)
            tc_start(tc, program_id, thomas)
            ws_session(ws.receive_json())
            _event(ws.receive_json())
            clock.set(at(WEDNESDAY_9, SMALL_END + 1))
            refused = tc.post(f"{SESSION}/end", headers=AGENT)
            skipped = tc.post(f"/api/v1/training-days/{other_day}/skip")
            assert skipped.status_code == 200, skipped.text
            completed = ws_session(ws.receive_json())
            event = _event(ws.receive_json())[0]
            stats = ws.receive_json()
            after = ws.receive_json()
    assert refused.status_code == 409
    assert completed["status"] == "completed"
    assert event == "session_completed"
    assert stats["type"] == "stats"
    assert (after["type"], after["event"]) == ("event", "skipped")


def test_null_push_after_a_restart_inside_the_window(make_app: MakeApp) -> None:
    """A restart inside a finished view's 5 minutes keeps that view on connect, and the loop still sends the null."""
    clock = FrozenClock(WEDNESDAY_9)
    with _client(make_app, clock) as tc:
        thomas, program_id = tc_setup(tc)
        tc_start(tc, program_id, thomas)
        clock.set(at(WEDNESDAY_9, 1))
        ended = _ok(tc, "end")
    clock.set(at(WEDNESDAY_9, 1) + KEPT - timedelta(seconds=1))
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        shown = ws_session(ws_connect(ws))
        clock.set(at(WEDNESDAY_9, 1) + KEPT)
        null = ws.receive_json()
    assert shown == {**ended, "server_time": shown["server_time"]}
    assert null == {"type": "session", "data": None}
