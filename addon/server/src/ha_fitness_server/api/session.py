"""REST routes for sessions (step 5 spec §3.5); errors answer with the detail `{code, message}`."""

from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.errors import SessionError
from ha_fitness_server.schemas import FeelingIn, NewSession, SessionHistory, SessionView
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(tags=["session"])

ServicesDep = Annotated[Services, Depends(get_services)]
ClientDep = Annotated[str, Depends(client_from_request)]


@router.get("/session")
def get_session(services: ServicesDep) -> SessionView | None:
    """Return the running or paused session, else the one finished under 5 minutes ago, else null."""
    return services.sessions.current()


@router.post("/session", status_code=201)
def start_session(
    services: ServicesDep, client: ClientDep, body: NewSession
) -> SessionView:
    """Start a session: 404 `not_found`, 409 `conflict` or 422 `invalid` when the start is refused."""
    return services.sessions.start(
        body.program_id, body.participants, body.training_day_id, client
    )


@router.post("/session/feeling")
def session_feeling(
    services: ServicesDep, client: ClientDep, body: FeelingIn
) -> SessionView:
    """Rate the completed session of the finished view: 422 `invalid` for an unknown value, 409 `conflict` otherwise.

    Declared before `POST /session/{command}`, which would take `feeling` as a command.
    """
    return services.sessions.feel(body.feeling, client)


@router.post("/session/{command}")
def session_command(
    services: ServicesDep, client: ClientDep, command: str
) -> SessionView:
    """Run `pause`, `resume`, `next`, `previous` or `end`: 404 `not_found` for another, 409 `conflict` if not allowed."""
    return services.sessions.command(command, client)


@router.get("/sessions")
def list_sessions(services: ServicesDep, limit: str = "20") -> SessionHistory:
    """Return the finished sessions, newest first, and `counting_from`; `limit` is 1 to 100 (422 `invalid`).

    `limit` is read as text, so a bad value gets the session routes' `{code, message}`, not FastAPI's field list.
    """
    try:
        count = int(limit)
    except ValueError as error:
        raise SessionError(
            422, "invalid", f"limit must be a whole number, got {limit}"
        ) from error
    return services.sessions.finished(count)
