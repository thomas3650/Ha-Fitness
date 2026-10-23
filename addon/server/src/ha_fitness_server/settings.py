"""Server settings, read from the environment."""

from dataclasses import dataclass
import os
from pathlib import Path

DEFAULT_PORT = 8765
DEFAULT_DATA_DIR = Path("/data")


@dataclass(frozen=True)
class Settings:
    """Settings for one server run."""

    port: int
    data_dir: Path

    @classmethod
    def from_env(cls) -> Settings:
        """Read the settings from `HA_FITNESS_PORT` and `HA_FITNESS_DATA_DIR`."""
        return cls(
            port=int(os.environ.get("HA_FITNESS_PORT", DEFAULT_PORT)),
            data_dir=Path(os.environ.get("HA_FITNESS_DATA_DIR", DEFAULT_DATA_DIR)),
        )
