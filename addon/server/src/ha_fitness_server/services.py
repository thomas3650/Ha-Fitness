"""The services the adapters (REST and MCP) call, filled by the app's lifespan."""

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import Engine


@dataclass
class Services:
    """Everything a request needs; later steps add a field per service."""

    engine: Engine


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


def get_services(request: Request) -> Services:
    """FastAPI dependency: the services of the running app."""
    holder: ServicesHolder = request.app.state.services
    return holder.get()
