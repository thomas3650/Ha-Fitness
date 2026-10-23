"""The library media: downloaded at runtime into the data folder, then served from there (spec §3.2, §3.3).

Each file is stored under its dataset basename in `<data_dir>/library/media/`. A download goes to `<name>.part` and is
renamed only once the whole body arrived, so a stopped download never leaves a half file under the real name.
"""

import asyncio
from collections.abc import Iterable
import logging
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple

import httpx

from ha_fitness_server.schemas import MediaState

type MediaKind = Literal["gif", "thumbnail"]

CONCURRENCY = 8
TIMEOUT_SECONDS = 60
PART_SUFFIX = ".part"

_LOGGER = logging.getLogger(__name__)


class MediaFiles(NamedTuple):
    """A library exercise's media, as dataset paths (`videos/<file>.gif`, `images/<file>.jpg`)."""

    exercise_id: str
    gif: str
    thumbnail: str


def _name(dataset_path: str) -> str:
    """Return the file name a dataset path is stored under."""
    return PurePosixPath(dataset_path).name


class MediaStore:
    """The media folder and the state of its download."""

    def __init__(
        self,
        data_dir: Path,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None,
    ) -> None:
        """Keep where the media lives and where it comes from; `transport` replaces the network in tests."""
        self._folder = data_dir / "library" / "media"
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._state: Literal["idle", "downloading", "done", "failed"] = "idle"
        self._present = 0
        self._total = 0

    def state(self) -> MediaState:
        """Return the download's state with the present and total file counts."""
        return MediaState(state=self._state, present=self._present, total=self._total)

    def path(self, kind: MediaKind, exercise: MediaFiles) -> Path | None:
        """Return the stored file of this kind, or `None` while it isn't there."""
        dataset_path = exercise.gif if kind == "gif" else exercise.thumbnail
        file = self._folder / _name(dataset_path)
        return file if file.is_file() else None

    async def download_missing(self, exercises: Iterable[MediaFiles]) -> None:
        """Remove leftover `.part` files, then download every missing file, 8 at a time.

        A failed file is logged and counted as missing; the state ends `done` if every file is there, else `failed`.
        """
        self._state = "downloading"
        try:
            self._folder.mkdir(parents=True, exist_ok=True)
            for part in self._folder.glob(f"*{PART_SUFFIX}"):
                part.unlink()
            wanted = [path for e in exercises for path in (e.gif, e.thumbnail)]
            self._total = len(wanted)
            missing = [
                path for path in wanted if not (self._folder / _name(path)).is_file()
            ]
            self._present = self._total - len(missing)
            semaphore = asyncio.Semaphore(CONCURRENCY)
            async with httpx.AsyncClient(
                transport=self._transport, timeout=TIMEOUT_SECONDS
            ) as client:
                await asyncio.gather(
                    *(self._fetch(client, semaphore, path) for path in missing)
                )
        except Exception:
            _LOGGER.exception("The media download stopped")
        self._state = "done" if self._present == self._total else "failed"
        if self._state == "failed":
            _LOGGER.warning(
                "%d of %d media files are missing; they are tried again at the next start",
                self._total - self._present,
                self._total,
            )

    async def _fetch(
        self, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, path: str
    ) -> None:
        """Download one file to `<name>.part` and rename it once complete; log a failure."""
        target = self._folder / _name(path)
        part = target.with_name(target.name + PART_SUFFIX)
        async with semaphore:
            try:
                async with client.stream("GET", f"{self._base_url}/{path}") as response:
                    response.raise_for_status()
                    with part.open("wb") as file:
                        async for chunk in response.aiter_bytes():
                            file.write(chunk)
                part.replace(target)
            except (httpx.HTTPError, OSError) as error:
                _LOGGER.warning("Could not download %s: %s", path, error)
                return
            finally:
                part.unlink(missing_ok=True)
            self._present += 1
