"""Shared fixtures for the server tests."""

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from ha_fitness_server.app import create_app
from ha_fitness_server.settings import Settings
import httpx
import pytest

type MakeApp = Callable[..., FastAPI]

_DATASET_FOLDERS = ("videos/", "images/")


class FrozenClock:
    """A clock that stands still until a test sets or advances it; times are aware UTC."""

    def __init__(self, start: datetime) -> None:
        """Start at `start`."""
        self._now = start

    def now(self) -> datetime:
        """Return the frozen time."""
        return self._now

    def set(self, moment: datetime) -> None:
        """Jump to `moment`."""
        self._now = moment

    def advance(self, delta: timedelta) -> None:
        """Move the time on by `delta`."""
        self._now += delta


def dataset_path(request: httpx.Request) -> str:
    """Return the dataset path a media request asks for (`videos/<file>.gif`, `images/<file>.jpg`)."""
    path = request.url.path
    for folder in _DATASET_FOLDERS:
        if folder in path:
            return path[path.index(folder) :]
    return path


def fake_media_bytes(path: str) -> bytes:
    """Return the small body the fake media source serves for a dataset path."""
    return f"fake media {path}".encode()


def fake_media_transport() -> httpx.MockTransport:
    """Return a fake media source that answers every file at once with small bytes."""
    return httpx.MockTransport(
        lambda request: httpx.Response(
            200, content=fake_media_bytes(dataset_path(request))
        )
    )


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Run the app's lifespan and yield an HTTP client talking to it in-process."""
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as http_client,
    ):
        yield http_client


@pytest.fixture
def make_app(tmp_path: Path) -> MakeApp:
    """Return a factory that builds a fresh app per call on the test's data folder.

    `settings_overrides` replaces `Settings` fields; the other keywords go to `create_app`. The media source is a
    fake unless a test passes its own `media_transport`, so no test touches the network. HA is not configured unless
    a test overrides `ha_url` with `ha_token` or `ha_token_file` (and passes an `ha_transport` fake).
    """

    def _make_app(
        settings_overrides: dict[str, Any] | None = None, **create_app_kwargs: Any
    ) -> FastAPI:
        settings = replace(
            Settings(port=0, data_dir=tmp_path), **(settings_overrides or {})
        )
        create_app_kwargs.setdefault("media_transport", fake_media_transport())
        return create_app(settings, **create_app_kwargs)

    return _make_app


@pytest.fixture
async def client(make_app: MakeApp) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client talking to a running app.

    pytest-asyncio sets a fixture up and tears it down in two tasks, but the MCP lifespan's task group must end in
    the task that started it; so one task of our own runs the whole lifespan.
    """
    started: asyncio.Future[httpx.AsyncClient] = (
        asyncio.get_running_loop().create_future()
    )
    stop = asyncio.Event()

    async def run() -> None:
        async with running(make_app()) as http_client:
            started.set_result(http_client)
            await stop.wait()

    task = asyncio.create_task(run())
    either: set[asyncio.Future[Any]] = {task, started}
    await asyncio.wait(either, return_when=asyncio.FIRST_COMPLETED)
    if not started.done():
        # The lifespan failed to start: raise its error.
        await task
    try:
        yield started.result()
    finally:
        stop.set()
        await task
