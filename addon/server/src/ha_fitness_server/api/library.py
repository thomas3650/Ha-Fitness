"""REST route for the library's state (spec §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import ExerciseCounts, LibraryStatus
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(tags=["library"])


@router.get("/library")
def library_status(
    services: Annotated[Services, Depends(get_services)],
) -> LibraryStatus:
    """Return the library and custom exercise counts and the media download's state."""
    counts = ExerciseCounts.model_validate(services.library.counts())
    return LibraryStatus(exercises=counts, media=services.media.state())
