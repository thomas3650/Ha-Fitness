"""The push channel `GET /api/v1/ws` (step 4 spec §3.6)."""

import asyncio
from contextlib import suppress
from datetime import date
from typing import Any

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, status

from ha_fitness_server import API_VERSION, __version__
from ha_fitness_server.errors import Unavailable
from ha_fitness_server.push import Hub, Message
from ha_fitness_server.services import Services, ServicesHolder

router = APIRouter()


@router.websocket("/ws")
async def push_channel(websocket: WebSocket) -> None:
    """Send `hello`, `today`, `session` and `stats`, then every message the hub broadcasts; the client sends nothing.

    It subscribes before it builds the snapshots, so nothing published meanwhile is lost. Every publish runs under the
    training days' lock, so the queue holds them in lock order. A `today` can be queued after the snapshot was built
    (a skip, a write or a tick in the gap before the drain), and `_publish_today` won't send that view again. So when
    the drain holds a `today`, the last one is the newest view and is sent instead of the snapshot. Otherwise the
    snapshot is the newest: a later change would have queued a `today`. `session` works the same way: every change of
    the session publishes one, and reading the snapshot can tick. So does `stats`: every change that can move them
    checks them and publishes them if they changed. The snapshot ticks the session, then reconciles once, for `today`,
    and computes its `stats` for that date too (#79). When the stats can't be computed, the snapshot has no `stats`
    unless one was queued. The queued events follow, in queue order.

    A client that falls behind is dropped by the hub; its websocket is then closed with 1013 ("try again later"),
    and the client reconnects to a fresh snapshot.
    """
    hub: Hub = websocket.app.state.hub
    holder: ServicesHolder = websocket.app.state.services
    await websocket.accept()
    async with hub.subscribe() as (queue, dropped):
        services = holder.get()
        current = await anyio.to_thread.run_sync(services.sessions.current)
        view = await anyio.to_thread.run_sync(services.training_days.today_view)
        today: Message = {"type": "today", "data": view.model_dump(mode="json")}
        session: Message = {
            "type": "session",
            "data": None if current is None else current.model_dump(mode="json"),
        }
        stats = await _stats(services, view.date)
        events: list[Message] = []
        for message in _drain(queue):
            if message.get("type") == "today":
                today = message
            elif message.get("type") == "session":
                session = message
            elif message.get("type") == "stats":
                stats = message
            else:
                events.append(message)
        await websocket.send_json(
            {"type": "hello", "version": __version__, "api_version": API_VERSION}
        )
        await websocket.send_json(today)
        await websocket.send_json(session)
        if stats is not None:
            await websocket.send_json(stats)
        for message in events:
            await websocket.send_json(message)
        await _serve(websocket, queue, dropped)


async def _stats(services: Services, today: date) -> Message | None:
    """Build the snapshot's `stats` for `today`, the date of its `today`; `None` when they can't be computed.

    The stats service logs why they can't.

    No `data: null` is sent: the integration reads that as malformed, and a later `stats` fills the gap.
    """
    try:
        numbers = await anyio.to_thread.run_sync(services.stats.view, today)
    except Unavailable:
        return None
    return {"type": "stats", "data": numbers.model_dump(mode="json")}


def _drain(queue: asyncio.Queue[Message]) -> list[Message]:
    """Take every message already on `queue`."""
    messages: list[Message] = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    return messages


async def _serve(
    websocket: WebSocket, queue: asyncio.Queue[Message], dropped: asyncio.Event
) -> None:
    """Forward the queue until the client goes or the hub drops it; whatever the client sends is ignored.

    A send to a client that has gone ends the forwarding; that error is dropped with the connection. A dropped
    subscriber's websocket is closed with 1013 once the other tasks have ended.
    """

    async def forward() -> None:
        while True:
            await websocket.send_json(await queue.get())

    async def until_closed() -> None:
        while (await websocket.receive())["type"] != "websocket.disconnect":
            pass

    tasks: set[asyncio.Task[Any]] = {
        asyncio.create_task(forward()),
        asyncio.create_task(until_closed()),
        asyncio.create_task(dropped.wait()),
    }
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(
                asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError
            ):
                await task
    if dropped.is_set():
        with suppress(WebSocketDisconnect, RuntimeError, OSError):
            await websocket.close(code=status.WS_1013_TRY_AGAIN_LATER)
