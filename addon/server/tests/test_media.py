"""Tests for the media download and serving (spec §3.2, §3.3)."""

import asyncio
from collections.abc import AsyncIterator, Collection
from pathlib import Path
from typing import Any

import httpx

from tests.conftest import MakeApp, dataset_path, fake_media_bytes, running

LIBRARY = "/api/v1/library"
TOTAL = 1442
TEST_BOUND = 30
GIF_0001_PATH = "videos/0001-2gPfomN.gif"
GIF_0001_NAME = "0001-2gPfomN.gif"


async def _settled_media(client: httpx.AsyncClient) -> dict[str, Any]:
    """Poll `GET /library` until the download has ended; return its media state."""
    while True:
        response = await client.get(LIBRARY)
        assert response.status_code == 200
        media: dict[str, Any] = response.json()["media"]
        if media["state"] in ("done", "failed"):
            return media
        await asyncio.sleep(0.01)


def _source(
    *,
    failing: Collection[str] = (),
    mid_body: Collection[str] = (),
    no_content: Collection[str] = (),
) -> httpx.MockTransport:
    """Return a fake media source.

    It answers 500 for `failing` paths, a broken body for `mid_body`, and 204 for `no_content`.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        path = dataset_path(request)
        if path in failing:
            return httpx.Response(500)
        if path in no_content:
            return httpx.Response(204)
        if path in mid_body:
            return httpx.Response(200, stream=_BrokenStream())
        return httpx.Response(200, content=fake_media_bytes(path))

    return httpx.MockTransport(handler)


class _BrokenStream(httpx.AsyncByteStream):
    """A body that breaks off after the first chunk."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield b"GIF89a-half"
        raise httpx.ReadError("connection lost")


def _media_folder(data_dir: Path) -> Path:
    """Return where the spec keeps the downloaded media."""
    return data_dir / "library" / "media"


async def test_media_downloads_all_and_serves_gif(make_app: MakeApp) -> None:
    """After the download every file is present, and the GIF is served as `image/gif`."""
    async with asyncio.timeout(TEST_BOUND), running(make_app()) as client:
        media = await _settled_media(client)
        assert media == {"state": "done", "present": TOTAL, "total": TOTAL}
        response = await client.get("/api/v1/exercises/0001/gif")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/gif"
        assert response.content == fake_media_bytes(GIF_0001_PATH)


async def test_thumbnail_is_served_as_jpeg(make_app: MakeApp) -> None:
    """The thumbnail is served as `image/jpeg`."""
    async with asyncio.timeout(TEST_BOUND), running(make_app()) as client:
        await _settled_media(client)
        response = await client.get("/api/v1/exercises/0001/thumbnail")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/jpeg"
        assert response.content == fake_media_bytes("images/0001-2gPfomN.jpg")


async def test_media_404_before_download_and_for_custom(make_app: MakeApp) -> None:
    """While nothing is downloaded the media is 404; custom and unknown exercises are 404 too."""
    never = asyncio.Event()

    async def stalled(_request: httpx.Request) -> httpx.Response:
        await never.wait()
        return httpx.Response(200)  # pragma: no cover - never reached

    app = make_app(media_transport=httpx.MockTransport(stalled))
    async with asyncio.timeout(TEST_BOUND), running(app) as client:
        created = await client.post(
            "/api/v1/exercises", json={"name": "Wall sit", "steps": ["Sit."]}
        )
        assert created.status_code == 201
        custom_id = created.json()["id"]
        library = (await client.get(LIBRARY)).json()
        assert library["media"]["present"] == 0
        assert library["media"]["state"] in ("idle", "downloading")
        for path in (
            "/api/v1/exercises/0001/gif",
            "/api/v1/exercises/0001/thumbnail",
            f"/api/v1/exercises/{custom_id}/gif",
            f"/api/v1/exercises/{custom_id}/thumbnail",
            "/api/v1/exercises/9999/gif",
        ):
            assert (await client.get(path)).status_code == 404, path


async def test_custom_exercise_media_is_404_after_download(make_app: MakeApp) -> None:
    """A custom exercise has no media, also once the library media is all there."""
    async with asyncio.timeout(TEST_BOUND), running(make_app()) as client:
        created = await client.post(
            "/api/v1/exercises", json={"name": "Wall sit", "steps": ["Sit."]}
        )
        await _settled_media(client)
        response = await client.get(f"/api/v1/exercises/{created.json()['id']}/gif")
        assert response.status_code == 404


async def test_failed_file_is_retried_next_start(make_app: MakeApp) -> None:
    """A file that failed is missing (`failed`), and the next start fetches it (`done`)."""
    async with asyncio.timeout(TEST_BOUND):
        app = make_app(media_transport=_source(failing={GIF_0001_PATH}))
        async with running(app) as client:
            media = await _settled_media(client)
            assert media == {"state": "failed", "present": TOTAL - 1, "total": TOTAL}
            assert (await client.get("/api/v1/exercises/0001/gif")).status_code == 404
        async with running(make_app(media_transport=_source())) as client:
            media = await _settled_media(client)
            assert media == {"state": "done", "present": TOTAL, "total": TOTAL}
            assert (await client.get("/api/v1/exercises/0001/gif")).status_code == 200


async def test_partial_file_is_not_kept_and_is_fetched_next_start(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A body that breaks off leaves no file under the real name; the next start fetches it."""
    folder = _media_folder(tmp_path)
    async with asyncio.timeout(TEST_BOUND):
        app = make_app(media_transport=_source(mid_body={GIF_0001_PATH}))
        async with running(app) as client:
            media = await _settled_media(client)
            assert media["state"] == "failed"
            assert not (folder / GIF_0001_NAME).exists()
        # A `.part` left by a stopped run is removed at the next start.
        (folder / "0002-Hy9D21L.gif.part").write_bytes(b"stale")
        async with running(make_app(media_transport=_source())) as client:
            media = await _settled_media(client)
            assert media["state"] == "done"
            assert (folder / GIF_0001_NAME).read_bytes() == fake_media_bytes(
                GIF_0001_PATH
            )
        assert list(folder.glob("*.part")) == []


async def test_download_that_cannot_start_is_failed(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """When the media folder can't be made, the download ends `failed` with nothing present."""
    (tmp_path / "library").mkdir()
    _media_folder(tmp_path).write_bytes(b"not a folder")
    async with asyncio.timeout(TEST_BOUND), running(make_app()) as client:
        media = await _settled_media(client)
        assert media == {"state": "failed", "present": 0, "total": TOTAL}


async def test_success_other_than_200_is_a_failed_file(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """Only a 200 counts: a 204 leaves the file missing and the state `failed`."""
    app = make_app(media_transport=_source(no_content={GIF_0001_PATH}))
    async with asyncio.timeout(TEST_BOUND), running(app) as client:
        media = await _settled_media(client)
        assert media == {"state": "failed", "present": TOTAL - 1, "total": TOTAL}
        assert not (_media_folder(tmp_path) / GIF_0001_NAME).exists()


async def test_unexpected_error_on_one_file_does_not_stop_the_others(
    make_app: MakeApp, tmp_path: Path
) -> None:
    """A non-HTTP error on one file leaves only that file missing; every other file is downloaded."""
    healthy = _source()

    async def handler(request: httpx.Request) -> httpx.Response:
        if dataset_path(request) == GIF_0001_PATH:
            raise RuntimeError("the source broke")
        # A real wait, so the other files are still under way when the error comes.
        await asyncio.sleep(0.001)
        return await healthy.handle_async_request(request)

    app = make_app(media_transport=httpx.MockTransport(handler))
    async with asyncio.timeout(TEST_BOUND), running(app) as client:
        media = await _settled_media(client)
        assert media == {"state": "failed", "present": TOTAL - 1, "total": TOTAL}
        assert not (_media_folder(tmp_path) / GIF_0001_NAME).exists()
        thumbnail = await client.get("/api/v1/exercises/0001/thumbnail")
        assert thumbnail.status_code == 200
