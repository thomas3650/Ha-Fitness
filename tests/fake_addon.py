"""A fake HA Fitness add-on: the REST routes and the push channel of spec §3.5 to §3.7 and §4.2.

Step 5 adds the session routes, the session message (the workout spec §3.5), and the programs,
people and exercise media routes the integration relays (the workout spec §4).
"""

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


# A running session in a work phase (spec §3.5's view); tests set server_time and copy it.
SESSION_RUNNING: dict[str, Any] = {
    "id": 7,
    "revision": 4,
    "status": "running",
    "counted": False,
    "program_name": "Onsdag",
    "training_day_id": 12,
    "participants": [{"id": 1, "name": "Anna"}, {"id": 2, "name": "Bo"}],
    "phase": {
        "index": 3,
        "kind": "work",
        "round": 1,
        "interval": 2,
        "duration": 40,
        "ends_at": "2026-10-28T17:00:40.000+00:00",
        "remaining": None,
    },
    "next_phase": {"kind": "switch", "duration": 15},
    "stations": [
        {
            "current": {"number": 2, "exercise_id": "0001", "name": "Squat"},
            "next": {"number": 3, "exercise_id": "0002", "name": "Push-up"},
        },
        {
            "current": {"number": 3, "exercise_id": "0002", "name": "Push-up"},
            "next": {"number": 1, "exercise_id": "0003", "name": "Plank"},
        },
    ],
    "totals": {"planned": 1500, "rounds": 5},
    "started_at": "2026-10-28T16:58:00.000+00:00",
    "ended_at": None,
    "rounds_completed": 0,
    "time_trained": 100,
    "server_time": "2026-10-28T17:00:00.000+00:00",
}


# Two programs as GET /api/v1/programs gives them (step 3's ProgramOut), by name; one is inactive.
PROGRAMS: list[dict[str, Any]] = [
    {
        "id": 4,
        "program": {
            "name": "Lørdag",
            "active": False,
            "weekdays": [],
            "stations": [{"exercise": "0003"}],
            "rounds": 3,
            "work_seconds": 40,
            "switch_seconds": 10,
            "round_rest_seconds": 30,
            "countdown_seconds": 10,
            "music": None,
        },
        "station_names": ["Plank"],
        "total_seconds": 600,
        "created_at": "2026-10-20T08:00:00Z",
        "updated_at": "2026-10-20T08:00:00Z",
    },
    {
        "id": 3,
        "program": {
            "name": "Onsdag",
            "active": True,
            "weekdays": ["wed"],
            "stations": [{"exercise": "0001"}, {"exercise": "custom-2"}],
            "rounds": 5,
            "work_seconds": 45,
            "switch_seconds": 15,
            "round_rest_seconds": 60,
            "countdown_seconds": 5,
            "music": {
                "playlist": "Workout",
                "speaker": "media_player.speaker",
                "volume": 40,
                "shuffle": False,
            },
        },
        "station_names": ["Squat", "Wall sit"],
        "total_seconds": 1769,
        "created_at": "2026-10-20T08:00:00Z",
        "updated_at": "2026-10-21T08:00:00Z",
    },
    {
        "id": 5,
        "program": {
            "name": "Søndag",
            "active": True,
            "weekdays": ["sun"],
            "stations": [{"exercise": "0002"}],
            "rounds": 2,
            "work_seconds": 30,
            "switch_seconds": 0,
            "round_rest_seconds": 0,
            "countdown_seconds": 0,
            "music": None,
        },
        "station_names": ["Push-up"],
        "total_seconds": 1770,
        "created_at": "2026-10-20T08:00:00Z",
        "updated_at": "2026-10-20T08:00:00Z",
    },
]

# GET /api/v1/people as the add-on gives it (step 3's PeopleView).
PEOPLE: dict[str, Any] = {
    "people": [
        {"id": 1, "name": "Anna", "person_entity_id": "person.anna"},
        {"id": 2, "name": "Bo", "person_entity_id": "person.bo"},
    ],
    "ha_persons": [],
    "ha_error": None,
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
        # The session view of spec §3.5, or None: what GET /session answers and the ws sends on connect.
        self.session: dict[str, Any] | None = None
        # True: an add-on from before sessions; /session gives 404 and the ws sends no session.
        # Unlike old_addon, the ws itself works.
        self.no_sessions = False
        # False: leave the session message out on connect, so a test can send it later.
        self.send_session = True
        # False: accept the ws but send nothing (no hello, no today).
        self.send_hello = True
        # False: never answer the client's pings, as a half-open connection wouldn't.
        self.answer_pings = True
        # What GET /programs and GET /people answer; a test may set a malformed body.
        self.programs: Any = copy.deepcopy(PROGRAMS)
        self.people: Any = copy.deepcopy(PEOPLE)
        # Not 200: GET /programs and GET /people answer this status instead.
        self.lists_status = 200
        # (status, body) for the session POSTs instead of the view; a str body is sent as plain text.
        self.session_error: tuple[int, Any] | None = None
        # Each session POST: (command, JSON body or None, User-Agent); start's command is "start".
        self.session_calls: list[tuple[str, Any, str]] = []
        # The exercise media: (exercise id, kind) -> (bytes, content type); others give 404.
        self.media: dict[tuple[str, str], tuple[bytes, str]] = {}
        # Not None: every media request answers this status.
        self.media_status: int | None = None
        # Every media request: (exercise id, kind).
        self.media_requests: list[tuple[str, str]] = []
        self.skip_user_agents: list[str] = []
        self.skip_ids: list[int] = []
        self.connects = 0
        self.connected = asyncio.Event()
        self._sockets: set[web.WebSocketResponse] = set()
        self.app = web.Application()
        self.app.router.add_get("/api/v1/health", self._health)
        self.app.router.add_get("/api/v1/today", self._today)
        self.app.router.add_post("/api/v1/training-days/{id}/skip", self._skip)
        self.app.router.add_get("/api/v1/session", self._session)
        self.app.router.add_post("/api/v1/session", self._start_session)
        self.app.router.add_post("/api/v1/session/{command}", self._session_command)
        self.app.router.add_get("/api/v1/programs", self._programs)
        self.app.router.add_get("/api/v1/people", self._people)
        self.app.router.add_get("/api/v1/exercises/{id}/{kind}", self._media)
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

    async def _session(self, request: web.Request) -> web.Response:
        if self.no_sessions:
            return web.json_response({"detail": "Not Found"}, status=404)
        return web.json_response(self.session)

    async def _start_session(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.session_calls.append(
            ("start", body, request.headers.get("User-Agent", ""))
        )
        if self.session_error is not None:
            return self._session_error(self.session_error)
        return web.json_response(self.session or SESSION_RUNNING, status=201)

    async def _session_command(self, request: web.Request) -> web.Response:
        command = request.match_info["command"]
        self.session_calls.append(
            (command, None, request.headers.get("User-Agent", ""))
        )
        if self.session_error is not None:
            return self._session_error(self.session_error)
        return web.json_response(self.session or SESSION_RUNNING)

    @staticmethod
    def _session_error(error: tuple[int, Any]) -> web.Response:
        status, body = error
        if isinstance(body, str):
            return web.Response(text=body, status=status)
        return web.json_response(body, status=status)

    async def _programs(self, request: web.Request) -> web.Response:
        if self.lists_status != 200:
            return web.json_response({"detail": "error"}, status=self.lists_status)
        return web.json_response(self.programs)

    async def _people(self, request: web.Request) -> web.Response:
        if self.lists_status != 200:
            return web.json_response({"detail": "error"}, status=self.lists_status)
        return web.json_response(self.people)

    async def _media(self, request: web.Request) -> web.Response:
        key = (request.match_info["id"], request.match_info["kind"])
        self.media_requests.append(key)
        if self.media_status is not None:
            return web.json_response({"detail": "error"}, status=self.media_status)
        if key not in self.media:
            return web.json_response({"detail": "Not Found"}, status=404)
        body, content_type = self.media[key]
        return web.Response(body=body, content_type=content_type)

    async def _skip(self, request: web.Request) -> web.Response:
        self.skip_user_agents.append(request.headers.get("User-Agent", ""))
        self.skip_ids.append(int(request.match_info["id"]))
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
                if self.send_session and not self.no_sessions:
                    await ws.send_json({"type": "session", "data": self.session})
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
