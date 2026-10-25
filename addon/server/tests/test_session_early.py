"""Tests for starting a program's next training early, from its upcoming date (today-ahead spec §2.2.3 to §2.2.8).

Through REST and the push channel, on a frozen clock in Copenhagen time, on the program `SMALL` (its phases are in
`tests/session_helpers.py`). The push messages are read from the hub every websocket relays, so a test sees each
batch the add-on publishes, in order. The midnight tests start at 23:59:50, as `test_reconcile_skips_in_session_day`
does: `SMALL` lasts 80 s.
"""

import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI
from ha_fitness_server.push import Hub, Message
import httpx

from tests.conftest import FrozenClock, MakeApp, running
from tests.session_helpers import (
    AGENT,
    PROGRAMS,
    SESSION,
    SESSIONS,
    SMALL,
    SMALL_END,
    SMALL_STARTS,
    TODAY,
    at,
    create_small,
    current,
    days,
    make_session_app,
    ok,
    open_day,
    set_people,
    start,
)
from tests.test_people import THOMAS
from tests.test_scheduler import local

STATS = "/api/v1/stats"
MWF = ["mon", "wed", "fri"]
TUESDAY_9 = local(2026, 10, 27, 9)
WEDNESDAY_9 = local(2026, 10, 28, 9)
SATURDAY_9 = local(2026, 10, 31, 9)
TUESDAY_NIGHT = local(2026, 10, 27, 23, 59) + timedelta(seconds=50)
WEDNESDAY = "2026-10-28"
PLANNED = SMALL_END - SMALL["countdown_seconds"]

type Drain = Callable[[], Awaitable[list[Message]]]


@asynccontextmanager
async def _app(
    clock: FrozenClock, make_app: MakeApp
) -> AsyncIterator[tuple[httpx.AsyncClient, Drain]]:
    """Run a session app; yield an HTTP client and `drain`, which returns the push messages published since last."""
    app: FastAPI = make_session_app(clock, make_app)
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


def _day_events(messages: list[Message]) -> list[tuple[str, str]]:
    """Return the training-day events among `messages` as (event, date)."""
    return [
        (message["event"], message["training_day"]["date"])
        for message in messages
        if message["type"] == "event" and "training_day" in message
    ]


def _entries(view: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Return `upcoming` as (date, program name, startable)."""
    return [
        (entry["date"], entry["program_name"], entry["startable"])
        for entry in view["upcoming"]
    ]


async def _today(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _early(
    client: httpx.AsyncClient,
    program_id: int,
    participants: list[int],
    date: str,
    **fields: Any,
) -> httpx.Response:
    """Ask to start a session for the program's training on `date`, as `test-agent`."""
    body = {"program_id": program_id, "participants": participants, "date": date}
    return await client.post(SESSION, json={**body, **fields}, headers=AGENT)


async def _start_early(
    client: httpx.AsyncClient, program_id: int, participants: list[int], date: str
) -> dict[str, Any]:
    """Start a session early for `date`; it must succeed. Return the view."""
    response = await _early(client, program_id, participants, date)
    assert response.status_code == 201, response.text
    view: dict[str, Any] = response.json()
    return view


async def _set_weekdays(
    client: httpx.AsyncClient, program: dict[str, Any], weekdays: list[str]
) -> None:
    """Replace the program's weekdays; it must succeed."""
    document = {**program["program"], "weekdays": weekdays}
    response = await client.put(f"{PROGRAMS}/{program['id']}", json=document)
    assert response.status_code == 200, response.text


async def _stats_of(client: httpx.AsyncClient) -> tuple[str, dict[str, Any]]:
    """Return `GET /stats` as (month, the one person's stats)."""
    response = await client.get(STATS)
    assert response.status_code == 200, response.text
    body = response.json()
    [person] = body["people"]
    return body["month"], person


def _statuses(listed: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Return the training days as (date, status)."""
    return [(day["date"], day["status"]) for day in listed]


async def test_early_start_accepted(make_app: MakeApp) -> None:
    """On Tuesday a start for Wednesday makes Wednesday's day under the session; `today` follows the start at once.

    Wednesday stays out of `open`, its `upcoming` entry stays on Wednesday, not startable, and the week ring's
    `planned` doesn't move; the training days list Wednesday as open.
    """
    clock = FrozenClock(TUESDAY_9)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        before = await _today(client)
        await drain()
        view = await _start_early(client, program["id"], [thomas], WEDNESDAY)
        messages = await drain()
        listed = await days(client, WEDNESDAY, WEDNESDAY)
        after = await _today(client)
    assert _entries(before) == [(WEDNESDAY, "Lille", True)]
    assert view["status"] == "running"
    assert view["training_day_id"] is not None
    kinds = [message.get("event", message["type"]) for message in messages]
    assert kinds[:3] == ["session", "session_started", "today"]
    today = messages[2]["data"]
    assert today["open"] == []
    assert _entries(today) == [(WEDNESDAY, "Lille", False)]
    assert today["week"] == before["week"]
    assert after == today
    assert [(day["id"], day["date"], day["status"]) for day in listed] == [
        (view["training_day_id"], WEDNESDAY, "open")
    ]


async def test_early_start_refused(make_app: MakeApp) -> None:
    """A date that isn't the program's startable upcoming date is 409; a training day and a date together are 422."""
    clock = FrozenClock(TUESDAY_9)
    async with _app(clock, make_app) as (client, _drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        busy = await create_small(client, "Tirsdag", weekdays=["tue", "thu"])
        busy_day = await open_day(client, busy["id"])
        refused = [
            await _early(client, program["id"], [thomas], "2026-10-30"),
            await _early(client, program["id"], [thomas], "2026-10-27"),
            await _early(client, program["id"], [thomas], "2026-10-26"),
            await _early(client, busy["id"], [thomas], "2026-10-29"),
        ]
        both = [
            await _early(
                client, busy["id"], [thomas], "2026-10-29", training_day_id=busy_day
            ),
            await _early(
                client, program["id"], [thomas], WEDNESDAY, training_day_id=busy_day
            ),
        ]
        session = await current(client)
        listed = await days(client, "2026-10-26", "2026-11-01")
    for response in refused:
        assert response.status_code == 409, response.text
        assert response.json()["detail"]["code"] == "conflict"
    for response in both:
        assert response.status_code == 422, response.text
        detail = response.json()["detail"]
        assert detail["code"] == "invalid"
        assert isinstance(detail["message"], str)
    assert session is None
    assert [(day["program_name"], day["date"]) for day in listed] == [
        ("Tirsdag", "2026-10-27")
    ]


async def _monday_done_on_saturday(
    clock: FrozenClock, client: httpx.AsyncClient, drain: Drain
) -> tuple[dict[str, Any], list[Message], dict[str, Any], dict[str, Any]]:
    """On Saturday 31 October, complete a session started early for a Monday-only program's Monday 2 November.

    Return the finished view, the push messages of the finish, and `today` before the start and after the finish.
    """
    [thomas] = await set_people(client, THOMAS)
    program = await create_small(client, "Lille", weekdays=["mon"])
    before = await _today(client)
    view = await _start_early(client, program["id"], [thomas], "2026-11-02")
    await drain()
    clock.set(at(SATURDAY_9, SMALL_END + 1))
    finished = await current(client)
    messages = await drain()
    after = await _today(client)
    assert finished["id"] == view["id"]
    return finished, messages, before, after


async def test_counted_early_session_closes_day_done(make_app: MakeApp) -> None:
    """A counted early session closes Monday done on Saturday; Monday makes no new day; the stats follow D47.

    This week's ring keeps its `done`; Monday's done counts in November and in the streak, the session's time in
    October, when it ran.
    """
    clock = FrozenClock(SATURDAY_9)
    async with _app(clock, make_app) as (client, drain):
        finished, messages, before, after = await _monday_done_on_saturday(
            clock, client, drain
        )
        saturday_stats = await _stats_of(client)
        clock.set(local(2026, 11, 2, 0, 5))
        monday = await _today(client)
        monday_messages = await drain()
        monday_stats = await _stats_of(client)
        listed = await days(client, "2026-11-02", "2026-11-02")
    assert finished["status"] == "completed"
    assert finished["counted"] is True
    assert _day_events(messages) == [("done", "2026-11-02")]
    assert after["week"]["done"] == before["week"]["done"]
    assert monday["open"] == []
    assert _day_events(monday_messages) == []
    assert _statuses(listed) == [("2026-11-02", "done")]
    month, person = saturday_stats
    assert month == "2026-10"
    assert (person["this_month"]["done"], person["this_month"]["time_trained"]) == (
        0,
        PLANNED,
    )
    month, person = monday_stats
    assert month == "2026-11"
    assert (person["this_month"]["done"], person["this_month"]["time_trained"]) == (
        1,
        0,
    )
    assert person["streak"] == 1


async def test_next_leaves_out_done_dates(make_app: MakeApp) -> None:
    """After Monday is done early on Saturday, the next training day is the Monday after."""
    clock = FrozenClock(SATURDAY_9)
    async with _app(clock, make_app) as (client, drain):
        *_rest, after = await _monday_done_on_saturday(clock, client, drain)
    assert after["next"] == {"date": "2026-11-09", "programs": ["Lille"]}


async def test_early_day_closes_earlier_late_day(make_app: MakeApp) -> None:
    """A day made early counts as the program's day on its date: it closes a late day before it (spec §2.2.8)."""
    clock = FrozenClock(WEDNESDAY_9)
    async with _app(clock, make_app) as (client, _drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=["fri"])
        await _start_early(client, program["id"], [thomas], "2026-10-30")
        clock.set(at(WEDNESDAY_9, SMALL_END + 1))
        assert (await current(client))["counted"] is True
        clock.set(local(2026, 10, 29, 9))
        await _set_weekdays(client, program, ["thu", "fri"])
        thursday = await _today(client)
        clock.set(local(2026, 10, 30, 0, 5))
        listed = await days(client, "2026-10-29", "2026-10-30")
    assert [(day["date"], day["state"]) for day in thursday["open"]] == [
        ("2026-10-29", "due")
    ]
    assert _statuses(listed) == [("2026-10-29", "missed"), ("2026-10-30", "done")]


async def test_uncounted_early_session_leaves_no_day(make_app: MakeApp) -> None:
    """An early session ended before one round removes Wednesday's day; Wednesday is startable again."""
    clock = FrozenClock(TUESDAY_9)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        view = await _start_early(client, program["id"], [thomas], WEDNESDAY)
        await drain()
        clock.set(at(TUESDAY_9, SMALL_STARTS[3] + 1))
        ended = await ok(client, "end")
        messages = await drain()
        listed = await days(client, WEDNESDAY, WEDNESDAY)
        today = await _today(client)
        history = await client.get(SESSIONS)
    assert ended["counted"] is False
    [ended_event] = [
        message
        for message in messages
        if message["type"] == "event" and message["event"] == "session_ended"
    ]
    assert ended_event["session"]["training_day_id"] == view["training_day_id"]
    assert _day_events(messages) == []
    assert listed == []
    assert today["open"] == []
    assert _entries(today) == [(WEDNESDAY, "Lille", True)]
    assert history.status_code == 200, history.text
    [stored] = history.json()["sessions"]
    assert stored["id"] == view["id"]
    assert stored["training_day_id"] is None


async def test_early_session_across_midnight_counted(make_app: MakeApp) -> None:
    """From the midnight into its date the early day is that date's day under a session: due, no `due` event.

    Its `upcoming` entry moves to the program's following date, not startable; the finish closes the day done.
    """
    clock = FrozenClock(TUESDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        view = await _start_early(client, program["id"], [thomas], WEDNESDAY)
        await drain()
        clock.set(at(TUESDAY_NIGHT, 15))  # Wednesday 00:00:05
        midnight = await _today(client)
        midnight_messages = await drain()
        clock.set(at(TUESDAY_NIGHT, SMALL_END + 1))
        finished = await current(client)
        messages = await drain()
    assert midnight["date"] == WEDNESDAY
    assert [(day["id"], day["date"], day["state"]) for day in midnight["open"]] == [
        (view["training_day_id"], WEDNESDAY, "due")
    ]
    assert _entries(midnight) == [("2026-10-30", "Lille", False)]
    assert _day_events(midnight_messages) == []
    assert finished["counted"] is True
    assert _day_events(messages) == [("done", WEDNESDAY)]


async def test_early_session_across_midnight_not_counted(make_app: MakeApp) -> None:
    """An early session that crosses into its date and ends before one round leaves the day due, with a `due` event."""
    clock = FrozenClock(TUESDAY_NIGHT)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        view = await _start_early(client, program["id"], [thomas], WEDNESDAY)
        await drain()
        clock.set(
            at(TUESDAY_NIGHT, 20)
        )  # Wednesday 00:00:10, in round 1's last work phase
        ended = await ok(client, "end")
        messages = await drain()
        today = await _today(client)
    assert ended["counted"] is False
    kinds = [message.get("event", message["type"]) for message in messages]
    assert kinds.index("session_ended") < kinds.index("due")
    assert _day_events(messages) == [("due", WEDNESDAY)]
    [due] = [message for message in messages if message.get("event") == "due"]
    assert due["training_day"]["id"] == view["training_day_id"]
    assert [(day["id"], day["state"]) for day in today["open"]] == [
        (view["training_day_id"], "due")
    ]


async def test_uncounted_due_day_session_sends_no_second_due(
    make_app: MakeApp,
) -> None:
    """A session for an ordinary due day, ended before one round, sends no `due` when it ends."""
    clock = FrozenClock(WEDNESDAY_9)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        await drain()
        clock.set(at(WEDNESDAY_9, SMALL_STARTS[3] + 1))
        ended = await ok(client, "end")
        messages = await drain()
        listed = await days(client, WEDNESDAY, WEDNESDAY)
    assert ended["counted"] is False
    assert any(message.get("event") == "session_ended" for message in messages)
    assert _day_events(messages) == []
    assert _statuses(listed) == [(WEDNESDAY, "open")]


async def test_upcoming_after_an_early_done_day(make_app: MakeApp) -> None:
    """Friday done early on Wednesday: the next Friday is upcoming, not startable until Saturday; `next` skips Friday."""
    clock = FrozenClock(WEDNESDAY_9)
    async with _app(clock, make_app) as (client, _drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=["fri"])
        await _start_early(client, program["id"], [thomas], "2026-10-30")
        clock.set(at(WEDNESDAY_9, SMALL_END + 1))
        assert (await current(client))["counted"] is True
        wednesday = await _today(client)
        clock.set(SATURDAY_9)
        saturday = await _today(client)
    assert _entries(wednesday) == [("2026-11-06", "Lille", False)]
    assert wednesday["next"] == {"date": "2026-11-06", "programs": ["Lille"]}
    assert _entries(saturday) == [("2026-11-06", "Lille", True)]


async def test_weekday_edit_during_early_session(make_app: MakeApp) -> None:
    """Weekdays that drop Wednesday during its early session: the entry stays pinned, the finish closes it done."""
    clock = FrozenClock(TUESDAY_9)
    async with _app(clock, make_app) as (client, drain):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MWF)
        view = await _start_early(client, program["id"], [thomas], WEDNESDAY)
        await _set_weekdays(client, program, ["mon", "fri"])
        during = await _today(client)
        await drain()
        clock.set(at(TUESDAY_9, SMALL_END + 1))
        finished = await current(client)
        messages = await drain()
        clock.set(WEDNESDAY_9)
        listed = await days(client, WEDNESDAY, WEDNESDAY)
    assert _entries(during) == [(WEDNESDAY, "Lille", False)]
    assert finished["counted"] is True
    assert _day_events(messages) == [("done", WEDNESDAY)]
    assert [(day["id"], day["status"]) for day in listed] == [
        (view["training_day_id"], "done")
    ]
