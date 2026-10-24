"""REST routes for today and the training days (step 4 spec §3.5)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ha_fitness_server.schemas import TodayView, TrainingDayOut
from ha_fitness_server.services import Services

from .deps import get_services

router = APIRouter(tags=["training days"])

ServicesDep = Annotated[Services, Depends(get_services)]


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
