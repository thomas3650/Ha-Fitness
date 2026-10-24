"""Tests for the music controller: the music follows the session (the music spec §5.1 and §5.2).

The views come from the fake add-on's push channel; the calls and states are the mock Music Assistant's.
The clock is frozen on a whole second before the entry is set up, so the controller's own start time is that
second: a session started before it is adopted, one started at it or later is not.
"""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from .common import is_open, set_up, unload, wait_for
from .fake_addon import SESSION_RUNNING, FakeAddon
from .music_fakes import (
    MockPlayer,
    async_setup_music_assistant,
    async_setup_other_player,
)

SESSION_RUNNING_SENSOR = "binary_sensor.ha_fitness_session_running"
PLAYLIST = "library://playlist/1"
MUSIC: dict[str, Any] = {
    "playlist": PLAYLIST,
    "playlist_name": "Workout Mix",
    "speaker": "media_player.kitchen",
    "volume": 70,
    "shuffle": True,
}
START_CALLS = ["volume_set", "play_media", "shuffle_set"]


def _iso(moment: datetime) -> str:
    """Write a UTC time as the add-on does: milliseconds and Z."""
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _view(
    status: str = "running",
    started_at: datetime | None = None,
    music: dict[str, Any] | None = MUSIC,
    **changes: Any,
) -> dict[str, Any]:
    """Return a session view with music; `started_at` None is the countdown."""
    return {
        **SESSION_RUNNING,
        "status": status,
        "started_at": None if started_at is None else _iso(started_at),
        "music": music,
        **changes,
    }


def _names(player: MockPlayer) -> list[str]:
    return [name for name, _ in player.calls]


class Workout:
    """The set-up test: the fake add-on, the entry, the players and the frozen setup time."""

    def __init__(
        self,
        hass: HomeAssistant,
        fake_addon: FakeAddon,
        entry: MockConfigEntry,
        players: dict[str, MockPlayer],
        setup_time: datetime,
    ) -> None:
        """Keep what the tests drive."""
        self.hass = hass
        self.fake_addon = fake_addon
        self.entry = entry
        self.players = players
        self.setup_time = setup_time

    @property
    def kitchen(self) -> MockPlayer:
        """The plan's speaker: a Music Assistant player that can set its volume."""
        return self.players["media_player.kitchen"]

    async def push(self, view: dict[str, Any] | None) -> None:
        """Send a session view, and wait until the integration has it and the controller's calls are done."""
        await self.fake_addon.push({"type": "session", "data": view})
        await wait_for(self.hass, lambda: self.entry.runtime_data.session == view)
        await self.hass.async_block_till_done()

    def music_state(self) -> dict[str, Any] | None:
        """The music state the subscription will send (Task 8 sends it over the ws)."""
        state: dict[str, Any] | None = self.entry.runtime_data.music.music_state()
        return state


async def _set_up_workout(
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
    cards_bundle: Path,
) -> AsyncGenerator[Workout]:
    """A loaded entry whose add-on supports music, with Music Assistant's players; unloaded afterwards."""
    music_entry, players, setup_time = await _set_up_workout(
        hass, freezer, fake_addon, config_entry
    )
    await wait_for(hass, lambda: config_entry.runtime_data.music_supported)
    yield Workout(hass, fake_addon, config_entry, players, setup_time)
    if config_entry.state is ConfigEntryState.LOADED:
        await unload(hass, config_entry)
    await unload(hass, music_entry)


async def test_start_at_countdown_end(workout: Workout) -> None:
    """The countdown's end sets the volume, replaces the queue with the playlist, then sets shuffle."""
    await workout.push(_view())
    assert workout.kitchen.calls == []
    assert workout.music_state() == {
        "playlist_name": "Workout Mix",
        "speaker": "media_player.kitchen",
        "speaker_name": "Kitchen speaker",
        "state": "waiting",
    }

    await workout.push(_view(started_at=workout.setup_time + timedelta(seconds=10)))

    assert workout.kitchen.calls == [
        ("volume_set", {"volume_level": 0.7}),
        (
            "play_media",
            {"media_id": [PLAYLIST], "media_type": "playlist", "enqueue": "replace"},
        ),
        ("shuffle_set", {"shuffle": True}),
    ]
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "playing"


async def test_start_without_volume_set_support(workout: Workout) -> None:
    """A speaker that can't set its volume only gets the playlist and shuffle."""
    music = {**MUSIC, "speaker": "media_player.garage", "playlist_name": None}
    await workout.push(_view(music=music))
    await workout.push(
        _view(music=music, started_at=workout.setup_time + timedelta(seconds=10))
    )

    assert _names(workout.players["media_player.garage"]) == [
        "play_media",
        "shuffle_set",
    ]
    assert workout.kitchen.calls == []
    state = workout.music_state()
    assert state is not None
    assert state["playlist_name"] == PLAYLIST


async def test_countdown_zero_first_seen_started_after_setup(
    workout: Workout,
) -> None:
    """A session first seen already started, at the controller's start or later, starts the music."""
    await workout.push(_view(started_at=workout.setup_time))

    assert _names(workout.kitchen) == START_CALLS


async def test_start_nu_while_paused_starts_on_resume(workout: Workout) -> None:
    """Start nu while paused sets started_at but stays paused; the Resume starts the music, not play."""
    started = workout.setup_time + timedelta(seconds=5)
    await workout.push(_view())
    await workout.push(_view(status="paused"))
    await workout.push(_view(status="paused", started_at=started))
    assert workout.kitchen.calls == []

    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == START_CALLS


async def test_adopted_session_pauses_but_never_starts(workout: Workout) -> None:
    """A session started before the controller (a restart mid-workout) is followed, never started."""
    started = workout.setup_time - timedelta(minutes=3)
    await workout.push(_view(started_at=started))
    assert workout.kitchen.calls == []

    await workout.push(_view(status="paused", started_at=started))
    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == ["media_pause", "media_play"]


async def test_pause_and_resume(workout: Workout) -> None:
    """After the start, the workout's Pause pauses the music and its Resume plays it."""
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view())
    await workout.push(_view(started_at=started))

    await workout.push(_view(status="paused", started_at=started))
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "paused"
    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == [*START_CALLS, "media_pause", "media_play"]


async def test_annuller_in_countdown_does_nothing(workout: Workout) -> None:
    """Pause, Resume and Annullér during the countdown make no call."""
    await workout.push(_view())
    await workout.push(_view(status="paused"))
    await workout.push(_view())
    await workout.push(_view(status="ended"))
    await workout.push(None)

    assert workout.kitchen.calls == []
    assert workout.music_state() is None


async def test_no_music_program_does_nothing(workout: Workout) -> None:
    """A session without music makes no call and has no music state."""
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(music=None))
    await workout.push(_view(music=None, started_at=started))
    await workout.push(_view(music=None, status="paused", started_at=started))

    assert all(player.calls == [] for player in workout.players.values())
    assert workout.music_state() is None


async def test_failed_start_is_unavailable_and_workout_goes_on(
    hass: HomeAssistant, workout: Workout
) -> None:
    """A start on an unavailable speaker isn't tried; the music is unavailable and the workout runs."""
    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    await workout.push(_view())

    await workout.push(_view(started_at=workout.setup_time + timedelta(seconds=10)))

    assert workout.kitchen.calls == []
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "unavailable"
    session_state = hass.states.get(SESSION_RUNNING_SENSOR)
    assert session_state is not None
    assert session_state.state == "on"


async def test_failed_start_retried_on_resume(
    hass: HomeAssistant, workout: Workout
) -> None:
    """A start whose call raises is failed: Pause makes no call, and the Resume starts again."""
    started = workout.setup_time + timedelta(seconds=10)
    workout.kitchen.fail = {"play_media"}
    await workout.push(_view())
    await workout.push(_view(started_at=started))
    assert _names(workout.kitchen) == ["volume_set", "play_media"]
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "unavailable"

    workout.kitchen.fail = set()
    # A change of the available speaker's attributes is no reason to retry.
    await hass.services.async_call(
        "media_player",
        "volume_set",
        {"entity_id": "media_player.kitchen", "volume_level": 0.5},
        blocking=True,
    )
    await hass.async_block_till_done()
    await workout.push(_view(status="paused", started_at=started))
    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == [
        "volume_set",
        "play_media",
        "volume_set",
        *START_CALLS,
    ]


async def test_failed_start_retried_when_speaker_returns(
    hass: HomeAssistant, workout: Workout
) -> None:
    """A speaker that comes back while the workout runs gets the start; not while it's paused."""
    started = workout.setup_time + timedelta(seconds=10)
    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    await workout.push(_view(started_at=started))
    await workout.push(_view(status="paused", started_at=started))

    workout.kitchen.set_available(True)
    await hass.async_block_till_done()
    assert workout.kitchen.calls == []

    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    await workout.push(_view(started_at=started))
    assert workout.kitchen.calls == []
    workout.kitchen.set_available(True)
    await hass.async_block_till_done()

    assert _names(workout.kitchen) == START_CALLS


async def test_start_on_non_music_assistant_speaker_fails(
    hass: HomeAssistant, workout: Workout
) -> None:
    """A speaker of another platform gets no call, and the music is unavailable."""
    other_entry = await async_setup_other_player(hass)
    music = {**MUSIC, "speaker": "media_player.tv"}
    await workout.push(_view(music=music))

    await workout.push(
        _view(music=music, started_at=workout.setup_time + timedelta(seconds=10))
    )

    # A call would have changed the television's state or volume.
    tv = hass.states.get("media_player.tv")
    assert tv is not None
    assert tv.state == "idle"
    assert tv.attributes["volume_level"] == pytest.approx(0.4)
    state = workout.music_state()
    assert state is not None
    assert state["speaker_name"] == "A television"
    assert state["state"] == "unavailable"
    await unload(hass, other_entry)


async def test_failed_pause_after_start_stays_started(workout: Workout) -> None:
    """A Pause whose call raises leaves the music started: the next Resume still plays."""
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(started_at=started))
    workout.kitchen.fail = {"media_pause"}

    await workout.push(_view(status="paused", started_at=started))
    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == [*START_CALLS, "media_pause", "media_play"]


@pytest.mark.usefixtures("cards_bundle")
async def test_no_start_without_music_supported(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """Against an add-on from before music, the controller makes no call."""
    fake_addon.no_music = True
    music_entry, players, setup_time = await _set_up_workout(
        hass, freezer, fake_addon, config_entry
    )
    await wait_for(hass, lambda: fake_addon.music_requests >= 1)
    workout = Workout(hass, fake_addon, config_entry, players, setup_time)
    started = setup_time + timedelta(seconds=10)

    await workout.push(_view())
    await workout.push(_view(started_at=started))
    await workout.push(_view(status="paused", started_at=started))
    await workout.push(_view(started_at=started))

    assert workout.kitchen.calls == []
    assert workout.music_state() is None
    await unload(hass, config_entry)
    await unload(hass, music_entry)
