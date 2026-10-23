"""Config flow for HA Fitness.

SPIKE (step 2): a Supervisor discovery step (`hassio`). Throwaway; findings in docs/spike-step-2.md.
"""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.service_info.hassio import HassioServiceInfo

from .const import DOMAIN


class HaFitnessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up HA Fitness; there is nothing to enter (one entry, see the manifest)."""

    VERSION = 1

    _discovered: dict[str, Any]

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the setup."""
        if user_input is None:
            return self.async_show_form(step_id="user")
        return self.async_create_entry(title="HA Fitness", data={})

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle the add-on's Supervisor discovery message."""
        self._discovered = {
            "host": discovery_info.config["host"],
            "port": discovery_info.config["port"],
        }
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered add-on."""
        if user_input is None:
            return self.async_show_form(
                step_id="hassio_confirm",
                description_placeholders={
                    "url": f"http://{self._discovered['host']}:{self._discovered['port']}"
                },
            )
        return self.async_create_entry(title="HA Fitness", data=self._discovered)
