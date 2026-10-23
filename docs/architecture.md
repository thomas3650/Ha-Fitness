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
  [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md); the code is the source for the details.
  - **Database:** SQLite in `<data folder>/ha_fitness.db`, in WAL mode (D4, D5). Alembic migrations ship in the
    package and run to `head` at start. A database at a revision the code doesn't know stops the start.
  - **Exercise library:** the 721 filtered exercises are built into the package; their GIFs and thumbnails are
    downloaded into `<data folder>/library/media/` in the background at every start (D13, D30). Custom exercises live
    in their own table.
  - **People** (at most 2) linked to HA person entities, **programs** (one validated JSON document each, D4) and the
    **change log** of every write.
  - **REST** under `/api/v1/` (the routes are spec §7). `GET /api/v1/health` answers
    `{"status": "ok", "version": "<server version>", "api_version": 1}`.
  - **MCP** at `/mcp` (the tools are spec §8).
  - **The Ingress page** at `/`: a status page, in English or Danish after the browser's language (D27).
  - **Hot backups** through a consistent snapshot, `<data folder>/backup/snapshot.db` (D31).
- **Integration:** a config flow with one entry and nothing to enter. Setting up the entry serves
  `custom_components/ha_fitness/frontend/` at `/ha_fitness_frontend/` and loads
  `/ha_fitness_frontend/ha-fitness-cards.js?v=<integration version>` in the frontend. The version in the URL busts
  browser caches after an update.
- **Cards:** Vite builds `cards/src/index.ts` into `custom_components/ha_fitness/frontend/ha-fitness-cards.js`.
  Importing a card registers its custom element (`ha-fitness-<name>-card`). The texts come from `cards/src/i18n/`
  (`en.json` is the base, `da.json` Danish) and follow the HA user's language (D11).

Not built yet: training days, sessions, history and stats; the websocket push channel (D6); the add-on↔integration
connection (Supervisor discovery, D28; a configured URL in the fast loop); entities and services. Each comes with its
feature spec.

### Routing in the add-on server

- The MCP app is mounted at `/`, after every other route, and serves `/mcp` itself (D26). So any path no route
  matches reaches the MCP app, which answers a plain-text 404.
- A catch-all route `/api/{path}` keeps an unknown `/api` path a JSON 404 (`{"detail": "Not Found"}`). It must stay
  after every `/api` route: a route registered below it is shadowed.
- A wrong method on a known `/api` path also gets that 404, not a 405. The catch-all matches the path and the method,
  and Starlette prefers it over a route that matches only the path.
- The Ingress page `GET /` sits after the catch-all and before the MCP mount.

## The contract between the add-on and the integration

- The add-on reports an **API version** (`api_version` in the health response; 1 now). It goes up only with a
  breaking change to the contract.
- The integration supports the current and the previous API version. If it finds another, it raises an HA repair issue
  saying which part to update.
- No non-major release of one part may require a newer version of the other part. The two are installed and updated
  separately (D8), in any order.
- REST and MCP are thin adapters over one service layer in the add-on; the integration uses the same REST API (D3).

## Data the add-on reads from HA

HA's timezone (for midnight), the person entities, and Music Assistant's speakers and playlists. The add-on reads
them itself through HA's REST API, so its MCP tools work even when the integration isn't connected. So far it reads
only the persons: `GET /api/states`, filtered to `person.*`.

- **Under the Supervisor:** `http://supervisor/core/api` with `SUPERVISOR_TOKEN` (`homeassistant_api: true`). The
  server only sees the token because the Dockerfile's `CMD` starts with `with-contenv`
  ([why](ha-notes.md#the-supervisor)). `SUPERVISOR_TOKEN` wins over the variables below.
- **Elsewhere (the fast loop):** `HA_FITNESS_HA_URL` is HA's base URL (the server adds `/api`), and
  `HA_FITNESS_HA_TOKEN_FILE` names a file with a token. The file is read at each call, so a token written after the
  server started works without a restart. `scripts/dev_onboard.py` keeps the dev token in `local/dev-ha-token` (D32).
- Without a URL or a token, HA is "not configured". A read still answers, with `ha_persons: null` and `ha_error`; a
  write that needs HA fails with 503.
