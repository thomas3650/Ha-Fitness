"""Tests for the media proxy: an exercise's GIF or thumbnail from the add-on, behind HA's login."""

from collections.abc import AsyncGenerator
import socket

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

from custom_components.ha_fitness.const import DOMAIN

from .common import set_up, unload
from .fake_addon import FakeAddon

GIF = b"GIF89a-not-really"
JPEG = b"\xff\xd8\xff-not-really"


def _url(exercise_id: str, kind: str) -> str:
    return f"/api/ha_fitness/media/{exercise_id}/{kind}"


@pytest.fixture
async def loaded(
    hass: HomeAssistant, fake_addon: FakeAddon, config_entry: MockConfigEntry
) -> AsyncGenerator[FakeAddon]:
    """The entry set up against the fake, which holds one library and one custom file."""
    fake_addon.media[("0001", "gif")] = (GIF, "image/gif")
    fake_addon.media[("custom-12", "thumbnail")] = (JPEG, "image/jpeg")
    await set_up(hass, config_entry)
    yield fake_addon
    await unload(hass, config_entry)


@pytest.mark.usefixtures("cards_bundle")
async def test_media_requires_auth(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator, loaded: FakeAddon
) -> None:
    """Without a login the proxy answers 401 and asks the add-on nothing."""
    client = await hass_client_no_auth()

    response = await client.get(_url("0001", "gif"))

    assert response.status == 401
    assert loaded.media_requests == []


@pytest.mark.usefixtures("cards_bundle")
@pytest.mark.parametrize(
    ("exercise_id", "kind", "status"),
    [
        ("001", "gif", 404),
        ("12345", "gif", 404),
        ("abcd", "gif", 404),
        ("custom-0", "gif", 404),
        ("custom-012", "gif", 404),
        ("custom-", "gif", 404),
        ("%D9%A1%D9%A2%D9%A3%D9%A4", "gif", 404),  # four Arabic-Indic digits
        ("0001", "video", 404),
        ("0001", "GIF", 404),
        # Home Assistant's own request filter answers these 400 before any view runs.
        ("0001%0A", "gif", 400),
        ("..%2Fhealth", "gif", 400),
        ("0001", "gif%0A", 400),
    ],
)
async def test_media_rejects_bad_id_or_kind_without_relay(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    loaded: FakeAddon,
    exercise_id: str,
    kind: str,
    status: int,
) -> None:
    """An id or kind outside the patterns gives 404, and nothing reaches the add-on."""
    client = await hass_client()

    response = await client.get(_url(exercise_id, kind))

    assert response.status == status
    assert loaded.media_requests == []


@pytest.mark.usefixtures("cards_bundle")
async def test_media_relays_bytes_and_cache_header(
    hass: HomeAssistant, hass_client: ClientSessionGenerator, loaded: FakeAddon
) -> None:
    """The add-on's bytes and content type come through, privately cached for a day."""
    client = await hass_client()

    for exercise_id, kind, body, content_type in (
        ("0001", "gif", GIF, "image/gif"),
        ("custom-12", "thumbnail", JPEG, "image/jpeg"),
    ):
        response = await client.get(_url(exercise_id, kind))
        assert response.status == 200
        assert await response.read() == body
        assert response.headers["Content-Type"] == content_type
        assert response.headers["Cache-Control"] == "private, max-age=86400"
    assert loaded.media_requests == [("0001", "gif"), ("custom-12", "thumbnail")]


def _closed_port() -> int:
    """Return a port on 127.0.0.1 that nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


@pytest.mark.usefixtures("cards_bundle")
async def test_media_404_and_503(
    hass: HomeAssistant,
    hass_client: ClientSessionGenerator,
    fake_addon: FakeAddon,
    config_entry: MockConfigEntry,
) -> None:
    """A file the add-on doesn't have stays 404; a failing or unreachable add-on, or no entry, is 503."""
    await set_up(hass, config_entry)
    client = await hass_client()
    response = await client.get(_url("0002", "gif"))
    assert response.status == 404
    assert fake_addon.media_requests == [("0002", "gif")]
    # An add-on that fails to serve the file is as good as unreachable.
    fake_addon.media_status = 500
    assert (await client.get(_url("0002", "gif"))).status == 503

    # No entry is loaded: there is no add-on to ask.
    await unload(hass, config_entry)
    assert (await client.get(_url("0001", "gif"))).status == 503

    dead = MockConfigEntry(
        domain=DOMAIN,
        title="HA Fitness",
        data={"url": f"http://127.0.0.1:{_closed_port()}"},
        unique_id="ha_fitness_dead",
        version=2,
    )
    dead.add_to_hass(hass)
    await set_up(hass, dead)
    assert (await client.get(_url("0001", "gif"))).status == 503
    await unload(hass, dead)
