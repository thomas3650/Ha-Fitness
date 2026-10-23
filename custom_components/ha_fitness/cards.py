"""Serve the HA Fitness Lovelace cards to the frontend."""

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url, remove_extra_js_url

# http re-exports StaticPathConfig without `as`, so strict mypy sees it as private; it is the public path.
from homeassistant.components.http import StaticPathConfig  # type: ignore[attr-defined]
from homeassistant.core import HomeAssistant, callback
from homeassistant.util.hass_dict import HassKey

from .const import CARDS_FILE, DOMAIN, FRONTEND_URL_BASE

FRONTEND_DIR = Path(__file__).parent / "frontend"

# A static path can't be unregistered, so it is registered once per Home Assistant run.
_DATA_STATIC_PATH_REGISTERED: HassKey[bool] = HassKey(
    f"{DOMAIN}_static_path_registered"
)


def cards_url(version: str) -> str:
    """Return the module URL of the cards bundle; the version busts browser caches."""
    return f"{FRONTEND_URL_BASE}/{CARDS_FILE}?v={version}"


async def async_register_cards(hass: HomeAssistant, version: str) -> None:
    """Serve the frontend folder and load the cards bundle in the frontend."""
    if not hass.data.get(_DATA_STATIC_PATH_REGISTERED):
        await hass.http.async_register_static_paths(
            [
                StaticPathConfig(
                    FRONTEND_URL_BASE, str(FRONTEND_DIR), cache_headers=False
                )
            ]
        )
        hass.data[_DATA_STATIC_PATH_REGISTERED] = True
    add_extra_js_url(hass, cards_url(version))


@callback
def async_unregister_cards(hass: HomeAssistant, version: str) -> None:
    """Stop loading the cards bundle in the frontend (the static path stays)."""
    remove_extra_js_url(hass, cards_url(version))
