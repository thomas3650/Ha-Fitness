"""Tests for the card's subscription, ha_fitness/today/subscribe, and the music in the cards' commands and subscription."""

import asyncio
from collections.abc import Callable
import copy
from datetime import timedelta
from typing import Any

from homeassistant.components.media_player.const import MediaPlayerState
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
from .music_fakes import (
    DEFAULT_PLAYERS,
    Player,
    async_setup_music_assistant,
    async_setup_other_player,
)
from .music_workout import MUSIC, START_CALLS, Workout, names, subscribe, view

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
    """Music Assistant's media players by name, not by entity id; other entities left out.

    An unavailable or unknown player is marked; a player without a friendly name goes by its entity id.
    """
    await set_up(hass, config_entry)
    music_entry, players = await async_setup_music_assistant(
        hass, (*DEFAULT_PLAYERS, Player("bathroom", "Bathroom speaker"))
    )
    other_entry, _ = await async_setup_other_player(hass)
    players["media_player.bathroom"].set_available(False)
    players["media_player.kitchen"].set_unknown()
    players["media_player.living_room"].set_name(None)
    await hass.async_block_till_done()
    client = await hass_ws_client(hass)

    result = await _result(client, {"type": "ha_fitness/speakers"})

    assert result == {
        "speakers": [
            {
                "entity_id": "media_player.bathroom",
                "name": "Bathroom speaker",
                "available": False,
            },
            {
                "entity_id": "media_player.kitchen",
                "name": "Kitchen speaker",
                "available": False,
            },
            {
                "entity_id": "media_player.living_room",
                "name": "media_player.living_room",
                "available": True,
            },
            {
                "entity_id": "media_player.garage",
                "name": "Workshop speaker",
                "available": True,
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
    other_entry, _ = await async_setup_other_player(hass)
    client = await hass_ws_client(hass)

    assert await _result(client, {"type": "ha_fitness/speakers"}) == {"speakers": []}
    await unload(hass, other_entry)
    await unload(hass, config_entry)


# The music in the session subscription, and `ha_fitness/music` (the music spec §5.4 and §5.5).

KITCHEN_WAITING = {
    "playlist_name": "Workout Mix",
    "speaker": "media_player.kitchen",
    "speaker_name": "Kitchen speaker",
    "state": "waiting",
}


async def _next_event(client: MockHAClientWebSocket) -> dict[str, Any]:
    """Return the next event of the client's one subscription."""
    message = await client.receive_json()
    assert message["type"] == "event", message
    event: dict[str, Any] = message["event"]
    return event


async def _event_until(
    client: MockHAClientWebSocket, condition: Callable[[dict[str, Any]], bool]
) -> dict[str, Any]:
    """Return the first event for which the condition holds, skipping the ones before it."""
    while not condition(event := await _next_event(client)):
        pass
    return event


def _assert_error(reply: dict[str, Any], code: str, key: str) -> None:
    assert not reply["success"], reply
    assert reply["error"]["code"] == code
    assert reply["error"]["translation_key"] == key
    assert reply["error"]["translation_domain"] == DOMAIN


async def test_subscription_sends_music(
    workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """The session subscription sends `{available, session, music}`, music null while there is no session."""
    client = await hass_ws_client(workout.hass)
    _, first = await subscribe(client)
    assert first == {"available": True, "session": None, "music": None}

    await workout.push(view())

    event = await _next_event(client)
    assert set(event) == {"available", "session", "music"}
    assert event["available"] is True
    assert event["session"]["id"] == 7
    assert event["music"] == KITCHEN_WAITING


async def test_subscription_resends_on_speaker_state_change(
    hass: HomeAssistant, workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """A change of the speaker's state is sent; a change of only its attributes isn't."""
    await workout.push(view(started_at=workout.setup_time + timedelta(seconds=10)))
    client = await hass_ws_client(hass)
    _, first = await subscribe(client)
    assert first["music"]["state"] == "playing"

    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": "media_player.kitchen", "volume_level": 0.3},
        blocking=True,
    )
    await hass.services.async_call(
        "media_player",
        "media_pause",
        {"entity_id": "media_player.kitchen"},
        blocking=True,
    )

    assert (await _next_event(client))["music"]["state"] == "paused"


async def test_subscription_music_null_without_music(
    workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """A running session of a program without music has no music."""
    client = await hass_ws_client(workout.hass)
    await subscribe(client)

    await workout.push(
        view(music=None, started_at=workout.setup_time + timedelta(seconds=10))
    )

    event = await _next_event(client)
    assert event["session"]["id"] == 7
    assert event["music"] is None


async def test_music_state_each_value(hass: HomeAssistant, workout: Workout) -> None:
    """Waiting, playing, paused (also when the speaker reports idle), unavailable; null without a session.

    Null also once Music Assistant's entry is unloaded.
    """
    started = workout.setup_time + timedelta(seconds=10)
    assert await workout.music_state() is None
    await workout.push(view())
    assert await workout.music_state() == KITCHEN_WAITING
    await workout.push(view(started_at=started))
    assert await workout.state() == "playing"
    await workout.push(view(status="paused", started_at=started))
    assert await workout.state() == "paused"
    # Music Assistant 2.10.8's web player reports idle after a pause.
    workout.kitchen.paused_state = MediaPlayerState.IDLE
    await workout.push(view(started_at=started))
    await workout.push(view(status="paused", started_at=started))
    speaker = hass.states.get("media_player.kitchen")
    assert speaker is not None
    assert speaker.state == MediaPlayerState.IDLE
    assert await workout.state() == "paused"
    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    assert await workout.state() == "unavailable"
    workout.kitchen.set_available(True)
    await hass.async_block_till_done()
    assert await workout.state() == "paused"

    music_entry = hass.config_entries.async_entries("music_assistant")[0]
    await unload(hass, music_entry)

    assert await workout.music_state() is None


async def test_open_subscription_music_null_after_music_assistant_unloads(
    hass: HomeAssistant, workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """A live subscription gets music null when Music Assistant's entry is unloaded during a session."""
    await workout.push(view(started_at=workout.setup_time + timedelta(seconds=10)))
    client = await hass_ws_client(hass)
    _, first = await subscribe(client)
    assert first["music"]["state"] == "playing"

    music_entry = hass.config_entries.async_entries("music_assistant")[0]
    await unload(hass, music_entry)

    event = await _event_until(client, lambda event: event["music"] != first["music"])
    assert event["session"] is not None
    assert event["music"] is None


async def test_music_state_kept_across_disconnect(
    workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """While the add-on is unreachable, the subscription still sends the music."""
    await workout.push(view(started_at=workout.setup_time + timedelta(seconds=10)))
    client = await hass_ws_client(workout.hass)
    await subscribe(client)

    await workout.fake_addon.close_ws()

    event = await _next_event(client)
    assert event["available"] is False
    assert event["music"] == {**KITCHEN_WAITING, "state": "playing"}


async def test_subscription_music_follows_music_supported(
    workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """The music goes null when the add-on's probe finds no music route, and comes back when it does."""
    await workout.push(view())
    client = await hass_ws_client(workout.hass)
    _, first = await subscribe(client)
    assert first["music"] == KITCHEN_WAITING

    workout.fake_addon.no_music = True
    await workout.fake_addon.push(
        {"type": "hello", "version": "0.2.0", "api_version": 1}
    )
    await _event_until(client, lambda event: event["music"] is None)

    workout.fake_addon.no_music = False
    await workout.fake_addon.push(
        {"type": "hello", "version": "0.3.0", "api_version": 1}
    )
    await _event_until(client, lambda event: event["music"] == KITCHEN_WAITING)
    assert workout.kitchen.calls == []


async def test_music_command_actions(workout: Workout) -> None:
    """Pause, play and next go to the speaker; the workout isn't changed."""
    await workout.push(view(started_at=workout.setup_time + timedelta(seconds=10)))

    for action in ("pause", "play", "next"):
        reply = await workout.command(action)
        assert reply["success"], reply
        assert reply["result"] is None
        if action == "pause":
            assert await workout.state() == "paused"
    await workout.hass.async_block_till_done()

    assert names(workout.kitchen) == [
        *START_CALLS,
        "media_pause",
        "media_play",
        "media_next_track",
    ]
    assert await workout.state() == "playing"
    assert workout.fake_addon.session_calls == []


async def test_play_after_failure_runs_start(
    hass: HomeAssistant, workout: Workout, hass_ws_client: WebSocketGenerator
) -> None:
    """After a failed start, Play runs the start; the music reads waiting at once, before any call lands."""
    started = workout.setup_time + timedelta(seconds=10)
    workout.kitchen.fail = {"play_media"}
    await workout.push(view(started_at=started))
    assert await workout.state() == "unavailable"
    client = await hass_ws_client(hass)
    await subscribe(client)
    workout.kitchen.fail = set()
    held = asyncio.Event()
    workout.kitchen.hold["volume_set"] = held

    await workout.client.send_json_auto_id(
        {"type": "ha_fitness/music", "action": "play"}
    )
    # Commands are handled in order, so once the speakers answer, Play waits for the held call.
    await workout.client.send_json_auto_id({"type": "ha_fitness/speakers"})
    assert (await workout.client.receive_json())["result"]["speakers"]
    # A later change of the session: the waiting music must come before it.
    await workout.push(view(started_at=started, revision=5), settle=False)

    event = await _next_event(client)
    assert event["music"]["state"] == "waiting"
    assert event["session"]["revision"] == 4
    assert names(workout.kitchen) == ["volume_set", "play_media"]
    held.set()
    reply = await workout.client.receive_json()
    assert reply["success"], reply
    assert names(workout.kitchen) == ["volume_set", "play_media", *START_CALLS]
    assert await workout.state() == "playing"


async def test_play_after_start_nu_while_paused_runs_start(workout: Workout) -> None:
    """Waiting with started_at set ("Start nu" while paused): Play runs the start, and the workout stays paused."""
    started = workout.setup_time + timedelta(seconds=5)
    await workout.push(view())
    await workout.push(view(status="paused"))
    await workout.push(view(status="paused", started_at=started))
    assert await workout.state() == "waiting"

    reply = await workout.command("play")

    assert reply["success"], reply
    assert names(workout.kitchen) == START_CALLS
    assert await workout.state() == "playing"
    assert workout.fake_addon.session_calls == []


async def test_play_during_countdown_is_not_found(workout: Workout) -> None:
    """In the countdown the music starts at its end: Play is not_found and makes no call."""
    await workout.push(view())

    _assert_error(await workout.command("play"), "not_found", "music_not_found")
    assert workout.kitchen.calls == []
    assert await workout.state() == "waiting"


@pytest.mark.parametrize("action", ["play", "pause"])
async def test_command_checks_the_session_in_the_lock(
    workout: Workout, action: str
) -> None:
    """A command that waits behind a speaker call is not_found once its session has ended, and calls nothing.

    Play would run the start, Pause would pause the speaker.
    """
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(view(started_at=started))
    held = asyncio.Event()
    workout.kitchen.hold["media_pause"] = held
    await workout.push(view(status="paused", started_at=started), settle=False)
    # Another session, waiting with started_at set, so Play would run the start.
    await workout.push(view(id=8, status="paused", started_at=started), settle=False)
    await workout.client.send_json_auto_id(
        {"type": "ha_fitness/music", "action": action}
    )
    # Commands are handled in order, so once the speakers answer, the command waits for the speaker call.
    await workout.client.send_json_auto_id({"type": "ha_fitness/speakers"})
    assert (await workout.client.receive_json())["result"]["speakers"]

    await workout.push(None, settle=False)
    held.set()

    _assert_error(await workout.client.receive_json(), "not_found", "music_not_found")
    await workout.hass.async_block_till_done()
    assert names(workout.kitchen) == [*START_CALLS, "media_pause"]


async def test_music_command_errors(hass: HomeAssistant, workout: Workout) -> None:
    """not_found without a session with music, or without the entry; unavailable for a speaker that can't play."""
    started = workout.setup_time + timedelta(seconds=10)
    _assert_error(await workout.command("pause"), "not_found", "music_not_found")
    await workout.push(view(music=None, started_at=started))
    _assert_error(await workout.command("next"), "not_found", "music_not_found")

    await workout.push(view(started_at=started))
    workout.kitchen.fail = {"media_next_track"}
    _assert_error(await workout.command("next"), "unavailable", "music_unavailable")
    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    _assert_error(await workout.command("pause"), "unavailable", "music_unavailable")
    assert names(workout.kitchen) == [*START_CALLS, "media_next_track"]

    await unload(hass, workout.entry)
    _assert_error(await workout.command("pause"), "not_found", "music_not_found")


async def test_music_command_unavailable_on_other_platform(
    hass: HomeAssistant, workout: Workout
) -> None:
    """A speaker that isn't a Music Assistant player gets no call: the command is unavailable."""
    other_entry, tv_player = await async_setup_other_player(hass)
    music = {**MUSIC, "speaker": "media_player.tv"}
    # Adopted: started before the controller, so it is followed as started.
    await workout.push(
        view(music=music, started_at=workout.setup_time - timedelta(minutes=3))
    )

    _assert_error(await workout.command("pause"), "unavailable", "music_unavailable")
    assert tv_player.calls == []
    assert await workout.state() == "unavailable"
    await unload(hass, other_entry)


async def test_schema_error_fails_the_start(workout: Workout) -> None:
    """A call the service's schema refuses fails the start, and Play's retry is unavailable."""
    music = {**MUSIC, "volume": 150}
    await workout.push(
        view(music=music, started_at=workout.setup_time + timedelta(seconds=10))
    )
    assert await workout.state() == "unavailable"

    _assert_error(await workout.command("play"), "unavailable", "music_unavailable")
    assert workout.kitchen.calls == []
    assert await workout.state() == "unavailable"
