"""The fake Music Assistant's config flow: no fields, one entry."""

from typing import Any

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from . import DOMAIN, TITLE


class FakeMusicAssistantConfigFlow(ConfigFlow, domain=DOMAIN):
    """Create the entry at once, titled "Fake Music Assistant"."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Create the entry, or abort when one exists."""
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        # The title isn't the domain, so `integration_entities('music_assistant')` falls back to the loaded
        # entities, as on a real Music Assistant titled "Music Assistant".
        return self.async_create_entry(title=TITLE, data={})
