"""Fixtures for the HA Fitness tests."""

from pathlib import Path

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness import cards
from custom_components.ha_fitness.const import CARDS_FILE, DOMAIN

# A stand-in for the bundle Task 5 builds; the real frontend/ folder is never used in tests.
FAKE_BUNDLE = (
    "customElements.define('ha-fitness-test-card', class extends HTMLElement {});\n"
)


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Let Home Assistant load integrations from custom_components in every test."""


@pytest.fixture
def cards_bundle(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Serve the cards from a temporary folder that holds a small bundle."""
    bundle = tmp_path / CARDS_FILE
    bundle.write_text(FAKE_BUNDLE, encoding="utf-8")
    monkeypatch.setattr(cards, "FRONTEND_DIR", tmp_path)
    return bundle


@pytest.fixture
def config_entry(hass: HomeAssistant) -> MockConfigEntry:
    """The integration's config entry, added to Home Assistant but not set up."""
    entry = MockConfigEntry(domain=DOMAIN, title="HA Fitness", data={})
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def setup_entry(
    hass: HomeAssistant, config_entry: MockConfigEntry, cards_bundle: Path
) -> MockConfigEntry:
    """The config entry, set up (with the cards served from the temporary bundle)."""
    assert await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry
