"""Shared fixtures for the server tests."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from ha_fitness_server.app import create_app
from ha_fitness_server.settings import Settings
import httpx
import pytest

type MakeApp = Callable[..., FastAPI]

_DATASET_FOLDERS = ("videos/", "images/")


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

    The media source is a fake unless a test passes its own `media_transport`, so no test touches the network.
    """

    def _make_app(**overrides: Any) -> FastAPI:
        settings = Settings(port=0, data_dir=overrides.pop("data_dir", tmp_path))
        overrides.setdefault("media_transport", fake_media_transport())
        return create_app(settings, **overrides)

    return _make_app


@pytest.fixture
async def client(make_app: MakeApp) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client talking to a running app."""
    async with running(make_app()) as http_client:
        yield http_client
