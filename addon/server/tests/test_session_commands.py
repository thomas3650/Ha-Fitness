"""Tests for the session commands (spec §3.3) through REST on a frozen clock, on the program `SMALL`."""

from datetime import timedelta
from typing import Any

import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    SMALL_STARTS,
    at,
    command,
    create_small,
    current,
    iso,
    ok,
    set_people,
    start,
    started,
)
from tests.test_people import THOMAS
from tests.test_scheduler import local

WEDNESDAY_9 = local(2026, 10, 28, 9)


async def test_pause_resume_moves_ends_at(make_app: MakeApp) -> None:
    """A pause freezes the phase's remaining seconds; resume moves `ends_at` on by the pause, and time trained skips it."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 9))
        paused = await ok(client, "pause")
        clock.advance(timedelta(seconds=60))
        still = await current(client)
        resumed = await ok(client, "resume")
        clock.advance(timedelta(seconds=6))
        moved_on = await current(client)
    assert paused["status"] == "paused"
    assert paused["phase"]["index"] == 1
    assert paused["phase"]["ends_at"] is None
    assert paused["phase"]["remaining"] == 6
    assert still["status"] == "paused"
    assert still["phase"]["remaining"] == 6
    assert still["time_trained"] == 4
    assert type(still["time_trained"]) is int
    assert resumed["status"] == "running"
    assert resumed["phase"]["remaining"] is None
    assert resumed["phase"]["ends_at"] == iso(at(WEDNESDAY_9, 75))
    assert resumed["time_trained"] == 4
    assert moved_on["phase"]["index"] == 2
    assert moved_on["time_trained"] == 10


async def test_pause_during_countdown_not_in_paused_seconds(make_app: MakeApp) -> None:
    """A pause in the countdown delays the start: `started_at` moves, and time trained runs from it."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 2))
        paused = await ok(client, "pause")
        clock.advance(timedelta(seconds=100))
        resumed = await ok(client, "resume")
        clock.advance(timedelta(seconds=3))
        working = await current(client)
        clock.advance(timedelta(seconds=7))
        ended = await ok(client, "end")
    assert paused["phase"]["remaining"] == 3
    assert resumed["phase"]["ends_at"] == iso(at(WEDNESDAY_9, 105))
    assert resumed["started_at"] is None
    assert working["phase"]["kind"] == "work"
    assert working["started_at"] == iso(at(WEDNESDAY_9, 105))
    assert ended["time_trained"] == 7


# (the phase index reached, seconds into it, the command, the phase index it gives)
_MOVES = [
    # next: during the countdown to the first work phase ("Start nu"), else to the next work phase.
    (0, 2, "next", 1),
    (1, 4, "next", 3),
    (2, 1, "next", 3),
    (4, 1, "next", 6),
    (5, 3, "next", 6),
    # previous: the countdown and the first work phase restart.
    (0, 3, "previous", 0),
    (1, 2, "previous", 1),
    (1, 8, "previous", 1),
    # previous on a work phase: under 3 s back to the previous one, from 3 s the start of this one.
    (3, 2, "previous", 1),
    (3, 3, "previous", 3),
    (6, 9, "previous", 6),
    (6, 1, "previous", 3),
    # previous in a switch or rest: the work phase before it.
    (2, 1, "previous", 1),
    (5, 10, "previous", 3),
    (7, 4, "previous", 6),
]


@pytest.mark.parametrize("paused", [False, True], ids=["running", "paused"])
@pytest.mark.parametrize(("index", "into", "name", "target"), _MOVES)
async def test_next_previous_each_phase_kind_running_and_paused(
    make_app: MakeApp, paused: bool, index: int, into: int, name: str, target: int
) -> None:
    """`next` and `previous` go to the start of a work phase (or restart one), at its full length.

    While paused the session stays paused and the 3 s count stops at the pause; resume then runs the full phase.
    """
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        begun = await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, SMALL_STARTS[index] + into))
        if paused:
            assert (await ok(client, "pause"))["phase"]["index"] == index
            clock.advance(timedelta(seconds=40))
        moved = await ok(client, name)
        resumed = await ok(client, "resume") if paused else moved
    duration = moved["phase"]["duration"]
    assert moved["phase"]["index"] == target
    assert moved["revision"] > begun["revision"]
    if paused:
        assert moved["status"] == "paused"
        assert moved["phase"]["remaining"] == duration
        assert moved["phase"]["ends_at"] is None
    else:
        assert moved["status"] == "running"
    assert resumed["phase"]["ends_at"] == iso(clock.now() + timedelta(seconds=duration))


async def test_next_from_countdown_starts_training(make_app: MakeApp) -> None:
    """`next` in the countdown sets `started_at` to now; time trained runs from there."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 1))
        moved = await ok(client, "next")
        clock.advance(timedelta(seconds=4))
        later = await current(client)
    assert moved["started_at"] == iso(at(WEDNESDAY_9, 1))
    assert later["time_trained"] == 4


async def test_command_after_deadline_acts_on_new_phase(make_app: MakeApp) -> None:
    """A command ticks first: a pause past a deadline pauses the new phase, and `next` jumps from it."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        # The work phase 1 ends at 15 s; 16 s is 1 s into the switch.
        clock.set(at(WEDNESDAY_9, 16))
        paused = await ok(client, "pause")
        await ok(client, "resume")
        # The switch ends at 20 s; at 21 s `next` goes from work phase 3 to 6.
        clock.set(at(WEDNESDAY_9, 21))
        moved = await ok(client, "next")
    assert paused["phase"]["index"] == 2
    assert paused["phase"]["remaining"] == 4
    assert moved["phase"]["index"] == 6


@pytest.mark.parametrize("paused", [False, True], ids=["running", "paused"])
async def test_next_on_last_work_completes(make_app: MakeApp, paused: bool) -> None:
    """`next` on the last work phase completes the session: counted, all rounds, the finished view."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 72))
        if paused:
            await ok(client, "pause")
            clock.advance(timedelta(seconds=30))
        done = await ok(client, "next")
        again = await command(client, "next")
    assert done["status"] == "completed"
    assert done["counted"] is True
    assert done["rounds_completed"] == 2
    assert done["ended_at"] == iso(clock.now())
    assert done["phase"] is None
    assert done["next_phase"] is None
    assert done["stations"] is None
    # 72 s less the 5 s countdown; a pause adds nothing.
    assert done["time_trained"] == 67
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "conflict"


async def test_end_while_paused_closes_open_pause(make_app: MakeApp) -> None:
    """`end` while paused closes the pause first, so time trained leaves it out."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        clock.set(at(WEDNESDAY_9, 12))
        await ok(client, "pause")
        clock.advance(timedelta(seconds=100))
        ended = await ok(client, "end")
    assert ended["status"] == "ended"
    assert ended["ended_at"] == iso(at(WEDNESDAY_9, 112))
    assert ended["time_trained"] == 7
    assert type(ended["time_trained"]) is int
    assert ended["rounds_completed"] == 0
    assert ended["counted"] is False


async def test_commands_not_allowed_are_409(make_app: MakeApp) -> None:
    """Every command without a session is a 409; pause while paused and resume while running are too."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        none = {
            name: await command(client, name)
            for name in ("pause", "resume", "next", "previous", "end")
        }
        await start(client, program["id"], [thomas])
        resume_running = await command(client, "resume")
        await ok(client, "pause")
        pause_paused = await command(client, "pause")
        unknown = await command(client, "jump")
    responses: dict[str, Any] = {
        **none,
        "resume running": resume_running,
        "pause paused": pause_paused,
    }
    for case, response in responses.items():
        assert response.status_code == 409, case
        assert response.json()["detail"]["code"] == "conflict", case
    assert unknown.status_code == 404
    assert unknown.json()["detail"]["code"] == "not_found"
