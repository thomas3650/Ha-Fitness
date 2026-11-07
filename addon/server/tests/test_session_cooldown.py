"""Tests for the session in and around the cool-down (cool-down spec §2.3, §4.4, §4.5), and `skip_cooldown`.

Through REST on a frozen clock in Copenhagen time, on `SMALL` with a cool-down of 2 stretches (hold 30, change 10).
Its phases, by index, with their start in seconds after the start of the session:

| index | phase | part | start | duration |
| --- | --- | --- | --- | --- |
| 0 to 7 | `SMALL` (tests/session_helpers.py) | circuit | 0 | 75 |
| 8 | rest | circuit | 75 | 20 |
| 9 | work, stretch 1 | cooldown | 95 | 30 |
| 10 | switch (the change) | cooldown | 125 | 10 |
| 11 | work, stretch 2 | cooldown | 135 | 30 |

It ends at 165 s; `totals.planned` is 160.
"""

from typing import Any

import httpx
import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    CHANGES,
    SMALL,
    SMALL_STARTS,
    TODAY,
    at,
    command,
    create_small,
    current,
    days,
    iso,
    ok,
    open_day,
    set_people,
    start,
    started,
    walk_by_ticks,
)
from tests.test_people import ELIN, THOMAS
from tests.test_scheduler import local

WEDNESDAY_9 = local(2026, 10, 28, 9)
STRETCHES = ["0690", "1378"]
COOLDOWN: dict[str, Any] = {
    "stretches": [{"exercise": exercise} for exercise in STRETCHES],
    "hold_seconds": 30,
    "change_seconds": 10,
}
# The start of the rest before the cool-down, of each stretch and of the change, and the end.
REST_BEFORE = 75
STRETCH_1 = 95
CHANGE = 125
STRETCH_2 = 135
END = 165


async def _program(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    """Create `SMALL` with the cool-down, `fields` replacing its values."""
    return await create_small(client, "Udstræk", cooldown=COOLDOWN, **fields)


def _stretch(program: dict[str, Any], index: int) -> dict[str, Any]:
    """Return a stretch of the program as a view's station: number from 1, its exercise and name, part cooldown."""
    return {
        "number": index + 1,
        "exercise_id": program["program"]["cooldown"]["stretches"][index]["exercise"],
        "name": program["stretch_names"][index],
        "part": "cooldown",
    }


def _station(program: dict[str, Any], index: int) -> dict[str, Any]:
    """Return a station of the program as a view's station, part circuit."""
    return {
        "number": index + 1,
        "exercise_id": program["program"]["stations"][index]["exercise"],
        "name": program["station_names"][index],
        "part": "circuit",
    }


async def _walk(
    client: httpx.AsyncClient, clock: FrozenClock, program: dict[str, Any]
) -> list[dict[str, Any]]:
    """Start a session of Thomas and Elin and walk every phase; return the views, the last finished."""
    [thomas, elin] = await set_people(client, THOMAS, ELIN)
    await start(client, program["id"], [thomas, elin])
    return await walk_by_ticks(client, clock)


async def _changes(client: httpx.AsyncClient, action: str) -> list[dict[str, Any]]:
    """Return the change-log rows of one action, newest first."""
    response = await client.get(CHANGES, params={"limit": 100})
    assert response.status_code == 200, response.text
    return [row for row in response.json() if row["action"] == action]


async def test_view_on_last_circuit_work(make_app: MakeApp) -> None:
    """On the last circuit work the next phase is the rest, and everyone's next station is stretch 1."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        views = await _walk(client, clock, program)
    view = views[7]
    assert (view["phase"]["kind"], view["phase"]["part"]) == ("work", "circuit")
    assert (view["next_phase"]["kind"], view["next_phase"]["part"]) == (
        "rest",
        "circuit",
    )
    assert [station["current"] for station in view["stations"]] == [
        _station(program, 1),
        _station(program, 0),
    ]
    assert [station["next"] for station in view["stations"]] == [
        _stretch(program, 0),
        _stretch(program, 0),
    ]


async def test_view_on_rest_before_cooldown(make_app: MakeApp) -> None:
    """On the rest before the cool-down the phase is circuit, the next is cooldown, and everyone is at stretch 1."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        views = await _walk(client, clock, program)
    view = views[8]
    assert (view["phase"]["kind"], view["phase"]["part"]) == ("rest", "circuit")
    assert (view["next_phase"]["kind"], view["next_phase"]["part"]) == (
        "work",
        "cooldown",
    )
    assert [station["current"] for station in view["stations"]] == [
        _stretch(program, 0),
        _stretch(program, 0),
    ]


async def test_view_in_cooldown(make_app: MakeApp) -> None:
    """In the cool-down everyone does the same stretch, then the next; the last has no next; totals count it."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        views = await _walk(client, clock, program)
    first, change, last = views[9], views[10], views[11]
    assert {
        key: first["phase"][key] for key in ("kind", "part", "round", "interval")
    } == {"kind": "work", "part": "cooldown", "round": 1, "interval": 1}
    assert first["phase"]["duration"] == 30
    assert (
        first["stations"]
        == [{"current": _stretch(program, 0), "next": _stretch(program, 1)}] * 2
    )
    assert (change["phase"]["kind"], change["phase"]["part"]) == ("switch", "cooldown")
    assert change["stations"] == [{"current": _stretch(program, 1), "next": None}] * 2
    assert (last["phase"]["kind"], last["phase"]["part"]) == ("work", "cooldown")
    assert last["stations"] == [{"current": _stretch(program, 1), "next": None}] * 2
    assert last["next_phase"] is None
    assert first["totals"] == {
        "planned": END - SMALL_STARTS[1],
        "rounds": 2,
        "stations": 2,
        "stretches": 2,
        "marks": [45, 90],
    }
    assert views[-1]["status"] == "completed"
    assert views[-1]["totals"]["stretches"] == 2


async def test_no_cooldown_has_no_stretches(make_app: MakeApp) -> None:
    """Without a cool-down `totals.stretches` is 0, and the last work has no next station."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await create_small(client, "Lille")
        views = await _walk(client, clock, program)
    assert views[0]["totals"]["stretches"] == 0
    assert [station["next"] for station in views[-2]["stations"]] == [None, None]


async def test_one_station_cooldown(make_app: MakeApp) -> None:
    """With 1 station, 2 rounds and 1 stretch, the last circuit work's next is stretch 1."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(
            client,
            "En",
            stations=SMALL["stations"][:1],
            cooldown={**COOLDOWN, "stretches": COOLDOWN["stretches"][:1]},
        )
        await start(client, program["id"], [thomas])
        views = await walk_by_ticks(client, clock)
    last_circuit = [
        view
        for view in views[:-1]
        if view["phase"]["kind"] == "work" and view["phase"]["part"] == "circuit"
    ][-1]
    assert last_circuit["phase"]["round"] == 2
    assert last_circuit["stations"] == [
        {"current": _station(program, 0), "next": _stretch(program, 0)}
    ]


async def test_previous_from_first_stretch(make_app: MakeApp) -> None:
    """`previous` within 3 s of stretch 1's start goes back to the start of the last circuit work."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, STRETCH_1 + 2))
        view = await ok(client, "previous")
    assert view["phase"]["index"] == 7
    assert (view["phase"]["kind"], view["phase"]["part"]) == ("work", "circuit")
    assert view["phase"]["ends_at"] == iso(at(WEDNESDAY_9, STRETCH_1 + 12))


async def test_next_on_last_stretch_completes(make_app: MakeApp) -> None:
    """`next` on the last stretch completes the session."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, STRETCH_2 + 1))
        view = await ok(client, "next")
    assert view["status"] == "completed"
    assert view["rounds_completed"] == 2


async def test_skip_cooldown_completes_now(make_app: MakeApp) -> None:
    """`skip_cooldown` 7 s into stretch 1 completes now: the rest of the cool-down adds no time, and the day is done."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        day_id = await open_day(client, program["id"])
        await start(client, program["id"], [thomas], day_id)
        now = at(WEDNESDAY_9, STRETCH_1 + 7)
        clock.set(now)
        view = await ok(client, "skip_cooldown")
        read = await current(client)
        completed = await _changes(client, "session.completed")
        today = (await client.get(TODAY)).json()
        listed = await days(client, "2026-10-28", "2026-10-28")
    assert view["status"] == "completed"
    assert view["counted"] is True
    assert view["rounds_completed"] == 2
    assert view["ended_at"] == iso(now)
    assert view["time_trained"] == STRETCH_1 + 7 - SMALL_STARTS[1]
    assert read == view
    assert len(completed) == 1
    assert completed[0]["client"] == "rest:test-agent"
    assert today["open"] == []
    assert [day["status"] for day in listed] == ["done"]


@pytest.mark.parametrize("seconds", [REST_BEFORE + 1, CHANGE + 1, STRETCH_2 + 1])
async def test_skip_cooldown_on_rest_before_and_later(
    make_app: MakeApp, seconds: int
) -> None:
    """`skip_cooldown` is allowed on the rest before the cool-down, on the change and on the last stretch."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, seconds))
        view = await ok(client, "skip_cooldown")
    assert view["status"] == "completed"
    assert view["ended_at"] == iso(at(WEDNESDAY_9, seconds))


async def test_skip_cooldown_while_paused(make_app: MakeApp) -> None:
    """`skip_cooldown` while paused in the cool-down completes at the skip; the pause doesn't count as trained."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, STRETCH_1 + 5))
        await ok(client, "pause")
        now = at(WEDNESDAY_9, STRETCH_1 + 65)
        clock.set(now)
        view = await ok(client, "skip_cooldown")
    assert view["status"] == "completed"
    assert view["ended_at"] == iso(now)
    assert view["time_trained"] == STRETCH_1 + 5 - SMALL_STARTS[1]


async def test_skip_cooldown_refused(make_app: MakeApp) -> None:
    """`skip_cooldown` is a 409 in the circuit, on the last circuit work, and in a program with no cool-down."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await _program(client)
        plain = await create_small(client, "Lille")
        refused = []
        await start(client, program["id"], [thomas])
        for seconds in (SMALL_STARTS[0] + 1, SMALL_STARTS[4] + 1, SMALL_STARTS[7] + 1):
            clock.set(at(WEDNESDAY_9, seconds))
            refused.append(await command(client, "skip_cooldown"))
        still = await current(client)
        await ok(client, "end")
        await start(client, plain["id"], [thomas])
        clock.set(at(clock.now(), SMALL_STARTS[7] + 1))
        refused.append(await command(client, "skip_cooldown"))
        plain_view = await current(client)
    assert [response.status_code for response in refused] == [409] * 4
    assert {response.json()["detail"]["code"] for response in refused} == {"conflict"}
    assert still["status"] == "running"
    assert still["phase"]["index"] == 7
    assert plain_view["status"] == "running"
    assert plain_view["phase"]["index"] == 7


async def test_end_in_cooldown_is_ended(make_app: MakeApp) -> None:
    """`end` during a stretch is `ended`, counted with both rounds, and the time trained includes the cool-down."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        program = await _program(client)
        [thomas] = await set_people(client, THOMAS)
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, STRETCH_2 + 4))
        view = await ok(client, "end")
    assert view["status"] == "ended"
    assert view["counted"] is True
    assert view["rounds_completed"] == 2
    assert view["time_trained"] == STRETCH_2 + 4 - SMALL_STARTS[1]
