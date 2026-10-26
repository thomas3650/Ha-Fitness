"""Tests for the household setup (website spec §2.4, D63)."""

from typing import Any

import httpx
import pytest

from tests.conftest import MakeApp, running

SETUP = "/api/v1/setup"
CHANGES = "/api/v1/changes"
PLAYLIST = {"uri": "library://playlist/1", "name": "Morgen"}


def _setup(**fields: Any) -> dict[str, Any]:
    """Return a setup body; the fields given replace the defaults."""
    return {
        "equipment": ["body weight"],
        "favourite_playlists": [],
        "default_speaker": None,
        **fields,
    }


async def test_setup_starts_with_the_defaults(client: httpx.AsyncClient) -> None:
    """Before any write the setup has body weight, no favourite playlists and no default speaker."""
    response = await client.get(SETUP)
    assert response.status_code == 200, response.text
    assert response.json() == _setup()


async def test_setup_round_trip(make_app: MakeApp) -> None:
    """A written setup is read back the same, also after a restart; equipment comes back sorted and once each."""
    body = _setup(
        equipment=["kettlebell", "dumbbell", "kettlebell", "body weight"],
        favourite_playlists=[
            PLAYLIST,
            {"uri": "library://playlist/2", "name": "Aften"},
        ],
        default_speaker="media_player.kitchen",
    )
    expected = body | {"equipment": ["body weight", "dumbbell", "kettlebell"]}
    async with running(make_app()) as client:
        response = await client.put(SETUP, json=body)
        assert response.status_code == 200, response.text
        assert response.json() == expected
    async with running(make_app()) as client:
        assert (await client.get(SETUP)).json() == expected


async def test_body_weight_is_always_in(client: httpx.AsyncClient) -> None:
    """A setup written without body weight still has it."""
    response = await client.put(SETUP, json=_setup(equipment=["dumbbell"]))
    assert response.status_code == 200, response.text
    assert response.json()["equipment"] == ["body weight", "dumbbell"]
    assert (await client.get(SETUP)).json()["equipment"] == ["body weight", "dumbbell"]


async def test_unknown_equipment_is_refused(client: httpx.AsyncClient) -> None:
    """Equipment no exercise has is a 422 with `equipment_unknown`, and nothing is stored."""
    response = await client.put(
        SETUP, json=_setup(equipment=["dumbbell", "trampoline"])
    )
    assert response.status_code == 422
    assert response.json()["code"] == "equipment_unknown"
    assert response.json()["field"] == "equipment"
    assert (await client.get(SETUP)).json() == _setup()


async def test_custom_exercise_equipment_is_accepted(client: httpx.AsyncClient) -> None:
    """Equipment only a custom exercise has is a choice too."""
    added = await client.post(
        "/api/v1/exercises",
        json={
            "name": "Pull-up on the bar",
            "steps": ["Hang from the bar.", "Pull up."],
            "equipment": "pull-up bar",
        },
    )
    assert added.status_code == 201, added.text
    response = await client.put(SETUP, json=_setup(equipment=["pull-up bar"]))
    assert response.status_code == 200, response.text
    assert response.json()["equipment"] == ["body weight", "pull-up bar"]


@pytest.mark.parametrize(
    "fields",
    [
        {"favourite_playlists": [PLAYLIST, PLAYLIST | {"name": "Igen"}]},
        {
            "favourite_playlists": [
                {"uri": f"library://playlist/{n}", "name": f"P{n}"} for n in range(21)
            ]
        },
        {"default_speaker": "light.kitchen"},
    ],
    ids=["duplicate-uri", "21-playlists", "not-a-speaker"],
)
async def test_bad_setup_is_refused(
    client: httpx.AsyncClient, fields: dict[str, Any]
) -> None:
    """A playlist given twice, more than 20 playlists, or a default speaker that isn't a media player is a 422."""
    response = await client.put(SETUP, json=_setup(**fields))
    assert response.status_code == 422
    assert (await client.get(SETUP)).json() == _setup()


async def test_twenty_playlists_are_allowed(client: httpx.AsyncClient) -> None:
    """Twenty favourite playlists is the most there can be."""
    playlists = [{"uri": f"library://playlist/{n}", "name": f"P{n}"} for n in range(20)]
    response = await client.put(SETUP, json=_setup(favourite_playlists=playlists))
    assert response.status_code == 200, response.text
    assert response.json()["favourite_playlists"] == playlists


async def test_setup_write_is_logged(client: httpx.AsyncClient) -> None:
    """A setup write leaves a `setup.updated` row with the REST client."""
    await client.put(
        SETUP, json=_setup(equipment=["dumbbell"]), headers={"User-Agent": "website"}
    )
    rows = (await client.get(CHANGES)).json()
    assert rows[0]["action"] == "setup.updated"
    assert rows[0]["client"] == "rest:website"
