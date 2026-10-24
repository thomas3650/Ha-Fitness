"""The fake Music Assistant's three players.

Their state really changes: `play_media` gives a player a queue and plays it, with the playlist's name as
`media_title`; next track moves on to "Track 2", "Track 3" and so on. As on a real Music Assistant, setting shuffle
does nothing while a player has no queue yet.
"""

from collections.abc import Mapping
from typing import Any

from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import DATA_PLAYERS, playlist_name

FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.SHUFFLE_SET
)
DEFAULT_VOLUME = 0.4

# (object id, name, whether it can set its volume)
PLAYERS = (
    ("fake_kitchen", "Kitchen speaker", True),
    ("fake_living_room", "Living room speaker", True),
    # No VOLUME_SET, to exercise the fade without volume.
    ("fake_garage", "Garage speaker", False),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Add the three players."""
    async_add_entities(FakePlayer(*player) for player in PLAYERS)


class FakePlayer(MediaPlayerEntity):
    """A Music Assistant player that only changes its own state."""

    _attr_should_poll = False
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, object_id: str, name: str, volume: bool) -> None:
        """Set the ids, the name and the features."""
        # Set explicitly: a name-derived id would be `media_player.kitchen_speaker`.
        self.entity_id = f"media_player.{object_id}"
        # A unique id puts the player in the entity registry, so `config_entry_id()` finds it.
        self._attr_unique_id = object_id
        self._attr_name = name
        self._attr_supported_features = FEATURES
        if volume:
            self._attr_supported_features |= MediaPlayerEntityFeature.VOLUME_SET
            self._attr_volume_level = DEFAULT_VOLUME
        self._attr_state = MediaPlayerState.IDLE
        self._attr_shuffle = False
        self._has_queue = False
        self._track = 1

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return `mass_player_type`; HA leaves it out while the player is unavailable."""
        return {"mass_player_type": "player"}

    async def async_added_to_hass(self) -> None:
        """Register the player under its entity id, for `fake_set_available`; a renamed entity is added again."""
        self.hass.data[DATA_PLAYERS][self.entity_id] = self

    async def async_will_remove_from_hass(self) -> None:
        """Forget the player, at unload or before a rename."""
        self.hass.data[DATA_PLAYERS].pop(self.entity_id, None)

    def set_available(self, available: bool) -> None:
        """Make the player available or unavailable (`music_assistant.fake_set_available`)."""
        self._attr_available = available
        self.async_write_ha_state()

    async def _async_handle_play_media(
        self,
        media_id: list[str],
        media_type: str | None = None,
        enqueue: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        radio_mode: bool | None = None,
        username: str | None = None,
    ) -> None:
        """Play the first of `media_id` from the start (`music_assistant.play_media`); fail on an unknown URI."""
        name = playlist_name(media_id[0])
        if name is None:
            raise HomeAssistantError(f"Media item {media_id[0]} not found")
        self._has_queue = True
        self._track = 1
        self._attr_media_title = name
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_play_media(
        self, media_type: MediaType | str, media_id: str, **kwargs: Any
    ) -> None:
        """Play media through `media_player.play_media`, as through `music_assistant.play_media`."""
        await self._async_handle_play_media([media_id], str(media_type))

    async def async_media_play(self) -> None:
        """Play again; a player with no queue stays idle."""
        if self._has_queue:
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Pause."""
        if self._has_queue:
            self._attr_state = MediaPlayerState.PAUSED
            self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Go on to the next track: "Track 2", "Track 3" …."""
        if self._has_queue:
            self._track += 1
            self._attr_media_title = f"Track {self._track}"
            self.async_write_ha_state()

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume (only the players with `VOLUME_SET`)."""
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set shuffle; like a real Music Assistant, do nothing while there is no queue."""
        if not self._has_queue:
            return
        self._attr_shuffle = shuffle
        self.async_write_ha_state()
