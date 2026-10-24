"""The REST API under `/api/v1`: thin routes over the services."""

from fastapi import APIRouter

from . import changes, exercises, library, people, programs, today, ws
from .errors import add_error_handlers

router = APIRouter(prefix="/api/v1")
router.include_router(library.router)
router.include_router(exercises.router)
router.include_router(programs.router)
router.include_router(people.router)
router.include_router(changes.router)
router.include_router(today.router)
router.include_router(ws.router)

__all__ = ["add_error_handlers", "router"]
