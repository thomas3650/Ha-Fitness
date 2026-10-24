"""Dev-only REST routes (step 4 spec §3.5): how the fast loop makes a due or late day on purpose.

The app includes this router only with `HA_FITNESS_DEV=1`, and never in OpenAPI.
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from ha_fitness_server.schemas import TrainingDayOut
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(prefix="/api/v1/dev", include_in_schema=False)

ServicesDep = Annotated[Services, Depends(get_services)]


class OpenDayRequest(BaseModel):
    """The body of `POST /api/v1/dev/training-days`."""

    model_config = ConfigDict(extra="forbid")

    program_id: int
    date: dt.date


@router.post("/training-days")
def upsert_open_day(services: ServicesDep, body: OpenDayRequest) -> TrainingDayOut:
    """Make an open day for the program on the date, or reopen the one there is; 404 for an unknown program."""
    return services.training_days.upsert_open(body.program_id, body.date)


@router.delete("/training-days", status_code=204)
def delete_days_of_date(
    services: ServicesDep, day: Annotated[dt.date, Query(alias="date")]
) -> None:
    """Remove every training day of the date, open or closed."""
    services.training_days.delete_date(day)
