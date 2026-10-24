"""Tests for restarts, the pause limit and the shutdown snapshot (step 5 spec §3.2, §3.6).

Through REST on a frozen clock in Copenhagen time, on the program `SMALL` (its phases are in
`tests/session_helpers.py`). A crash is simulated with `create_app(..., skip_shutdown=True)`: its shutdown neither
pauses nor writes the snapshot.
"""

from datetime import timedelta
from pathlib import Path
from typing import Any

from ha_fitness_server.db import DATABASE_NAME

from tests.conftest import FrozenClock, MakeApp, running
from tests.session_helpers import (
    AGENT,
    CHANGES,
    PROGRAMS,
    SESSIONS,
    SMALL_STARTS,
    at,
    create_small,
    current,
    iso,
    make_session_app,
    ok,
    set_people,
    start,
    started,
)
from tests.test_people import THOMAS
from tests.test_scheduler import local

WEDNESDAY_9 = local(2026, 10, 28, 9)
LIMIT = timedelta(minutes=30)


async def _start_small(client: Any) -> dict[str, Any]:
    """Set Thomas, create `SMALL` as Lille and start an extra session of it; return the view."""
    [thomas] = await set_people(client, THOMAS)
    program = await create_small(client, "Lille")
    return await start(client, program["id"], [thomas])


async def _crash_at_12(clock: FrozenClock, make_app: MakeApp) -> None:
    """Start a session at 9:00, tick at 6 s and 12 s, move to 14 s and crash.

    The tick at 6 s enters the first work phase; the one at 12 s is the 5 s write of `last_tick_at`. At 14 s there is
    no write (2 s after the last), so `last_tick_at` stays at 12 s.
    """
    app = make_session_app(clock, make_app, skip_shutdown=True)
    async with running(app) as client:
        await _start_small(client)
        clock.set(at(WEDNESDAY_9, 6))
        assert (await current(client))["phase"]["index"] == 1
        clock.set(at(WEDNESDAY_9, 12))
        await current(client)
        clock.set(at(WEDNESDAY_9, 14))


async def _shut_down_at_12(clock: FrozenClock, make_app: MakeApp) -> None:
    """Start a session at 9:00, move to 12 s with no tick, and shut down normally.

    The loop waits an hour, so nothing ticks after the start: `last_tick_at` stays at 0 s, and only the shutdown's
    pause can keep the session at 12 s.
    """
    app = make_session_app(clock, make_app, {"session_tick_max": 3600})
    async with running(app) as client:
        await _start_small(client)
        clock.set(at(WEDNESDAY_9, 12))


async def test_shutdown_pauses_running_session(make_app: MakeApp) -> None:
    """A normal shutdown pauses a running session at the shutdown; the next start keeps it paused there."""
    clock = FrozenClock(WEDNESDAY_9)
    await _shut_down_at_12(clock, make_app)
    clock.set(at(WEDNESDAY_9, 12) + timedelta(minutes=10))
    async with started(clock, make_app) as client:
        paused = await current(client)
        resumed = await ok(client, "resume")
    assert paused["status"] == "paused"
    assert paused["phase"]["index"] == 1
    assert paused["phase"]["ends_at"] is None
    assert paused["phase"]["remaining"] == 3.0
    assert paused["time_trained"] == 7
    assert resumed["status"] == "running"
    assert resumed["phase"]["ends_at"] == iso(clock.now() + timedelta(seconds=3))


async def test_crash_start_pauses_at_last_tick_no_skips(make_app: MakeApp) -> None:
    """After a crash the start pauses the session at `last_tick_at`: the phase as of then, nothing skipped."""
    clock = FrozenClock(WEDNESDAY_9)
    await _crash_at_12(clock, make_app)
    clock.set(at(WEDNESDAY_9, 14) + timedelta(minutes=10))
    async with started(clock, make_app) as client:
        paused = await current(client)
        resumed = await ok(client, "resume")
    assert paused["status"] == "paused"
    assert paused["phase"]["index"] == 1
    assert paused["phase"]["kind"] == "work"
    assert paused["phase"]["remaining"] == 3.0
    assert paused["time_trained"] == 7
    assert paused["rounds_completed"] == 0
    assert resumed["phase"]["index"] == 1
    assert resumed["phase"]["ends_at"] == iso(clock.now() + timedelta(seconds=3))


async def test_crash_longer_than_30_minutes_ends_at_start(make_app: MakeApp) -> None:
    """A crash down longer than the pause limit ends the session at once, 30 minutes after `last_tick_at`."""
    clock = FrozenClock(WEDNESDAY_9)
    await _crash_at_12(clock, make_app)
    clock.set(at(WEDNESDAY_9, 12) + LIMIT + timedelta(minutes=10))
    async with started(clock, make_app) as client:
        response = await client.get(SESSIONS, headers=AGENT)
        log = (await client.get(CHANGES, params={"limit": 100})).json()
        nothing = await current(client)
    [ended] = response.json()["sessions"]
    assert ended["status"] == "ended"
    assert ended["counted"] is False
    assert ended["rounds_completed"] == 0
    assert ended["ended_at"] == iso(at(WEDNESDAY_9, 12) + LIMIT)
    assert ended["time_trained"] == 7
    [logged] = [row for row in log if row["action"] == "session.ended"]
    assert logged["client"] == "addon"
    assert nothing is None


async def test_pause_limit_ends_after_30_minutes(make_app: MakeApp) -> None:
    """A session paused for 30 minutes is ended at the limit; just before, it is still paused (`GET /session`).

    It was paused after round 1, so it counts. The websocket side is in `test_session_push.py`.
    """
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        await _start_small(client)
        pause_at = at(WEDNESDAY_9, SMALL_STARTS[5] + 1)
        clock.set(pause_at)
        await ok(client, "pause")
        clock.set(pause_at + LIMIT - timedelta(seconds=1))
        before = await current(client)
        clock.set(pause_at + LIMIT)
        after = await current(client)
        resume = await client.post(f"{SESSIONS[:-1]}/resume", headers=AGENT)
    assert before["status"] == "paused"
    assert after["status"] == "ended"
    assert after["counted"] is True
    assert after["rounds_completed"] == 1
    assert after["ended_at"] == iso(pause_at + LIMIT)
    assert resume.status_code == 409


async def test_shutdown_snapshot_holds_latest_program(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """The shutdown writes the snapshot: with the database lost, the next start restores a program made just before."""
    clock = FrozenClock(WEDNESDAY_9)
    async with started(clock, make_app) as client:
        await create_small(client, "Seneste")
    (tmp_path / DATABASE_NAME).unlink()
    async with started(clock, make_app) as client:
        programs = (await client.get(PROGRAMS)).json()
    assert [program["program"]["name"] for program in programs] == ["Seneste"]


async def test_shutdown_pauses_before_the_snapshot(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """The snapshot written at shutdown holds the session paused as of the shutdown, not as of `last_tick_at`."""
    clock = FrozenClock(WEDNESDAY_9)
    await _shut_down_at_12(clock, make_app)
    (tmp_path / DATABASE_NAME).unlink()
    clock.set(at(WEDNESDAY_9, 12) + timedelta(minutes=10))
    async with started(clock, make_app) as client:
        paused = await current(client)
    assert paused["status"] == "paused"
    assert paused["phase"]["index"] == 1
    assert paused["phase"]["remaining"] == 3.0
