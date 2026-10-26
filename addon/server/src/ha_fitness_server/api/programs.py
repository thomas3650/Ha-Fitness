"""REST routes for the programs (spec §5, §7)."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends

from ha_fitness_server.schemas import (
    ProgramActive,
    ProgramDefaults,
    ProgramDocument,
    ProgramOut,
)
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(prefix="/programs", tags=["programs"])

ServicesDep = Annotated[Services, Depends(get_services)]
ClientDep = Annotated[str, Depends(client_from_request)]


@router.get("")
def list_programs(services: ServicesDep) -> list[ProgramOut]:
    """Return every program, by name."""
    return services.programs.list()


@router.post("", status_code=201)
def create_program(
    services: ServicesDep, client: ClientDep, program: ProgramDocument
) -> ProgramOut:
    """Create a program; 422 with close matches for a station that can't be resolved, 409 for a taken name."""
    return services.programs.create(program, client)


@router.get("/defaults")
def get_program_defaults() -> ProgramDefaults:
    """Return what a program gets for each field it leaves out; before `/{program_id}`, which would take the path."""
    return ProgramDefaults()


@router.get("/{program_id}")
def get_program(services: ServicesDep, program_id: int) -> ProgramOut:
    """Return one program."""
    return services.programs.get(program_id)


@router.put("/{program_id}")
def replace_program(
    services: ServicesDep,
    client: ClientDep,
    program_id: int,
    program: ProgramDocument,
    if_updated_at: datetime | None = None,
) -> ProgramOut:
    """Replace a program's whole document; with `if_updated_at` only while it is the stored `updated_at`.

    A different one is a 409 with the code `changed_elsewhere` (spec §2.2.6).
    """
    return services.programs.replace(program_id, program, client, if_updated_at)


@router.put("/{program_id}/active")
def set_program_active(
    services: ServicesDep, client: ClientDep, program_id: int, body: ProgramActive
) -> ProgramOut:
    """Switch a program on or off; switching on one without weekdays is a 422."""
    return services.programs.set_active(program_id, body.active, client)


@router.delete("/{program_id}", status_code=204)
def delete_program(services: ServicesDep, client: ClientDep, program_id: int) -> None:
    """Delete a program for good."""
    services.programs.delete(program_id, client)
