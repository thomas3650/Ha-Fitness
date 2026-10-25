"""Tests for skipping a training day (step 4 spec §3.4), through REST with a frozen clock."""

from typing import Any

import httpx

from tests.conftest import FrozenClock, MakeApp
from tests.test_scheduler import FIVE, local, started

TODAY = "/api/v1/today"
DAYS = "/api/v1/training-days"
PROGRAMS = "/api/v1/programs"
CHANGES = "/api/v1/changes"


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


async def _open_ids(client: httpx.AsyncClient) -> list[int]:
    """Return the ids of the open days in `GET /today`."""
    response = await client.get(TODAY)
    assert response.status_code == 200, response.text
    return [day["id"] for day in response.json()["open"]]


async def _skip(client: httpx.AsyncClient, day_id: int) -> httpx.Response:
    """Skip a training day as the client `test-agent`."""
    return await client.post(
        f"{DAYS}/{day_id}/skip", headers={"User-Agent": "test-agent"}
    )


async def _days(client: httpx.AsyncClient, start: str, end: str) -> list[Any]:
    """Return `GET /training-days` for a range as (date, name, status)."""
    response = await client.get(DAYS, params={"from": start, "to": end})
    assert response.status_code == 200, response.text
    return [
        (day["date"], day["program_name"], day["status"]) for day in response.json()
    ]


async def test_skip_closes_open_day_and_logs(make_app: MakeApp) -> None:
    """A skip closes the open day as skipped, empties `/today` and logs one change-log row."""
    clock = FrozenClock(local(2026, 10, 28, 9))  # a Wednesday
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        [day_id] = await _open_ids(client)
        clock.set(local(2026, 10, 28, 10))
        response = await _skip(client, day_id)
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body.pop("created_at"), str)
        assert body == {
            "id": day_id,
            "program_id": program_id,
            "program_name": "Onsdag",
            "date": "2026-10-28",
            "status": "skipped",
            "closed_at": "2026-10-28T09:00:00Z",
        }
        assert await _open_ids(client) == []
        changes = await client.get(CHANGES, params={"limit": 1})
    [newest] = changes.json()
    assert {key: newest[key] for key in ("client", "action", "target", "summary")} == {
        "client": "rest:test-agent",
        "action": "training_day.skipped",
        "target": f"training_day:{day_id}",
        "summary": "Skipped Onsdag (2026-10-28)",
    }


async def test_skipped_day_is_not_made_again(make_app: MakeApp) -> None:
    """A skipped day stays skipped through later reconciles and program writes that day."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(make_app, clock) as client:
        program_id = await _create(client, "Onsdag", ["wed"])
        [day_id] = await _open_ids(client)
        assert (await _skip(client, day_id)).status_code == 200
        for active in (False, True):
            switched = await client.put(
                f"{PROGRAMS}/{program_id}/active", json={"active": active}
            )
            assert switched.status_code == 200, switched.text
        clock.set(local(2026, 10, 28, 23, 59))
        assert await _open_ids(client) == []
        assert await _days(client, "2026-10-28", "2026-10-28") == [
            ("2026-10-28", "Onsdag", "skipped")
        ]


async def test_skip_closed_day_is_409(make_app: MakeApp) -> None:
    """Skipping a day that is already closed, skipped or missed, is a 409 and logs nothing."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(make_app, clock, late_days=0) as client:
        await _create(client, "Onsdag", ["wed"])
        await _create(client, "Torsdag", ["thu"])
        [wednesday] = await _open_ids(client)
        clock.set(local(2026, 10, 29, 9))
        [thursday] = await _open_ids(client)  # Wednesday is missed now
        assert (await _skip(client, thursday)).status_code == 200
        before = (await client.get(CHANGES)).json()
        for day_id in (wednesday, thursday):
            response = await _skip(client, day_id)
            assert response.status_code == 409, response.text
            assert isinstance(response.json()["detail"], str)
        assert (await client.get(CHANGES)).json() == before
        assert await _days(client, "2026-10-28", "2026-10-29") == [
            ("2026-10-28", "Onsdag", "missed"),
            ("2026-10-29", "Torsdag", "skipped"),
        ]


async def test_skip_unknown_is_404(make_app: MakeApp) -> None:
    """Skipping an id that no training day has is a 404."""
    clock = FrozenClock(local(2026, 10, 28, 9))
    async with started(make_app, clock) as client:
        response = await _skip(client, 999)
    assert response.status_code == 404
    assert isinstance(response.json()["detail"], str)
