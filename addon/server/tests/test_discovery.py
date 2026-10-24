"""Tests for the Supervisor discovery at start (step 4 spec §3.7), with a fake Supervisor."""

import asyncio
from collections.abc import Callable
import json
import logging

import httpx
import pytest

from tests.conftest import MakeApp, running

TOKEN = "test-supervisor-token"
HOSTNAME = "local-ha-fitness"


class FakeSupervisor:
    """A Supervisor that answers `addons/self/info` and `discovery`, and records every request."""

    def __init__(self) -> None:
        """Start with no requests."""
        self.requests: list[httpx.Request] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Record and answer one request."""
        self.requests.append(request)
        if request.method == "GET" and request.url.path == "/addons/self/info":
            return httpx.Response(
                200, json={"result": "ok", "data": {"hostname": HOSTNAME}}
            )
        if request.method == "POST" and request.url.path == "/discovery":
            return httpx.Response(200, json={"result": "ok", "data": {"uuid": "x"}})
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        """Return a transport to this fake."""
        return httpx.MockTransport(self.handle)


async def _until(condition: Callable[[], bool], seconds: float = 5) -> None:
    """Wait until `condition()` is true; fail after `seconds`."""
    async with asyncio.timeout(seconds):
        while not condition():
            await asyncio.sleep(0.01)


async def test_discovery_posts_hostname(make_app: MakeApp) -> None:
    """Under the Supervisor the start posts the service, the hostname and port 8765, with the token."""
    supervisor = FakeSupervisor()
    app = make_app(
        settings_overrides={"supervisor_token": TOKEN},
        supervisor_transport=supervisor.transport(),
    )
    async with running(app):
        await _until(lambda: any(r.method == "POST" for r in supervisor.requests))
    [post] = [r for r in supervisor.requests if r.method == "POST"]
    assert str(post.url) == "http://supervisor/discovery"
    assert json.loads(post.content) == {
        "service": "ha_fitness",
        "config": {"host": HOSTNAME, "port": 8765},
    }
    for request in supervisor.requests:
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"


async def test_no_token_no_discovery(make_app: MakeApp) -> None:
    """Outside the Supervisor no request goes to it, and the server answers."""
    supervisor = FakeSupervisor()
    app = make_app(supervisor_transport=supervisor.transport())
    async with running(app) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
        await asyncio.sleep(0.1)
    assert supervisor.requests == []


async def test_discovery_failure_does_not_stop_start(
    make_app: MakeApp, caplog: pytest.LogCaptureFixture
) -> None:
    """A Supervisor that can't be reached logs a warning; the server starts and answers."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    app = make_app(
        settings_overrides={"supervisor_token": TOKEN},
        supervisor_transport=httpx.MockTransport(refuse),
    )
    with caplog.at_level(logging.WARNING, logger="ha_fitness_server.discovery"):
        async with running(app) as client:
            await _until(
                lambda: any(
                    r.name == "ha_fitness_server.discovery"
                    and r.levelno == logging.WARNING
                    for r in caplog.records
                )
            )
            assert (await client.get("/api/v1/health")).status_code == 200


async def test_slow_supervisor_does_not_delay_start(make_app: MakeApp) -> None:
    """A Supervisor that never answers doesn't hold up the start."""

    async def hang(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(3600)
        return httpx.Response(200)

    app = make_app(
        settings_overrides={"supervisor_token": TOKEN},
        supervisor_transport=httpx.MockTransport(hang),
    )
    async with asyncio.timeout(5), running(app) as client:
        assert (await client.get("/api/v1/health")).status_code == 200
