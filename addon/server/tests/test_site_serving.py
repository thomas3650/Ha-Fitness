"""Tests for serving the website (website spec §2.1, §6 Serving): its HTML at `/`, its assets under `/web/`."""

from html.parser import HTMLParser
from pathlib import Path

from ha_fitness_server import __version__
from ha_fitness_server.settings import Settings
from mcp.types import LATEST_PROTOCOL_VERSION
import pytest

from tests.conftest import MakeApp, running

INDEX = '<!DOCTYPE html><html lang="en"><head><script type="module" src="./web/app.js"></script></head></html>'
SCRIPT = "console.log('HA Fitness');\n"
NOT_BUILT = "The HA Fitness website isn't built."


class _Text(HTMLParser):
    """Collects a page's rendered text."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _text(html: str) -> str:
    """Return the text a browser renders from `html`, its parts joined by spaces."""
    parser = _Text()
    parser.feed(html)
    parser.close()
    return " ".join(parser.parts)


def _site(tmp_path: Path) -> Path:
    """Write a built site, `index.html` and `web/app.js`, and return its folder."""
    web_dir = tmp_path / "site"
    (web_dir / "web").mkdir(parents=True)
    (web_dir / "index.html").write_text(INDEX, encoding="utf-8")
    (web_dir / "web" / "app.js").write_text(SCRIPT, encoding="utf-8")
    return web_dir


async def test_root_serves_the_sites_html(make_app: MakeApp, tmp_path: Path) -> None:
    """`GET /` answers the site's `index.html` as HTML that the browser must check again before reuse."""
    async with running(make_app({"web_dir": _site(tmp_path)})) as client:
        response = await client.get("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.text == INDEX


async def test_head_root_answers_like_get(make_app: MakeApp, tmp_path: Path) -> None:
    """`HEAD /` answers 200 with the page's content type and no body."""
    async with running(make_app({"web_dir": _site(tmp_path)})) as client:
        response = await client.head("/")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-cache"
    assert response.content == b""


async def test_root_reads_the_html_on_each_request(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A rebuilt site shows at once, without a restart."""
    web_dir = _site(tmp_path)
    async with running(make_app({"web_dir": web_dir})) as client:
        first = await client.get("/")
        (web_dir / "index.html").write_text("<p>rebuilt</p>", encoding="utf-8")
        second = await client.get("/")
    assert first.text == INDEX
    assert second.text == "<p>rebuilt</p>"


async def test_assets_are_served_under_web(make_app: MakeApp, tmp_path: Path) -> None:
    """A file in the site's `web/` folder is served at `/web/<file>`."""
    async with running(make_app({"web_dir": _site(tmp_path)})) as client:
        response = await client.get("/web/app.js")
    assert response.status_code == 200
    assert response.text == SCRIPT
    assert "javascript" in response.headers["content-type"]


async def test_missing_asset_is_a_json_404(make_app: MakeApp, tmp_path: Path) -> None:
    """A missing asset is FastAPI's JSON 404, not the MCP mount's answer."""
    async with running(make_app({"web_dir": _site(tmp_path)})) as client:
        response = await client.get("/web/missing.js")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


async def test_without_a_site_root_says_it_isnt_built(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """Without a built site, `/` is a short English page with the version, and `/web/…` is a 404."""
    async with running(make_app({"web_dir": tmp_path / "missing"})) as client:
        page = await client.get("/")
        head = await client.head("/")
        asset = await client.get("/web/x")
    assert page.status_code == 200
    assert page.headers["content-type"].startswith("text/html")
    text = _text(page.text)
    assert NOT_BUILT in text
    assert __version__ in text
    assert head.status_code == 200
    assert asset.status_code == 404


async def test_mcp_and_api_still_answer_beside_the_site(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """With a site, `POST /mcp` still answers MCP and an unknown `/api` path is still a JSON 404."""
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "test", "version": "1"},
        },
    }
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    async with running(make_app({"web_dir": _site(tmp_path)})) as client:
        mcp = await client.post("/mcp", json=body, headers=headers)
        unknown = await client.get("/api/x")
    assert mcp.status_code == 200, mcp.text
    assert "HA Fitness" in mcp.text
    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "Not Found"}


def test_web_dir_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """`HA_FITNESS_WEB_DIR` names the site's folder; without it the add-on image's folder is used."""
    monkeypatch.delenv("HA_FITNESS_WEB_DIR", raising=False)
    assert Settings.from_env().web_dir == Path("/opt/ha-fitness/web")
    monkeypatch.setenv("HA_FITNESS_WEB_DIR", "/srv/site")
    assert Settings.from_env().web_dir == Path("/srv/site")
