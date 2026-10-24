"""The services the adapters (REST and MCP) call, filled by the app's lifespan."""

from dataclasses import dataclass

from sqlalchemy import Engine

from .library.media import MediaStore
from .library.service import Library
from .people import People
from .programs import Programs
from .training_days import TrainingDays


@dataclass
class Services:
    """Everything a request needs; later steps add a field per service."""

    engine: Engine
    library: Library
    media: MediaStore
    people: People
    programs: Programs
    training_days: TrainingDays


class ServicesHolder:
    """Holds the services from the lifespan's start on; adapters read them at call time."""

    def __init__(self) -> None:
        """Start empty."""
        self._services: Services | None = None

    def set(self, services: Services) -> None:
        """Keep the services the lifespan built."""
        self._services = services

    def get(self) -> Services:
        """Return the services; raise `RuntimeError` before the lifespan ran."""
        if self._services is None:
            raise RuntimeError("not started")
        return self._services
