"""The push channel `GET /api/v1/ws` (step 4 spec §3.6)."""

import asyncio
from contextlib import suppress
from typing import Any

import anyio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ha_fitness_server import API_VERSION, __version__
from ha_fitness_server.push import Hub, Message
from ha_fitness_server.services import ServicesHolder

router = APIRouter()


@router.websocket("/ws")
async def push_channel(websocket: WebSocket) -> None:
    """Send `hello`, `today` and `session`, then every message the hub broadcasts; the client sends nothing.

    It subscribes before it builds the snapshots, so nothing published meanwhile is lost. Every publish runs under the
    training days' lock, so the queue holds them in lock order. A `today` can be queued after the snapshot was built
    (a skip, a write or a tick in the gap before the drain), and `_publish_today` won't send that view again. So when
    the drain holds a `today`, the last one is the newest view and is sent instead of the snapshot. Otherwise the
    snapshot is the newest: a later change would have queued a `today`. `session` works the same way: every change of
    the session publishes one, and reading the snapshot can tick. The queued events follow, in queue order.
    """
    hub: Hub = websocket.app.state.hub
    holder: ServicesHolder = websocket.app.state.services
    await websocket.accept()
    async with hub.subscribe() as queue:
        services = holder.get()
        view = await anyio.to_thread.run_sync(services.training_days.today_view)
        today: Message = {"type": "today", "data": view.model_dump(mode="json")}
        current = await anyio.to_thread.run_sync(services.sessions.current)
        session: Message = {
            "type": "session",
            "data": None if current is None else current.model_dump(mode="json"),
        }
        events: list[Message] = []
        for message in _drain(queue):
            if message.get("type") == "today":
                today = message
            elif message.get("type") == "session":
                session = message
            else:
                events.append(message)
        await websocket.send_json(
            {"type": "hello", "version": __version__, "api_version": API_VERSION}
        )
        await websocket.send_json(today)
        await websocket.send_json(session)
        for message in events:
            await websocket.send_json(message)
        await _serve(websocket, queue)


def _drain(queue: asyncio.Queue[Message]) -> list[Message]:
    """Take every message already on `queue`."""
    messages: list[Message] = []
    while not queue.empty():
        messages.append(queue.get_nowait())
    return messages


async def _serve(websocket: WebSocket, queue: asyncio.Queue[Message]) -> None:
    """Forward the queue until the client goes; whatever the client sends is ignored.

    A send to a client that has gone ends the forwarding; that error is dropped with the connection.
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
