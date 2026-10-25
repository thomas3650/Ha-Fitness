# Today ahead, late days, the start beep and the language fix: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repo, `docs/way-of-working.md` wins over the skill: `implementer` per task, `task-reviewer` on `Review: yes`.

**Goal:** Late days stay open per program for `late_days` days, a program's next training can be done early from the
today card, every work phase starts with a long beep (and the one after the countdown no longer gets lost), and a
non-string `language` no longer breaks a card.

**Architecture:** The add-on owns the rules: the closing rule and `late_days` in the scheduler (`training_days.py`),
`upcoming` in the today view, and the early start in the session engine (`sessions.py`). The integration relays a new
optional `date` on the start. The cards show upcoming rows, play the long beep and fix the tone race.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, pytest (add-on); Home Assistant custom integration, pytest (HA); Lit,
TypeScript, Vitest (cards).

**Spec:** `docs/superpowers/specs/2026-10-25-today-ahead-and-start-beep-design.md`. Every task reads it; section
numbers below are the spec's.

## Global Constraints

- `late_days`: integer 0–6, default **2**. `days_ahead`: integer 0–6, default **0**.
- `upcoming` and `next` search **14** days ahead; `next` is null only when no program is active.
- The long beep is about **1 s**; the quiet time after a work start is at least its length; switch and rest keep
  `QUIET_MS` (0.3 s).
- `api_version` stays 1. No release may need a newer other part: the integration sends `date` only when the add-on's
  last today data has `upcoming`.
- Hard rule 5: tests through public interfaces (REST, MCP, push messages, services, websocket commands, entity states,
  rendered text and roles), a frozen clock for anything time-based, no snapshot or exact-log tests.
- Hard rule 6: every UI text in a language file, English and Danish. Exercise and program names are never translated.
- Commits: Conventional Commits with the co-author trailer from the dispatch, `git commit -F <file>`.
- The gates in `CLAUDE.md` pass before every commit.

## Review Focus

1. **Midnight during an early session:** the session crosses into the day's date. The day must turn due under D42,
   leave `upcoming`, and send no `due` event; a counted finish closes it done, an uncounted one leaves it due with a
   `due` event. Tests in Task 3.
2. **A program write during an early session:** a weekday edit that drops the early day's weekday must not remove or
   duplicate the day, and the finish still closes it. Test in Task 3.
3. **An older add-on with a new integration:** `ha_fitness.start_session` with `date` is refused before any relay, with
   its own translated message. Test in Task 4.
4. **A phase view that arrives before local zero:** the change tone still plays, once. Tests in Task 6.
5. **The card on an older add-on:** no `upcoming` key renders exactly as today, also with `days_ahead` set. Test in
   Task 7.

---

### Task 1: Late days stay open per program (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/settings.py`, `training_days.py`, `app.py`
- Modify: `addon/config.yaml`; create `addon/translations/en.yaml`, `addon/translations/da.yaml`
- Modify: `addon/DOCS.md`; `scripts/develop` and `docs/testing.md` if the fast loop sets it
- Test: `addon/server/tests/test_scheduler.py`, `addon/server/tests/test_settings_late_days.py` (new),
  `addon/server/tests/test_dev_routes.py`

**Interfaces:**
- Produces: `Settings.late_days: int` (default `DEFAULT_LATE_DAYS = 2`); `TrainingDays(engine, clock, timezone,
  publish, late_days: int = DEFAULT_LATE_DAYS)`. `open` in the today view sorted by date, then program name ignoring
  case, then id.

- [ ] **Step 1: Write the failing tests** in `test_scheduler.py` (use `make_app(settings_overrides={"late_days": n})`
  and the file's `FrozenClock`, `local`, `_create`, `_today`, `_open`, `_days`, `_statuses` helpers):
  - `test_other_programs_day_keeps_late_day_open`: replaces `test_next_training_day_closes_late_as_missed`. Onsdag
    (wed) and Lørdag (sat), `late_days` 6; on Sat 2026-10-31 00:05 `_open` is
    `[("Onsdag", "2026-10-28", "late"), ("Lørdag", "2026-10-31", "due")]` (late first: by date).
  - `test_own_program_closes_late_day`: one program on mon and wed, `late_days` 2; Mon 2026-10-26 untouched; Tue reads
    it late; Wed 00:05 shows only Wednesday due, and Monday's status is `missed` with `closed_at` set.
  - `test_late_days_up_closes_late_day`: one program on mon and fri, `late_days` 2; Monday open on Wed 2026-10-28
    23:59; missed on Thu 2026-10-29 00:05.
  - `test_late_days_zero_never_late`: `late_days` 0; a Wednesday day is `missed` at Thursday 00:05.
  - `test_default_late_days_is_two`: no override; mon/fri program; Monday open on Wednesday, missed on Thursday.
  - `test_lowered_late_days_closes_at_start`: data folder from a run with `late_days` 6 and a Monday late on Friday;
    a new app on the same folder with `late_days` 2 shows it `missed` at its first read.
  - `test_weekday_edit_adding_today_closes_late_day_at_once`: mon program, Monday late on Tuesday 10:00; the program's
    weekdays become mon and tue; Monday is `missed`, Tuesday `due`.
  - `test_session_keeps_late_day_open_across_own_next_day` (D42): mon/wed program, Monday late; a session for
    Monday's day started Tue 23:50 (`POST /api/v1/session` with `training_day_id`); at Wed 00:05 `open` holds both
    Monday (late) and Wednesday (due).
- [ ] **Step 2:** `test_settings_late_days.py`: `Settings.from_env()` reads `late_days` from
  `<HA_FITNESS_DATA_DIR>/options.json` (`{"late_days": 4}` → 4); `HA_FITNESS_LATE_DAYS=1` wins over the file; no file
  and no variable → 2; a value outside 0–6 or not an integer → 2 (a warning; don't assert its text).
- [ ] **Step 3: Run them to see them fail:** `uv run --directory addon/server pytest tests/test_scheduler.py
  tests/test_settings_late_days.py -q`. Expected: the new tests fail.
- [ ] **Step 4: Implement.** In `TrainingDays._handle`, replace the "close every earlier open day" query: for a date
  `day`, an open day `d` (not under a session, `~_in_session`) with `d.date < day` closes as missed when its program
  has a training day dated after `d.date` and at most `day`, or when `day > d.date + late_days`. Keep the event order
  and `closed_at`. Sort `open` in `_build_view` by `(date, name.casefold(), id)`. Pass `settings.late_days` in
  `app.py`. In `upsert_open` keep the refusal of a date after today, with the reason in the message: an open day dated
  after today would show as due (spec §2.1.7).
- [ ] **Step 5: The add-on option.** `addon/config.yaml`: `options: {late_days: 2}`, `schema: {late_days:
  "int(0,6)"}`. `addon/translations/en.yaml` and `da.yaml` give `configuration.late_days.name` and `.description`
  (en: "Days a missed training stays open" / "How many days after its date a training you missed can still be done.
  It closes earlier when the same program trains again. 0 closes it at midnight."; da: "Dage en forfalden træning er
  åben" / "Hvor mange dage efter sin dato en forfalden træning kan tages. Den lukker før, hvis samme program træner
  igen. 0 lukker den ved midnat."). `addon/DOCS.md`: the option, and that it takes effect at the add-on's next start.
  If the fast loop should set it, `scripts/develop` exports `HA_FITNESS_LATE_DAYS` only when the caller set it, and
  `docs/testing.md` says so.
- [ ] **Step 6: Run** the add-on gates (`CLAUDE.md`). Expected: all pass, coverage as before.
- [ ] **Step 7: Commit** `feat(addon): late training days stay open per program, for late_days days`.

### Task 2: `upcoming`, `startable` and the next training day (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/schemas.py`, `training_days.py`, `mcp_tools.py` (the `get_today`
  docstring)
- Test: `addon/server/tests/test_today_upcoming.py` (new), `addon/server/tests/test_scheduler.py` (the `next` tests)

**Interfaces:**
- Consumes: Task 1's closing rule.
- Produces: `class UpcomingTraining(BaseModel)`: `program_id: int`, `program_name: str`, `date: dt.date`,
  `station_count: int`, `rounds: int`, `total_minutes: int`, `startable: bool`. `TodayView.upcoming:
  list[UpcomingTraining]`, sorted by date, then name ignoring case. `TrainingDays.upcoming_for(db_session, program,
  today) -> UpcomingTraining | None` (Task 3 uses it to check a start).

- [ ] **Step 1: Write the failing tests** (`GET /api/v1/today`, frozen clock):
  - `test_upcoming_lists_each_programs_next_training`: Onsdag (wed) and Fredag (fri) on Mon 2026-10-26 → two entries,
    2026-10-28 Onsdag and 2026-10-30 Fredag, both `startable` true, with the program's station count, rounds and
    total minutes.
  - `test_open_day_blocks_its_program_only`: mon/wed program A and wed program B on Monday with A due → A's entry
    (Wednesday) `startable` false, B's true.
  - `test_done_day_today_blocks_until_tomorrow`: A done today through a counted session (`session_helpers`) → A's
    entry `startable` false today, true at the next 00:05.
  - `test_no_upcoming_without_active_programs`: `upcoming == []`.
  - `test_next_leaves_out_done_dates` and `test_next_is_null_only_without_active_programs` in `test_scheduler.py`.
  - The MCP `get_today` result has `upcoming` (one assertion in the new file through the MCP client the other MCP tests
    use).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** `upcoming` in `_build_view` per spec §2.2.1–§2.2.2: per active program, the first date in
  `today + 1 … today + 14` on which `_trains_on` and that has no done, missed or skipped day of the program;
  `startable` is false when the program has an open day of any date or a done day dated today or later. `_next` looks
  14 days ahead and leaves out a program on a date where it already has a done day; it returns null only when no
  program is active.
- [ ] **Step 4: Run** the add-on gates. Expected: pass.
- [ ] **Step 5: Commit** `feat(addon): the today data lists each program's next training, startable or not`.

### Task 3: Starting a training early (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/schemas.py` (`NewSession`), `api/session.py`, `sessions.py`,
  `training_days.py`
- Test: `addon/server/tests/test_session_early.py` (new)

**Interfaces:**
- Consumes: `TrainingDays.upcoming_for` (Task 2).
- Produces: `NewSession.date: dt.date | None = None`; `Sessions.start(program_id, participants, training_day_id,
  client, speaker=None, date: dt.date | None = None)`. REST body `{"program_id", "participants", "date"}`.

- [ ] **Step 1: Write the failing tests** (REST and the push channel; frozen clock; mon/wed/fri program unless said):
  - `test_early_start_accepted`: on Tue, `POST /api/v1/session` with Wednesday's `date` → 201; the view's
    `training_day_id` is set; a `today` message follows at once; in it Wednesday is not in `open`, and the program's
    `upcoming` entry is Wednesday with `startable` false; `GET /api/v1/training-days` lists Wednesday `open`.
  - `test_early_start_refused`: 409 `conflict` for a date that isn't the program's upcoming date, for a program with
    an open day, and for a date not after today; 422 `invalid` for both `training_day_id` and `date`.
  - `test_counted_early_session_closes_day_done`: the finish sends `done` for Wednesday; at Wed 00:05 no `due` event,
    `open` is empty, and `GET /api/v1/stats` counts done on Wednesday's date (streak follows); the week ring counts it
    once in Wednesday's week.
  - `test_uncounted_early_session_leaves_no_day`: ended before one round → Wednesday has no training day, the program's
    `upcoming` entry is Wednesday again with `startable` true; the session is in `GET /api/v1/sessions`.
  - `test_early_session_across_midnight_counted`: starts Tue 23:55; at Wed 00:01 `open` holds Wednesday `due`, the
    program's `upcoming` moved past Wednesday (`startable` false), no `due` event; the finish closes it `done`.
  - `test_early_session_across_midnight_not_counted`: same, ended before one round → Wednesday stays `due` and a `due`
    event is sent when the session ends.
  - `test_upcoming_after_an_early_done_day`: a fri-only program, its Friday done early on Wednesday → on Wednesday
    the entry is the following Friday (9 days ahead, found by the 14-day search) with `startable` false, `next` skips
    the done Friday; on Saturday the entry is `startable` true.
  - `test_weekday_edit_during_early_session`: during the early session the program's weekdays drop Wednesday; the
    finish still closes Wednesday `done`, and no second Wednesday day exists.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** `start` with `date`: under the lock, check against `upcoming_for` (409 otherwise), make
  the day `open` with `created_at` now, and use its id as `training_day_id`. `_send` also calls `publish_today()` after
  a start. `_build_view` leaves out of `open` the open days dated after today. On an uncounted finish of a session
  whose day is open: delete the day if its date is after today; if its date is today and no `due` was sent for it,
  send `due` in the finish's batch. Reconcile already skips a date that has the program's day, so no new day is made.
- [ ] **Step 4: Run** the add-on gates. Expected: pass.
- [ ] **Step 5: Commit** `feat(addon): start a program's next training early from its upcoming date`.

### Task 4: The start's date in the integration

Model: opus · Review: yes

**Files:**
- Modify: `custom_components/ha_fitness/client.py`, `services.py`, `services.yaml`, `websocket_api.py`,
  `strings.json`, `translations/en.json`, `translations/da.json`
- Test: `tests/test_session_services.py`, `tests/test_websocket.py`, `tests/fake_addon.py` (the fake add-on learns
  `date` and `upcoming`)

**Interfaces:**
- Consumes: Task 3's REST body.
- Produces: `ha_fitness/session/command` `start` and `ha_fitness.start_session` take an optional `date`
  (`YYYY-MM-DD`). Refusal key `session_early_unsupported`.

- [ ] **Step 1: Write the failing tests:**
  - The ws `start` and the service relay `date` to the add-on (the fake records the body), and return the view.
  - With the coordinator's last today data lacking `upcoming`, both refuse before any relay: the ws command answers
    `invalid`; the service raises a translated validation error with key `session_early_unsupported` (en: "The HA
    Fitness add-on is too old to start a training early. Update the add-on."; da: "HA Fitness-tilføjelsen er for gammel
    til at starte en træning før tid. Opdater tilføjelsen."). Use the same wording style as the existing
    `session_*` keys if they differ.
  - A `date` that isn't a date fails HA's schema (`invalid_format` for ws, a schema error for the service).
- [ ] **Step 2: Run them to see them fail:** `uv run pytest tests/test_session_services.py tests/test_websocket.py -q`.
- [ ] **Step 3: Implement** the field next to `training_day_id` in both schemas and `client.start_session`, the gate
  on `"upcoming" in coordinator.today`, and the field's name and description in `services.yaml`, `strings.json` and
  both translations.
- [ ] **Step 4: Run** the integration gates. Expected: pass.
- [ ] **Step 5: Commit** `feat: the integration starts a training early with a date`.

### Task 5: A non-string language option (cards, #72)

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/language.ts`, `cards/src/card-editor.ts`
- Test: `cards/test/card-editor.test.ts`, `cards/test/today-card.test.ts` (or the card test that covers `language`)

- [ ] **Step 1: Write the failing tests:**
  - A today card with `language: 1` renders in the user's language (Danish text with `hass.locale.language` "da").
  - Each editor opened with `language: 1` shows a selected option labelled "1" next to the three usual ones; choosing
    it again fires no change that turns it into `"1"`; choosing "Follow the user's language" removes the key.
- [ ] **Step 2: Run them to see them fail:** `npm test --prefix cards -- card-editor today-card`.
- [ ] **Step 3: Implement:** `cardLanguage()` uses `config.language` only when it is a non-empty string. The editor
  keeps a non-string value as its own option, labelled `String(value)`.
- [ ] **Step 4: Run** the cards gates. Expected: pass.
- [ ] **Step 5: Commit** `fix(cards): a non-string language option no longer breaks a card`.

### Task 6: The long beep, and the start tone after the countdown (cards, #71)

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/audio.ts`, `cards/src/workout-flow.ts`
- Test: `cards/test/workout-flow-pings.test.ts`, `cards/test/audio.test.ts`

- [ ] **Step 1: Write the failing tests** in `workout-flow-pings.test.ts` (its `mount`, `view`, `phase`, `at`, `wait`,
  `push`, `live`, `beeps` helpers):
  - `the change tone plays when the next phase's view arrives just before local zero`: countdown ending at `at(10)`,
    next work; `wait(flow, 9_990)`; push the work view (revision 2, index 1, ends `at(55)`, `server_time: at(10.02)`).
    `live()` holds exactly one `work` tone, starting at once (≈ 9.99 s), and the work phase's beeps and rest tone.
  - `the change tone plays once when the view arrives just after it started` stays green (existing "a natural phase
    change gets its change tone once").
  - `no beep in the first second of a work phase`: a 10 s work phase (`duration: 10`) has beeps at 5–9 s left only if
    each is at least the long beep's length after the start; a 5 s switch keeps its beep at 1 s left.
  - `a program without a countdown plays the long beep at Start`: in the details flow, Start on a program whose first
    phase is work, with the start's view answering; one `work` tone at once. A second flow on the same session (opened
    with `resume`) plays none.
  - `audio.test.ts`: the `work` tone lasts at least 0.9 s (the stop is at least 0.9 s after the start); `beep` stays
    0.12 s.
- [ ] **Step 2: Run them to see them fail:** `npm test --prefix cards -- workout-flow-pings audio`.
- [ ] **Step 3: Implement.** `TONES.work` becomes one 1320 Hz note of 1.0 s. In `plan()`, a change tone that was
  pending when the new view arrived and whose `at` is the new phase's start is planned again (at once if passed),
  never twice; the simplest shape is `tonesOf()` also listing the current phase's own change tone at its start, which
  the existing started/pending rules then keep or drop. Keep `playSkipTone` from doubling it (Næste/Forrige tests).
  The quiet time after a phase start is `WORK_QUIET_MS` (≥ the tone's length) for work and `QUIET_MS` otherwise. The
  flow that sent `start` plays `work` at once when the answer's phase is work.
- [ ] **Step 4: Run** the cards gates. Expected: pass, the existing tone tests included.
- [ ] **Step 5: Commit** `feat(cards): a long beep at every work start, also after the countdown`.

### Task 7: Upcoming rows and `days_ahead` on the today card (cards, #70)

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/today-data.ts`, `today-card.ts`, `card-editor.ts`, `overlay.ts`, `workout-flow.ts`,
  `cards/src/i18n/en.json`, `cards/src/i18n/da.json`
- Test: `cards/test/today-card.test.ts`, `cards/test/card-editor.test.ts`, `cards/test/workout-flow-details.test.ts`

**Interfaces:**
- Consumes: Task 2's `upcoming` shape, Task 4's `date` on `start`.
- Produces: `interface Upcoming { program_id; program_name; date; station_count; rounds; total_minutes; startable }`,
  `Today.upcoming?: Upcoming[]`; the overlay's details mode gains `date?: string`; the today card config gains
  `days_ahead?: number`.

- [ ] **Step 1: Write the failing tests** (rendered text and roles; the today data's `date` is the reference):
  - With `days_ahead: 2` and `upcoming` for tomorrow (startable) and in two days (not startable): rows show the
    program's name, "Tomorrow" (en) / "I morgen" (da) and the weekday name for the other, stations, rounds and
    minutes; the first has a Start button and no Spring over; the second has no buttons.
  - An entry three days ahead isn't shown with `days_ahead: 2`; nothing upcoming shows with `days_ahead` unset.
  - Order: open rows by date then name (late before due), then upcoming by date then name.
  - Nothing open and one upcoming row in range → the card isn't hidden; nothing open and nothing in range → hidden, as
    today. `getCardSize()` counts upcoming rows like open rows.
  - An older add-on (no `upcoming` key) with `days_ahead: 2` renders as today.
  - Start on an upcoming row opens the details step; its Start sends `{command: "start", program_id, participants,
    date}` and no `training_day_id`; a refused start (409) shows the existing error text.
  - The today card's editor has a "Days ahead" / "Dage frem" field (0–6); 0 removes the key; the workout and stats
    editors have no such field.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** the rows (the look follows the open row, visibly "coming"; keys in both language files),
  the editor field for the today card only, the details mode's `date`, and `date` on the start.
- [ ] **Step 4: Run** the cards gates. Expected: pass.
- [ ] **Step 5: Commit** `feat(cards): the today card shows trainings ahead, with Start or as a reminder`.

### Task 8: Docs

Model: sonnet · Review: no

**Files:** `docs/domain-language.md`, `docs/architecture.md`, `docs/decisions.md`

- [ ] **Step 1:** Update per spec §7: Late, Missed, Upcoming, Done early, Extra session, Today card, Next training day,
  the week-ring case and the stats surprise in `domain-language.md`; `upcoming`, the order of `open`, the start's
  `date` (REST, ws, service, the gate), `late_days` and `days_ahead` in `architecture.md`.
- [ ] **Step 2:** `decisions.md`: D60 "Late days stay open per program, for `late_days` days" (replaces design spec
  §3.2's and step 4 spec §3.3's any-program rule and §3.5's one-date rule), D61 "A program's next training can be done
  early, one at a time" (the add-on makes the day at the start; an uncounted early session leaves no day). Format per
  `way-of-working.md` §5, date 2026-10-25, source this spec.
- [ ] **Step 3: Run** `uv run python scripts/check_links.py`. Expected: pass.
- [ ] **Step 4: Commit** `docs: late days, starting early and upcoming trainings`.

### After the tasks (controller)

- `full-reviewer` on the branch until Ready.
- The fast loop and the Chrome check: the today card with a late day and upcoming rows (screenshots in
  `screenshots/2026-10-25-today-ahead/`), reviewed with Thomas one screen at a time; the long beep with Thomas
  listening, also after the countdown.
- The PR: title `feat: trainings ahead, late days, the long start beep`, `Closes #70`, `Closes #71`, `Closes #72`;
  the squash message lists each change as its own Conventional Commit line (spec §6).
- Before the release: the full loop, with `late_days` on the Configuration tab and read by the add-on.
