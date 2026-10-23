"""Tests for the HA Fitness config flow and the entry migration."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_HASSIO, SOURCE_USER, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import DOMAIN

from .fake_addon import FakeAddon

# Setting the entry up is covered by test_frontend; here it would serve the real frontend/ folder.
PATCH_SETUP_ENTRY = "custom_components.ha_fitness.async_setup_entry"

DISCOVERY = HassioServiceInfo(
    config={"host": "local-ha-fitness", "port": 8765},
    name="HA Fitness",
    slug="local_ha_fitness",
    uuid="1234",
)


async def test_user_step_checks_health_and_creates_entry(
    hass: HomeAssistant, fake_addon: FakeAddon
) -> None:
    """The user step asks for the add-on's URL and creates the entry once it answers."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["data_schema"] is not None
    assert result["data_schema"]({}) == {"url": "http://localhost:8765"}

    with patch(PATCH_SETUP_ENTRY, return_value=True) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": f"{fake_addon.url}/"}
        )
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA Fitness"
    assert result["data"] == {"url": fake_addon.url}
    assert result["result"].unique_id == "ha_fitness"
    assert len(mock_setup_entry.mock_calls) == 1


async def test_user_step_cannot_connect(
    hass: HomeAssistant, fake_addon: FakeAddon, unused_tcp_port: int
) -> None:
    """A URL where no add-on answers shows cannot_connect; a working one then succeeds."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": f"http://127.0.0.1:{unused_tcp_port}"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert result["errors"] == {"base": "cannot_connect"}

    with patch(PATCH_SETUP_ENTRY, return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"url": fake_addon.url}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_user_step_health_not_found(
    hass: HomeAssistant, fake_addon: FakeAddon
) -> None:
    """A URL where something answers, but health gives 404, shows cannot_connect."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"url": f"{fake_addon.url}/nope"}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "cannot_connect"}


async def test_second_entry_already_configured(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """With an entry in place, a second manual one is aborted as already_configured."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_hassio_discovery_creates_entry(hass: HomeAssistant) -> None:
    """The add-on's discovery shows a named confirm step and creates the entry with its URL."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "hassio_confirm"
    [flow] = hass.config_entries.flow.async_progress()
    assert flow["context"]["title_placeholders"] == {"name": "HA Fitness"}

    with patch(PATCH_SETUP_ENTRY, return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA Fitness"
    assert result["data"] == {"url": "http://local-ha-fitness:8765"}
    assert result["result"].unique_id == "ha_fitness"


async def test_hassio_discovery_updates_existing_url(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """A discovery for an existing entry gives that entry the add-on's address."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    assert config_entry.data == {"url": "http://local-ha-fitness:8765"}


async def test_migrate_v1_sets_url_and_unique_id(hass: HomeAssistant) -> None:
    """A version 1 entry (no URL, no unique id) becomes version 2 with the default URL."""
    entry = MockConfigEntry(domain=DOMAIN, title="HA Fitness", data={}, version=1)
    entry.add_to_hass(hass)

    # Patched, so the migrated entry connects to nothing on localhost.
    with patch(PATCH_SETUP_ENTRY, return_value=True):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state is ConfigEntryState.LOADED
    assert entry.version == 2
    assert entry.data == {"url": "http://localhost:8765"}
    assert entry.unique_id == "ha_fitness"


async def test_user_step_while_discovery_in_progress(hass: HomeAssistant) -> None:
    """With a Discovered card waiting, a manual setup aborts with Home Assistant's own text."""
    await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_HASSIO}, data=DISCOVERY
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_in_progress"
    assert result["translation_domain"] == "homeassistant"
