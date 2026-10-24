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
  [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md) and, for training days, the
  [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md); the code is the source for the details.
  - **Database:** SQLite in `<data folder>/ha_fitness.db`, in WAL mode (D4, D5). Alembic migrations ship in the
    package and run to `head` at start. A database at a revision the code doesn't know stops the start.
  - **Exercise library:** the 721 filtered exercises are built into the package; their GIFs and thumbnails are
    downloaded into `<data folder>/library/media/` in the background at every start (D13, D30). Custom exercises live
    in their own table.
  - **People** (at most 2) linked to HA person entities, **programs** (one validated JSON document each, D4) and the
    **change log** of every write.
  - **Training days** and the **scheduler** (step 4 spec §3.3, D34). A training day is one program on one local date,
    stored as open, missed or skipped (done comes with sessions). The scheduler reconciles at start, every minute,
    after every program write and before every read of the days. One lock serialises the scheduler, skips, program
    writes and the dev routes.
  - **REST** under `/api/v1/` (the routes are step 3 spec §7). `GET /api/v1/health` answers
    `{"status": "ok", "version": "<server version>", "api_version": 1}`. Step 4 adds `GET /api/v1/today`,
    `GET /api/v1/training-days?from=&to=` and `POST /api/v1/training-days/{id}/skip` (step 4 spec §3.4–§3.5).
  - **MCP** at `/mcp` (the tools are step 3 spec §8, plus `get_today` and `skip_training_day` from step 4 spec §3.5).
  - **The push channel** `GET /api/v1/ws`, a websocket (D6, D35; [below](#the-push-channel)).
  - **Supervisor discovery:** at every start under the Supervisor the add-on posts the service `ha_fitness` with its
    hostname and port 8765 (D28, step 4 spec §3.7). Outside the Supervisor it does nothing. A failure is logged and
    doesn't stop the server.
  - **Dev routes** under `/api/v1/dev/` exist only with `HA_FITNESS_DEV=1`, which only `scripts/develop` sets
    ([`testing.md`](testing.md#fast-loop)).
  - **The Ingress page** at `/`: a status page, in English or Danish after the browser's language (D27).
  - **Hot backups** through a consistent snapshot, `<data folder>/backup/snapshot.db` (D31).
- **Integration:** a config flow with one entry and nothing to enter. Setting up the entry serves
  `custom_components/ha_fitness/frontend/` at `/ha_fitness_frontend/` and loads
  `/ha_fitness_frontend/ha-fitness-cards.js?v=<integration version>` in the frontend. The version in the URL busts
  browser caches after an update.
- **Cards:** Vite builds `cards/src/index.ts` into `custom_components/ha_fitness/frontend/ha-fitness-cards.js`.
  Importing a card registers its custom element (`ha-fitness-<name>-card`). The texts come from `cards/src/i18n/`
  (`en.json` is the base, `da.json` Danish) and follow the HA user's language (D11).

Not built yet: sessions, history and stats; the integration's side of the connection (taking the discovery, D28; a
configured URL in the fast loop; the push channel's subscription); entities and services. Each comes with its feature
spec.

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
  separately (D8), in any order.
- REST and MCP are thin adapters over one service layer in the add-on; the integration uses the same REST API (D3).
- The push channel `/api/v1/ws` is part of the contract, under the same API version. Its `hello` message carries the
  `api_version`. Both sides ignore message types they don't know, so a new message type isn't a breaking change.

### The push channel

`GET /api/v1/ws` is a websocket (D6). The protocol is step 4 spec §3.6 (D35):

- The client sends nothing. Whatever it sends is ignored.
- On connect the add-on sends `hello` (`version`, `api_version`), then `today`, with the same data as
  `GET /api/v1/today`.
- After that it sends a new `today` whenever that data changes, and one `event` (`due`, `skipped` or `missed`) per
  state change of a training day.
- Events are fire-and-forget: a client that isn't connected misses them. The `today` state is what counts.

```json
{"type": "event", "event": "skipped", "training_day": {"id": 12, "program_id": 3, "program_name": "Onsdag", "date": "2026-10-28"}}
```

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
