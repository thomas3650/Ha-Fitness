"""The services: ha_fitness.skip (spec §4.4), and start_session and end_session (the workout spec §4)."""

from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import probatio

from .client import (
    AddonConnectionError,
    SessionRefusedError,
    TrainingDayNotFoundError,
    TrainingDayNotOpenError,
    async_session_command,
    async_skip,
    async_start_session,
)
from .const import DOMAIN
from .coordinator import FitnessCoordinator, usable_coordinator

SERVICE_SKIP = "skip"
SERVICE_START_SESSION = "start_session"
SERVICE_END_SESSION = "end_session"
ATTR_TRAINING_DAY_ID = "training_day_id"
ATTR_PROGRAM_ID = "program_id"
ATTR_PARTICIPANTS = "participants"

# Training day ids start at 1, as services.yaml says.
SKIP_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_TRAINING_DAY_ID): probatio.All(
            probatio.Coerce(int), probatio.Range(min=1)
        )
    }
)

# The add-on checks the participants (1 or 2, unique, existing), so its refusal is the one shown.
START_SESSION_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_PROGRAM_ID): probatio.Coerce(int),
        probatio.Required(ATTR_PARTICIPANTS): [probatio.Coerce(int)],
        probatio.Optional(ATTR_TRAINING_DAY_ID): probatio.Coerce(int),
    }
)
END_SESSION_SCHEMA = probatio.Schema({})


def _unavailable() -> HomeAssistantError:
    return HomeAssistantError(translation_domain=DOMAIN, translation_key="unavailable")


def _coordinator(hass: HomeAssistant) -> FitnessCoordinator:
    """Return the loaded entry's coordinator, or raise unavailable.

    It is unavailable too while the add-on is disconnected or speaks an unsupported API version.
    """
    if (coordinator := usable_coordinator(hass)) is None:
        raise _unavailable()
    return coordinator


def _refused(err: SessionRefusedError) -> ServiceValidationError:
    return ServiceValidationError(
        translation_domain=DOMAIN, translation_key=f"session_{err.code}"
    )


async def _async_start_session(call: ServiceCall) -> None:
    """Start a session through the add-on."""
    coordinator = _coordinator(call.hass)
    try:
        await async_start_session(
            coordinator.http_session,
            coordinator.url,
            call.data[ATTR_PROGRAM_ID],
            call.data[ATTR_PARTICIPANTS],
            call.data.get(ATTR_TRAINING_DAY_ID),
            coordinator.integration_version,
        )
    except SessionRefusedError as err:
        raise _refused(err) from err
    except AddonConnectionError as err:
        raise _unavailable() from err


async def _async_end_session(call: ServiceCall) -> None:
    """End the running or paused session through the add-on."""
    coordinator = _coordinator(call.hass)
    try:
        await async_session_command(
            coordinator.http_session,
            coordinator.url,
            "end",
            coordinator.integration_version,
        )
    except SessionRefusedError as err:
        raise _refused(err) from err
    except AddonConnectionError as err:
        raise _unavailable() from err


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
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_SESSION,
        _async_start_session,
        schema=START_SESSION_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_END_SESSION, _async_end_session, schema=END_SESSION_SCHEMA
    )
