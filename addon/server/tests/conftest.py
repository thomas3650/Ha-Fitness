"""Shared fixtures for the server tests."""

from collections.abc import AsyncIterator
from pathlib import Path

from ha_fitness_server.app import create_app
from ha_fitness_server.settings import Settings
import httpx
import pytest


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    """Return an HTTP client talking to the app in-process."""
    app = create_app(Settings(port=0, data_dir=tmp_path))
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://test"
    ) as http_client:
        yield http_client
