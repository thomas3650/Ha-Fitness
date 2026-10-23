"""A fake HA Fitness add-on: the REST routes and the push channel of spec §3.5 to §3.7 and §4.2."""

import asyncio
import copy
from typing import Any

from aiohttp import web

# The example of spec §3.5: one due day.
TODAY_DUE: dict[str, Any] = {
    "date": "2026-10-28",
    "open": [
        {
            "id": 12,
            "program_id": 3,
            "program_name": "Onsdag",
            "date": "2026-10-28",
            "state": "due",
            "station_count": 5,
            "rounds": 5,
            "total_minutes": 29,
        }
    ],
    "next": {"date": "2026-10-31", "programs": ["Lørdag"]},
}


class FakeAddon:
    """An aiohttp app that speaks the add-on's API; tests set its fields and drive the ws."""

    def __init__(self) -> None:
        """Start as a current add-on (API version 1) with one due day."""
        self.url = ""  # set by the fixture once the server listens
        self.version = "0.2.0"
        self.api_version = 1
        self.today: dict[str, Any] = copy.deepcopy(TODAY_DUE)
        self.skip_status = 200
        self.old_addon = False
        # False: accept the ws but send nothing (no hello, no today).
        self.send_hello = True
        # False: never answer the client's pings, as a half-open connection wouldn't.
        self.answer_pings = True
        self.skip_user_agents: list[str] = []
        self.connects = 0
        self.connected = asyncio.Event()
        self._sockets: set[web.WebSocketResponse] = set()
        self.app = web.Application()
        self.app.router.add_get("/api/v1/health", self._health)
        self.app.router.add_get("/api/v1/today", self._today)
        self.app.router.add_post("/api/v1/training-days/{id}/skip", self._skip)
        self.app.router.add_get("/api/v1/ws", self._ws)
        self.app.on_shutdown.append(self._on_shutdown)

    async def _health(self, request: web.Request) -> web.Response:
        return web.json_response(
            {"status": "ok", "version": self.version, "api_version": self.api_version}
        )

    async def _today(self, request: web.Request) -> web.Response:
        if self.old_addon:
            return web.json_response({"detail": "Not Found"}, status=404)
        return web.json_response(self.today)

    async def _skip(self, request: web.Request) -> web.Response:
        self.skip_user_agents.append(request.headers.get("User-Agent", ""))
        if self.skip_status != 200:
            return web.json_response({"detail": "error"}, status=self.skip_status)
        day_id = int(request.match_info["id"])
        open_day = next(
            (day for day in self.today["open"] if day["id"] == day_id),
            {"id": day_id, "program_id": None, "program_name": "", "date": ""},
        )
        # The training day as stored (spec §3.1), not the /today row with its program fields.
        fields = ("id", "program_id", "program_name", "date")
        return web.json_response(
            {**{key: open_day[key] for key in fields}, "status": "skipped"}
        )

    async def _ws(self, request: web.Request) -> web.WebSocketResponse:
        if self.old_addon:
            # An older add-on has no ws route: the handshake is rejected with an HTTP status.
            raise web.HTTPForbidden
        ws = web.WebSocketResponse(autoping=self.answer_pings)
        await ws.prepare(request)
        self._sockets.add(ws)
        self.connects += 1
        self.connected.set()
        try:
            if self.send_hello:
                await ws.send_json(
                    {
                        "type": "hello",
                        "version": self.version,
                        "api_version": self.api_version,
                    }
                )
                await ws.send_json({"type": "today", "data": self.today})
            async for _ in ws:  # the client sends nothing; wait for the close
                pass
        finally:
            self._sockets.discard(ws)
            if not self._sockets:
                self.connected.clear()
        return ws

    async def push(self, message: dict[str, Any]) -> None:
        """Send a message to every connected client."""
        for ws in list(self._sockets):
            await ws.send_json(message)

    async def close_ws(self) -> None:
        """Close every open websocket, as an add-on restart would."""
        for ws in list(self._sockets):
            await ws.close()

    async def _on_shutdown(self, app: web.Application) -> None:
        await self.close_ws()
