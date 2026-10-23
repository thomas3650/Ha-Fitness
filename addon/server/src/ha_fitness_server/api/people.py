"""REST routes for the people (spec §4, §7)."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import PeopleUpdate, PeopleView, Person
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(prefix="/people", tags=["people"])

ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("")
def list_people(services: ServicesDep) -> PeopleView:
    """Return the people and HA's persons; reading never fails because of HA."""
    return services.people.list()


@router.put("")
def set_people(
    services: ServicesDep,
    client: Annotated[str, Depends(client_from_request)],
    update: PeopleUpdate,
) -> list[Person]:
    """Replace the people; 422 for a bad list, 503 when HA can't be asked."""
    return services.people.set(update.people, client)
