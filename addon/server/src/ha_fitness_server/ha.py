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
        return [
            HaPerson(
                entity_id=state["entity_id"],
                friendly_name=state.get("attributes", {}).get(
                    "friendly_name", state["entity_id"]
                ),
            )
            for state in states
            if isinstance(state, dict)
            and str(state.get("entity_id", "")).startswith(PERSON_PREFIX)
        ]

    def _get(self, path: str) -> Any:
        """Return the JSON of `GET <base_url><path>`."""
        if self._base_url is None:
            raise Unavailable("Home Assistant isn't configured: no URL")
        headers = {"Authorization": f"Bearer {self._read_token()}"}
        try:
            with httpx.Client(
                transport=self._transport, timeout=TIMEOUT_SECONDS
            ) as http_client:
                response = http_client.get(f"{self._base_url}{path}", headers=headers)
        except httpx.HTTPError as error:
            raise Unavailable(f"Can't reach Home Assistant: {error}") from error
        if not response.is_success:
            raise Unavailable(
                f"Can't reach Home Assistant: HTTP {response.status_code}"
            )
        try:
            return response.json()
        except ValueError as error:
            raise Unavailable(
                "Can't reach Home Assistant: answer isn't JSON"
            ) from error

    def _read_token(self) -> str:
        """Return the token; raise `Unavailable` when there is none."""
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
