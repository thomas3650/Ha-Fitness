"""Tests for the timeline (cool-down spec §2.2, §4.2): the phases a session runs, walked by the clock, and the totals."""

from typing import Any

import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    PROGRAMS,
    at,
    create_small,
    current,
    ok,
    set_people,
    start,
    started,
    started_with_mcp,
    walk_by_ticks,
)
from tests.test_mcp import call
from tests.test_people import THOMAS
from tests.test_scheduler import FIVE, local

WEDNESDAY_9 = local(2026, 10, 28, 9)
# Two stretches: 0690 and 1378 are stretches of the library.
STRETCHES = [{"exercise": "0690"}, {"exercise": "1378"}]
TWO_STRETCHES: dict[str, Any] = {
    "stretches": STRETCHES,
    "hold_seconds": 30,
    "change_seconds": 10,
}

type Entry = tuple[str, str, int, int, int]


def _entry(view: dict[str, Any]) -> Entry:
    """Return a view's phase as (kind, part, round, interval, duration)."""
    phase = view["phase"]
    return (
        phase["kind"],
        phase["part"],
        phase["round"],
        phase["interval"],
        phase["duration"],
    )


async def _walk(make_app: MakeApp, stations: int, **fields: Any) -> list[Entry]:
    """Start `SMALL` with `stations` stations and `fields`, walk it by the clock, and return its phases; it completes."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Plan", stations=FIVE[:stations], **fields)
        await start(client, program["id"], [thomas])
        *walked, done = await walk_by_ticks(client, clock)
    assert done["status"] == "completed"
    return [_entry(view) for view in walked]


def _work(round_number: int, interval: int, part: str = "circuit") -> Entry:
    """Return a work entry of 10 s in the circuit, or of 30 s in the cool-down."""
    return ("work", part, round_number, interval, 10 if part == "circuit" else 30)


def _switch(round_number: int, interval: int) -> Entry:
    """Return a switch of 5 s in the circuit."""
    return ("switch", "circuit", round_number, interval, 5)


async def test_no_switch_before_round_rest(make_app: MakeApp) -> None:
    """After a round's last station the rest follows directly; no switch comes before it."""
    phases = await _walk(make_app, 3)
    assert phases == [
        ("countdown", "circuit", 1, 1, 5),
        _work(1, 1),
        _switch(1, 1),
        _work(1, 2),
        _switch(1, 2),
        _work(1, 3),
        ("rest", "circuit", 1, 3, 20),
        _work(2, 1),
        _switch(2, 1),
        _work(2, 2),
        _switch(2, 2),
        _work(2, 3),
    ]


async def test_rest_zero_joins_rounds(make_app: MakeApp) -> None:
    """With no rest, round 2's first work follows round 1's last work directly, though everyone moves one station."""
    phases = await _walk(make_app, 2, round_rest_seconds=0, countdown_seconds=0)
    assert phases == [
        _work(1, 1),
        _switch(1, 1),
        _work(1, 2),
        _work(2, 1),
        _switch(2, 1),
        _work(2, 2),
    ]


async def test_one_station(make_app: MakeApp) -> None:
    """One station has no switch at all: its rounds are joined by rests only."""
    phases = await _walk(make_app, 1, rounds=3, countdown_seconds=0)
    assert phases == [
        _work(1, 1),
        ("rest", "circuit", 1, 1, 20),
        _work(2, 1),
        ("rest", "circuit", 2, 1, 20),
        _work(3, 1),
    ]


async def test_cooldown_after_rest(make_app: MakeApp) -> None:
    """After the last round comes the rest, then each stretch held, with a change between stretches."""
    phases = await _walk(make_app, 2, cooldown=TWO_STRETCHES)
    assert phases[-6:] == [
        _switch(2, 1),
        _work(2, 2),
        ("rest", "circuit", 2, 2, 20),
        _work(1, 1, "cooldown"),
        ("switch", "cooldown", 1, 1, 10),
        _work(1, 2, "cooldown"),
    ]
    assert len(phases) == 12


async def test_cooldown_rest_zero_and_change_zero(make_app: MakeApp) -> None:
    """With rest 0 the first stretch follows the last work; with change 0 the stretches follow each other."""
    phases = await _walk(
        make_app,
        2,
        round_rest_seconds=0,
        cooldown={**TWO_STRETCHES, "change_seconds": 0},
    )
    assert phases[-4:] == [
        _switch(2, 1),
        _work(2, 2),
        _work(1, 1, "cooldown"),
        _work(1, 2, "cooldown"),
    ]


async def test_one_stretch(make_app: MakeApp) -> None:
    """One stretch is one cool-down work, and nothing comes after it."""
    cooldown = {**TWO_STRETCHES, "stretches": STRETCHES[:1]}
    phases = await _walk(make_app, 2, cooldown=cooldown)
    assert phases[-3:] == [
        _work(2, 2),
        ("rest", "circuit", 2, 2, 20),
        _work(1, 1, "cooldown"),
    ]


@pytest.mark.parametrize(
    ("fields", "seconds", "minutes"),
    [
        # The default program: 25 works of 45 s, 4 switches of 15 s per round, 4 rests of 60 s.
        (
            {
                "stations": FIVE,
                "rounds": 5,
                "work_seconds": 45,
                "switch_seconds": 15,
                "round_rest_seconds": 60,
            },
            1665,
            28,
        ),
        # 3 stations, 2 rounds: 6 works of 10 s, 4 switches of 5 s, 1 rest of 20 s.
        ({"stations": FIVE[:3]}, 100, 2),
        # The same, then a rest of 20 s, 2 holds of 30 s and 1 change of 10 s.
        ({"stations": FIVE[:3], "cooldown": TWO_STRETCHES}, 190, 3),
    ],
)
async def test_total_seconds_is_the_timeline(
    make_app: MakeApp, fields: dict[str, Any], seconds: int, minutes: int
) -> None:
    """A program's `total_seconds`, `total_minutes` and a session's `totals.planned` are the timeline less the countdown."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started_with_mcp(clock, make_app) as (client, mcp_client):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Plan", **fields)
        stored = await client.get(f"{PROGRAMS}/{program['id']}")
        listed = await call(mcp_client, "list_programs")
        view = await start(client, program["id"], [thomas])
    assert program["total_seconds"] == seconds
    assert stored.json()["total_seconds"] == seconds
    assert listed["result"][0]["total_minutes"] == minutes
    assert view["totals"]["planned"] == seconds


async def test_rounds_completed_ignores_cooldown(make_app: MakeApp) -> None:
    """`end` during the second stretch counts the 2 circuit rounds; the cool-down's round 1 is no round."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(
            client, "Plan", stations=FIVE[:2], cooldown=TWO_STRETCHES
        )
        await start(client, program["id"], [thomas])
        # 5 countdown, 10 + 5 + 10, 20 rest, 10 + 5 + 10, 20 rest, 30 hold, 10 change: stretch 2 starts at 135 s.
        clock.set(at(WEDNESDAY_9, 140))
        view = await current(client)
        assert _entry(view) == _work(1, 2, "cooldown")
        ended = await ok(client, "end")
    assert ended["status"] == "ended"
    assert ended["counted"] is True
    assert ended["rounds_completed"] == 2
