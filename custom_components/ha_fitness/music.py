"""Music during a workout: Music Assistant's speakers (the music spec §5).

This module never imports `websocket_api`; the commands import from here.
"""

import asyncio
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player.const import (
    ATTR_MEDIA_SHUFFLE,
    ATTR_MEDIA_VOLUME_LEVEL,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
    MediaPlayerEntityFeature,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_SUPPORTED_FEATURES,
    SERVICE_MEDIA_NEXT_TRACK,
    SERVICE_MEDIA_PAUSE,
    SERVICE_MEDIA_PLAY,
    SERVICE_SHUFFLE_SET,
    SERVICE_VOLUME_SET,
    STATE_PLAYING,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    CALLBACK_TYPE,
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.entity import entity_sources
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util
import probatio

from .const import DOMAIN, SIGNAL_UPDATE

if TYPE_CHECKING:
    from .coordinator import FitnessCoordinator

_LOGGER = logging.getLogger(__name__)

MUSIC_ASSISTANT = "music_assistant"
MEDIA_PLAYER_PREFIX = "media_player."
_NOT_AVAILABLE = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN})
# What a failed service call raises: HA's errors, and a schema error for invalid data.
_CALL_ERRORS = (HomeAssistantError, probatio.Invalid)

# The controller's states per session (the music spec §5.1).
WAITING = "waiting"
STARTED = "started"
FAILED = "failed"

# The fade (the music spec §5.3): ten steps, one every half second, so 5 s.
FADE_STEPS = 10
FADE_STEP_SECONDS = 0.5

# The session statuses of an active session; the others are finished.
_ACTIVE = frozenset({"running", "paused"})

# The music commands of the cards (the music spec §5.5) and the speaker service each calls.
_COMMAND_SERVICES = {
    "pause": SERVICE_MEDIA_PAUSE,
    "play": SERVICE_MEDIA_PLAY,
    "next": SERVICE_MEDIA_NEXT_TRACK,
}


class MusicNotFound(Exception):
    """There is no active session with music, or its music can't be played yet."""


class MusicUnavailable(Exception):
    """The speaker is unavailable, or the call to it failed."""


def music_speakers(hass: HomeAssistant) -> list[dict[str, Any]]:
    """Return Music Assistant's speakers as `{entity_id, name, available}`, sorted by name.

    The rule is the add-on's (the music spec §3 and §5.5): the `media_player` entities in `entity_sources` of the
    `music_assistant` platform. So these are the loaded players, unavailable ones included. `available` is false
    for `unavailable` and `unknown`.
    """
    speakers: list[dict[str, Any]] = []
    for entity_id, info in entity_sources(hass).items():
        if not entity_id.startswith(MEDIA_PLAYER_PREFIX):
            continue
        if info["domain"] != MUSIC_ASSISTANT:
            continue
        # As the add-on's template: no state reads as unknown, and no friendly name as the entity id.
        state = hass.states.get(entity_id)
        name = state.attributes.get("friendly_name") if state is not None else None
        speakers.append(
            {
                "entity_id": entity_id,
                "name": name or entity_id,
                "available": state is not None and state.state not in _NOT_AVAILABLE,
            }
        )
    return sorted(
        speakers, key=lambda speaker: (speaker["name"].casefold(), speaker["entity_id"])
    )


def _parse_time(value: object) -> datetime | None:
    """Return an ISO time as a datetime, or None for anything else."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_music_assistant_player(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether the entity is a media player of the `music_assistant` platform (as `music_speakers`)."""
    info = entity_sources(hass).get(entity_id)
    return (
        entity_id.startswith(MEDIA_PLAYER_PREFIX)
        and info is not None
        and info["domain"] == MUSIC_ASSISTANT
    )


def _is_available(state: State | None) -> bool:
    return state is not None and state.state not in _NOT_AVAILABLE


def _can_play(hass: HomeAssistant, entity_id: str) -> bool:
    """Return whether the speaker gets calls: it is available and a Music Assistant player."""
    return _is_available(hass.states.get(entity_id)) and _is_music_assistant_player(
        hass, entity_id
    )


@dataclass(slots=True)
class _Followed:
    """The session the controller follows: its id, its frozen music, its last status and the controller's state."""

    session_id: Any
    music: dict[str, Any]
    status: str
    started_at: datetime | None
    state: str
    # True while a start is queued or running: the music state reads `waiting` until it ends.
    starting: bool = False
    remove_speaker_listener: CALLBACK_TYPE | None = None

    @property
    def speaker(self) -> str:
        """Return the plan's speaker: every call goes to it."""
        speaker: str = self.music["speaker"]
        return speaker


@dataclass(slots=True)
class _Fade:
    """A running fade on a speaker: its starting level, its step timers and the steps in flight.

    It stays in the controller's fades until its last step has set the starting level back (`restored`).
    """

    speaker: str
    level: float
    cancel_timers: list[CALLBACK_TYPE] = field(default_factory=list)
    tasks: set[asyncio.Task[None]] = field(default_factory=set)
    cancelled: bool = False
    restored: bool = False


class MusicController:
    """Play, pause and resume the session's music on its speaker (the music spec §5.1 and §5.2).

    It takes the session views from the coordinator's listener. Per session it is `waiting`, `started` or
    `failed`. Its decisions are made in the listener, in the order of the views; the speaker calls run one after
    another, so a Pause during the start goes out after it. Each change of the music state, a speaker's state
    included, is sent on the dispatcher. When a started session ends, its music fades out (§5.3).
    """

    def __init__(self, hass: HomeAssistant, coordinator: FitnessCoordinator) -> None:
        """Keep the coordinator; `async_start` begins following its session."""
        self.hass = hass
        self.coordinator = coordinator
        self._started: datetime | None = None
        self._followed: _Followed | None = None
        self._remove_listener: CALLBACK_TYPE | None = None
        self._lock = asyncio.Lock()
        # The running fades by speaker: at most one per speaker.
        self._fades: dict[str, _Fade] = {}
        self._stopped = False

    async def async_start(self) -> None:
        """Note the controller's own start time and follow the session's views."""
        self._started = dt_util.utcnow()
        self._remove_listener = self.coordinator.async_add_listener(self._handle_update)
        self._handle_update()

    async def async_stop(self) -> None:
        """Stop following the session and its speaker; pause each fading speaker, then set its level back."""
        self._stopped = True
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        self._forget()
        async with self._lock:
            for fade in list(self._fades.values()):
                await self._async_cancel_fade(fade)
                if not fade.restored:
                    await self._async_fade_call(fade.speaker, SERVICE_MEDIA_PAUSE)
                    await self._async_restore(fade)

    @callback
    def music_state(self) -> dict[str, Any] | None:
        """Return the music state the session subscription sends (the music spec §5.4), or None."""
        followed = self._followed
        if (
            followed is None
            or not self.coordinator.music_supported
            or not self.hass.config_entries.async_loaded_entries(MUSIC_ASSISTANT)
        ):
            return None
        speaker = self.hass.states.get(followed.speaker)
        name = speaker.attributes.get("friendly_name") if speaker is not None else None
        if followed.state == FAILED or not _can_play(self.hass, followed.speaker):
            state = "unavailable"
        elif followed.state == WAITING or followed.starting:
            state = "waiting"
        elif speaker is not None and speaker.state == STATE_PLAYING:
            state = "playing"
        else:
            state = "paused"
        return {
            "playlist_name": followed.music.get("playlist_name")
            or followed.music["playlist"],
            "speaker": followed.speaker,
            "speaker_name": name or followed.speaker,
            "state": state,
        }

    async def async_command(self, action: str) -> None:
        """Run a card's music command on the session's speaker (the music spec §5.5).

        It doesn't change the workout. It raises `MusicNotFound` without an active session with music, and
        `MusicUnavailable` when the speaker is unavailable or the call fails.
        """
        service = _COMMAND_SERVICES[action]
        followed = self._followed
        if followed is None or not self.coordinator.music_supported:
            raise MusicNotFound
        if action == "play" and followed.state != STARTED:
            if followed.started_at is None:
                # The countdown: the music starts when it ends.
                raise MusicNotFound
            followed.state = STARTED
            followed.starting = True
            async with self._lock:
                if self._followed is not followed:
                    # The session ended while the command waited.
                    raise MusicNotFound
                if not await self._async_start_music(followed):
                    raise MusicUnavailable
            return
        async with self._lock:
            if self._followed is not followed:
                raise MusicNotFound
            if not _can_play(self.hass, followed.speaker):
                raise MusicUnavailable
            try:
                await self._async_call(MEDIA_PLAYER_DOMAIN, service, followed.speaker)
            except _CALL_ERRORS as err:
                _LOGGER.warning("The music command %s failed: %s", action, err)
                raise MusicUnavailable from err

    @callback
    def _handle_update(self) -> None:
        """Follow the coordinator's session view: the event table of the music spec §5.1."""
        view = self.coordinator.session if self.coordinator.music_supported else None
        followed = self._followed
        if followed is not None and (
            view is None
            or view.get("id") != followed.session_id
            or view.get("status") not in _ACTIVE
        ):
            # The session completed, ended or disappeared: once forgotten, it can't fade twice.
            self._forget()
            if followed.state == STARTED:
                speaker = followed.speaker
                self._queue(lambda: self._async_begin_fade(speaker))
            followed = None
        if view is None or view.get("status") not in _ACTIVE or not view.get("music"):
            return
        status: str = view["status"]
        started_at = _parse_time(view.get("started_at"))
        if followed is None:
            # First seen. A session started before the controller (HA restarted, the entry reloaded) is
            # adopted: the music may be playing already, and a start would restart the playlist.
            adopted = (
                started_at is not None
                and self._started is not None
                and started_at < self._started
            )
            followed = self._follow(view, STARTED if adopted else WAITING)
        previous = followed.status
        followed.status = status
        followed.started_at = started_at
        if status != "running":
            if previous == "running" and followed.state == STARTED:
                self._queue(
                    lambda: self._async_speaker_call(followed, SERVICE_MEDIA_PAUSE)
                )
            return
        if started_at is not None and followed.state == WAITING:
            # The countdown's end, "Start nu", or the Resume after "Start nu" while paused.
            self._queue_start(followed)
        elif previous == "paused" and followed.state == STARTED:
            self._queue(lambda: self._async_speaker_call(followed, SERVICE_MEDIA_PLAY))
        elif previous == "paused" and followed.state == FAILED:
            self._queue_start(followed)

    @callback
    def _follow(self, view: dict[str, Any], state: str) -> _Followed:
        """Start following a session and its speaker's state."""
        followed = _Followed(
            session_id=view.get("id"),
            music=view["music"],
            status=view["status"],
            started_at=None,
            state=state,
        )
        followed.remove_speaker_listener = async_track_state_change_event(
            self.hass, followed.speaker, self._handle_speaker_change
        )
        self._followed = followed
        self._changed()
        return followed

    @callback
    def _forget(self) -> None:
        """Stop following the session."""
        followed = self._followed
        if followed is None:
            return
        self._followed = None
        if followed.remove_speaker_listener is not None:
            followed.remove_speaker_listener()
        self._changed()

    @callback
    def _handle_speaker_change(self, event: Event[EventStateChangedData]) -> None:
        """Send the change; retry a failed start when the speaker comes back while the workout runs."""
        followed = self._followed
        if (
            followed is not None
            and followed.state == FAILED
            and followed.status == "running"
            and not _is_available(event.data["old_state"])
            and _is_available(event.data["new_state"])
        ):
            self._queue_start(followed)
        self._changed()

    @callback
    def _queue_start(self, followed: _Followed) -> None:
        """Leave `waiting` or `failed` now, so a repeated view doesn't start twice; the start sets `failed`."""
        followed.state = STARTED
        followed.starting = True
        self._queue(lambda: self._async_locked_start(followed))

    @callback
    def _queue(self, job: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Run a speaker job after the ones before it; the entry's unload waits for it."""
        self.coordinator.entry.async_create_task(
            self.hass, self._async_in_turn(job), f"{DOMAIN} music"
        )

    async def _async_in_turn(
        self, job: Callable[[], Coroutine[Any, Any, None]]
    ) -> None:
        """Make the job's coroutine only once its turn comes, so a cancelled wait leaves none behind."""
        async with self._lock:
            await job()

    async def _async_locked_start(self, followed: _Followed) -> None:
        if self._followed is followed and followed.state == STARTED:
            await self._async_start_music(followed)
        else:
            followed.starting = False

    async def _async_start_music(self, followed: _Followed) -> bool:
        """The start (the music spec §5.2), under the lock; return whether it succeeded, else set `failed`."""
        try:
            return await self._async_try_start(followed)
        finally:
            followed.starting = False
            self._changed()

    async def _async_try_start(self, followed: _Followed) -> bool:
        speaker = followed.speaker
        if (fade := self._fades.get(speaker)) is not None:
            # A start on a fading speaker: stop the fade and set its level back first.
            await self._async_cancel_fade(fade)
            if not fade.restored:
                await self._async_restore(fade)
        state = self.hass.states.get(speaker)
        if not _can_play(self.hass, speaker):
            _LOGGER.warning("The speaker %s can't play the workout's music", speaker)
            return self._fail(followed)
        assert state is not None
        music = followed.music
        try:
            volume = music.get("volume")
            features = state.attributes.get(ATTR_SUPPORTED_FEATURES, 0)
            if volume is not None and features & MediaPlayerEntityFeature.VOLUME_SET:
                await self._async_call(
                    MEDIA_PLAYER_DOMAIN,
                    SERVICE_VOLUME_SET,
                    speaker,
                    {ATTR_MEDIA_VOLUME_LEVEL: volume / 100},
                )
            await self._async_call(
                MUSIC_ASSISTANT,
                "play_media",
                speaker,
                {
                    "media_id": music["playlist"],
                    "media_type": "playlist",
                    "enqueue": "replace",
                },
            )
            # After play_media: replace makes a new queue, and shuffle needs one.
            await self._async_call(
                MEDIA_PLAYER_DOMAIN,
                SERVICE_SHUFFLE_SET,
                speaker,
                {ATTR_MEDIA_SHUFFLE: bool(music.get("shuffle"))},
            )
        except _CALL_ERRORS as err:
            _LOGGER.warning("The workout's music didn't start on %s: %s", speaker, err)
            return self._fail(followed)
        return True

    @callback
    def _fail(self, followed: _Followed) -> bool:
        followed.state = FAILED
        self._changed()
        return False

    async def _async_speaker_call(self, followed: _Followed, service: str) -> None:
        """Pause or play the followed session's music after a start; a failure leaves it `started`."""
        if self._followed is not followed or followed.state != STARTED:
            return
        if not _can_play(self.hass, followed.speaker):
            _LOGGER.warning(
                "The speaker %s can't take the music's %s", followed.speaker, service
            )
            return
        try:
            await self._async_call(MEDIA_PLAYER_DOMAIN, service, followed.speaker)
        except _CALL_ERRORS as err:
            _LOGGER.warning(
                "The music's %s on %s failed: %s", service, followed.speaker, err
            )

    async def _async_begin_fade(self, speaker: str) -> None:
        """The fade (the music spec §5.3), under the lock: schedule its ten steps, or only pause.

        It runs after the jobs before it, so a Pause queued just before the end has landed: a speaker that
        isn't playing then gets nothing. A fade still running on the speaker (an adopted session's end, say)
        is replaced, and its starting level kept: the speaker's level is part way down.
        """
        previous = self._fades.get(speaker)
        if previous is not None:
            await self._async_cancel_fade(previous)
        state = self.hass.states.get(speaker)
        playing = (
            _can_play(self.hass, speaker)
            and state is not None
            and state.state == STATE_PLAYING
        )
        level = previous.level if previous is not None else None
        if state is not None and level is None:
            level = state.attributes.get(ATTR_MEDIA_VOLUME_LEVEL)
        features = state.attributes.get(ATTR_SUPPORTED_FEATURES, 0) if state else 0
        if (
            not playing
            or self._stopped
            or level is None
            or not features & MediaPlayerEntityFeature.VOLUME_SET
        ):
            if playing:
                # No volume to lower, or the entry is unloading: only the pause.
                await self._async_fade_call(speaker, SERVICE_MEDIA_PAUSE)
            if previous is not None and not previous.restored:
                await self._async_restore(previous)
            return
        fade = _Fade(speaker=speaker, level=float(level))
        self._fades[speaker] = fade
        # Every step is scheduled now, from the same moment, so a slow call doesn't push the next back.
        fade.cancel_timers = [
            async_call_later(
                self.hass,
                step * FADE_STEP_SECONDS,
                partial(self._handle_fade_step, fade, step),
            )
            for step in range(1, FADE_STEPS + 1)
        ]

    @callback
    def _handle_fade_step(self, fade: _Fade, step: int, _now: datetime) -> None:
        """Run a step when its time comes (a cancelled fade has no timers left); the entry's unload waits for it."""
        task = self.coordinator.entry.async_create_task(
            self.hass, self._async_fade_step(fade, step), f"{DOMAIN} music fade"
        )
        fade.tasks.add(task)
        task.add_done_callback(fade.tasks.discard)

    async def _async_fade_step(self, fade: _Fade, step: int) -> None:
        """Set the step's level; the last step (level 0) then pauses and sets the starting level back.

        The last step first waits for the earlier steps still in flight, so none of them lands after it.
        """
        if step == FADE_STEPS:
            await self._async_wait_for_steps(fade)
            if fade.cancelled:
                return
        await self._async_fade_call(
            fade.speaker,
            SERVICE_VOLUME_SET,
            {ATTR_MEDIA_VOLUME_LEVEL: fade.level * (FADE_STEPS - step) / FADE_STEPS},
        )
        if step < FADE_STEPS or fade.cancelled:
            return
        await self._async_fade_call(fade.speaker, SERVICE_MEDIA_PAUSE)
        await self._async_restore(fade)
        if self._fades.get(fade.speaker) is fade:
            del self._fades[fade.speaker]

    async def _async_cancel_fade(self, fade: _Fade) -> None:
        """Stop a fade: no later step starts, and every step in flight has finished."""
        fade.cancelled = True
        for cancel in fade.cancel_timers:
            cancel()
        await self._async_wait_for_steps(fade)
        if self._fades.get(fade.speaker) is fade:
            del self._fades[fade.speaker]

    @staticmethod
    async def _async_wait_for_steps(fade: _Fade) -> None:
        """Wait for the fade's steps in flight, other than the current task."""
        steps = fade.tasks - {asyncio.current_task()}
        if steps:
            # asyncio.wait doesn't raise if a step's task was cancelled at shutdown.
            await asyncio.wait(steps)

    async def _async_restore(self, fade: _Fade) -> None:
        """Set the fade's starting level back, so the next playback isn't silent."""
        await self._async_fade_call(
            fade.speaker, SERVICE_VOLUME_SET, {ATTR_MEDIA_VOLUME_LEVEL: fade.level}
        )
        fade.restored = True

    async def _async_fade_call(
        self, speaker: str, service: str, data: dict[str, Any] | None = None
    ) -> None:
        """Call the speaker for the fade; a failure, or a speaker that can't play, is a warning."""
        if not _can_play(self.hass, speaker):
            _LOGGER.warning("The speaker %s can't take the fade's %s", speaker, service)
            return
        try:
            await self._async_call(MEDIA_PLAYER_DOMAIN, service, speaker, data)
        except _CALL_ERRORS as err:
            _LOGGER.warning("The fade's %s on %s failed: %s", service, speaker, err)

    async def _async_call(
        self,
        domain: str,
        service: str,
        entity_id: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        await self.hass.services.async_call(
            domain,
            service,
            {ATTR_ENTITY_ID: entity_id, **(data or {})},
            blocking=True,
        )

    @callback
    def _changed(self) -> None:
        """Tell the subscriptions the music state may have changed."""
        async_dispatcher_send(self.hass, SIGNAL_UPDATE)
