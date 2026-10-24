"""The push hub (step 4 spec §3.6): fans each message out to every connected websocket."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

type Message = dict[str, Any]


class Hub:
    """Holds one queue per subscriber; used from the event loop only."""

    def __init__(self) -> None:
        """Start with no subscribers."""
        self._queues: set[asyncio.Queue[Message]] = set()

    def broadcast(self, message: Message) -> None:
        """Put `message` on every subscriber's queue; with none, it is dropped (fire-and-forget)."""
        for queue in self._queues:
            queue.put_nowait(message)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[Message]]:
        """Yield a queue that receives every message broadcast until the block ends."""
        queue: asyncio.Queue[Message] = asyncio.Queue()
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)
