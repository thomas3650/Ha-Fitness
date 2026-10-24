"""The media proxy: an exercise's GIF or thumbnail from the add-on, behind HA's login (the workout spec §4)."""

from http import HTTPStatus
import re

from aiohttp import web
from homeassistant.helpers.http import KEY_HASS, HomeAssistantView

from .client import AddonConnectionError, async_media
from .const import DOMAIN
from .coordinator import FitnessCoordinator

# A library id (four digits) or a custom one (custom-<n>); ASCII only, matched whole.
EXERCISE_ID = re.compile(r"(\d{4}|custom-[1-9]\d*)", re.ASCII)
KINDS = ("gif", "thumbnail")
CACHE_CONTROL = "private, max-age=86400"


class MediaView(HomeAssistantView):
    """Relay `GET /api/v1/exercises/{exercise_id}/{kind}` from the add-on; it requires a login."""

    url = "/api/ha_fitness/media/{exercise_id}/{kind}"
    name = "api:ha_fitness:media"
    requires_auth = True

    async def get(
        self, request: web.Request, exercise_id: str, kind: str
    ) -> web.Response:
        """Return the file; 404 for an id or kind outside the patterns, before any relay."""
        if kind not in KINDS or EXERCISE_ID.fullmatch(exercise_id) is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        hass = request.app[KEY_HASS]
        entries = hass.config_entries.async_loaded_entries(DOMAIN)
        if not entries:
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
        coordinator: FitnessCoordinator = entries[0].runtime_data
        try:
            media = await async_media(
                coordinator.http_session, coordinator.url, exercise_id, kind
            )
        except AddonConnectionError:
            return web.Response(status=HTTPStatus.SERVICE_UNAVAILABLE)
        if media is None:
            return web.Response(status=HTTPStatus.NOT_FOUND)
        return web.Response(
            body=media.body,
            content_type=media.content_type,
            headers={"Cache-Control": CACHE_CONTROL},
        )
