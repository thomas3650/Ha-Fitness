"""Supervisor discovery (step 4 spec §3.7): tell HA where the add-on's API is, so it offers the integration."""

import asyncio
import logging

import httpx

from .settings import Settings

_LOGGER = logging.getLogger(__name__)

SUPERVISOR_URL = "http://supervisor"
SERVICE = "ha_fitness"
# The port the add-on's API listens on inside the Supervisor's network (`addon/config.yaml`).
PORT = 8765
TIMEOUT = 10.0


async def announce(
    settings: Settings, transport: httpx.AsyncBaseTransport | None = None
) -> None:
    """Post the discovery message, with the add-on's hostname; a failure or a timeout logs a warning.

    Without `settings.supervisor_token` (outside the Supervisor) it does nothing.
    """
    if not settings.supervisor_token:
        return
    headers = {"Authorization": f"Bearer {settings.supervisor_token}"}
    try:
        async with (
            asyncio.timeout(TIMEOUT),
            httpx.AsyncClient(
                base_url=SUPERVISOR_URL, headers=headers, transport=transport
            ) as http,
        ):
            info = await http.get("/addons/self/info")
            info.raise_for_status()
            config = {"host": info.json()["data"]["hostname"], "port": PORT}
            response = await http.post(
                "/discovery", json={"service": SERVICE, "config": config}
            )
            response.raise_for_status()
    except Exception:
        _LOGGER.warning("The discovery message could not be sent", exc_info=True)
        return
    _LOGGER.info("Discovery sent: %s", config)
