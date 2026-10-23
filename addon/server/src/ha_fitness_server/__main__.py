"""Run the server: `python -m ha_fitness_server`."""

import uvicorn

from .app import create_app
from .settings import Settings


def main() -> None:
    """Start uvicorn on all interfaces with the settings from the environment."""
    settings = Settings.from_env()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    uvicorn.run(create_app(settings), host="0.0.0.0", port=settings.port)


if __name__ == "__main__":
    main()
