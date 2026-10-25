"""The push hub (step 4 spec §3.6): fans each message out to every connected websocket."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import logging
from typing import Any

type Message = dict[str, Any]

QUEUE_SIZE = 100

_LOGGER = logging.getLogger(__name__)


class Hub:
    """Holds one queue per subscriber, with an event set when it is dropped; used from the event loop only.

    A queue has no size limit of its own. A subscriber is dropped when a batch arrives while its backlog is already
    `QUEUE_SIZE` or more, so a queue holds at most `QUEUE_SIZE` messages plus one batch.
    """

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._subscribers: dict[asyncio.Queue[Message], asyncio.Event] = {}

    def broadcast(self, messages: list[Message]) -> None:
        """Put the batch `messages` on every subscriber's queue, in order; with none, it is dropped (fire-and-forget).

        A batch is one publish, so a burst (a catch-up's events) is queued whole. A subscriber whose backlog is
        already `QUEUE_SIZE` or more has fallen behind: it is dropped and its event set, so its websocket closes and
        the client reconnects to a fresh snapshot. An empty batch changes nothing.
        """
        if not messages:
            return
        for queue, dropped in list(self._subscribers.items()):
            if queue.qsize() >= QUEUE_SIZE:
                self._subscribers.pop(queue, None)
                dropped.set()
                _LOGGER.warning(
                    "A push subscriber fell %d messages behind; dropping it",
                    QUEUE_SIZE,
                )
                continue
            for message in messages:
                queue.put_nowait(message)

    @asynccontextmanager
    async def subscribe(
        self,
    ) -> AsyncIterator[tuple[asyncio.Queue[Message], asyncio.Event]]:
        """Yield a queue that receives every message broadcast until the block ends, and the event set on a drop.

        Once the event is set the queue gets no more messages.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue()
        dropped = asyncio.Event()
        self._subscribers[queue] = dropped
        try:
            yield queue, dropped
        finally:
            self._subscribers.pop(queue, None)
