"""The FastAPI app."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TypedDict

from fastapi import FastAPI, HTTPException
from fastmcp.utilities.lifespan import combine_lifespans
import httpx

from . import __version__
from .api import add_error_handlers, router as api_router
from .db import open_database
from .ha import HaClient
from .library.media import MediaStore
from .library.service import Library
from .mcp_tools import build_mcp
from .people import People
from .programs import Programs
from .services import Services, ServicesHolder
from .settings import Settings

API_VERSION: int = 1
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


class Health(TypedDict):
    """Body of `GET /api/v1/health`."""

    status: str
    version: str
    api_version: int


def create_app(
    settings: Settings,
    *,
    ha_transport: httpx.BaseTransport | None = None,
    media_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the app for the given settings.

    The transports replace the network to HA and to the media source; tests pass fakes.
    """
    holder = ServicesHolder()
    mcp = build_mcp(holder)
    mcp_app = mcp.http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the database and start the media download; stop the download and close the database at the end."""
        engine = open_database(settings.data_dir)
        app.state.engine = engine
        library = Library(engine)
        media = MediaStore(settings.data_dir, settings.media_base_url, media_transport)
        ha = HaClient(
            settings.ha_url, settings.ha_token, settings.ha_token_file, ha_transport
        )
        holder.set(
            Services(
                engine=engine,
                library=library,
                media=media,
                people=People(engine, ha),
                programs=Programs(engine, library),
            )
        )
        download = asyncio.create_task(media.download_missing(library.media_files()))
        try:
            yield
        finally:
            download.cancel()
            with suppress(asyncio.CancelledError):
                await download
            engine.dispose()

    app = FastAPI(
        title="HA Fitness",
        version=__version__,
        lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
    )
    app.state.settings = settings
    app.state.services = holder
    app.state.mcp = mcp
    app.state.ha_transport = ha_transport
    app.state.media_transport = media_transport

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    app.include_router(api_router)
    add_error_handlers(app)

    @app.api_route("/api/{path:path}", methods=_ALL_METHODS, include_in_schema=False)
    async def unknown_api_path(path: str) -> None:
        """Answer an unknown `/api` path with FastAPI's JSON 404, so the MCP mount below never answers it."""
        raise HTTPException(status_code=404)

    # Mounted at the root and last, after every route: the MCP app serves `/mcp` itself, with no redirect (D26).
    app.mount("/", mcp_app)
    return app
