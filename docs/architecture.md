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

- **Add-on server** (`addon/server/`, FastAPI, D2): `GET /api/v1/health` on port 8765 (D15) answers
  `{"status": "ok", "version": "<server version>", "api_version": 1}`. It keeps its data in `/data`
  (`HA_FITNESS_DATA_DIR` in the fast loop). The image is built from `addon/Dockerfile` on HA's Python base image.
- **Integration:** a config flow with one entry and nothing to enter. Setting up the entry serves
  `custom_components/ha_fitness/frontend/` at `/ha_fitness_frontend/` and loads
  `/ha_fitness_frontend/ha-fitness-cards.js?v=<integration version>` in the frontend. The version in the URL busts
  browser caches after an update.
- **Cards:** Vite builds `cards/src/index.ts` into `custom_components/ha_fitness/frontend/ha-fitness-cards.js`.
  Importing a card registers its custom element (`ha-fitness-<name>-card`). The texts come from `cards/src/i18n/`
  (`en.json` is the base, `da.json` Danish) and follow the HA user's language (D11).

Not built yet: the database, MCP, the websocket push channel (D6), the add-on↔integration connection (Supervisor
discovery; a configured URL in the fast loop), entities and services. Each comes with its feature spec.

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
them itself through the Supervisor's HA API (`homeassistant_api: true`), so its MCP tools work even when the
integration isn't connected. In the fast loop it will use the dev HA's URL and a token from the git-ignored `.env`
(`.env.example` lists the names).
