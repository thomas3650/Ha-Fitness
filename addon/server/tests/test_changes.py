"""Tests for the change log (spec §6)."""

from datetime import UTC, datetime

import httpx
import pytest

from tests.conftest import FrozenClock, MakeApp, running

CHANGES = "/api/v1/changes"
FROZEN = datetime(2026, 10, 28, 9, 30, tzinfo=UTC)


async def _add(client: httpx.AsyncClient, name: str, **headers: str) -> None:
    """Add a custom exercise; it must succeed."""
    response = await client.post(
        "/api/v1/exercises", json={"name": name, "steps": ["Go."]}, headers=headers
    )
    assert response.status_code == 201


async def test_change_log_records_custom_add_with_rest_client(
    client: httpx.AsyncClient,
) -> None:
    """Adding a custom exercise logs who did it, what and when, in UTC."""
    await _add(client, "Garden squat", **{"User-Agent": "pytest"})
    response = await client.get(CHANGES)
    assert response.status_code == 200
    newest = response.json()[0]
    assert newest["client"] == "rest:pytest"
    assert newest["action"] == "exercise.added"
    assert newest["target"] == "exercise:custom-1"
    assert "Garden squat" in newest["summary"]
    assert datetime.fromisoformat(newest["at"]).utcoffset() is not None


async def test_change_log_is_newest_first_and_limited(
    client: httpx.AsyncClient,
) -> None:
    """Entries come newest first, cut to the limit."""
    for name in ("One", "Two", "Three"):
        await _add(client, name)
    targets = [entry["target"] for entry in (await client.get(CHANGES)).json()]
    assert targets == ["exercise:custom-3", "exercise:custom-2", "exercise:custom-1"]
    limited = (await client.get(CHANGES, params={"limit": 2})).json()
    assert [entry["target"] for entry in limited] == targets[:2]


async def test_change_log_client_without_user_agent(
    client: httpx.AsyncClient,
) -> None:
    """Without a User-Agent the client is `rest:unknown`."""
    await _add(client, "Garden squat", **{"User-Agent": ""})
    assert (await client.get(CHANGES)).json()[0]["client"] == "rest:unknown"


async def test_change_log_client_is_cut_to_100_characters(
    client: httpx.AsyncClient,
) -> None:
    """A long User-Agent is cut so the client has at most 100 characters."""
    await _add(client, "Garden squat", **{"User-Agent": "a" * 300})
    assert (await client.get(CHANGES)).json()[0]["client"] == "rest:" + "a" * 95


@pytest.mark.parametrize(("limit", "status"), [(0, 422), (201, 422), (200, 200)])
async def test_change_log_limit_bounds(
    client: httpx.AsyncClient, limit: int, status: int
) -> None:
    """The limit is 1 to 200."""
    response = await client.get(CHANGES, params={"limit": limit})
    assert response.status_code == status


async def test_change_log_stamps_with_the_clock(make_app: MakeApp) -> None:
    """A setup write and a custom exercise are logged at the clock's time, not the system's."""
    async with running(make_app(clock=FrozenClock(FROZEN))) as client:
        await _add(client, "Garden squat")
        setup = {"equipment": ["body weight"], "favourite_playlists": []}
        response = await client.put("/api/v1/setup", json=setup)
        assert response.status_code == 200, response.text
        logged = (await client.get(CHANGES)).json()
    assert [
        (entry["action"], datetime.fromisoformat(entry["at"])) for entry in logged
    ] == [
        ("setup.updated", FROZEN),
        ("exercise.added", FROZEN),
    ]
