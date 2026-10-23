# Step 3: Programs through chat – design

- **Date:** 2026-10-24 · **Status:** approved by Claude 2026-10-24 (full-reviewer Ready after 3 rounds), on Thomas's
  delegation for the night of 2026-10-23; Thomas reviews it on 2026-10-24
- **Implements:** [design spec](2026-10-23-ha-fitness-design.md) §10 step 3, with §3.1, §3.6, §3.7 and §4. Issue #3.
- **Needs an update on the real Home Assistant:** **yes.** A new add-on version; the integration doesn't change and
  must not be released by this step (§12). After installing:
  - The house checks that port 8765 answers on the LAN and is not reachable through Cloudflared (design §3.7).
  - An HA person for Elin exists before the people are set.
  - Thomas adds the real endpoint to Claude Code under the name **`ha-fitness-house`**, in local scope, from a folder
    **outside this repo** (for example his home folder): `claude mcp add --transport http ha-fitness-house
    http://<ha-host>:8765/mcp`. Sessions in this repo never see it, so they can't change real data (hard rule 4). The
    dev endpoint is `ha-fitness-dev` (§11).
- "Claude's call" marks choices made without Thomas; he may overrule them.

## 1. Goal

Thomas talks to Claude on his Mac and gets the Wednesday and Saturday programs into HA Fitness. Claude can search the
exercise library, link the people to HA persons, and create, change, switch on or off and delete programs. Nothing
shows on the tablet yet (step 4).

*Try it:* "Make a program for Wednesday with five body-weight exercises, five rounds, 45 s work", then the same for
Saturday; both come back from `list_programs`.

## 2. What ships

All in the add-on (`addon/`), plus fast-loop scripts and docs:

1. **The database:** SQLite in the data folder, SQLAlchemy 2, Alembic migrations from this first schema (D4, D5), and
   consistent hot backups.
2. **The exercise library:** the filtered exercise data built into the add-on; the GIFs and thumbnails downloaded into
   the data folder (D13, design §3.6); custom exercises.
3. **People** linked to HA person entities, read through HA's API.
4. **Programs:** one validated JSON document each (D4).
5. **The change log** of every write.
6. **REST** at `/api/v1/` and **MCP** at `/mcp` (D3, D26), thin adapters over one service layer.
7. **The Ingress page**: a small status page (D27). `addon/config.yaml` gets `ingress: true`, `ingress_port: 8765`,
   `panel_icon: mdi:dumbbell`, `panel_title: HA Fitness`, and `ports_description` "HA Fitness API (REST and MCP)".
8. **Fast loop:** the add-on server talks to the dev HA; `scripts/seed`.

Not in this step: training days, sessions, history and stats (steps 4–6); playlists and speakers (step 7); Supervisor
discovery (`discovery:` stays out of `config.yaml` until step 4, which adds the integration's side) and anything else in
the integration.

"The data folder" is `/data` in the add-on and `HA_FITNESS_DATA_DIR` (`local/addon-data/`) in the fast loop.

## 3. The exercise library

### 3.1 Data built in, media downloaded (Claude's call, D30)

The dataset's **data** (names, equipment, body part, target, instructions) is MIT licensed; its **media** is Gym
visual's, under a separate permission (the dataset's `LICENSE` "media exception" and `NOTICE.md`). So:

- `scripts/build_library.py` (stdlib only, run by hand) downloads `data/exercises.json` from
  `https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/<commit>/data/exercises.json` at the pinned commit
  `7455efae41b330c265e7cd4b78dfa848e7ce5ebd` (or reads `--source <file>`), keeps the records whose `equipment` is one
  of `body weight`, `band`, `resistance band`, `dumbbell`, `kettlebell` (721 records), and writes
  `addon/server/src/ha_fitness_server/library/exercises.json`. The output is deterministic: sorted by `id`, `indent=1`,
  `ensure_ascii=False`, one trailing newline, so a re-run gives no diff. The file is committed and ships in the image.
- Per record it keeps: `id`, `name`, `equipment`, `body_part`, `target`, `secondary_muscles`, `steps` (the English
  `instruction_steps`), `gif` and `thumbnail` (the dataset paths `videos/<file>.gif` and `images/<file>.jpg`). The
  attribution is the same for every record; it is stored once, as a constant in the server
  ("© Gym visual — https://gymvisual.com/"), and returned with every library exercise.
- Next to it, `library/NOTICE.md` names the source and the commit, carries the dataset's full MIT licence text
  (copyright line included), and says the media is not included and is downloaded at runtime for personal use.
- The file is about 0.6 MB, over the `check-added-large-files` hook's 500 kB default. A `chore:` PR before this step's
  PR excludes that one path from the hook (§12).
- A later change of the pinned commit must keep the library ids, or migrate the stored stations.

This replaces design §3.6's "downloads the filtered set" for the data only. Search works offline from the first start,
and tests need no network.

### 3.2 Media download

- At every start, a background task removes leftover `*.part` files, then checks `<data folder>/library/media/` for
  each library exercise's GIF and thumbnail (1,442 files, about 72 MB) and downloads the missing ones from
  `https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/<commit>/<path>`, **8 at a time**.
- A file is written to `<name>.part` and renamed when the response was 200 and complete, so a stopped download never
  leaves a half file under the real name.
- A failed file is logged and tried again at the next start; the task never stops the server.
- `HA_FITNESS_MEDIA_BASE_URL` overrides the base URL (tests use a fake server).
- The state, in `GET /api/v1/library` and on the Ingress page: `idle` before the task starts, `downloading` while it
  runs, then `done` if `present == total`, else `failed`; with the `present` and `total` counts.
- The media folder is left out of HA backups (`backup_exclude`, §10): it is downloaded again after a restore.

### 3.3 Serving media

`GET /api/v1/exercises/{exercise_id}/gif` and `/thumbnail` return the file (`image/gif`, `image/jpeg`), or 404 while it
isn't there. Custom exercises have no media: 404. The integration's media proxy uses these in step 5.

### 3.4 Custom exercises

- Added through Claude: `name` (1–80 characters), `steps` (1–10 strings), optional `equipment`, `body_part`, `target`.
- Ids are `custom-1`, `custom-2` … in the order added. Library ids are the dataset's (`0001` …), so they never collide.
- A custom name must not equal any library or custom name, compared with Python's `str.casefold()` (so "Ø" and "ø"
  match): 409.
- Stored in their own table, so a library update never touches them (design §3.6).
- v1 has no edit or delete for custom exercises (YAGNI; an edit UI is v2).

### 3.5 Search and lookup

- Search matches the query against the name, case-insensitive: names that contain every word of the query, the ones
  that start with the query first, then alphabetical. Optional filters `equipment` and `body_part` match exactly.
  Library and custom exercises are searched together. Default limit 20, 1–100.
- A search with an empty query and no filters returns the first `limit` exercises by name **and** the `facets`: the
  equipment and body-part values to filter by. REST and MCP return the same shape:
  `{"results": [...], "facets": {"equipment": [...], "body_part": [...]} | null}`.
- **Resolving a station's exercise** (Claude's call): a station gives `exercise` as an id or a name. An exact id wins;
  else an exact name (casefolded) that only one exercise has. Otherwise the write fails with 422 and this `detail`:
  `{"message": "Unknown exercise 'pushup'" | "Exercise name '…' is shared; give the id", "station": <1-based index>,
  "close_matches": [{"id", "name"}, …]}` (up to 5 from `difflib.get_close_matches` on the names, cutoff 0.5; for a
  shared name, the exercises that share it). One library name ("self assisted inverse leg curl") is shared by two
  exercises.

## 4. People

- A **person** has an `id` (integer), a `name` (1–40 characters) and a `person_entity_id` (an HA `person.*` entity).
  At most **2** people (Claude's call: only Thomas and Elin train, design §2, and there are two person colours, design
  §3.4). The order is the colour order.
- `set_people` replaces the whole list. A person whose `person_entity_id` is still there keeps their `id` (and, from
  step 5 on, their history); the others are removed. Duplicate entity ids are a 422.
- Every `person_entity_id` must be a `person.*` entity in HA at the time of the write; otherwise 422 naming it, with the
  HA persons that exist. If HA can't be reached or isn't configured the write fails with 503.
- `list_people` (and `GET /people`) returns `{"people": [...], "ha_persons": [{"entity_id", "friendly_name"}] | null,
  "ha_error": null | "<why>"}`. Reading never fails because of HA: when HA is down or not configured, `ha_persons` is
  `null` and `ha_error` says why.

### 4.1 Reaching HA (design §4)

- Under the Supervisor: `http://supervisor/core/api` with `SUPERVISOR_TOKEN` (`homeassistant_api: true`). The server
  only sees the token because `CMD` starts with `with-contenv` (`docs/ha-notes.md`); the Dockerfile gets it now.
  `SUPERVISOR_TOKEN` wins over the variables below.
- Elsewhere: `HA_FITNESS_HA_URL` (HA's base URL; the server adds `/api`) and the token from `HA_FITNESS_HA_TOKEN_FILE`
  (a path), read at each call, so a token written after the server started works without a restart. Without either,
  HA is "not configured".
- The persons are read with `GET /api/states` and filtered to `person.*`. Timeout 10 s.

## 5. Programs

### 5.1 The document

One JSON document per program, validated by one Pydantic model, used by REST, MCP, storage and import/export
(design §3.7):

| Field | Type | Rule | Default |
| --- | --- | --- | --- |
| `name` | string | 1–60 characters; unique, compared with `casefold()` | — |
| `active` | bool | | `true` |
| `weekdays` | list of `mon` `tue` `wed` `thu` `fri` `sat` `sun` | no duplicates, stored in week order; at least one when `active` | — |
| `stations` | list of `{"exercise": <id or name>}` | 1–15; the same exercise may appear twice | — |
| `rounds` | int | 1–10 | 5 |
| `work_seconds` | int | 10–120 | 45 |
| `switch_seconds` | int | 0–60 | 15 |
| `round_rest_seconds` | int | 0–180 | 60 |
| `countdown_seconds` | int | 0, 5 or 10 | 5 |
| `music` | object or null | see below | `null` |

`music` (stored now, used in step 7): `playlist` (required, string 1–200, a Music Assistant URI or name), `speaker`
(required, a `media_player.*` entity id), `volume` (int 0–100 or null; null keeps the speaker's volume; default null),
`shuffle` (bool, default `false`). Not checked against HA in this step. Claude's call: `music` may be `null`, unlike
design §3.1 ("each program also has a playlist and a speaker"), because the playlist and speaker tools arrive in step 7;
step 7 decides what a program without music does.

Defaults are filled in on write, so a stored document is always complete. Stored stations hold the resolved **id**:
`{"exercise": "0001"}`.

### 5.2 What the API returns

A program comes back as `{"id": <int>, "program": <the stored document>, "station_names": [<name per station>],
"total_seconds": <int>, "created_at": …, "updated_at": …}`. `program` is exactly a writable document, so "Claude gets,
edits and sends back" and export → import work unchanged. `id` is never reused (SQLite `AUTOINCREMENT`).
`total_seconds` is design §3.1's S × R × (W + r) + (R − 1) × round rest. Times are UTC ISO 8601.

### 5.3 Writes

- **Create** takes a document; **update** takes a whole document and replaces the stored one. **Set active** changes
  only `active` (switching on a program without weekdays is a 422). **Delete** removes it (Claude's call: a hard
  delete now; step 4 decides how deleting works once training days point at programs).
- Several programs may share a weekday (design §3.2).
- Export is "get" (take `program`); import is "create" with it. Unknown fields are a 422.

## 6. The change log

Every successful write adds one row; a failed write adds none. A row has `at` (UTC), `client`, `action`
(`program.created`, `program.updated`, `program.activated`, `program.deactivated`, `program.deleted`, `people.set`,
`exercise.added`), `target` (e.g. `program:3`, `people`, `exercise:custom-1`) and `summary`: one English line that says
what changed, e.g. "Created program Onsdag", "Updated program Onsdag: rounds 5 → 4, stations", "Set people: Thomas,
Elin". `client` is `mcp:<clientInfo name>` for MCP, from the session's initialize (`mcp:unknown` when there is none), and
`rest:<User-Agent>` (`rest:unknown`) for REST, cut to 100 characters. Read with `GET /api/v1/changes` and the MCP tool
`get_change_log`, newest first, default 20, 1–200. Rows are never changed.

## 7. REST

All under `/api/v1`, JSON, OpenAPI at FastAPI's default `/openapi.json` and `/docs`. Errors use FastAPI's `detail`
(404 not found, 409 name taken, 422 invalid, 503 HA unreachable or not configured).

| Method and path | Does |
| --- | --- |
| `GET /health` | as now (`api_version` stays 1: nothing breaks) |
| `GET /library` | `{"exercises": {"library": n, "custom": n}, "media": {"state", "present", "total"}}` |
| `GET /exercises?q=&equipment=&body_part=&limit=` | search (§3.5) |
| `GET /exercises/{id}` | one exercise, with steps and attribution |
| `POST /exercises` | add a custom exercise (201) |
| `GET /exercises/{id}/gif`, `/thumbnail` | media |
| `GET /programs` | all programs, by name |
| `POST /programs` | create (201) |
| `GET /programs/{id}` | one program |
| `PUT /programs/{id}` | replace |
| `PUT /programs/{id}/active` | body `{"active": bool}` |
| `DELETE /programs/{id}` | delete (204) |
| `GET /people` | people and HA persons (§4) |
| `PUT /people` | body `{"people": [{"name", "person_entity_id"}]}` |
| `GET /changes?limit=` | change log |

## 8. MCP tools

Names fixed here (design §3.7). Each tool's description is written for an LLM: what it does, the ranges and defaults
("5 stations" as the usual choice), and for writes: **"Show the program (or people) to the user and get a yes before
calling."** Annotations: read tools `readOnlyHint: true`; `update_program`, `delete_program` and `set_people`
`destructiveHint: true`; `create_program`, `add_custom_exercise` and `set_program_active` `readOnlyHint: false`,
`destructiveHint: false` (they add or are reversible). Errors come back as MCP tool errors with the same content as
REST's `detail` (a dict as JSON text).

| Tool | Arguments | Returns |
| --- | --- | --- |
| `search_exercises` | `query`, `equipment?`, `body_part?`, `limit?` | as REST |
| `get_exercise` | `exercise_id` | as REST |
| `add_custom_exercise` | `name`, `steps`, `equipment?`, `body_part?`, `target?` | the exercise |
| `list_programs` | — | summaries: `id`, `name`, `active`, `weekdays`, `station_count`, `rounds`, `total_minutes` (rounded) |
| `get_program` | `program_id` | as REST |
| `create_program` | `program` (the document) | as REST |
| `update_program` | `program_id`, `program` | as REST |
| `set_program_active` | `program_id`, `active` | as REST |
| `delete_program` | `program_id` | `{"deleted": id}` |
| `list_people` | — | as REST |
| `set_people` | `people` (list of `{name, person_entity_id}`) | the people |
| `get_change_log` | `limit?` | as REST |

## 9. The Ingress page

`GET /` (D27): the add-on's version, the library (exercises, media `present/total` and state), the people and the
programs (name, on or off, weekdays, minutes). Plain server-rendered HTML with relative links, `color-scheme: light
dark` and no colours of its own. Every text on it, including the weekday names and the on/off and media-state labels,
comes from `addon/server/src/ha_fitness_server/i18n/en.json` and `da.json` (hard rule 6). The language is picked from
the request's `Accept-Language` (the browser's language, not the HA user's as for the cards, D11): Danish when `da` is
preferred, otherwise English. All values are HTML-escaped. No writes from the page.

## 10. Storage and backups

- The database file is `<data folder>/ha_fitness.db`. Alembic migrations ship in the package and run to `head` at
  start, before the server accepts requests. A database at a revision this code doesn't know stops the start with a
  clear log line instead of guessing.
- Tables: `programs` (id `AUTOINCREMENT`, name, `name_key` = `casefold()` of the name with a unique index, active,
  document JSON, created_at, updated_at), `people` (id, name, person_entity_id unique, position), `custom_exercises`
  (number, name, `name_key` unique, document JSON), `change_log` (id, at, client, action, target, summary).
- SQLite runs in WAL mode with foreign keys on.
- **Hot backups** (`backup: hot` stays, so a backup never stops a running workout from step 5 on). A raw copy of a
  WAL database while it runs can be inconsistent, so (Claude's call):
  - `backup_pre` runs `/usr/bin/with-contenv /opt/venv/bin/python -m ha_fitness_server.snapshot`, which writes a
    consistent copy with SQLite's `VACUUM INTO` to a temporary name and renames it to
    `<data folder>/backup/snapshot.db`, so a failed run never leaves a half snapshot. With no database yet it does
    nothing and exits 0 (a non-zero exit fails the add-on's part of the backup).
  - `backup_exclude` leaves out `ha_fitness.db`, `ha_fitness.db-wal`, `ha_fitness.db-shm` and `library/media`. The
    Supervisor matches each pattern against the end of the path (`PurePath.match`), so the snapshot has a name none of
    them matches.
  - At start, when `ha_fitness.db` is missing and `backup/snapshot.db` exists (after a restore), it is copied into
    place before migrating.
    A missing database with an older snapshot brings back the last backup's state; that is intended.
  - The Supervisor's exclude rules can't be tested in pytest: the full loop takes a backup, checks that the add-on's
    archive holds `backup/snapshot.db` and neither the live database nor the media, and restores it (§12).

## 11. Fast loop and seed

- Claude's call, replacing design §4's "a token from a git-ignored `.env`": `scripts/dev_onboard.py` keeps a
  long-lived token for the dev user in `local/dev-ha-token` (mode 600; a dev HA token only). If the file is missing, or
  HA rejects the token in it, it creates a new one (websocket `auth/long_lived_access_token`). `scripts/develop`
  starts the add-on server with `HA_FITNESS_HA_URL=http://localhost:8123` and
  `HA_FITNESS_HA_TOKEN_FILE=<repo>/local/dev-ha-token`; the server reads the file at each call, so running
  `dev_onboard.py` after `scripts/develop` on a fresh `config/` needs no restart. `.env.example` is deleted (nothing
  reads `.env`; `.gitignore` keeps ignoring `.env`).
- `scripts/seed [--ha-url URL] [--server-url URL]` (defaults `http://localhost:8123`, `http://localhost:8765`; design
  §9): refuses unless **both** hosts are `localhost` or `127.0.0.1`, so it can never touch a real HA or a real add-on.
  It logs in to HA as `dev` / `dev` (the dev user, as `dev_onboard.py` does), creates the persons "Thomas" and "Elin"
  over HA's websocket (`person/create`; REST can't) unless a person of that name exists, sets the people through the
  server's REST, and creates the program "Sample" (Wednesday, 5 body-weight stations) unless a program of that name
  exists. A second run changes nothing. The fake speaker comes with step 7.
- The dev MCP entry is named `ha-fitness-dev` (`docs/testing.md`).
- The full loop needs nothing new: the add-on reaches its HA through the Supervisor. `scripts/seed --ha-url
  http://localhost:7123` creates the persons there.

## 12. Releases and PRs

The integration must not release from this step (D19 would install an unchanged 0.2.0 by itself). release-please
counts a commit for the root component unless **every** file in it sits under an excluded folder; root files can't be
excluded (`addon`, `docs`, `scripts`, `tools`, `.github`, `.devcontainer`, `.claude` are, D29). So root files
(`LICENSE`, `README.md`, `CLAUDE.md`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml`, `.env.example`,
`repository.yaml` …) keep releasing the integration when they are in a `feat:` or `fix:` commit. This step therefore
has three PRs:

1. `chore:` before: `.pre-commit-config.yaml` excludes `addon/server/src/ha_fitness_server/library/exercises.json`
   from `check-added-large-files`; `.env.example` is deleted.
2. `feat: programs through chat`: only `addon/`, `scripts/` and `docs/`. It releases the add-on 0.1.0 → 0.2.0 only.
   Tests live in `addon/server/tests/` (the scripts have none; they are checked by running them), never in the root
   `tests/`. The docs it updates:
   - `docs/architecture.md`: "What exists now", "Not built yet", and "Data the add-on reads from HA" (the token file
     instead of `.env`);
   - `docs/testing.md`: the token file, `scripts/seed`, the dev MCP entry `ha-fitness-dev`, the backup check;
   - `addon/DOCS.md`: MCP (and where to add the real endpoint), Ingress, the library download, backups;
   - `docs/domain-language.md`: custom exercises and the change log;
   - `docs/decisions.md`: D30 (§3.1), D31 (§10, hot backups), D32 (§11, the dev token file).
3. `docs:` after: `CLAUDE.md` (Commands: `scripts/seed`; Layout unchanged).

Before the add-on's release PR merges: the full loop with the MCP check and the backup check (§10,
`docs/testing.md`). The `fitness` issue says:
add-on only, and the checks in this spec's header. The release PR waits for Thomas's local test (2026-10-24).

## 13. Tests

Through public interfaces only (hard rule 5): REST responses and MCP tool results (FastMCP's in-memory client). HA and
the media source are fake HTTP servers. The one exception: the "unknown revision" case writes `alembic_version`
directly. Cases that must be covered:

- Every field range edge of §5.1, unknown fields, an active program without weekdays, a duplicate name in other case,
  including `"Lørdag"` vs `"LØRDAG"`.
- Station resolution: by id, by name in other case, the shared name, an unknown name with close matches and the station
  index.
- `total_seconds` for 1 round (no round rest) and for 5 rounds.
- Get → send `program` back unchanged as an update and as a create under a new name: both accepted.
- Ids not reused after deleting the newest program.
- People: keep an id across `set_people`; a third person; a non-person entity; HA down (503 on write, read gives
  `ha_persons: null` and `ha_error`); the token file read after start.
- Change log rows for each write, with `mcp:` and `rest:` clients and a changed-fields summary; nothing for a failed
  write.
- Media: a partial download leaves no file under the real name; a failed file is retried at the next start; 404
  before download.
- Migrations: a fresh database migrates to head; a second start keeps the data; an unknown revision stops the start.
- Backups: the snapshot command writes a database with the same programs; it exits 0 with no database; a start with
  only the snapshot restores it.
- MCP: the tool list has exactly the names of §8, each write tool has its annotations.
- The Ingress page in English and Danish; an HTML-looking program name is escaped; links are relative.

## 14. Left to the plan

Module layout, sync or async SQLAlchemy, how sync work runs off the event loop, the Alembic setup, test fixtures, and
the order of tasks.
