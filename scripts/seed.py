"""Seed a dev Home Assistant and a dev add-on server with people and a sample program; safe to run again.

Usage: `scripts/seed [--ha-url URL] [--server-url URL]` (defaults http://localhost:8123 and http://localhost:8765)

- Refuses unless both hosts are `localhost` or `127.0.0.1`, before any request: it never touches a real Home
  Assistant or a real add-on.
- Logs in to Home Assistant as the dev user (`dev` / `dev`, as `dev_onboard.py` does), so it works for the fast loop
  and for the full loop (`--ha-url http://localhost:7123`).
- Creates the HA persons "Thomas" and "Elin" over the websocket (`person/create`) unless a person of that name
  exists, and finds their entity ids through the entity registry.
- Sets them as the people on the server (`PUT /api/v1/people`) unless the server has exactly those people already.
- Creates the program "Sample" (Wednesday, 5 body-weight stations) unless a program of that name exists.

A second run changes nothing.
"""

import argparse
import asyncio
from collections.abc import Sequence
import sys
import time
from typing import Any
from urllib.parse import urlsplit

import aiohttp

from scripts.dev_onboard import OnboardError, login, websocket

DEFAULT_HA_URL = "http://localhost:8123"
DEFAULT_SERVER_URL = "http://localhost:8765"
LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})
USER_AGENT = "ha-fitness-seed"
PERSONS = ("Thomas", "Elin")
WAIT_SECONDS = 10.0
# Body-weight exercises from the built-in library, by id: push-up, jump squat, mountain climber, walking lunge,
# burpee.
SAMPLE_NAME = "Sample"
SAMPLE: dict[str, Any] = {
    "name": SAMPLE_NAME,
    "weekdays": ["wed"],
    "stations": [
        {"exercise": exercise} for exercise in ("0662", "0514", "0630", "1460", "1160")
    ],
}


class SeedError(Exception):
    """Something answered what this script can't continue from."""


def _is_local(url: str) -> bool:
    """Whether the URL's host is exactly `localhost` or `127.0.0.1`."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return False
    return host in LOCAL_HOSTS


async def _json(response: aiohttp.ClientResponse) -> Any:
    """Return the JSON body (None when empty), or raise with the method, path, status and text."""
    if response.status >= 400:
        raise SeedError(
            f"{response.method} {response.url.path}: {response.status} {await response.text()}"
        )
    if response.status == 204:
        return None
    return await response.json()


async def _ha_persons(ha_url: str) -> list[dict[str, str]]:
    """Make sure the HA persons exist; return `[{name, person_entity_id}]` in `PERSONS` order."""
    async with aiohttp.ClientSession(base_url=ha_url) as session:
        token = await login(session, ha_url)
        async with websocket(session, token) as call:
            listed = await call(type="person/list")
            by_name = {
                person["name"]: person
                for person in [*listed["config"], *listed["storage"]]
            }
            for name in PERSONS:
                if name in by_name:
                    print(f"seed: the HA person {name} exists")
                    continue
                by_name[name] = await call(type="person/create", name=name)
                print(f"seed: created the HA person {name}")
            ids = {name: by_name[name]["id"] for name in PERSONS}

            # A new person's entity takes a moment to be registered and get a state; the server checks the states.
            deadline = time.monotonic() + WAIT_SECONDS
            while True:
                registry = await call(type="config/entity_registry/list")
                entity_ids = {
                    entry["unique_id"]: entry["entity_id"]
                    for entry in registry
                    if entry["platform"] == "person"
                }
                found = {
                    name: entity_ids[ids[name]]
                    for name in PERSONS
                    if ids[name] in entity_ids
                }
                if len(found) == len(PERSONS):
                    states = await call(type="get_states")
                    with_state = {state["entity_id"] for state in states}
                    if all(entity_id in with_state for entity_id in found.values()):
                        break
                if time.monotonic() > deadline:
                    missing = [name for name in PERSONS if name not in found]
                    raise SeedError(
                        f"the person entities didn't appear within {WAIT_SECONDS:.0f} s"
                        + (f" (missing: {', '.join(missing)})" if missing else "")
                    )
                await asyncio.sleep(0.5)
    return [{"name": name, "person_entity_id": found[name]} for name in PERSONS]


async def _seed_server(server_url: str, people: list[dict[str, str]]) -> None:
    """Set the people and create the sample program on the server, unless they are there."""
    headers = {"User-Agent": USER_AGENT}
    async with aiohttp.ClientSession(base_url=server_url, headers=headers) as session:
        async with session.get("/api/v1/people") as response:
            view = await _json(response)
        stored = [
            {"name": person["name"], "person_entity_id": person["person_entity_id"]}
            for person in view["people"]
        ]
        if stored == people:
            print("seed: the people are set")
        else:
            async with session.put(
                "/api/v1/people", json={"people": people}
            ) as response:
                if response.status == 503:
                    raise SeedError(
                        "the server can't reach Home Assistant (503); run scripts/dev_onboard.py so it has a token, "
                        f"then seed again: {await response.text()}"
                    )
                await _json(response)
            names = ", ".join(person["name"] for person in people)
            print(f"seed: set the people {names}")

        async with session.get("/api/v1/programs") as response:
            programs = await _json(response)
        if any(
            program["program"]["name"].casefold() == SAMPLE_NAME.casefold()
            for program in programs
        ):
            print(f"seed: the program {SAMPLE_NAME} exists")
        else:
            async with session.post("/api/v1/programs", json=SAMPLE) as response:
                await _json(response)
            print(f"seed: created the program {SAMPLE_NAME}")


async def _run(ha_url: str, server_url: str) -> None:
    people = await _ha_persons(ha_url)
    await _seed_server(server_url, people)


def main(argv: Sequence[str] | None = None) -> int:
    """Parse the arguments and seed; return 0, 1 when a step fails, or 2 for a host that isn't local."""
    parser = argparse.ArgumentParser(prog="seed", description=__doc__)
    parser.add_argument(
        "--ha-url",
        default=DEFAULT_HA_URL,
        help=f"dev Home Assistant URL (default {DEFAULT_HA_URL})",
    )
    parser.add_argument(
        "--server-url",
        default=DEFAULT_SERVER_URL,
        help=f"dev add-on server URL (default {DEFAULT_SERVER_URL})",
    )
    args = parser.parse_args(argv)
    for option, url in (("--ha-url", args.ha_url), ("--server-url", args.server_url)):
        if not _is_local(url):
            print(
                f"seed: refusing {option} {url}: the host must be localhost or 127.0.0.1",
                file=sys.stderr,
            )
            return 2
    try:
        asyncio.run(_run(args.ha_url.rstrip("/"), args.server_url.rstrip("/")))
    except (SeedError, OnboardError, aiohttp.ClientError) as err:
        print(f"seed: {err}", file=sys.stderr)
        return 1
    print("seed: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
