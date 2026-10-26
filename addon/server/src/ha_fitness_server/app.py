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

from . import API_VERSION, __version__, discovery, snapshot
from .api import add_error_handlers, router as api_router
from .api.dev import router as dev_router
from .clock import Clock, SystemClock
from .db import open_database
from .ha import HaClient
from .ingress import render as render_ingress
from .library.media import MediaStore
from .library.service import Library
from .mcp_tools import build_mcp
from .music import MusicService
from .people import People
from .programs import Programs
from .push import Hub, Message
from .services import Services, ServicesHolder
from .sessions import Sessions
from .settings import Settings
from .setup import SetupService
from .stats import StatsService
from .training_days import TrainingDays

_LOGGER = logging.getLogger(__name__)

__all__ = ["API_VERSION", "create_app"]

_ALL_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


def _publisher(
    hub: Hub, loop: asyncio.AbstractEventLoop
) -> Callable[[list[Message]], None]:
    """Return a `publish` for any thread: it hands each batch of messages to `hub` on `loop`, in one callback.

    Once the loop is closed (a worker thread still running at shutdown), the message is dropped.
    """

    def publish(messages: list[Message]) -> None:
        with suppress(RuntimeError):
            loop.call_soon_threadsafe(hub.broadcast, messages)

    return publish


async def _run_scheduler(training_days: TrainingDays, interval: float) -> None:
    """Reconcile every `interval` seconds in a worker thread; a failed run is logged and the next one still runs."""
    while True:
        await asyncio.sleep(interval)
        try:
            await anyio.to_thread.run_sync(training_days.reconcile_now)
        except Exception:
            _LOGGER.exception("The scheduler run failed")


async def _run_session_loop(sessions: Sessions, tick_max: float) -> None:
    """Tick the session in a worker thread, waking at the phase's deadline and at least every `tick_max` seconds.

    A failed tick is logged and the next one still runs.
    """
    while True:
        wait: float | None = None
        try:
            wait = await anyio.to_thread.run_sync(sessions.tick)
        except Exception:
            _LOGGER.exception("The session tick failed")
        await asyncio.sleep(tick_max if wait is None else min(wait, tick_max))


def _shut_down(sessions: Sessions, settings: Settings) -> None:
    """Pause a running session, then write the backup snapshot (step 5 spec §3.6); a failure is logged, not raised."""
    try:
        sessions.pause_for_shutdown()
    except Exception:
        _LOGGER.exception("Pausing the session at shutdown failed")
    try:
        snapshot.write_snapshot(settings.data_dir)
    except Exception:
        _LOGGER.exception("Writing the snapshot at shutdown failed")


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
    skip_shutdown: bool = False,
) -> FastAPI:
    """Build the app for the given settings.

    The transports replace the network to HA, to the media source and to the Supervisor; the clock replaces the
    system clock. Tests pass fakes. `skip_shutdown` is for tests only: the shutdown neither pauses the session nor
    writes the snapshot, as after a crash.
    """
    holder = ServicesHolder()
    the_clock = clock or SystemClock()
    mcp = build_mcp(holder)
    mcp_app = mcp.http_app(path="/mcp")
    hub = Hub()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Open the database, recover the session, reconcile, then start the loops, the media download and the discovery.

        The discovery runs as a task, so a slow Supervisor never delays the start. At the end the tasks stop, then a
        running session is paused and the snapshot written (spec §3.6).
        """
        engine = open_database(settings.data_dir)
        app.state.engine = engine
        library = Library(engine)
        media = MediaStore(settings.data_dir, settings.media_base_url, media_transport)
        ha = HaClient(
            settings.ha_url, settings.ha_token, settings.ha_token_file, ha_transport
        )
        publish = _publisher(hub, asyncio.get_running_loop())
        training_days = TrainingDays(
            engine, the_clock, settings.timezone, publish, settings.late_days
        )
        people = People(engine, ha, training_days, the_clock)
        programs = Programs(engine, library, training_days)
        sessions = Sessions(engine, the_clock, training_days, programs, people, publish)
        stats = StatsService(engine, training_days, sessions)
        holder.set(
            Services(
                engine=engine,
                library=library,
                media=media,
                music=MusicService(ha),
                people=people,
                programs=programs,
                sessions=sessions,
                setup=SetupService(engine, library),
                stats=stats,
                training_days=training_days,
            )
        )
        # Before recover and the reconcile, so the stats' memory of what was published starts filled.
        training_days.on_change = stats.messages_if_changed
        # Before reconcile: a session ended by the pause limit leaves its day to reconcile like any other.
        sessions.recover()
        training_days.reconcile_now()
        scheduler = asyncio.create_task(
            _run_scheduler(training_days, settings.scheduler_interval)
        )
        session_loop = asyncio.create_task(
            _run_session_loop(sessions, settings.session_tick_max)
        )
        download = asyncio.create_task(media.download_missing(library.media_files()))
        announce = asyncio.create_task(
            discovery.announce(settings, supervisor_transport)
        )
        try:
            yield
        finally:
            for task in (scheduler, session_loop, download, announce):
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            if not skip_shutdown:
                await anyio.to_thread.run_sync(_shut_down, sessions, settings)
            engine.dispose()

    app = FastAPI(
        title="HA Fitness",
        version=__version__,
        lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
    )
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

    @app.api_route(
        "/",
        methods=["GET", "HEAD"],
        response_class=HTMLResponse,
        include_in_schema=False,
    )
    def ingress_page(request: Request) -> HTMLResponse:
        """The Ingress page (spec §9); before the MCP mount, which would answer `/` otherwise."""
        page = render_ingress(holder.get(), request.headers.get("accept-language"))
        return HTMLResponse(page)

    # Mounted at the root and last, after every route: the MCP app serves `/mcp` itself, with no redirect (D26).
    app.mount("/", mcp_app)
    return app
