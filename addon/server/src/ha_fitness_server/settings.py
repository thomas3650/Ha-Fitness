"""Server settings, read from the environment and from <data dir>/options.json."""

from dataclasses import dataclass
import json
import logging
import os
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .library import DATASET_COMMIT

_LOGGER = logging.getLogger(__name__)

DEFAULT_PORT = 8765
DEFAULT_SCHEDULER_INTERVAL = 60.0
DEFAULT_SESSION_TICK_MAX = 1.0
DEFAULT_LATE_DAYS = 2
MAX_LATE_DAYS = 6
# The add-on's options, as the Supervisor writes them into the data folder.
OPTIONS_FILE = "options.json"
UTC_ZONE = ZoneInfo("UTC")
DEFAULT_DATA_DIR = Path("/data")
# Where the add-on image holds the built website (website spec §6).
DEFAULT_WEB_DIR = Path("/opt/ha-fitness/web")
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
    least every `session_tick_max` seconds (step 5 spec §3.2). A late training day stays open at most `late_days` days
    after its date (today-ahead spec §2.1.5). `web_dir` holds the built website: `index.html` and the `web/` assets
    (website spec §6).
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
    late_days: int = DEFAULT_LATE_DAYS
    web_dir: Path = DEFAULT_WEB_DIR

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
        data_dir = Path(os.environ.get("HA_FITNESS_DATA_DIR", DEFAULT_DATA_DIR))
        return cls(
            port=int(os.environ.get("HA_FITNESS_PORT", DEFAULT_PORT)),
            data_dir=data_dir,
            ha_url=ha_url,
            ha_token=supervisor_token or None,
            ha_token_file=ha_token_file,
            media_base_url=os.environ.get(
                "HA_FITNESS_MEDIA_BASE_URL", DEFAULT_MEDIA_BASE_URL
            ),
            timezone=_timezone_from_env(),
            dev=os.environ.get("HA_FITNESS_DEV") == "1",
            supervisor_token=supervisor_token or None,
            late_days=_late_days(data_dir),
            web_dir=Path(os.environ.get("HA_FITNESS_WEB_DIR", DEFAULT_WEB_DIR)),
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


def _late_days(data_dir: Path) -> int:
    """Return `late_days`: `HA_FITNESS_LATE_DAYS`, else the add-on option in `options.json`, else the default.

    A value that isn't a whole number from 0 to 6 is ignored with a warning.
    """
    variable = os.environ.get("HA_FITNESS_LATE_DAYS")
    if variable:
        try:
            value: Any = int(variable)
        except ValueError:
            value = variable
        if _valid_late_days(value):
            return int(value)
        _LOGGER.warning(
            "HA_FITNESS_LATE_DAYS=%r is not a whole number from 0 to %d; ignoring it",
            variable,
            MAX_LATE_DAYS,
        )
    options = _options(data_dir)
    if "late_days" in options:
        value = options["late_days"]
        if _valid_late_days(value):
            return int(value)
        _LOGGER.warning(
            "The option late_days=%r is not a whole number from 0 to %d; using %d",
            value,
            MAX_LATE_DAYS,
            DEFAULT_LATE_DAYS,
        )
    return DEFAULT_LATE_DAYS


def _valid_late_days(value: Any) -> bool:
    """Return whether `value` is an integer from 0 to 6; a boolean is not."""
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= MAX_LATE_DAYS
    )


def _options(data_dir: Path) -> dict[str, Any]:
    """Return the add-on's options from the data folder; none when the file is missing or isn't a JSON object."""
    path = data_dir / OPTIONS_FILE
    try:
        options = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except OSError, ValueError:
        _LOGGER.warning("The add-on options in %s can't be read; ignoring them", path)
        return {}
    if not isinstance(options, dict):
        _LOGGER.warning(
            "The add-on options in %s are not an object; ignoring them", path
        )
        return {}
    return options
