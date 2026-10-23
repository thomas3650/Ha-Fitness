"""REST route for the change log (spec §6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ha_fitness_server import changes
from ha_fitness_server.schemas import ChangeEntry
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(tags=["changes"])


@router.get("/changes")
def change_log(
    services: Annotated[Services, Depends(get_services)],
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
) -> list[ChangeEntry]:
    """Return the newest writes, newest first."""
    return changes.recent(services.engine, limit)
