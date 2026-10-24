"""The FastAPI app."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
import logging
from typing import Any, TypedDict

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastmcp.utilities.lifespan import combine_lifespans
import httpx

from . import __version__
from .api import add_error_handlers, router as api_router
from .clock import Clock, SystemClock
from .db import open_database
from .ha import HaClient
from .ingress import render as render_ingress
from .library.media import MediaStore
from .library.service import Library
from .mcp_tools import build_mcp
from .people import People
from .programs import Programs
from .services import Services, ServicesHolder
from .settings import Settings
from .training_days import TrainingDays

_LOGGER = logging.getLogger(__name__)

API_VERSION: int = 1
_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _no_publish(message: dict[str, Any]) -> None:
    """Drop a push message; the push channel arrives with the websocket."""


async def _run_scheduler(training_days: TrainingDays, interval: float) -> None:
    """Reconcile every `interval` seconds in a worker thread; a failed run is logged and the next one still runs."""
    while True:
        await asyncio.sleep(interval)
        try:
            await anyio.to_thread.run_sync(training_days.reconcile_now)
        except Exception:
            _LOGGER.exception("The scheduler run failed")


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
    clock: Clock | None = None,
    supervisor_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    """Build the app for the given settings.

    The transports replace the network to HA, to the media source and to the Supervisor; the clock replaces the
    system clock. Tests pass fakes.
    """
    holder = ServicesHolder()
    the_clock = clock or SystemClock()
    mcp = build_mcp(holder)
    mcp_app = mcp.http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the database, reconcile, then start the scheduler and the media download; stop both at the end."""
        engine = open_database(settings.data_dir)
        app.state.engine = engine
        library = Library(engine)
        media = MediaStore(settings.data_dir, settings.media_base_url, media_transport)
        ha = HaClient(
            settings.ha_url, settings.ha_token, settings.ha_token_file, ha_transport
        )
        training_days = TrainingDays(engine, the_clock, settings.timezone, _no_publish)
        holder.set(
            Services(
                engine=engine,
                library=library,
                media=media,
                people=People(engine, ha),
                programs=Programs(engine, library, training_days),
                training_days=training_days,
            )
        )
        training_days.reconcile_now()
        scheduler = asyncio.create_task(
            _run_scheduler(training_days, settings.scheduler_interval)
        )
        download = asyncio.create_task(media.download_missing(library.media_files()))
        try:
            yield
        finally:
            for task in (scheduler, download):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
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
    app.state.clock = the_clock
    app.state.supervisor_transport = supervisor_transport

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    app.include_router(api_router)
    add_error_handlers(app)

    @app.api_route("/api/{path:path}", methods=_ALL_METHODS, include_in_schema=False)
    async def unknown_api_path(path: str) -> None:
        """Answer an unknown `/api` path with FastAPI's JSON 404, so the MCP mount below never answers it.

        It must stay after every `/api` route: a route registered below it is shadowed.
        """
        raise HTTPException(status_code=404)

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def ingress_page(request: Request) -> HTMLResponse:
        """The Ingress page (spec §9); before the MCP mount, which would answer `/` otherwise."""
        page = render_ingress(holder.get(), request.headers.get("accept-language"))
        return HTMLResponse(page)

    # Mounted at the root and last, after every route: the MCP app serves `/mcp` itself, with no redirect (D26).
    app.mount("/", mcp_app)
    return app
