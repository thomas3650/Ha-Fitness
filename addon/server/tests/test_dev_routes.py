"""Tests for the dev routes (step 4 spec §3.5): only with `HA_FITNESS_DEV=1`, never in OpenAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx

from tests.conftest import FrozenClock, MakeApp, running
from tests.test_scheduler import FIVE, ZONE, local

DEV = "/api/v1/dev/training-days"
TODAY = "/api/v1/today"
DAYS = "/api/v1/training-days"
PROGRAMS = "/api/v1/programs"


@asynccontextmanager
async def dev_app(
    make_app: MakeApp, clock: FrozenClock
) -> AsyncIterator[httpx.AsyncClient]:
    """Run an app with the dev routes, in Copenhagen time on the frozen clock."""
    app = make_app(settings_overrides={"timezone": ZONE, "dev": True}, clock=clock)
    async with running(app) as client:
        yield client


async def _create(client: httpx.AsyncClient, name: str, weekdays: list[str]) -> int:
    """Create a program of five stations; it must succeed. Return its id."""
    document = {
        "name": name,
        "weekdays": weekdays,
        "stations": [{"exercise": exercise} for exercise in FIVE],
    }
    response = await client.post(PROGRAMS, json=document)
    assert response.status_code == 201, response.text
    program_id: int = response.json()["id"]
    return program_id


async def _open(client: httpx.AsyncClient) -> list[tuple[str, str, str]]:
    """Return the open days of `GET /today` as (name, date, state)."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    return [
        (day["program_name"], day["date"], day["state"])
        for day in response.json()["open"]
    ]


async def _days(client: httpx.AsyncClient, start: str, end: str) -> list[Any]:
    """Return `GET /training-days` for a range as (date, name, status)."""
    response = await client.get(DAYS, params={"from": start, "to": end})
    assert response.status_code == 200, response.text
    return [
        (day["date"], day["program_name"], day["status"]) for day in response.json()
    ]


async def test_dev_routes_absent_without_flag(make_app: MakeApp) -> None:
    """Without the dev flag both routes answer 404, and OpenAPI lists neither, with the flag or without."""
    async with running(make_app()) as client:
        post = await client.post(DEV, json={"program_id": 1, "date": "2026-10-28"})
        delete = await client.delete(DEV, params={"date": "2026-10-28"})
        plain = (await client.get("/openapi.json")).json()
    async with running(make_app(settings_overrides={"dev": True})) as client:
        with_flag = (await client.get("/openapi.json")).json()
    assert post.status_code == 404
    assert delete.status_code == 404
    for schema in (plain, with_flag):
        assert not [path for path in schema["paths"] if "/dev" in path]
    assert "/api/v1/today" in plain["paths"]


async def test_dev_post_creates_late_day_and_reopens_closed(make_app: MakeApp) -> None:
    """`POST` makes an open day on a past date, which reads late, and reopens a closed one."""
    clock = FrozenClock(local(2026, 10, 29, 9))  # a Thursday
    async with dev_app(make_app, clock) as client:
        program_id = await _create(client, "Sample", ["mon"])
        response = await client.post(
            DEV, json={"program_id": program_id, "date": "2026-10-28"}
        )
        assert response.status_code == 200, response.text
        day = response.json()
        assert (day["program_id"], day["date"], day["status"]) == (
            program_id,
            "2026-10-28",
            "open",
        )
        assert day["closed_at"] is None
        assert await _open(client) == [("Sample", "2026-10-28", "late")]
        skip = await client.post(f"{DAYS}/{day['id']}/skip")
        assert skip.status_code == 200, skip.text
        assert await _open(client) == []
        again = await client.post(
            DEV, json={"program_id": program_id, "date": "2026-10-28"}
        )
        assert again.status_code == 200, again.text
        reopened = again.json()
        assert (reopened["id"], reopened["status"], reopened["closed_at"]) == (
            day["id"],
            "open",
            None,
        )
        assert await _open(client) == [("Sample", "2026-10-28", "late")]
        unknown = await client.post(DEV, json={"program_id": 999, "date": "2026-10-28"})
        assert unknown.status_code == 404


async def test_dev_post_rejects_a_date_after_today(make_app: MakeApp) -> None:
    """`POST` for a date after today is a 422 and makes nothing, so open days keep sharing one date."""
    clock = FrozenClock(local(2026, 10, 29, 9))  # a Thursday
    async with dev_app(make_app, clock) as client:
        program_id = await _create(client, "Sample", ["mon"])
        response = await client.post(
            DEV, json={"program_id": program_id, "date": "2026-10-30"}
        )
        assert response.status_code == 422, response.text
        assert isinstance(response.json()["detail"], str)
        today = await client.post(
            DEV, json={"program_id": program_id, "date": "2026-10-29"}
        )
        assert today.status_code == 200, today.text
        assert await _open(client) == [("Sample", "2026-10-29", "due")]
        assert await _days(client, "2026-10-30", "2026-10-30") == []


async def test_dev_delete_removes_open_and_closed(make_app: MakeApp) -> None:
    """`DELETE ?date=` removes every training day of that date, open or closed, and no other."""
    clock = FrozenClock(local(2026, 10, 29, 9))  # a Thursday, when nothing trains
    async with dev_app(make_app, clock) as client:
        onsdag = await _create(client, "Onsdag", ["wed"])
        sample = await _create(client, "Sample", ["mon"])
        made = {}
        for program_id, day in (
            (onsdag, "2026-10-28"),
            (sample, "2026-10-28"),
            (sample, "2026-10-27"),
        ):
            response = await client.post(
                DEV, json={"program_id": program_id, "date": day}
            )
            assert response.status_code == 200, response.text
            made[program_id, day] = response.json()["id"]
        skip = await client.post(f"{DAYS}/{made[sample, '2026-10-28']}/skip")
        assert skip.status_code == 200, skip.text
        response = await client.delete(DEV, params={"date": "2026-10-28"})
        assert response.status_code == 204, response.text
        assert await _days(client, "2026-10-27", "2026-10-28") == [
            ("2026-10-27", "Sample", "open")
        ]
