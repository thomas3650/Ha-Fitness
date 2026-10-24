"""Seed a dev Home Assistant and a dev add-on server with people and a sample program; safe to run again.

Usage: `scripts/seed [--ha-url URL] [--server-url URL] [--today | --late | --short]` (defaults http://localhost:8123 and
http://localhost:8765)

- Refuses unless both hosts are `localhost` or `127.0.0.1`, before any request: it never touches a real Home
  Assistant or a real add-on.
- Logs in to Home Assistant as the dev user (`dev` / `dev`, as `dev_onboard.py` does), so it works for the fast loop
  and for the full loop (`--ha-url http://localhost:7123`).
- Creates the HA persons "Thomas" and "Elin" over the websocket (`person/create`) unless a person of that name
  exists, and finds their entity ids through the entity registry.
- Sets them as the people on the server (`PUT /api/v1/people`) unless the server has exactly those people already.
- Creates the program "Sample" (Wednesday, 5 body-weight stations, music on the fake Music Assistant's living-room
  player) unless a program of that name exists. A Sample without music gets Sample's music, with the rest of its
  document kept.

A second run changes nothing.

Three flags then make a training day on purpose, through the add-on's dev routes (`HA_FITNESS_DEV=1`, which
`scripts/develop` sets). "Today" is the date in Europe/Copenhagen, the dev HA's zone.

- Each flag first checks that the server has its dev routes, before anything changes, and refuse when it hasn't.
- `--today` adds today's weekday to Sample, switches Sample on when it is off, and creates or reopens its day for
  today, so it is due at once, also after a skip earlier that day.
- `--late` makes Sample late. It first refuses when another active program trains today, before it changes anything
  (also before the persons, people and Sample above). Then it switches Sample off (which removes its open days), sets
  its weekdays to every day except today, removes every training day of today (any day today, closed ones included,
  would close the late one), switches Sample on, and creates or reopens its day for yesterday.
- `--short` is for a short real run of the workout: it creates the program "Kort" (2 body-weight stations, 1 round,
  work 10 s, switch 0 s, countdown 5 s) with today's weekday only, or, when Kort exists, sets its weekdays to today's
  only and switches it on. Then it creates or reopens Kort's day for today. Kort's day for today closes an earlier
  late day as missed, and makes `--late` refuse on that weekday.
"""

import argparse
import asyncio
from collections.abc import Sequence
import datetime as dt
import sys
import time
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from scripts.dev_onboard import TIMEZONE, OnboardError, is_local_url, login, websocket

DEFAULT_HA_URL = "http://localhost:8123"
DEFAULT_SERVER_URL = "http://localhost:8765"
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
    # A playlist and a player of the fake Music Assistant (`scripts/dev/fake_music_assistant/`).
    "music": {
        "playlist": "library://playlist/1",
        "playlist_name": "Workout Mix",
        "speaker": "media_player.fake_living_room",
        "volume": 30,
        "shuffle": False,
    },
}
# Push-up and jump squat; the weekdays are set to today's when Kort is created.
SHORT_NAME = "Kort"
SHORT: dict[str, Any] = {
    "name": SHORT_NAME,
    "rounds": 1,
    "work_seconds": 10,
    "switch_seconds": 0,
    "round_rest_seconds": 0,
    "countdown_seconds": 5,
    "stations": [{"exercise": exercise} for exercise in ("0662", "0514")],
}


# The add-on's weekday keys, Monday first (`date.weekday()` order).
WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


class SeedError(Exception):
    """Something answered what this script can't continue from."""


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
    async with _server_session(server_url) as session:
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

        sample = await _find_program(session, SAMPLE_NAME)
        if sample is None:
            async with session.post("/api/v1/programs", json=SAMPLE) as response:
                await _json(response)
            print(f"seed: created the program {SAMPLE_NAME}")
        elif sample["program"]["music"] is None:
            await _put_program(
                session, sample["id"], {**sample["program"], "music": SAMPLE["music"]}
            )
            print(f"seed: gave the program {SAMPLE_NAME} its music")
        else:
            print(f"seed: the program {SAMPLE_NAME} exists")


def _local_today() -> dt.date:
    """Today's date in the dev HA's zone."""
    return dt.datetime.now(ZoneInfo(TIMEZONE)).date()


def _server_session(server_url: str) -> aiohttp.ClientSession:
    """A session for the server; the server takes the client name of the change log from the User-Agent."""
    return aiohttp.ClientSession(
        base_url=server_url, headers={"User-Agent": USER_AGENT}
    )


async def _refuse_late(server_url: str, today: dt.date) -> None:
    """Raise when another active program trains today: its day of today would close Sample's late day."""
    weekday = WEEKDAYS[today.weekday()]
    async with (
        _server_session(server_url) as session,
        session.get("/api/v1/programs") as response,
    ):
        programs = await _json(response)
    others = [
        program["program"]["name"]
        for program in programs
        if program["program"]["active"]
        and weekday in program["program"]["weekdays"]
        and program["program"]["name"].casefold() != SAMPLE_NAME.casefold()
    ]
    if others:
        raise SeedError(
            f"refusing --late: the active program {', '.join(others)} trains today ({weekday}); "
            "switch it off first, then seed again"
        )


async def _find_program(
    session: aiohttp.ClientSession, name: str
) -> dict[str, Any] | None:
    """Return the stored program of that name (`{id, program, ...}`), or None."""
    async with session.get("/api/v1/programs") as response:
        programs = await _json(response)
    for program in programs:
        if program["program"]["name"].casefold() == name.casefold():
            return dict(program)
    return None


async def _sample(session: aiohttp.ClientSession) -> dict[str, Any]:
    """Return the stored Sample program (`{id, program, ...}`)."""
    sample = await _find_program(session, SAMPLE_NAME)
    if sample is None:
        raise SeedError(f"the program {SAMPLE_NAME} is missing")
    return sample


async def _put_program(
    session: aiohttp.ClientSession, program_id: int, document: dict[str, Any]
) -> dict[str, Any]:
    """Replace a program's document; return the stored program."""
    async with session.put(f"/api/v1/programs/{program_id}", json=document) as response:
        return dict(await _json(response))


async def _set_active(
    session: aiohttp.ClientSession, program_id: int, active: bool
) -> dict[str, Any]:
    """Switch a program on or off; return the stored program."""
    async with session.put(
        f"/api/v1/programs/{program_id}/active", json={"active": active}
    ) as response:
        return dict(await _json(response))


async def _dev_json(response: aiohttp.ClientResponse) -> Any:
    """`_json` for a dev route; a 404 most likely means the server runs without its dev routes."""
    if response.status == 404:
        raise SeedError(
            f"{response.method} {response.url.path}: 404 {await response.text()}; the dev routes need "
            "HA_FITNESS_DEV=1 on the server (scripts/develop sets it)"
        )
    return await _json(response)


async def _open_day(
    session: aiohttp.ClientSession, program_id: int, day: dt.date
) -> None:
    """Create or reopen the program's training day of `day` (dev route)."""
    async with session.post(
        "/api/v1/dev/training-days",
        json={"program_id": program_id, "date": day.isoformat()},
    ) as response:
        await _dev_json(response)


async def _delete_days(session: aiohttp.ClientSession, day: dt.date) -> None:
    """Remove every training day of `day`, open or closed (dev route)."""
    async with session.delete(
        "/api/v1/dev/training-days", params={"date": day.isoformat()}
    ) as response:
        await _dev_json(response)


async def _require_dev_routes(server_url: str) -> None:
    """Raise unless the server has its dev routes: an empty POST is a 422 there, and a 404 without them."""
    async with (
        _server_session(server_url) as session,
        session.post("/api/v1/dev/training-days", json={}) as response,
    ):
        if response.status == 422:
            return
        if response.status == 404:
            raise SeedError(
                "refusing: the server has no dev routes (POST /api/v1/dev/training-days is a 404); "
                "start it with HA_FITNESS_DEV=1 (scripts/develop sets it), then seed again"
            )
        raise SeedError(
            f"POST /api/v1/dev/training-days with an empty body: expected 422, got {response.status} "
            f"{await response.text()}"
        )


async def _make_due(server_url: str, today: dt.date) -> None:
    """Add today's weekday to Sample, switch it on when it is off, and create or reopen its day for today."""
    weekday = WEEKDAYS[today.weekday()]
    async with _server_session(server_url) as session:
        sample = await _sample(session)
        document = sample["program"]
        if weekday in document["weekdays"]:
            print(f"seed: {SAMPLE_NAME} trains on {weekday}")
        else:
            await _put_program(
                session,
                sample["id"],
                {**document, "weekdays": [*document["weekdays"], weekday]},
            )
            print(f"seed: added {weekday} to {SAMPLE_NAME}")
        if not document["active"]:
            await _set_active(session, sample["id"], True)
            print(f"seed: switched {SAMPLE_NAME} on")
        await _open_day(session, sample["id"], today)
        print(f"seed: {SAMPLE_NAME} has an open day for today ({today})")


async def _make_late(server_url: str, today: dt.date) -> None:
    """Make Sample late: off, every weekday but today's, no day today, on, and an open day for yesterday."""
    weekday = WEEKDAYS[today.weekday()]
    yesterday = today - dt.timedelta(days=1)
    async with _server_session(server_url) as session:
        sample = await _sample(session)
        program_id = sample["id"]
        off = await _set_active(session, program_id, False)
        print(f"seed: switched {SAMPLE_NAME} off")
        # From the switched-off document: `active` must stay false here (the document's default is true).
        document = {
            **off["program"],
            "active": False,
            "weekdays": [day for day in WEEKDAYS if day != weekday],
        }
        await _put_program(session, program_id, document)
        print(f"seed: {SAMPLE_NAME} trains every day except {weekday}")
        await _delete_days(session, today)
        print(f"seed: removed every training day of today ({today})")
        await _set_active(session, program_id, True)
        print(f"seed: switched {SAMPLE_NAME} on")
        await _open_day(session, program_id, yesterday)
        print(f"seed: {SAMPLE_NAME} has an open day for yesterday ({yesterday})")


async def _make_short(server_url: str, today: dt.date) -> None:
    """Create Kort for today's weekday, or set its weekdays to today's and switch it on; then open its day for today."""
    weekday = WEEKDAYS[today.weekday()]
    async with _server_session(server_url) as session:
        short = await _find_program(session, SHORT_NAME)
        if short is None:
            async with session.post(
                "/api/v1/programs", json={**SHORT, "weekdays": [weekday]}
            ) as response:
                short = dict(await _json(response))
            print(f"seed: created the program {SHORT_NAME} for {weekday}")
        else:
            document = short["program"]
            if document["weekdays"] == [weekday]:
                print(f"seed: {SHORT_NAME} trains on {weekday} only")
            else:
                # The stored `active` goes along, so a switched-off Kort stays off until the switch below.
                await _put_program(
                    session, short["id"], {**document, "weekdays": [weekday]}
                )
                print(f"seed: set {SHORT_NAME}'s weekdays to {weekday} only")
            if not document["active"]:
                await _set_active(session, short["id"], True)
                print(f"seed: switched {SHORT_NAME} on")
        await _open_day(session, short["id"], today)
        print(f"seed: {SHORT_NAME} has an open day for today ({today})")


async def _run(ha_url: str, server_url: str, mode: str | None) -> None:
    today = _local_today()
    if mode is not None:
        await _require_dev_routes(server_url)
    if mode == "late":
        await _refuse_late(server_url, today)
    people = await _ha_persons(ha_url)
    await _seed_server(server_url, people)
    if mode == "today":
        await _make_due(server_url, today)
    elif mode == "late":
        await _make_late(server_url, today)
    elif mode == "short":
        await _make_short(server_url, today)


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
    when = parser.add_mutually_exclusive_group()
    when.add_argument(
        "--today",
        dest="mode",
        action="store_const",
        const="today",
        help="then make Sample due today",
    )
    when.add_argument(
        "--late",
        dest="mode",
        action="store_const",
        const="late",
        help="then make Sample late (refuses when another active program trains today)",
    )
    when.add_argument(
        "--short",
        dest="mode",
        action="store_const",
        const="short",
        help="then make the short program Kort due today (1 round, work 10 s, 2 stations)",
    )
    args = parser.parse_args(argv)
    for option, url in (("--ha-url", args.ha_url), ("--server-url", args.server_url)):
        if not is_local_url(url):
            print(
                f"seed: refusing {option} {url}: the host must be localhost or 127.0.0.1",
                file=sys.stderr,
            )
            return 2
    try:
        asyncio.run(
            _run(args.ha_url.rstrip("/"), args.server_url.rstrip("/"), args.mode)
        )
    except (SeedError, OnboardError, aiohttp.ClientError) as err:
        print(f"seed: {err}", file=sys.stderr)
        return 1
    print("seed: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
