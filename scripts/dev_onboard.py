"""Onboard a fresh dev Home Assistant and add the HA Fitness entry; safe to run again.

Usage: `uv run python scripts/dev_onboard.py [--url URL] [--no-entry]`

- Completes onboarding through HA's onboarding API with the user `dev` / password `dev` (dev only).
- Sets that user's frontend language to Danish (`frontend/set_user_data`, key `language`); onboarding's
  `language` field only names the default areas.
- Unless `--no-entry`, creates the HA Fitness config entry.

Every step that is already done is skipped, so a second run changes nothing.
"""

import argparse
import asyncio
from collections.abc import Sequence
import sys
from typing import Any

import aiohttp

DEFAULT_URL = "http://localhost:8123"
NAME = "dev"
USERNAME = "dev"
PASSWORD = "dev"  # A local dev instance only; never a real Home Assistant.
DOMAIN = "ha_fitness"
# The frontend saves the language as its locale settings; the rest follow the language.
LANGUAGE = {
    "language": "da",
    "number_format": "language",
    "time_format": "language",
    "date_format": "language",
    "time_zone": "local",
    "first_weekday": "language",
}


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


async def _onboard(session: aiohttp.ClientSession, base: str) -> str:
    """Finish the onboarding steps that aren't done; return an access token for the dev user."""
    client_id = f"{base}/"
    redirect_uri = f"{base}/?auth_callback=1"
    async with session.get("/api/onboarding") as response:
        done = {step["step"] for step in await _json(response) if step["done"]}

    if "user" in done:
        token = await _token(
            session, client_id, await _login(session, client_id, redirect_uri)
        )
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
    async with session.ws_connect("/api/websocket") as ws:
        await ws.receive_json()  # auth_required
        await ws.send_json({"type": "auth", "access_token": token})
        auth = await ws.receive_json()
        if auth.get("type") != "auth_ok":
            raise OnboardError(f"websocket auth failed: {auth}")

        async def call(msg_id: int, **message: Any) -> Any:
            await ws.send_json({"id": msg_id, **message})
            while True:
                reply = await ws.receive_json()
                if reply.get("id") == msg_id:
                    break
            if not reply.get("success"):
                raise OnboardError(f"{message['type']} failed: {reply.get('error')}")
            return reply.get("result")

        current = await call(1, type="frontend/get_user_data", key="language")
        if current.get("value") != LANGUAGE:
            await call(2, type="frontend/set_user_data", key="language", value=LANGUAGE)
            print("onboard: set the frontend language to Danish")
        stored = await call(3, type="frontend/get_user_data", key="language")
        print(f"onboard: frontend language is {stored.get('value')}")


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


async def _run(base: str, add_entry: bool) -> None:
    async with aiohttp.ClientSession(base_url=base) as session:
        token = await _onboard(session, base)
        await _set_language(session, token)
        if add_entry:
            await _add_entry(session, token)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments and onboard; return 0, or 1 when Home Assistant refuses a step."""
    parser = argparse.ArgumentParser(prog="dev_onboard", description=__doc__)
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"Home Assistant URL (default {DEFAULT_URL})"
    )
    parser.add_argument(
        "--no-entry", action="store_true", help="don't create the HA Fitness entry"
    )
    args = parser.parse_args(argv)
    try:
        asyncio.run(_run(args.url.rstrip("/"), not args.no_entry))
    except (OnboardError, aiohttp.ClientError) as err:
        print(f"onboard: {err}", file=sys.stderr)
        return 1
    print("onboard: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
