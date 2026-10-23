"""REST routes for exercises (spec §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

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


@router.post("", status_code=201)
def add_custom_exercise(
    services: ServicesDep,
    client: Annotated[str, Depends(client_from_request)],
    new: NewCustomExercise,
) -> Exercise:
    """Add a custom exercise."""
    return services.library.add_custom(new, client)
