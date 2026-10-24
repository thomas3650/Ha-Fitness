"""Tests for steering a session: the services, the session command, and the programs and people lists."""

import copy
from typing import Any

from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.loader import async_get_integration
import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import PROGRAMS, SESSION_RUNNING, FakeAddon

COMMAND = "ha_fitness/session/command"


def _refusal(code: str) -> dict[str, Any]:
    """Return the body of a refused session route (the workout spec §3.5)."""
    return {"detail": {"code": code, "message": f"refused: {code}"}}


# The add-on's answer, and the code it gives: a refusal's own code, else unavailable.
ERRORS = [
    pytest.param(404, _refusal("not_found"), "not_found", id="not_found"),
    pytest.param(409, _refusal("conflict"), "conflict", id="conflict"),
    pytest.param(422, _refusal("invalid"), "invalid", id="invalid"),
    pytest.param(
        422,
        {"detail": [{"loc": ["body"], "msg": "Field required"}]},
        "unavailable",
        id="field_list",
    ),
    pytest.param(409, _refusal("strange"), "unavailable", id="unknown_code"),
    pytest.param(500, {"detail": "error"}, "unavailable", id="server_error"),
    pytest.param(502, "Bad Gateway", "unavailable", id="not_json"),
    pytest.param(200, "a view?", "unavailable", id="success_not_json"),
]


async def _connected(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> MockConfigEntry:
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    return config_entry


async def _command(client: MockHAClientWebSocket, **data: Any) -> dict[str, Any]:
    await client.send_json_auto_id({"type": COMMAND, **data})
    reply: dict[str, Any] = await client.receive_json()
    return reply


@pytest.mark.usefixtures("cards_bundle")
async def test_start_and_end_services_and_errors(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """The services post start and end; a refusal is a translated error, an outage unavailable."""
    await _connected(hass, config_entry)
    version = (await async_get_integration(hass, DOMAIN)).version
    agent = f"ha_fitness/{version}"

    await hass.services.async_call(
        DOMAIN,
        "start_session",
        {"program_id": 3, "participants": [1, 2], "training_day_id": 12},
        blocking=True,
    )
    await hass.services.async_call(
        DOMAIN, "start_session", {"program_id": 3, "participants": [2]}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "end_session", {}, blocking=True)
    assert fake_addon.session_calls == [
        (
            "start",
            {"program_id": 3, "participants": [1, 2], "training_day_id": 12},
            agent,
        ),
        ("start", {"program_id": 3, "participants": [2]}, agent),
        ("end", None, agent),
    ]

    # The add-on checks the participants, so an empty list reaches it and its refusal shows.
    for status, body, key in [
        (404, _refusal("not_found"), "session_not_found"),
        (409, _refusal("conflict"), "session_conflict"),
        (422, _refusal("invalid"), "session_invalid"),
    ]:
        fake_addon.session_error = (status, body)
        with pytest.raises(ServiceValidationError) as raised:
            await hass.services.async_call(
                DOMAIN,
                "start_session",
                {"program_id": 3, "participants": []},
                blocking=True,
            )
        assert raised.value.translation_domain == DOMAIN
        assert raised.value.translation_key == key
    fake_addon.session_error = (409, _refusal("conflict"))
    with pytest.raises(ServiceValidationError) as raised:
        await hass.services.async_call(DOMAIN, "end_session", {}, blocking=True)
    assert raised.value.translation_key == "session_conflict"

    fake_addon.session_error = (500, {"detail": "error"})
    for service, data in (
        ("start_session", {"program_id": 3, "participants": [1]}),
        ("end_session", {}),
    ):
        with pytest.raises(HomeAssistantError) as outage:
            await hass.services.async_call(DOMAIN, service, data, blocking=True)
        assert not isinstance(outage.value, ServiceValidationError)
        assert outage.value.translation_key == "unavailable"

    await unload(hass, config_entry)
    with pytest.raises(HomeAssistantError) as unloaded:
        await hass.services.async_call(DOMAIN, "end_session", {}, blocking=True)
    assert unloaded.value.translation_key == "unavailable"


@pytest.mark.usefixtures("cards_bundle")
@pytest.mark.parametrize(("status", "body", "code"), ERRORS)
async def test_ws_command_relays_and_maps_errors(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    status: int,
    body: Any,
    code: str,
) -> None:
    """Each command reaches the add-on and returns its view; a refusal keeps the add-on's code."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    started = await _command(
        client, command="start", program_id=3, participants=[1, 2], training_day_id=12
    )
    assert started["success"]
    assert started["result"] == SESSION_RUNNING
    for command in ("pause", "resume", "next", "previous", "end"):
        reply = await _command(client, command=command)
        assert reply["success"]
        assert reply["result"] == SESSION_RUNNING
    assert [call[0] for call in fake_addon.session_calls] == [
        "start",
        "pause",
        "resume",
        "next",
        "previous",
        "end",
    ]
    assert fake_addon.session_calls[0][1] == {
        "program_id": 3,
        "participants": [1, 2],
        "training_day_id": 12,
    }

    fake_addon.session_error = (status, body)
    for data in (
        {"command": "start", "program_id": 3, "participants": [1]},
        {"command": "next"},
    ):
        reply = await _command(client, **data)
        assert not reply["success"]
        assert reply["error"]["code"] == code
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_ws_command_start_needs_its_arguments_and_a_loaded_entry(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A start without a program or participants is invalid; with no add-on, unavailable."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    for data in (
        {"command": "start", "participants": [1]},
        {"command": "start", "program_id": 3},
    ):
        reply = await _command(client, **data)
        assert reply["error"]["code"] == "invalid"
    assert fake_addon.session_calls == []
    reply = await _command(client, command="jump")
    assert not reply["success"]

    await unload(hass, config_entry)
    for message in (
        {"type": COMMAND, "command": "pause"},
        {"type": "ha_fitness/programs"},
        {"type": "ha_fitness/people"},
    ):
        await client.send_json_auto_id(message)
        reply = await client.receive_json()
        assert reply["error"]["code"] == "unavailable"
    assert fake_addon.session_calls == []


@pytest.mark.usefixtures("cards_bundle")
async def test_ws_feeling_relays_the_view_and_keeps_refusal_codes(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """The feeling reaches the add-on and returns the view; a refusal keeps the add-on's code."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    reply = await _command(client, command="feeling", feeling="too_hard")
    assert reply["success"]
    assert reply["result"] == SESSION_RUNNING
    assert [call[:2] for call in fake_addon.session_calls] == [
        ("feeling", {"feeling": "too_hard"})
    ]

    for status, code in ((409, "conflict"), (422, "invalid")):
        fake_addon.session_error = (status, _refusal(code))
        reply = await _command(client, command="feeling", feeling="just_right")
        assert not reply["success"]
        assert reply["error"]["code"] == code
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_ws_feeling_needs_its_value_and_the_addon(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A feeling without a value is invalid and never reaches the add-on; with no add-on, unavailable."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    reply = await _command(client, command="feeling")
    assert reply["error"]["code"] == "invalid"
    assert fake_addon.session_calls == []

    await unload(hass, config_entry)
    reply = await _command(client, command="feeling", feeling="too_easy")
    assert reply["error"]["code"] == "unavailable"
    assert fake_addon.session_calls == []


@pytest.mark.usefixtures("cards_bundle")
async def test_ws_programs_shape_active_only(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """Only the active programs, in the add-on's order, each in exactly §4's shape.

    Søndag stands for an older add-on that sends no equipment: the key stays out. Fredag sends an empty list.
    """
    # A program that needs no equipment, from an add-on that sends the list.
    fredag = copy.deepcopy(PROGRAMS[2])
    fredag["id"] = 6
    fredag["program"]["name"] = "Fredag"
    fredag["equipment"] = []
    fake_addon.programs = [*copy.deepcopy(PROGRAMS), fredag]
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "ha_fitness/programs"})
    reply = await client.receive_json()

    assert reply["success"]
    assert reply["result"] == [
        {
            "id": 3,
            "name": "Onsdag",
            "rounds": 5,
            "work_seconds": 45,
            "switch_seconds": 15,
            "round_rest_seconds": 60,
            "countdown_seconds": 5,
            "total_minutes": 29,
            "total_seconds": 1769,
            "equipment": ["dumbbells", "mat"],
            "stations": [
                {"exercise_id": "0001", "name": "Squat"},
                {"exercise_id": "custom-2", "name": "Wall sit"},
            ],
        },
        {
            "id": 5,
            "name": "Søndag",
            "rounds": 2,
            "work_seconds": 30,
            "switch_seconds": 0,
            "round_rest_seconds": 0,
            "countdown_seconds": 0,
            "total_minutes": 30,
            "total_seconds": 1770,
            "stations": [{"exercise_id": "0002", "name": "Push-up"}],
        },
        {
            "id": 6,
            "name": "Fredag",
            "rounds": 2,
            "work_seconds": 30,
            "switch_seconds": 0,
            "round_rest_seconds": 0,
            "countdown_seconds": 0,
            "total_minutes": 30,
            "total_seconds": 1770,
            "equipment": [],
            "stations": [{"exercise_id": "0002", "name": "Push-up"}],
        },
    ]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_ws_people_shape(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """The people in the add-on's order, each only `{id, name}`."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id({"type": "ha_fitness/people"})
    reply = await client.receive_json()

    assert reply["success"]
    assert reply["result"] == [{"id": 1, "name": "Anna"}, {"id": 2, "name": "Bo"}]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_non_admin_can_use_commands(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A plain user, as the tablet's is, can steer the session, read the lists and subscribe."""
    await _connected(hass, config_entry)
    user = await hass.auth.async_create_user("Tablet", group_ids=[GROUP_ID_USER])
    assert not user.is_admin
    refresh_token = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    client = await hass_ws_client(
        hass, hass.auth.async_create_access_token(refresh_token)
    )

    for message in (
        {"type": COMMAND, "command": "start", "program_id": 3, "participants": [1]},
        {"type": COMMAND, "command": "pause"},
        {"type": "ha_fitness/programs"},
        {"type": "ha_fitness/people"},
    ):
        await client.send_json_auto_id(message)
        assert (await client.receive_json())["success"]

    # The subscriptions answer with their result, then their first event.
    for subscribe in ("ha_fitness/session/subscribe", "ha_fitness/stats/subscribe"):
        await client.send_json_auto_id({"type": subscribe})
        result = await client.receive_json()
        assert result["success"]
        first = await client.receive_json()
        assert first["id"] == result["id"]
        assert "available" in first["event"]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
@pytest.mark.parametrize(
    ("programs", "people", "status"),
    [
        pytest.param(None, None, 500, id="server_error"),
        pytest.param({"programs": []}, [], 200, id="malformed"),
        pytest.param(
            [{**PROGRAMS[1], "station_names": ["Squat"]}],
            {"people": [{"id": 1}]},
            200,
            id="malformed_item",
        ),
    ],
)
async def test_ws_lists_unavailable_when_the_addon_fails(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    programs: Any,
    people: Any,
    status: int,
) -> None:
    """An error status or a body of the wrong shape gives unavailable."""
    await _connected(hass, config_entry)
    client = await hass_ws_client(hass)
    fake_addon.lists_status = status
    fake_addon.programs = programs
    fake_addon.people = people

    for kind in ("programs", "people"):
        await client.send_json_auto_id({"type": f"ha_fitness/{kind}"})
        reply = await client.receive_json()
        assert reply["error"]["code"] == "unavailable"
    await unload(hass, config_entry)
