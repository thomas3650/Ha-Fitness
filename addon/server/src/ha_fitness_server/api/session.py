"""REST routes for the session (step 5 spec §3.5); errors answer with the detail `{code, message}`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import NewSession, SessionView
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(prefix="/session", tags=["session"])

ServicesDep = Annotated[Services, Depends(get_services)]
ClientDep = Annotated[str, Depends(client_from_request)]


@router.get("")
def get_session(services: ServicesDep) -> SessionView | None:
    """Return the running or paused session, or null."""
    return services.sessions.current()


@router.post("", status_code=201)
def start_session(
    services: ServicesDep, client: ClientDep, body: NewSession
) -> SessionView:
    """Start a session: 404 `not_found`, 409 `conflict` or 422 `invalid` when the start is refused."""
    return services.sessions.start(
        body.program_id, body.participants, body.training_day_id, client
    )
