"""Tests for the programs (spec §5, §3.5 station resolution, §6 change log)."""

from datetime import datetime
from typing import Any

import httpx
import pytest

PROGRAMS = "/api/v1/programs"
CHANGES = "/api/v1/changes"
# Five library exercises, by id.
FIVE = ["0001", "0002", "0003", "0006", "0020"]


def _program(name: str = "Onsdag", **fields: Any) -> dict[str, Any]:
    """Return a minimal valid program document with the given name."""
    return {
        "name": name,
        "weekdays": ["wed"],
        "stations": [{"exercise": "0001"}],
        **fields,
    }


async def _create(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    """Create a program; it must succeed."""
    response = await client.post(PROGRAMS, json=_program(**fields))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


async def _changes(client: httpx.AsyncClient) -> list[dict[str, Any]]:
    """Return the change log, oldest first."""
    response = await client.get(CHANGES, params={"limit": 200})
    assert response.status_code == 200
    rows: list[dict[str, Any]] = response.json()
    return rows[::-1]


async def test_create_fills_defaults_and_returns_names(
    client: httpx.AsyncClient,
) -> None:
    """A minimal document gets every default and the station names."""
    body = await _create(client)
    assert body["program"] == {
        "name": "Onsdag",
        "active": True,
        "weekdays": ["wed"],
        "stations": [{"exercise": "0001"}],
        "rounds": 5,
        "work_seconds": 45,
        "switch_seconds": 15,
        "round_rest_seconds": 60,
        "countdown_seconds": 5,
        "music": None,
    }
    assert body["station_names"] == ["3/4 sit-up"]
    assert isinstance(body["id"], int)


@pytest.mark.parametrize(("rounds", "total"), [(5, 1740), (1, 300)])
async def test_total_seconds(
    client: httpx.AsyncClient, rounds: int, total: int
) -> None:
    """S * R * (W + switch) + (R - 1) * round rest; one round has no round rest."""
    body = await _create(
        client, stations=[{"exercise": ref} for ref in FIVE], rounds=rounds
    )
    assert body["total_seconds"] == total


_BAD_FIELDS: list[tuple[str, Any]] = [
    ("stations", []),
    ("stations", [{"exercise": "0001"}] * 16),
    ("rounds", 0),
    ("rounds", 11),
    ("work_seconds", 9),
    ("work_seconds", 121),
    ("switch_seconds", -1),
    ("switch_seconds", 61),
    ("round_rest_seconds", -1),
    ("round_rest_seconds", 181),
    ("countdown_seconds", 3),
    ("name", ""),
    ("name", "x" * 61),
]
_GOOD_FIELDS: list[tuple[str, Any]] = [
    ("stations", [{"exercise": "0001"}]),
    ("stations", [{"exercise": "0001"}] * 15),
    ("rounds", 1),
    ("rounds", 10),
    ("work_seconds", 10),
    ("work_seconds", 120),
    ("switch_seconds", 0),
    ("switch_seconds", 60),
    ("round_rest_seconds", 0),
    ("round_rest_seconds", 180),
    ("countdown_seconds", 0),
    ("countdown_seconds", 5),
    ("countdown_seconds", 10),
    ("name", "x"),
    ("name", "x" * 60),
]


@pytest.mark.parametrize(
    ("field", "value", "status"),
    [(field, value, 422) for field, value in _BAD_FIELDS]
    + [(field, value, 201) for field, value in _GOOD_FIELDS],
)
async def test_field_ranges(
    client: httpx.AsyncClient, field: str, value: Any, status: int
) -> None:
    """Every field range edge of spec §5.1."""
    response = await client.post(PROGRAMS, json=_program(**{field: value}))
    assert response.status_code == status, response.text
    if status == 201:
        assert response.json()["program"][field] == value


@pytest.mark.parametrize(("name", "status"), [("  Onsdag  ", 201), ("   ", 422)])
async def test_name_is_stripped(
    client: httpx.AsyncClient, name: str, status: int
) -> None:
    """Spaces around the name are dropped; a name of only spaces is empty."""
    response = await client.post(PROGRAMS, json=_program(name=name))
    assert response.status_code == status
    if status == 201:
        assert response.json()["program"]["name"] == "Onsdag"


async def test_unknown_field_is_422(client: httpx.AsyncClient) -> None:
    """Unknown fields are refused, at the top and in a station."""
    assert (await client.post(PROGRAMS, json=_program(colour="red"))).status_code == 422
    stations = [{"exercise": "0001", "reps": 10}]
    response = await client.post(PROGRAMS, json=_program(stations=stations))
    assert response.status_code == 422


async def test_duplicate_weekday_is_422(client: httpx.AsyncClient) -> None:
    """A weekday given twice is refused."""
    response = await client.post(PROGRAMS, json=_program(weekdays=["wed", "wed"]))
    assert response.status_code == 422


async def test_weekdays_stored_in_week_order(client: httpx.AsyncClient) -> None:
    """Weekdays come back in week order."""
    body = await _create(client, weekdays=["sat", "wed"])
    assert body["program"]["weekdays"] == ["wed", "sat"]


async def test_active_without_weekdays_is_422(client: httpx.AsyncClient) -> None:
    """An active program needs at least one weekday."""
    response = await client.post(PROGRAMS, json=_program(weekdays=[]))
    assert response.status_code == 422


async def test_inactive_without_weekdays_ok(client: httpx.AsyncClient) -> None:
    """An inactive program may have no weekdays."""
    body = await _create(client, weekdays=[], active=False)
    assert body["program"]["weekdays"] == []
    assert body["program"]["active"] is False


async def test_activate_without_weekdays_is_422(client: httpx.AsyncClient) -> None:
    """Switching on a program without weekdays is refused, and it stays off."""
    body = await _create(client, weekdays=[], active=False)
    url = f"{PROGRAMS}/{body['id']}"
    response = await client.put(f"{url}/active", json={"active": True})
    assert response.status_code == 422
    assert (await client.get(url)).json()["program"]["active"] is False


@pytest.mark.parametrize(
    ("first", "second"), [("Onsdag", "ONSDAG"), ("Lørdag", "LØRDAG")]
)
async def test_name_unique_case_insensitive(
    client: httpx.AsyncClient, first: str, second: str
) -> None:
    """A name that differs only in case is taken."""
    await _create(client, name=first)
    response = await client.post(PROGRAMS, json=_program(name=second))
    assert response.status_code == 409
    assert len((await client.get(PROGRAMS)).json()) == 1


async def test_update_to_another_programs_name_is_409(
    client: httpx.AsyncClient,
) -> None:
    """Renaming to a taken name fails and leaves both the program and the change log as they were."""
    await _create(client, name="Onsdag")
    saturday = await _create(client, name="Lørdag", rounds=3)
    before = await _changes(client)
    url = f"{PROGRAMS}/{saturday['id']}"
    response = await client.put(url, json=_program(name="onsdag", rounds=4))
    assert response.status_code == 409
    assert (await client.get(url)).json() == saturday
    assert await _changes(client) == before


async def test_times_are_utc_aware(client: httpx.AsyncClient) -> None:
    """Created and updated times are UTC with an offset."""
    body = await _create(client)
    for field in ("created_at", "updated_at"):
        assert body[field].endswith(("+00:00", "Z"))
        assert datetime.fromisoformat(body[field]).utcoffset() is not None
    stored = (await client.get(f"{PROGRAMS}/{body['id']}")).json()
    assert stored["created_at"].endswith(("+00:00", "Z"))


async def test_resolve_by_id(client: httpx.AsyncClient) -> None:
    """A station given by id keeps that id."""
    body = await _create(client, stations=[{"exercise": "0002"}])
    assert body["program"]["stations"] == [{"exercise": "0002"}]


async def test_resolve_by_name_other_case(client: httpx.AsyncClient) -> None:
    """A station given by a name in another case is stored by id."""
    body = await _create(client, stations=[{"exercise": "3/4 SIT-UP"}])
    assert body["program"]["stations"] == [{"exercise": "0001"}]
    assert body["station_names"] == ["3/4 sit-up"]


async def test_resolve_custom_exercise_by_name(client: httpx.AsyncClient) -> None:
    """A custom exercise resolves by its name too."""
    added = await client.post(
        "/api/v1/exercises", json={"name": "Garden squat", "steps": ["Squat."]}
    )
    assert added.status_code == 201
    body = await _create(client, stations=[{"exercise": "garden squat"}])
    assert body["program"]["stations"] == [{"exercise": added.json()["id"]}]
    assert body["station_names"] == ["Garden squat"]


async def test_resolve_ambiguous_name_needs_id(client: httpx.AsyncClient) -> None:
    """A name two exercises share is refused with both of them."""
    name = "self assisted inverse leg curl"
    response = await client.post(PROGRAMS, json=_program(stations=[{"exercise": name}]))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["station"] == 1
    assert "give the id" in detail["message"]
    matches = detail["close_matches"]
    assert len(matches) == 2
    assert {match["name"] for match in matches} == {name}
    assert len({match["id"] for match in matches}) == 2


async def test_create_with_unknown_exercise_lists_close_matches(
    client: httpx.AsyncClient,
) -> None:
    """An unknown exercise names the station and lists close matches, and nothing is stored."""
    stations = [{"exercise": "0001"}, {"exercise": "pushup"}]
    response = await client.post(PROGRAMS, json=_program(stations=stations))
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["station"] == 2
    assert "pushup" in detail["message"]
    assert detail["close_matches"]
    for match in detail["close_matches"]:
        assert set(match) == {"id", "name"}
    assert any(match["name"] == "push-up" for match in detail["close_matches"])
    assert (await client.get(PROGRAMS)).json() == []


async def test_same_exercise_twice_ok(client: httpx.AsyncClient) -> None:
    """The same exercise may be two stations."""
    stations = [{"exercise": "0001"}, {"exercise": "0001"}]
    body = await _create(client, stations=stations)
    assert body["program"]["stations"] == stations
    assert body["station_names"] == ["3/4 sit-up", "3/4 sit-up"]


async def test_list_is_by_name_case_insensitive(client: httpx.AsyncClient) -> None:
    """All programs come back by name, ignoring case."""
    for name in ("onsdag", "Fredag", "Mandag"):
        await _create(client, name=name)
    names = [body["program"]["name"] for body in (await client.get(PROGRAMS)).json()]
    assert names == ["Fredag", "Mandag", "onsdag"]


async def test_replace_set_active_delete(client: httpx.AsyncClient) -> None:
    """Replace, switch off and on, then delete one program."""
    created = await _create(client)
    url = f"{PROGRAMS}/{created['id']}"
    replaced = await client.put(
        url, json=_program(rounds=4, stations=[{"exercise": "0002"}])
    )
    assert replaced.status_code == 200
    assert replaced.json()["program"]["rounds"] == 4
    assert replaced.json()["station_names"] != created["station_names"]
    assert replaced.json()["created_at"] == created["created_at"]

    off = await client.put(f"{url}/active", json={"active": False})
    assert off.status_code == 200
    assert off.json()["program"]["active"] is False
    stored = (await client.get(url)).json()
    assert stored["program"]["active"] is False
    assert stored["program"]["rounds"] == 4

    on = await client.put(f"{url}/active", json={"active": True})
    assert on.status_code == 200
    assert (await client.get(url)).json()["program"]["active"] is True

    deleted = await client.delete(url)
    assert deleted.status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.get(PROGRAMS)).json() == []


async def test_missing_program_is_404(client: httpx.AsyncClient) -> None:
    """Every route on a program that doesn't exist answers 404."""
    url = f"{PROGRAMS}/99"
    assert (await client.get(url)).status_code == 404
    assert (await client.put(url, json=_program())).status_code == 404
    assert (
        await client.put(f"{url}/active", json={"active": False})
    ).status_code == 404
    assert (await client.delete(url)).status_code == 404


async def test_set_active_body_forbids_unknown_fields(
    client: httpx.AsyncClient,
) -> None:
    """The set-active body takes only `active`."""
    created = await _create(client)
    response = await client.put(
        f"{PROGRAMS}/{created['id']}/active", json={"active": False, "x": 1}
    )
    assert response.status_code == 422


async def test_ids_not_reused(client: httpx.AsyncClient) -> None:
    """Deleting the newest program doesn't free its id."""
    await _create(client, name="A")
    b = await _create(client, name="B")
    assert (await client.delete(f"{PROGRAMS}/{b['id']}")).status_code == 204
    c = await _create(client, name="C")
    assert c["id"] > b["id"]


@pytest.mark.parametrize(
    ("music", "status"),
    [
        ({"playlist": "Workout", "speaker": "light.x"}, 422),
        (
            {"playlist": "Workout", "speaker": "media_player.kitchen", "volume": 101},
            422,
        ),
        ({"playlist": "Workout", "speaker": "media_player.kitchen", "volume": -1}, 422),
        ({"playlist": "", "speaker": "media_player.kitchen"}, 422),
        ({"playlist": "x" * 201, "speaker": "media_player.kitchen"}, 422),
        ({"playlist": "Workout", "speaker": "media_player.kitchen", "x": 1}, 422),
        ({"speaker": "media_player.kitchen"}, 422),
        ({"playlist": "x" * 200, "speaker": "media_player.kitchen", "volume": 0}, 201),
        (
            {"playlist": "Workout", "speaker": "media_player.kitchen", "volume": 100},
            201,
        ),
    ],
)
async def test_music_validation(
    client: httpx.AsyncClient, music: dict[str, Any], status: int
) -> None:
    """The music has a playlist, a `media_player.*` speaker and a volume of 0 to 100."""
    response = await client.post(PROGRAMS, json=_program(music=music))
    assert response.status_code == status, response.text


async def test_music_defaults(client: httpx.AsyncClient) -> None:
    """Music without volume and shuffle keeps the speaker's volume and doesn't shuffle."""
    music = {"playlist": "Workout", "speaker": "media_player.kitchen"}
    body = await _create(client, music=music)
    assert body["program"]["music"] == {**music, "volume": None, "shuffle": False}


async def test_change_log_program_actions(client: httpx.AsyncClient) -> None:
    """Each program write logs one row in order; a refused create logs none."""
    created = await _create(client)
    url = f"{PROGRAMS}/{created['id']}"
    target = f"program:{created['id']}"
    assert (
        await client.put(url, json=_program(rounds=4, stations=[{"exercise": "0002"}]))
    ).status_code == 200
    assert (
        await client.put(f"{url}/active", json={"active": False})
    ).status_code == 200
    assert (await client.put(f"{url}/active", json={"active": True})).status_code == 200
    assert (await client.delete(url)).status_code == 204
    bad = await client.post(PROGRAMS, json=_program(stations=[{"exercise": "pushup"}]))
    assert bad.status_code == 422

    rows = await _changes(client)
    assert [row["action"] for row in rows] == [
        "program.created",
        "program.updated",
        "program.deactivated",
        "program.activated",
        "program.deleted",
    ]
    assert {row["target"] for row in rows} == {target}
    assert rows[0]["summary"] == "Created program Onsdag"
    assert rows[1]["summary"] == "Updated program Onsdag: rounds 5 → 4, stations"
    assert rows[4]["summary"] == "Deleted program Onsdag"


async def test_update_summary_names_changed_fields(
    client: httpx.AsyncClient,
) -> None:
    """The update summary gives plain fields with values first, then names the lists and music."""
    created = await _create(client)
    music = {"playlist": "Workout", "speaker": "media_player.kitchen"}
    response = await client.put(
        f"{PROGRAMS}/{created['id']}",
        json=_program(name="Torsdag", weekdays=["thu"], work_seconds=40, music=music),
    )
    assert response.status_code == 200
    summary = (await _changes(client))[-1]["summary"]
    assert summary == (
        "Updated program Torsdag: name Onsdag → Torsdag, work_seconds 45 → 40, "
        "weekdays, music"
    )


async def test_get_then_send_back(client: httpx.AsyncClient) -> None:
    """A got program sent back unchanged is accepted as an update and, renamed, as a create."""
    created = await _create(
        client, stations=[{"exercise": "3/4 sit-up"}, {"exercise": "0002"}]
    )
    url = f"{PROGRAMS}/{created['id']}"
    document = (await client.get(url)).json()["program"]

    replaced = await client.put(url, json=document)
    assert replaced.status_code == 200
    assert replaced.json()["program"] == document
    assert (await _changes(client))[-1]["summary"] == "Updated program Onsdag"

    copy = await client.post(PROGRAMS, json={**document, "name": "Kopi"})
    assert copy.status_code == 201
    assert copy.json()["program"] == {**document, "name": "Kopi"}


async def test_program_equipment_distinct_in_station_order(
    client: httpx.AsyncClient,
) -> None:
    """Each equipment value shows once, in the order the stations first use it."""
    stations = [{"exercise": "0285"}, {"exercise": "0968"}, {"exercise": "0286"}]
    body = await _create(client, stations=stations)
    assert body["equipment"] == ["dumbbell", "band"]
    fetched = await client.get(f"{PROGRAMS}/{body['id']}")
    assert fetched.json()["equipment"] == ["dumbbell", "band"]


async def test_program_equipment_leaves_out_body_weight_and_none(
    client: httpx.AsyncClient,
) -> None:
    """Body weight (in any case) and exercises without equipment add nothing."""
    bare = await client.post(
        "/api/v1/exercises", json={"name": "Bare move", "steps": ["Move."]}
    )
    shouting = await client.post(
        "/api/v1/exercises",
        json={"name": "Loud move", "steps": ["Move."], "equipment": "Body Weight"},
    )
    stations = [
        {"exercise": "0001"},
        {"exercise": bare.json()["id"]},
        {"exercise": shouting.json()["id"]},
        {"exercise": "0285"},
    ]
    body = await _create(client, stations=stations)
    assert body["equipment"] == ["dumbbell"]


async def test_program_equipment_includes_custom_exercises(
    client: httpx.AsyncClient,
) -> None:
    """A custom exercise's equipment counts like a library exercise's."""
    added = await client.post(
        "/api/v1/exercises",
        json={"name": "Garden swing", "steps": ["Swing."], "equipment": "sandbag"},
    )
    assert added.status_code == 201
    body = await _create(
        client, stations=[{"exercise": "0285"}, {"exercise": added.json()["id"]}]
    )
    assert body["equipment"] == ["dumbbell", "sandbag"]


async def test_program_equipment_empty(client: httpx.AsyncClient) -> None:
    """A program of body-weight exercises has no equipment."""
    body = await _create(client)
    assert body["equipment"] == []
