"""Tests for the speakers and playlists Claude reads from HA (music spec §4.3)."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
from typing import Any

from fastapi import FastAPI
from fastmcp.exceptions import ToolError
import httpx
import pytest

from tests.conftest import MakeApp, running
from tests.test_mcp import McpClient, call, mcp_client
from tests.test_people import HA_URL, TOKEN

MUSIC = "/api/v1/music"
SPEAKERS = "/api/v1/music/speakers"
PLAYLISTS = "/api/v1/music/playlists"
TEMPLATE_PATH = "/core/api/template"
LIBRARY_PATH = "/core/api/services/music_assistant/get_library"
# The speakers template, word for word as checked through the Supervisor's proxy (music spec §4.3).
SPEAKERS_TEMPLATE = """\
{%- set ns = namespace(out=[]) -%}
{%- for e in integration_entities('music_assistant') if e.startswith('media_player.') -%}
{%- set ns.out = ns.out + [{'entity_id': e, 'name': state_attr(e, 'friendly_name') or e, 'state': states(e), 'entry': config_entry_id(e)}] -%}
{%- endfor -%}
{{ ns.out | tojson }}"""

KITCHEN = {
    "entity_id": "media_player.kitchen",
    "name": "Kitchen speaker",
    "state": "idle",
    "entry": "entry-1",
}
GARAGE = {
    "entity_id": "media_player.garage",
    "name": "Garage speaker",
    "state": "unavailable",
    "entry": "entry-1",
}
ATTIC = {
    "entity_id": "media_player.attic",
    "name": "attic speaker",
    "state": "unknown",
    "entry": "entry-1",
}
LIVING = {
    "entity_id": "media_player.living_room",
    "name": "Living room speaker",
    "state": "playing",
    "entry": "entry-1",
}
ITEMS = [
    {
        "media_type": "playlist",
        "uri": "library://playlist/2",
        "name": "Workout Mix",
        "version": "",
        "image": None,
        "favorite": False,
        "explicit": None,
    },
    {
        "media_type": "playlist",
        "uri": "library://playlist/1",
        "name": "cardio Beats",
        "version": "",
        "image": None,
        "favorite": True,
        "explicit": None,
    },
]


class FakeHa:
    """A fake HA that answers the speakers template and `music_assistant.get_library`, and remembers the calls."""

    def __init__(
        self,
        speakers: Any = (),
        items: Any = (),
        *,
        template_text: str | None = None,
        service_response: Any = None,
    ) -> None:
        """Answer `speakers` (as JSON, or `template_text` as it is) and `items` (or `service_response` as it is)."""
        self.template_text = (
            template_text if template_text is not None else json.dumps(list(speakers))
        )
        self.service_response = (
            service_response
            if service_response is not None
            else {
                "items": list(items),
                "limit": 500,
                "offset": 0,
                "order_by": "name",
                "media_type": "playlist",
            }
        )
        self.down = False
        self.library_calls: list[dict[str, Any]] = []
        self.template_calls = 0

    def handle(self, request: httpx.Request) -> httpx.Response:
        """Answer one request; anything but the two expected calls is a 404."""
        if self.down:
            raise httpx.ConnectError(f"refused {TOKEN}", request=request)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        if request.method == "POST" and request.url.path == TEMPLATE_PATH:
            assert json.loads(request.content) == {"template": SPEAKERS_TEMPLATE}
            self.template_calls += 1
            return httpx.Response(200, text=self.template_text)
        if (
            request.method == "POST"
            and request.url.path == LIBRARY_PATH
            and "return_response" in request.url.params
        ):
            self.library_calls.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={"changed_states": [], "service_response": self.service_response},
            )
        return httpx.Response(404)

    def transport(self) -> httpx.MockTransport:
        """Return the transport to give the app."""
        return httpx.MockTransport(self.handle)


def _app(make_app: MakeApp, ha: FakeHa) -> FastAPI:
    """Build an app that reaches the fake HA."""
    return make_app({"ha_url": HA_URL, "ha_token": TOKEN}, ha_transport=ha.transport())


@asynccontextmanager
async def both(
    make_app: MakeApp, ha: FakeHa
) -> AsyncIterator[tuple[httpx.AsyncClient, McpClient]]:
    """Run one app and yield a REST client and an MCP client on it."""
    app = _app(make_app, ha)
    async with mcp_client(app) as session:
        client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        )
        async with client:
            yield client, session


async def test_speakers_sorted_with_availability(make_app: MakeApp) -> None:
    """Speakers come sorted by name, ignoring case; `unavailable` and `unknown` aren't available."""
    expected = [
        {
            "entity_id": "media_player.attic",
            "name": "attic speaker",
            "available": False,
        },
        {
            "entity_id": "media_player.garage",
            "name": "Garage speaker",
            "available": False,
        },
        {
            "entity_id": "media_player.kitchen",
            "name": "Kitchen speaker",
            "available": True,
        },
        {
            "entity_id": "media_player.living_room",
            "name": "Living room speaker",
            "available": True,
        },
    ]
    ha = FakeHa([LIVING, GARAGE, KITCHEN, ATTIC])
    async with both(make_app, ha) as (client, session):
        response = await client.get(SPEAKERS)
        tool = await call(session, "list_speakers")
    assert response.status_code == 200
    assert response.json() == expected
    assert tool == {"result": expected}


async def test_speakers_empty_without_music_assistant(make_app: MakeApp) -> None:
    """With no Music Assistant players the template answers `[]`, and so do the speakers."""
    async with both(make_app, FakeHa([])) as (client, session):
        response = await client.get(SPEAKERS)
        tool = await call(session, "list_speakers")
    assert response.status_code == 200
    assert response.json() == []
    assert tool == {"result": []}


async def test_playlists_from_get_library(make_app: MakeApp) -> None:
    """Playlists come from `get_library` on the first speaker's entry, sorted by name ignoring case."""
    expected = [
        {"name": "cardio Beats", "uri": "library://playlist/1"},
        {"name": "Workout Mix", "uri": "library://playlist/2"},
    ]
    no_entry = {**ATTIC, "entry": None}
    ha = FakeHa([no_entry, {**KITCHEN, "entry": "entry-7"}, LIVING], ITEMS)
    async with both(make_app, ha) as (client, session):
        response = await client.get(PLAYLISTS)
        tool = await call(session, "list_playlists")
    assert response.status_code == 200
    assert response.json() == expected
    assert tool == {"result": expected}
    request = {"config_entry_id": "entry-7", "media_type": "playlist", "limit": 500}
    assert ha.library_calls == [request, request]


async def test_playlists_search_passed_on(make_app: MakeApp) -> None:
    """A search goes to `get_library`; an empty one is no search."""
    ha = FakeHa([KITCHEN], ITEMS[:1])
    async with both(make_app, ha) as (client, session):
        searched = await client.get(PLAYLISTS, params={"search": "work"})
        empty = await client.get(PLAYLISTS, params={"search": ""})
        tool = await call(session, "list_playlists", search="mix")
        empty_tool = await call(session, "list_playlists", search="")
    assert searched.status_code == 200
    assert empty.status_code == 200
    assert tool == {"result": [{"name": "Workout Mix", "uri": "library://playlist/2"}]}
    assert empty_tool == tool
    base = {"config_entry_id": "entry-1", "media_type": "playlist", "limit": 500}
    assert ha.library_calls == [
        {**base, "search": "work"},
        base,
        {**base, "search": "mix"},
        base,
    ]


@pytest.mark.parametrize(
    "speakers",
    [[], [{**KITCHEN, "entry": None}]],
    ids=["no-speakers", "no-entry"],
)
async def test_playlists_empty_without_speakers(
    make_app: MakeApp, speakers: list[dict[str, Any]]
) -> None:
    """Without a speaker that has a config entry, the playlists are `[]` and no service is called."""
    ha = FakeHa(speakers, ITEMS)
    async with both(make_app, ha) as (client, session):
        response = await client.get(PLAYLISTS)
        tool = await call(session, "list_playlists")
    assert response.status_code == 200
    assert response.json() == []
    assert tool == {"result": []}
    assert ha.library_calls == []


@pytest.mark.parametrize(
    ("ha", "path"),
    [
        (FakeHa(template_text="<html>"), SPEAKERS),
        (FakeHa(template_text='{"a": 1}'), SPEAKERS),
        (FakeHa(template_text='[{"entity_id": "media_player.x"}]'), SPEAKERS),
        (FakeHa(template_text="<html>"), PLAYLISTS),
        (FakeHa([KITCHEN], service_response={"limit": 500}), PLAYLISTS),
        (FakeHa([KITCHEN], service_response={"items": [{"uri": "x"}]}), PLAYLISTS),
    ],
    ids=[
        "template-not-json",
        "template-not-a-list",
        "speaker-missing-fields",
        "playlists-template-not-json",
        "no-items",
        "item-without-name",
    ],
)
async def test_music_malformed_answer_is_unavailable(
    make_app: MakeApp, ha: FakeHa, path: str
) -> None:
    """An answer from HA that isn't the expected shape is a 503 over REST and a `ToolError` over MCP."""
    tool = "list_speakers" if path == SPEAKERS else "list_playlists"
    async with both(make_app, ha) as (client, session):
        response = await client.get(path)
        with pytest.raises(ToolError, match="Home Assistant"):
            await session.call_tool(tool, {})
    assert response.status_code == 503
    assert "Home Assistant" in response.json()["detail"]


async def test_music_service_response_not_an_object_is_unavailable(
    make_app: MakeApp,
) -> None:
    """A service call answer without `service_response` is a 503."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path == TEMPLATE_PATH:
            return httpx.Response(200, text=json.dumps([KITCHEN]))
        return httpx.Response(200, json=["changed"])

    app = make_app(
        {"ha_url": HA_URL, "ha_token": TOKEN}, ha_transport=httpx.MockTransport(handle)
    )
    async with running(app) as client:
        response = await client.get(PLAYLISTS)
    assert response.status_code == 503


@pytest.mark.parametrize("path", [SPEAKERS, PLAYLISTS])
async def test_music_ha_down(make_app: MakeApp, path: str) -> None:
    """HA unreachable is a 503 over REST and a `ToolError` over MCP; neither shows the token."""
    ha = FakeHa([KITCHEN], ITEMS)
    ha.down = True
    tool = "list_speakers" if path == SPEAKERS else "list_playlists"
    async with both(make_app, ha) as (client, session):
        response = await client.get(path)
        with pytest.raises(ToolError, match="Home Assistant") as error:
            await session.call_tool(tool, {})
    assert response.status_code == 503
    assert "Home Assistant" in response.json()["detail"]
    assert TOKEN not in response.text
    assert TOKEN not in str(error.value)


@pytest.mark.parametrize("status", [401, 500])
async def test_music_ha_refusing_is_unavailable(make_app: MakeApp, status: int) -> None:
    """HA refusing the template or the service call is a 503 naming the status."""
    seen: list[str] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == TEMPLATE_PATH and len(seen) > 1:
            return httpx.Response(200, text=json.dumps([KITCHEN]))
        return httpx.Response(status)

    app = make_app(
        {"ha_url": HA_URL, "ha_token": TOKEN}, ha_transport=httpx.MockTransport(handle)
    )
    async with running(app) as client:
        template = await client.get(SPEAKERS)
        service = await client.get(PLAYLISTS)
    assert template.status_code == 503
    assert str(status) in template.json()["detail"]
    assert service.status_code == 503
    assert str(status) in service.json()["detail"]
    assert seen == [TEMPLATE_PATH, TEMPLATE_PATH, LIBRARY_PATH]


async def test_music_without_ha_config_is_unavailable(make_app: MakeApp) -> None:
    """Without a URL or a token HA isn't configured: a 503."""
    async with running(make_app({}, ha_transport=FakeHa().transport())) as client:
        response = await client.get(SPEAKERS)
    assert response.status_code == 503
    assert "isn't configured" in response.json()["detail"]


async def test_music_index_route(make_app: MakeApp) -> None:
    """`GET /api/v1/music` names the two routes and never calls HA."""
    ha = FakeHa([KITCHEN], ITEMS)
    ha.down = True
    async with running(_app(make_app, ha)) as client:
        response = await client.get(MUSIC)
    assert response.status_code == 200
    assert response.json() == {"speakers": SPEAKERS, "playlists": PLAYLISTS}
    assert ha.template_calls == 0
