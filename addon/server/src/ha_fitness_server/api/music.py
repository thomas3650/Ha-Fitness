"""REST routes for Music Assistant's speakers and playlists (music spec §4.3)."""

from typing import Annotated, TypedDict

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import PlaylistOut, SpeakerOut
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(prefix="/music", tags=["music"])

ServicesDep = Annotated[Services, Depends(get_services)]


class MusicIndex(TypedDict):
    """Body of `GET /api/v1/music`: where the speakers and the playlists are."""

    speakers: str
    playlists: str


@router.get("")
def music_index() -> MusicIndex:
    """Name the music routes without calling HA; the integration probes it to tell an older add-on."""
    return {
        "speakers": "/api/v1/music/speakers",
        "playlists": "/api/v1/music/playlists",
    }


@router.get("/speakers")
def list_speakers(services: ServicesDep) -> list[SpeakerOut]:
    """Return Music Assistant's speakers, sorted by name; 503 when HA can't be read."""
    return services.music.speakers()


@router.get("/playlists")
def list_playlists(
    services: ServicesDep, search: str | None = None
) -> list[PlaylistOut]:
    """Return the library's playlists, sorted by name; 503 when HA can't be read."""
    return services.music.playlists(search)
