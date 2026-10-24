"""Tests for the push channel `GET /api/v1/ws` (step 4 spec §3.6), with a frozen clock in Copenhagen time.

`receive_json()` has no timeout, so every test asserts on the exact next message: a missing message shows up as a
wrong one. The scheduler runs every 0.05 s, so a test that only moves the clock sees what the loop's tick pushes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from fastapi.testclient import TestClient
from ha_fitness_server import __version__

from tests.conftest import FrozenClock, MakeApp
from tests.test_scheduler import FIVE, ZONE, local

WS = "/api/v1/ws"
PROGRAMS = "/api/v1/programs"
DAYS = "/api/v1/training-days"
FAST = 0.05


@contextmanager
def _client(
    make_app: MakeApp, clock: FrozenClock, interval: float = FAST
) -> Iterator[TestClient]:
    """Run an app in Copenhagen time on the frozen clock, with the scheduler every `interval` seconds."""
    app = make_app(
        settings_overrides={"timezone": ZONE, "scheduler_interval": interval},
        clock=clock,
    )
    with TestClient(app) as tc:
        yield tc


def _create(tc: TestClient, name: str, weekdays: list[str]) -> int:
    """Create a program of five stations; it must succeed. Return its id."""
    document = {
        "name": name,
        "weekdays": weekdays,
        "stations": [{"exercise": exercise} for exercise in FIVE],
    }
    response = tc.post(PROGRAMS, json=document)
    assert response.status_code == 201, response.text
    program_id: int = response.json()["id"]
    return program_id


def _today(message: dict[str, Any]) -> tuple[str, list[tuple[str, str, str]]]:
    """Return a `today` message as (date, [(name, date, state)]); fail on another type."""
    assert message["type"] == "today", message
    data = message["data"]
    return data["date"], [
        (day["program_name"], day["date"], day["state"]) for day in data["open"]
    ]


def _event(message: dict[str, Any]) -> tuple[str, str, str]:
    """Return an event message as (event, program name, date); fail on another type."""
    assert message["type"] == "event", message
    day = message["training_day"]
    assert set(day) == {"id", "program_id", "program_name", "date"}
    return message["event"], day["program_name"], day["date"]


def _connect_expect(ws: Any, date: str) -> dict[str, Any]:
    """Read `hello`, the first `today` and `session` (none) of a new connection; check the date and return `today`."""
    assert ws.receive_json() == {
        "type": "hello",
        "version": __version__,
        "api_version": 1,
    }
    today: dict[str, Any] = ws.receive_json()
    assert _today(today)[0] == date
    assert ws.receive_json() == {"type": "session", "data": None}
    return today


def test_ws_hello_then_today(make_app: MakeApp) -> None:
    """On connect the add-on sends `hello`, then the same `today` that `GET /today` returns."""
    clock = FrozenClock(local(2026, 10, 28, 9))  # a Wednesday
    with _client(make_app, clock) as tc:
        _create(tc, "Onsdag", ["wed"])
        with tc.websocket_connect(WS) as ws:
            today = _connect_expect(ws, "2026-10-28")
            assert today["data"] == tc.get("/api/v1/today").json()
            assert _today(today)[1] == [("Onsdag", "2026-10-28", "due")]


def test_skip_publishes_today_and_skipped(make_app: MakeApp) -> None:
    """A skip pushes the `skipped` event, then a `today` with the day gone."""
    clock = FrozenClock(local(2026, 10, 28, 9))  # a Wednesday
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-28")
        _create(tc, "Onsdag", ["wed"])
        assert _event(ws.receive_json()) == ("due", "Onsdag", "2026-10-28")
        today = ws.receive_json()
        assert _today(today)[1] == [("Onsdag", "2026-10-28", "due")]
        [day_id] = [day["id"] for day in today["data"]["open"]]
        response = tc.post(f"{DAYS}/{day_id}/skip")
        assert response.status_code == 200, response.text
        skipped = ws.receive_json()
        assert _event(skipped) == ("skipped", "Onsdag", "2026-10-28")
        assert skipped["training_day"]["id"] == day_id
        assert _today(ws.receive_json()) == ("2026-10-28", [])


def test_midnight_publishes_today_without_creates(make_app: MakeApp) -> None:
    """At midnight the scheduler's tick alone pushes a new `today`, though no day is created."""
    clock = FrozenClock(local(2026, 10, 26, 23, 59))  # a Monday
    with _client(make_app, clock) as tc:
        _create(tc, "Fredag", ["fri"])
        with tc.websocket_connect(WS) as ws:
            first = _connect_expect(ws, "2026-10-26")
            assert first["data"]["next"] == {
                "date": "2026-10-30",
                "programs": ["Fredag"],
            }
            clock.set(local(2026, 10, 27, 0, 1))  # no request: only the tick reconciles
            message = ws.receive_json()
            assert _today(message) == ("2026-10-27", [])
            assert message["data"]["next"] == first["data"]["next"]


def test_due_event_only_for_today(make_app: MakeApp) -> None:
    """A day made for today fires `due`; a day made for a past date during catch-up fires nothing."""
    clock = FrozenClock(local(2026, 10, 26, 9))  # a Monday
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        _create(tc, "Mandag", ["mon", "wed"])
        assert _event(ws.receive_json()) == ("due", "Mandag", "2026-10-26")
        assert _today(ws.receive_json()) == (
            "2026-10-26",
            [("Mandag", "2026-10-26", "due")],
        )
        # Three days off: Wednesday's day is made late during catch-up, and closes Monday's.
        clock.set(local(2026, 10, 29, 9))
        assert _event(ws.receive_json()) == ("missed", "Mandag", "2026-10-26")
        assert _today(ws.receive_json()) == (
            "2026-10-29",
            [("Mandag", "2026-10-28", "late")],
        )


def test_missed_event_when_next_day_begins(make_app: MakeApp) -> None:
    """The next training day's start fires `due` for it, then `missed` for the open day before it."""
    clock = FrozenClock(local(2026, 10, 26, 9))  # a Monday
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        _create(tc, "Hver dag", ["mon", "tue"])
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-26")
        _today(ws.receive_json())
        clock.set(local(2026, 10, 27, 0, 1))
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-27")
        assert _event(ws.receive_json()) == ("missed", "Hver dag", "2026-10-26")
        assert _today(ws.receive_json()) == (
            "2026-10-27",
            [("Hver dag", "2026-10-27", "due")],
        )


def test_program_write_after_midnight_publishes_rollover_first(
    make_app: MakeApp,
) -> None:
    """A program write just after midnight pushes the rollover's `today` first, then the write's effects.

    The scheduler waits a minute here, so the write's own reconcile does the rollover.
    """
    clock = FrozenClock(local(2026, 10, 26, 23, 59))  # a Monday
    with _client(make_app, clock, interval=60) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        clock.set(local(2026, 10, 27, 0, 0))
        _create(tc, "Tirsdag", ["tue"])
        assert _today(ws.receive_json()) == ("2026-10-27", [])
        assert _event(ws.receive_json()) == ("due", "Tirsdag", "2026-10-27")
        assert _today(ws.receive_json()) == (
            "2026-10-27",
            [("Tirsdag", "2026-10-27", "due")],
        )


def test_connect_sends_one_today_and_the_events_of_its_reconcile(
    make_app: MakeApp,
) -> None:
    """A connect that reconciles a new date sends one `today`, then that reconcile's events, then live pushes.

    The scheduler waits a minute here, so the connect's own reconcile does the rollover.
    """
    clock = FrozenClock(local(2026, 10, 26, 9))  # a Monday
    with _client(make_app, clock, interval=60) as tc:
        _create(tc, "Hver dag", ["mon", "tue"])
        clock.set(local(2026, 10, 27, 9))
        with tc.websocket_connect(WS) as ws:
            today = _connect_expect(ws, "2026-10-27")
            assert _today(today)[1] == [("Hver dag", "2026-10-27", "due")]
            assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-27")
            assert _event(ws.receive_json()) == ("missed", "Hver dag", "2026-10-26")
            [day_id] = [day["id"] for day in today["data"]["open"]]
            assert tc.post(f"{DAYS}/{day_id}/skip").status_code == 200
            assert _event(ws.receive_json())[0] == "skipped"
            assert _today(ws.receive_json()) == ("2026-10-27", [])


def test_messages_from_the_client_are_ignored(make_app: MakeApp) -> None:
    """Whatever the client sends is ignored; the pushes go on."""
    clock = FrozenClock(local(2026, 10, 26, 23, 59))  # a Monday
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        ws.send_json({"type": "unknown"})
        ws.send_text("hello?")
        clock.set(local(2026, 10, 27, 0, 1))
        assert _today(ws.receive_json()) == ("2026-10-27", [])
