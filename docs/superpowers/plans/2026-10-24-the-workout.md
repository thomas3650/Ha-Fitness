# The Workout (Step 5) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run a circuit workout on the kitchen tablet.
- The add-on runs the session engine and pushes the state.
- The integration relays sessions, exposes the session-running sensor, services and events, and proxies GIFs.
- A full-screen flow runs details → get ready → timer (1 or 2 people) → done, with pings.

**Architecture:** Three parts, three branches, three PRs, one component each (spec §2).
- **Part S** (`feat/sessions`, add-on) extends steps 3–4's services:
  - a `Sessions` service under step 4's RLock and clock;
  - a deadline-driven loop;
  - finishing rules that close training days.
- **Part E** (`feat/session-entities`, integration) extends step 4 Part B's client, coordinator and websocket API.
- **Part F** (`feat/workout-flow`, cards) extends Part B's today card with:
  - a page-level `<dialog>` overlay controller;
  - the `ha-fitness-workout-flow` element;
  - an audio module.

Parts E and F start from `feat/today-card` in their own worktrees and use fakes. They rebase once step 4 is merged. Merge order: step 4 A → step 4 B → S → E → F. The integration's release PR waits for F.

**Tech Stack:**
- Add-on: Python 3.14, FastAPI and websockets, SQLAlchemy 2, Alembic, FastMCP 4.1.3.
- Integration: HA 2026.10.2, aiohttp, pytest-homeassistant-custom-component (phcc).
- Cards: Lit 3, TypeScript, Vitest with happy-dom, Web Audio.

**Spec:** `docs/superpowers/specs/2026-10-24-the-workout-design.md` (steps 3–4 are its base).

**Plan status:** approved by Claude 2026-10-24 (Thomas's night delegation). full-reviewer round 1: 19 findings, all addressed; round 2: all 19 confirmed, one new finding ("a session is active" = running or paused) fixed by definition. Ruling: approved without a third round, because the fix is a definition plus one test.

## Global Constraints

- **Paths.** Each part touches only these:
  - Part S: `addon/server/` (sources in `src/ha_fitness_server/`, tests in `tests/`, `pyproject.toml`, `uv.lock`), `addon/DOCS.md`, `scripts/` and `docs/`.
  - Part E: `custom_components/ha_fitness/`, `tests/` and `docs/`.
  - Part F: `cards/` and `docs/`.
- **The protocol between the parts** is exactly spec §3.5 and §4. That covers the session view, the `session` message, the events, the session routes' error `detail` `{code, message}`, and the shapes of `ha_fitness/programs` and `ha_fitness/people`.
  - Part E's fake add-on (`tests/fake_addon.py`, from step 4) grows only what §3.5 says.
  - Part F's fake `hass` mirrors §4's ws commands.
- **Texts.** Every UI text comes from a language file, in Danish and English. Exercise and program names are data.
- **Tests.**
  - Tests go through public interfaces (hard rule 5).
  - Time is frozen in every part: the add-on's `FrozenClock`, the integration's `freezer`, Vitest's fake timers.
  - The integration's tests use `127.0.0.1` only.
- **Gates and commits.** The gates in `CLAUDE.md` pass before every commit. Commits are Conventional Commits with the co-author trailer.
- **Who runs what.**
  - Subagents never run the fast or full loop; the controller tasks do.
  - Every implementer task is `Model: opus`.
- **"A session is active"** means `state.session?.status` is `running` or `paused`; a finished view (kept 5 minutes) is not active. Cards and the flow use this wherever the spec says "a session exists".
- **Decisions** are numbered next at merge, after step 4's.

## Review Focus

1. **A restart or a long pause completes or blocks a workout wrongly.** S3 tests these cases:
   - a shutdown pauses the session;
   - a crash start pauses it at `last_tick_at`;
   - the 30-minute pause limit;
   - a crash longer than 30 minutes ends it at once.
2. **The tablet's countdown drifts from the add-on's phases.** E1 tests the fresh `server_time` and the advance of `time_trained`. F3 tests:
   - the offset;
   - the change at local zero;
   - the revision rule;
   - that unavailable keeps the last view.
3. **The overlay disappears at the finish, or traps the kiosk.** F1 tests:
   - the overlay survives its card;
   - a `cancel` event is prevented.

   F3 tests Luk after 10 s unreachable. F6 checks in Chrome that the overlay sits above the header.
4. **A wake tap starts or ends a workout.** F2 tests the 60 s idle guard. F3 tests Slut's two taps with the 0.5 s guard.
5. **The pings are late or doubled after a pause or skip.** F4 tests:
   - beeps at 5…1 s;
   - no beep in the first 0.3 s;
   - rescheduling after a change;
   - the change tone at local zero.

---

## Part S — add-on (`feat/sessions`, from `main` after step 4 Part A is merged)

Paths below are relative to `addon/server/` unless they start with `addon/`, `scripts/` or `docs/`.

### Task S1: Sessions storage, the plan, start and read

**Model:** opus · **Review:** yes

**Files:**
- Create:
  - `src/ha_fitness_server/sessions.py`;
  - `src/ha_fitness_server/api/session.py`;
  - `src/ha_fitness_server/migrations/versions/0003_sessions.py`.
- Modify:
  - `src/ha_fitness_server/models.py`;
  - `src/ha_fitness_server/schemas.py`;
  - `src/ha_fitness_server/errors.py`;
  - `src/ha_fitness_server/api/errors.py`;
  - `src/ha_fitness_server/api/__init__.py`, which includes the session router in `api_router`;
  - `src/ha_fitness_server/services.py`;
  - `src/ha_fitness_server/app.py`;
  - `src/ha_fitness_server/training_days.py`, which gets a public `local_date(moment: datetime) -> date` (the timezone conversion).
- Test: `tests/test_session_start.py`

**Interfaces:**
- **Tables:**
  - `sessions`, with the fields of spec §3.2. `plan` is JSON, `revision` is an int, and `last_tick_at` is a UtcDateTime.
  - `session_participants`: `session_id` (FK to sessions), `position`, `person_id` (no FK) and `name`.
  - `app_state`: one row holding `counting_from: date | None`.
- **Errors:** `errors.SessionError(status: int, code: str, message: str)`. `api/errors.py` maps it to that status with `detail = {"code", "message"}`. It is used by the session routes only; steps 3–4 routes keep their shapes. MCP tools turn it into JSON text.
- **The service:** `Sessions(engine, clock, training_days, programs, people, publish)`. It uses `training_days.lock`, the shared RLock.
  - `start(program_id: int, participants: list[int], training_day_id: int | None, client: str) -> SessionView`. The participant rules of spec §3.5 are checked here: 1–2 people, unique, existing, at most S, otherwise 422 `invalid`. The rules on the program, the day and "one session at a time" give 404 or 409.
  - `current() -> SessionView | None` (S2 adds the tick).
- **The plan:** `build_plan(program_out, participants: list[(id, name)]) -> Plan`, with the phases and stations of spec §3.1. The stations follow the `next` rule.
- **The view:** `SessionView` follows spec §3.5. `revision` starts at 1. `time_trained` is live.
- **Routes:** `GET /api/v1/session` and `POST /api/v1/session`. The body is `{program_id, participants: list[int], training_day_id?}`, with no length constraints in the schema.

- [ ] **Step 1: Write the failing tests.**
  - `test_start_returns_view_at_phase_0` (countdown) and `test_start_without_countdown_begins_at_work`.
  - `test_planned_total_excludes_countdown_and_last_switch`.
  - `test_start_validation_codes`: each 404, 409 and 422 case of spec §3.5, each with `detail.code`.
  - `test_one_session_at_a_time_running`.
  - `test_participant_names_frozen_in_view`: start, then set the people without that person; the view keeps the name.
  - `test_start_logs_session_started`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: start a session`.

### Task S2: The tick, commands, finishing and history

**Model:** opus · **Review:** yes

**Files:**
- Modify:
  - `sessions.py`: `tick(now)`, `pause`, `resume`, `next`, `previous`, `end`, finishing, and `finished(limit)`;
  - `training_days.py`: reconcile skips an open day that has a running or paused session; skipping such a day gives 409; a counted session closes its day as `done`;
  - `programs.py`: a 409 for switching off or deleting the program of a running or paused session, including an extra session and a `PUT` with `active: false`, with the message of spec §3.4;
  - `api/session.py`: `POST /api/v1/session/{command}` and `GET /api/v1/sessions?limit=` (default 20, 1–100), shaped `{counting_from, sessions}` per spec §3.5.
- Test: `tests/test_session_plan_walk.py`, `tests/test_session_commands.py`, `tests/test_session_finish.py`

**Interfaces:**
- **The tick** runs under the lock.
  - Every command, and every read of `GET /session`, ticks first.
  - `tick(now)` moves running sessions on by chaining `phase_started_at`. One tick publishes at most one `session` message and one `phase_changed` event.
  - It writes `last_tick_at` every 5 s and at every phase change.
  - For paused sessions it checks only the pause limit (S3 adds the limit; here keep a hook).
- **History.** `finished(limit)` builds participants from `session_participants`. `counting_from` comes from `app_state`. Both are the public read of history (`GET /sessions`).

- [ ] **Step 1: Write the failing tests.** They use `FrozenClock` and are driven through REST.
  - **The plan walk:**
    - `test_phase_sequence_edge_values`: walk with `next` and ticks; no switch after the last interval; rest left out when 0; countdown 0; switch 0; 1 round; 1 station.
    - `test_stations_current_and_next_per_phase_kind`: 1 and 2 people. A switch shows s+1; a rest shows p; `next` is null on the last work phase and on every phase leading only to it.
  - **The tick:** `test_tick_moves_several_phases_without_drift_one_event_per_tick`.
  - **Commands:**
    - `test_pause_resume_moves_ends_at`.
    - `test_pause_during_countdown_not_in_paused_seconds`.
    - `test_next_previous_each_phase_kind_running_and_paused`, including the 3 s rule and the countdown.
    - `test_command_after_deadline_acts_on_new_phase`: tick first.
    - `test_next_on_last_work_completes`.
    - `test_end_while_paused_closes_open_pause`.
  - **Finishing:**
    - `test_end_with_zero_rounds_not_counted_day_open`.
    - `test_end_after_one_round_counted_day_done`.
    - `test_completed`.
    - `test_done_late_and_not_late_across_midnight`.
  - **The day and the program under a session:**
    - `test_reconcile_skips_in_session_day`.
    - `test_skip_in_session_day_is_409`: REST and the MCP `skip_training_day`.
    - `test_program_off_put_active_false_or_delete_during_session_is_409`: also for an extra session.
    - `test_extra_session_closes_no_day`.
    - `test_one_session_at_a_time_paused`.
  - **History:**
    - `test_counting_from_set_once`, via `GET /sessions`.
    - `test_participant_rows_for_finished_sessions`: rows are stored for every finished session, counted or not. After removing the person, `GET /sessions` still lists them by name, also for an uncounted ended session.
  - **The view:**
    - `test_get_session_keeps_finished_view_five_minutes`.
    - `test_revision_increases`.
    - `test_change_log_completed_by_tick_client_addon`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: session commands, finishing and history`.

### Task S3: The loop, restarts, the pause limit, push, MCP and the shutdown snapshot

**Model:** opus · **Review:** yes

**Files:**
- Modify:
  - `sessions.py`: `recover()`, `pause_for_shutdown()` and the pause limit.
  - `settings.py`: `session_tick_max: float = 1.0`.
  - `app.py`:
    - The session loop wakes at `min(next deadline, settings.session_tick_max)`, where `session_tick_max` defaults to 1.0 and is a new `Settings` field. It runs `tick` via `anyio.to_thread.run_sync`. It also sends the `session: null` push when a finished view's 5 minutes end.
    - The lifespan calls `recover()` after migrating. On shutdown it calls `pause_for_shutdown()`, then `snapshot.write_snapshot(data_dir)`.
    - `create_app(..., skip_shutdown: bool = False)` is a test-only flag that skips the shutdown hooks, to simulate a crash.
  - `push.py`, `api/ws.py`: the `session` message on connect after `today`; the session events and `done`.
  - `mcp_tools.py`: `get_session` and `list_sessions`, both read-only. `list_sessions` returns the same `{counting_from, sessions}` as REST, and `test_annotations` covers both tools as read-only.
- Test: `tests/test_session_restart.py`, `tests/test_session_push.py`, `tests/test_mcp.py` (now 16 tools)

- [ ] **Step 1: Write the failing tests.**
  - **Restarts:**
    - `test_shutdown_pauses_running_session`.
    - `test_crash_start_pauses_at_last_tick_no_skips`. The **first** app runs with `skip_shutdown=True`. Advance the `FrozenClock` past at least one 5 s `last_tick_at` write, then stop it. A second app starts 10 minutes later; its view is paused and `phase.remaining` equals the value as of `last_tick_at`.
    - `test_crash_longer_than_30_minutes_ends_at_start`.
  - **The pause limit and the null push:**
    - `test_pause_limit_ends_after_30_minutes`, seen through `GET /session` and ws.
    - `test_null_push_after_finished_window`.
  - **The websocket:**
    - `test_ws_session_after_today_on_connect`.
    - `test_loop_wakes_at_deadline`: ws with `TestClient` alone; advance the `FrozenClock` past a phase deadline; `session` and `phase_changed` arrive with no request.
    - `test_ws_events_session_started_completed_ended_done`.
  - **Snapshot and MCP:**
    - `test_shutdown_snapshot_holds_latest_program`.
    - `test_mcp_get_session_and_list_sessions`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: session loop, restarts, push and the shutdown snapshot`.

### Task S4: Seed and docs (Part S)

**Model:** opus · **Review:** yes, because the seed has logic

**Files:**
- `scripts/seed.py`: `--short` per spec §7.
  - It creates "Kort" if missing, or else updates its weekdays to today's only and switches it on.
  - It reopens today's day through the dev route.
- The docs of spec §7, PR 1:
  - `docs/architecture.md`;
  - `docs/domain-language.md`;
  - `docs/testing.md`;
  - `addon/DOCS.md`;
  - `docs/decisions.md`.

- [ ] **Steps:**
  - Implement.
  - Run `uv run ruff check scripts`, `uv run mypy scripts/seed.py` and `check_links.py`.
  - Check that `seed --short --server-url http://example.com:8765` exits non-zero.
  - Commit `chore: seed a short program` and `docs: sessions`.

### Task S5: Verification (controller)

**Model:** controller · **Review:** no

- [ ] Gates. Fast loop:
  - `seed --short`;
  - start, pause, next and end through `curl`;
  - a full short session completes and the day is done.
- [ ] Full loop:
  - install;
  - a session, with the add-on restarted mid-session: it comes back paused;
  - **#20**: stop the add-on, run `ha backups new`, and the archive's `backup/snapshot.db` holds the latest program.
- [ ] Branch review, then the PR `feat: sessions` and the merge. The add-on's release PR waits for Thomas's local test, like every release this night.

---

## Part E — integration (`feat/session-entities`, worktree from `feat/today-card`, rebased on main after step 4 merges)

### Task E1: The session relay, the sensor and the subscription

**Model:** opus · **Review:** yes

**Files:**
- Modify:
  - `client.py`: parse `session` messages and the new events (`session_started`, `session_completed`, `session_ended`, `phase_changed`, `done`).
  - `coordinator.py`:
    - It holds `session` (the last view) and `session_seen: bool`.
    - After `hello` it starts a background task of the entry (cancelled on unload). The task probes `GET /api/v1/session`; a 404 while `/health` answers raises `addon_too_old`. `_handle_hello` deletes the issue on every hello, so the probe raises it again on each reconnect, as intended.
  - `websocket_api.py`: `ha_fitness/session/subscribe` sends `{available, session}`.
    - It compares the add-on's **raw** views without `server_time` (never the adjusted message it last sent).
    - On each send it sets `server_time` to now. While the session is running and past the countdown it also adds (now − the add-on's `server_time`) to `time_trained`.
    - While unavailable it sends `{available: false, session: <last known view>}`.
  - `binary_sensor.py`: `session_running` (spec §4). Its `available` overrides the shared one: available only when connected **and** `session_seen`.
  - `strings.json` and the translations: the sensor name.
  - `const.py`: the event list gains `done`.
  - `tests/fake_addon.py`: `/api/v1/session`, session pushes and events, and a new mode `no_sessions` that answers 404 on `/session`. This mode is separate from `old_addon`, which refuses the ws.
- Test: `tests/test_session_entities.py`

- [ ] **Step 1: Write the failing tests.**
  - `test_sensor_unavailable_until_first_session_message_then_on_off`.
  - `test_sensor_unavailable_on_disconnect`.
  - `test_events_fired_with_data`.
  - `test_subscription_fresh_server_time_and_time_trained`. Using the freezer: subscribe, tick 30 s, subscribe a second time. The second message's `server_time` is 30 s later and `time_trained` is 30 s higher. A push that differs only in `server_time` sends nothing.
  - `test_subscription_unavailable_keeps_last_view`.
  - `test_no_sessions_mode_raises_addon_too_old_after_hello`.
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: relay sessions and the session-running sensor`.

### Task E2: Services, commands and the media proxy

**Model:** opus · **Review:** yes

**Files:**
- Modify:
  - `client.py`: `start_session`, `session_command`, `programs()`, `people()`, `media(exercise_id, kind)`.
  - `services.py` and `services.yaml`: `start_session` and `end_session`.
  - `websocket_api.py`:
    - `ha_fitness/session/command` (`command` plus the start arguments);
    - `ha_fitness/programs`, built from the add-on's `GET /api/v1/programs`: only the active programs, zipping `station_names` with each `{exercise}`. `total_minutes` is `(total_seconds + 30) // 60`, as step 3 rounds;
    - `ha_fitness/people`, from the add-on's `GET /api/v1/people`, taking its `people` list.
  - The translations.
- Modify: `__init__.py`, which registers the media view once per HA run.
- Create: `media.py`, a `HomeAssistantView` (requires auth) at `/api/ha_fitness/media/{exercise_id}/{kind}`.
  - Patterns: `^(\d{4}|custom-[1-9]\d*)$` for the id, and `gif` or `thumbnail` for the kind; anything else gives 404 with no relay.
  - It relays with `Cache-Control: private, max-age=86400`.
  - A 404 passes through. An unreachable add-on gives 503.
- `tests/fake_addon.py`: the matching routes.
- Test: `tests/test_session_services.py`, `tests/test_media_proxy.py`

**Interfaces:**
- Error codes `not_found`, `conflict`, `invalid` and `unavailable`, taken from the add-on's `detail.code`.
- The ws commands need no admin.
- The shapes of `ha_fitness/programs` and `ha_fitness/people` are exactly those of spec §4.

- [ ] **Step 1: Write the failing tests.**
  - `test_start_and_end_services_and_errors`
  - `test_ws_command_relays_and_maps_errors`
  - `test_ws_programs_shape_active_only`
  - `test_ws_people_shape`
  - `test_non_admin_can_use_commands`
  - `test_media_requires_auth`
  - `test_media_rejects_bad_id_or_kind_without_relay`
  - `test_media_relays_bytes_and_cache_header`
  - `test_media_404_and_503`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, run the gates. Commit `feat: session services, commands and the media proxy`.

### Task E3: Docs (Part E)

**Model:** opus · **Review:** no

- [ ] Write the docs of spec §7, PR 2: `docs/architecture.md`, `docs/ha-notes.md` and the decision. Run `check_links.py`, then commit `docs: session entities and media proxy`.

### Task E4: Verification (controller)

**Model:** controller · **Review:** no

- [ ] Run the gates and `scripts/smoke`.
- [ ] Once Part S is merged, rebase and check in the fast loop against the real add-on:
  - the sensor through a short session;
  - the services;
  - the media proxy (a GIF through a logged-in browser, and a 401 without login).
- [ ] Branch review, then the PR `feat: session entities and media proxy` and the merge. Hold the integration's release PR until Part F is merged.

---

## Part F — cards (`feat/workout-flow`, worktree from `feat/today-card`, rebased later)

### Task F1: The overlay controller, the audio module and the image cache

**Model:** opus · **Review:** yes

**Files:**
- Create: `cards/src/overlay.ts`, `cards/src/audio.ts`, `cards/src/images.ts`.
- Test: `cards/test/overlay.test.ts`, `cards/test/audio.test.ts`, `cards/test/images.test.ts`.

**Interfaces:**
- **`overlay.ts`**, a module-level controller:
  - **`setHass(hass)`.** Every card calls it on each `hass` change. On the first call the controller subscribes to `ha_fitness/session/subscribe`, using `{resubscribe: false}` and resubscribing on the connection's `ready` event (step 4's pattern). It keeps the latest `hass`.
  - **`state(): {available: boolean, session: SessionView | null}`** and **`subscribe(listener) -> unsubscribe`.** Cards use these to show Fortsæt or "Træning i gang" when a session is active.
  - The flow element gets `state` as a live property that the controller sets on every change (the flow doesn't subscribe itself).
  - **`open(mode)`.** `mode` is `{kind: "details", programId, trainingDayId?}` or `{kind: "resume"}`. It creates one `<dialog>` in `document.body` if none exists, puts a `ha-fitness-workout-flow` in it, and opens it with `showModal()`. The flow gets `hass`, `state`, `mode` and `onClose`.
  - **`close()`.** Closes and removes the dialog.
  - **While open:** the `cancel` event is prevented, backdrop clicks are ignored, and scrolling is locked (`document.documentElement.style.overflow = "hidden"`, restored on close).
- **`audio.ts`:**
  - `unlockAudio()` creates or resumes one module-level `AudioContext`. It must be called synchronously in a tap handler.
  - `audioLocked(): boolean`.
  - `scheduleTone(kind: "beep" | "work" | "rest" | "chime", atEpochMs: number, nowEpochMs: number) -> () => void` (cancel). It maps to `ctx.currentTime + (atEpochMs - nowEpochMs) / 1000` and starts an oscillator at that `when`.
- **`images.ts`:** `imageUrl(hass, exerciseId, kind) -> Promise<string | null>` goes through `hass.fetchWithAuth("/api/ha_fitness/media/…")`. A page-wide `Map` holds the object URLs; a 404 or other error gives null.

- [ ] **Step 1: Write the failing tests.** The fake `AudioContext` records `oscillator.start(when)` and the frequency.
  - `opens one dialog in body that survives the opening card's removal`
  - `cancel event is prevented and the dialog stays open` (dispatch a cancelable `cancel` and check `defaultPrevented`)
  - `backdrop click ignored`
  - `scroll locked while open and restored on close`
  - `subscribes from first setHass with resubscribe false; listeners get state`
  - `unlockAudio creates one context synchronously`
  - `scheduleTone maps epoch ms to context time and cancels`
  - `images cached per exercise and kind; 404 gives null`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then lint, test and build. Commit `feat: overlay, audio and images for the workout flow`.

### Task F2: The flow — details and get ready

**Model:** opus · **Review:** yes

**Files:**
- Create: `cards/src/workout-flow.ts`, the element `ha-fitness-workout-flow`.
- Modify: `cards/src/i18n/en.json` and `da.json`.
- Test: `cards/test/workout-flow-details.test.ts`

**Interfaces:**
- **Which step shows:**
  - Details is local, shown when `mode.kind == "details"` and no session is active.
  - Otherwise the step comes from the flow's newest view by F3's revision rule. That is the command result or the push, whichever is newer, so details never lingers after Start:
    - a running or paused session in its countdown → get ready;
    - work, switch or rest → timer;
    - `completed` or `ended` → done.
  - After Annullér the flow calls `onClose` at once and never shows the done step for that session.
- **Details** (spec §5.2 step 1):
  - It fetches `ha_fitness/programs` and `ha_fitness/people` when it opens.
  - Chips: the colour follows people order; both are preselected only if S ≥ 2; 1–2 can be chosen, at most S; with no people, the no-people text shows.
  - The 60 s idle guard calls `onClose`.
  - **Start** calls `unlockAudio()` synchronously, then sends `ha_fitness/session/command` `{command: "start", program_id, participants, training_day_id?}`.
  - **Errors:**
    - `conflict` while a session is active gives "already running";
    - any other `conflict` gives "can't start now";
    - `not_found`, `invalid` and `unavailable` each have their own text.
- **Get ready** (spec §5.2 step 2): who starts where, **Start nu** (`next`), **Annullér** (`end`, then close), and pause.

- [ ] **Step 1: Write the failing tests.**
  - `details shows program, stations with thumbnails, rounds and seconds`
  - `chips colours by people order`
  - `preselect both only when stations >= 2`
  - `select 1..2 and at most stations`
  - `no people disables Start`
  - `idle 60 s closes`
  - `Start unlocks audio before the command resolves` (assert the fake context exists while `callWS` is pending)
  - `Start sends participants and training day`
  - `error texts per code`
  - `get ready shows start stations; Start nu sends next; Annullér sends end and closes without done`
  - `renders in Danish and English`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then lint, test and build. Commit `feat: workout details and get ready`.

### Task F3: The timer and done

**Model:** opus · **Review:** yes

**Files:**
- Modify: `cards/src/workout-flow.ts` and the i18n files.
- Create: `cards/src/ring.ts`, an SVG ring with `role="progressbar"`, `aria-valuemin`, `aria-valuemax` and `aria-valuenow`.
- Test: `cards/test/workout-flow-timer.test.ts`

**Interfaces** (spec §5.2 steps 3–4, §5.3):
- **The message rule:**
  - The offset `server_time − Date.now()` updates on **every** message.
  - The view applies only when its `revision` is higher for the same session id, or when it is a different session.
  - `{available: false}` keeps the last view and counts down locally.
- **Rendering:**
  - The seconds are rounded up.
  - At local zero it shows the next phase's word.
  - The 1-person layout shows the current station big and Næste beside it. The 2-person layout has one panel per person.
  - Header: Runde, Interval, and elapsed (`time_trained` + the time since `server_time` while running past the countdown) against `totals.planned`.
- **Controls:**
  - pause and resume; tapping the ring pauses;
  - previous and next;
  - Slut asks twice with the 0.5 s Ja guard, then sends `end`.
- **Unreachable:** the note shows, the countdown holds at zero, and **Luk** appears after 10 s.
- **Done:** counted or not counted, then Luk; it closes by itself after 60 s.

- [ ] **Step 1: Write the failing tests.**
  - `timer text and ring from a view with a clock offset`
  - `seconds rounded up`
  - `local zero shows next phase word`
  - `older revision ignored; new session applied`
  - `pause, resume and ring tap`
  - `previous and next send commands`
  - `Slut two taps with guard`
  - `one-person and two-person layouts in work and switch`
  - `elapsed from time_trained and server_time`
  - `unreachable keeps counting, holds at zero, Luk after 10 s`
  - `done counted and not counted; auto-close 60 s`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then lint, test and build. Commit `feat: the workout timer and done`.

### Task F4: The pings

**Model:** opus · **Review:** yes

**Files:**
- Modify: `cards/src/workout-flow.ts`, which schedules tones through `audio.ts` from the corrected local clock.
- Test: `cards/test/workout-flow-pings.test.ts`, which reads the fake context's recorded `start(when)` and frequency.

**Interfaces:** spec §5.4.
- On every applied view, pause, resume or command it cancels all pending tones and schedules them again.

- [ ] **Step 1: Write the failing tests.**
  - `beeps at 5,4,3,2,1`
  - `short phase beeps only its seconds`
  - `no beep in first 0.3 s`
  - `rescheduled after pause, next and newer revision`
  - `work and switch/rest tones at local zero`
  - `completion chime`
  - `Tryk for lyd when locked`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then lint, test and build. Commit `feat: workout pings`.

### Task F5: Start and Fortsæt on the today card, and the workout card

**Model:** opus · **Review:** yes

**Files:**
- Modify:
  - `cards/src/today-card.ts`:
    - it calls `overlay.setHass` and listens with `overlay.subscribe`;
    - **Start** calls `unlockAudio()` synchronously, then `overlay.open({kind: "details", programId, trainingDayId})`;
    - while a session is active, the card shows "Træning i gang" and **Fortsæt** (unlock, then `open({kind: "resume"})`) and hides Spring over;
    - it stays visible while a session is active.
  - `cards/src/index.ts`.
- Create: `cards/src/workout-card.ts` (`ha-fitness-workout-card`). It lists the active programs (`ha_fitness/programs`, fetched on connect and before each Start), each with **Start**, which opens an extra session. While a session is active it shows Fortsæt.
- Modify: the i18n files and the picker entries.
- Test: `cards/test/today-card.test.ts` (extended), `cards/test/workout-card.test.ts`.

- [ ] **Step 1: Write the failing tests.**
  - `Start opens overlay with the day, nothing started, audio unlocked synchronously`
  - `Fortsæt while session active unlocks audio and resumes; Spring over hidden`
  - `after a completed view the today card shows no Fortsæt and hides when nothing is open`
  - `today card visible during extra session with nothing open`
  - `workout card lists active programs and refetches before Start`
  - `workout card Start opens details without training day`
  - `workout card Fortsæt`
- [ ] **Steps 2–4:** See them fail, implement, see them pass, then lint, test and build. Commit `feat: Start, Fortsæt and the workout card`.

### Task F6: Docs and verification (Part F)

**Model:** opus (docs), then controller · **Review:** no

- [ ] **Docs:** spec §7 PR 3 (`docs/testing.md`, `docs/ha-notes.md`, the decisions). Run `check_links.py`, then commit.
- [ ] **Controller, Chrome at 1368×912**, in a sections view with the header showing, as the Danish user:
  - the overlay sits above the header;
  - details;
  - get ready;
  - the timer for 1 and 2 people, in work and in switch;
  - paused;
  - done;
  - Fortsæt after a reload;
  - the today card stays visible during an extra session;
  - a clean console;
  - a real short run with `seed --short`, listening to the beeps.
- [ ] **Full loop:**
  - a session from the today card;
  - the sensor on and off;
  - the GIFs through the proxy.
- [ ] **Finish:**
  - Branch review, then the PR and the merge.
  - After all three PRs are merged and released (after Thomas's test), open the `fitness` issue of spec §8.
