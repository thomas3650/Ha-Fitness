"""One date per request around midnight (#79): a request's checks, `today` and `stats` all use the date it reconciled.

Through REST and the push channel, in Copenhagen time, on the program `SMALL` (its phases are in
`tests/session_helpers.py`). The push messages are read from the hub every websocket relays, in the order the add-on
publishes them. The scheduler and the session loop wait a minute, so only the requests read the clock (one test lets
the loop tick). A `MidnightClock` gives a request's first read Saturday 31 October 23:59:59, and every read after it
Sunday 1 November 00:00:01. A request's reconcile uses that first read; a program write and a session start use it
for their stamps and their tick too (#97). The stats show their date only as `month`, so the tests cross the end of
a month.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from ha_fitness_server.push import Hub, Message
from ha_fitness_server.sessions import PAUSE_LIMIT
import httpx

from tests.conftest import FrozenClock, MakeApp, MidnightClock, running
from tests.session_helpers import (
    AGENT,
    CHANGES,
    DAYS,
    PROGRAMS,
    SESSION,
    SMALL_END,
    TODAY,
    WS,
    at,
    create_small,
    days,
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
    clock: FrozenClock, make_app: MakeApp, tick_max: float = 60
) -> AsyncIterator[tuple[httpx.AsyncClient, Drain]]:
    """Run a session app where only requests read the clock; yield an HTTP client and `drain` (messages since last).

    A short `tick_max` lets the session loop tick (and read the clock) too; the scheduler still waits a minute.
    """
    app: FastAPI = make_session_app(
        clock, make_app, {"scheduler_interval": 60, "session_tick_max": tick_max}
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


async def _newest_change(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return the newest change-log entry."""
    response = await client.get(CHANGES)
    assert response.status_code == 200, response.text
    newest: dict[str, Any] = response.json()[0]
    return newest


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


async def test_program_create_across_midnight_stamps_its_one_read(
    make_app: MakeApp,
) -> None:
    """A program create whose one read is Saturday 23:59:59 is stamped with that instant, not a later one."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        await set_people(client, THOMAS)
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        created = await create_small(client, "Lille", weekdays=["sat"])
        messages = await drain()
        logged = await _newest_change(client)
    assert datetime.fromisoformat(created["created_at"]) == LAST_READ
    assert datetime.fromisoformat(created["updated_at"]) == LAST_READ
    assert (logged["action"], datetime.fromisoformat(logged["at"])) == (
        "program.created",
        LAST_READ,
    )
    assert _todays(messages) == [(SATURDAY, [("Lille", SATURDAY, "due")])]
    # The open day leaves the stats as they were: none go out, so none for Sunday's month.
    assert _months(messages) == []


async def test_program_update_across_midnight_stamps_and_publishes_one_date(
    make_app: MakeApp,
) -> None:
    """An update whose one read is Saturday 23:59:59 is stamped with it and publishes Saturday's day and `today`."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sun"])
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        document = {**lille["program"], "weekdays": ["sat"]}
        response = await client.put(f"{PROGRAMS}/{lille['id']}", json=document)
        messages = await drain()
        logged = await _newest_change(client)
        sunday, later = await _then_sunday(client, drain)
    assert response.status_code == 200, response.text
    updated = response.json()
    assert datetime.fromisoformat(updated["updated_at"]) == LAST_READ
    assert updated["created_at"] == lille["created_at"]
    assert (logged["action"], datetime.fromisoformat(logged["at"])) == (
        "program.updated",
        LAST_READ,
    )
    assert _day_events(messages) == [("due", SATURDAY)]
    assert _todays(messages) == [(SATURDAY, [("Lille", SATURDAY, "due")])]
    assert _months(messages) == []
    _moved_on_together(sunday, later)


async def test_program_activate_across_midnight_stamps_its_one_read(
    make_app: MakeApp,
) -> None:
    """Switching a program on with one read of Saturday 23:59:59 stamps and logs it then and makes Saturday's day."""
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sat"], active=False)
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        response = await client.put(
            f"{PROGRAMS}/{lille['id']}/active", json={"active": True}
        )
        messages = await drain()
        logged = await _newest_change(client)
    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["updated_at"]) == LAST_READ
    assert (logged["action"], datetime.fromisoformat(logged["at"])) == (
        "program.activated",
        LAST_READ,
    )
    assert _day_events(messages) == [("due", SATURDAY)]
    assert _todays(messages) == [(SATURDAY, [("Lille", SATURDAY, "due")])]


async def test_start_across_midnight_settles_an_old_early_day_for_its_date(
    make_app: MakeApp,
) -> None:
    """A start whose one read is Saturday ends an early Sunday session paused too long and removes its Sunday day.

    The session was started early for Sunday and paused before a round, so it ends uncounted at the pause limit. Its
    day is dated after the start's date, Saturday, so it goes, and no `due` for Sunday is sent.
    """
    evening = local(2026, 10, 31, 23, 0)
    clock = MidnightClock(evening)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sun"])
        store = await create_small(client, "Store", weekdays=["sat"])
        body = {"program_id": lille["id"], "participants": [thomas], "date": SUNDAY}
        early = await client.post(SESSION, json=body, headers=AGENT)
        assert early.status_code == 201, early.text
        early_day = early.json()["training_day_id"]
        await ok(client, "pause")
        store_day = await open_day(client, store["id"])
        await drain()
        assert at(evening, 1) + PAUSE_LIMIT < LAST_READ
        clock.arm(LAST_READ, FIRST_READ)
        await start(client, store["id"], [thomas], store_day)
        messages = await drain()
        listed = await days(client, SATURDAY, SUNDAY)
    events = [message.get("event") for message in messages]
    assert "session_ended" in events
    assert "session_started" in events
    assert ("due", SUNDAY) not in _day_events(messages)
    assert SUNDAY not in [today[0] for today in _todays(messages)]
    assert early_day not in [day["id"] for day in listed]


async def test_early_start_across_midnight_stamps_its_day_with_its_one_read(
    make_app: MakeApp,
) -> None:
    """An early start for Sunday whose one read is Saturday makes the day early, so an uncounted end sends its `due`.

    The day is stamped with the start's read, Saturday. The session ends before a round just after midnight: the day
    was made early and its date is now today, so it stays due and the end's batch carries its `due` (#97).
    """
    clock = MidnightClock(SATURDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sun"])
        await drain()
        clock.arm(LAST_READ, FIRST_READ)
        body = {"program_id": lille["id"], "participants": [thomas], "date": SUNDAY}
        response = await client.post(SESSION, json=body, headers=AGENT)
        assert response.status_code == 201, response.text
        early_day = response.json()["training_day_id"]
        await drain()
        clock.set(at(LAST_READ, 11))  # Sunday 00:00:10, in round 1's first work phase
        ended = await ok(client, "end")
        messages = await drain()
    assert ended["counted"] is False
    [due] = [message for message in messages if message.get("event") == "due"]
    assert (due["training_day"]["id"], due["training_day"]["date"]) == (
        early_day,
        SUNDAY,
    )


async def test_counting_from_set_after_midnight_leaves_the_old_dates_stats_alone(
    make_app: MakeApp,
) -> None:
    """A first counted session finished by the loop just after midnight sets `counting_from` to Sunday.

    No reconcile of Sunday has run, so its batch's stats are for Saturday's month. Saturday's skipped day is before
    `counting_from`, so it doesn't count: the numbers are what they'd be with `counting_from` null.
    """
    clock = FrozenClock(SATURDAY_NIGHT)
    async with _app(clock, make_app, tick_max=0.05) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        lille = await create_small(client, "Lille", weekdays=["sat"])
        store = await create_small(client, "Store", weekdays=["sat"])
        skipped = await client.post(
            f"{DAYS}/{await open_day(client, store['id'])}/skip", headers=AGENT
        )
        assert skipped.status_code == 200, skipped.text
        await start(client, lille["id"], [thomas], await open_day(client, lille["id"]))
        await drain()
        clock.set(at(SATURDAY_NIGHT, SMALL_END + 10))  # Sunday 00:00:30
        messages: list[Message] = []
        for _ in range(100):
            messages += await drain()
            # The finish's `stats` come in a second batch, after its session messages.
            if any(message["type"] == "stats" for message in messages):
                break
    assert any(message["type"] == "stats" for message in messages), (
        "no stats batch arrived after the finish"
    )
    assert "session_completed" in [message.get("event") for message in messages]
    [stats] = [message["data"] for message in messages if message["type"] == "stats"]
    assert (stats["month"], stats["counting_from"]) == ("2026-10", SUNDAY)
    [person] = stats["people"]
    assert person["streak"] == 1
    for totals in (person["this_month"], person["all_time"]):
        assert (
            totals["done"],
            totals["extra"],
            totals["missed"],
            totals["skipped"],
        ) == (1, 0, 0, 0)


def test_connect_across_midnight_sends_one_date(make_app: MakeApp) -> None:
    """A connect whose reconcile reads Saturday sends `today` and `stats` for Saturday, and reconciles no other date.

    The connect ticks the session first (one read), then reconciles (one read): both read Saturday, every read after
    them Sunday. A `GET /today` first lets the session loop's first tick at the start read the clock before the arm.
    """
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
        assert tc.get(TODAY).status_code == 200
        clock.arm(LAST_READ, FIRST_READ, reads=2)
        with tc.websocket_connect(WS) as ws:
            assert ws.receive_json()["type"] == "hello"
            today = ws.receive_json()
            assert ws.receive_json() == {"type": "session", "data": None}
            stats = ws.receive_json()
    assert today["type"] == "today"
    assert stats["type"] == "stats"
    assert (today["data"]["date"], stats["data"]["month"]) == (SATURDAY, "2026-10")
