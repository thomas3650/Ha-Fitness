"""The FastAPI app.

SPIKE (step 2): MCP at /mcp, an Ingress page at /, and a Supervisor discovery message at start-up.
Throwaway code; the findings are in docs/spike-step-2.md.
"""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
import os
from typing import TypedDict

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastmcp import FastMCP
from fastmcp.utilities.lifespan import combine_lifespans
import httpx

from . import __version__
from .settings import Settings

API_VERSION: int = 1
DISCOVERY_SERVICE = "ha_fitness"

_LOGGER = logging.getLogger(__name__)


class Health(TypedDict):
    """Body of `GET /api/v1/health`."""

    status: str
    version: str
    api_version: int


async def _send_discovery(settings: Settings) -> None:
    """Tell the Supervisor where the API is, so HA offers to set up the integration."""
    token = os.environ.get("SUPERVISOR_TOKEN")
    if not token:
        _LOGGER.info("No SUPERVISOR_TOKEN: not under the Supervisor, no discovery sent")
        return
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(base_url="http://supervisor", headers=headers) as http:
        info = (await http.get("/addons/self/info")).json()["data"]
        config = {"host": info["hostname"], "port": settings.port}
        response = await http.post(
            "/discovery", json={"service": DISCOVERY_SERVICE, "config": config}
        )
        _LOGGER.warning(
            "Discovery sent %s: %s %s", config, response.status_code, response.text
        )


def create_app(settings: Settings) -> FastAPI:
    """Build the app for the given settings."""
    mcp = FastMCP("HA Fitness")

    @mcp.tool
    def ping() -> str:
        """Check that the HA Fitness add-on answers. Returns its version."""
        return f"HA Fitness {__version__}"

    @mcp.tool
    def search_exercises(query: str) -> list[str]:
        """Search the exercise library by name (spike: a fixed list)."""
        names = ["push-up", "squat", "plank", "burpee", "lunge"]
        return [name for name in names if query.lower() in name]

    mcp_app = mcp.http_app(path="/mcp")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        try:
            await _send_discovery(settings)
        except Exception:
            _LOGGER.exception("Discovery failed")
        yield

    app = FastAPI(
        title="HA Fitness",
        version=__version__,
        lifespan=combine_lifespans(lifespan, mcp_app.lifespan),
    )
    app.state.settings = settings

    @app.get("/api/v1/health")
    async def health() -> Health:
        return {"status": "ok", "version": __version__, "api_version": API_VERSION}

    @app.get("/", response_class=HTMLResponse)
    async def status_page(request: Request) -> str:
        ingress_path = request.headers.get("X-Ingress-Path", "(none)")
        return (
            "<!doctype html><title>HA Fitness</title>"
            f"<h1>HA Fitness {__version__}</h1>"
            f"<p>Ingress path: <code>{ingress_path}</code></p>"
            '<p><a href="api/v1/health">health</a></p>'
        )

    # Mounted last at the root: the MCP app serves /mcp itself (no /mcp -> /mcp/ redirect).
    app.mount("/", mcp_app)
    return app
