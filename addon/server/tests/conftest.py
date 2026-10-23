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
    """Return a factory that builds a fresh app per call on the test's data folder."""

    def _make_app(**overrides: Any) -> FastAPI:
        settings = Settings(port=0, data_dir=overrides.pop("data_dir", tmp_path))
        return create_app(settings, **overrides)

    return _make_app


@pytest.fixture
async def client(make_app: MakeApp) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client talking to a running app."""
    async with running(make_app()) as http_client:
        yield http_client
