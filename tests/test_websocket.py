"""Tests for the card's subscription, ha_fitness/today/subscribe, and the music in the cards' commands."""

import copy
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.ha_fitness.const import DOMAIN

from .common import is_open, set_up, unload, wait_for
from .fake_addon import PROGRAMS, TODAY_DUE, FakeAddon
from .music_fakes import async_setup_music_assistant, async_setup_other_player

SUBSCRIBE = {"type": "ha_fitness/today/subscribe"}


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_sends_data_and_null(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """The subscription sends today at once and after each change, and null on a disconnect."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    result = await client.receive_json()
    assert result["success"]
    first = await client.receive_json()
    assert first["type"] == "event"
    assert first["id"] == result["id"]
    assert first["event"] == TODAY_DUE

    changed = copy.deepcopy(TODAY_DUE)
    changed["open"] = []
    await fake_addon.push({"type": "today", "data": changed})
    assert (await client.receive_json())["event"] == changed

    await fake_addon.close_ws()
    assert (await client.receive_json())["event"] is None
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_sends_null_without_loaded_entry_then_data(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """Subscribed before the entry is set up, it sends null, then the data once the add-on connects."""
    await set_up(hass, config_entry)
    await unload(hass, config_entry)
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"] is None

    assert await hass.config_entries.async_setup(config_entry.entry_id)
    assert (await client.receive_json())["event"] == TODAY_DUE

    await unload(hass, config_entry)
    assert (await client.receive_json())["event"] is None


@pytest.mark.usefixtures("cards_bundle")
async def test_subscription_passes_the_week_through(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A week in the add-on's today reaches the card as it is."""
    week = {"done": 1, "planned": 3}
    fake_addon.today = {**copy.deepcopy(TODAY_DUE), "week": week}
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    client = await hass_ws_client(hass)

    await client.send_json_auto_id(SUBSCRIBE)
    assert (await client.receive_json())["success"]
    assert (await client.receive_json())["event"]["week"] == week
    await unload(hass, config_entry)


START = {
    "type": "ha_fitness/session/command",
    "command": "start",
    "program_id": 3,
    "participants": [1],
}


async def _music_probed(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> None:
    """Set the entry up and wait until the add-on is open and the music probe found its music route."""
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    await wait_for(hass, lambda: config_entry.runtime_data.music_supported)


async def _result(client: MockHAClientWebSocket, message: dict[str, Any]) -> Any:
    await client.send_json_auto_id(message)
    reply = await client.receive_json()
    assert reply["success"], reply
    return reply["result"]


@pytest.mark.usefixtures("cards_bundle")
async def test_programs_carry_music(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """Each program carries its music as the add-on sends it, or null; a program without the key gives null."""
    without_key = copy.deepcopy(PROGRAMS[2])
    without_key["id"] = 6
    without_key["program"]["name"] = "Tirsdag"
    del without_key["program"]["music"]
    fake_addon.programs = [*copy.deepcopy(PROGRAMS), without_key]
    await _music_probed(hass, fake_addon, config_entry)
    client = await hass_ws_client(hass)

    programs = await _result(client, {"type": "ha_fitness/programs"})

    assert {program["id"]: program["music"] for program in programs} == {
        3: {
            "playlist": "library://playlist/1",
            "playlist_name": "Workout Mix",
            "speaker": "media_player.speaker",
            "volume": 40,
            "shuffle": False,
        },
        5: None,
        6: None,
    }
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_start_passes_speaker(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A start's speaker reaches the add-on; a start without one sends none."""
    await _music_probed(hass, fake_addon, config_entry)
    client = await hass_ws_client(hass)

    await _result(client, {**START, "speaker": "media_player.kitchen_2"})
    await _result(client, START)

    assert [call[1] for call in fake_addon.session_calls] == [
        {"program_id": 3, "participants": [1], "speaker": "media_player.kitchen_2"},
        {"program_id": 3, "participants": [1]},
    ]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_start_rejects_bad_speaker(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A speaker that isn't a media player's entity id is invalid and never reaches the add-on."""
    await _music_probed(hass, fake_addon, config_entry)
    client = await hass_ws_client(hass)

    for speaker in (
        "light.kitchen",
        "media_player.Kitchen",
        "media_player.",
        "media_player.kitchen\n",
        "media_player.kitchen speaker",
        "",
    ):
        await client.send_json_auto_id({**START, "speaker": speaker})
        reply = await client.receive_json()
        assert not reply["success"]
        assert reply["error"]["code"] == "invalid"
    assert fake_addon.session_calls == []
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_no_music_without_music_supported(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    issue_registry: ir.IssueRegistry,
) -> None:
    """Once the add-on lacks music, programs carry no music and a start drops its speaker."""
    await _music_probed(hass, fake_addon, config_entry)
    client = await hass_ws_client(hass)

    # The add-on is replaced by one from before music: the probe after its hello gets 404.
    fake_addon.no_music = True
    await fake_addon.push({"type": "hello", "version": "0.2.0", "api_version": 1})
    await wait_for(
        hass,
        lambda: issue_registry.async_get_issue(DOMAIN, "addon_too_old") is not None,
    )

    programs = await _result(client, {"type": "ha_fitness/programs"})
    assert [program["music"] for program in programs] == [None, None]

    await _result(client, {**START, "speaker": "media_player.kitchen"})
    assert [call[1] for call in fake_addon.session_calls] == [
        {"program_id": 3, "participants": [1]}
    ]
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_speakers_lists_music_assistant_players(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
) -> None:
    """Music Assistant's media players by name, unavailable ones marked; other entities left out."""
    await set_up(hass, config_entry)
    music_entry, players = await async_setup_music_assistant(hass)
    other_entry = await async_setup_other_player(hass)
    players["media_player.living_room"].set_available(False)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    result = await _result(client, {"type": "ha_fitness/speakers"})

    assert result == {
        "speakers": [
            {
                "entity_id": "media_player.garage",
                "name": "Garage speaker",
                "available": True,
            },
            {
                "entity_id": "media_player.kitchen",
                "name": "Kitchen speaker",
                "available": True,
            },
            {
                "entity_id": "media_player.living_room",
                "name": "Living room speaker",
                "available": False,
            },
        ]
    }
    await unload(hass, other_entry)
    await unload(hass, music_entry)
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_speakers_empty_without_music_assistant(
    hass: HomeAssistant,
    hass_ws_client: WebSocketGenerator,
    config_entry: MockConfigEntry,
) -> None:
    """Without Music Assistant the list is empty, other platforms' media players left out."""
    await set_up(hass, config_entry)
    other_entry = await async_setup_other_player(hass)
    client = await hass_ws_client(hass)

    assert await _result(client, {"type": "ha_fitness/speakers"}) == {"speakers": []}
    await unload(hass, other_entry)
    await unload(hass, config_entry)
