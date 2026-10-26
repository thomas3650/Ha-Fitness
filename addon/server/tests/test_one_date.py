"""One date per request around midnight (#79): a request's checks, `today` and `stats` all use the date it reconciled.

Through REST and the push channel, in Copenhagen time, on the program `SMALL` (its phases are in
`tests/session_helpers.py`). The push messages are read from the hub every websocket relays, in the order the add-on
publishes them. The scheduler and the session loop wait a minute, so only the requests read the clock. A
`MidnightClock` gives a request's reconcile its own read of Saturday 31 October 23:59:59, and every read after it
Sunday 1 November 00:00:01. The stats show their date only as `month`, so the tests cross the end of a month.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ha_fitness_server.push import Hub, Message
import httpx

from tests.conftest import FrozenClock, MakeApp, MidnightClock, running
from tests.session_helpers import (
    AGENT,
    SESSION,
    TODAY,
    WS,
    at,
    create_small,
    make_session_app,
    ok,
    open_day,
    set_people,
    start,
)
from tests.test_people import THOMAS
from tests.test_scheduler import ZONE, local

SATURDAY = "2026-10-31"
SUNDAY = "2026-11-01"
SATURDAY_NIGHT = local(2026, 10, 31, 23, 59)
LAST_READ = at(SATURDAY_NIGHT, 59)  # Saturday 23:59:59
FIRST_READ = at(local(2026, 11, 1, 0, 0), 1)  # Sunday 00:00:01

type Drain = Callable[[], Awaitable[list[Message]]]


@asynccontextmanager
async def _app(
    clock: FrozenClock, make_app: MakeApp
) -> AsyncIterator[tuple[httpx.AsyncClient, Drain]]:
    """Run a session app where only requests read the clock; yield an HTTP client and `drain` (messages since last)."""
    app: FastAPI = make_session_app(
        clock, make_app, {"scheduler_interval": 60, "session_tick_max": 60}
    )
    async with running(app) as client:
        hub: Hub = app.state.hub
        async with hub.subscribe() as (queue, _dropped):

            async def drain() -> list[Message]:
                # A publish is handed to the event loop before the request returns; let it run.
                await asyncio.sleep(0.01)
                messages: list[Message] = []
                while not queue.empty():
                    messages.append(queue.get_nowait())
                return messages

            yield client, drain


def _todays(messages: list[Message]) -> list[tuple[str, list[tuple[str, str, str]]]]:
    """Return the `today` messages as (date, [(name, date, state)])."""
    return [
        (
            message["data"]["date"],
            [
                (day["program_name"], day["date"], day["state"])
                for day in message["data"]["open"]
            ],
        )
        for message in messages
        if message["type"] == "today"
    ]


def _months(messages: list[Message]) -> list[str]:
    """Return the `month` of each `stats` message."""
    return [
        message["data"]["month"] for message in messages if message["type"] == "stats"
    ]


def _day_events(messages: list[Message]) -> list[tuple[str, str]]:
    """Return the training-day events among `messages` as (event, date)."""
    return [
        (message["event"], message["training_day"]["date"])
        for message in messages
        if message["type"] == "event" and "training_day" in message
    ]


async def _get_today(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _then_sunday(
    client: httpx.AsyncClient, drain: Drain
) -> tuple[dict[str, Any], list[Message]]:
    """Read `/today` on Sunday, which reconciles Sunday; return the view and the messages it published."""
    view = await _get_today(client)
    return view, await drain()


def _moved_on_together(view: dict[str, Any], messages: list[Message]) -> None:
    """Check that the Sunday reconcile moved `today` and `stats` on to Sunday together."""
    assert view["date"] == SUNDAY
    assert [today[0] for today in _todays(messages)] == [SUNDAY]
    assert _months(messages) == ["2026-11"]


async def test_start_across_midnight_publishes_nothing_for_the_new_date(
    make_app: MakeApp,
) -> None:
    """A start whose reconcile reads Saturday publishes no `today` or `stats` for Sunday, whose days aren't made."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sat", "sun"])
        await create_small(client, "Store", weekdays=["sat"])
        day_id = await open_day(client, lille["id"])
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        await start(client, lille["id"], [thomas], day_id)
        messages = await drain()
        sunday, later = await _then_sunday(client, drain)
    assert _todays(messages) == []
    assert _months(messages) == []
    _moved_on_together(sunday, later)
    assert ("Lille", SUNDAY, "due") in [
        (day["program_name"], day["date"], day["state"]) for day in sunday["open"]
    ]


async def test_finish_across_midnight_publishes_today_and_stats_for_one_date(
    make_app: MakeApp,
) -> None:
    """A counted finish just after midnight, before any reconcile of Sunday, publishes Saturday's `today` and stats."""
    clock = FrozenClock(at(SATURDAY_NIGHT, 30))
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sat"])
        await create_small(client, "Store", weekdays=["sat"])
        await start(client, lille["id"], [thomas], await open_day(client, lille["id"]))
        await drain()
        clock.set(at(SATURDAY_NIGHT, 30 + 40))  # Sunday 00:00:10, in round 1's rest
        ended = await ok(client, "end")
        messages = await drain()
        sunday, later = await _then_sunday(client, drain)
    assert ended["counted"] is True
    assert _day_events(messages) == [("done", SATURDAY)]
    assert _todays(messages) == [(SATURDAY, [("Store", SATURDAY, "due")])]
    assert _months(messages) == ["2026-10"]
    _moved_on_together(sunday, later)


async def test_program_write_across_midnight_publishes_one_date(
    make_app: MakeApp,
) -> None:
    """A program write whose first reconcile reads Saturday makes Saturday's day and publishes Saturday only."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        await set_people(client, THOMAS)
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        await create_small(client, "Lille", weekdays=["sat"])
        messages = await drain()
        sunday, later = await _then_sunday(client, drain)
    assert _day_events(messages) == [("due", SATURDAY)]
    assert _todays(messages) == [(SATURDAY, [("Lille", SATURDAY, "due")])]
    assert _months(messages) == []
    _moved_on_together(sunday, later)


async def test_early_start_across_midnight_checks_the_reconciled_date(
    make_app: MakeApp,
) -> None:
    """An early start for Sunday whose reconcile reads Saturday is checked against Saturday's upcoming: accepted."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sun"])
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        body = {"program_id": lille["id"], "participants": [thomas], "date": SUNDAY}
        response = await client.post(SESSION, json=body, headers=AGENT)
        messages = await drain()
        sunday, later = await _then_sunday(client, drain)
    assert response.status_code == 201, response.text
    view = response.json()
    [today] = [message for message in messages if message["type"] == "today"]
    assert today["data"]["date"] == SATURDAY
    assert today["data"]["open"] == []
    assert [
        (entry["date"], entry["program_name"], entry["startable"])
        for entry in today["data"]["upcoming"]
    ] == [(SUNDAY, "Lille", False)]
    assert _months(messages) == []
    assert [(day["id"], day["date"], day["state"]) for day in sunday["open"]] == [
        (view["training_day_id"], SUNDAY, "due")
    ]
    _moved_on_together(sunday, later)


def test_connect_across_midnight_sends_one_date(make_app: MakeApp) -> None:
    """A connect whose reconcile reads Saturday sends `today` and `stats` for Saturday, and reconciles no other date."""
    clock = MidnightClock(SATURDAY_NIGHT)
    app = make_app(
        settings_overrides={
            "timezone": ZONE,
            "scheduler_interval": 60,
            "session_tick_max": 60,
        },
        clock=clock,
    )
    with TestClient(app) as tc:
        clock.arm(LAST_READ, FIRST_READ)
        with tc.websocket_connect(WS) as ws:
            assert ws.receive_json()["type"] == "hello"
            today = ws.receive_json()
            assert ws.receive_json() == {"type": "session", "data": None}
            stats = ws.receive_json()
    assert today["type"] == "today"
    assert stats["type"] == "stats"
    assert (today["data"]["date"], stats["data"]["month"]) == (SATURDAY, "2026-10")
