"""REST route for the stats (stats spec §4)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import Stats
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(tags=["stats"])

ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("/stats")
def get_stats(services: ServicesDep) -> Stats:
    """Return each person's streak and their numbers for this month and all time; ticks and reconciles first."""
    return services.stats.view()
