"""Tests for the week in the today view (UI refresh spec §3.1), through REST and the push channel on a frozen clock.

The week is Monday to Sunday of the add-on's local date, in Copenhagen time. 2026-10-26 is a Monday.
"""

from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient
import httpx

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    AGENT,
    PROGRAMS,
    SESSION,
    SMALL,
    SMALL_END,
    TODAY,
    at,
    create_small,
    current,
    make_session_app,
    open_day,
    set_people,
    start,
    started,
)
from tests.test_people import THOMAS
from tests.test_scheduler import local
from tests.test_ws import FAST, WS

MONDAY_9 = local(2026, 10, 26, 9)
MON_WED_FRI = ["mon", "wed", "fri"]


async def _week(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return the `week` of `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    week: dict[str, Any] = response.json()["week"]
    return week


async def _train(
    client: httpx.AsyncClient,
    clock: FrozenClock,
    person: int,
    program_id: int,
    day_id: int | None,
) -> None:
    """Run a whole session of `SMALL` from now, for a training day or as an extra session; it completes."""
    begin: datetime = clock.now()
    await start(client, program_id, [person], day_id)
    clock.set(at(begin, SMALL_END + 30))
    assert (await current(client))["status"] == "completed"


async def test_week_counts_past_today_and_future(make_app: MakeApp) -> None:
    """Monday done, Wednesday open today, Friday still to come: one done of three."""
    clock = FrozenClock(MONDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MON_WED_FRI)
        await _train(
            client, clock, thomas, program["id"], await open_day(client, program["id"])
        )
        clock.set(local(2026, 10, 28, 9))
        assert await _week(client) == {"done": 1, "planned": 3}


async def test_week_skipped_and_missed_count_as_planned_only(make_app: MakeApp) -> None:
    """A missed Monday and a skipped Wednesday count in `planned`, never in `done`."""
    clock = FrozenClock(MONDAY_9)
    async with started(clock, make_app) as client:
        program = await create_small(client, "Lille", weekdays=MON_WED_FRI)
        clock.set(local(2026, 10, 28, 9))
        day_id = await open_day(client, program["id"])
        response = await client.post(f"/api/v1/training-days/{day_id}/skip")
        assert response.status_code == 200, response.text
        clock.set(local(2026, 10, 29, 9))
        response = await client.get(
            "/api/v1/training-days", params={"from": "2026-10-26", "to": "2026-10-29"}
        )
        assert [(day["date"], day["status"]) for day in response.json()] == [
            ("2026-10-26", "missed"),
            ("2026-10-28", "skipped"),
        ]
        assert await _week(client) == {"done": 0, "planned": 3}


async def test_week_program_switched_off_drops_future_days(make_app: MakeApp) -> None:
    """Switching a program off drops its future days; its closed days of the week stay."""
    clock = FrozenClock(MONDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MON_WED_FRI)
        await _train(
            client, clock, thomas, program["id"], await open_day(client, program["id"])
        )
        clock.set(local(2026, 10, 28, 9))
        day_id = await open_day(client, program["id"])
        response = await client.post(f"/api/v1/training-days/{day_id}/skip")
        assert response.status_code == 200, response.text
        assert await _week(client) == {"done": 1, "planned": 3}
        response = await client.put(
            f"{PROGRAMS}/{program['id']}", json={**program["program"], "active": False}
        )
        assert response.status_code == 200, response.text
        assert await _week(client) == {"done": 1, "planned": 2}


async def test_week_fresh_install_counts_from_today(make_app: MakeApp) -> None:
    """A first run on Wednesday counts Wednesday and Friday, not the Monday before it."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(clock, make_app) as client:
        await create_small(client, "Lille", weekdays=MON_WED_FRI)
        assert await _week(client) == {"done": 0, "planned": 2}


async def test_week_late_day_from_last_week_stays_in_last_week(
    make_app: MakeApp,
) -> None:
    """Sunday's day trained late on Monday is done in last week: this week has nothing done."""
    clock = FrozenClock(local(2026, 10, 25, 9))  # a Sunday
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=["sun"])
        assert await _week(client) == {"done": 0, "planned": 1}
        sunday_day = await open_day(client, program["id"])
        clock.set(MONDAY_9)
        await _train(client, clock, thomas, program["id"], sunday_day)
        response = await client.get(
            "/api/v1/training-days", params={"from": "2026-10-25", "to": "2026-10-25"}
        )
        assert [day["status"] for day in response.json()] == ["done"]
        assert await _week(client) == {"done": 0, "planned": 1}


async def test_week_extra_session_does_not_count(make_app: MakeApp) -> None:
    """A finished extra session leaves the week as it was."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=MON_WED_FRI)
        await _train(client, clock, thomas, program["id"], None)
        assert await _week(client) == {"done": 0, "planned": 2}


async def test_week_on_sunday_has_no_future_days(make_app: MakeApp) -> None:
    """On Sunday the week has only Sunday left: next Monday's day isn't counted."""
    clock = FrozenClock(local(2026, 11, 1, 9))  # a Sunday
    async with started(clock, make_app) as client:
        await create_small(client, "Lille", weekdays=["mon", "sun"])
        assert await _week(client) == {"done": 0, "planned": 1}


def _next_today(ws: Any) -> dict[str, Any]:
    """Return the next `today` message, passing over `session` and `stats` messages only."""
    while True:
        message: dict[str, Any] = ws.receive_json()
        if message["type"] in {"session", "stats"}:
            continue
        assert message["type"] == "today", message
        return message


def test_week_starts_over_on_monday(make_app: MakeApp) -> None:
    """At the Sunday to Monday midnight the scheduler's tick pushes the new week's numbers."""
    clock = FrozenClock(local(2026, 11, 1, 22))  # a Sunday
    app = make_session_app(
        clock, make_app, settings_overrides={"scheduler_interval": FAST}
    )
    with TestClient(app) as tc:
        response = tc.put("/api/v1/people", json={"people": [THOMAS]})
        assert response.status_code == 200, response.text
        [thomas] = [person["id"] for person in response.json()]
        document = {
            "name": "Lille",
            "weekdays": ["wed", "sun"],
            "stations": [{"exercise": exercise} for exercise in SMALL["stations"]],
            **{key: value for key, value in SMALL.items() if key != "stations"},
        }
        response = tc.post(PROGRAMS, json=document)
        assert response.status_code == 201, response.text
        program_id = response.json()["id"]
        [day_id] = [day["id"] for day in tc.get(TODAY).json()["open"]]
        response = tc.post(
            SESSION,
            json={
                "program_id": program_id,
                "participants": [thomas],
                "training_day_id": day_id,
            },
            headers=AGENT,
        )
        assert response.status_code == 201, response.text
        clock.set(at(clock.now(), SMALL_END + 30))
        assert tc.get(SESSION, headers=AGENT).json()["status"] == "completed"
        with tc.websocket_connect(WS) as ws:
            assert ws.receive_json()["type"] == "hello"
            first = ws.receive_json()
            assert first["type"] == "today"
            assert first["data"]["week"] == {"done": 1, "planned": 1}
            clock.set(local(2026, 11, 2, 0, 1))  # no request: only the tick reconciles
            message = _next_today(ws)
            assert message["data"]["date"] == "2026-11-02"
            assert message["data"]["week"] == {"done": 0, "planned": 2}
