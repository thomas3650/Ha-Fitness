"""Tests for the people and reaching Home Assistant (spec §4, §4.1)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from tests.conftest import MakeApp, running

PEOPLE = "/api/v1/people"
CHANGES = "/api/v1/changes"
# A base URL with a path, like the Supervisor's `http://supervisor/core`; the server adds `/api`.
HA_URL = "http://ha.test/core"
TOKEN = "test-token"
STATES = [
    {"entity_id": "person.thomas", "attributes": {"friendly_name": "Thomas"}},
    {"entity_id": "person.elin", "attributes": {"friendly_name": "Elin"}},
    {"entity_id": "light.kitchen", "attributes": {"friendly_name": "Kitchen"}},
]
HA_PERSONS = [
    {"entity_id": "person.thomas", "friendly_name": "Thomas"},
    {"entity_id": "person.elin", "friendly_name": "Elin"},
]
THOMAS = {"name": "Thomas", "person_entity_id": "person.thomas"}
ELIN = {"name": "Elin", "person_entity_id": "person.elin"}


class FakeHa:
    """A fake HA: `GET <HA_URL>/api/states` answers the states and remembers the auth headers; `down` raises ConnectError."""

    def __init__(self) -> None:
        """Start up and reachable."""
        self.down = False
        self.authorizations: list[str | None] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request."""
        if self.down:
            raise httpx.ConnectError("connection refused", request=request)
        if request.method != "GET" or request.url.path != "/core/api/states":
            return httpx.Response(404)
        self.authorizations.append(request.headers.get("authorization"))
        return httpx.Response(200, json=STATES)

    def transport(self) -> httpx.MockTransport:
        """Return the transport to give the app."""
        return httpx.MockTransport(self.handle)


@asynccontextmanager
async def ha_app(
    make_app: MakeApp, ha: FakeHa, **settings: Any
) -> AsyncIterator[httpx.AsyncClient]:
    """Run an app that reaches the fake HA; by default with `HA_URL` and `TOKEN`."""
    settings.setdefault("ha_url", HA_URL)
    if "ha_token_file" not in settings:
        settings.setdefault("ha_token", TOKEN)
    async with running(
        make_app(ha_transport=ha.transport(), **settings)
    ) as http_client:
        yield http_client


async def _put(
    client: httpx.AsyncClient, *people: dict[str, str], **headers: str
) -> httpx.Response:
    """Set the people."""
    return await client.put(PEOPLE, json={"people": list(people)}, headers=headers)


async def test_list_people_shows_ha_persons_only_persons(make_app: MakeApp) -> None:
    """Listing gives the stored people and only the `person.*` entities of HA."""
    async with ha_app(make_app, FakeHa()) as client:
        response = await client.get(PEOPLE)
    assert response.status_code == 200
    assert response.json() == {
        "people": [],
        "ha_persons": HA_PERSONS,
        "ha_error": None,
    }


async def test_set_people_and_keep_ids(make_app: MakeApp) -> None:
    """Setting the same persons in another order keeps their ids and takes the new order."""
    async with ha_app(make_app, FakeHa()) as client:
        first = await _put(client, THOMAS, ELIN)
        assert first.status_code == 200
        ids = {person["person_entity_id"]: person["id"] for person in first.json()}
        second = await _put(client, ELIN, THOMAS)
        assert second.status_code == 200
        listed = (await client.get(PEOPLE)).json()["people"]
    expected = [
        {"id": ids["person.elin"], **ELIN},
        {"id": ids["person.thomas"], **THOMAS},
    ]
    assert second.json() == expected
    assert listed == expected


async def test_set_people_renames_and_removes(make_app: MakeApp) -> None:
    """A kept person takes the new name; a person left out is removed."""
    async with ha_app(make_app, FakeHa()) as client:
        first = (await _put(client, THOMAS, ELIN)).json()
        response = await _put(client, {**ELIN, "name": "  Elin J  "})
        listed = (await client.get(PEOPLE)).json()["people"]
    elin_id = next(p["id"] for p in first if p["person_entity_id"] == "person.elin")
    assert response.status_code == 200
    assert listed == [
        {"id": elin_id, "name": "Elin J", "person_entity_id": "person.elin"}
    ]


@pytest.mark.parametrize(
    ("name", "status"),
    [("", 422), ("   ", 422), ("a" * 41, 422), ("a" * 40, 200), ("a", 200)],
)
async def test_person_name_limits(make_app: MakeApp, name: str, status: int) -> None:
    """A name has 1 to 40 characters after stripping."""
    async with ha_app(make_app, FakeHa()) as client:
        response = await _put(client, {**THOMAS, "name": name})
    assert response.status_code == status


async def test_set_people_rejects_unknown_field(make_app: MakeApp) -> None:
    """A person with a field the API doesn't know is a 422."""
    async with ha_app(make_app, FakeHa()) as client:
        response = await _put(client, {**THOMAS, "colour": "red"})
    assert response.status_code == 422


async def test_set_people_rejects_third_person(make_app: MakeApp) -> None:
    """At most two people."""
    third = {"name": "Guest", "person_entity_id": "person.guest"}
    async with ha_app(make_app, FakeHa()) as client:
        response = await _put(client, THOMAS, ELIN, third)
        listed = (await client.get(PEOPLE)).json()["people"]
    assert response.status_code == 422
    assert "2" in str(response.json()["detail"])
    assert listed == []


async def test_set_people_rejects_duplicate_entity(make_app: MakeApp) -> None:
    """Two people can't share an HA person."""
    async with ha_app(make_app, FakeHa()) as client:
        response = await _put(client, THOMAS, {**THOMAS, "name": "Tom"})
    assert response.status_code == 422
    assert "person.thomas" in str(response.json()["detail"])


async def test_set_people_rejects_non_person_entity(make_app: MakeApp) -> None:
    """An entity that isn't an HA person is a 422 naming it and listing the HA persons; nothing is stored or logged."""
    async with ha_app(make_app, FakeHa()) as client:
        response = await _put(
            client, THOMAS, {"name": "Lamp", "person_entity_id": "light.kitchen"}
        )
        listed = (await client.get(PEOPLE)).json()["people"]
        log = (await client.get(CHANGES)).json()
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["entity_id"] == "light.kitchen"
    assert "light.kitchen" in detail["message"]
    assert detail["ha_persons"] == HA_PERSONS
    assert listed == []
    assert log == []


async def test_set_people_ha_down_is_503_and_read_still_works(
    make_app: MakeApp,
) -> None:
    """With HA unreachable a write is a 503; a read still gives the people, with `ha_error`."""
    ha = FakeHa()
    async with ha_app(make_app, ha) as client:
        stored = (await _put(client, THOMAS)).json()
        ha.down = True
        write = await _put(client, ELIN)
        read = await client.get(PEOPLE)
    assert write.status_code == 503
    assert "Home Assistant" in write.json()["detail"]
    assert read.status_code == 200
    body = read.json()
    assert body["people"] == stored
    assert body["ha_persons"] is None
    assert "Home Assistant" in body["ha_error"]


async def test_ha_error_status_is_503(make_app: MakeApp) -> None:
    """HA answering with an error status counts as unreachable."""

    def handle(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    app = make_app(
        ha_url=HA_URL, ha_token=TOKEN, ha_transport=httpx.MockTransport(handle)
    )
    async with running(app) as client:
        write = await _put(client, THOMAS)
        read = (await client.get(PEOPLE)).json()
    assert write.status_code == 503
    assert read["ha_persons"] is None
    assert "401" in read["ha_error"]


@pytest.mark.parametrize(
    "settings",
    [{}, {"ha_url": HA_URL}, {"ha_token": TOKEN}],
    ids=["nothing", "no-token", "no-url"],
)
async def test_set_people_without_ha_config_is_503(
    make_app: MakeApp, settings: dict[str, str]
) -> None:
    """Without a URL or a token HA isn't configured: a write is a 503 and a read says why."""
    async with running(
        make_app(ha_transport=FakeHa().transport(), **settings)
    ) as client:
        write = await _put(client, THOMAS)
        read = (await client.get(PEOPLE)).json()
    assert write.status_code == 503
    assert "isn't configured" in write.json()["detail"]
    assert read["ha_persons"] is None
    assert "isn't configured" in read["ha_error"]


async def test_token_file_is_read_per_call(make_app: MakeApp, tmp_path: Path) -> None:
    """A token file written after the start is used without a restart."""
    token_file = tmp_path / "secrets" / "ha-token"
    ha = FakeHa()
    async with ha_app(make_app, ha, ha_token_file=token_file) as client:
        before = (await client.get(PEOPLE)).json()
        token_file.parent.mkdir()
        token_file.write_text(f"{TOKEN}\n")
        write = await _put(client, THOMAS)
    assert before["ha_persons"] is None
    assert before["ha_error"]
    assert write.status_code == 200
    assert ha.authorizations == [f"Bearer {TOKEN}"]


async def test_change_log_people_set(make_app: MakeApp) -> None:
    """A successful set logs one `people.set` row naming the people in order, in UTC."""
    async with ha_app(make_app, FakeHa()) as client:
        await _put(client, THOMAS, ELIN, **{"User-Agent": "pytest"})
        log = (await client.get(CHANGES)).json()
    assert len(log) == 1
    entry = log[0]
    assert entry["client"] == "rest:pytest"
    assert entry["action"] == "people.set"
    assert entry["target"] == "people"
    assert entry["summary"] == "Set people: Thomas, Elin"
    assert datetime.fromisoformat(entry["at"]).utcoffset() is not None


async def test_ha_auth_header_is_bearer_token(make_app: MakeApp) -> None:
    """HA is asked with the token as a bearer token."""
    ha = FakeHa()
    async with ha_app(make_app, ha) as client:
        await client.get(PEOPLE)
    assert ha.authorizations == [f"Bearer {TOKEN}"]


@pytest.mark.parametrize(
    "answer",
    [httpx.Response(200, content=b"<html>"), httpx.Response(200, json={"a": 1})],
    ids=["not-json", "not-a-list"],
)
async def test_ha_unexpected_answer_is_503(
    make_app: MakeApp, answer: httpx.Response
) -> None:
    """An answer that isn't a list of states counts as unreachable."""
    transport = httpx.MockTransport(lambda _request: answer)
    app = make_app(ha_url=HA_URL, ha_token=TOKEN, ha_transport=transport)
    async with running(app) as client:
        write = await _put(client, THOMAS)
        read = (await client.get(PEOPLE)).json()
    assert write.status_code == 503
    assert read["ha_persons"] is None
    assert "Home Assistant" in read["ha_error"]


async def test_ha_person_without_friendly_name_uses_entity_id(
    make_app: MakeApp,
) -> None:
    """A person without a friendly name is listed under its entity id."""
    states = [{"entity_id": "person.guest", "attributes": {}}]
    transport = httpx.MockTransport(lambda _request: httpx.Response(200, json=states))
    app = make_app(ha_url=HA_URL, ha_token=TOKEN, ha_transport=transport)
    async with running(app) as client:
        read = (await client.get(PEOPLE)).json()
    assert read["ha_persons"] == [
        {"entity_id": "person.guest", "friendly_name": "person.guest"}
    ]
