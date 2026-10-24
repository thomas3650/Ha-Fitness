"""Server settings, read from the environment."""

from dataclasses import dataclass
import logging
import os
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .library import DATASET_COMMIT

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_SCHEDULER_INTERVAL = 60.0
DEFAULT_SESSION_TICK_MAX = 1.0
UTC_ZONE = ZoneInfo("UTC")
DEFAULT_DATA_DIR = Path("/data")
SUPERVISOR_HA_URL = "http://supervisor/core"
DEFAULT_MEDIA_BASE_URL = (
    f"https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/{DATASET_COMMIT}"
)


@dataclass(frozen=True)
class Settings:
    """Settings for one server run.

    HA is reached at `ha_url` (the server adds `/api`) with `ha_token`, or with the token read from `ha_token_file` at
    each call. Without a URL HA is not configured. `timezone` gives the local dates of training days (spec §3.2);
    `supervisor_token` is for the Supervisor's discovery API. The session loop wakes at a phase's deadline, and at
    least every `session_tick_max` seconds (step 5 spec §3.2).
    """

    port: int
    data_dir: Path
    ha_url: str | None = None
    ha_token: str | None = None
    ha_token_file: Path | None = None
    media_base_url: str = DEFAULT_MEDIA_BASE_URL
    timezone: ZoneInfo = UTC_ZONE
    dev: bool = False
    scheduler_interval: float = DEFAULT_SCHEDULER_INTERVAL
    session_tick_max: float = DEFAULT_SESSION_TICK_MAX
    supervisor_token: str | None = None

    @classmethod
    def from_env(cls) -> Settings:
        """Read the settings from the environment; `SUPERVISOR_TOKEN` wins over `HA_FITNESS_HA_*`."""
        supervisor_token = os.environ.get("SUPERVISOR_TOKEN")
        if supervisor_token:
            ha_url: str | None = SUPERVISOR_HA_URL
            ha_token_file = None
        else:
            ha_url = os.environ.get("HA_FITNESS_HA_URL") or None
            token_file = os.environ.get("HA_FITNESS_HA_TOKEN_FILE")
            ha_token_file = Path(token_file) if token_file else None
        return cls(
            port=int(os.environ.get("HA_FITNESS_PORT", DEFAULT_PORT)),
            data_dir=Path(os.environ.get("HA_FITNESS_DATA_DIR", DEFAULT_DATA_DIR)),
            ha_url=ha_url,
            ha_token=supervisor_token or None,
            ha_token_file=ha_token_file,
            media_base_url=os.environ.get(
                "HA_FITNESS_MEDIA_BASE_URL", DEFAULT_MEDIA_BASE_URL
            ),
            timezone=_timezone_from_env(),
            dev=os.environ.get("HA_FITNESS_DEV") == "1",
            supervisor_token=supervisor_token or None,
        )


def _timezone_from_env() -> ZoneInfo:
    """Return the zone named by `HA_FITNESS_TIMEZONE`, else `TZ`, else UTC; an unknown name gives UTC."""
    name = os.environ.get("HA_FITNESS_TIMEZONE") or os.environ.get("TZ")
    if not name:
        _LOGGER.info("No timezone is set; using UTC")
        return UTC_ZONE
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError, ValueError:
        _LOGGER.warning("The timezone %r is unknown; using UTC", name)
        return UTC_ZONE
