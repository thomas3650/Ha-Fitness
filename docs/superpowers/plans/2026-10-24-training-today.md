# Træning i dag (Step 4) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The add-on keeps training days by the due/late/missed/skipped rules and pushes them over a websocket. The integration turns them into entities, a skip service, events and a card subscription. The "Træning i dag" card shows the open days, with a two-step Spring over.

**Architecture:** Two parts, two branches, two PRs (spec §2).

- **Part A** (`feat/training-days`, the add-on) extends step 3's service layer with:
  - a `TrainingDays` service, with an injectable clock and one re-entrant lock;
  - a push hub, fed from worker threads through the event loop;
  - discovery at start.
- **Part B** (`feat/today-card`, the integration and the cards):
  - B1–B5 are built against a fake add-on, an aiohttp test server that speaks the spec's REST and ws protocol. They run in their own worktree, in parallel with step 3 and Part A.
  - B6 starts only once Part B is rebased on a `main` that has Part A.
- **Merge order:** step 3 → A → B.

**Tech Stack:**
- Add-on: Python 3.14, FastAPI websockets, SQLAlchemy 2, Alembic, `tzdata`.
- Integration: HA 2026.10.2, aiohttp, `pytest-homeassistant-custom-component` (phcc), `freezer`.
- Cards: Lit 3, TypeScript, Vitest with happy-dom.

**Spec:** `docs/superpowers/specs/2026-10-24-training-today-design.md`. It builds on `docs/superpowers/specs/2026-10-24-programs-through-chat-design.md` and that spec's plan.

**Plan status:** approved by Claude 2026-10-24 (Thomas's night delegation). full-reviewer round 2: all 16 round-1 findings fixed; its one new finding (`today_view` ↔ `reconcile` recursion) is fixed with `_build_view`. Ruling: approved without a third round — a one-line, mechanical fix.

## Global Constraints

- **Paths.**
  - Part A code lives in `addon/server/src/ha_fitness_server/` and its tests in `addon/server/tests/`.
  - Its dependency files are `addon/server/pyproject.toml` and `addon/server/uv.lock`, never the root ones.
  - Part A touches only `addon/`, `scripts/` and `docs/`.
  - Part B touches `custom_components/`, `cards/`, `tests/`, `scripts/`, `docs/`, and root files if needed (spec §2, D29).
- **The protocol between the parts** is exactly spec §3.5–§3.7 and §4.2. Part B's fake add-on implements only that.
- **Names and texts.**
  - Entity ids, names, keys and translation texts are exactly as in spec §4.3–§4.4 and §6.
  - Every UI text comes from a language file (hard rule 6), in Danish and English.
  - Plurals use `_one`/`_other` keys, for example "1 øvelse" and "5 øvelser".
- **Tests.**
  - Tests go through public interfaces (hard rule 5).
  - Time is frozen for anything time-based:
    - add-on: an injected `Clock`;
    - integration: `freezer` and `async_fire_time_changed`;
    - cards: Vitest fake timers.
  - The integration's tests use `127.0.0.1` URLs only, the one socket phcc allows.
- **Gates and commits.**
  - The gates of `CLAUDE.md` pass before each commit.
  - Commits are Conventional Commits with the co-author trailer from the dispatch.
- **Who runs what.**
  - Subagents never run the fast loop or the full loop: their logs are under `local/` (hard rule 7). Those runs belong to the controller tasks.
  - Every implementer task is `Model: opus`.

## Review Focus

1. **Midnight on a DST Sunday, or after days off, creates or closes the wrong days.** → Task A2 tests with a frozen clock across 2026-03-29 and 2026-10-25 in Europe/Copenhagen, and across a 3-day gap.
2. **A wake tap skips a training day.** → Task B5 tests:
   - one tap never calls the service;
   - Ja ignores taps for 0.5 s;
   - Nej sits where Spring over was.
3. **The card leaves an empty row, or never comes back after hiding.** → Task B5 tests:
   - `hidden` and `card-visibility-changed` are set;
   - `connectedWhileHidden` is set;
   - hidden, then a day opens, then the card shows.

   Task B7 checks the same in Chrome.
4. **The integration never recovers after the add-on restarts.** → Task B3 test: the fake add-on closes the ws, the entities go unavailable, it comes back, and the entities return.
5. **Entity ids differ on a Danish HA.** → Task B3 test with `hass.config.language = "da"` asserts the exact ids.

---

## Part A — add-on (`feat/training-days`, from `main` after step 3 is merged)

### Task A1: Training days storage, settings and the clock

**Model:** opus · **Review:** yes

**Files** (in `addon/server/`):
- Create:
  - `src/ha_fitness_server/migrations/versions/0002_training_days.py`
  - `src/ha_fitness_server/clock.py`
- Modify:
  - `src/ha_fitness_server/models.py`: `training_days` and `scheduler_state`.
  - `src/ha_fitness_server/settings.py`.
  - `src/ha_fitness_server/app.py`: `create_app(..., clock=None, supervisor_transport=None)`.
  - `src/ha_fitness_server/db.py`: a new `migrate(engine, revision="head")`, which `open_database` now uses.
  - `pyproject.toml` and `uv.lock`: add `tzdata`.
  - `tests/conftest.py`.
- Test: `tests/test_settings_timezone.py`, `tests/test_storage.py`

**Interfaces:**
- **The clock.** `Clock` is a protocol with `now() -> datetime`, which returns an aware UTC time. `SystemClock` implements it. `conftest.py` gets `FrozenClock(start)` with `set()` and `advance()`.
- **Settings.** All new fields have defaults, so `Settings(port=0, data_dir=…)` still works.

  | Field | Source | Default |
  | --- | --- | --- |
  | `timezone: ZoneInfo` | `HA_FITNESS_TIMEZONE`, else `TZ` | UTC. An unknown name logs and falls back to UTC. |
  | `dev: bool` | `HA_FITNESS_DEV == "1"` | `False` |
  | `scheduler_interval: float` | — | `60.0` |
  | `supervisor_token: str \| None` | `SUPERVISOR_TOKEN` | `None` |

  Step 3's HA settings keep reading `SUPERVISOR_TOKEN` as they do now.
- **`make_app`.** It becomes `make_app(settings_overrides: dict | None = None, **create_app_kwargs)`, which builds a fresh app each time. `settings_overrides` replaces `Settings` fields through `dataclasses.replace`.
- **Tables.**
  - `training_days` follows spec §3.1. The pair `(program_id, date)` is unique. `program_id` is a foreign key with `ON DELETE SET NULL`, and `status` is a string enum.
  - `scheduler_state` has one row with `last_date`, which is null until the first run.

- [ ] **Step 1: Write the failing tests.**
  - `test_timezone_precedence`:
    - `HA_FITNESS_TIMEZONE` wins over `TZ`;
    - `TZ` alone is used;
    - neither gives UTC;
    - `Mars/Base` gives UTC and logs it. Check through `caplog` by record level only, not by text.
  - `test_new_settings_defaults`.
  - `test_migration_0002_keeps_programs`:
    - Build a 0001 database with `db.migrate(engine, "0001")`. **Ruling:** this is the second raw-database exception, and it is for setup only.
    - Insert one `programs` row with raw SQL.
    - Start a fresh app. `GET /api/v1/programs` lists the program.
    - `GET /api/v1/training-days?from=…&to=…` should answer 200, but that route arrives in A2, so add this assertion there.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: training days table, settings and the clock`.

### Task A2: The scheduler and the read routes

**Model:** opus · **Review:** yes

**Files** (in `addon/server/`):
- Create:
  - `src/ha_fitness_server/training_days.py`
  - `src/ha_fitness_server/api/today.py`: `GET /api/v1/today` and `GET /api/v1/training-days`
- Modify:
  - `src/ha_fitness_server/programs.py`.
  - `src/ha_fitness_server/services.py`: add the field `training_days`.
  - `src/ha_fitness_server/app.py`: the lifespan reconciles at start, then loops every `scheduler_interval` with `await anyio.to_thread.run_sync(training_days.reconcile_now)`.
- Test: `tests/test_scheduler.py`

**Interfaces:**
- **The service.** `TrainingDays(engine, clock, timezone, publish)`.
  - `publish` is a callable `(message: dict) -> None` that is safe to call from any thread. A4 provides the real one; until then it is a no-op.
  - One `threading.RLock` per service is taken by every public method. Program writes call into the service as well, so the lock is re-entrant and nothing deadlocks.
- **Methods:**
  - `reconcile_now() -> None` runs `reconcile(local_today())`.
  - `reconcile(today: date)` applies spec §3.3, including the re-run of today. It records `last_date` and calls `publish` for the events of §3.6.
  - `_build_view(today: date) -> TodayView` builds the JSON of spec §3.5 **without** reconciling.
  - `today_view() -> TodayView` reconciles first, then calls `_build_view`.
  - `in_range(start: date, end: date) -> list[TrainingDayOut]` also reconciles first.
  - `skip(day_id: int, client: str) -> TrainingDayOut`, `upsert_open(program_id, date)` and `delete_date(date)` belong to A3. Leave them out here.
- **Publishing `today`.** After each `reconcile` (and, later, each skip, program write and dev call), the service computes `today_view()`. It does this with `_build_view(local_today())`, never the reconciling `today_view()`. When that differs from the last view it published, it publishes `{"type": "today", "data": …}`. This covers the midnight rollover, and program edits that only change `station_count` or `total_minutes`.
- **Wiring.** The lifespan builds `TrainingDays` first and passes it to `Programs(engine, library, training_days)`. `Programs` takes the `TrainingDays` lock around each write.
- **The program-write hook.** `Programs` calls `training_days.on_program_written(session, before: ProgramRow | None, after: ProgramRow | None)`.
  - It runs **inside** the write's session, **before** the commit and before a delete, so it still sees the program's open days.
  - It removes open days when a program is switched off or deleted.
  - It renames open days when a program is renamed.
  - After the commit, `Programs` calls `training_days.reconcile_now()`.
  - All of this happens under the service lock (the RLock).

- [ ] **Step 1: Write the failing tests.**
  - They go through REST with `FrozenClock` and the timezone `Europe/Copenhagen`: advance the clock, then `GET /api/v1/today` or `/training-days`.
  - They cover the cases of spec §7 "Add-on", except skip, ws, discovery, the dev routes and MCP:
    - `test_midnight_creates_due_days`
    - `test_passed_day_reads_late`
    - `test_next_training_day_closes_late_as_missed`
    - `test_date_without_days_closes_nothing`
    - `test_catch_up_after_three_days_off`
    - `test_first_run_makes_up_nothing`
    - `test_create_on_training_day_makes_today_and_closes_late`
    - `test_update_active_false_removes_open_days`
    - `test_rename_updates_open_days`
    - `test_delete_removes_open_keeps_closed`
    - `test_two_programs_one_date_by_name`
    - `test_removing_today_from_weekdays_keeps_todays_day`
    - `test_next_is_null_without_active_programs`
    - `test_dst_sundays_one_rollover_each` (2026-03-29 and 2026-10-25)
  - Also add the `/training-days` assertion that A1 deferred to `test_migration_0002_keeps_programs`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: the scheduler`.

### Task A3: Skip, MCP tools and the dev routes

**Model:** opus · **Review:** yes

**Files** (in `addon/server/`):
- Create: `src/ha_fitness_server/api/dev.py`
- Modify:
  - `src/ha_fitness_server/training_days.py`: `skip`, `upsert_open` and `delete_date`.
  - `src/ha_fitness_server/api/today.py`: the skip route.
  - `src/ha_fitness_server/mcp_tools.py`: `get_today` (`readOnlyHint: true`) and `skip_training_day` (`destructiveHint: true`).
  - `src/ha_fitness_server/app.py`: include the dev router only when `settings.dev` is set.
- Test:
  - `tests/test_skip.py` and `tests/test_dev_routes.py`.
  - `tests/test_mcp.py`: the tool list grows to 14, `test_annotations` covers the new tools, and two new tests are added.

**Interfaces:**
- `POST /api/v1/training-days/{id}/skip` returns 200, 404 or 409.
- `POST /api/v1/dev/training-days` (`{program_id, date}`) and `DELETE /api/v1/dev/training-days?date=` follow spec §3.5.
- A skip writes the change-log row of spec §3.4.

- [ ] **Step 1: Write the failing tests.**
  - `test_skip_closes_open_day_and_logs`
  - `test_skipped_day_is_not_made_again`
  - `test_skip_closed_day_is_409`
  - `test_skip_unknown_is_404`
  - `test_dev_routes_absent_without_flag`: both routes give 404 and neither is in `/openapi.json`.
  - `test_dev_post_creates_late_day_and_reopens_closed`
  - `test_dev_delete_removes_open_and_closed`
  - `test_get_today_tool_equals_rest`
  - `test_skip_tool_logs_mcp_client` (`mcp:claude-code`)
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: skip, MCP tools and dev routes`.

### Task A4: The push channel and discovery

**Model:** opus · **Review:** yes

**Files** (in `addon/server/`):
- Create:
  - `src/ha_fitness_server/push.py`
  - `src/ha_fitness_server/api/ws.py`
  - `src/ha_fitness_server/discovery.py`
- Modify:
  - `src/ha_fitness_server/app.py`: the lifespan captures the running loop and hands `TrainingDays` a `publish` that does `loop.call_soon_threadsafe(hub.broadcast, message)`. It also announces discovery.
  - `addon/config.yaml`: `discovery: [ha_fitness]`.
- Test: `tests/test_ws.py`, `tests/test_discovery.py`

**Interfaces:**
- **The hub.** `Hub.broadcast(message)` puts the message on each subscriber's `asyncio.Queue`. `Hub.subscribe()` is an async context manager that yields a queue.
- **The websocket.** `GET /api/v1/ws` follows spec §3.6: it sends `hello`, then the current `today`, then whatever arrives on the queue.
- **Discovery.** The lifespan calls `discovery.announce(settings, transport)` when `settings.supervisor_token` is set.
  - It reads `http://supervisor/addons/self/info`.
  - It posts to `/discovery` with `Authorization: Bearer <token>`.
  - A failure is logged at WARNING, and the start goes on. The lifespan runs it as a task with a 10 s timeout, so a slow Supervisor never delays the start.

- [ ] **Step 1: Write the failing tests.**
  - The ws tests use `with TestClient(app) as tc:` for both REST and ws. Never combine that with `running(app)`: the lifespan runs only once.
  - `receive_json()` has no timeout, so each test asserts on the exact next message. A missing message then shows up as a wrong message, not a hang. Use `pytest-timeout`'s `@pytest.mark.timeout(10)` if it is already available; otherwise keep the messages in a fixed order.
  - They use `settings_overrides={"scheduler_interval": 0.05}` and a `FrozenClock`.
  - The tests:
    - `test_ws_hello_then_today`
    - `test_skip_publishes_today_and_skipped`
    - `test_midnight_publishes_today_without_creates`
    - `test_due_event_only_for_today`
    - `test_missed_event_when_next_day_begins`
    - `test_discovery_posts_hostname` (`supervisor_transport` is a `MockTransport`, and `supervisor_token` is set)
    - `test_no_token_no_discovery`
    - `test_discovery_failure_does_not_stop_start`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: push channel and discovery`.

### Task A5: Fast-loop scripts for training days

**Model:** opus · **Review:** yes

**Files:**
- `scripts/develop`: set `HA_FITNESS_DEV=1` and `HA_FITNESS_TIMEZONE=Europe/Copenhagen`.
- `scripts/dev_onboard.py`: set the dev HA's timezone through the websocket call `config/core/update` (`time_zone`).
- `scripts/seed.py`: add `--today` and `--late`, exactly as in spec §8. `--late` refuses before it changes anything.

- [ ] **Step 1:** Implement.
- [ ] **Step 2:** Check:
  - `bash -n scripts/develop scripts/seed`
  - `uv run ruff check scripts`
  - `uv run mypy scripts/seed.py scripts/dev_onboard.py`
  - `seed --late --server-url http://example.com:8765` exits non-zero before it sends any request.
- [ ] **Step 3:** Commit `chore: fast loop for training days`.

### Task A6: Docs for Part A

**Model:** opus · **Review:** no

**Files:**
- `addon/DOCS.md`: discovery and the timezone.
- `docs/architecture.md`:
  - what exists now;
  - the ws protocol as part of the contract;
  - "Data the add-on reads from HA": the timezone now comes from `TZ`.
- `docs/domain-language.md`: training days are now also created during the day.
- `docs/testing.md`: `seed --today` and `--late`, and the dev routes.
- `docs/decisions.md`: D33, D34 and D35 (spec §10).

- [ ] Write the docs, run `check_links.py`, and commit `docs: training days`.

### Task A7: Verification (controller)

**Model:** controller · **Review:** no

- [ ] Run the gates.
- [ ] Fast loop:
  - `seed --today`: `GET /today` shows one due day;
  - skip with `curl`: nothing is open;
  - `seed --late`: one late day;
  - the MCP check with `get_today` from Claude Code.
- [ ] Full loop: install, then check that the add-on log shows discovery was sent and the HA log has no errors.
- [ ] Branch review, then the PR `feat: training days` (#4 closes with Part B). Merge on green.

---

## Part B — integration and card (`feat/today-card`, worktree from `main`)

### Task B1: Config flow v2, migration, the health client and the fake add-on

**Model:** opus · **Review:** yes

**Files:**
- Modify in `custom_components/ha_fitness/`:
  - `manifest.json`: drop `single_config_entry`.
  - `config_flow.py`.
  - `__init__.py`: add `async_migrate_entry`.
  - `const.py`.
  - `strings.json`, `translations/en.json` and `translations/da.json`.
- Create:
  - `custom_components/ha_fitness/client.py`, with only `async_health(session, url) -> dict` for now. B2 extends it.
  - `tests/fake_addon.py`: class `FakeAddon`, which builds an aiohttp `web.Application`.
    - Routes:
      - `/api/v1/health`;
      - `/api/v1/today`;
      - `/api/v1/training-days/{id}/skip`, which records the `User-Agent`;
      - `/api/v1/ws`.
    - Settable fields: `today`, `api_version`, `skip_status`, and `old_addon`. With `old_addon` set, it rejects the ws handshake with 403 and answers 404 on `/today`.
    - Methods: `close_ws()` and `push(message)`.
- Modify: `tests/conftest.py`.
  - The fixture `fake_addon` uses `aiohttp_server` (from pytest-aiohttp, which phcc brings), so its URL is `http://127.0.0.1:<port>`.
  - `config_entry` becomes a **version 2** entry with `data={"url": fake_addon.url}` and the unique id `ha_fitness`.
- Test: `tests/test_config_flow.py`

**Interfaces:** spec §4.1.
- `VERSION = 2`.
- The entry data is `{"url": str}`.
- The unique id is `"ha_fitness"`.
- The hassio step builds the url from `discovery_info.config["host"]` and `["port"]`.

- [ ] **Step 1: Write the failing tests.**
  - `test_user_step_checks_health_and_creates_entry`
  - `test_user_step_cannot_connect`
  - `test_second_entry_already_configured`
  - `test_hassio_discovery_creates_entry` (with `title_placeholders`)
  - `test_hassio_discovery_updates_existing_url`
  - `test_migrate_v1_sets_url_and_unique_id`: a v1 entry with `data={}`. Patch `custom_components.ha_fitness.async_setup_entry` to return True, so nothing connects to `localhost`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: config flow with discovery and a URL`.

### Task B2: The connection and the repair issues

**Model:** opus · **Review:** yes

**Files:**
- Modify: `custom_components/ha_fitness/client.py`.
  - `skip` sends `User-Agent: ha_fitness/<version>`.
  - The ws loop parses `hello`, `today` and `event`, and ignores unknown types.
- Create: `custom_components/ha_fitness/coordinator.py`. `FitnessCoordinator` holds `today`, `connected` and `addon_version`, and keeps a list of listeners.
- Modify:
  - `__init__.py`: setup creates the coordinator and starts the ws loop with `entry.async_create_background_task`. Setup **never waits** for the first connect, so there is no `ConfigEntryNotReady`. Unload cancels the loop.
  - `strings.json` and the translations: the repair issues.
- Test: `tests/test_repairs.py`

**Interfaces:**
- **Backoff.** It uses `async_call_later` with `HassJob(..., cancel_on_shutdown=True)`: 1, 2, 5 and 10 s, then every 30 s. Unload cancels the pending timer. Tests drive it with `freezer.tick()` and `async_fire_time_changed`, and each test unloads its entry, so phcc's `verify_cleanup` finds no lingering timer.
- **Logging.** An unreachable add-on is logged at WARNING, once per outage, never at ERROR, because `scripts/smoke` fails on ERROR.
- **Repair issues** (spec §4.2):
  - `unsupported_api_version`: the add-on reports an `api_version` other than 1.
  - `addon_too_old`: the ws handshake is rejected with an HTTP status while `/health` answers and `/today` gives 404.
  - A supported connect deletes both.

- [ ] **Step 1: Write the failing tests.** They observe the issue registry.
  - `test_api_version_3_raises_issue`
  - `test_old_addon_raises_addon_too_old`
  - `test_supported_connect_deletes_issues`
  - `test_setup_does_not_wait_for_addon`: the entry points at `http://127.0.0.1:<unused_tcp_port>` with nothing listening, and the entry is `LOADED`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: connect to the add-on`.

### Task B3: Entities, the service, events and the subscription

**Model:** opus · **Review:** yes

**Files:**
- Create in `custom_components/ha_fitness/`: `entity.py`, `sensor.py`, `binary_sensor.py`, `services.py`, `services.yaml`, `websocket_api.py`.
- Modify:
  - `__init__.py`: `async_setup` registers the service and the ws command. Add `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)` and `PLATFORMS`.
  - `strings.json` and the translations.
- Test: `tests/test_entities.py`, `tests/test_service.py`, `tests/test_websocket.py`, `tests/test_events.py`

**Interfaces:** spec §4.3–§4.5.
- **Entities.** Each sets an explicit `entity_id`, which HA uses as the suggested object id. The attributes go in `_unrecorded_attributes`.
- **The device.** `sw_version` is updated through `dr.async_get(hass).async_update_device(…)` when `hello` arrives.
- **The service.** When no entry is loaded, it raises `unavailable`.
- **Events:** `ha_fitness_training_day_<event>`.
- **The ws command.** `ha_fitness/today/subscribe` sends `null` while disconnected.

- [ ] **Step 1: Write the failing tests.**
  - `test_entity_ids_on_danish_ha`
  - `test_states_and_attributes_from_today`
  - `test_unavailable_on_disconnect_and_back_on_reconnect`
  - `test_device_sw_version_from_hello`
  - `test_skip_service_ok_and_user_agent`
  - `test_skip_service_not_found_not_open_unavailable`
  - `test_events_fired_with_data`
  - `test_subscription_sends_data_and_null`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: entities, skip service, events and the card subscription`.

### Task B4: The card's texts and language

**Model:** opus · **Review:** yes

**Files:**
- `cards/src/i18n/en.json` and `da.json`: every text of spec §6, the weekday names, and the plural keys.
- `cards/src/i18n/index.ts`: `localize(language, key, vars?)`, with `_one`/`_other` plurals.
- `cards/src/language.ts`: the language comes from the `language` option, else `hass.locale.language`, else `en`.

**Tests:** `cards/test/i18n.test.ts` checks that both files have the same keys and that the plural choice is right. The language choice itself is tested through the card in B5.

**The picker entry.** At module load there is no `hass`, so the picker entry uses the English file's name and description. Update the existing test to read them from `en.json`.

- [ ] See the tests fail, implement, see them pass, then run `npm run lint/test/build`. Commit `feat: card texts`.

### Task B5: The today card

**Model:** opus · **Review:** yes

**Files:**
- `cards/src/today-card.ts`.
- `cards/src/today-data.ts`: the subscription logic.
- Test: `cards/test/today-card.test.ts`. The data module is tested through the card.

**Interfaces:** spec §6 exactly, plus:
- **Staying subscribed while hidden.** HA's `hui-card` removes a hidden element from the DOM unless that element has `connectedWhileHidden` set. So the card sets `connectedWhileHidden = true` and stays subscribed while hidden.
- **Hiding**, as HA's own cards do:
  - `this.toggleAttribute("hidden", h)`;
  - `this.style.display = h ? "none" : ""`;
  - dispatch `card-visibility-changed` with `detail: {value: !h}`, bubbling and composed.
- **Skipping** calls `hass.callService("ha_fitness", "skip", {training_day_id}, undefined, false)`, so HA shows no toast of its own. The card shows its own error text, chosen by `err.translation_key`.

- [ ] **Step 1: Write the failing tests**, with fake timers and a fake `hass` (a `callService` spy and a fake `connection.subscribeMessage`):
  - `due and late rows in da and en`
  - `hides when nothing open and returns when a day opens`
  - `in preview never hides and shows the note`
  - `one tap never skips`
  - `Nej in place of Spring over`
  - `Ja ignores taps for 0.5 s`
  - `Ja calls skip with notifyOnError false`
  - `10 s timeout cancels`
  - `error text from translation_key for 5 s`
  - `unreachable line`
  - `language option wins`
  - `grid options 2 rows per day`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then run lint, test and build. Commit `feat: the Træning i dag card`.

### Task B6: Fast-loop scripts and docs for Part B

**Model:** opus · **Review:** yes

This task starts only after Part B is rebased on a `main` that has Part A.

**Files:**
- `scripts/dev_onboard.py`:
  - `_add_entry` posts `{"url": "http://localhost:8765"}` through the user step;
  - it treats `already_configured` as done;
  - it creates the dev dashboard `ha-fitness-dev`, a sections view holding the card.
- The docs of spec §10, PR 2:
  - `docs/architecture.md`, including the pointer to D36;
  - `docs/domain-language.md`;
  - `docs/testing.md`, with B7's Chrome steps;
  - `docs/ha-notes.md`: `single_config_entry` against discovery; Danish entity ids; `hidden`, `connectedWhileHidden` and `card-visibility-changed`; `callService`'s `notifyOnError`.
- Decisions D36, D37 and D38.

- [ ] Implement, then run `uv run mypy scripts/dev_onboard.py` and `check_links.py`. Commit `chore: dev onboarding for the integration` and `docs: Træning i dag`.

### Task B7: Verification and the house issue (controller)

**Model:** controller · **Review:** no

- [ ] Run the gates and `scripts/smoke`: no ERROR from `ha_fitness`.
- [ ] Fast loop. In Chrome at 1368×912, as the Danish user, take screenshots for the PR:
  - `seed --today`: one due day;
  - skip with two taps: the card hides;
  - `seed --late`: the card comes back **without a reload**, showing "Forfalden · <weekday>";
  - edit mode: the note;
  - add-on stopped: the unreachable line;
  - the console is clean.
- [ ] Full loop: the Discovered card, setup, the entities, and the card on a test dashboard.
- [ ] Branch review, then the PR `feat: Træning i dag card and entities` (`Closes #4`). Merge on green.
- [ ] After both releases, which come after Thomas's local test, open a `fitness` issue for both parts. It covers:
  - the install order: the integration first, then accept the Discovered card;
  - the card's placement proposal, with `grid_options`, the visibility rule `state_not: "off"` on `binary_sensor.ha_fitness_training_open`, and `language: da`;
  - the unreachable line during updates;
  - the checks after installing.
