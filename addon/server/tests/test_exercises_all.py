"""Tests for reading every exercise, the target facet and the household filter (website spec §2.3, §2.4.5, D63)."""

from typing import Any

import httpx

EXERCISES = "/api/v1/exercises"
ALL = "/api/v1/exercises/all"
SETUP = "/api/v1/setup"


async def _add_custom(client: httpx.AsyncClient, name: str, **fields: Any) -> str:
    """Add a custom exercise and return its id."""
    response = await client.post(
        EXERCISES, json={"name": name, "steps": ["Stand up."], **fields}
    )
    assert response.status_code == 201, response.text
    exercise_id: str = response.json()["id"]
    return exercise_id


async def _set_equipment(client: httpx.AsyncClient, equipment: list[str]) -> None:
    """Store a setup with this equipment."""
    response = await client.put(SETUP, json={"equipment": equipment})
    assert response.status_code == 200, response.text


async def test_all_has_every_exercise_by_name(client: httpx.AsyncClient) -> None:
    """`/exercises/all` lists every library and custom exercise as a summary, sorted by name, with `target`."""
    custom = await _add_custom(client, "Garden squat", target="glutes")
    response = await client.get(ALL)
    assert response.status_code == 200, response.text
    exercises = response.json()
    assert len(exercises) == 1324 + 1
    names = [exercise["name"].casefold() for exercise in exercises]
    assert names == sorted(names)
    first = next(exercise for exercise in exercises if exercise["id"] == "0001")
    assert first == {
        "id": "0001",
        "name": "3/4 sit-up",
        "equipment": "body weight",
        "body_part": "waist",
        "target": "abs",
        "custom": False,
    }
    added = next(exercise for exercise in exercises if exercise["id"] == custom)
    assert added["custom"] is True
    assert added["target"] == "glutes"
    assert all(exercise["target"] for exercise in exercises)


async def test_facets_have_target(client: httpx.AsyncClient) -> None:
    """An empty search's facets list the target muscles too, sorted, custom ones included."""
    await _add_custom(client, "Garden squat", target="garden muscle")
    facets = (await client.get(EXERCISES)).json()["facets"]
    assert "abs" in facets["target"]
    assert "garden muscle" in facets["target"]
    assert facets["target"] == sorted(set(facets["target"]))


async def test_household_filter(client: httpx.AsyncClient) -> None:
    """`household=true` keeps the setup's equipment, body weight always, and every custom exercise."""
    await _set_equipment(client, ["dumbbell"])
    plain = await _add_custom(client, "Garden squat")
    cable = await _add_custom(client, "Garden cable row", equipment="cable")
    response = await client.get(EXERCISES, params={"household": "true", "limit": 100})
    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert len(results) == 100
    assert {result["equipment"] for result in results if not result["custom"]} == {
        "body weight",
        "dumbbell",
    }

    found = (
        await client.get(EXERCISES, params={"household": "true", "q": "garden"})
    ).json()["results"]
    assert {result["id"] for result in found} == {plain, cable}
    dumbbell = (
        await client.get(
            EXERCISES, params={"household": "true", "equipment": "dumbbell"}
        )
    ).json()["results"]
    assert dumbbell
    assert all(result["equipment"] == "dumbbell" for result in dumbbell)


async def test_household_filter_drops_equipment_not_in_the_setup(
    client: httpx.AsyncClient,
) -> None:
    """A library cable exercise is left out with the household filter and found without it."""
    await _set_equipment(client, ["dumbbell"])
    cables = (
        await client.get(EXERCISES, params={"household": "true", "equipment": "cable"})
    ).json()["results"]
    assert cables == []
    without = (
        await client.get(EXERCISES, params={"equipment": "cable", "limit": 3})
    ).json()["results"]
    assert len(without) == 3


async def test_household_filter_default_setup_is_body_weight(
    client: httpx.AsyncClient,
) -> None:
    """Before any setup is stored the household has body weight only; without the flag nothing changes."""
    household = (
        await client.get(EXERCISES, params={"household": "true", "limit": 100})
    ).json()["results"]
    assert {result["equipment"] for result in household} == {"body weight"}
    everything = (await client.get(EXERCISES, params={"limit": 100})).json()
    assert len({result["equipment"] for result in everything["results"]}) > 1
