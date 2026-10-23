"""The FastAPI app."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TypedDict

from fastapi import FastAPI
import httpx

from . import __version__
from .api import add_error_handlers, router as api_router
from .db import open_database
from .library.service import Library
from .services import Services, ServicesHolder
from .settings import Settings

API_VERSION: int = 1


class Health(TypedDict):
    """Body of `GET /api/v1/health`."""

    status: str
    version: str
    api_version: int


def create_app(
    settings: Settings,
    *,
    ha_transport: httpx.AsyncBaseTransport | None = None,
    media_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the app for the given settings.

    The transports replace the network to HA and to the media source; tests pass fakes.
    """
    holder = ServicesHolder()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the database before requests are served; close it at the end."""
        engine = open_database(settings.data_dir)
        app.state.engine = engine
        holder.set(Services(engine=engine, library=Library(engine)))
        try:
            yield
        finally:
            engine.dispose()

    app = FastAPI(title="HA Fitness", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.services = holder
    app.state.ha_transport = ha_transport
    app.state.media_transport = media_transport

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    app.include_router(api_router)
    add_error_handlers(app)

    return app
