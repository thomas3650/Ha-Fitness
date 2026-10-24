"""Map the service errors to HTTP responses with FastAPI's `detail`."""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from ha_fitness_server.errors import (
    Conflict,
    Invalid,
    NotFound,
    SessionError,
    Unavailable,
)

_STATUS = {NotFound: 404, Conflict: 409, Invalid: 422, Unavailable: 503}


async def _handle(_request: Request, error: Exception) -> JSONResponse:
    """Answer with the error's status; `Invalid` carries its own detail, the others their text."""
    detail = error.detail if isinstance(error, Invalid) else str(error)
    return JSONResponse({"detail": detail}, status_code=_STATUS[type(error)])


async def _handle_session(_request: Request, error: Exception) -> JSONResponse:
    """Answer a session error with its own status and the detail `{code, message}` (step 5 spec §3.5)."""
    assert isinstance(error, SessionError)
    return JSONResponse(
        {"detail": {"code": error.code, "message": error.message}},
        status_code=error.status,
    )


def add_error_handlers(app: FastAPI) -> None:
    """Install the handlers for the service errors on `app`."""
    for error_type in _STATUS:
        app.add_exception_handler(error_type, _handle)
    app.add_exception_handler(SessionError, _handle_session)
