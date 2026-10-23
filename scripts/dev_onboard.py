"""Onboard a fresh dev Home Assistant and add the HA Fitness entry; safe to run again.

Usage: `uv run python scripts/dev_onboard.py [--url URL] [--no-entry] [--token-file PATH]`

- Refuses, before any request, unless the host of `--url` is `localhost` or `127.0.0.1`: it never talks to a real
  Home Assistant.
- Completes onboarding through HA's onboarding API with the user `dev` / password `dev` (dev only). Once
  onboarding is done HA answers 404 there; the script then logs in as `dev` and goes on.
- Sets that user's frontend language to Danish (`frontend/set_user_data`, key `language`); onboarding's
  `language` field only names the default areas.
- Keeps a long-lived token for the dev user in `local/dev-ha-token` (relative to the repo root, mode 600; a dev
  token only): when the file is missing or HA rejects the token in it (`GET /api/` answers 401), it creates a new one
  (websocket `auth/long_lived_access_token`, client name `ha-fitness-dev`) and writes it there; a valid file is kept.
  `--token-file PATH` uses another file (a relative path is relative to the current folder). The fast loop's add-on
  server reads this file at each call (`HA_FITNESS_HA_TOKEN_FILE`).
- Unless `--no-entry`, creates the HA Fitness config entry.

Every step that is already done is skipped, so a second run changes nothing.
"""

import argparse
import asyncio
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import asynccontextmanager
import itertools
import os
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

import aiohttp
import yarl

DEFAULT_URL = "http://localhost:8123"
NAME = "dev"
USERNAME = "dev"
PASSWORD = "dev"  # A local dev instance only; never a real Home Assistant.
DOMAIN = "ha_fitness"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
DEFAULT_TOKEN_FILE = Path(__file__).resolve().parents[1] / "local" / "dev-ha-token"
TOKEN_CLIENT_NAME = "ha-fitness-dev"
TOKEN_LIFESPAN_DAYS = 3650
LONG_LIVED = "long_lived_access_token"
# The frontend saves the language as its locale settings; the rest follow the language.
LANGUAGE = {
    "language": "da",
    "number_format": "language",
    "time_format": "language",
    "date_format": "language",
    "time_zone": "local",
    "first_weekday": "language",
}


def is_local_url(url: str) -> bool:
    """Whether the URL's host is exactly `localhost` or `127.0.0.1`, as both urllib and yarl (aiohttp) read it.

    Both parsers must agree: they disagree on some odd URLs (for example a backslash before `@`), and either one
    may raise `ValueError`, which counts as not local.
    """
    try:
        hosts = (urlsplit(url).hostname, yarl.URL(url).host)
    except ValueError:
        return False
    return all(host in LOCAL_HOSTS for host in hosts)


class OnboardError(Exception):
    """Home Assistant answered something this script can't continue from."""


async def _json(response: aiohttp.ClientResponse) -> Any:
    """Return the JSON body, or raise with the status and text."""
    if response.status >= 400:
        raise OnboardError(
            f"{response.method} {response.url.path}: {response.status} {await response.text()}"
        )
    return await response.json()


async def _token(session: aiohttp.ClientSession, client_id: str, code: str) -> str:
    """Exchange an authorization code for an access token."""
    async with session.post(
        "/auth/token",
        data={"grant_type": "authorization_code", "code": code, "client_id": client_id},
    ) as response:
        return str((await _json(response))["access_token"])


async def _login(
    session: aiohttp.ClientSession, client_id: str, redirect_uri: str
) -> str:
    """Log in as the dev user through the login flow; return an authorization code."""
    async with session.post(
        "/auth/login_flow",
        json={
            "client_id": client_id,
            "handler": ["homeassistant", None],
            "redirect_uri": redirect_uri,
        },
    ) as response:
        flow = await _json(response)
    async with session.post(
        f"/auth/login_flow/{flow['flow_id']}",
        json={"client_id": client_id, "username": USERNAME, "password": PASSWORD},
    ) as response:
        result = await _json(response)
    if result.get("type") != "create_entry":
        raise OnboardError(f"login as {USERNAME} failed: {result.get('errors')}")
    return str(result["result"])


async def login(session: aiohttp.ClientSession, base: str) -> str:
    """Log in as the dev user of an onboarded Home Assistant; return an access token."""
    client_id = f"{base}/"
    redirect_uri = f"{base}/?auth_callback=1"
    return await _token(
        session, client_id, await _login(session, client_id, redirect_uri)
    )


WsCall = Callable[..., Awaitable[Any]]


@asynccontextmanager
async def websocket(
    session: aiohttp.ClientSession, token: str
) -> AsyncIterator[WsCall]:
    """Open HA's websocket API with `token`; yield `call(type=..., **fields)`, which returns the result."""
    async with session.ws_connect("/api/websocket") as ws:
        await ws.receive_json()  # auth_required
        await ws.send_json({"type": "auth", "access_token": token})
        auth = await ws.receive_json()
        if auth.get("type") != "auth_ok":
            raise OnboardError(f"websocket auth failed: {auth.get('message')}")
        ids = itertools.count(1)

        async def call(**message: Any) -> Any:
            msg_id = next(ids)
            await ws.send_json({"id": msg_id, **message})
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == msg_id:
                    break
            if not reply.get("success"):
                raise OnboardError(f"{message['type']} failed: {reply.get('error')}")
            return reply.get("result")

        yield call


async def _onboard(session: aiohttp.ClientSession, base: str) -> str:
    """Finish the onboarding steps that aren't done; return an access token for the dev user."""
    client_id = f"{base}/"
    redirect_uri = f"{base}/?auth_callback=1"
    done: set[str] | None
    async with session.get("/api/onboarding") as response:
        if response.status == 404:
            # Home Assistant drops the onboarding views once onboarding is done.
            done = None
        else:
            done = {step["step"] for step in await _json(response) if step["done"]}

    if done is None:
        print("onboard: already onboarded")
        return await login(session, base)
    if "user" in done:
        token = await login(session, base)
    else:
        async with session.post(
            "/api/onboarding/users",
            json={
                "client_id": client_id,
                "name": NAME,
                "username": USERNAME,
                "password": PASSWORD,
                "language": "da",
            },
        ) as response:
            code = (await _json(response))["auth_code"]
        token = await _token(session, client_id, code)
        print(f"onboard: created user {USERNAME}")

    headers = {"Authorization": f"Bearer {token}"}
    steps: dict[str, dict[str, str]] = {
        "core_config": {},
        "analytics": {},
        "integration": {"client_id": client_id, "redirect_uri": redirect_uri},
    }
    for step, body in steps.items():
        if step in done:
            continue
        async with session.post(
            f"/api/onboarding/{step}", json=body, headers=headers
        ) as response:
            await _json(response)
        print(f"onboard: finished step {step}")
    return token


async def _set_language(session: aiohttp.ClientSession, token: str) -> None:
    """Set the dev user's frontend language to Danish and print what Home Assistant stored."""
    async with websocket(session, token) as call:
        current = await call(type="frontend/get_user_data", key="language")
        if current.get("value") != LANGUAGE:
            await call(type="frontend/set_user_data", key="language", value=LANGUAGE)
            print("onboard: set the frontend language to Danish")
        stored = await call(type="frontend/get_user_data", key="language")
        print(f"onboard: frontend language is {stored.get('value')}")


async def _token_is_valid(session: aiohttp.ClientSession, token: str) -> bool:
    """Ask HA whether it accepts `token`: 200 yes, 401 no; anything else is an error."""
    if not token:
        return False
    async with session.get(
        "/api/", headers={"Authorization": f"Bearer {token}"}
    ) as response:
        if response.status == 401:
            return False
        await _json(response)
        return True


def _write_private(path: Path, text: str) -> None:
    """Write `text` to `path` with mode 600, also when the file exists with another mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as file:
        file.write(text)
    path.chmod(0o600)


async def _keep_token(session: aiohttp.ClientSession, token: str, path: Path) -> None:
    """Keep a valid long-lived token for the dev user in `path`; create one when it is missing or rejected."""
    existing = path.read_text().strip() if path.is_file() else ""
    if await _token_is_valid(session, existing):
        print(f"onboard: the token in {path} is valid")
        return
    async with websocket(session, token) as call:
        # HA allows one long-lived token per client name, so an old one (its file lost) is removed first.
        for refresh in await call(type="auth/refresh_tokens"):
            if (
                refresh["type"] == LONG_LIVED
                and refresh["client_name"] == TOKEN_CLIENT_NAME
            ):
                await call(
                    type="auth/delete_refresh_token", refresh_token_id=refresh["id"]
                )
                print(f"onboard: removed the old {TOKEN_CLIENT_NAME} token")
        new_token = await call(
            type="auth/long_lived_access_token",
            client_name=TOKEN_CLIENT_NAME,
            lifespan=TOKEN_LIFESPAN_DAYS,
        )
    _write_private(path, f"{new_token}\n")
    print(f"onboard: wrote a new {TOKEN_CLIENT_NAME} token to {path}")


async def _add_entry(session: aiohttp.ClientSession, token: str) -> None:
    """Create the HA Fitness config entry if there is none."""
    headers = {"Authorization": f"Bearer {token}"}
    async with session.get(
        "/api/config/config_entries/entry", params={"domain": DOMAIN}, headers=headers
    ) as response:
        if await _json(response):
            print("onboard: the HA Fitness entry exists")
            return
    async with session.post(
        "/api/config/config_entries/flow", json={"handler": DOMAIN}, headers=headers
    ) as response:
        flow = await _json(response)
    if flow.get("type") == "form":
        async with session.post(
            f"/api/config/config_entries/flow/{flow['flow_id']}",
            json={},
            headers=headers,
        ) as response:
            flow = await _json(response)
    if flow.get("type") == "abort" and flow.get("reason") == "single_instance_allowed":
        print("onboard: the HA Fitness entry exists")
        return
    if flow.get("type") != "create_entry":
        raise OnboardError(f"the HA Fitness config flow ended with {flow}")
    print("onboard: created the HA Fitness entry")


async def _run(base: str, add_entry: bool, token_file: Path) -> None:
    async with aiohttp.ClientSession(base_url=base) as session:
        token = await _onboard(session, base)
        await _set_language(session, token)
        await _keep_token(session, token, token_file)
        if add_entry:
            await _add_entry(session, token)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments and onboard; return 0, 1 when Home Assistant refuses a step, or 2 for a host that isn't local."""
    parser = argparse.ArgumentParser(prog="dev_onboard", description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"Home Assistant URL (default {DEFAULT_URL})"
    )
    parser.add_argument(
        "--no-entry", action="store_true", help="don't create the HA Fitness entry"
    )
    parser.add_argument(
        "--token-file",
        type=Path,
        default=DEFAULT_TOKEN_FILE,
        help="where to keep the dev user's long-lived token (default local/dev-ha-token in the repo)",
    )
    args = parser.parse_args(argv)
    if not is_local_url(args.url):
        print(
            f"onboard: refusing --url {args.url}: the host must be localhost or 127.0.0.1",
            file=sys.stderr,
        )
        return 2
    try:
        asyncio.run(_run(args.url.rstrip("/"), not args.no_entry, args.token_file))
    except (OnboardError, aiohttp.ClientError, OSError) as err:
        print(f"onboard: {err}", file=sys.stderr)
        return 1
    print("onboard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
