"""A mock `music_assistant` platform for the tests (music spec §7, "Two fakes").

It is separate from the dev loops' fake in `scripts/dev/fake_music_assistant/`, but behaves like it, and so like
HA core's Music Assistant in what HA Fitness uses: `media_player` entities on the `music_assistant` platform, the
`music_assistant.play_media` entity service, and one button entity, as the real integration also makes entities
of other domains. Each player records the service calls it gets and really changes its state.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.components.media_player import MediaPlayerEntity
from homeassistant.components.media_player.const import (
    ATTR_MEDIA_ENQUEUE,
    MediaPlayerEntityFeature,
    MediaPlayerState,
    MediaType,
)
from homeassistant.config_entries import ConfigEntry, ConfigFlow
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv, entity_platform
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
import probatio
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    MockModule,
    MockPlatform,
    mock_config_flow,
    mock_integration,
    mock_platform,
)

DOMAIN = "music_assistant"
TITLE = "Music Assistant"
PLATFORMS = [Platform.MEDIA_PLAYER, Platform.BUTTON]

FEATURES = (
    MediaPlayerEntityFeature.PLAY_MEDIA
    | MediaPlayerEntityFeature.PAUSE
    | MediaPlayerEntityFeature.PLAY
    | MediaPlayerEntityFeature.NEXT_TRACK
    | MediaPlayerEntityFeature.SHUFFLE_SET
)
DEFAULT_VOLUME = 0.4

# The string values of Music Assistant's enums, as core's services.yaml lists them.
PLAY_MEDIA_TYPES = [
    "artist",
    "album",
    "audiobook",
    "folder",
    "playlist",
    "podcast",
    "track",
    "radio",
]
QUEUE_OPTIONS = ["play", "replace", "next", "replace_next", "add"]


@dataclass(frozen=True, slots=True)
class Player:
    """A player to set up: `media_player.<object_id>`, its name, and whether it can set its volume."""

    object_id: str
    name: str
    volume: bool = True


# Named so that their order by name differs from their order by entity id.
DEFAULT_PLAYERS = (
    Player("kitchen", "Kitchen speaker"),
    Player("living_room", "Living room speaker"),
    Player("garage", "Garage speaker", volume=False),
)


class MockPlayer(MediaPlayerEntity):
    """A Music Assistant player that records its calls and changes only its own state.

    `calls` holds each call as `(name, arguments)`: `play_media`, `media_play`, `media_pause`,
    `media_next_track`, `volume_set` and `shuffle_set`. As on a real Music Assistant, pause, play, next and
    shuffle do nothing while the player has no queue; `play_media` gives it one and plays it. A call whose name
    is in `fail` is recorded, then raises `HomeAssistantError` and changes nothing.
    """

    _attr_should_poll = False
    _attr_media_content_type = MediaType.MUSIC

    def __init__(self, player: Player) -> None:
        """Set the ids, the name and the features."""
        self.entity_id = f"media_player.{player.object_id}"
        self._attr_unique_id = f"mass_{player.object_id}"
        self._attr_name = player.name
        self._attr_supported_features = FEATURES
        if player.volume:
            self._attr_supported_features |= MediaPlayerEntityFeature.VOLUME_SET
            self._attr_volume_level = DEFAULT_VOLUME
        self._attr_state = MediaPlayerState.IDLE
        self._attr_shuffle = False
        self.has_queue = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.fail: set[str] = set()

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return `mass_player_type`; HA leaves it out while the player is unavailable."""
        return {"mass_player_type": "player"}

    def _record(self, name: str, arguments: dict[str, Any]) -> None:
        """Record a call; raise when the call is set to fail."""
        self.calls.append((name, arguments))
        if name in self.fail:
            raise HomeAssistantError(f"{name} failed on {self.entity_id}")

    def set_available(self, available: bool) -> None:
        """Make the player available or unavailable."""
        self._attr_available = available
        self.async_write_ha_state()

    async def async_handle_play_media(
        self,
        media_id: list[str],
        media_type: str | None = None,
        enqueue: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        radio_mode: bool | None = None,
        username: str | None = None,
    ) -> None:
        """Play the first of `media_id` from the start (`music_assistant.play_media`)."""
        self._record(
            "play_media",
            {"media_id": media_id, "media_type": media_type, "enqueue": enqueue},
        )
        self.has_queue = True
        self._attr_media_title = media_id[0]
        self._attr_state = MediaPlayerState.PLAYING
        self.async_write_ha_state()

    async def async_media_play(self) -> None:
        """Play again; a player with no queue stays idle."""
        self._record("media_play", {})
        if self.has_queue:
            self._attr_state = MediaPlayerState.PLAYING
            self.async_write_ha_state()

    async def async_media_pause(self) -> None:
        """Pause; a player with no queue stays idle."""
        self._record("media_pause", {})
        if self.has_queue:
            self._attr_state = MediaPlayerState.PAUSED
            self.async_write_ha_state()

    async def async_media_next_track(self) -> None:
        """Go on to the next track."""
        self._record("media_next_track", {})

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the volume (only the players with `VOLUME_SET`)."""
        self._record("volume_set", {"volume_level": volume})
        self._attr_volume_level = volume
        self.async_write_ha_state()

    async def async_set_shuffle(self, shuffle: bool) -> None:
        """Set shuffle; like a real Music Assistant, do nothing while there is no queue."""
        self._record("shuffle_set", {"shuffle": shuffle})
        if not self.has_queue:
            return
        self._attr_shuffle = shuffle
        self.async_write_ha_state()


class _MockFlow(ConfigFlow):
    """A config flow for a mock entry: its setup asks for the flow's version."""

    VERSION = 1


class MockFavoriteButton(ButtonEntity):
    """A button on the `music_assistant` platform, as the real integration makes: not a speaker."""

    _attr_should_poll = False

    def __init__(self) -> None:
        """Set the ids and the name."""
        self.entity_id = "button.kitchen_favorite"
        self._attr_unique_id = "mass_kitchen_favorite"
        self._attr_name = "Kitchen favourite"

    async def async_press(self) -> None:
        """Do nothing."""


async def async_setup_music_assistant(
    hass: HomeAssistant, players: tuple[Player, ...] = DEFAULT_PLAYERS
) -> tuple[MockConfigEntry, dict[str, MockPlayer]]:
    """Set up a loaded mock Music Assistant with `players`; return its entry and the players by entity id.

    Unload the entry at the end of the test, so no entity is left behind.
    """
    entities = {
        f"media_player.{player.object_id}": MockPlayer(player) for player in players
    }

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        return True

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    async def async_setup_media_players(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        # An entity service of the platform, as core's: it only reaches this platform's players.
        entity_platform.async_get_current_platform().async_register_entity_service(
            "play_media",
            {
                probatio.Required("media_id"): probatio.All(
                    probatio.EnsureList(), [cv.string]
                ),
                probatio.Optional("media_type"): probatio.In(PLAY_MEDIA_TYPES),
                probatio.Optional(ATTR_MEDIA_ENQUEUE): probatio.In(QUEUE_OPTIONS),
                probatio.Optional("artist"): cv.string,
                probatio.Optional("album"): cv.string,
                probatio.Optional("radio_mode"): probatio.Coerce(bool),
                probatio.Optional("username"): cv.string,
            },
            "async_handle_play_media",
        )
        async_add_entities(list(entities.values()))

    async def async_setup_buttons(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        async_add_entities([MockFavoriteButton()])

    mock_integration(
        hass,
        MockModule(
            DOMAIN,
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )
    mock_platform(
        hass,
        f"{DOMAIN}.media_player",
        MockPlatform(async_setup_entry=async_setup_media_players),
    )
    mock_platform(
        hass, f"{DOMAIN}.button", MockPlatform(async_setup_entry=async_setup_buttons)
    )
    # A config entry's setup imports the integration's config flow; a Mock stands in.
    mock_platform(hass, f"{DOMAIN}.config_flow")
    entry = MockConfigEntry(domain=DOMAIN, title=TITLE)
    await _async_set_up_entry(hass, entry)
    return entry, entities


async def async_setup_other_player(hass: HomeAssistant) -> MockConfigEntry:
    """Set up a media player of another platform (`other_audio`): never a Music Assistant speaker."""

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        await hass.config_entries.async_forward_entry_setups(
            entry, [Platform.MEDIA_PLAYER]
        )
        return True

    async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        return await hass.config_entries.async_unload_platforms(
            entry, [Platform.MEDIA_PLAYER]
        )

    async def async_setup_media_players(
        hass: HomeAssistant,
        entry: ConfigEntry,
        async_add_entities: AddConfigEntryEntitiesCallback,
    ) -> None:
        async_add_entities([MockPlayer(Player("tv", "A television"))])

    mock_integration(
        hass,
        MockModule(
            "other_audio",
            async_setup_entry=async_setup_entry,
            async_unload_entry=async_unload_entry,
        ),
    )
    mock_platform(
        hass,
        "other_audio.media_player",
        MockPlatform(async_setup_entry=async_setup_media_players),
    )
    mock_platform(hass, "other_audio.config_flow")
    entry = MockConfigEntry(domain="other_audio", title="Other audio")
    await _async_set_up_entry(hass, entry)
    return entry


async def _async_set_up_entry(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Add a mock integration's entry and set it up."""
    entry.add_to_hass(hass)
    with mock_config_flow(entry.domain, _MockFlow):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
