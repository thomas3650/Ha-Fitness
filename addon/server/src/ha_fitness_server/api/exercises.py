"""REST routes for exercises (spec §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from ha_fitness_server.errors import NotFound
from ha_fitness_server.library.media import MediaKind
from ha_fitness_server.schemas import (
    Exercise,
    ExerciseSearch,
    Facets,
    NewCustomExercise,
)
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(prefix="/exercises", tags=["exercises"])

ServicesDep = Annotated[Services, Depends(get_services)]

_MEDIA_TYPES: dict[MediaKind, str] = {"gif": "image/gif", "thumbnail": "image/jpeg"}


@router.get("")
def search_exercises(
    services: ServicesDep,
    q: str = "",
    equipment: str | None = None,
    body_part: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ExerciseSearch:
    """Search the library and custom exercises; the facets come with an empty search."""
    library = services.library
    results = library.search(q, equipment, body_part, limit)
    empty = not q.strip() and equipment is None and body_part is None
    facets = Facets.model_validate(library.facets()) if empty else None
    return ExerciseSearch(results=results, facets=facets)


@router.get("/{exercise_id}")
def get_exercise(services: ServicesDep, exercise_id: str) -> Exercise:
    """Return one exercise with its steps and attribution."""
    return services.library.get(exercise_id)


def _media(services: Services, exercise_id: str, kind: MediaKind) -> FileResponse:
    """Return a library exercise's stored media file; raise `NotFound` while it isn't there or for a custom one."""
    files = services.library.media_of(exercise_id)
    path = None if files is None else services.media.path(kind, files)
    if path is None:
        raise NotFound(f"No {kind} for exercise '{exercise_id}'")
    return FileResponse(path, media_type=_MEDIA_TYPES[kind])


@router.get("/{exercise_id}/gif", response_class=FileResponse)
def get_gif(services: ServicesDep, exercise_id: str) -> FileResponse:
    """Return the exercise's GIF; 404 while it isn't downloaded, and for custom exercises."""
    return _media(services, exercise_id, "gif")


@router.get("/{exercise_id}/thumbnail", response_class=FileResponse)
def get_thumbnail(services: ServicesDep, exercise_id: str) -> FileResponse:
    """Return the exercise's thumbnail; 404 while it isn't downloaded, and for custom exercises."""
    return _media(services, exercise_id, "thumbnail")


@router.post("", status_code=201)
def add_custom_exercise(
    services: ServicesDep,
    client: Annotated[str, Depends(client_from_request)],
    new: NewCustomExercise,
) -> Exercise:
    """Add a custom exercise."""
    return services.library.add_custom(new, client)
