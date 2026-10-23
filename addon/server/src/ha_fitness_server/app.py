"""The FastAPI app."""

from typing import TypedDict

from fastapi import FastAPI

from . import __version__
from .settings import Settings

API_VERSION: int = 1


class Health(TypedDict):
    """Body of `GET /api/v1/health`."""

    status: str
    version: str
    api_version: int


def create_app(settings: Settings) -> FastAPI:
    """Build the app for the given settings."""
    app = FastAPI(title="HA Fitness", version=__version__)
    app.state.settings = settings

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    return app
