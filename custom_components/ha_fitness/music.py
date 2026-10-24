"""Music during a workout: Music Assistant's speakers (the music spec §5).

This module never imports `websocket_api`; the commands import from here.
"""

from datetime import datetime
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import entity_sources

MUSIC_ASSISTANT = "music_assistant"
MEDIA_PLAYER_PREFIX = "media_player."
_NOT_AVAILABLE = frozenset({STATE_UNAVAILABLE, STATE_UNKNOWN})


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
