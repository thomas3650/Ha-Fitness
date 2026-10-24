"""The ha_fitness.skip service (spec §4.4)."""

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import probatio

from .client import (
    AddonConnectionError,
    TrainingDayNotFoundError,
    TrainingDayNotOpenError,
    async_skip,
)
from .const import DOMAIN
from .coordinator import FitnessCoordinator

SERVICE_SKIP = "skip"
ATTR_TRAINING_DAY_ID = "training_day_id"

# Training day ids start at 1, as services.yaml says.
SKIP_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_TRAINING_DAY_ID): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1)
        )
    }
)


def _unavailable() -> HomeAssistantError:
    return HomeAssistantError(translation_domain=DOMAIN, translation_key="unavailable")


def _coordinator(hass: HomeAssistant) -> FitnessCoordinator:
    """Return the loaded entry's coordinator, or raise unavailable.

    It is unavailable too while the add-on is disconnected or speaks an unsupported API version.
    """
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        coordinator: FitnessCoordinator = entry.runtime_data
        if coordinator.available:
            return coordinator
    raise _unavailable()


async def _async_skip(call: ServiceCall) -> None:
    """Skip an open training day through the add-on."""
    coordinator = _coordinator(call.hass)
    training_day_id: int = call.data[ATTR_TRAINING_DAY_ID]
    placeholders = {ATTR_TRAINING_DAY_ID: str(training_day_id)}
    try:
        await async_skip(
            coordinator.http_session,
            coordinator.url,
            training_day_id,
            coordinator.integration_version,
        )
    except TrainingDayNotFoundError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_found",
            translation_placeholders=placeholders,
        ) from err
    except TrainingDayNotOpenError as err:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="not_open",
            translation_placeholders=placeholders,
        ) from err
    except AddonConnectionError as err:
        raise _unavailable() from err


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services; they exist even while no entry is loaded."""
    hass.services.async_register(DOMAIN, SERVICE_SKIP, _async_skip, schema=SKIP_SCHEMA)
