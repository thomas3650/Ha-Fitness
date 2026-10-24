"""Reaching Home Assistant's REST API (spec §4.1)."""

from pathlib import Path
from typing import Any

import httpx

from .errors import Unavailable
from .schemas import HaPerson

TIMEOUT_SECONDS = 10.0
PERSON_PREFIX = "person."


class HaClient:
    """Reads Home Assistant at `<base_url>/api` with a bearer token.

    The token is `token`, else the stripped contents of `token_file`, read at each call so a token written after the
    start works without a restart.
    """

    def __init__(
        self,
        base_url: str | None,
        token: str | None,
        token_file: Path | None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        """Keep where and how to reach HA; `transport` replaces the network in tests."""
        self._base_url = base_url.rstrip("/") if base_url else None
        self._token = token
        self._token_file = token_file
        self._transport = transport

    def persons(self) -> list[HaPerson]:
        """Return HA's `person.*` entities; raise `Unavailable` when HA isn't configured or can't be reached."""
        states = self._get("/api/states")
        if not isinstance(states, list):
            raise Unavailable("Can't reach Home Assistant: unexpected answer")
        persons = []
        for state in states:
            entity_id = state.get("entity_id") if isinstance(state, dict) else None
            if isinstance(entity_id, str) and entity_id.startswith(PERSON_PREFIX):
                persons.append(
                    HaPerson(
                        entity_id=entity_id,
                        friendly_name=_friendly_name(state) or entity_id,
                    )
                )
        return persons

    def render_template(self, template: str) -> str:
        """Return HA's rendering of `template` (`POST /api/template`), as plain text."""
        return self._send("POST", "/api/template", {"template": template}).text

    def call_service_response(
        self, domain: str, service: str, data: dict[str, Any]
    ) -> Any:
        """Call a service that answers a response, and return its `service_response`."""
        response = self._send(
            "POST", f"/api/services/{domain}/{service}?return_response", data
        )
        body = _json(response)
        if not isinstance(body, dict) or "service_response" not in body:
            raise Unavailable("Can't reach Home Assistant: unexpected answer")
        return body["service_response"]

    def _get(self, path: str) -> Any:
        """Return the JSON of `GET <base_url><path>`."""
        return _json(self._send("GET", path, None))

    def _send(
        self, method: str, path: str, body: dict[str, Any] | None
    ) -> httpx.Response:
        """Send one request to `<base_url><path>` and return the successful response; raise `Unavailable` otherwise."""
        if self._base_url is None:
            raise Unavailable("Home Assistant isn't configured: no URL")
        headers = {"Authorization": f"Bearer {self._read_token()}"}
        try:
            with httpx.Client(
                transport=self._transport, timeout=TIMEOUT_SECONDS
            ) as http_client:
                response = http_client.request(
                    method, f"{self._base_url}{path}", headers=headers, json=body
                )
        except httpx.HTTPError as error:
            # Never the error's text: it can quote the request, the token included.
            raise Unavailable(
                f"Can't reach Home Assistant: {type(error).__name__}"
            ) from error
        if not response.is_success:
            raise Unavailable(
                f"Can't reach Home Assistant: HTTP {response.status_code}"
            )
        return response

    def _read_token(self) -> str:
        """Return the token; raise `Unavailable` when there is none or it can't go in a header."""
        token = self._find_token()
        if not _valid_token(token):
            raise Unavailable("Home Assistant isn't configured: the token is not valid")
        return token

    def _find_token(self) -> str:
        """Return `token`, else the token file's stripped contents; raise `Unavailable` when there is none."""
        if self._token:
            return self._token
        if self._token_file is not None:
            try:
                token = self._token_file.read_text().strip()
            except OSError:
                token = ""
            if token:
                return token
            raise Unavailable(
                "Home Assistant isn't configured: no token in the token file"
            )
        raise Unavailable("Home Assistant isn't configured: no token")


def _json(response: httpx.Response) -> Any:
    """Return the response's JSON; raise `Unavailable` when it isn't JSON."""
    try:
        return response.json()
    except ValueError as error:
        raise Unavailable("Can't reach Home Assistant: answer isn't JSON") from error


def _valid_token(token: str) -> bool:
    """Tell whether the token is printable ASCII without whitespace, so it can go in a header."""
    return (
        token.isascii()
        and token.isprintable()
        and not any(character.isspace() for character in token)
    )


def _friendly_name(state: dict[str, Any]) -> str | None:
    """Return the state's friendly name, or `None` when it is missing or not a text."""
    attributes = state.get("attributes")
    if not isinstance(attributes, dict):
        return None
    name = attributes.get("friendly_name")
    return name if isinstance(name, str) and name else None
