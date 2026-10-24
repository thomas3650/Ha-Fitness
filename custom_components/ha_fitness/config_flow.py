"""Config flow for HA Fitness: found through Supervisor discovery, or set up with the add-on's URL."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_URL
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
import probatio

from .client import AddonConnectionError, async_health
from .const import DEFAULT_URL, DOMAIN, UNIQUE_ID

TITLE = "HA Fitness"


class HaFitnessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up the one HA Fitness entry; its data is the add-on's URL."""

    VERSION = 2

    _url: str

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the add-on's URL and check that the add-on answers there."""
        # Any entry counts: a version 1 entry gets its unique id only when it is migrated.
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured()

        errors: dict[str, str] = {}
        if user_input is not None:
            url = user_input[CONF_URL].rstrip("/")
            try:
                await async_health(async_get_clientsession(self.hass), url)
            except AddonConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(title=TITLE, data={CONF_URL: url})

        return self.async_show_form(
            step_id="user",
            data_schema=probatio.Schema(
                {probatio.Required(CONF_URL, default=DEFAULT_URL): str}
            ),
            errors=errors,
        )

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Handle the add-on's Supervisor discovery; an existing entry gets the new address."""
        url = f"http://{discovery_info.config['host']}:{discovery_info.config['port']}"
        for entry in self._async_current_entries():
            if entry.unique_id is None:
                # A version 1 entry not migrated (so not loaded) yet: give it the version 2
                # shape with this URL; its setup then skips the migration and uses the URL.
                self.hass.config_entries.async_update_entry(
                    entry,
                    data={CONF_URL: url},
                    unique_id=UNIQUE_ID,
                    version=self.VERSION,
                )
                return self.async_abort(reason="already_configured")
        await self.async_set_unique_id(UNIQUE_ID)
        self._abort_if_unique_id_configured(updates={CONF_URL: url})
        self._url = url
        # Without placeholders the Discovered card shows the domain, ha_fitness.
        self.context["title_placeholders"] = {"name": TITLE}
        return await self.async_step_hassio_confirm()

    async def async_step_hassio_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm the discovered add-on."""
        if user_input is None:
            self._set_confirm_only()
            return self.async_show_form(step_id="hassio_confirm")
        return self.async_create_entry(title=TITLE, data={CONF_URL: self._url})
