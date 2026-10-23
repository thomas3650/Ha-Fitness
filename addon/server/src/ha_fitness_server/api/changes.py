"""REST route for the change log (spec §6)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ha_fitness_server import changes
from ha_fitness_server.schemas import ChangeEntry, ChangeLogLimit
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(tags=["changes"])


@router.get("/changes")
def change_log(
    services: Annotated[Services, Depends(get_services)],
    limit: Annotated[ChangeLogLimit, Query()] = 20,
) -> list[ChangeEntry]:
    """Return the newest writes, newest first."""
    return changes.recent(services.engine, limit)
