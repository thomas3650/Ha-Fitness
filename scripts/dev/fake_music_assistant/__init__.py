"""A fake Music Assistant for the dev loops only (D55); never shipped.

It copies the surface of HA core's `music_assistant` integration that HA Fitness uses: three media players, the
`play_media` entity service and the `get_library` service. `fake_set_available` makes a player unavailable, or
available again. It imports nothing from core's integration or from Music Assistant's packages, so it runs on any
Home Assistant.
"""

from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player.const import (
    ATTR_MEDIA_ENQUEUE,
    DOMAIN as MEDIA_PLAYER_DOMAIN,
)
from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import ATTR_CONFIG_ENTRY_ID, ATTR_ENTITY_ID, Platform
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.typing import ConfigType
from homeassistant.util.hass_dict import HassKey
import probatio

if TYPE_CHECKING:
    from .media_player import FakePlayer

DOMAIN = "music_assistant"
TITLE = "Fake Music Assistant"
PLATFORMS = [Platform.MEDIA_PLAYER]
# The players by entity id, for `fake_set_available`.
DATA_PLAYERS: HassKey[dict[str, FakePlayer]] = HassKey(DOMAIN)

# The library: four playlists, as (uri, name).
PLAYLISTS = (
    ("library://playlist/1", "Workout Mix"),
    ("library://playlist/2", "Cardio Beats"),
    ("library://playlist/3", "Calm Stretch"),
    ("library://playlist/4", "Rock Classics"),
)

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
LIBRARY_MEDIA_TYPES = [
    "artist",
    "album",
    "audiobook",
    "playlist",
    "podcast",
    "track",
    "radio",
]
QUEUE_OPTIONS = ["play", "replace", "next", "replace_next", "add"]

DEFAULT_LIMIT = 25
DEFAULT_OFFSET = 0
DEFAULT_ORDER_BY = "name"

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register the services, as core's integration does in its setup."""
    hass.data[DATA_PLAYERS] = {}
    hass.services.async_register(
        DOMAIN,
        "get_library",
        _handle_get_library,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_CONFIG_ENTRY_ID): str,
                probatio.Required("media_type"): probatio.In(LIBRARY_MEDIA_TYPES),
                probatio.Optional("favorite"): cv.boolean,
                probatio.Optional("search"): cv.string,
                probatio.Optional("limit"): cv.positive_int,
                probatio.Optional("offset"): int,
                probatio.Optional("order_by"): cv.string,
                probatio.Optional("album_type"): list,
                probatio.Optional("album_artists_only"): cv.boolean,
                probatio.Optional("username"): cv.string,
            }
        ),
        supports_response=SupportsResponse.ONLY,
    )
    service.async_register_platform_entity_service(
        hass,
        DOMAIN,
        "play_media",
        entity_domain=MEDIA_PLAYER_DOMAIN,
        schema={
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
        func="_async_handle_play_media",
    )
    # A plain service, not an entity service: HA skips unavailable entities in entity services, so one couldn't
    # make a player available again.
    hass.services.async_register(
        DOMAIN,
        "fake_set_available",
        _handle_set_available,
        schema=probatio.Schema(
            {
                probatio.Required(ATTR_ENTITY_ID): cv.entity_id,
                probatio.Required("available"): cv.boolean,
            }
        ),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up the three players."""
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the players."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


def playlist_name(uri: str) -> str | None:
    """Return the name of the library's playlist with `uri`, or None."""
    return next((name for item_uri, name in PLAYLISTS if item_uri == uri), None)


def _library_item(uri: str, name: str) -> dict[str, Any]:
    """Return a playlist as core's `get_library` answers an item."""
    return {
        "media_type": "playlist",
        "uri": uri,
        "name": name,
        "version": "",
        "image": None,
        "favorite": False,
        "explicit": False,
    }


async def _handle_get_library(call: ServiceCall) -> ServiceResponse:
    """Answer the library's playlists, filtered by `search` (case-insensitive) and paged by `offset` and `limit`."""
    entry = call.hass.config_entries.async_get_entry(call.data[ATTR_CONFIG_ENTRY_ID])
    if (
        entry is None
        or entry.domain != DOMAIN
        or entry.state is not ConfigEntryState.LOADED
    ):
        raise ServiceValidationError("The Music Assistant entry isn't loaded")
    media_type = call.data["media_type"]
    limit = call.data.get("limit", DEFAULT_LIMIT)
    offset = call.data.get("offset", DEFAULT_OFFSET)
    order_by = call.data.get("order_by", DEFAULT_ORDER_BY)
    items: list[tuple[str, str]] = []
    # Every fake playlist is a playlist and none is a favourite.
    if media_type == "playlist" and not call.data.get("favorite"):
        search = call.data.get("search", "").casefold()
        items = [item for item in PLAYLISTS if search in item[1].casefold()]
        if order_by == "name":
            items.sort(key=lambda item: item[1])
        elif order_by == "name_desc":
            items.sort(key=lambda item: item[1], reverse=True)
    return {
        "items": [_library_item(uri, name) for uri, name in items[offset:][:limit]],
        "limit": limit,
        "offset": offset,
        "order_by": order_by,
        "media_type": media_type,
    }


async def _handle_set_available(call: ServiceCall) -> None:
    """Make a fake player unavailable, or available again."""
    entity_id = call.data[ATTR_ENTITY_ID]
    player = call.hass.data[DATA_PLAYERS].get(entity_id)
    if player is None:
        raise ServiceValidationError(f"{entity_id} isn't a fake Music Assistant player")
    player.set_available(call.data["available"])
