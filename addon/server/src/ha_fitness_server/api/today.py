"""REST routes for today and the training days (step 4 spec §3.5)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ha_fitness_server.schemas import TodayView, TrainingDayOut
from ha_fitness_server.services import Services

from .deps import client_from_request, get_services

router = APIRouter(tags=["training days"])

ServicesDep = Annotated[Services, Depends(get_services)]
ClientDep = Annotated[str, Depends(client_from_request)]


@router.get("/today")
def get_today(services: ServicesDep) -> TodayView:
    """Return the open training days, due or late, and the next date a program trains."""
    return services.training_days.today_view()


@router.get("/training-days")
def list_training_days(
    services: ServicesDep,
    start: Annotated[date, Query(alias="from")],
    end: Annotated[date, Query(alias="to")],
) -> list[TrainingDayOut]:
    """Return the training days from `from` to `to`, both included, by date."""
    return services.training_days.in_range(start, end)


@router.post("/training-days/{training_day_id}/skip")
def skip_training_day(
    services: ServicesDep, client: ClientDep, training_day_id: int
) -> TrainingDayOut:
    """Close an open training day as skipped; 404 for an unknown id, 409 for a closed day."""
    return services.training_days.skip(training_day_id, client)
