# Programs Through Chat (Step 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The add-on stores programs, people and custom exercises in SQLite, ships the exercise library, downloads its media, and serves REST at `/api/v1` and MCP at `/mcp`, so Thomas can make programs by talking to Claude.

**Architecture:** One sync service layer, held in a `Services` container that the app's lifespan fills (Task 2), in `addon/server/src/ha_fitness_server/` over SQLAlchemy 2 (sync engine, SQLite in WAL mode, Alembic migrations run at start). FastAPI routes (`def`, run in the threadpool) and FastMCP tools (sync, `run_in_thread` default) are thin adapters over it. Domain errors are mapped once per adapter. The media download is one asyncio task started by the app's lifespan.

**Tech Stack:** Python 3.14, FastAPI, FastMCP 4.1.3, SQLAlchemy 2, Alembic, Pydantic 2, httpx, pytest; aiohttp in `scripts/`.

**Spec:** `docs/superpowers/specs/2026-10-24-programs-through-chat-design.md` (step 3), which implements `docs/superpowers/specs/2026-10-23-ha-fitness-design.md` §10 step 3.

**Plan status:** full-reviewer Ready after 2 rounds (2026-10-24); approved by Claude (spec §6; Thomas's night delegation).

## Global Constraints

- All server code in `addon/server/src/ha_fitness_server/`, tests in `addon/server/tests/`. The integration (`custom_components/`) and the cards don't change.
- **This branch touches only `addon/`, `scripts/` and `docs/`** (spec §12): no root file (`LICENSE`, `CLAUDE.md`, `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml` …). A root-file change goes in the follow-up `docs:` PR or a `chore:` PR. PR #17 (`chore:`) already excludes `library/exercises.json` from the large-file hook; this branch is rebased on it.
- The gates of `CLAUDE.md` → *Commands* pass before each commit; server: `uv run --directory addon/server ruff check && … mypy && … pytest`. mypy is strict.
- Tests through public interfaces only (hard rule 5): REST via `httpx.AsyncClient(transport=ASGITransport(app))` inside the app's lifespan, MCP via `fastmcp.Client(<the FastMCP server>)`. Fakes for HA and the media source are `httpx.MockTransport` handlers injected through `create_app(settings, *, ha_transport=None, media_transport=None)`. No test imports a service module to assert on internals; tests may set up state through the public API, and may write raw rows only to create the "unknown revision" case.
- Every UI text (only the Ingress page in this step) comes from `i18n/en.json` / `i18n/da.json`. API error texts and MCP descriptions are English and not UI.
- Never committed: GIFs, `.env`, `config/`, `local/`, `.superpowers/`. `library/exercises.json` (data only, MIT) **is** committed.
- The pinned dataset commit is `7455efae41b330c265e7cd4b78dfa848e7ce5ebd` (one constant, `library.DATASET_COMMIT`, also read by `scripts/build_library.py`).
- `api_version` stays 1. `__version__` and `config.yaml`'s version are release-please's; don't edit them.
- Commits: Conventional Commits, `feat:`/`test:`/`chore:` as fits, with the co-author trailer from the dispatch.
- Every task except the controller's Task 11 is `Model: opus`.
- Subagents never run the fast loop or the full loop (their logs are under `local/`, hard rule 7): those checks are the controller's (Task 11).

## Review Focus

1. **The add-on runs under the Supervisor but can't reach HA** (s6 drops `SUPERVISOR_TOKEN`). → Task 9 puts `with-contenv` in `CMD`; Task 11 step 4 sets people in the full loop, which only works with the token.
2. **A restart during the media download leaves broken GIFs** that are never fetched again. → Task 4 test `test_partial_file_is_not_kept_and_is_fetched_next_start`.
3. **Claude gives an exercise by a name that is close but wrong, or shared**, and gets a silent wrong station. → Task 3 tests `test_resolve_*`; Task 6 test `test_create_with_unknown_exercise_lists_close_matches`.
4. **A program name with HTML breaks or injects into the Ingress page.** → Task 8 test `test_page_escapes_names`.
5. **A failed write still lands in the change log, or a successful one is missing.** → Task 3 and Task 6 tests `test_change_log_*`.

---

### Task 1: The library data

**Model:** opus · **Review:** no (the 721-record and key checks of Step 2 stand in for a review)

**Files:**
- Create: `scripts/build_library.py`, `addon/server/src/ha_fitness_server/library/__init__.py` (holds `DATASET_COMMIT` and `ATTRIBUTION`), `addon/server/src/ha_fitness_server/library/exercises.json`, `addon/server/src/ha_fitness_server/library/NOTICE.md`
- Modify: `addon/server/pyproject.toml` only if the wheel leaves out `library/*.json` (check with `uv build` and `unzip -l`)

**Interfaces:**
- Produces: `ha_fitness_server.library.DATASET_COMMIT: str`, `ATTRIBUTION: str = "© Gym visual — https://gymvisual.com/"`; `exercises.json` is a JSON list sorted by `id`, each `{"id","name","equipment","body_part","target","secondary_muscles","steps","gif","thumbnail"}` (spec §3.1; no per-record attribution).

- [ ] **Step 1:** Write `scripts/build_library.py` (stdlib: `urllib.request`, `json`, `argparse`). It downloads `data/exercises.json` at the commit (or reads `--source <file>`), filters by the five equipment values of spec §3.1, maps `instruction_steps.en` → `steps`, `gif_url` → `gif`, `image` → `thumbnail`, and writes the file with `indent=1`, `ensure_ascii=False`, sorted by `id`, ending with one newline (a re-run gives no diff). It reads `DATASET_COMMIT` by parsing `library/__init__.py` (no import of the server package).
- [ ] **Step 2:** Run `uv run python scripts/build_library.py` twice, with `shasum addon/server/src/ha_fitness_server/library/exercises.json` after each. Expected: it prints `721 exercises` and both sums are equal; `python3 -c "import json;d=json.load(open('addon/server/src/ha_fitness_server/library/exercises.json'));print(len(d), sorted(d[0]))"` prints 721 and the nine keys.
- [ ] **Step 3:** Write `NOTICE.md`: source URL, commit, the dataset's full MIT licence text from its `LICENSE` (copyright line `Copyright (c) 2026 Hasan Emir Yıldırım` included), and "media © Gym visual, not included, downloaded at runtime for personal use".
- [ ] **Step 4:** Gates; commit `chore: add the exercise library data`.

---

### Task 2: Storage and migrations

**Model:** opus · **Review:** yes

**Files:**
- Create: `db.py`, `models.py`, `snapshot.py`, `services.py`, `migrations/__init__.py`, `migrations/env.py`, `migrations/script.py.mako`, `migrations/versions/__init__.py`, `migrations/versions/0001_initial.py`, `errors.py`
- Modify: `app.py` (lifespan opens the database and fills the services), `settings.py`, `pyproject.toml` and `uv.lock` (runtime dependencies `sqlalchemy`, `alembic`, `fastmcp==4.1.3`, `httpx`; fastmcp brings `httpx2`, not `httpx`, so `httpx` must be a runtime dependency for Tasks 4 and 5), `tests/conftest.py`
- Test: `tests/test_storage.py`, `tests/test_health.py` (settings tests updated)

**Interfaces:**
- Produces:
  - `Settings` gains `ha_url: str | None`, `ha_token: str | None`, `ha_token_file: Path | None`, `media_base_url: str`. `from_env()`: if `SUPERVISOR_TOKEN` is set → `ha_url="http://supervisor/core"`, `ha_token=<it>`, `ha_token_file=None` (it wins); else `ha_url` from `HA_FITNESS_HA_URL`, `ha_token=None`, `ha_token_file` from `HA_FITNESS_HA_TOKEN_FILE`. `media_base_url` from `HA_FITNESS_MEDIA_BASE_URL`, default `https://raw.githubusercontent.com/hasaneyldrm/exercises-dataset/<DATASET_COMMIT>`.
  - `db.open_database(data_dir: Path) -> sqlalchemy.Engine` — creates `<data_dir>/ha_fitness.db`, sets `journal_mode=WAL` and `foreign_keys=ON` on every connection, runs Alembic to `head` programmatically (no `alembic.ini`; `script_location` = the package's `migrations`), raises `errors.DatabaseTooNew` when the stored revision isn't one this code knows.
  - `db.session(engine) -> contextmanager[Session]` — commits on success, rolls back on error.
  - `models.py`: tables of spec §10 (`programs` with `sqlite_autoincrement=True`, `people`, `custom_exercises`, `change_log`); `name_key` columns (`str.casefold()` of the name) with unique indexes on `programs` and `custom_exercises`; JSON columns are `sqlalchemy.JSON`; times are timezone-aware UTC.
  - `snapshot.py`: `write_snapshot(data_dir: Path) -> Path | None` (`VACUUM INTO` a temp name in `<data_dir>/backup/`, then `os.replace` to `backup/snapshot.db`; returns `None` and does nothing when there is no database) and a `__main__`-style entry `python -m ha_fitness_server.snapshot` that uses `Settings.from_env().data_dir`; `open_database` first restores `backup/snapshot.db` into place when `ha_fitness.db` is missing (spec §10).
  - `errors.py`: `class NotFound(Exception)`, `class Conflict(Exception)`, `class Invalid(Exception)` (carries `detail: object`, a str or a JSON-able dict), `class Unavailable(Exception)`, `class DatabaseTooNew(Exception)`. These are the only errors adapters map (REST: 404/409/422/503 with `detail`; MCP: `ToolError(detail if str else json.dumps(detail, ensure_ascii=False))`).
  - `services.py`: `@dataclass class Services` with the fields `engine`, and from later tasks `library` (Task 3), `media` (Task 4), `people` (Task 5), `programs` (Task 6) — each task adds its field; and `class ServicesHolder` with `set(services)`, `get() -> Services` (raises `RuntimeError("not started")` before the lifespan ran). `create_app` makes one holder (`app.state.services`), the lifespan fills it; REST routes read it through a FastAPI dependency `get_services(request) -> Services`, and MCP tools (Task 7) call `holder.get()` at call time. So `build_mcp(holder)`, the MCP mount and `combine_lifespans` all happen in `create_app`, before the lifespan.
  - `create_app(settings, *, ha_transport=None, media_transport=None)`: the lifespan opens the database (and, from Task 4, starts the media task) before requests are served; `app.state.engine`.
  - `conftest.py`: a fixture `make_app(**overrides)` builds a **fresh** app per call (from Task 7 the MCP session manager runs once per instance, so a "second start" test builds a second app); an async context helper `running(app)` enters `app.router.lifespan_context(app)` and yields an `httpx.AsyncClient(transport=ASGITransport(app), base_url="http://test")`; the fixture `client` = `running(make_app())`. From Task 4 on, `make_app` passes a fake media transport by default (instant small bytes), so **no test touches the network**.
  - Times: a `UtcDateTime` `TypeDecorator` stores UTC and returns timezone-aware values (SQLite returns naive ones otherwise).
- [ ] **Step 1: Failing tests** in `test_storage.py`:
  - `test_fresh_start_migrates_and_serves` — app on an empty `tmp_path` → `GET /api/v1/health` 200 and `<tmp>/ha_fitness.db` exists.
  - `test_second_start_is_a_noop` — start, stop, start again on the same dir → health 200 (and, after Task 6 exists, a program created in the first run is still listed; add that assertion in Task 6).
  - `test_unknown_revision_stops_the_start` — after a first start, `sqlite3` sets `alembic_version.version_num` to `"9999_future"`; entering the lifespan raises `DatabaseTooNew`.
  - `test_start_restores_snapshot_when_database_missing` — start, stop, run `python -m ha_fitness_server.snapshot` (subprocess, `HA_FITNESS_DATA_DIR` = tmp), delete `ha_fitness.db*`, start a fresh app → health 200 (Task 6 adds: the program created before the snapshot is listed, and the snapshot's `programs` table holds it).
  - `test_snapshot_command_runs` — `subprocess.run([sys.executable, "-m", "ha_fitness_server.snapshot"], env={…, "HA_FITNESS_DATA_DIR": tmp})` exits 0 and `backup/snapshot.db` opens with `sqlite3` and has the `programs` table.
  - `test_snapshot_without_database_exits_0` — same command on an empty dir → exit 0, no snapshot file.
  - Settings tests: `SUPERVISOR_TOKEN` set (also with `HA_FITNESS_HA_*` set) → `ha_url == "http://supervisor/core"` and that token; the two `HA_FITNESS_HA_*` vars → url and token file; neither → `None`.
- [ ] **Step 2:** Run, see them fail for the right reason.
- [ ] **Step 3:** Implement. `0001_initial` creates all four tables (later tasks use them; no further migration in this step).
- [ ] **Step 4:** Tests pass; gates; commit `feat: add the database and migrations`.

---

### Task 3: Exercises, custom exercises and the change log

**Model:** opus · **Review:** yes

**Files:**
- Create: `library/service.py` (`Library`), `changes.py`, `schemas.py`, `api/__init__.py`, `api/deps.py` (`get_services`, `client_from_request`), `api/exercises.py`, `api/library.py` (`GET /library`), `api/changes.py`, `api/errors.py` (exception handlers)
- Modify: `app.py`, `services.py` (field `library`)
- Test: `tests/test_exercises.py`, `tests/test_changes.py`

**Interfaces:**
- Consumes: Task 2's `db`, `errors`, `models`.
- Produces:
  - `Library(engine)`: `search(query: str = "", equipment: str | None = None, body_part: str | None = None, limit: int = 20) -> list[ExerciseSummary]`; `facets() -> dict[str, list[str]]` (`{"equipment": [...], "body_part": [...]}`, sorted); `get(exercise_id: str) -> Exercise` (`NotFound`); `resolve(ref: str, station: int) -> Exercise` (spec §3.5: exact id, else unique casefolded name, else `Invalid({"message": …, "station": station, "close_matches": [{"id","name"}…≤5]})`; a shared name → `Invalid` with the sharing exercises as `close_matches`); `add_custom(new: NewCustomExercise, client: str) -> Exercise` (`Conflict` on a taken name, id `custom-<n>`); `counts() -> dict[str,int]` (`library`, `custom`).
  - Pydantic models in `schemas.py`: `ExerciseSummary {id, name, equipment, body_part, target, custom: bool}`; `Exercise` = summary + `steps`, `secondary_muscles`, `attribution` (`ATTRIBUTION` for library exercises, null for custom); `NewCustomExercise` (spec §3.4 limits, `extra="forbid"`).
  - `changes.record(session, *, client: str, action: str, target: str, summary: str) -> None` — called **inside** the write's session, so a failed write logs nothing; `changes.recent(engine, limit: int = 20) -> list[ChangeEntry]` (newest first, `limit` 1–200).
  - `client_from_request(request) -> str` → `"rest:" + User-Agent` (or `"rest:unknown"`), max 100 chars.
  - Routes of spec §7 for exercises (without media), `GET /changes`, and `GET /library` with `{"exercises": {"library": 721, "custom": n}}` (Task 4 adds `"media"`).
  - Search response shape (REST and MCP): `{"results": [...], "facets": {"equipment": [...], "body_part": [...]} | null}`; facets only when the query and filters are empty.
- [ ] **Step 1: Failing tests**:
  - `test_search_prefix_first` — `q=push-up`: every result contains `push-up`; at least one result starts with it (`push-up`) and at least one doesn't (`side push-up`); every result that starts with it comes before every one that doesn't.
  - `test_search_filters_by_equipment` — `equipment=kettlebell` → every result's equipment is kettlebell.
  - `test_search_limit_bounds` — `limit=0` and `limit=101` → 422; `limit=100` ok.
  - `test_empty_search_returns_facets` — facets list `body weight` and `upper legs`.
  - `test_get_exercise_has_steps_and_attribution` — `GET /exercises/0001` → name `3/4 sit-up`, 5 steps, attribution with "Gym visual"; `GET /exercises/nope` 404.
  - `test_add_custom_exercise` — POST → 201 `custom-1`, then searchable and `custom: true`; second → `custom-2`.
  - `test_custom_name_taken_case_insensitive` — `"3/4 SIT-UP"` → 409; logs nothing; custom `"Æble løft"` then `"ÆBLE LØFT"` → 409.
  - `test_custom_exercise_limits` — empty name, 81-char name, 0 or 11 steps, unknown field → 422.
  - `test_change_log_records_custom_add_with_rest_client` — `User-Agent: pytest` → newest entry `client == "rest:pytest"`, `action == "exercise.added"`, `target == "exercise:custom-1"`.
  - `test_change_log_limit_bounds` — `limit=0`/`201` → 422.
  - `resolve` has no route of its own: its tests (`test_resolve_*`) are in Task 6, through `POST /programs`.
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: search the exercise library and add custom exercises`.

---

### Task 4: Media download and serving

**Model:** opus · **Review:** yes

**Files:**
- Create: `library/media.py`
- Modify: `app.py` (lifespan starts the task and cancels it on shutdown), `services.py` (field `media`), `api/exercises.py` (media routes), `api/library.py` (adds `"media"`), `tests/conftest.py` (default fake media transport)
- Test: `tests/test_media.py`

**Interfaces:**
- Produces: `MediaStore(data_dir: Path, base_url: str, transport: httpx.AsyncBaseTransport | None)`: `state() -> MediaState {state: "idle"|"downloading"|"done"|"failed", present: int, total: int}`; `async download_missing(exercises) -> None` (first deletes every `*.part` in the media folder; 8 concurrent via `asyncio.Semaphore(8)`; each file to `<name>.part` then `os.replace`; per-file errors logged and counted; ends `done` when all present, else `failed`); `path(kind: "gif"|"thumbnail", exercise) -> Path | None` (None if absent). Files live in `<data_dir>/library/media/` under the dataset's basename. `GET /library` adds `"media": MediaState`. `GET /exercises/{id}/gif|thumbnail` → `FileResponse` with `image/gif` / `image/jpeg`, 404 if absent or custom.
- [ ] **Step 1: Failing tests** (the fake media source is a `MockTransport` that serves bytes per path and can be told to fail paths):
  - `test_media_downloads_all_and_serves_gif` — after the task finishes (await it via a test hook: poll `GET /library` until `state == "done"`, bounded) `present == total == 1442` and `GET /exercises/0001/gif` returns the fake bytes with `image/gif`.
  - `test_media_404_before_download_and_for_custom`.
  - `test_failed_file_is_retried_next_start` — first start: one path fails → `failed`, `present == total - 1`; second start with a healthy source → `done`.
  - `test_partial_file_is_not_kept_and_is_fetched_next_start` — the fake raises mid-body for one file; no `<name>` file exists afterwards; the next start (fresh app) fetches it and no `*.part` file remains.
  - The tests use the real 721-record library with an instant fake transport; each test is bounded to 30 s.
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: download and serve the exercise media`.

---

### Task 5: HA access and people

**Model:** opus · **Review:** yes

**Files:**
- Create: `ha.py`, `people.py`, `api/people.py`
- Modify: `app.py`, `services.py` (field `people`), `schemas.py`
- Test: `tests/test_people.py`

**Interfaces:**
- Produces:
  - `HaClient(base_url: str | None, token: str | None, token_file: Path | None, transport=None)`: `persons() -> list[HaPerson {entity_id, friendly_name}]` via `GET {base_url}/api/states` (sync `httpx.Client`, 10 s timeout), filtered to `person.*`; the token is `token`, else the stripped contents of `token_file` read at each call; `Unavailable("Home Assistant isn't configured …")` without URL or token; `Unavailable("Can't reach Home Assistant: …")` on connection errors or non-2xx.
  - `People(engine, ha)`: `list() -> PeopleView {people: [Person {id, name, person_entity_id}], ha_persons: [HaPerson] | null, ha_error: str | null}` (reading never fails because of HA); `set(people: list[NewPerson], client: str) -> list[Person]` (spec §4: ≤2, unique entity ids, all must be HA persons → `Invalid` naming the bad id and listing HA persons; ids kept per entity id; `position` = list order; one change-log row `people.set`, target `people`, summary `Set people: Thomas, Elin`).
  - Routes `GET /people`, `PUT /people` (body `{"people": [...]}`).
- [ ] **Step 1: Failing tests** (fake HA = `MockTransport` returning `person.thomas`, `person.elin`, `light.kitchen`):
  - `test_list_people_shows_ha_persons_only_persons`.
  - `test_set_people_and_keep_ids` — set Thomas+Elin, then Elin+Thomas → same ids, order swapped.
  - `test_person_name_limits` (empty, 41 characters → 422), `test_set_people_rejects_third_person`, `test_set_people_rejects_duplicate_entity`, `test_set_people_rejects_non_person_entity` (`light.kitchen` → 422 naming it).
  - `test_set_people_ha_down_is_503_and_read_still_works` — fake raises `httpx.ConnectError`.
  - `test_set_people_without_ha_config_is_503`.
  - `test_token_file_is_read_per_call` — start with a token file path that doesn't exist yet (`GET /people` → `ha_error` set), write the file, `PUT /people` → 200.
  - `test_change_log_people_set`.
  - `test_ha_auth_header_is_bearer_token` — the fake asserts `Authorization: Bearer <token>`.
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: link people to HA persons`.

---

### Task 6: Programs

**Model:** opus · **Review:** yes

**Files:**
- Create: `programs.py`, `api/programs.py`
- Modify: `schemas.py`, `app.py`, `services.py` (field `programs`), `tests/test_storage.py` (the persistence and snapshot assertions of Task 2)
- Test: `tests/test_programs.py`

**Interfaces:**
- Consumes: `Library.resolve`, `changes.record`.
- Produces:
  - `schemas.ProgramDocument` (spec §5.1, `extra="forbid"` on it and on `StationIn`, `Music`, `NewPerson`, `NewCustomExercise` and the set-active body; defaults filled; `weekdays` normalised to week order; validator: `active` needs ≥1 weekday); `StationIn {exercise: str}`; `Music {playlist, speaker (pattern ^media_player\.[a-z0-9_]+$), volume: int|None 0–100, shuffle=False}`.
  - `schemas.ProgramOut`: `{"id", "program": ProgramDocument (stations as {"exercise": <id>}), "station_names": [str], "total_seconds", "created_at", "updated_at"}` (spec §5.2). `ProgramSummary {id, name, active, weekdays, station_count, rounds, total_minutes}` (`total_minutes` = `round(total_seconds/60)`).
  - `Programs(engine, library)`: `list() -> list[ProgramOut]` (by name, case-insensitive); `summaries()`; `get(id)`; `create(doc, client)`; `replace(id, doc, client)`; `set_active(id, active, client)`; `delete(id, client)`. Name clash → `Conflict`; missing → `NotFound`; resolution → `Invalid` with close matches. Change-log actions `program.created|updated|activated|deactivated|deleted`, target `program:<id>`; summaries `Created program Onsdag`, `Updated program Onsdag: rounds 5 → 4, stations` (top-level fields that differ; `stations`/`music`/`weekdays` named without values), `Deleted program Onsdag`.
  - Routes of spec §7. Ids are SQLite `INTEGER PRIMARY KEY AUTOINCREMENT` (never reused).
- [ ] **Step 1: Failing tests**:
  - `test_create_fills_defaults_and_returns_names` — minimal `{"name","weekdays":["wed"],"stations":[{"exercise":"0001"}]}` → 201; `program` has rounds 5, work 45, switch 15, rest 60, countdown 5, `music: null`, stations `[{"exercise":"0001"}]`; `station_names == ["3/4 sit-up"]`.
  - `test_total_seconds` — 5 stations, 5 rounds, defaults → `5*5*(45+15) + 4*60 = 1740`; 1 round → no rest: `5*1*60 = 300`.
  - `test_field_ranges` — parametrised edges: stations 0/16, rounds 0/11, work 9/121, switch -1/61, rest -1/181, countdown 3, name ""/61 chars → 422; 1/15, 1/10, 10/120, 0/60, 0/180, 0/5/10, 60 chars → 201.
  - `test_unknown_field_is_422`, `test_duplicate_weekday_is_422`, `test_weekdays_stored_in_week_order` (`["sat","wed"]` → `["wed","sat"]`).
  - `test_active_without_weekdays_is_422`; `test_inactive_without_weekdays_ok`; `test_activate_without_weekdays_is_422`.
  - `test_name_unique_case_insensitive` (409), including `"Lørdag"` then `"LØRDAG"`; `test_update_to_another_programs_name_is_409`.
  - `test_times_are_utc_aware` — `created_at` ends in `+00:00` or `Z`.
  - `test_resolve_by_id`, `test_resolve_by_name_other_case` (`"3/4 SIT-UP"` → `0001`), `test_resolve_ambiguous_name_needs_id` (`"self assisted inverse leg curl"` → 422 with both candidates), `test_create_with_unknown_exercise_lists_close_matches` (second station `"pushup"` → 422, `detail.station == 2`, `detail.close_matches` non-empty, each with id and name).
  - `test_same_exercise_twice_ok`.
  - `test_replace_set_active_delete` (404 after delete).
  - `test_ids_not_reused` — create A, B; delete B; create C → C's id > B's.
  - `test_music_validation` (speaker `light.x` → 422; volume 101 → 422).
  - `test_change_log_program_actions` — create/update (rounds 5→4)/deactivate/activate/delete → five rows in order, the update summary contains `rounds 5 → 4`; a 422 create adds none.
  - `test_get_then_send_back` — GET a program; PUT its `program` unchanged → 200 and equal; POST its `program` with a new `name` → 201 with an equal document apart from the name.
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: store and manage programs`.

---

### Task 7: MCP tools

**Model:** opus · **Review:** yes

**Files:**
- Create: `mcp_tools.py`
- Modify: `app.py` (mount per D26: `http_app(path="/mcp")` mounted at `/` after all routes, including Task 8's `GET /` (added later); `combine_lifespans`)
- Test: `tests/test_mcp.py`

**Interfaces:**
- Consumes: the services of Tasks 3, 5, 6.
- Produces: `build_mcp(holder: ServicesHolder) -> FastMCP` with exactly the 12 tools of spec §8, sync functions, Pydantic argument types reused from `schemas.py` (so the JSON schema Claude sees is the API's), descriptions per spec §8 (ranges, defaults "5 stations", "show it and get a yes first" on writes), `ToolAnnotations` per spec §8. Domain errors → `fastmcp.exceptions.ToolError` with the same text as REST (`Invalid` detail dicts as JSON text). The client for the change log: `"mcp:" + ctx.session.client_params.client_info.name` (FastMCP `Context`; verified to work in sync tools in 4.1.3), `"mcp:unknown"` when absent, max 100 chars. `app.state.mcp` holds the server for tests.
  - **Ruling (against spec §8's wording, recorded in the PR):** argument validation that Pydantic does before the tool runs (ranges, unknown fields, the active-without-weekdays validator) comes back as FastMCP's validation text, which names the field and the reason; the domain errors raised by the services (unknown exercise with close matches, name taken, not found, HA unavailable) carry REST's `detail` as JSON. Keeping the Pydantic argument types keeps one JSON schema for REST and MCP, which matters more.
- [ ] **Step 1: Failing tests** (run inside the app's lifespan: `async with running(app): async with fastmcp.Client(app.state.mcp, client_info=mcp.types.Implementation(name="claude-code", version="1")) as c:`):
  - `test_tool_names_are_exactly_the_spec_list`.
  - `test_annotations` — read tools `readOnlyHint is True`; `update_program`, `delete_program`, `set_people` `destructiveHint is True`; `create_program`, `add_custom_exercise`, `set_program_active` `readOnlyHint is False` and `destructiveHint is False` (spec §8).
  - `test_create_and_list_programs_via_mcp` — `create_program` then `list_programs` shows the summary with `total_minutes`.
  - `test_unknown_exercise_error_has_close_matches` — `ToolError` text contains `close_matches`.
  - `test_change_log_client_is_mcp` — after a write by the client named `claude-code`, the newest entry's client is exactly `mcp:claude-code`.
  - `test_out_of_range_field_is_a_tool_error` — `create_program` with `rounds: 11` raises `ToolError` whose text names `rounds`.
  - `test_search_exercises_and_facets_via_mcp`.
  - `test_list_people_via_mcp_with_fake_ha`.
  - `test_http_mcp_endpoint_answers_initialize` — over the ASGI app: `POST /mcp` with an `initialize` JSON-RPC body and `Accept: application/json, text/event-stream` → 200 (no 307).
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: MCP tools for programs, people and exercises`.

---

### Task 8: The Ingress page

**Model:** opus · **Review:** yes

**Files:**
- Create: `ingress.py`, `i18n/en.json`, `i18n/da.json`
- Modify: `app.py` (`GET /` → HTML), `pyproject.toml` only if `unzip -l` on the built wheel shows `i18n/*.json` missing
- Test: `tests/test_ingress.py`

**Interfaces:**
- Produces: `GET /` (spec §9), registered before the MCP mount. The page reads the database only (people from the `people` table, never `People.list()`, which calls HA). Language: the first language tag of `Accept-Language` (ignoring q-values order rules: take the highest q, ties by position) is `da*` → Danish, else English. Both files have the same keys (a test checks). Weekdays use the files' short names. No inline colours; `<meta name="color-scheme" content="light dark">`.
- [ ] **Step 1: Failing tests**:
  - `test_page_in_english_by_default` — contains the English heading text read from `en.json` and the version.
  - `test_page_in_danish` — `Accept-Language: da-DK,da;q=0.9,en;q=0.8` → Danish heading from `da.json`.
  - `test_page_lists_programs_people_and_media_state`.
  - `test_page_escapes_names` — program named `<b>x</b>` appears as `&lt;b&gt;x&lt;/b&gt;`.
  - `test_language_files_have_the_same_keys`.
  - `test_page_links_are_relative` — the page has at least one link, and no `href`/`src` starts with `/` or `http`.
- [ ] **Step 2–4:** fail, implement, pass; gates; commit `feat: the add-on's Ingress page`.

---

### Task 9: Packaging and the fast loop

**Model:** opus · **Review:** yes

**Files:**
- Modify: `addon/Dockerfile` (`CMD ["/usr/bin/with-contenv", "/opt/venv/bin/python", "-m", "ha_fitness_server"]` with a comment why, see `docs/ha-notes.md`), `addon/config.yaml` (`ingress: true`, `ingress_port: 8765`, `panel_icon: mdi:dumbbell`, `panel_title: HA Fitness`, `ports_description` "HA Fitness API (REST and MCP)", `backup_pre: /usr/bin/with-contenv /opt/venv/bin/python -m ha_fitness_server.snapshot`, `backup_exclude: [ha_fitness.db, ha_fitness.db-wal, ha_fitness.db-shm, library/media]`; **no** `discovery` yet), `scripts/dev_onboard.py`, `scripts/develop`, `scripts/full-loop` (`up` passes `--token-file local/full-loop-ha-token`), `addon/DOCS.md` (MCP endpoint `ha-fitness-house` and where to add it, per the spec header; the Ingress page; the library download; backups)
- Create: `scripts/seed`
- No unit tests: the scripts are checked by running them (Step 2). The server-side settings are tested in Task 2.

**Interfaces:**
- `dev_onboard.py`: after onboarding, if `local/dev-ha-token` is missing or HA rejects it (`GET /api/` → 401), creates a long-lived token (websocket `auth/long_lived_access_token`, `client_name: "ha-fitness-dev"`, `lifespan: 3650`) and writes it there with mode 600; a valid existing file is kept. `--token-file` overrides the path; the default `local/dev-ha-token` is relative to the repo root. Its docstring says so.
- `scripts/develop`: exports `HA_FITNESS_HA_URL=http://localhost:8123` and `HA_FITNESS_HA_TOKEN_FILE="$root/local/dev-ha-token"` for the server (the server reads it per call, so a later `dev_onboard.py` needs no restart).
- `scripts/seed [--ha-url URL] [--server-url URL]` (bash wrapper → `scripts/seed.py`, aiohttp; defaults `http://localhost:8123` and `http://localhost:8765`): refuses unless both hosts are `localhost` or `127.0.0.1`; logs in to HA as `dev` / `dev` by reusing `dev_onboard`'s login (so it works for the fast loop and the full loop); lists persons (websocket `person/list`) and creates "Thomas" and "Elin" (`person/create`) when no person has that name; maps each person to its entity id through the entity registry (`config/entity_registry/list`: `platform == "person"` and `unique_id ==` the person's storage `id`), waiting up to 10 s for a new entity to appear; `PUT /api/v1/people` with their entity ids; creates program `Sample` (wed, 5 body-weight stations by id) unless a program of that name exists. Safe to run again.
- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Self-check without the loops: `scripts/seed --ha-url http://example.com` and `scripts/seed --server-url http://example.com:8765` both exit non-zero before any request; `bash -n scripts/seed scripts/develop scripts/full-loop`; `uv run ruff check scripts` and `uv run mypy scripts/seed.py scripts/dev_onboard.py` pass. The running checks are the controller's (Task 11 Step 2).
- [ ] **Step 3:** No image build here: the controller's full loop (Task 11) builds and runs the image.
- [ ] **Step 4:** Gates; commit `chore: fast loop talks to the dev HA; seed script`.

---

### Task 10: Docs

**Model:** opus · **Review:** no

**Files:**
- Modify: `docs/architecture.md` (What exists now: database, library, REST, MCP, Ingress, backups; "Not built yet"; "Data the add-on reads from HA": the token file instead of `.env`), `docs/testing.md` (fast loop: the token file and `scripts/seed`; MCP check: the entry is `ha-fitness-dev`, the step 3 tools; the full loop's backup check as in Task 11 Step 5), `docs/domain-language.md` (custom exercise ids, change log), `docs/decisions.md` (D30: library data built in, media downloaded — spec §3.1; D31: hot backups through a `VACUUM INTO` snapshot — spec §10; D32: the dev HA token lives in `local/dev-ha-token` — spec §11), `docs/ha-notes.md` (`backup_pre`/`backup_exclude` if anything was learned). Not `CLAUDE.md` (a root file): the controller's follow-up `docs:` PR adds `scripts/seed` there.
- [ ] **Step 1:** Write; `uv run python scripts/check_links.py`.
- [ ] **Step 2:** Commit `docs: step 3 docs`.

---

### Task 11: Verification (controller)

**Model:** controller · **Review:** no

- [ ] **Step 1:** All gates on the branch.
- [ ] **Step 2:** Fast loop on a fresh `config/`: `scripts/develop`, `dev_onboard.py`, then **without a restart** `GET /api/v1/people` has `ha_persons` (not `null`); `scripts/seed` twice (the second changes nothing; people Thomas and Elin listed); the MCP check of `docs/testing.md` from Claude Code: add the endpoint as `ha-fitness-dev`, create the Wednesday and Saturday programs in a headless `claude -p` session by asking in plain words, then `list_programs` shows both; delete them again.
- [ ] **Step 3:** Chrome: `http://localhost:8765/` in the fast loop renders the status page with no console errors.
- [ ] **Step 4:** Full loop: `scripts/full-loop install` (rebuilds the image with `with-contenv`), create HA persons in the full-loop HA with `scripts/seed --ha-url http://localhost:7123` (the seed's localhost rule allows it), then `curl localhost:8765/api/v1/people` shows them; the MCP check against `http://localhost:8765/mcp`; the Ingress page at `/app/local_ha_fitness` in Chrome (Danish user → Danish page); `GET /api/v1/library` reaches `done`.
- [ ] **Step 5:** Backup check (spec §10): in the full loop `ha backups new --name t`; open the backup tar inside the container and list the add-on's archive: `backup/snapshot.db` present, `ha_fitness.db*` and `library/media/` absent. Then restore it (`ha backups restore <slug> --app local_ha_fitness`), and check the programs are still listed.
- [ ] **Step 6:** Branch review (`full-reviewer`), PR `feat: programs through chat` (`Closes #3`), merge on green, then the `docs:` PR for `CLAUDE.md`. The release PR stays open until Thomas's local test; after the release, the `fitness` issue (add-on only, the spec header's checks, `docs/releasing.md`).
