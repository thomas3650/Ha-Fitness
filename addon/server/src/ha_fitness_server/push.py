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
    """Holds one bounded queue per subscriber, with an event set when it is dropped; used from the event loop only."""

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._subscribers: dict[asyncio.Queue[Message], asyncio.Event] = {}

    def broadcast(self, message: Message) -> None:
        """Put `message` on every subscriber's queue; with none, it is dropped (fire-and-forget).

        A subscriber whose queue is full has fallen behind: it is dropped and its event set, so its websocket closes
        and the client reconnects to a fresh snapshot.
        """
        for queue, dropped in list(self._subscribers.items()):
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull:
                self._subscribers.pop(queue, None)
                dropped.set()
                _LOGGER.warning(
                    "A push subscriber fell %d messages behind; dropping it",
                    QUEUE_SIZE,
                )

    @asynccontextmanager
    async def subscribe(
        self,
    ) -> AsyncIterator[tuple[asyncio.Queue[Message], asyncio.Event]]:
        """Yield a queue that receives every message broadcast until the block ends, and the event set on a drop.

        Once the event is set the queue gets no more messages.
        """
        queue: asyncio.Queue[Message] = asyncio.Queue(maxsize=QUEUE_SIZE)
        dropped = asyncio.Event()
        self._subscribers[queue] = dropped
        try:
            yield queue, dropped
        finally:
            self._subscribers.pop(queue, None)
