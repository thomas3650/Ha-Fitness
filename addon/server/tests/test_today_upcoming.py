"""Tests for `upcoming` in the today data: each active program's next training, startable or not.

Today-ahead spec §2.2.1 and §2.2.2, through REST and MCP on a frozen clock in Copenhagen time.
"""

from typing import Any

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    SMALL,
    SMALL_STARTS,
    TODAY,
    at,
    create,
    create_small,
    ok,
    open_day,
    set_people,
    start,
    started,
    started_with_mcp,
)
from tests.test_mcp import call
from tests.test_people import THOMAS
from tests.test_scheduler import local

MONDAY = local(2026, 10, 26)
WEDNESDAY_9 = local(2026, 10, 28, 9)


async def _today(client: Any) -> dict[str, Any]:
    """Return `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def _entries(view: dict[str, Any]) -> list[tuple[str, str, bool]]:
    """Return `upcoming` as (date, program name, startable)."""
    return [
        (entry["date"], entry["program_name"], entry["startable"])
        for entry in view["upcoming"]
    ]


async def test_upcoming_lists_each_programs_next_training(make_app: MakeApp) -> None:
    """On a Monday a Wednesday and a Friday program each have their next date, startable, with their fields."""
    clock = FrozenClock(MONDAY)
    async with started(clock, make_app) as client:
        friday = (await create(client, "Fredag", weekdays=["fri"]))["id"]
        wednesday = (await create(client, "Onsdag"))["id"]
        view = await _today(client)
    # FIVE: 5 stations x 5 rounds x (45 + 15) s + 4 x 60 s = 29 minutes.
    assert view["upcoming"] == [
        {
            "program_id": wednesday,
            "program_name": "Onsdag",
            "date": "2026-10-28",
            "station_count": 5,
            "rounds": 5,
            "total_minutes": 29,
            "startable": True,
        },
        {
            "program_id": friday,
            "program_name": "Fredag",
            "date": "2026-10-30",
            "station_count": 5,
            "rounds": 5,
            "total_minutes": 29,
            "startable": True,
        },
    ]


async def test_open_day_blocks_its_program_only(make_app: MakeApp) -> None:
    """A program with a due day has its next training not startable; another program's stays startable."""
    clock = FrozenClock(MONDAY)
    async with started(clock, make_app) as client:
        await create(client, "Bravo")
        await create(client, "Alfa", weekdays=["mon", "wed"])
        view = await _today(client)
    assert [day["program_name"] for day in view["open"]] == ["Alfa"]
    assert _entries(view) == [
        ("2026-10-28", "Alfa", False),
        ("2026-10-28", "Bravo", True),
    ]


async def test_done_day_today_blocks_until_tomorrow(make_app: MakeApp) -> None:
    """A day done today keeps the program's next training not startable until the next midnight."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        clock.set(at(WEDNESDAY_9, SMALL_STARTS[4] + 1))
        ended = await ok(client, "end")
        done_today = (await client.get(TODAY)).json()
        clock.set(local(2026, 10, 29, 0, 5))
        tomorrow = (await client.get(TODAY)).json()
    assert ended["counted"] is True
    assert done_today["open"] == []
    assert _entries(done_today) == [("2026-11-04", "Lille", False)]
    assert _entries(tomorrow) == [("2026-11-04", "Lille", True)]
    [entry] = tomorrow["upcoming"]
    assert (entry["station_count"], entry["rounds"]) == (
        len(SMALL["stations"]),
        SMALL["rounds"],
    )


async def test_no_upcoming_without_active_programs(make_app: MakeApp) -> None:
    """With no program, or only inactive ones, `upcoming` is empty."""
    clock = FrozenClock(MONDAY)
    async with started(clock, make_app) as client:
        assert (await _today(client))["upcoming"] == []
        await create(client, "Hvile", active=False)
        assert (await _today(client))["upcoming"] == []


async def test_get_today_tool_has_upcoming(make_app: MakeApp) -> None:
    """The MCP `get_today` result has `upcoming`, as REST has."""
    clock = FrozenClock(MONDAY)
    async with started_with_mcp(clock, make_app) as (client, mcp_client):
        await create_small(client, "Lille")
        today = await call(mcp_client, "get_today")
    assert _entries(today) == [("2026-10-28", "Lille", True)]
