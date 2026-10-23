"""FastAPI dependencies of the REST routes."""

from fastapi import Request

from ha_fitness_server.services import Services, ServicesHolder

MAX_CLIENT_LENGTH = 100


def get_services(request: Request) -> Services:
    """Return the services of the running app."""
    holder: ServicesHolder = request.app.state.services
    return holder.get()


def client_from_request(request: Request) -> str:
    """Return the change-log client: `rest:<User-Agent>` (`rest:unknown`), at most 100 characters."""
    user_agent = request.headers.get("user-agent") or "unknown"
    return f"rest:{user_agent}"[:MAX_CLIENT_LENGTH]
