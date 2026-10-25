"""A set-up workout with music, shared by the music controller's tests and the cards' websocket tests.

The views come from the fake add-on's push channel; the calls and states are the mock Music Assistant's.
The clock is frozen on a whole second before the entry is set up, so the controller's own start time is that
second: a session started before it is adopted, one started at it or later is not. The music state is read
the way the cards read it: through `ha_fitness/session/subscribe`.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from .common import is_open, set_up, unload, wait_for
from .fake_addon import SESSION_RUNNING, FakeAddon
from .music_fakes import MockPlayer, async_setup_music_assistant

SESSION_SUBSCRIBE = {"type": "ha_fitness/session/subscribe"}
PLAYLIST = "library://playlist/1"
MUSIC: dict[str, Any] = {
    "playlist": PLAYLIST,
    "playlist_name": "Workout Mix",
    "speaker": "media_player.kitchen",
    "volume": 70,
    "shuffle": True,
}
START_CALLS = ["volume_set", "play_media", "shuffle_set"]


def iso(moment: datetime) -> str:
    """Write a UTC time as the add-on does: milliseconds and Z."""
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def view(
    status: str = "running",
    started_at: datetime | None = None,
    music: dict[str, Any] | None = MUSIC,
    **changes: Any,
) -> dict[str, Any]:
    """Return a session view with music; `started_at` None is the countdown."""
    return {
        **SESSION_RUNNING,
        "status": status,
        "started_at": None if started_at is None else iso(started_at),
        "music": music,
        **changes,
    }


def names(player: MockPlayer) -> list[str]:
    """Return the names of the player's calls, in order."""
    return [name for name, _ in player.calls]


async def yield_loop(rounds: int = 100) -> None:
    """Let the event loop run the tasks that can go on."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def subscribe(client: MockHAClientWebSocket) -> tuple[int, dict[str, Any]]:
    """Subscribe to the session; return the subscription's id and its first event."""
    await client.send_json_auto_id(SESSION_SUBSCRIBE)
    result = await client.receive_json()
    assert result["success"], result
    first = await client.receive_json()
    assert first["id"] == result["id"]
    event: dict[str, Any] = first["event"]
    return result["id"], event


async def unsubscribe(client: MockHAClientWebSocket, subscription: int) -> None:
    """End a subscription; skip its events until the answer."""
    await client.send_json_auto_id(
        {"type": "unsubscribe_events", "subscription": subscription}
    )
    while True:
        reply = await client.receive_json()
        if reply["type"] == "result":
            assert reply["success"], reply
            return


async def music_command(client: MockHAClientWebSocket, action: str) -> dict[str, Any]:
    """Send `ha_fitness/music`; return the reply."""
    await client.send_json_auto_id({"type": "ha_fitness/music", "action": action})
    reply: dict[str, Any] = await client.receive_json()
    return reply


class Workout:
    """The set-up test: the fake add-on, the entry, the players, the frozen setup time and a ws client."""

    def __init__(
        self,
        hass: HomeAssistant,
        fake_addon: FakeAddon,
        entry: MockConfigEntry,
        players: dict[str, MockPlayer],
        setup_time: datetime,
        client: MockHAClientWebSocket,
    ) -> None:
        """Keep what the tests drive."""
        self.hass = hass
        self.fake_addon = fake_addon
        self.entry = entry
        self.players = players
        self.setup_time = setup_time
        self.client = client

    @property
    def kitchen(self) -> MockPlayer:
        """The plan's speaker: a Music Assistant player that can set its volume."""
        return self.players["media_player.kitchen"]

    async def push(self, session: dict[str, Any] | None, settle: bool = True) -> None:
        """Send a session view, and wait until the integration has it.

        With `settle`, also wait until the controller's calls are done.
        """
        await self.fake_addon.push({"type": "session", "data": session})
        await wait_for(self.hass, lambda: self.entry.runtime_data.session == session)
        if settle:
            await self.hass.async_block_till_done()

    async def music_state(self) -> dict[str, Any] | None:
        """Return the music state the session subscription sends now (a fresh subscription's first event)."""
        subscription, event = await subscribe(self.client)
        await unsubscribe(self.client, subscription)
        music: dict[str, Any] | None = event["music"]
        return music

    async def state(self) -> str:
        """Return the music state's `state`; the music state must be there."""
        music = await self.music_state()
        assert music is not None
        state: str = music["state"]
        return state

    async def command(self, action: str) -> dict[str, Any]:
        """Send `ha_fitness/music`; return the reply."""
        return await music_command(self.client, action)


async def set_up_workout(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> tuple[MockConfigEntry, dict[str, MockPlayer], datetime]:
    """Freeze the clock, set up Music Assistant and the entry, and wait until the add-on is open."""
    freezer.move_to(dt_util.utcnow().replace(microsecond=0))
    setup_time = dt_util.utcnow()
    music_entry, players = await async_setup_music_assistant(hass)
    await set_up(hass, config_entry)
    await wait_for(hass, lambda: is_open(hass))
    return music_entry, players, setup_time


@pytest.fixture
async def workout(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    cards_bundle: Any,
) -> AsyncGenerator[Workout]:
    """A loaded entry whose add-on supports music, with Music Assistant's players; unloaded afterwards."""
    music_entry, players, setup_time = await set_up_workout(
        hass, freezer, fake_addon, config_entry
    )
    await wait_for(hass, lambda: config_entry.runtime_data.music_supported)
    client = await hass_ws_client(hass)
    yield Workout(hass, fake_addon, config_entry, players, setup_time, client)
    for player in players.values():
        player.release()
    if config_entry.state is ConfigEntryState.LOADED:
        await unload(hass, config_entry)
    if music_entry.state is ConfigEntryState.LOADED:
        await unload(hass, music_entry)
