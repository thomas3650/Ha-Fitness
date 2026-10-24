# Architecture

Three parts in one repo (D1). The design, with what each part will own in v1, is spec §4
([design spec](superpowers/specs/2026-10-23-ha-fitness-design.md)). This doc says who owns what, what exists now, and
the rules for the contract between the parts.

## Who owns what

| Part | Folder | Owns | Talks to |
| --- | --- | --- | --- |
| Add-on "HA Fitness" (slug `ha_fitness`) | `addon/` | The data and the logic: programs, people, the exercise library, the scheduler, sessions, history, the change log; REST and MCP on its own port | The integration; Claude (MCP); HA through the Supervisor's HA API |
| Integration "HA Fitness" (domain `ha_fitness`) | `custom_components/ha_fitness/` | Entities, services, events, Music Assistant calls, the websocket relay for the cards, the media proxy for GIFs; serves the cards bundle | The add-on; HA |
| Cards | `cards/` | The screens: "Træning i dag", the workout flow, stats | Only HA, through the integration's websocket commands |

The cards are built into the integration: one bundle, released and versioned with it (D8).

## What exists now

- **Add-on server** (`addon/server/`, FastAPI, D2) on port 8765 (D15). It keeps its data in the data folder: `/data`
  in the add-on, `HA_FITNESS_DATA_DIR` in the fast loop. The image is built from `addon/Dockerfile` on HA's Python base
  image. The design of what it holds is the
  [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md), for training days the
  [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md), and for sessions the
  [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md); the code is the source for the details.
  - **Database:** SQLite in `<data folder>/ha_fitness.db`, in WAL mode (D4, D5). Alembic migrations ship in the
    package and run to `head` at start. A database at a revision the code doesn't know stops the start.
  - **Exercise library:** the 721 filtered exercises are built into the package; their GIFs and thumbnails are
    downloaded into `<data folder>/library/media/` in the background at every start (D13, D30). Custom exercises live
    in their own table.
  - **People** (at most 2) linked to HA person entities, **programs** (one validated JSON document each, D4) and the
    **change log** of every write.
  - **Training days** and the **scheduler** (step 4 spec §3.3, D34). A training day is one program on one local date,
    stored as open, done, missed or skipped; only a counted session closes a day as done. Training-day ids are never reused, so a skip by id
    can't hit a later day. The scheduler reconciles at start, every minute, after every program write and before
    every read of the days. One lock serialises the scheduler, skips, program writes, sessions and the dev routes.
  - **Sessions** ([below](#sessions)): the workout engine, one session at a time (D40), with history and the
    "counting from" date.
  - **REST** under `/api/v1/` (the routes are step 3 spec §7). `GET /api/v1/health` answers
    `{"status": "ok", "version": "<server version>", "api_version": 1}`. Step 4 adds `GET /api/v1/today`,
    `GET /api/v1/training-days?from=&to=` and `POST /api/v1/training-days/{id}/skip` (step 4 spec §3.4–§3.5). Step 5
    adds the [session routes](#sessions).
  - **MCP** at `/mcp` (the tools are step 3 spec §8, plus `get_today` and `skip_training_day` from step 4 spec §3.5,
    and the read-only `get_session` and `list_sessions` from step 5 spec §3.5). No MCP tool starts or steers a
    workout.
  - **The push channel** `GET /api/v1/ws`, a websocket (D6, D35; [below](#the-push-channel)).
  - **Supervisor discovery:** at every start under the Supervisor the add-on posts the service `ha_fitness` with its
    hostname and port 8765 (D28, step 4 spec §3.7). Outside the Supervisor it does nothing. A failure is logged and
    doesn't stop the server.
  - **Dev routes** under `/api/v1/dev/` exist only with `HA_FITNESS_DEV=1`, which only `scripts/develop` sets
    ([`testing.md`](testing.md#fast-loop)).
  - **The Ingress page** at `/`: a status page, in English or Danish after the browser's language (D27).
  - **Hot backups** through a consistent snapshot, `<data folder>/backup/snapshot.db` (D31). The snapshot is also
    written at every shutdown (D43).
- **Integration** (the [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §4; the code is the
  source for the details):
  - **One entry**, version 2, with the unique id `ha_fitness` and the add-on's URL as its data (D39). It comes from
    the add-on's discovery (D28), which shows under "Discovered", or from the user step, which asks for the URL
    (`http://localhost:8765` in the fast loop) and checks `GET /api/v1/health` first. A discovery for an existing entry
    updates its URL and reloads it. A version 1 entry (0.1.0) is migrated to `http://localhost:8765`, and the next
    discovery corrects that under the Supervisor.
  - **The connection** to the add-on's push channel ([below](#the-integrations-side)). Setup never waits for the
    add-on.
  - **Entities** on one device "HA Fitness", whose software version is the add-on's version:
    `sensor.ha_fitness_today` (`none`, `due` or `late`, with the open days in `training_days`),
    `sensor.ha_fitness_next_training_day` (a date, with `programs`) and `binary_sensor.ha_fitness_training_open`. The
    entity ids are set in the code, so they are the same in every HA language
    ([why](ha-notes.md#the-integration)). The two attributes aren't recorded.
  - **The service** `ha_fitness.skip` (`training_day_id`) and the **events** `ha_fitness_training_day_due`,
    `_skipped` and `_missed`, with the training day as data.
  - **The card's subscription** `ha_fitness/today/subscribe`, a websocket command: the add-on's `today` data at once
    and after each change, `null` while the add-on can't be used.
  - **The cards bundle:** setting up the entry serves `custom_components/ha_fitness/frontend/` at
    `/ha_fitness_frontend/` and loads `/ha_fitness_frontend/ha-fitness-cards.js?v=<integration version>` in the
    frontend. The version in the URL busts browser caches after an update.
- **Cards:** Vite builds `cards/src/index.ts` into `custom_components/ha_fitness/frontend/ha-fitness-cards.js`.
  Importing a card registers its custom element (`ha-fitness-<name>-card`). The texts come from `cards/src/i18n/`
  (`en.json` is the base, `da.json` Danish) and follow the card's `language` option, else the HA user's language
  (D11, D38).
  - **"Træning i dag"** (`custom:ha-fitness-today-card`) shows one row per open training day, with a two-tap Spring
    over. It hides itself when nothing is open, except in edit mode, and shows one line while the add-on can't be
    reached (step 4 spec §6).

Not built yet: the integration's side of sessions and the workout flow (step 5, parts E and F), and stats. Each
comes with its feature spec.

### Routing in the add-on server

- The MCP app is mounted at `/`, after every other route, and serves `/mcp` itself (D26). So any path no route
  matches reaches the MCP app, which answers a plain-text 404.
- A catch-all route `/api/{path}` keeps an unknown `/api` path a JSON 404 (`{"detail": "Not Found"}`). It must stay
  after every `/api` route: a route registered below it is shadowed.
- A wrong method on a known `/api` path also gets that 404, not a 405. The catch-all matches the path and the method,
  and Starlette prefers it over a route that matches only the path.
- The dev router (only with `HA_FITNESS_DEV=1`) is included right after the `/api` routes, above the catch-all.
- The Ingress page `GET /` sits after the catch-all and before the MCP mount.

## The contract between the add-on and the integration

- The add-on reports an **API version** (`api_version` in the health response; 1 now). It goes up only with a
  breaking change to the contract.
- The integration supports the current and the previous API version. If it finds another, it raises an HA repair issue
  saying which part to update.
- No non-major release of one part may require a newer version of the other part. The two are installed and updated
  separately (D8), in any order. While both parts are 0.x, an integration release may need a newer add-on, through
  the `addon_too_old` repair issue (D37). From 1.0.0 on the rule holds without exception.
- REST and MCP are thin adapters over one service layer in the add-on; the integration uses the same REST API (D3).
- The push channel `/api/v1/ws` is part of the contract, under the same API version. Its `hello` message carries the
  `api_version`. Both sides ignore message types they don't know, so a new message type isn't a breaking change.

### The push channel

`GET /api/v1/ws` is a websocket (D6). The protocol is step 4 spec §3.6 (D35):

- The client sends nothing. Whatever it sends is ignored.
- On connect the add-on sends `hello` (`version`, `api_version`), then `today`, with the same data as
  `GET /api/v1/today`.
- After that it sends a new `today` whenever that data changes, and one `event` (`due`, `skipped`, `missed` or `done`)
  per state change of a training day.
- Step 5 adds `session` ([below](#sessions)): it follows `today` on connect, and comes again after every change.
- Events are fire-and-forget: a client that isn't connected misses them. The `today` state is what counts.

```json
{"type": "event", "event": "skipped", "training_day": {"id": 12, "program_id": 3, "program_name": "Onsdag", "date": "2026-10-28"}}
```

### The integration's side

- **One client per entry** holds the websocket, with a 30 s heartbeat (a ping the add-on answers). It reconnects after
  1, 2, 5 and 10 s, then every 30 s. The first failed connect of an outage logs one warning.
- **On `hello`** it checks `api_version`. It speaks version 1. On another version it raises a repair issue, and the
  entities stay unavailable.
- **REST calls** (the skip) send `User-Agent: ha_fitness/<integration version>`, so the add-on's change log names
  the integration.
- **While disconnected, or on an unsupported version,** every entity is unavailable and the card's subscription sends
  `null`.
- **The repair issues**, both errors that the user fixes by updating a part. Each is deleted once a supported add-on
  connects.
  - `unsupported_api_version`: the add-on speaks another API version. It says to update the integration.
  - `addon_too_old`: the ws handshake is refused with an HTTP status, `GET /api/v1/health` answers and
    `GET /api/v1/today` gives 404. That is an add-on from before step 4 (D37). It says to update the add-on, and the
    client keeps retrying.

## Data the add-on reads from HA

HA's timezone (for midnight), the person entities, and Music Assistant's speakers and playlists.

- **The timezone** comes from the environment, not from HA's API (D36): `HA_FITNESS_TIMEZONE`, else `TZ`, else UTC
  with a log line. Under the Supervisor, `TZ` is HA's timezone ([`ha-notes.md`](ha-notes.md#the-supervisor)). The
  fast loop sets `HA_FITNESS_TIMEZONE`. A change takes effect at the next start.
- **The rest** the add-on reads itself through HA's REST API, so its MCP tools work even when the integration isn't
  connected. So far it reads only the persons: `GET /api/states`, filtered to `person.*`.

- **Under the Supervisor:** `http://supervisor/core/api` with `SUPERVISOR_TOKEN` (`homeassistant_api: true`). The
  server only sees the token because the Dockerfile's `CMD` starts with `with-contenv`
  ([why](ha-notes.md#the-supervisor)). `SUPERVISOR_TOKEN` wins over the variables below.
- **Elsewhere (the fast loop):** `HA_FITNESS_HA_URL` is HA's base URL (the server adds `/api`), and
  `HA_FITNESS_HA_TOKEN_FILE` names a file with a token. The file is read at each call, so a token written after the
  server started works without a restart. `scripts/dev_onboard.py` keeps the dev token in `local/dev-ha-token` (D32).
- Without a URL or a token, HA is "not configured". A read still answers, with `ha_persons: null` and `ha_error`; a
  write that needs HA fails with 503.

## Sessions

The design is the [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3 (D40–D43); the code is
`addon/server/src/ha_fitness_server/sessions.py`.

- **The plan.** A start freezes the plan: the program's name and timing, its stations with their names, and the
  participants with their names. A later program edit or a removed person changes no running session and no history.
  The phases follow from the plan: countdown, then per round work and switch per station, then rest. There is no
  switch after the last interval of the last round (D41), so the session ends with the last work phase.
- **Deadlines, not counters.** A session stores its phase and the time that phase started. Each next phase starts at
  the previous one's deadline, so no time drifts, and several phases can pass in one tick.
- **One at a time.** Only one session can be running or paused. Another start gives a 409.
- **The loop.** The lifespan runs the tick in a worker thread. It wakes at the current phase's deadline, and at least
  every `session_tick_max` seconds (1 s; a field of `Settings` with no environment variable, which tests change). Every command and every read ticks first, under
  the scheduler's lock. A tick that moves on publishes one `session` message and one `phase_changed` event, for the
  phase it ends on. `last_tick_at` is written every 5 s and at every phase change.
- **Restarts.** At shutdown the lifespan pauses a running session, then writes the snapshot (D43). At start a session
  still running (after a crash) is paused at its `last_tick_at`, so the time the add-on was down counts as a pause.
  A restart never skips phases or completes a workout nobody did.
- **The pause limit.** A session paused for 30 minutes is ended, at `paused_at + 30 min`, with the client `addon`.
  After a crash that was down longer than that, it is ended at the start. The usual counting rules apply.
- **Finishing.** The tick passing the last work phase, or `next` on it, completes the session. `end` or the pause
  limit ends it early; it counts when at least one full round is behind it. A counted session with a training day
  closes the day as done (done late when the day's date is before the local date of `started_at`). The first counted
  session sets `counting_from`. Each finished session keeps one row per participant, with the name and no foreign key.
- **The day under a session** (D42). Reconcile leaves an open day alone while a session for it is running or paused.
  Skipping that day gives a 409. Switching off or deleting the program of a running or paused session gives a 409 with
  "A session for this program is running"; this holds for extra sessions too.
- **Due and late can mix.** Step 4's rule that a new training day closes a late one waits while a session runs for the
  late day. A session that crosses midnight into another training day keeps its late day open next to the new due day.

### The session routes

| Method and path | Does |
| --- | --- |
| `GET /api/v1/session` | The running or paused session; else the last finished one for 5 minutes after it finished; else `null`. |
| `POST /api/v1/session` | Start: `{"program_id", "participants": [person ids], "training_day_id"?}` → the session view (201). |
| `POST /api/v1/session/{command}` | `pause`, `resume`, `next`, `previous` or `end` → the session view. |
| `GET /api/v1/sessions?limit=` | `{"counting_from", "sessions": [finished views, newest first]}`; `limit` 1–100, default 20. |

- **Errors.** These routes answer `{"detail": {"code", "message"}}`. The codes are `not_found` (404), `conflict` (409)
  and `invalid` (422). An unknown command is a 404 `not_found`; a command not allowed now is a 409 `conflict`. Steps
  3–4's routes keep their own error shapes, and so do the skip and program 409s above.
- **The view** (`SessionView` in `schemas.py`) has the phase with `ends_at` (UTC with milliseconds, null while paused)
  or `remaining` (while paused), the next phase, each participant's current and next station, `totals`
  (`planned`, `rounds`, `stations`), `time_trained` in whole seconds, `revision`, which goes up with every change, and
  `server_time`. A finished view has no phase, next phase or stations.
- **The change log** records `session.started`, `session.completed` and `session.ended`. Pause, resume, next and
  previous aren't logged.

### Session messages on the push channel

- `{"type": "session", "data": <view or null>}`. It is sent on connect after `today`, and after every change: a phase,
  a command, a finish or the pause limit. A finished view is sent once. When its 5 minutes are over, the loop sends
  `null`, unless a new session has started.
- Events: `{"type": "event", "event": …, "session": {"id", "program_name", "training_day_id", …}}` for
  `session_started`, `session_completed`, `session_ended` (with `counted`) and `phase_changed` (with `phase`).
- `{"type": "event", "event": "done", "training_day": {…}}` when a counted session closes its day, then a new
  `today`.
