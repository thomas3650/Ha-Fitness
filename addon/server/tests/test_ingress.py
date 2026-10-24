"""Tests for the Ingress page (spec §9, D27)."""

import asyncio
from html.parser import HTMLParser
import json
from pathlib import Path
from typing import Any

from ha_fitness_server import __version__
import httpx

from tests.conftest import MakeApp, running

I18N = Path(__file__).parent.parent / "src" / "ha_fitness_server" / "i18n"
HA_URL = "http://ha.test/core"
STATES = [
    {"entity_id": "person.thomas", "attributes": {"friendly_name": "Thomas"}},
    {"entity_id": "person.elin", "attributes": {"friendly_name": "Elin"}},
]
DANISH = "da-DK,da;q=0.9,en;q=0.8"


def _texts(language: str) -> dict[str, str]:
    """Return a language file's texts."""
    texts: dict[str, str] = json.loads((I18N / f"{language}.json").read_text())
    return texts


def _ha(request: httpx.Request) -> httpx.Response:
    """A fake HA that answers its states."""
    return httpx.Response(200, json=STATES)


def _failing_media(request: httpx.Request) -> httpx.Response:
    """A fake media source where every file fails."""
    return httpx.Response(500)


async def _settled(client: httpx.AsyncClient) -> None:
    """Wait until the media download has ended."""
    for _ in range(500):
        response = await client.get("/api/v1/library")
        if response.json()["media"]["state"] in ("done", "failed"):
            return
        await asyncio.sleep(0.01)
    raise AssertionError("the media download didn't end")


async def _page(client: httpx.AsyncClient, **headers: str) -> str:
    """Return the page's HTML."""
    response = await client.get("/", headers=headers)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    return response.text


class _Links(HTMLParser):
    """Collects the `href` and `src` attributes of a page."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.links += [value or "" for name, value in attrs if name in ("href", "src")]


async def test_page_in_english_by_default(make_app: MakeApp) -> None:
    """With no `Accept-Language`, the page is English and shows the version."""
    async with running(make_app()) as client:
        page = await _page(client)
    assert _texts("en")["heading"] in page
    assert _texts("da")["heading"] not in page
    assert __version__ in page
    assert 'name="color-scheme" content="light dark"' in page


async def test_page_in_danish(make_app: MakeApp) -> None:
    """A browser that prefers Danish gets the Danish page."""
    async with running(make_app()) as client:
        page = await _page(client, **{"Accept-Language": DANISH})
    assert _texts("da")["heading"] in page
    assert _texts("en")["heading"] not in page


async def test_language_is_the_highest_q(make_app: MakeApp) -> None:
    """The highest q wins, whatever its position; at equal q the first one does."""
    async with running(make_app()) as client:
        danish = await _page(client, **{"Accept-Language": "en;q=0.5, da;q=0.8"})
        english = await _page(client, **{"Accept-Language": "en, da"})
        odd = await _page(client, **{"Accept-Language": "da;q=x, en;q=0.1"})
    assert _texts("da")["heading"] in danish
    assert _texts("en")["heading"] in english
    assert _texts("en")["heading"] in odd


async def test_page_lists_programs_people_and_media_state(make_app: MakeApp) -> None:
    """The page shows the library, the people and each program's state, weekdays and minutes."""
    texts = _texts("da")
    app = make_app(
        {"ha_url": HA_URL, "ha_token": "test-token"},
        ha_transport=httpx.MockTransport(_ha),
        media_transport=httpx.MockTransport(_failing_media),
    )
    async with running(app) as client:
        await _settled(client)
        people = {
            "people": [
                {"name": "Thomas", "person_entity_id": "person.thomas"},
                {"name": "Elin", "person_entity_id": "person.elin"},
            ]
        }
        assert (await client.put("/api/v1/people", json=people)).status_code == 200
        programs: list[dict[str, Any]] = [
            {
                "name": "Onsdag",
                "weekdays": ["mon", "wed"],
                "stations": [{"exercise": "0001"}],
            },
            {
                "name": "Weekend",
                "active": False,
                "weekdays": ["sat"],
                "stations": [{"exercise": "0001"}],
            },
        ]
        for program in programs:
            response = await client.post("/api/v1/programs", json=program)
            assert response.status_code == 201
        custom = {"name": "Garden squat", "steps": ["Stand up.", "Sit down."]}
        assert (await client.post("/api/v1/exercises", json=custom)).status_code == 201
        library = (await client.get("/api/v1/library")).json()
        page = await _page(client, **{"Accept-Language": DANISH})
    media = library["media"]
    assert f"{media['present']}/{media['total']}" in page
    assert texts["media_failed"] in page
    exercises = library["exercises"]
    assert exercises["custom"] == 1
    assert (
        texts["exercises"].format(
            library=exercises["library"], custom=exercises["custom"]
        )
        in page
    )
    assert "Thomas" in page
    assert "Elin" in page
    assert "Onsdag" in page
    assert "Weekend" in page
    assert texts["on"] in page
    assert texts["off"] in page
    weekdays = [texts["weekday_mon"], texts["weekday_wed"]]
    assert texts["list_separator"].join(weekdays) in page
    assert texts["weekday_sat"] in page
    # One station of 5 rounds: 5 * 60 + 4 * 60 = 540 s, 9 minutes.
    assert texts["minutes"].format(minutes=9) in page


async def test_head_answers_like_get(make_app: MakeApp) -> None:
    """`HEAD /` answers 200 with the page's content type, like `GET /`."""
    async with running(make_app()) as client:
        response = await client.head("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


async def test_page_never_asks_ha(make_app: MakeApp) -> None:
    """The page shows the stored people without a request to HA."""
    calls: list[httpx.Request] = []

    def counting_ha(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return _ha(request)

    app = make_app(
        {"ha_url": HA_URL, "ha_token": "test-token"},
        ha_transport=httpx.MockTransport(counting_ha),
    )
    async with running(app) as client:
        people = {"people": [{"name": "Thomas", "person_entity_id": "person.thomas"}]}
        assert (await client.put("/api/v1/people", json=people)).status_code == 200
        before = len(calls)
        page = await _page(client)
    assert len(calls) == before
    assert "Thomas" in page


async def test_page_without_people_or_programs(make_app: MakeApp) -> None:
    """An empty database says there are no people and no programs."""
    async with running(make_app()) as client:
        page = await _page(client)
    assert _texts("en")["no_people"] in page
    assert _texts("en")["no_programs"] in page


async def test_page_escapes_names(make_app: MakeApp) -> None:
    """A program's name is HTML-escaped."""
    async with running(make_app()) as client:
        program = {
            "name": "<b>x</b>",
            "weekdays": ["wed"],
            "stations": [{"exercise": "0001"}],
        }
        assert (await client.post("/api/v1/programs", json=program)).status_code == 201
        page = await _page(client)
    assert "&lt;b&gt;x&lt;/b&gt;" in page
    assert "<b>x</b>" not in page


def test_language_files_have_the_same_keys() -> None:
    """English and Danish have the same keys, each a non-empty text."""
    english, danish = _texts("en"), _texts("da")
    assert english.keys() == danish.keys()
    for texts in (english, danish):
        assert all(isinstance(text, str) and text for text in texts.values())


async def test_page_links_are_relative(make_app: MakeApp) -> None:
    """The page links somewhere, and only relatively, so it works behind Ingress."""
    async with running(make_app()) as client:
        page = await _page(client)
        parser = _Links()
        parser.feed(page)
        assert parser.links
        for link in parser.links:
            assert not link.startswith(("/", "http")), link
            assert (await client.get(f"/{link}")).status_code == 200, link
