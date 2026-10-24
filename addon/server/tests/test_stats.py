"""Tests for the stats (stats spec §3, §4), through `GET /api/v1/stats` on a frozen clock in Copenhagen time.

The sessions start through REST and finish by moving the clock past their end. An earlier open day turns missed only
on a date with a day of its own, so a test that wants a missed day gives the next date a day; a test that wants a day
still open (late) gives the next date none. October 2026: Mon 12, Tue 13, Wed 14, Thu 15, Fri 16, Sat 17, Sun 18,
Mon 26, Tue 27, Wed 28, Sat 31; Sun 1 November.
"""

from datetime import timedelta
import json
from pathlib import Path
import sqlite3
from typing import Any

from ha_fitness_server import db
import httpx
import pytest
from sqlalchemy import create_engine

from tests.conftest import FrozenClock, MakeApp, running
from tests.session_helpers import (
    AGENT,
    DAYS,
    PEOPLE,
    SMALL,
    SMALL_END,
    SMALL_STARTS,
    create_small,
    current,
    ok,
    open_day,
    set_people,
    start,
    started,
)
from tests.test_people import ELIN, THOMAS
from tests.test_scheduler import ZONE, local

STATS = "/api/v1/stats"
EVERY_DAY = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
# The seconds a finished `SMALL` session has trained: its work starts after the 5 s countdown.
SMALL_TIME = SMALL_END - SMALL["countdown_seconds"]


def totals(
    done: int = 0,
    extra: int = 0,
    missed: int = 0,
    skipped: int = 0,
    time_trained: int = 0,
) -> dict[str, int]:
    """Return a `Totals` body."""
    return {
        "done": done,
        "extra": extra,
        "missed": missed,
        "skipped": skipped,
        "time_trained": time_trained,
    }


async def stats(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return `GET /stats`; it must succeed."""
    response = await client.get(STATS)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


def of(body: dict[str, Any], person_id: int) -> dict[str, Any]:
    """Return one person's `PersonStats` from a `Stats` body."""
    people: list[dict[str, Any]] = body["people"]
    [person] = [person for person in people if person["id"] == person_id]
    return person


async def train(
    client: httpx.AsyncClient,
    clock: FrozenClock,
    program_id: int,
    participants: list[int],
    day_id: int | None = None,
) -> dict[str, Any]:
    """Start a session now and complete it by moving the clock 5 minutes on; return the finished view.

    The finished view stays 5 minutes after the end, so every program here ends within 5 minutes.
    """
    await start(client, program_id, participants, day_id)
    clock.advance(timedelta(minutes=5))
    view: dict[str, Any] = await current(client)
    assert view["status"] == "completed", view
    return view


async def skip(client: httpx.AsyncClient, day_id: int) -> None:
    """Skip an open day; it must succeed."""
    response = await client.post(f"{DAYS}/{day_id}/skip", headers=AGENT)
    assert response.status_code == 200, response.text


async def test_all_zero_before_counting_from(make_app: MakeApp) -> None:
    """Before the first counted session `counting_from` is null and every number is 0 (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille", weekdays=EVERY_DAY)
        # An uncounted session: ended before one round.
        await start(client, program["id"], [thomas])
        clock.advance(timedelta(seconds=SMALL_STARTS[3] + 5))
        await ok(client, "end")
        # Wednesday's day turns missed on Thursday; Thursday's is skipped.
        clock.set(local(2026, 10, 15, 9))
        await skip(client, await open_day(client, program["id"]))
        clock.set(local(2026, 10, 16, 9))
        body = await stats(client)
    assert body["counting_from"] is None
    assert body["month"] == "2026-10"
    for person_id in (thomas, elin):
        person = of(body, person_id)
        assert person["streak"] == 0
        assert person["all_time"] == totals()
        assert person["this_month"] == totals()


async def test_day_done_by_both(make_app: MakeApp) -> None:
    """A day done by both: done 1 and streak 1 for each (spec §3.1, §3.2)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await train(client, clock, program["id"], [thomas, elin], day_id)
        body = await stats(client)
    assert body["counting_from"] == "2026-10-14"
    assert [person["id"] for person in body["people"]] == [thomas, elin]
    for person_id in (thomas, elin):
        person = of(body, person_id)
        assert person["streak"] == 1
        assert person["all_time"] == totals(done=1, time_trained=SMALL_TIME)
        assert person["this_month"] == totals(done=1, time_trained=SMALL_TIME)


async def test_day_done_by_one_is_missed_for_the_other(make_app: MakeApp) -> None:
    """A done day without a person is missed for them and breaks only their streak (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        day_id = await open_day(client, program["id"])
        await train(client, clock, program["id"], [thomas], day_id)
        body = await stats(client)
    assert of(body, thomas)["streak"] == 1
    assert of(body, thomas)["all_time"] == totals(done=1, time_trained=SMALL_TIME)
    assert of(body, elin)["streak"] == 0
    assert of(body, elin)["all_time"] == totals(missed=1)


async def test_missed_and_skipped_days_break_the_streak(make_app: MakeApp) -> None:
    """A skipped day and a missed day are counted apart, and each ends the streak (spec §3.2)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=EVERY_DAY)
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        clock.set(local(2026, 10, 15, 9))
        await skip(client, await open_day(client, program["id"]))
        after_skip = of(await stats(client), thomas)
        clock.set(local(2026, 10, 16, 9))
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        after_done = of(await stats(client), thomas)
        # Saturday's day is left open; Sunday has a day, so Saturday turns missed.
        clock.set(local(2026, 10, 18, 9))
        after_miss = of(await stats(client), thomas)
    assert after_skip["streak"] == 0
    assert after_skip["all_time"] == totals(done=1, skipped=1, time_trained=SMALL_TIME)
    assert after_done["streak"] == 1
    assert after_miss["streak"] == 0
    assert after_miss["all_time"] == totals(
        done=2, missed=1, skipped=1, time_trained=2 * SMALL_TIME
    )


async def test_first_session_done_late_counts(make_app: MakeApp) -> None:
    """Monday's day trained on Tuesday is the first session: done, though `counting_from` is Tuesday (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 26, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Mandag", weekdays=["mon"])
        day_id = await open_day(client, program["id"])
        clock.set(local(2026, 10, 27, 9))
        await train(client, clock, program["id"], [thomas], day_id)
        body = await stats(client)
    assert body["counting_from"] == "2026-10-27"
    assert of(body, thomas)["streak"] == 1
    assert of(body, thomas)["all_time"] == totals(done=1, time_trained=SMALL_TIME)


@pytest.mark.parametrize("extra", [False, True])
async def test_first_session_across_midnight_counts(
    make_app: MakeApp, extra: bool
) -> None:
    """A first session from Wednesday 23:59:50 into Thursday counts, for a day and as an extra (spec §3.1).

    `counting_from` is Thursday, the local date of the end; the day and the extra belong to Wednesday.
    """
    begin = local(2026, 10, 28, 23, 59) + timedelta(seconds=50)
    clock = FrozenClock(begin)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        day_id = None if extra else await open_day(client, program["id"])
        await train(client, clock, program["id"], [thomas], day_id)
        body = await stats(client)
    assert body["counting_from"] == "2026-10-29"
    person = of(body, thomas)
    expected = totals(done=1, extra=int(extra), time_trained=SMALL_TIME)
    assert person["all_time"] == expected
    assert person["this_month"] == expected
    assert person["streak"] == (0 if extra else 1)


async def test_open_days_count_nowhere(make_app: MakeApp) -> None:
    """A due day and a late day leave the numbers and the streak as they are (spec §3.1, §3.2)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        before = of(await stats(client), thomas)
        clock.set(local(2026, 10, 21, 9))
        due = of(await stats(client), thomas)
        clock.set(local(2026, 10, 22, 9))
        late = of(await stats(client), thomas)
    assert before["streak"] == 1
    assert before["all_time"] == totals(done=1, time_trained=SMALL_TIME)
    assert due == before
    assert late == before


@pytest.mark.parametrize("trained", [0, 1])
async def test_two_programs_one_date_one_missed_breaks_streak(
    make_app: MakeApp, trained: int
) -> None:
    """Two programs on one date: doing only one breaks the streak, whichever day has the lower id (spec §3.2)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        programs = [
            await create_small(client, name, weekdays=["wed", "thu"])
            for name in ("Alfa", "Beta")
        ]
        program = programs[trained]
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        clock.set(local(2026, 10, 15, 9))
        person = of(await stats(client), thomas)
    assert person["all_time"] == totals(done=1, missed=1, time_trained=SMALL_TIME)
    assert person["streak"] == 0


async def test_extra_session_counts_done_extra_time_not_streak(
    make_app: MakeApp,
) -> None:
    """An extra session adds one done, one extra and its time; the streak stays (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        before = of(await stats(client), thomas)
        clock.set(local(2026, 10, 14, 18))
        await start(client, program["id"], [thomas])
        # Paused 30 s inside the first work phase: the time is the active seconds.
        clock.advance(timedelta(seconds=10))
        await ok(client, "pause")
        clock.advance(timedelta(seconds=30))
        await ok(client, "resume")
        clock.advance(timedelta(minutes=5))
        extra = await current(client)
        after = of(await stats(client), thomas)
    assert extra["time_trained"] == SMALL_TIME
    assert before["all_time"] == totals(done=1, time_trained=SMALL_TIME)
    assert after["all_time"] == totals(done=2, extra=1, time_trained=2 * SMALL_TIME)
    assert after["this_month"] == after["all_time"]
    assert after["streak"] == before["streak"] == 1


async def test_uncounted_session_counts_nothing(make_app: MakeApp) -> None:
    """A session ended before one round adds no done and no time (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        before = await stats(client)
        clock.set(local(2026, 10, 14, 18))
        await start(client, program["id"], [thomas])
        clock.advance(timedelta(seconds=SMALL_STARTS[3] + 5))
        ended = await ok(client, "end")
        after = await stats(client)
    assert ended["counted"] is False
    assert ended["time_trained"] > 0
    assert after == before


async def test_missed_before_counting_from_left_out(make_app: MakeApp) -> None:
    """A skipped and a missed day before `counting_from` count nothing (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 13, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=EVERY_DAY)
        await skip(client, await open_day(client, program["id"]))
        # Wednesday's day is left open and turns missed on Thursday.
        clock.set(local(2026, 10, 15, 9))
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        body = await stats(client)
    assert body["counting_from"] == "2026-10-15"
    assert of(body, thomas)["all_time"] == totals(done=1, time_trained=SMALL_TIME)
    assert of(body, thomas)["streak"] == 1


async def test_person_added_later(make_app: MakeApp) -> None:
    """Days before a person's `added_at` date count for them only when they did them (spec §3.1).

    Before Elin is added on Sunday: Tuesday done without her, Wednesday missed, Thursday skipped. Saturday's late day
    she does on Sunday counts, though it is dated before she was added.
    """
    clock = FrozenClock(local(2026, 10, 13, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(
            client, "Lille", weekdays=["tue", "wed", "thu", "sat"]
        )
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        clock.set(local(2026, 10, 15, 9))
        await skip(client, await open_day(client, program["id"]))
        clock.set(local(2026, 10, 17, 9))
        saturday = await open_day(client, program["id"])
        clock.set(local(2026, 10, 18, 9))
        thomas, elin = await set_people(client, THOMAS, ELIN)
        before = of(await stats(client), elin)
        await train(client, clock, program["id"], [thomas, elin], saturday)
        body = await stats(client)
    assert before["all_time"] == totals()
    assert before["streak"] == 0
    assert of(body, elin)["all_time"] == totals(done=1, time_trained=SMALL_TIME)
    assert of(body, elin)["streak"] == 1
    assert of(body, thomas)["all_time"] == totals(
        done=2, missed=1, skipped=1, time_trained=2 * SMALL_TIME
    )
    assert of(body, thomas)["streak"] == 1


async def test_existing_person_keeps_added_at(make_app: MakeApp) -> None:
    """Adding a person keeps the others' `added_at`: Thomas's earlier missed day still counts (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=EVERY_DAY)
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        # Thursday's day is left open and turns missed on Friday.
        clock.set(local(2026, 10, 16, 9))
        kept, _elin = await set_people(client, THOMAS, ELIN)
        person = of(await stats(client), thomas)
    assert kept == thomas
    assert person["all_time"] == totals(done=1, missed=1, time_trained=SMALL_TIME)


async def test_migration_0004_keeps_the_numbers(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A step 5 database with counted days gives the same done, missed and time after migration 0004 (spec §6).

    The people have a null `added_at`, which counts from the start: Elin, in neither day, has both as missed.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'ha_fitness.db'}")
    try:
        db.migrate(engine, "0003_sessions")
    finally:
        engine.dispose()
    plan = {
        "program_id": 1,
        "program_name": "Onsdag",
        "stations": [
            {"exercise_id": "0001", "name": "One"},
            {"exercise_id": "0002", "name": "Two"},
        ],
        "rounds": 2,
        "work_seconds": 10,
        "switch_seconds": 5,
        "round_rest_seconds": 20,
        "countdown_seconds": 5,
        "participants": [{"id": 1, "name": "Thomas"}],
    }
    # Raw-database setup only, as step 5 stored it: the days' program was deleted since, so `program_id` is null.
    with sqlite3.connect(tmp_path / "ha_fitness.db") as connection:
        connection.executemany(
            "INSERT INTO people (id, name, person_entity_id, position) VALUES (?, ?, ?, ?)",
            [(1, "Thomas", "person.thomas", 0), (2, "Elin", "person.elin", 1)],
        )
        connection.executemany(
            "INSERT INTO training_days (id, program_id, program_name, date, status, created_at, closed_at) "
            "VALUES (?, NULL, 'Onsdag', ?, ?, ?, ?)",
            [
                (
                    1,
                    "2026-10-07",
                    "done",
                    "2026-10-07 04:00:00",
                    "2026-10-07 07:01:20",
                ),
                (
                    2,
                    "2026-10-14",
                    "missed",
                    "2026-10-14 04:00:00",
                    "2026-10-21 04:00:00",
                ),
            ],
        )
        connection.execute(
            "INSERT INTO sessions (id, plan, training_day_id, status, counted, phase_index, phase_started_at, "
            "paused_at, paused_seconds, last_tick_at, started_at, ended_at, rounds_completed, revision) "
            "VALUES (1, ?, 1, 'completed', 1, 8, '2026-10-07 07:01:10', NULL, 0, '2026-10-07 07:01:20', "
            "'2026-10-07 07:00:05', '2026-10-07 07:01:20', 2, 9)",
            (json.dumps(plan),),
        )
        connection.execute(
            "INSERT INTO session_participants (session_id, position, person_id, name) VALUES (1, 0, 1, 'Thomas')"
        )
        connection.execute("UPDATE app_state SET counting_from = '2026-10-07'")
    connection.close()
    clock = FrozenClock(local(2026, 10, 28, 9))
    app = make_app(settings_overrides={"timezone": ZONE}, clock=clock)
    async with running(app) as client:
        body = await stats(client)
    assert body["counting_from"] == "2026-10-07"
    assert of(body, 1)["all_time"] == totals(done=1, missed=1, time_trained=75)
    assert of(body, 1)["streak"] == 0
    assert of(body, 2)["all_time"] == totals(missed=2)


async def test_removed_person_has_no_stats(make_app: MakeApp) -> None:
    """A removed person has no stats; added again, they are a new person whose stats start over (spec §3.1)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        thomas, elin = await set_people(client, THOMAS, ELIN)
        program = await create_small(client, "Lille")
        await train(
            client,
            clock,
            program["id"],
            [thomas, elin],
            await open_day(client, program["id"]),
        )
        await set_people(client, THOMAS)
        removed = await stats(client)
        # Added again the next day, so Wednesday's day is before her `added_at` date.
        clock.set(local(2026, 10, 15, 9))
        _thomas, new_elin = await set_people(client, THOMAS, ELIN)
        again = await stats(client)
    assert [person["id"] for person in removed["people"]] == [thomas]
    assert new_elin != elin
    assert [person["id"] for person in again["people"]] == [thomas, new_elin]
    assert of(again, new_elin)["all_time"] == totals()


async def test_this_month_vs_all_time_across_a_month_boundary(
    make_app: MakeApp,
) -> None:
    """A day's own date and a session's start decide the month (spec §3.3).

    An extra session started 31 October 23:58 runs into 1 November. Saturday 31 October's day, done on 1 November
    (which has no day), counts as done in October and its time in November.
    """
    begin = local(2026, 10, 31, 23, 58)
    clock = FrozenClock(begin)
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        # 60 s work phases: the session runs 280 s, so it ends on 1 November.
        program = await create_small(
            client, "Lørdag", weekdays=["sat"], work_seconds=60
        )
        day_id = await open_day(client, program["id"])
        extra = await train(client, clock, program["id"], [thomas])
        clock.set(local(2026, 11, 1, 10))
        late = await train(client, clock, program["id"], [thomas], day_id)
        body = await stats(client)
    seconds = extra["time_trained"]
    assert seconds > 0
    assert late["time_trained"] == seconds
    assert body["month"] == "2026-11"
    assert body["counting_from"] == "2026-11-01"
    person = of(body, thomas)
    assert person["all_time"] == totals(done=2, extra=1, time_trained=2 * seconds)
    assert person["this_month"] == totals(time_trained=seconds)
    assert person["streak"] == 1


async def test_read_after_midnight_sees_yesterday_missed(make_app: MakeApp) -> None:
    """A read just after midnight reconciles first: yesterday's open day is missed before the minute loop runs (§4)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille", weekdays=EVERY_DAY)
        await train(
            client,
            clock,
            program["id"],
            [thomas],
            await open_day(client, program["id"]),
        )
        clock.set(local(2026, 10, 15, 9))
        await open_day(client, program["id"])
        clock.set(local(2026, 10, 16, 0, 0) + timedelta(seconds=30))
        person = of(await stats(client), thomas)
    assert person["all_time"] == totals(done=1, missed=1, time_trained=SMALL_TIME)
    assert person["streak"] == 0


async def test_people_order(make_app: MakeApp) -> None:
    """`people` follows the people's positions, with their names and person entities (spec §3.4)."""
    clock = FrozenClock(local(2026, 10, 14, 9))
    async with started(clock, make_app) as client:
        elin, thomas = await set_people(client, ELIN, THOMAS)
        first = await stats(client)
        response = await client.put(PEOPLE, json={"people": [THOMAS, ELIN]})
        assert response.status_code == 200, response.text
        second = await stats(client)
    assert [
        (person["id"], person["name"], person["person_entity_id"])
        for person in first["people"]
    ] == [(elin, "Elin", "person.elin"), (thomas, "Thomas", "person.thomas")]
    assert [person["id"] for person in second["people"]] == [thomas, elin]
