"""Tests for the exercise library: search, lookup and custom exercises (spec §3.4, §3.5)."""

from typing import Any

import httpx
import pytest

EXERCISES = "/api/v1/exercises"


def _custom(name: str, **fields: Any) -> dict[str, Any]:
    """Return a valid custom exercise body with the given name."""
    return {"name": name, "steps": ["Stand up.", "Sit down."], **fields}


async def _search(client: httpx.AsyncClient, **params: Any) -> dict[str, Any]:
    """Search and return the body; the search must succeed."""
    response = await client.get(EXERCISES, params=params)
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


async def test_search_prefix_first(client: httpx.AsyncClient) -> None:
    """Names that start with the query come before the ones that only contain it."""
    body = await _search(client, q="push-up", limit=100)
    names = [result["name"] for result in body["results"]]
    assert all("push-up" in name for name in names)
    starts = [name.startswith("push-up") for name in names]
    assert "push-up" in names
    assert "side push-up" in names
    assert starts == sorted(starts, reverse=True)
    assert body["facets"] is None


async def test_search_matches_every_word_case_insensitive(
    client: httpx.AsyncClient,
) -> None:
    """Every word of the query must be in the name, in any case and order."""
    body = await _search(client, q="PUSH-UP incline", limit=100)
    names = [result["name"] for result in body["results"]]
    assert "incline push-up" in names
    assert all("incline" in name and "push-up" in name for name in names)


async def test_search_filters_by_equipment(client: httpx.AsyncClient) -> None:
    """The equipment filter matches exactly."""
    body = await _search(client, equipment="kettlebell", limit=100)
    assert body["results"]
    assert all(result["equipment"] == "kettlebell" for result in body["results"])
    assert body["facets"] is None


async def test_search_filters_by_body_part(client: httpx.AsyncClient) -> None:
    """The body-part filter matches exactly."""
    body = await _search(client, body_part="upper legs")
    assert body["results"]
    assert all(result["body_part"] == "upper legs" for result in body["results"])


@pytest.mark.parametrize(("limit", "status"), [(0, 422), (101, 422), (100, 200)])
async def test_search_limit_bounds(
    client: httpx.AsyncClient, limit: int, status: int
) -> None:
    """The limit is 1 to 100."""
    response = await client.get(EXERCISES, params={"limit": limit})
    assert response.status_code == status
    if status == 200:
        assert len(response.json()["results"]) == 100


async def test_empty_search_returns_facets(client: httpx.AsyncClient) -> None:
    """An empty search lists the first exercises by name and the values to filter by."""
    body = await _search(client)
    assert len(body["results"]) == 20
    names = [result["name"].casefold() for result in body["results"]]
    assert names == sorted(names)
    assert "body weight" in body["facets"]["equipment"]
    assert "upper legs" in body["facets"]["body_part"]
    assert body["facets"]["equipment"] == sorted(body["facets"]["equipment"])


async def test_get_exercise_has_steps_and_attribution(
    client: httpx.AsyncClient,
) -> None:
    """One library exercise comes with its steps and the media attribution."""
    response = await client.get(f"{EXERCISES}/0001")
    assert response.status_code == 200
    exercise = response.json()
    assert exercise["name"] == "3/4 sit-up"
    assert len(exercise["steps"]) == 5
    assert "Gym visual" in exercise["attribution"]
    assert exercise["custom"] is False
    assert (await client.get(f"{EXERCISES}/nope")).status_code == 404
    assert (await client.get(f"{EXERCISES}/custom-1")).status_code == 404


async def test_add_custom_exercise(client: httpx.AsyncClient) -> None:
    """Custom exercises get the next id, are searchable and have no attribution."""
    response = await client.post(
        EXERCISES, json=_custom("Garden squat", equipment="body weight")
    )
    assert response.status_code == 201
    created = response.json()
    assert created["id"] == "custom-1"
    assert created["custom"] is True
    assert created["attribution"] is None
    assert created["steps"] == ["Stand up.", "Sit down."]

    found = await _search(client, q="garden")
    assert [(r["id"], r["custom"]) for r in found["results"]] == [("custom-1", True)]
    fetched = await client.get(f"{EXERCISES}/custom-1")
    assert fetched.json() == created

    second = await client.post(EXERCISES, json=_custom("Garden lunge"))
    assert second.status_code == 201
    assert second.json()["id"] == "custom-2"
    assert second.json()["equipment"] is None


async def test_custom_name_taken_case_insensitive(client: httpx.AsyncClient) -> None:
    """A custom name may not equal a library or custom name in any case; a refused add logs nothing."""
    taken = await client.post(EXERCISES, json=_custom("3/4 SIT-UP"))
    assert taken.status_code == 409
    assert (await client.get("/api/v1/changes")).json() == []

    first = await client.post(EXERCISES, json=_custom("Æble løft"))
    assert first.status_code == 201
    again = await client.post(EXERCISES, json=_custom("ÆBLE LØFT"))
    assert again.status_code == 409
    assert len((await client.get("/api/v1/changes")).json()) == 1


@pytest.mark.parametrize(
    "body",
    [
        _custom(""),
        _custom("x" * 81),
        {"name": "No steps", "steps": []},
        {"name": "Many steps", "steps": [f"Step {n}." for n in range(11)]},
        _custom("Extra field", colour="red"),
    ],
    ids=["empty-name", "long-name", "no-steps", "eleven-steps", "unknown-field"],
)
async def test_custom_exercise_limits(
    client: httpx.AsyncClient, body: dict[str, Any]
) -> None:
    """Names are 1 to 80 characters, steps 1 to 10, and unknown fields are refused."""
    response = await client.post(EXERCISES, json=body)
    assert response.status_code == 422


async def test_custom_exercise_limit_edges_ok(client: httpx.AsyncClient) -> None:
    """An 80-character name with 10 steps is accepted."""
    body = {"name": "x" * 80, "steps": [f"Step {n}." for n in range(10)]}
    assert (await client.post(EXERCISES, json=body)).status_code == 201


async def test_library_counts(client: httpx.AsyncClient) -> None:
    """The library reports its library and custom exercise counts."""
    response = await client.get("/api/v1/library")
    assert response.status_code == 200
    assert response.json()["exercises"] == {"library": 721, "custom": 0}
    await client.post(EXERCISES, json=_custom("Garden squat"))
    response = await client.get("/api/v1/library")
    assert response.json()["exercises"] == {"library": 721, "custom": 1}
