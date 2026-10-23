"""Talk to the HA Fitness add-on's REST API."""

from typing import Any

import aiohttp

# Health is a quick check; an add-on that takes longer counts as unreachable.
HEALTH_TIMEOUT = aiohttp.ClientTimeout(total=10)


class AddonConnectionError(Exception):
    """The add-on could not be reached, or did not answer as an add-on does."""


async def async_health(session: aiohttp.ClientSession, url: str) -> dict[str, Any]:
    """Return the body of `GET <url>/api/v1/health`."""
    try:
        async with session.get(
            f"{url}/api/v1/health", timeout=HEALTH_TIMEOUT, raise_for_status=True
        ) as response:
            body: dict[str, Any] = await response.json()
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise AddonConnectionError(str(err)) from err
    return body
