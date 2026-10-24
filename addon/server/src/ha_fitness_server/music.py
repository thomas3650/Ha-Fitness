"""Music Assistant's speakers and playlists, read from Home Assistant (music spec §4.3)."""

from typing import Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from .errors import Unavailable
from .ha import HaClient
from .schemas import PlaylistOut, SpeakerOut

# Lists Music Assistant's `media_player` entities, unavailable ones included, as JSON (music spec §3).
SPEAKERS_TEMPLATE = """\
{%- set ns = namespace(out=[]) -%}
{%- for e in integration_entities('music_assistant') if e.startswith('media_player.') -%}
{%- set ns.out = ns.out + [{'entity_id': e, 'name': state_attr(e, 'friendly_name') or e, 'state': states(e), 'entry': config_entry_id(e)}] -%}
{%- endfor -%}
{{ ns.out | tojson }}"""

PLAYLIST_LIMIT = 500
_NOT_AVAILABLE = frozenset({"unavailable", "unknown"})
_UNEXPECTED = "Can't reach Home Assistant: unexpected answer"


class _Player(BaseModel):
    """One entry of the speakers template's answer."""

    entity_id: str
    name: str
    state: str
    entry: str | None


class _Item(BaseModel):
    """One item of `music_assistant.get_library`'s answer; the other keys are ignored."""

    name: str
    uri: str


class _Library(BaseModel):
    """`music_assistant.get_library`'s `service_response`; the other keys are ignored."""

    items: list[_Item]


_PLAYERS = TypeAdapter(list[_Player])


class MusicService:
    """Reads the speakers and playlists through the add-on's HA client; every failure is `Unavailable`."""

    def __init__(self, ha: HaClient) -> None:
        """Keep the HA client."""
        self._ha = ha

    def speakers(self) -> list[SpeakerOut]:
        """Return Music Assistant's players, sorted by name; `unavailable` and `unknown` aren't available."""
        speakers = [
            SpeakerOut(
                entity_id=player.entity_id,
                name=player.name,
                available=player.state not in _NOT_AVAILABLE,
            )
            for player in self._players()
        ]
        return sorted(speakers, key=lambda s: (s.name.casefold(), s.entity_id))

    def playlists(self, search: str | None) -> list[PlaylistOut]:
        """Return the library's playlists, sorted by name, from the first speaker's config entry.

        Without a speaker that has a config entry the answer is `[]`. An empty `search` is no search.
        """
        entry = next(
            (player.entry for player in self._players() if player.entry is not None),
            None,
        )
        if entry is None:
            return []
        data: dict[str, Any] = {
            "config_entry_id": entry,
            "media_type": "playlist",
            "limit": PLAYLIST_LIMIT,
        }
        if search:
            data["search"] = search
        answer = self._ha.call_service_response("music_assistant", "get_library", data)
        try:
            library = _Library.model_validate(answer)
        except ValidationError as error:
            raise Unavailable(_UNEXPECTED) from error
        playlists = [
            PlaylistOut(name=item.name, uri=item.uri) for item in library.items
        ]
        return sorted(playlists, key=lambda p: (p.name.casefold(), p.uri))

    def _players(self) -> list[_Player]:
        """Return the speakers template's answer, in HA's order."""
        text = self._ha.render_template(SPEAKERS_TEMPLATE)
        try:
            return _PLAYERS.validate_json(text)
        except ValidationError as error:
            raise Unavailable(_UNEXPECTED) from error
