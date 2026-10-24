# UI Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repo the dispatches use the `implementer` and `task-reviewer` agents ([way of working](../../way-of-working.md)).

**Goal:** The today card and every workout screen take the mockups' layout (icons, tiles, rings) in HA's light theme,
with three small additions in the add-on to feed them: the week's numbers, a program's equipment, and how a workout felt.

**Architecture:** The add-on adds `week` to the today view, `equipment` to `ProgramOut`, and a `feeling` on the session
with its own route; the integration relays them. In the cards, the workout flow is first split by step into render
modules with no visible change, then each screen is rebuilt in its own task. The flow keeps all state, timers and
commands; a step module only renders what its context gives it.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2, Alembic, FastMCP (add-on); Home Assistant custom integration;
Lit + TypeScript, Vite, Vitest, Testing Library (cards).

**Spec:** [`docs/superpowers/specs/2026-10-24-ui-refresh-design.md`](../specs/2026-10-24-ui-refresh-design.md). Read
it first, and the mockup named in each screen task (`docs/mockups/<Name>.html` and `.png`); the mockups give the layout,
the spec gives the rules where they differ. Issue #42.

## Global Constraints

- Hard rules of `CLAUDE.md`, especially rule 5 (tests through public interfaces: roles, accessible names, rendered text;
  no CSS selectors, no snapshots; a frozen clock) and rule 6 (every UI text from the language files, English and
  Danish; exercise names never translated).
- `api_version` stays 1. No `addon_too_old` for these fields: a card hides what a missing field would feed (spec §4).
- Colours: HA's theme variables. Phases: work orange, switch and rest blue (the existing `RING_COLORS`). People, in
  people order: `#B18CFF`, `#3DD6C6`, then `var(--primary-color)`.
- Icons: `<ha-icon icon="mdi:…">` only; no icon package is added. Every icon-only button has an `aria-label` from the
  language files. Icons: `mdi:play`, `mdi:pause`, `mdi:skip-previous`, `mdi:skip-next`, `mdi:arrow-left`,
  `mdi:lightning-bolt`, `mdi:check`, `mdi:debug-step-over`. The controller checked on 2026-10-24 that `ha-icon`
  renders inside a shadow root under a page-level `<dialog>` in the dev HA.
- Touch targets at least 48 px; the round pause/play button is the largest control.
- Step 5's behaviour stays: commands, timing, beeps, the idle close, the reach note, Slut's and Spring over's confirms.
- Two PRs (D29): Part A `feat: week, equipment and feeling in the add-on` (`addon/`, `docs/`); Part B
  `feat: the refreshed screens` (`custom_components/`, `cards/`, `tests/`, `docs/`). Merge A first.
- D50 goes with Part A, D51 with Part B (spec §6).
- Commits: Conventional Commits with the co-author trailer from the dispatch, `git commit -F <file>`.

## Review Focus

1. A week whose Monday is in last week's late day: the late day trained on Monday counts in last week, not this one
   (spec §3.1). Test in A1.
2. A feeling sent after the 5-minute finished view, or for an ended session, is refused with 409 and changes nothing
   (spec §3.3). Test in A3.
3. A Part B card against a Part A-less add-on: no ring, no equipment chips, no feeling buttons, and nothing else breaks
   (spec §4). Tests in B3, B4 and B8.
4. Tapping the ring during the countdown does nothing; during work it pauses, while paused it resumes (spec §2.3,
   §2.5). Tests in B5 and B6.
5. Two people whose names start with the same letter get two-letter initials in the streak badge (spec §2.1). Test in
   B3.

---

## Part A — the add-on (`feat/ui-refresh-addon`, from `main`)

### Task A1: The week in the today view

**Model:** opus · **Review:** yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/schemas.py` (`Week`, `TodayView`),
  `addon/server/src/ha_fitness_server/training_days.py` (`_build_view`)
- Test: `addon/server/tests/test_week.py` (new; reuse the clock and client fixtures of `test_scheduler.py`)

**Interfaces:**
- Produces: `class Week(BaseModel): done: int; planned: int`, and `TodayView.week: Week`. It reaches `GET /today`, the
  `today` push message and MCP `get_today` with no other change.
- `_build_view(today)` computes it in the same database session, for Monday to Sunday of `today`'s local week:
  - `planned` = training days dated in the week (any status, any program, active or not) + for each date from
    `today + 1` to Sunday, the active programs that train on it (`_trains_on`) and have no training day on that date yet.
  - `done` = training days dated in the week with status `done`.
- A change in `week` changes the view, so the existing `view != self._published` rule publishes it.

- [ ] **Step 1: Failing tests**, all with a frozen clock and the default timezone of the existing tests:
  - `test_week_counts_past_today_and_future`: a program on Mon/Wed/Fri, today Wednesday, Monday done, Wednesday open →
    `{done: 1, planned: 3}`.
  - `test_week_skipped_and_missed_count_as_planned_only`: Monday missed, Wednesday skipped, today Thursday →
    `done 0, planned 3`.
  - `test_week_program_switched_off_drops_future_days`: switch the program off on Wednesday after Monday was done →
    `planned` keeps Monday and Wednesday's existing days, loses Friday.
  - `test_week_fresh_install_counts_from_today`: first run on Wednesday → Monday isn't counted (`planned 2`).
  - `test_week_late_day_from_last_week_stays_in_last_week`: Sunday's day trained on Monday → this week `done 0`.
  - `test_week_extra_session_does_not_count`.
  - `test_week_starts_over_on_monday`: across the Sunday→Monday midnight with the fast scheduler interval, the next
    `today` message has the new week's numbers.
  - `test_week_on_sunday_has_no_future_days`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** the Interfaces block. Existing tests that compare the whole today body get `week`.
- [ ] **Step 4: Run all the add-on gates;** they pass.
- [ ] **Step 5: Commit** `feat: the week's numbers in the today view`.

### Task A2: A program's equipment

**Model:** sonnet · **Review:** yes

**Files:**
- Modify: `schemas.py` (`ProgramOut`), `programs.py` (`Programs._out`), `mcp_tools.py` (the `get_program` description)
- Test: `addon/server/tests/test_programs.py`, `addon/server/tests/test_mcp.py`

**Interfaces:**
- Produces: `ProgramOut.equipment: list[str]`: each station's exercise `equipment` (`self._library.get(...).equipment`),
  in station order, the first time each value appears; nulls and values equal to `body weight` ignoring case left out.
  Custom exercises count like library ones.

- [ ] **Step 1: Failing tests:** `test_program_equipment_distinct_in_station_order` (dumbbell, band, dumbbell →
  `["dumbbell", "band"]`), `test_program_equipment_leaves_out_body_weight_and_none` (`Body Weight` too),
  `test_program_equipment_includes_custom_exercises`, `test_program_equipment_empty`, and the field in MCP
  `get_program`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** The `get_program` tool description names `equipment` (Claude reads it).
- [ ] **Step 4: Run all the add-on gates;** they pass.
- [ ] **Step 5: Commit** `feat: a program's equipment`.

### Task A3: How a workout felt

**Model:** opus · **Review:** yes

**Files:**
- Create: `addon/server/src/ha_fitness_server/migrations/versions/0005_session_feeling.py`
- Modify: `models.py` (`WorkoutSession`), `schemas.py` (`SessionView`, a `FeelingIn` body), `sessions.py`,
  `api/session.py`, `mcp_tools.py` (the `list_sessions` description)
- Test: `addon/server/tests/test_session_feeling.py` (new; reuse `session_helpers.py`), `test_storage.py` (migration)

**Interfaces:**
- Produces:
  - `FEELINGS = ("too_easy", "just_right", "too_hard")` in `sessions.py`.
  - `WorkoutSession.feeling: Mapped[str | None]`; migration `0005_session_feeling` (down: `0004_people_added_at`) adds
    the nullable column, and its downgrade drops it with `sqlite_autoincrement` kept, as 0004 does.
  - `SessionView.feeling: Literal["too_easy", "just_right", "too_hard"] | None`, always present: null on a live view and
    on a finished one without a rating. `GET /sessions` and MCP `list_sessions` carry it through `SessionView`.
  - `class FeelingIn(BaseModel): feeling: str` (any text, so the service gives the `{code, message}` 422).
  - `Sessions.feel(feeling: str, client: str) -> SessionView`, under `training_days.lock`, after `_tick_alone`:
    - 422 `invalid` when `feeling` isn't in `FEELINGS`;
    - 409 `conflict` unless there is no active session and the last finished one is `completed` and ended less than
      `FINISHED_VIEW_KEPT` ago;
    - else sets it, `revision += 1`, a change-log row (`action="session.feeling"`, `target="session:<id>"`, summary
      `"Rated session of <program> as <feeling>"`), and `_send([_session_message(view)])`; returns the view.
  - `POST /api/v1/session/feeling` with `FeelingIn`, declared **before** `POST /session/{command}`.
- [ ] **Step 1: Failing tests:**
  - `test_feeling_sets_and_changes` (a second call replaces it; `revision` rises each time);
  - `test_feeling_pushes_session` (the ws gets one `session` message with the feeling);
  - `test_feeling_adds_a_change_log_row`;
  - `test_feeling_refused_without_a_finished_view`: none, running, paused → 409 `conflict`;
  - `test_feeling_refused_for_ended_sessions`: ended counted and not counted → 409;
  - `test_feeling_refused_after_five_minutes` (frozen clock moved past `FINISHED_VIEW_KEPT`) → 409, nothing stored;
  - `test_feeling_unknown_value_is_invalid` → 422 with `detail.code == "invalid"`;
  - `test_feeling_in_history_and_mcp_list_sessions`;
  - `test_migration_0005_keeps_step_6_data` in `test_storage.py`, the way the 0004 test does.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** the Interfaces block. Existing tests that compare a whole session view get `feeling: null`.
- [ ] **Step 4: Run all the add-on gates;** they pass.
- [ ] **Step 5: Commit** `feat: how a workout felt`.

### Task A4: Docs (Part A)

**Model:** sonnet · **Review:** no

- [ ] **Docs** per spec §6, PR 1: `architecture.md` (`week`, `equipment`, `feeling` and its route);
  `domain-language.md` (the week ring with the five named cases of spec §3.1, and *feeling*); **D50** in
  `decisions.md` (how a workout felt is stored with the session, for Claude; source: spec §3.3). Then
  `uv run python scripts/check_links.py`.
- [ ] **Commit** `docs: week, equipment and feeling`.
- [ ] **Controller:** fast loop. Over REST: `GET /today` shows `week`; `GET /programs` shows `equipment`; finish a
  workout, `POST /session/feeling`, then `GET /sessions` and MCP `list_sessions` show it.
- [ ] **Controller:** branch review (`full-reviewer`), the PR `feat: week, equipment and feeling in the add-on`
  (part of #42), the merge.

---

## Part B — the integration and the cards (`feat/ui-refresh-cards`, worktree from `main`; rebase after Part A merges)

B1 and B2 don't depend on Part A and may start while Part A is in review. The card tests use fake data, so no card
task waits for Part A's merge; only the controller's fast-loop check does.

### Task B1: The relay and the feeling command

**Model:** sonnet · **Review:** yes

**Files:**
- Modify: `custom_components/ha_fitness/client.py`, `custom_components/ha_fitness/websocket_api.py`
- Test: `tests/test_websocket.py`, `tests/fake_addon.py`

**Interfaces:**
- Produces:
  - `async_session_feeling(session, url, feeling: str, integration_version: str) -> dict[str, Any]`: `POST
    /api/v1/session/feeling` with `{"feeling": feeling}` through `_async_session_post`.
  - `ha_fitness/session/command` accepts `command: "feeling"` (added to `SESSION_COMMANDS`) with
    `probatio.Optional("feeling"): str`. Without `feeling` it answers `invalid` before calling the add-on, as `start`
    does without its fields. Refusals map as the other commands do.
  - `ha_fitness/programs` items add `total_seconds` (as stored) and `equipment` (`stored.get("equipment", [])`).
- [ ] **Step 1: Failing tests:** the feeling command relays and returns the view; a refusal keeps the add-on's code
  (`conflict`, `invalid`); a missing `feeling` gives `invalid` with no add-on call; the add-on down gives `unavailable`;
  `ha_fitness/programs` has `total_seconds` and `equipment`, and `equipment: []` from a fake add-on that leaves it out.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the integration gates;** they pass.
- [ ] **Step 5: Commit** `feat: relay equipment, total seconds and the feeling command`.

### Task B2: Split the workout flow by step

**Model:** opus · **Review:** yes

**Files:**
- Create: `cards/src/flow/details.ts`, `cards/src/flow/ready.ts`, `cards/src/flow/timer.ts`, `cards/src/flow/done.ts`,
  `cards/src/flow/shared.ts`, `cards/src/people.ts`, `cards/src/icon-button.ts`
- Modify: `cards/src/workout-flow.ts`, `cards/src/stats-card.ts` (imports only)
- Test: the existing `cards/test/workout-flow-*.test.ts`, unchanged; `cards/test/icon-button.test.ts` (new)

**Interfaces:**
- Produces:
  - `cards/src/people.ts`: `PERSON_COLORS`, `personColor(index: number): string` (the primary colour from the third),
    and `initials(names: string[]): string[]` (first letter, upper-cased; two letters for every name whose first letter
    another name shares). The flow and the stats card import the colours from here.
  - `cards/src/icon-button.ts`: `iconButton(options: { icon: string; label: string; onClick: () => void; className?:
    string; disabled?: boolean; pressed?: boolean; text?: string })`: a `<button>` with `aria-label=label` when there is
    no `text`, an `<ha-icon>` (aria-hidden), the `text` after the icon when given, and `aria-pressed` only when
    `pressed` is given.
  - `cards/src/flow/<step>.ts`: each exports `render<Step>(ctx: <Step>Context): TemplateResult` and `<step>Styles`
    (a `css` block). Each context interface, in its module, holds only the data and callbacks that step renders, and
    `t`. `shared.ts` holds `clock()`, the image rendering and the shared styles (buttons, chips, page layout).
  - `WorkoutFlow` keeps every property, timer, command and the audio. It builds each context and composes the styles.
- No visible change: same texts, roles, layout and behaviour. Moving code is the change.
- [ ] **Step 1: Failing tests** for `initials` (`["Thomas", "Elin"]` → `["T", "E"]`; `["Thomas", "Tina"]` →
  `["Th", "Ti"]`; one name) and `iconButton` (named by label; text instead of label when given; `aria-pressed` only
  when given), rendered with Lit's `render` into a container.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement** the helpers, then move each step's render and styles out of `workout-flow.ts`.
- [ ] **Step 4: Run the cards gates;** every existing test passes unchanged.
- [ ] **Step 5: Commit** `refactor: split the workout flow by step`.

### Task B3: The today card

**Model:** opus · **Review:** yes

**Mockup:** `StatusCard` (the top line and the ring) mixed with today's card (spec §2.1).

**Files:**
- Modify: `cards/src/today-card.ts`, `cards/src/today-data.ts` (`Today.week?`), `cards/src/i18n/en.json`, `da.json`
- Test: `cards/test/today-card.test.ts`

**Interfaces:**
- Consumes: `WsSubscription<StatsMessage>` on `ha_fitness/stats/subscribe` (types from `stats-card.ts`);
  `initials`, `personColor`, `iconButton` (B2).
- Produces: `Today.week?: { done: number; planned: number }`.
- The streak badge: a `role="img"` group named "Streak: Thomas 6, Elin 4" (`today.streak_label`), showing
  `mdi:lightning-bolt` and, per person in people order, a colour dot, the initial and the streak. Hidden while there are
  no stats, `counting_from` is null, or the subscription is refused.
- The week ring: a small SVG ring, a `progressbar` named "This week" / "Denne uge" with `aria-valuenow=done`,
  `aria-valuemax=planned`, showing "2/4" and the name under it. Hidden when `week` is missing or `planned` is 0. It may
  generalise `ring.ts` with a size option, or be its own; the timer ring's behaviour doesn't change.
- Day rows: program name; state line "Today" / "I dag" for due, the existing late line for late; the summary line;
  then the buttons under the text: Start (`mdi:play` with the text) and Spring over (`mdi:debug-step-over` with the
  text). The confirm keeps step 4's rule, with Nej in Spring over's place.
- During a session the top line and the ring stay, and the rows are replaced by the session row with Fortsæt
  (`mdi:play` with the text).
- [ ] **Step 1: Failing tests,** in Danish and English where text matters:
  - `streak badge shows initials, numbers and an accessible name`; `two-letter initials on a clash`;
    `streak badge hidden before counting and while stats are refused`;
  - `week ring shows done of planned`; `no ring without week or with planned 0` (the §4 compatibility case);
  - `due day says I dag, late day keeps Forfalden`;
  - `buttons sit under the text and Spring over keeps its two taps`;
  - `several open days share one top line and ring`;
  - `session row replaces the days but keeps the top line`.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** The card fits a 500 px sections column without the line wrapping into the buttons (#29).
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: the today card follows the mockup`.

### Task B4: Details

**Model:** opus · **Review:** yes

**Mockup:** `WorkoutDetails` (spec §2.2).

**Files:**
- Modify: `cards/src/flow/details.ts`, `cards/src/workout-flow.ts` (the `Program` type: `total_seconds?`,
  `equipment?`), the language files
- Test: `cards/test/workout-flow-details.test.ts`

**Interfaces:**
- Consumes: B1's `total_seconds` and `equipment` on each program; `iconButton`.
- The layout: a back button (`mdi:arrow-left`, label "Back" / "Tilbage") and the name on top; left, the line
  "N exercises · everyone moves one station each interval" and a grid of the thumbnails with "n · name"; right, the
  people chips, Rounds, Work / switch in the phase colours, "Rest between rounds" when above 0, "You'll need" with the
  equipment chips (hidden when empty or missing), the total as `m:ss` from `total_seconds` (from `total_minutes × 60`
  when missing), a big Start (`mdi:play` with the text), and the small "Change the program by asking Claude".
- Equipment translation keys `equipment.dumbbell`, `equipment.band`, `equipment.kettlebell`,
  `equipment.resistance_band` (spaces become `_`); any other value shows as stored.
- [ ] **Step 1: Failing tests:** the grid's items in order with numbers and names; chips and Start as today; rounds,
  work/switch and the round rest row shown only above 0; the equipment chips translated in Danish, an unknown value as
  stored, none without `equipment` (the §4 case); the total "44:00"; the back button by its label closes.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.** Portrait (800 px wide) stacks the panels.
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: details follows the mockup`.

### Task B5: Get ready

**Model:** opus · **Review:** yes

**Mockup:** `GetReady` (spec §2.3).

**Files:**
- Modify: `cards/src/flow/ready.ts`, `cards/src/workout-flow.ts` (its context), the language files
- Test: `cards/test/workout-flow-timer.test.ts` (or a new `workout-flow-ready.test.ts`)

**Interfaces:**
- The summary pill "Sample · 2 people · 5 rounds · 29 min" (minutes from `totals.planned`, rounded as `total_minutes`
  is) and Annullér on the right; the countdown inside the ring with "GET READY" above the number; "GO TO YOUR START
  STATION" and one card per participant: a numbered badge (participant order, 1-based) in the person's colour, the
  thumbnail, "name · station n", the exercise name large; Start nu at the bottom.
- No Pause button. A paused countdown shows a "PAUSED" pill, and Fortsæt (sends `resume`) instead of Start nu.
- The countdown ring has no tap handler.
- [ ] **Step 1: Failing tests:** the pill text in both languages; one card per person with badge numbers 1 and 2; no
  button named Pause; Start nu sends `next`; Annullér sends `end` and closes; paused: the PAUSED pill and Fortsæt
  sending `resume`, no Start nu; a tap on the countdown ring sends nothing.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: get ready follows the mockup`.

### Task B6: The timer for one person, switch and paused

**Model:** opus · **Review:** yes

**Mockups:** `Timer` and `TimerRest` (spec §2.4, §2.5).

**Files:**
- Modify: `cards/src/flow/timer.ts`, `cards/src/ring.ts`, `cards/src/workout-flow.ts` (its context, the ring tap), the
  language files
- Test: `cards/test/workout-flow-timer.test.ts`

**Interfaces:**
- The top row: pills "Round 3/5" and "Station 4/8" (`phase.interval` / `totals.stations`; "Station 4" without
  `totals.stations`), a "PAUSED" pill while paused, then the elapsed time and Slut with its confirm.
- Left: the GIF and the exercise name; during a switch **and a rest**, "GO TO THE NEXT STATION" above it (`current` is
  the station moved to). Plan ruling: a rest is a move to the next round's first station, so it reads like a switch.
- Middle: the ring keeps the phase word while paused (not "PAUSED"), with "seconds left" under the number while
  running and "tap the ring to resume" while paused. Its `progressbar` role and name stay; it has no button role and
  no tab stop.
- Right: the "NEXT" card (during a switch or rest: "THEN") with the thumbnail, the name and the subtitle from
  `next_phase`: "after 15 s switch", "after 60 s rest", or "next up" when the next phase is work. No card when
  `stations[0].next` is null, and the ring stays centred (#36: the three columns keep their widths).
- Bottom: `iconButton`s Previous (`mdi:skip-previous`), Pause/Resume (`mdi:pause` / `mdi:play`, the big round one),
  Next (`mdi:skip-next`); then a `progressbar` named "Whole workout" / "Hele træningen" with `aria-valuemax` =
  `totals.planned` and `aria-valuenow` = the elapsed seconds.
- The ring tap: running → `pause`, paused → `resume`.
- [ ] **Step 1: Failing tests,** with the frozen clock the file already uses:
  - the pills, including "Station" during a switch;
  - the NEXT card's subtitle for a switch, a rest and a 0 s switch; THEN during a switch; no card on the last interval;
  - the three icon buttons found by their labels send `previous`, `pause`/`resume` and `next`;
  - the whole-workout progressbar's value moves with the clock;
  - paused: the PAUSED pill, the ring keeps the phase word and says to tap, the round button is named Resume;
  - a tap on the ring sends `pause` while running and `resume` while paused.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: the one-person timer follows the mockup`.

### Task B7: The timer for two people

**Model:** sonnet · **Review:** yes

**Mockup:** `TimerDuo` (spec §2.6).

**Files:**
- Modify: `cards/src/flow/timer.ts`, the language files
- Test: `cards/test/workout-flow-timer.test.ts`

**Interfaces:**
- Consumes: B6's top row, ring, buttons and progress bar.
- One card per person: a coloured bar along the top, the numbered badge with the name, "Station n" on the right, the
  GIF, the exercise name large, and "Next: station 4 · Burpee" small. The top row's second pill is "Interval y/S"
  (`flow.interval_of`). Portrait keeps step 5's layout: the two cards side by side, the ring below.
- [ ] **Step 1: Failing tests:** two regions named after the people, each with its badge number, station and exercise;
  the Interval pill instead of Station; the next line; the buttons and progress bar as in B6.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: the two-person timer follows the mockup`.

### Task B8: Complete and ended

**Model:** opus · **Review:** yes

**Mockup:** `Complete` (spec §2.7).

**Files:**
- Modify: `cards/src/flow/done.ts`, `cards/src/workout-flow.ts` (a stats subscription while the done step shows, the
  feeling command, the auto-close restart), `cards/src/overlay.ts` (`SessionView.feeling?`), the language files
- Test: `cards/test/workout-flow-done.test.ts` (new)

**Interfaces:**
- Consumes: B1's `feeling` command; `WsSubscription<StatsMessage>` on `hass.connection` (add `connection` to the flow's `Hass` type; the tests' fake gets a `subscribeMessage`); `iconButton`, `personColor`.
- Produces: `SessionView.feeling?: "too_easy" | "just_right" | "too_hard" | null` (absent from an older add-on).
- Completed: `mdi:check`, "Workout complete", the program and the date: the browser's local date of `started_at`
  written with `done.date` ("{weekday} {day}. {month}" in Danish, "{weekday} {day} {month}" in English) and new
  `month.<name>` keys; four tiles: Time, Rounds "5 / 5", Trained (the names), Streak (each participant's dot, name and
  streak from the stats, matched by person id; the tile shows once the stats arrive).
- The feeling group "How did it feel?": three buttons For let / Tilpas / For hårdt with `aria-pressed` from the view's
  `feeling`, the chosen one with `mdi:check` too. A tap sends `{type: "ha_fitness/session/command", command:
  "feeling", feeling}`, restarts the 60 s auto-close, and on failure shows one text per code (`conflict`, `invalid`,
  `unavailable`, else general) under the buttons. The group is absent when the view has no `feeling` key.
- Færdig closes.
- Ended and counted: the check, "Ended after 2 of 5 rounds" (`rounds_completed`, `totals.rounds`), the four tiles; no
  feeling group. Ended, not counted: "The workout was ended", Time, Rounds, Trained, Færdig; no check, no streak, no
  feeling group.
- [ ] **Step 1: Failing tests:** the date in both languages under a frozen clock and a fixed timezone; the four tiles;
  the streak tile after a stats message; the feeling command sent, `aria-pressed` following the next view, a second tap
  changing it; an error text per code; a tap at 50 s keeps the overlay open past 60 s from the finish; no feeling group
  without the key (the §4 case); ended counted and not counted layouts; Færdig closes.
- [ ] **Step 2: Run them; they fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run the cards gates;** they pass.
- [ ] **Step 5: Commit** `feat: complete follows the mockup, with how it felt`.

### Task B9: Docs and verification (Part B)

**Model:** sonnet · **Review:** no

- [ ] **Docs** per spec §6, PR 2: `architecture.md` (the relay additions, the flow split by step);
  `docs/mockups/README.md` (the built screens follow the mockups' layout in light colours); `testing.md` (the Chrome
  check per screen); **D51** in `decisions.md` (Thomas, 2026-10-24). Then `uv run python scripts/check_links.py`.
- [ ] **Commit** `docs: the refreshed screens`.
- [ ] **Controller:** rebase on main (after Part A), fast loop with fresh data, then the Chrome check of every screen at
  1368×912 and 800×1280 in Danish, against the mockups: the today card (open day, late day, session, a 500 px column),
  details, get ready (and paused), the timer (work, switch, paused, last interval), two people, complete with a
  feeling, ended counted and not counted. Screenshots go to Thomas and into the PR (no data from the real HA).
- [ ] **Controller:** the full loop, branch review (`full-reviewer`), the PR `feat: the refreshed screens`
  (Closes #42, #29, #36), the merge. The release PRs stay held for Thomas's local test.
