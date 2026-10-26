"""Tests for the push channel `GET /api/v1/ws` (step 4 spec §3.6), with a frozen clock in Copenhagen time.

`receive_json()` has no timeout of its own, so every test asserts on the exact next message: a missing message shows
up as a wrong one. A read that never gets a message fails on the per-test timeout (`pytest-timeout`). The scheduler
runs every 0.05 s, so a test that only moves the clock sees what the loop's tick pushes.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
import logging
import threading
from typing import Any

from fastapi.testclient import TestClient
from ha_fitness_server import __version__
from ha_fitness_server.push import Hub
import pytest
from starlette.websockets import WebSocketDisconnect

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
    """Read `hello`, the first `today`, `session` (none) and `stats` of a new connection.

    Check the date and return `today`.
    """
    assert ws.receive_json() == {
        "type": "hello",
        "version": __version__,
        "api_version": 1,
    }
    today: dict[str, Any] = ws.receive_json()
    assert _today(today)[0] == date
    assert ws.receive_json() == {"type": "session", "data": None}
    assert ws.receive_json()["type"] == "stats"
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


class _FailOnceClock(FrozenClock):
    """A frozen clock that raises on its next read once armed, then reads normally again.

    `failed` is set at the raise, and `recovered` at the first normal read after it.
    """

    def __init__(self, start: datetime) -> None:
        """Start at `start`, not armed."""
        super().__init__(start)
        self.armed = False
        self.raised = 0
        self.error = RuntimeError("clock failure")
        self.failed = threading.Event()
        self.recovered = threading.Event()

    def now(self) -> datetime:
        """Raise once when armed, else return the frozen time."""
        if self.armed:
            self.armed = False
            self.raised += 1
            self.failed.set()
            raise self.error
        if self.failed.is_set():
            self.recovered.set()
        return super().now()


def test_failed_scheduler_run_is_logged_and_the_next_runs(
    make_app: MakeApp, caplog: pytest.LogCaptureFixture
) -> None:
    """A scheduler run that raises is logged at ERROR, and the next run still reconciles and pushes `today`."""
    clock = _FailOnceClock(local(2026, 10, 26, 23, 59))  # a Monday
    # The session loop ticks once at the start, then waits an hour: only the scheduler reads the clock below.
    app = make_app(
        settings_overrides={
            "timezone": ZONE,
            "scheduler_interval": FAST,
            "session_tick_max": 3600.0,
        },
        clock=clock,
    )
    with (
        caplog.at_level(logging.ERROR, logger="ha_fitness_server.app"),
        TestClient(app) as tc,
        tc.websocket_connect(WS) as ws,
    ):
        _connect_expect(ws, "2026-10-26")
        clock.armed = True
        assert clock.failed.wait(timeout=5)
        # No request: only a later scheduler run reconciles.
        clock.set(local(2026, 10, 27, 0, 1))
        # A dead scheduler never reads the clock again; checked first, as receive_json() has no timeout.
        assert clock.recovered.wait(timeout=5)
        assert _today(ws.receive_json()) == ("2026-10-27", [])
    assert clock.raised == 1
    assert any(
        record.levelno == logging.ERROR
        and record.name == "ha_fitness_server.app"
        and record.exc_info is not None
        and record.exc_info[1] is clock.error
        for record in caplog.records
    )


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


class _MidnightClock(FrozenClock):
    """A frozen clock that can cross midnight between a reconcile's own read and every read after it."""

    def __init__(self, start: datetime) -> None:
        """Start at `start`, with nothing armed."""
        super().__init__(start)
        self._then: datetime | None = None

    def arm(self, first: datetime, then: datetime) -> None:
        """Return `first` on the next read only, then `then` on every read after it."""
        self.set(first)
        self._then = then

    def now(self) -> datetime:
        """Return the frozen time; an armed clock moves on to its second time after this read."""
        moment = super().now()
        if self._then is not None:
            self.set(self._then)
            self._then = None
        return moment


@contextmanager
def _quiet_client(make_app: MakeApp, clock: FrozenClock) -> Iterator[TestClient]:
    """Run an app in Copenhagen time where only requests read the clock.

    The scheduler and the session loop wait a minute.
    """
    app = make_app(
        settings_overrides={
            "timezone": ZONE,
            "scheduler_interval": 60,
            "session_tick_max": 60,
        },
        clock=clock,
    )
    with TestClient(app) as tc:
        yield tc


def test_reconcile_publishes_today_for_the_date_it_handled(make_app: MakeApp) -> None:
    """A reconcile whose date ends while it runs pushes `today` for the date it handled, not the clock's new date."""
    clock = _MidnightClock(local(2026, 10, 26, 23, 59))  # a Monday
    with _quiet_client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        _create(tc, "Hver dag", ["mon", "tue"])
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-26")
        _today(ws.receive_json())
        clock.arm(local(2026, 10, 27, 23, 59), local(2026, 10, 28, 0, 1))
        assert tc.get("/api/v1/today").status_code == 200
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-27")
        assert _event(ws.receive_json()) == ("missed", "Hver dag", "2026-10-26")
        assert _today(ws.receive_json()) == (
            "2026-10-27",
            [("Hver dag", "2026-10-27", "due")],
        )


def test_skip_publishes_today_for_the_date_it_reconciled(make_app: MakeApp) -> None:
    """A skip whose date ends while it runs pushes `today` for the date its reconcile handled."""
    clock = _MidnightClock(local(2026, 10, 26, 9))  # a Monday
    with _quiet_client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        _create(tc, "Hver dag", ["mon", "tue"])
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-10-26")
        [day_id] = [day["id"] for day in ws.receive_json()["data"]["open"]]
        clock.arm(local(2026, 10, 26, 23, 59), local(2026, 10, 27, 0, 1))
        assert tc.post(f"{DAYS}/{day_id}/skip").status_code == 200
        assert _event(ws.receive_json()) == ("skipped", "Hver dag", "2026-10-26")
        assert _today(ws.receive_json()) == ("2026-10-26", [])


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


async def test_hub_drops_a_subscriber_that_falls_behind() -> None:
    """A subscriber that never reads is dropped once it is 100 behind; one that reads gets every message.

    The hub is tested directly: the test transport has no backpressure, so a slow websocket can't be made.
    """
    hub = Hub()
    async with (
        hub.subscribe() as (slow, slow_dropped),
        hub.subscribe() as (reader, reader_dropped),
    ):
        received: list[dict[str, Any]] = []
        for number in range(101):
            if number == 100:
                assert not slow_dropped.is_set()
                assert slow.qsize() == 100
            hub.broadcast([{"type": "event", "number": number}])
            while not reader.empty():
                received.append(reader.get_nowait())
        assert slow_dropped.is_set()
        assert not reader_dropped.is_set()
        assert received == [{"type": "event", "number": n} for n in range(101)]
        held = slow.qsize()
        hub.broadcast([{"type": "event", "number": 101}])
        assert slow.qsize() == held
        assert reader.get_nowait() == {"type": "event", "number": 101}


EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def test_catch_up_burst_reaches_the_client_in_order(make_app: MakeApp) -> None:
    """A catch-up over 250 days pushes every `missed`, then `due`, `today` and `stats`, in order, without a drop.

    The 251 events are far more than a subscriber's backlog limit, but they come as one batch.
    """
    clock = FrozenClock(local(2026, 1, 5, 9))  # a Monday
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-01-05")
        _create(tc, "Hver dag", EVERY_DAY)
        assert _event(ws.receive_json()) == ("due", "Hver dag", "2026-01-05")
        _today(ws.receive_json())
        clock.set(local(2026, 9, 12, 9))  # 250 days on
        start = date(2026, 1, 5)
        expected = [
            ("missed", "Hver dag", (start + timedelta(days=n)).isoformat())
            for n in range(249)
        ]
        expected += [
            ("due", "Hver dag", "2026-09-12"),
            ("missed", "Hver dag", "2026-09-11"),
        ]
        received = [_event(ws.receive_json()) for _ in expected]
        assert received == expected
        assert _today(ws.receive_json()) == (
            "2026-09-12",
            [("Hver dag", "2026-09-12", "due")],
        )
        assert ws.receive_json()["type"] == "stats"


async def test_hub_queues_a_whole_batch_unless_already_behind() -> None:
    """A batch longer than the backlog limit is queued whole; a subscriber already 100 behind is dropped on the next.

    The hub is tested directly, like the test above.
    """
    hub = Hub()
    async with hub.subscribe() as (queue, dropped):
        hub.broadcast([])
        hub.broadcast([{"type": "event", "number": n} for n in range(250)])
        assert not dropped.is_set()
        assert queue.qsize() == 250
        hub.broadcast([])
        assert not dropped.is_set()
        hub.broadcast([{"type": "event", "number": 250}])
        assert dropped.is_set()
        assert queue.qsize() == 250


def test_a_client_100_behind_is_closed_with_1013(make_app: MakeApp) -> None:
    """A client still 100 messages behind when the next publish comes is closed with 1013 ("try again later").

    Setup only: the hub gets 101 single publishes in one loop callback, so the websocket can't send any in between.
    """
    clock = FrozenClock(local(2026, 10, 26, 9))
    with _client(make_app, clock) as tc, tc.websocket_connect(WS) as ws:
        _connect_expect(ws, "2026-10-26")
        hub: Hub = tc.app.state.hub  # type: ignore[attr-defined]

        def burst() -> None:
            for number in range(101):
                hub.broadcast([{"type": "event", "number": number}])

        tc.portal.call(burst)  # type: ignore[union-attr]
        assert _close_code(ws, limit=102) == 1013


def _close_code(ws: Any, limit: int) -> int:
    """Read up to `limit` messages until the add-on closes the websocket; return the close code."""
    for _ in range(limit):
        try:
            ws.receive_json()
        except WebSocketDisconnect as closed:
            return closed.code
    raise AssertionError(f"still open after {limit} messages")
