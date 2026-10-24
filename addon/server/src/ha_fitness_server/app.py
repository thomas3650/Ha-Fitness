"""The FastAPI app."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager, suppress
import logging
from typing import TypedDict

import anyio
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastmcp.utilities.lifespan import combine_lifespans
import httpx

from . import API_VERSION, __version__, discovery
from .api import add_error_handlers, router as api_router
from .api.dev import router as dev_router
from .clock import Clock, SystemClock
from .db import open_database
from .ha import HaClient
from .ingress import render as render_ingress
from .library.media import MediaStore
from .library.service import Library
from .mcp_tools import build_mcp
from .people import People
from .programs import Programs
from .push import Hub, Message
from .services import Services, ServicesHolder
from .settings import Settings
from .training_days import TrainingDays

_LOGGER = logging.getLogger(__name__)

__all__ = ["API_VERSION", "create_app"]

_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _publisher(hub: Hub, loop: asyncio.AbstractEventLoop) -> Callable[[Message], None]:
    """Return a `publish` for any thread: it hands each message to `hub` on `loop`.

    Once the loop is closed (a worker thread still running at shutdown), the message is dropped.
    """

    def publish(message: Message) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(hub.broadcast, message)

    return publish


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
    hub = Hub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the database, reconcile, then start the scheduler, the media download and the discovery; stop them at the end.

        The discovery runs as a task, so a slow Supervisor never delays the start.
        """
        engine = open_database(settings.data_dir)
        app.state.engine = engine
        library = Library(engine)
        media = MediaStore(settings.data_dir, settings.media_base_url, media_transport)
        ha = HaClient(
            settings.ha_url, settings.ha_token, settings.ha_token_file, ha_transport
        )
        training_days = TrainingDays(
            engine,
            the_clock,
            settings.timezone,
            _publisher(hub, asyncio.get_running_loop()),
        )
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
        announce = asyncio.create_task(
            discovery.announce(settings, supervisor_transport)
        )
        try:
            yield
        finally:
            for task in (scheduler, download, announce):
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
    app.state.hub = hub

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    app.include_router(api_router)
    if settings.dev:
        app.include_router(dev_router)
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
