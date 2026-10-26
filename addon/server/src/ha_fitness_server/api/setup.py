"""REST routes for the household setup (website spec §2.4)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import Setup
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(prefix="/setup", tags=["setup"])

ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("")
def get_setup(services: ServicesDep) -> Setup:
    """Return the setup; the defaults while none is written."""
    return services.setup.get()


@router.put("")
def set_setup(
    services: ServicesDep,
    client: Annotated[str, Depends(client_from_request)],
    setup: Setup,
) -> Setup:
    """Replace the setup; 422 for equipment no exercise has (`equipment_unknown`)."""
    return services.setup.set(setup, client)
