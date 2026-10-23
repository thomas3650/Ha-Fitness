"""Tests for the HA Fitness config flow."""

from unittest.mock import patch

from homeassistant.config_entries import SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.ha_fitness.const import DOMAIN


async def test_user_step_creates_entry(hass: HomeAssistant) -> None:
    """The user step has no fields and creates the "HA Fitness" entry."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    # Setting the entry up is covered by test_frontend; here it would serve the real frontend/ folder.
    with patch(
        "custom_components.ha_fitness.async_setup_entry", return_value=True
    ) as mock_setup_entry:
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA Fitness"
    assert len(mock_setup_entry.mock_calls) == 1


async def test_second_entry_is_refused(
    hass: HomeAssistant, config_entry: MockConfigEntry
) -> None:
    """With an entry in place, a second one is refused."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
