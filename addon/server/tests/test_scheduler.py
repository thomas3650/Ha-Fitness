"""Tests for the scheduler and the read routes (step 4 spec §3.3, §3.5), through REST with a frozen clock."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from itertools import pairwise
import json
from pathlib import Path
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from ha_fitness_server import db
import httpx
from sqlalchemy import create_engine

from tests.conftest import FrozenClock, MakeApp, running

TODAY = "/api/v1/today"
DAYS = "/api/v1/training-days"
PROGRAMS = "/api/v1/programs"
ZONE = ZoneInfo("Europe/Copenhagen")
# Five library exercises, by id: 5 stations x 5 rounds x (45 + 15) s + 4 x 60 s = 29 minutes.
FIVE = ["0001", "0002", "0003", "0006", "0020"]


def local(year: int, month: int, day: int, hour: int = 12, minute: int = 0) -> datetime:
    """Return a Copenhagen wall-clock time as aware UTC."""
    return datetime(year, month, day, hour, minute, tzinfo=ZONE).astimezone(UTC)


def _program(name: str, weekdays: list[str], **fields: Any) -> dict[str, Any]:
    """Return a valid program document."""
    return {
        "name": name,
        "weekdays": weekdays,
        "stations": [{"exercise": exercise} for exercise in FIVE],
        **fields,
    }


@asynccontextmanager
async def started(
    make_app: MakeApp, clock: FrozenClock, late_days: int | None = None
) -> AsyncIterator[httpx.AsyncClient]:
    """Run an app in Copenhagen time on the frozen clock, with `late_days` if given (else the default)."""
    overrides: dict[str, Any] = {"timezone": ZONE}
    if late_days is not None:
        overrides["late_days"] = late_days
    app = make_app(settings_overrides=overrides, clock=clock)
    async with running(app) as client:
        yield client


async def _create(
    client: httpx.AsyncClient, name: str, weekdays: list[str], **fields: Any
) -> int:
    """Create a program; it must succeed. Return its id."""
    response = await client.post(PROGRAMS, json=_program(name, weekdays, **fields))
    assert response.status_code == 201, response.text
    program_id: int = response.json()["id"]
    return program_id


async def _today(client: httpx.AsyncClient) -> dict[str, Any]:
    """Return `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    body: dict[str, Any] = response.json()
    return body


async def _days(
    client: httpx.AsyncClient, start: str, end: str
) -> list[dict[str, Any]]:
    """Return `GET /training-days` for a range."""
    response = await client.get(DAYS, params={"from": start, "to": end})
    assert response.status_code == 200, response.text
    body: list[dict[str, Any]] = response.json()
    return body


def _open(view: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return the open days of a view as (name, date, state)."""
    return [(day["program_name"], day["date"], day["state"]) for day in view["open"]]


def _statuses(days: list[dict[str, Any]]) -> list[tuple[str, str, str]]:
    """Return training days as (date, name, status)."""
    return [(day["date"], day["program_name"], day["status"]) for day in days]


async def test_midnight_creates_due_days(make_app: MakeApp) -> None:
    """At local midnight a Wednesday program gets its day, due, with the program's fields."""
    clock = FrozenClock(local(2026, 10, 27))  # a Tuesday
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        assert await _today(client) == {
            "date": "2026-10-27",
            "open": [],
            "next": {"date": "2026-10-28", "programs": ["Onsdag"]},
            "week": {"done": 0, "planned": 1},
            "upcoming": [
                {
                    "program_id": program_id,
                    "program_name": "Onsdag",
                    "date": "2026-10-28",
                    "station_count": 5,
                    "rounds": 5,
                    "total_minutes": 29,
                    "startable": True,
                }
            ],
        }
        clock.set(local(2026, 10, 27, 23, 59))
        assert (await _today(client))["open"] == []
        clock.set(local(2026, 10, 28, 0, 1))
        view = await _today(client)
        assert view["date"] == "2026-10-28"
        [day] = view["open"]
        assert isinstance(day.pop("id"), int)
        assert day == {
            "program_id": program_id,
            "program_name": "Onsdag",
            "date": "2026-10-28",
            "state": "due",
            "station_count": 5,
            "rounds": 5,
            "total_minutes": 29,
        }
        assert view["next"] == {"date": "2026-11-04", "programs": ["Onsdag"]}


async def test_passed_day_reads_late(make_app: MakeApp) -> None:
    """An open day reads as late once its date has passed."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        await _create(client, "Onsdag", ["wed"])
        clock.set(local(2026, 10, 29, 8))
        view = await _today(client)
        assert view["date"] == "2026-10-29"
        assert _open(view) == [("Onsdag", "2026-10-28", "late")]


async def test_other_programs_day_keeps_late_day_open(make_app: MakeApp) -> None:
    """Another program's training day leaves the late day open; open days sort by date, so late comes first."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock, late_days=6) as client:
        await _create(client, "Onsdag", ["wed"])
        await _create(client, "Lørdag", ["sat"])
        clock.set(local(2026, 10, 30))
        assert _open(await _today(client)) == [("Onsdag", "2026-10-28", "late")]
        clock.set(local(2026, 10, 31, 0, 5))
        assert _open(await _today(client)) == [
            ("Onsdag", "2026-10-28", "late"),
            ("Lørdag", "2026-10-31", "due"),
        ]
        assert _statuses(await _days(client, "2026-10-28", "2026-10-31")) == [
            ("2026-10-28", "Onsdag", "open"),
            ("2026-10-31", "Lørdag", "open"),
        ]


async def test_own_program_closes_late_day(make_app: MakeApp) -> None:
    """The program's next training day closes its late day as missed, before its days are up."""
    clock = FrozenClock(local(2026, 10, 26))  # a Monday
    async with started(make_app, clock, late_days=2) as client:
        await _create(client, "Mandag", ["mon", "wed"])
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "due")]
        clock.set(local(2026, 10, 27))
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "late")]
        clock.set(local(2026, 10, 28, 0, 5))
        assert _open(await _today(client)) == [("Mandag", "2026-10-28", "due")]
        days = await _days(client, "2026-10-26", "2026-10-28")
        assert _statuses(days) == [
            ("2026-10-26", "Mandag", "missed"),
            ("2026-10-28", "Mandag", "open"),
        ]
        assert days[0]["closed_at"] is not None


async def test_late_days_up_closes_late_day(make_app: MakeApp) -> None:
    """With no own training day in between, a late day closes at the start of the date `late_days + 1` after it."""
    clock = FrozenClock(local(2026, 10, 26))  # a Monday
    async with started(make_app, clock, late_days=2) as client:
        await _create(client, "Mandag", ["mon", "fri"])
        clock.set(local(2026, 10, 28, 23, 59))
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "late")]
        clock.set(local(2026, 10, 29, 0, 5))
        assert (await _today(client))["open"] == []
        days = await _days(client, "2026-10-26", "2026-10-29")
        assert _statuses(days) == [("2026-10-26", "Mandag", "missed")]
        assert days[0]["closed_at"] is not None


async def test_late_days_zero_never_late(make_app: MakeApp) -> None:
    """With `late_days` 0 a day closes as missed at the midnight after its date."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock, late_days=0) as client:
        await _create(client, "Onsdag", ["wed"])
        clock.set(local(2026, 10, 29, 0, 5))
        assert (await _today(client))["open"] == []
        assert _statuses(await _days(client, "2026-10-28", "2026-10-29")) == [
            ("2026-10-28", "Onsdag", "missed"),
        ]


async def test_default_late_days_is_two(make_app: MakeApp) -> None:
    """Without the setting a late day stays open two days after its date."""
    clock = FrozenClock(local(2026, 10, 26))  # a Monday
    async with started(make_app, clock) as client:
        await _create(client, "Mandag", ["mon", "fri"])
        clock.set(local(2026, 10, 28))
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "late")]
        clock.set(local(2026, 10, 29))
        assert (await _today(client))["open"] == []
        assert _statuses(await _days(client, "2026-10-26", "2026-10-29")) == [
            ("2026-10-26", "Mandag", "missed"),
        ]


async def test_lowered_late_days_closes_at_start(make_app: MakeApp) -> None:
    """A late day past a lowered limit closes as missed at the first read after the restart."""
    clock = FrozenClock(local(2026, 10, 26))  # a Monday
    async with started(make_app, clock, late_days=6) as client:
        await _create(client, "Mandag", ["mon"])
        clock.set(local(2026, 10, 30))  # Friday
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "late")]
    async with started(make_app, clock, late_days=2) as client:
        assert (await _today(client))["open"] == []
        assert _statuses(await _days(client, "2026-10-26", "2026-10-30")) == [
            ("2026-10-26", "Mandag", "missed"),
        ]


async def test_weekday_edit_adding_today_closes_late_day_at_once(
    make_app: MakeApp,
) -> None:
    """An edit that makes today a training day of the program closes its late day at once (D34)."""
    clock = FrozenClock(local(2026, 10, 26))  # a Monday
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Mandag", ["mon"])
        clock.set(local(2026, 10, 27, 10))
        assert _open(await _today(client)) == [("Mandag", "2026-10-26", "late")]
        response = await client.put(
            f"{PROGRAMS}/{program_id}", json=_program("Mandag", ["mon", "tue"])
        )
        assert response.status_code == 200, response.text
        assert _open(await _today(client)) == [("Mandag", "2026-10-27", "due")]
        assert _statuses(await _days(client, "2026-10-26", "2026-10-27")) == [
            ("2026-10-26", "Mandag", "missed"),
            ("2026-10-27", "Mandag", "open"),
        ]


async def test_date_without_days_closes_nothing(make_app: MakeApp) -> None:
    """Dates with no training day leave the late day open, for a whole week."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock, late_days=6) as client:
        await _create(client, "Onsdag", ["wed"])
        for day in range(29, 32):
            clock.set(local(2026, 10, day))
            assert _open(await _today(client)) == [("Onsdag", "2026-10-28", "late")]
        for day in range(1, 4):
            clock.set(local(2026, 11, day))
            assert _open(await _today(client)) == [("Onsdag", "2026-10-28", "late")]
        clock.set(local(2026, 11, 4))
        assert _open(await _today(client)) == [("Onsdag", "2026-11-04", "due")]
        assert _statuses(await _days(client, "2026-10-28", "2026-11-04")) == [
            ("2026-10-28", "Onsdag", "missed"),
            ("2026-11-04", "Onsdag", "open"),
        ]


async def test_catch_up_after_three_days_off(make_app: MakeApp) -> None:
    """After three days off, each date is handled in order: Wednesday's day is made, then missed by Thursday's."""
    clock = FrozenClock(local(2026, 10, 27))  # Tuesday
    async with started(make_app, clock) as client:
        await _create(client, "Midtuge", ["wed", "thu"])
        assert (await _today(client))["open"] == []
    clock.set(
        local(2026, 10, 30)
    )  # Friday: Wednesday and Thursday passed with the add-on off
    async with started(make_app, clock) as client:
        assert _statuses(await _days(client, "2026-10-26", "2026-11-01")) == [
            ("2026-10-28", "Midtuge", "missed"),
            ("2026-10-29", "Midtuge", "open"),
        ]
        assert _open(await _today(client)) == [("Midtuge", "2026-10-29", "late")]


async def test_first_run_makes_up_nothing(make_app: MakeApp, tmp_path: Path) -> None:
    """A program from before the scheduler existed gets today's day only, none for the past."""
    engine = create_engine(f"sqlite:///{tmp_path / 'ha_fitness.db'}")
    try:
        db.migrate(engine, "0001")
    finally:
        engine.dispose()
    # Setup only, as in test_migration_0002_keeps_programs: a program step 3 stored, before any scheduler run.
    document = _program("Hver dag", ["mon", "tue", "wed", "thu", "fri", "sat", "sun"])
    document["stations"] = [{"exercise": "0001"}]
    with sqlite3.connect(tmp_path / "ha_fitness.db") as connection:
        connection.execute(
            "INSERT INTO programs (name, name_key, active, document, created_at, updated_at) "
            "VALUES (?, ?, 1, ?, '2026-10-01 06:00:00', '2026-10-01 06:00:00')",
            ("Hver dag", "hver dag", json.dumps(document | {"active": True})),
        )
    connection.close()
    clock = FrozenClock(local(2026, 10, 24))
    async with started(make_app, clock) as client:
        assert _statuses(await _days(client, "2026-10-01", "2026-10-31")) == [
            ("2026-10-24", "Hver dag", "open"),
        ]


async def test_create_on_training_day_makes_today_and_keeps_late_open(
    make_app: MakeApp,
) -> None:
    """Creating, or switching on, a program on its weekday makes today's day; another program's late day stays open."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        await _create(client, "Onsdag", ["wed"])
        clock.set(local(2026, 10, 29))
        assert _open(await _today(client)) == [("Onsdag", "2026-10-28", "late")]
        await _create(client, "Torsdag", ["thu"])
        assert _open(await _today(client)) == [
            ("Onsdag", "2026-10-28", "late"),
            ("Torsdag", "2026-10-29", "due"),
        ]
        sleeper = await _create(client, "Fredag", ["fri"], active=False)
        clock.set(local(2026, 10, 30))
        assert _open(await _today(client)) == [
            ("Onsdag", "2026-10-28", "late"),
            ("Torsdag", "2026-10-29", "late"),
        ]
        response = await client.put(
            f"{PROGRAMS}/{sleeper}/active", json={"active": True}
        )
        assert response.status_code == 200
        assert _open(await _today(client)) == [
            ("Onsdag", "2026-10-28", "late"),
            ("Torsdag", "2026-10-29", "late"),
            ("Fredag", "2026-10-30", "due"),
        ]
        assert _statuses(await _days(client, "2026-10-28", "2026-10-30")) == [
            ("2026-10-28", "Onsdag", "open"),
            ("2026-10-29", "Torsdag", "open"),
            ("2026-10-30", "Fredag", "open"),
        ]


async def test_update_active_false_removes_open_days(make_app: MakeApp) -> None:
    """Switching a program off, by update or by the active route, removes its open days."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        first = await _create(client, "Onsdag", ["wed"])
        second = await _create(client, "Aften", ["wed"])
        assert len((await _today(client))["open"]) == 2
        response = await client.put(
            f"{PROGRAMS}/{first}", json=_program("Onsdag", ["wed"], active=False)
        )
        assert response.status_code == 200
        assert _open(await _today(client)) == [("Aften", "2026-10-28", "due")]
        response = await client.put(
            f"{PROGRAMS}/{second}/active", json={"active": False}
        )
        assert response.status_code == 200
        view = await _today(client)
        assert view["open"] == []
        assert view["next"] is None
        assert await _days(client, "2026-10-28", "2026-10-28") == []


async def test_rename_updates_open_days(make_app: MakeApp) -> None:
    """A rename changes the name on open days; a closed day keeps the name it had."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        # No read and no scheduler run after the jump: the write itself reconciles first.
        clock.set(local(2026, 11, 4))
        response = await client.put(
            f"{PROGRAMS}/{program_id}", json=_program("Midtuge", ["wed"])
        )
        assert response.status_code == 200
        assert _open(await _today(client)) == [("Midtuge", "2026-11-04", "due")]
        assert _statuses(await _days(client, "2026-10-28", "2026-11-04")) == [
            ("2026-10-28", "Onsdag", "missed"),
            ("2026-11-04", "Midtuge", "open"),
        ]


async def test_delete_right_after_midnight_keeps_late_day_as_missed(
    make_app: MakeApp,
) -> None:
    """A delete with no read since midnight first closes the late day as missed, so it stays, without a program id."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        clock.set(local(2026, 11, 4, 0, 1))
        response = await client.delete(f"{PROGRAMS}/{program_id}")
        assert response.status_code == 204
        days = await _days(client, "2026-10-28", "2026-11-04")
        assert _statuses(days) == [("2026-10-28", "Onsdag", "missed")]
        assert days[0]["program_id"] is None
        assert (await _today(client))["open"] == []


async def test_adding_todays_weekday_makes_todays_day(make_app: MakeApp) -> None:
    """An update that adds today's weekday makes today's day at once."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Torsdag", ["thu"])
        assert (await _today(client))["open"] == []
        response = await client.put(
            f"{PROGRAMS}/{program_id}", json=_program("Torsdag", ["wed", "thu"])
        )
        assert response.status_code == 200
        assert _open(await _today(client)) == [("Torsdag", "2026-10-28", "due")]


async def test_delete_removes_open_keeps_closed(make_app: MakeApp) -> None:
    """Deleting a program removes its open days; closed ones stay, with the name and no program id."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        clock.set(local(2026, 11, 4))
        assert len((await _today(client))["open"]) == 1
        response = await client.delete(f"{PROGRAMS}/{program_id}")
        assert response.status_code == 204
        assert (await _today(client))["open"] == []
        days = await _days(client, "2026-10-28", "2026-11-04")
        assert _statuses(days) == [("2026-10-28", "Onsdag", "missed")]
        assert days[0]["program_id"] is None


async def test_two_programs_one_date_by_name(make_app: MakeApp) -> None:
    """Two programs on one date give two open days, by program name ignoring case."""
    clock = FrozenClock(local(2026, 10, 27))
    async with started(make_app, clock) as client:
        await _create(client, "Onsdag", ["wed"])
        await _create(client, "aften", ["wed", "sat"])
        assert (await _today(client))["next"] == {
            "date": "2026-10-28",
            "programs": ["aften", "Onsdag"],
        }
        clock.set(local(2026, 10, 28))
        assert _open(await _today(client)) == [
            ("aften", "2026-10-28", "due"),
            ("Onsdag", "2026-10-28", "due"),
        ]


async def test_removing_today_from_weekdays_keeps_todays_day(make_app: MakeApp) -> None:
    """Taking today out of the weekdays leaves today's open day; it still asks once."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        response = await client.put(
            f"{PROGRAMS}/{program_id}", json=_program("Onsdag", ["thu"])
        )
        assert response.status_code == 200
        view = await _today(client)
        assert _open(view) == [("Onsdag", "2026-10-28", "due")]
        assert view["next"] == {"date": "2026-10-29", "programs": ["Onsdag"]}


async def test_next_is_null_without_active_programs(make_app: MakeApp) -> None:
    """`next` is null with no program or only inactive ones, and isn't null while one program is active."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock) as client:
        assert await _today(client) == {
            "date": "2026-10-28",
            "open": [],
            "next": None,
            "week": {"done": 0, "planned": 0},
            "upcoming": [],
        }
        await _create(client, "Hvile", ["wed"], active=False)
        assert (await _today(client))["next"] is None
        await _create(client, "Onsdag", ["wed"])
        view = await _today(client)
        assert view["next"] is not None
        assert view["next"] == {"date": "2026-11-04", "programs": ["Onsdag"]}


async def _dates_across(
    client: httpx.AsyncClient, clock: FrozenClock, start: datetime, end: datetime
) -> list[str]:
    """Step the clock every 15 minutes from `start` to `end`; return `/today`'s date at each step."""
    seen: list[str] = []
    moment = start
    while moment <= end:
        clock.set(moment)
        seen.append((await _today(client))["date"])
        moment += timedelta(minutes=15)
    return seen


def _rollovers(seen: list[str]) -> list[str]:
    """Return the dates `/today` changed to, in order."""
    return [after for before, after in pairwise(seen) if after != before]


async def test_dst_sundays_one_rollover_each(make_app: MakeApp) -> None:
    """Across both DST Sundays in Copenhagen each local midnight rolls the date once, and Sunday gets one day."""
    clock = FrozenClock(datetime(2026, 3, 28, 12, tzinfo=UTC))
    async with started(make_app, clock) as client:
        await _create(client, "Søndag", ["sun"])
        # 2026-03-29: clocks go forward at 02:00, so the Sunday has 23 hours.
        seen = await _dates_across(
            client,
            clock,
            datetime(2026, 3, 28, 12, tzinfo=UTC),
            datetime(2026, 3, 30, 12, tzinfo=UTC),
        )
        assert _rollovers(seen) == ["2026-03-29", "2026-03-30"]
        assert seen.count("2026-03-29") == 23 * 4
        clock.set(datetime(2026, 3, 28, 22, 59, tzinfo=UTC))
        assert (await _today(client))["date"] == "2026-03-28"
        clock.set(datetime(2026, 3, 28, 23, 0, tzinfo=UTC))
        assert (await _today(client))["date"] == "2026-03-29"
        assert _statuses(await _days(client, "2026-03-28", "2026-03-30")) == [
            ("2026-03-29", "Søndag", "open"),
        ]
        # 2026-10-25: clocks go back at 03:00, so the Sunday has 25 hours.
        seen = await _dates_across(
            client,
            clock,
            datetime(2026, 10, 24, 12, tzinfo=UTC),
            datetime(2026, 10, 26, 12, tzinfo=UTC),
        )
        assert _rollovers(seen) == ["2026-10-25", "2026-10-26"]
        assert seen.count("2026-10-25") == 25 * 4
        assert _statuses(await _days(client, "2026-10-24", "2026-10-26")) == [
            ("2026-10-25", "Søndag", "open"),
        ]
        clock.set(datetime(2026, 10, 25, 22, 59, tzinfo=UTC))
        assert (await _today(client))["date"] == "2026-10-25"
        clock.set(datetime(2026, 10, 25, 23, 0, tzinfo=UTC))
        assert (await _today(client))["date"] == "2026-10-26"


async def test_training_days_range_is_inclusive_by_date(make_app: MakeApp) -> None:
    """`/training-days` returns the days from `from` to `to`, both included, by date, then name ignoring case."""
    clock = FrozenClock(local(2026, 10, 28))
    async with started(make_app, clock, late_days=0) as client:
        await _create(client, "Onsdag", ["wed"])
        await _create(client, "Torsdag", ["thu"])
        await _create(client, "aften", ["thu"])
        clock.set(local(2026, 10, 29))
        assert _statuses(await _days(client, "2026-10-28", "2026-10-29")) == [
            ("2026-10-28", "Onsdag", "missed"),
            ("2026-10-29", "aften", "open"),
            ("2026-10-29", "Torsdag", "open"),
        ]
        assert _statuses(await _days(client, "2026-10-29", "2026-10-29")) == [
            ("2026-10-29", "aften", "open"),
            ("2026-10-29", "Torsdag", "open"),
        ]
        assert (await client.get(DAYS)).status_code == 422


async def test_ids_are_not_reused_after_a_switch_off(make_app: MakeApp) -> None:
    """Switching a program off removes its open day; the day made when it is back on gets a new, greater id."""
    clock = FrozenClock(local(2026, 10, 28, 9))  # a Wednesday
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        [first] = (await _today(client))["open"]
        for active in (False, True):
            response = await client.put(
                f"{PROGRAMS}/{program_id}/active", json={"active": active}
            )
            assert response.status_code == 200, response.text
        [again] = (await _today(client))["open"]
        assert again["id"] > first["id"]
