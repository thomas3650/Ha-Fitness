"""Tests for the music controller: the music follows the session (the music spec §5.1 to §5.3).

The views come from the fake add-on's push channel; the calls and states are the mock Music Assistant's.
The clock is frozen on a whole second before the entry is set up, so the controller's own start time is that
second: a session started before it is adopted, one started at it or later is not.

The fade's steps are driven by `freezer.tick` and `async_fire_time_changed_exact`: the plain
`async_fire_time_changed` reaches 0.5 s past the time it is given, one step too far.
"""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from freezegun.api import FrozenDateTimeFactory
from homeassistant.components.media_player.const import MediaPlayerState
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed_exact,
)

from custom_components.ha_fitness.const import SIGNAL_UPDATE

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
# The kitchen's level after the start (the plan's volume 70), and the fade's ten steps from it down to 0.
START_LEVEL = 0.7
FADE_LEVELS = [START_LEVEL * (10 - step) / 10 for step in range(1, 11)]


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


def _levels(calls: list[tuple[str, dict[str, Any]]]) -> list[float]:
    """Return the levels of the `volume_set` calls."""
    return [
        arguments["volume_level"] for name, arguments in calls if name == "volume_set"
    ]


async def _yield(rounds: int = 100) -> None:
    """Let the event loop run the tasks that can go on."""
    for _ in range(rounds):
        await asyncio.sleep(0)


async def _tick(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    seconds: float,
    settle: bool = True,
) -> None:
    """Move the clock on, fire what is due by then, and let its calls finish.

    Without `settle`, only let the loop run a while: a held call would keep `async_block_till_done` waiting.
    """
    freezer.tick(timedelta(seconds=seconds))
    async_fire_time_changed_exact(hass, dt_util.utcnow())
    if settle:
        await hass.async_block_till_done()
    else:
        await _yield()


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

    async def push(self, view: dict[str, Any] | None, settle: bool = True) -> None:
        """Send a session view, and wait until the integration has it.

        With `settle`, also wait until the controller's calls are done.
        """
        await self.fake_addon.push({"type": "session", "data": view})
        await wait_for(self.hass, lambda: self.entry.runtime_data.session == view)
        if settle:
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
    for player in players.values():
        player.release()
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


@pytest.mark.parametrize(
    "paused_state", [MediaPlayerState.PAUSED, MediaPlayerState.IDLE]
)
async def test_pause_and_resume(
    workout: Workout, paused_state: MediaPlayerState
) -> None:
    """After the start, the workout's Pause pauses the music and its Resume plays it.

    A paused speaker reads paused, also when it reports idle, as Music Assistant's web player does.
    """
    workout.kitchen.paused_state = paused_state
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view())
    await workout.push(_view(started_at=started))

    await workout.push(_view(status="paused", started_at=started))
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "paused"
    speaker = workout.hass.states.get("media_player.kitchen")
    assert speaker is not None
    assert speaker.state == paused_state
    await workout.push(_view(started_at=started))

    assert _names(workout.kitchen) == [*START_CALLS, "media_pause", "media_play"]
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "playing"


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
    other_entry, tv_player = await async_setup_other_player(hass)
    music = {**MUSIC, "speaker": "media_player.tv"}
    await workout.push(_view(music=music))

    await workout.push(
        _view(music=music, started_at=workout.setup_time + timedelta(seconds=10))
    )

    assert tv_player.calls == []
    state = workout.music_state()
    assert state is not None
    assert state["speaker_name"] == "A television"
    assert state["state"] == "unavailable"
    await unload(hass, other_entry)


async def test_adopted_session_on_non_music_assistant_speaker_gets_no_calls(
    hass: HomeAssistant, workout: Workout
) -> None:
    """An adopted session's Pause and Resume skip a speaker of another platform."""
    other_entry, tv_player = await async_setup_other_player(hass)
    music = {**MUSIC, "speaker": "media_player.tv"}
    started = workout.setup_time - timedelta(minutes=3)
    await workout.push(_view(music=music, started_at=started))

    await workout.push(_view(music=music, status="paused", started_at=started))
    await workout.push(_view(music=music, started_at=started))

    assert tv_player.calls == []
    await unload(hass, other_entry)


async def test_pause_during_start_reads_waiting_then_pauses(
    workout: Workout,
) -> None:
    """While the start is in flight the music is waiting; a Pause then goes out after the start."""
    started = workout.setup_time + timedelta(seconds=10)
    gate = asyncio.Event()
    workout.kitchen.gate = gate
    await workout.push(_view())
    await workout.push(_view(started_at=started), settle=False)
    await wait_for(workout.hass, lambda: "play_media" in _names(workout.kitchen))
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "waiting"

    await workout.push(_view(status="paused", started_at=started), settle=False)
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "waiting"
    assert _names(workout.kitchen) == ["volume_set", "play_media"]
    gate.set()
    await workout.hass.async_block_till_done()

    assert _names(workout.kitchen) == [*START_CALLS, "media_pause"]
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "paused"


async def test_new_session_is_followed_afresh(workout: Workout) -> None:
    """A session with another id after a started one waits for its own start, then starts again.

    The first session's end began a fade; the new start stops it and sets the level back first.
    """
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(started_at=started))
    assert _names(workout.kitchen) == START_CALLS

    await workout.push(_view(id=8))
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "waiting"
    assert _names(workout.kitchen) == START_CALLS
    await workout.push(_view(id=8, started_at=started + timedelta(minutes=30)))

    assert _names(workout.kitchen) == [*START_CALLS, "volume_set", *START_CALLS]


async def test_unload_stops_following_the_speaker(
    hass: HomeAssistant, workout: Workout
) -> None:
    """After unload, a speaker that comes back sends no update and gets no start."""
    workout.kitchen.set_available(False)
    await hass.async_block_till_done()
    await workout.push(_view(started_at=workout.setup_time + timedelta(seconds=10)))
    await unload(hass, workout.entry)
    updates: list[None] = []
    remove = async_dispatcher_connect(hass, SIGNAL_UPDATE, lambda: updates.append(None))

    workout.kitchen.set_available(True)
    await hass.async_block_till_done()

    assert updates == []
    assert workout.kitchen.calls == []
    remove()


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


async def _start_then_end(workout: Workout) -> int:
    """Start the music, then end the session; return the number of calls before the end."""
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(started_at=started))
    before = len(workout.kitchen.calls)
    await workout.push(_view(status="ended", started_at=started))
    return before


async def test_fade_steps_then_pause_then_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """The end lowers the volume in ten steps over 5 s, then pauses, then sets the starting level back."""
    before = await _start_then_end(workout)
    assert workout.kitchen.calls[before:] == []
    assert workout.music_state() is None

    for step in range(1, 11):
        await _tick(hass, freezer, 0.4)
        assert len(workout.kitchen.calls) == before + step - 1
        await _tick(hass, freezer, 0.1)
        assert len(workout.kitchen.calls) >= before + step

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        *["volume_set"] * 10,
        "media_pause",
        "volume_set",
    ]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS, START_LEVEL])
    speaker = hass.states.get("media_player.kitchen")
    assert speaker is not None
    assert speaker.state == MediaPlayerState.PAUSED
    assert speaker.attributes["volume_level"] == pytest.approx(START_LEVEL)
    await _tick(hass, freezer, 5)
    assert len(workout.kitchen.calls) == before + 12


async def test_fade_steps_keep_absolute_times(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A slow step doesn't push the next one back: each step runs at 0.5 s times its number."""
    before = await _start_then_end(workout)
    workout.kitchen.on_volume_set = lambda: freezer.tick(timedelta(seconds=0.3))

    await _tick(hass, freezer, 0.5)
    assert len(workout.kitchen.calls) == before + 1
    # The step's call took 0.3 s, so the clock is at 0.8 s; the second step is due at 1.0 s.
    await _tick(hass, freezer, 0.1)
    assert len(workout.kitchen.calls) == before + 1
    await _tick(hass, freezer, 0.1)

    assert _levels(workout.kitchen.calls[before:]) == pytest.approx(FADE_LEVELS[:2])


async def test_fade_on_other_speaker_runs_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A new session on another speaker starts there, and the kitchen's fade goes on to its end."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 1)
    living_room = workout.players["media_player.living_room"]
    music = {**MUSIC, "speaker": "media_player.living_room"}

    await workout.push(
        _view(id=8, music=music, started_at=workout.setup_time + timedelta(minutes=30))
    )
    for _ in range(8):
        await _tick(hass, freezer, 0.5)

    assert _names(living_room) == START_CALLS
    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade][-2:] == ["media_pause", "volume_set"]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS, START_LEVEL])


@pytest.mark.parametrize("speaker", ["media_player.garage", "media_player.kitchen"])
async def test_fade_without_volume_set_only_pauses(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    workout: Workout,
    speaker: str,
) -> None:
    """A speaker without VOLUME_SET (the garage), or without a volume level, is only paused."""
    player = workout.players[speaker]
    music = {**MUSIC, "speaker": speaker}
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(music=music, started_at=started))
    player.set_volume_level(None)
    before = len(player.calls)

    await workout.push(_view(status="ended", music=music, started_at=started))
    await _tick(hass, freezer, 6)

    assert _names(player)[before:] == ["media_pause"]


@pytest.mark.parametrize(
    "paused_state", [MediaPlayerState.PAUSED, MediaPlayerState.IDLE]
)
async def test_no_fade_when_not_playing(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    workout: Workout,
    paused_state: MediaPlayerState,
) -> None:
    """A workout that ends while paused gets no fade and no second pause, also when a pause reads idle."""
    workout.kitchen.paused_state = paused_state
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(started_at=started))
    await workout.push(_view(status="paused", started_at=started))

    await workout.push(_view(status="ended", started_at=started))
    await _tick(hass, freezer, 6)

    assert _names(workout.kitchen) == [*START_CALLS, "media_pause"]


async def test_fade_on_disappearance(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A running session whose view goes straight to none fades out."""
    started = workout.setup_time + timedelta(seconds=10)
    await workout.push(_view(started_at=started))
    before = len(workout.kitchen.calls)

    await workout.push(None)
    for _ in range(10):
        await _tick(hass, freezer, 0.5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade][-2:] == ["media_pause", "volume_set"]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS, START_LEVEL])


async def test_fade_cancelled_by_start_on_same_speaker(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A start on the fading speaker stops the fade, sets the starting level back, then starts."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 0.5)

    await workout.push(
        _view(
            id=8,
            music={**MUSIC, "volume": 50},
            started_at=workout.setup_time + timedelta(minutes=30),
        )
    )
    await _tick(hass, freezer, 5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        *["volume_set"] * 3,
        "volume_set",
        *START_CALLS,
    ]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS[:3], START_LEVEL, 0.5])
    state = workout.music_state()
    assert state is not None
    assert state["state"] == "playing"


async def test_fade_at_unload_pauses_then_restores(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """Unloading during a fade stops it: the speaker is paused, then gets its starting level back."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 0.5)

    await unload(hass, workout.entry)
    await _tick(hass, freezer, 5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        "volume_set",
        "volume_set",
        "media_pause",
        "volume_set",
    ]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS[:2], START_LEVEL])


async def test_fade_once_per_session(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """The ended view, a repeat of it, then no view: one fade."""
    started = workout.setup_time + timedelta(seconds=10)
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    await workout.push(_view(status="ended", started_at=started))
    await workout.push(None)

    await _tick(hass, freezer, 5)

    assert len(workout.kitchen.calls) == before + 12


async def test_failed_fade_step_goes_on(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A step whose call raises doesn't stop the fade: the steps, the pause and the restore still go out."""
    before = await _start_then_end(workout)
    workout.kitchen.fail = {"volume_set"}

    for _ in range(10):
        await _tick(hass, freezer, 0.5)

    assert _names(workout.kitchen)[before:] == [
        *["volume_set"] * 10,
        "media_pause",
        "volume_set",
    ]


async def test_fade_on_speaker_gone_unavailable_makes_no_calls(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A speaker that goes unavailable during the fade gets no more calls."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    workout.kitchen.set_available(False)

    for _ in range(9):
        await _tick(hass, freezer, 0.5)

    assert _levels(workout.kitchen.calls[before:]) == pytest.approx(FADE_LEVELS[:1])
    assert len(workout.kitchen.calls) == before + 1


async def _start_then_hold_first_step(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> tuple[int, asyncio.Event]:
    """End a started session and hold the fade's first step across the second one, which lands.

    Return the number of calls before the end, and the held step's event.
    """
    before = await _start_then_end(workout)
    held = asyncio.Event()
    workout.kitchen.hold["volume_set"] = held
    await _tick(hass, freezer, 0.5, settle=False)
    del workout.kitchen.hold["volume_set"]
    await _tick(hass, freezer, 0.5, settle=False)
    assert _levels(workout.kitchen.calls[before:]) == pytest.approx(FADE_LEVELS[1:2])
    return before, held


async def test_held_step_lands_before_restore_on_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A step still in flight at a start on the speaker lands before the restore, and the start after it."""
    before, held = await _start_then_hold_first_step(hass, freezer, workout)

    await workout.push(
        _view(
            id=8,
            music={**MUSIC, "volume": 50},
            started_at=workout.setup_time + timedelta(minutes=30),
        ),
        settle=False,
    )
    await _yield()
    assert len(workout.kitchen.calls) == before + 1
    held.set()
    await hass.async_block_till_done()
    await _tick(hass, freezer, 5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        "volume_set",
        "volume_set",
        "volume_set",
        *START_CALLS,
    ]
    assert _levels(fade) == pytest.approx(
        [FADE_LEVELS[1], FADE_LEVELS[0], START_LEVEL, 0.5]
    )


async def test_held_step_lands_before_restore_on_unload(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A step still in flight at unload lands before the pause and the restore."""
    before, held = await _start_then_hold_first_step(hass, freezer, workout)

    unloading = hass.async_create_task(unload(hass, workout.entry))
    await _yield()
    assert len(workout.kitchen.calls) == before + 1
    held.set()
    await unloading
    await _tick(hass, freezer, 5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        "volume_set",
        "volume_set",
        "media_pause",
        "volume_set",
    ]
    assert _levels(fade) == pytest.approx([FADE_LEVELS[1], FADE_LEVELS[0], START_LEVEL])


async def test_held_step_lands_before_last_step(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A slow ninth step lands before the last step's level, its pause and its restore."""
    before = await _start_then_end(workout)
    for _ in range(8):
        await _tick(hass, freezer, 0.5)
    held = asyncio.Event()
    workout.kitchen.hold["volume_set"] = held
    await _tick(hass, freezer, 0.5, settle=False)
    del workout.kitchen.hold["volume_set"]
    await _tick(hass, freezer, 0.5, settle=False)
    assert len(workout.kitchen.calls) == before + 8

    held.set()
    await hass.async_block_till_done()

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade][-2:] == ["media_pause", "volume_set"]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS, START_LEVEL])


async def test_start_during_last_step_comes_after_restore(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A start on the speaker during the last step's pause and restore waits for them."""
    before = await _start_then_end(workout)
    held = asyncio.Event()
    workout.kitchen.hold["media_pause"] = held
    for _ in range(9):
        await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 0.5, settle=False)

    await workout.push(
        _view(
            id=8,
            music={**MUSIC, "volume": 50},
            started_at=workout.setup_time + timedelta(minutes=30),
        ),
        settle=False,
    )
    await _yield()
    assert len(workout.kitchen.calls) == before + 10
    held.set()
    await hass.async_block_till_done()

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade][10:] == [
        "media_pause",
        "volume_set",
        *START_CALLS,
    ]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS, START_LEVEL, 0.5])


async def test_second_fade_on_fading_speaker_keeps_starting_level(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """An adopted session on a fading speaker that ends replaces the fade; the starting level stays."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 0.5)
    adopted = workout.setup_time - timedelta(minutes=3)

    await workout.push(_view(id=8, started_at=adopted))
    await workout.push(_view(id=8, status="ended", started_at=adopted))
    for _ in range(10):
        await _tick(hass, freezer, 0.5)
    await _tick(hass, freezer, 5)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == [
        *["volume_set"] * 12,
        "media_pause",
        "volume_set",
    ]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS[:2], *FADE_LEVELS, START_LEVEL])


async def test_start_while_last_step_waits_cancels_it(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """A start while the last step waits for a slow ninth one: the last step never runs, the restore does."""
    before = await _start_then_end(workout)
    for _ in range(8):
        await _tick(hass, freezer, 0.5)
    held = asyncio.Event()
    workout.kitchen.hold["volume_set"] = held
    await _tick(hass, freezer, 0.5, settle=False)
    del workout.kitchen.hold["volume_set"]
    await _tick(hass, freezer, 0.5, settle=False)

    await workout.push(
        _view(
            id=8,
            music={**MUSIC, "volume": 50},
            started_at=workout.setup_time + timedelta(minutes=30),
        ),
        settle=False,
    )
    await _yield()
    held.set()
    await hass.async_block_till_done()

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade][9:] == ["volume_set", *START_CALLS]
    assert _levels(fade) == pytest.approx([*FADE_LEVELS[:9], START_LEVEL, 0.5])


async def test_second_end_on_stopped_fading_speaker_restores(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, workout: Workout
) -> None:
    """An adopted session ends on a fading speaker someone paused: no new fade, the starting level comes back."""
    before = await _start_then_end(workout)
    await _tick(hass, freezer, 0.5)
    await hass.services.async_call(
        "media_player",
        "media_pause",
        {"entity_id": "media_player.kitchen"},
        blocking=True,
    )
    adopted = workout.setup_time - timedelta(minutes=3)

    await workout.push(_view(id=8, started_at=adopted))
    await workout.push(_view(id=8, status="ended", started_at=adopted))
    await _tick(hass, freezer, 6)

    fade = workout.kitchen.calls[before:]
    assert [name for name, _ in fade] == ["volume_set", "media_pause", "volume_set"]
    assert _levels(fade) == pytest.approx([FADE_LEVELS[0], START_LEVEL])
