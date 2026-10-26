"""Tests for the REST refusals' stable `code` and `field` (D65) and the opt-in conflict check on a program replace."""

from datetime import datetime, timedelta, timezone
from typing import Any

from fastmcp.exceptions import ToolError
import httpx
import pytest

from tests.conftest import FrozenClock, MakeApp
from tests.session_helpers import (
    PROGRAMS,
    SESSION,
    command,
    create_small,
    set_people,
    start,
    started,
    started_with_mcp,
)
from tests.test_people import ELIN, PEOPLE, THOMAS, FakeHa, ha_app
from tests.test_session_finish import WEDNESDAY_9

EXERCISES = "/api/v1/exercises"


def _program(name: str = "Onsdag", **fields: Any) -> dict[str, Any]:
    """Return a minimal valid program document with the given name."""
    return {
        "name": name,
        "weekdays": ["wed"],
        "stations": [{"exercise": "0001"}],
        **fields,
    }


async def _create(client: httpx.AsyncClient, **fields: Any) -> dict[str, Any]:
    """Create a program; it must succeed. Return the stored program."""
    response = await client.post(PROGRAMS, json=_program(**fields))
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def _refusal(response: httpx.Response, status: int) -> dict[str, Any]:
    """Return a refusal's body after checking its status and that `code` and `field` are there."""
    assert response.status_code == status, response.text
    body: dict[str, Any] = response.json()
    assert set(body) == {"detail", "code", "field"}
    return body


async def test_taken_name_on_create_and_replace(client: httpx.AsyncClient) -> None:
    """A name another program has is `name_taken` at `name`, with the same detail as before."""
    await _create(client, name="Onsdag")
    other = await _create(client, name="Fredag")
    created = await client.post(PROGRAMS, json=_program("onsdag"))
    replaced = await client.put(f"{PROGRAMS}/{other['id']}", json=_program("ONSDAG"))
    for response, name in ((created, "onsdag"), (replaced, "ONSDAG")):
        body = _refusal(response, 409)
        assert body == {
            "detail": f"Program name '{name}' is taken",
            "code": "name_taken",
            "field": "name",
        }


async def test_taken_custom_exercise_name(client: httpx.AsyncClient) -> None:
    """A custom exercise with a name already in the library is `name_taken` at `name` too."""
    response = await client.post(
        EXERCISES,
        json={"name": "3/4 sit-up", "steps": ["Sit up."]},
    )
    body = _refusal(response, 409)
    assert body["code"] == "name_taken"
    assert body["field"] == "name"
    assert body["detail"] == "Exercise name '3/4 sit-up' is taken"


async def test_not_found_has_the_default_code(client: httpx.AsyncClient) -> None:
    """A refusal without its own code gets the default for its kind."""
    body = _refusal(await client.get(f"{PROGRAMS}/999"), 404)
    assert body == {
        "detail": "Program 999 not found",
        "code": "not_found",
        "field": None,
    }


async def test_session_running_on_delete_and_switch_off(make_app: MakeApp) -> None:
    """A delete or `active: false` during the program's session is `session_running`, with no field."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        url = f"{PROGRAMS}/{program['id']}"
        refused = [
            await client.delete(url),
            await client.put(f"{url}/active", json={"active": False}),
            await client.put(url, json={**program["program"], "active": False}),
        ]
    for response in refused:
        body = _refusal(response, 409)
        assert body == {
            "detail": "A session for this program is running",
            "code": "session_running",
            "field": None,
        }


async def test_active_without_weekdays_is_at_weekdays(
    client: httpx.AsyncClient,
) -> None:
    """An active program without weekdays is a 422 item at `weekdays`, typed `weekday_needed`."""
    response = await client.post(PROGRAMS, json=_program(weekdays=[]))
    assert response.status_code == 422, response.text
    items = response.json()["detail"]
    [item] = [item for item in items if item["type"] == "weekday_needed"]
    assert item["loc"] == ["body", "weekdays"]
    assert "at least one weekday" in item["msg"]


async def test_bad_active_without_weekdays_is_a_422_for_active(
    client: httpx.AsyncClient,
) -> None:
    """A wrong `active` with no weekdays is a 422 about `active`, not a crash."""
    response = await client.post(PROGRAMS, json=_program(weekdays=[], active="x"))
    assert response.status_code == 422, response.text
    locs = [item["loc"] for item in response.json()["detail"]]
    assert ["body", "active"] in locs


async def test_switch_on_without_weekdays_is_weekday_needed(
    client: httpx.AsyncClient,
) -> None:
    """`PUT /active` on a program without weekdays is `weekday_needed` at `weekdays`."""
    program = await _create(client, weekdays=[], active=False)
    response = await client.put(
        f"{PROGRAMS}/{program['id']}/active", json={"active": True}
    )
    body = _refusal(response, 422)
    assert body["code"] == "weekday_needed"
    assert body["field"] == "weekdays"
    assert isinstance(body["detail"], str)


async def test_unknown_station_is_at_its_index(client: httpx.AsyncClient) -> None:
    """An unknown third station is `station_unknown` at `stations.2`; the detail is the same dict."""
    stations = [{"exercise": "0001"}, {"exercise": "0002"}, {"exercise": "no such"}]
    response = await client.post(PROGRAMS, json=_program(stations=stations))
    body = _refusal(response, 422)
    assert body["code"] == "station_unknown"
    assert body["field"] == "stations.2"
    assert body["detail"]["message"] == "Unknown exercise 'no such'"
    assert body["detail"]["station"] == 3
    assert isinstance(body["detail"]["close_matches"], list)


async def test_shared_station_name_is_station_shared(
    client: httpx.AsyncClient,
) -> None:
    """A station named by a name two exercises share is `station_shared` at its index."""
    stations = [{"exercise": "lever chest press"}]
    response = await client.post(PROGRAMS, json=_program(stations=stations))
    body = _refusal(response, 422)
    assert body["code"] == "station_shared"
    assert body["field"] == "stations.0"
    assert {match["id"] for match in body["detail"]["close_matches"]} >= {
        "0576",
        "0577",
    }


async def test_people_refusals_have_codes(make_app: MakeApp) -> None:
    """Three people, a person twice and an unknown HA person are refused at `people`, each with its own code."""
    third = {"name": "Guest", "person_entity_id": "person.guest"}
    async with ha_app(make_app, FakeHa()) as client:
        responses = {
            "too_many_people": await client.put(
                PEOPLE, json={"people": [THOMAS, ELIN, third]}
            ),
            "person_twice": await client.put(
                PEOPLE, json={"people": [THOMAS, {**THOMAS, "name": "Tom"}]}
            ),
            "person_unknown": await client.put(PEOPLE, json={"people": [third]}),
        }
    for code, response in responses.items():
        body = _refusal(response, 422)
        assert body["code"] == code
        assert body["field"] == "people"
    assert isinstance(responses["person_unknown"].json()["detail"], dict)


async def test_ha_unreachable_is_ha_unavailable(make_app: MakeApp) -> None:
    """HA unreachable on the people write is a 503 `ha_unavailable`, with no field."""
    ha = FakeHa()
    ha.down = True
    async with ha_app(make_app, ha) as client:
        response = await client.put(PEOPLE, json={"people": [THOMAS]})
    body = _refusal(response, 503)
    assert body["code"] == "ha_unavailable"
    assert body["field"] is None
    assert "Home Assistant" in body["detail"]


async def test_if_updated_at_equal_saves(client: httpx.AsyncClient) -> None:
    """The stored `updated_at` given back lets the replace through."""
    program = await _create(client)
    response = await client.put(
        f"{PROGRAMS}/{program['id']}",
        json=_program(rounds=3),
        params={"if_updated_at": program["updated_at"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()["program"]["rounds"] == 3


async def test_if_updated_at_compares_instants(client: httpx.AsyncClient) -> None:
    """The same instant in another offset is still equal."""
    program = await _create(client)
    url = f"{PROGRAMS}/{program['id']}"
    stored = (await client.get(url)).json()["updated_at"]
    shifted = (
        datetime.fromisoformat(stored)
        .astimezone(timezone(timedelta(hours=1)))
        .isoformat()
    )
    response = await client.put(
        url, json=_program(rounds=3), params={"if_updated_at": shifted}
    )
    assert response.status_code == 200, response.text


async def test_if_updated_at_different_is_changed_elsewhere(
    client: httpx.AsyncClient,
) -> None:
    """After another write, the old `updated_at` is refused with `changed_elsewhere` and nothing changes."""
    program = await _create(client)
    url = f"{PROGRAMS}/{program['id']}"
    other = await client.put(url, json=_program(rounds=4))
    assert other.status_code == 200, other.text
    response = await client.put(
        url, json=_program(rounds=3), params={"if_updated_at": program["updated_at"]}
    )
    body = _refusal(response, 409)
    assert body["code"] == "changed_elsewhere"
    assert body["field"] is None
    assert isinstance(body["detail"], str)
    assert (await client.get(url)).json()["program"]["rounds"] == 4


async def test_if_updated_at_omitted_saves_after_another_write(
    client: httpx.AsyncClient,
) -> None:
    """Without `if_updated_at` a replace saves as before, whatever was written in between."""
    program = await _create(client)
    url = f"{PROGRAMS}/{program['id']}"
    await client.put(url, json=_program(rounds=4))
    response = await client.put(url, json=_program(rounds=3))
    assert response.status_code == 200, response.text


async def test_two_saves_in_a_row_with_the_previous_updated_at(
    client: httpx.AsyncClient,
) -> None:
    """Each save given the previous answer's `updated_at` goes through."""
    program = await _create(client)
    url = f"{PROGRAMS}/{program['id']}"
    first = await client.put(
        url, json=_program(rounds=4), params={"if_updated_at": program["updated_at"]}
    )
    assert first.status_code == 200, first.text
    second = await client.put(
        url,
        json=_program(rounds=3),
        params={"if_updated_at": first.json()["updated_at"]},
    )
    assert second.status_code == 200, second.text


async def test_session_route_refusal_keeps_its_shape(make_app: MakeApp) -> None:
    """A session route's refusal is still `{detail: {code, message}}`, with no top-level code."""
    async with started(FrozenClock(WEDNESDAY_9), make_app) as client:
        response = await command(client, "pause")
        current = await client.get(SESSION)
    assert response.status_code in (404, 409), response.text
    body = response.json()
    assert set(body) == {"detail"}
    assert set(body["detail"]) == {"code", "message"}
    assert current.status_code == 200


async def test_mcp_refusal_texts_are_unchanged(make_app: MakeApp) -> None:
    """MCP's text for a taken name and a running session stays the plain detail."""
    async with started_with_mcp(FrozenClock(WEDNESDAY_9), make_app) as (
        client,
        mcp_client,
    ):
        [thomas] = await set_people(client, THOMAS)
        program = await create_small(client, "Lille")
        await start(client, program["id"], [thomas])
        with pytest.raises(ToolError) as taken:
            await mcp_client.call_tool("create_program", {"program": _program("lille")})
        with pytest.raises(ToolError) as running_session:
            await mcp_client.call_tool("delete_program", {"program_id": program["id"]})
    assert str(taken.value) == "Program name 'lille' is taken"
    assert str(running_session.value) == "A session for this program is running"
