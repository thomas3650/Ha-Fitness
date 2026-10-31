# The cool-down, the timeline, the end-of-work beeps and the break between rounds: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repo, `docs/way-of-working.md` wins over the skill: `implementer` per task, `task-reviewer` on `Review: yes`.

**Goal:** Sessions run from a timeline frozen at the start, with no break before the rest between rounds and an
optional cool-down of stretches; the tablet shows and sounds the cool-down, plays 5 beeps and a 1.5 s long beep at
both ends of work, and the website and MCP can write a cool-down.

**Architecture:** The add-on owns the rules: a new `timeline.py` builds the phase list from a program, `build_plan`
freezes it into the plan, and everything after the start reads it. The program document gains `cooldown`. The
integration relays `cooldown` and the new `skip_cooldown` command. The cards read `part` from the view; the website
mirrors the timeline's length in TypeScript.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, pytest (add-on); Home Assistant custom integration, pytest
(HA); Lit, TypeScript, Vite, Vitest (cards and website).

**Spec:** `docs/superpowers/specs/2026-10-31-cooldown-and-timeline-design.md`. Every task reads it; section numbers
below are the spec's.

## Global Constraints

- `cooldown`: `null` or `{stretches: 1–10 entries {exercise}, hold_seconds: 10–120 default 30, change_seconds: 0–60
  default 10}`. An empty `stretches` is a 422 with code `invalid` at `cooldown.stretches`.
- Stretch refusals: `stretch_unknown` / `stretch_shared` at `cooldown.stretches.<index from 0>`.
- `station_names` stays the stations only; `stretch_names` is new.
- `part`: `"circuit"` | `"cooldown"`; the rest before the cool-down is `circuit`. Phase kinds stay `countdown`, `work`,
  `switch`, `rest`. `api_version` stays 1.
- The long beep: 1320 Hz, **1.5 s**. A phase that starts with it has a **1.6 s** quiet window; the countdown keeps
  `QUIET_MS` (0.3 s).
- Hard rule 5: tests through public interfaces (REST, MCP, push messages, services, websocket commands, rendered text
  and roles), a frozen clock for anything time-based, no snapshot or exact-log tests.
- Hard rule 6: every card text in `en.json` and `da.json`; the website is English only (D62). Exercise names are never
  translated.
- Commits: Conventional Commits with the co-author trailer from the dispatch, `git commit -F <file>`.
- The gates in `CLAUDE.md` pass before every commit.

## Review Focus

1. **A session running across the update:** a plan stored before the migration must keep its phase index on the same
   phase. Test in Task 3 (the migration on a mid-session plan, then a tick and a `next`).
2. **A program with one station:** no switch at all, rounds joined by rests only; with a cool-down the last work's
   `next` is stretch 1. Test in Task 2.
3. **`previous` and `next` across the circuit/cool-down border**, and `next` on the last stretch completing the
   session. Tests in Task 4.
4. **`update_program` without `cooldown`** deletes it: the MCP text must tell Claude to send it back. Test in Task 5
   (the tool text names it; a round-trip keeps it when sent).
5. **An older add-on with the new cards:** no `part`, no `totals.stretches`, no `cooldown` must render as today. Tests
   in Task 8 and Task 9.

---

### Task 1: `cooldown` in the program document (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/schemas.py` (`ProgramDocument`, `ProgramOut`, `ProgramDefaults`, a new
  `Cooldown` model), `programs.py` (`_resolved`, `_out`, `_NAMED_ONLY`), `library/service.py` (`resolve`)
- Test: `addon/server/tests/test_programs.py`

**Interfaces:**
- Produces: `class Cooldown(BaseModel)` with `stretches: list[StationIn]` (1–10), `hold_seconds: int = 30` (10–120),
  `change_seconds: int = 10` (0–60); `ProgramDocument.cooldown: Cooldown | None = None`;
  `ProgramOut.stretch_names: list[str]`; `ProgramDefaults.cooldown_hold_seconds`, `.cooldown_change_seconds`;
  `Library.resolve(ref: str, position: int, field: Literal["stations", "stretches"] = "stations") -> Exercise`
  (stretches: codes `stretch_unknown` / `stretch_shared`, field `cooldown.stretches.<i>`).

- [ ] **Step 1: Write the failing tests** in `test_programs.py`, through `POST`/`PUT`/`GET /api/v1/programs`:
  - `test_cooldown_round_trip`: write a program with two stretches by name; `GET` returns them as ids in
    `program.cooldown.stretches`, `stretch_names` with their names, `station_names` unchanged, and `equipment`
    including a stretch's equipment.
  - `test_cooldown_defaults`: `cooldown: {stretches: [...]}` reads back `hold_seconds` 30, `change_seconds` 10;
    `GET /api/v1/programs/defaults` has `cooldown_hold_seconds` 30 and `cooldown_change_seconds` 10.
  - `test_cooldown_ranges`: parametrized 422 for `hold_seconds` 9 and 121, `change_seconds` -1 and 61, 11 stretches;
    0 and 60, 10 and 120 pass.
  - `test_cooldown_empty_stretches_is_invalid`: 422, an item with code `invalid` and field `cooldown.stretches`.
  - `test_cooldown_unknown_stretch`: an unknown name gives `stretch_unknown` at `cooldown.stretches.1` for the second
    stretch; a name two exercises share gives `stretch_shared`.
  - `test_cooldown_null_and_missing`: both read back as `cooldown: null` and `stretch_names: []`.
  - `test_cooldown_change_log_names_it`: an update that changes the cool-down has a summary naming `cooldown` without
    a JSON dump (assert the word is in it and `{` is not).
- [ ] **Step 2: Run** `uv run --directory addon/server pytest tests/test_programs.py -q`. Expected: the new tests fail.
- [ ] **Step 3: Implement.** The empty-list refusal is a `field_validator` raising `PydanticCustomError("invalid", …)`,
  like `weekday_needed`. `_resolved` resolves stretches with `field="stretches"`; `_out` fills `stretch_names` and
  adds the stretches' equipment. `_NAMED_ONLY` gains `cooldown`. Leave `total_seconds` to Task 2.
- [ ] **Step 4: Run** the add-on gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): a program can have a cool-down of stretches`.

### Task 2: The timeline builder and the plan (add-on)

Model: opus · Review: yes

**Files:**
- Create: `addon/server/src/ha_fitness_server/timeline.py`
- Modify: `sessions.py` (`Plan`, `build_plan`, `Phase`, `phases`, `_rounds_behind`, `_station`), `programs.py`
  (`total_seconds`), `schemas.py` (`PhaseKind` moves or is imported; `Part`)
- Test: `addon/server/tests/test_timeline.py` (new, through `POST /api/v1/session` and `GET /api/v1/session` /
  `total_seconds` in `GET /api/v1/programs`), `test_session_start.py`, `test_session_plan_walk.py`, `test_programs.py`

**Interfaces:**
- Consumes: Task 1's `ProgramDocument.cooldown`.
- Produces: `type Part = Literal["circuit", "cooldown"]` in `schemas.py`;
  `class TimelineEntry(BaseModel)`: `kind: PhaseKind`, `part: Part`, `round: int`, `interval: int`, `duration: int`,
  `work: int | None` (a circuit work's station offset, a cool-down work's stretch index from 0, else None);
  `build_timeline(document: ProgramDocument) -> list[TimelineEntry]` (§4.2's four rules);
  `Plan.timeline: list[TimelineEntry]`, `Plan.stretches: list[PlanStation] = []`,
  `Plan.cooldown_hold_seconds: int = 0`, `Plan.cooldown_change_seconds: int = 0`;
  `Phase.part: Part`; `phases(plan)` derives `current_offset`/`next_offset` from `plan.timeline`'s `work`;
  `total_seconds(document) = sum(e.duration for e in build_timeline(document) if e.kind != "countdown")`.

- [ ] **Step 1: Write the failing tests** in `test_timeline.py`. Read the phases through the session: start, then walk
  with `next` (as `test_session_plan_walk.py` does) and record `(kind, part, round, interval, duration)` per phase:
  - `test_no_switch_before_round_rest`: 3 stations, 2 rounds, switch 15, rest 60, countdown 5 → countdown, w, s, w, s,
    w, **rest**, w, s, w, s, w (no switch after the third work of round 1).
  - `test_rest_zero_joins_rounds`: rest 0 → round 2's first work follows round 1's last work directly.
  - `test_one_station`: 1 station, 3 rounds, switch 15, rest 30 → w, rest, w, rest, w.
  - `test_cooldown_after_rest`: 2 stations, 2 rounds, 2 stretches, hold 30, change 10 → … last circuit work, rest
    (part circuit), work (cooldown, round 1, interval 1, 30), switch (cooldown, interval 1, 10), work (cooldown,
    interval 2).
  - `test_cooldown_rest_zero_and_change_zero`: no rest before it, no switch between stretches.
  - `test_one_stretch`: one cool-down work and nothing after it.
  - `test_total_seconds_is_the_timeline`: for each case above, the program's `total_seconds` equals the sum of the
    non-countdown durations walked, and `totals.planned` in the view equals it too.
  - `test_rounds_completed_ignores_cooldown`: 2 rounds with a cool-down, `end` during the second stretch →
    `rounds_completed` 2 in the finished view.
  - **Existing tests the rule changes**: `test_session_start.py`'s totals cases (e.g. the `675` case) and any
    `total_seconds`/`total_minutes` expectation in `test_programs.py`, `test_mcp.py` and `test_session_plan_walk.py`
    that has a switch before a rest. Recompute each; say in the report which ones changed.
- [ ] **Step 2: Run** `uv run --directory addon/server pytest tests/test_timeline.py -q`. Expected: fail.
- [ ] **Step 3: Implement** `build_timeline` and wire `build_plan` (freeze the stretches with their names, like the
  stations, and the two cool-down times). `phases` reads only `plan.timeline`. `_rounds_behind` counts only
  `part == "circuit"` work. `_station` returns the stretch for a cool-down phase, numbered from 1.
- [ ] **Step 4: Run** the add-on gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): sessions run from a timeline frozen at the start; no break before the round rest`.

### Task 3: The migration for stored plans (add-on)

Model: opus · Review: yes

**Files:**
- Create: `addon/server/src/ha_fitness_server/migrations/versions/0007_plan_timeline.py`
- Test: `addon/server/tests/test_storage.py` (or the file that tests 0005/0006; follow it)

**Interfaces:**
- Consumes: Task 2's `TimelineEntry` JSON shape (the migration writes plain dicts in that shape; it imports nothing
  from `sessions.py` or `timeline.py`).

- [ ] **Step 1: Write the failing tests:** a database at revision 0006 with a stored session whose plan has 3
  stations, 2 rounds, switch 15, rest 60, countdown 5, and `phase_index` on the rest:
  - `test_0007_writes_old_rule_timeline`: after upgrade the plan's `timeline` has a switch before the rest (today's
    rule) and `stretches` is `[]`.
  - `test_0007_running_session_keeps_its_phase`: start the app on that database with a frozen clock; `GET
    /api/v1/session` shows the same phase kind, round and remaining time as before; `next` moves to round 2's first
    work.
  - `test_0007_downgrade_drops_the_keys`: downgrade to 0006 removes `timeline`, `stretches` and the two cool-down
    times.
- [ ] **Step 2: Run** them. Expected: fail.
- [ ] **Step 3: Implement** with a frozen copy of today's `phases` rule inside the migration (switch after every work
  but the last of the last round; rest between rounds), writing `part: "circuit"`.
- [ ] **Step 4: Run** the add-on gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): give stored plans their timeline`.

### Task 4: The session view in the cool-down, and `skip_cooldown` (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `schemas.py` (`SessionPhase.part`, `NextPhase.part`, `SessionTotals.stretches`), `sessions.py`
  (`COMMANDS`, `command`, the view), `api/session.py` (docstring)
- Test: `addon/server/tests/test_session_cooldown.py` (new), `test_session_push.py` (the `phase_changed` event)

**Interfaces:**
- Consumes: Task 2's `Phase.part`, `Plan.stretches`.
- Produces: `part` on `phase` and `next_phase`; `totals.stretches`; command `skip_cooldown` (409 `conflict` outside
  the cool-down and the rest before it).

- [ ] **Step 1: Write the failing tests** with a frozen clock, a program of 2 stations, 2 rounds, rest 20, and 2
  stretches:
  - `test_view_on_last_circuit_work`: `part` circuit, `next_phase.part` circuit (the rest), each participant's
    `stations.next` is stretch 1 (number 1, its name).
  - `test_view_on_rest_before_cooldown`: `part` circuit, `next_phase.part` cooldown, `stations.current` stretch 1 for
    both participants.
  - `test_view_in_cooldown`: on stretch 1 `part` cooldown, `round` 1, `interval` 1, both participants' `current` is
    stretch 1 and `next` stretch 2; on stretch 2 `next` is null; `totals.stretches` 2; `planned` includes the
    cool-down.
  - `test_phase_changed_carries_part`: the push channel's `phase_changed` on entering stretch 1 has `part: cooldown`;
    `session_completed` has no `part`.
  - `test_previous_from_first_stretch`: goes back to the last circuit work phase.
  - `test_next_on_last_stretch_completes`: status `completed`.
  - `test_skip_cooldown_completes_now`: during stretch 1 at +7 s, `skip_cooldown` → `completed`, `ended_at` is now,
    the session time excludes the rest of the cool-down; the change log has `session.completed`; the training day is
    done.
  - `test_skip_cooldown_on_rest_before_and_paused`: allowed on the rest before the cool-down, and while paused in the
    cool-down.
  - `test_skip_cooldown_refused`: 409 `conflict` during the circuit, and in a program with no cool-down.
  - `test_end_in_cooldown_is_ended`: `end` during a stretch → `ended`, counted, `rounds_completed` 2.
- [ ] **Step 2: Run** them. Expected: fail.
- [ ] **Step 3: Implement.** `skip_cooldown` finishes through the same path as `next` on the last work phase, with
  `ended_at` = now.
- [ ] **Step 4: Run** the add-on gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): the cool-down in the session view, and skip_cooldown`.

### Task 5: MCP tools (add-on)

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/mcp_tools.py`
- Test: `addon/server/tests/test_mcp.py`

- [ ] **Step 1: Write the failing tests:** `create_program` and `update_program` accept and return `cooldown`; a bad
  stretch fails with its stretch number in the tool error; the tool descriptions mention `cooldown` and say to send
  it back unchanged on an update the user didn't ask to change it in (assert the field name and the word
  "cooldown" appear in the description, not exact text); `total_minutes` follows the new rule.
- [ ] **Step 2: Run** `uv run --directory addon/server pytest tests/test_mcp.py -q`. Expected: fail.
- [ ] **Step 3: Implement.** Update the tool texts: the cool-down (stretches, hold, change, defaults 30/10), "the break
  between stations comes only between two stations of a round", "leave the timing fields and the cool-down the user
  didn't mention as they are", and that Claude shows the cool-down when it shows a program before writing. Claude may
  suggest a cool-down when making a program.
- [ ] **Step 4: Run** the add-on gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): MCP tools write and describe the cool-down`.

### Task 6: The integration relays `cooldown` and `skip_cooldown`

Model: opus · Review: yes

**Files:**
- Modify: `custom_components/ha_fitness/websocket_api.py` (`SESSION_COMMANDS`, `_program`)
- Modify: `tests/fake_addon.py` (the fake add-on knows `cooldown`, `stretch_names`, `skip_cooldown`)
- Test: `tests/test_websocket.py`

- [ ] **Step 1: Write the failing tests:** `ha_fitness/programs` gives `cooldown: null` for a program without one and
  for an older add-on's program with no `cooldown` key; with one it gives `{stretches: [{exercise_id, name}],
  hold_seconds, change_seconds}`. `ha_fitness/session/command` with `skip_cooldown` reaches the add-on.
- [ ] **Step 2: Run** `uv run pytest tests/test_websocket.py -q`. Expected: fail.
- [ ] **Step 3: Implement.** Pair `cooldown.stretches` with `stretch_names` the way stations pair with
  `station_names`.
- [ ] **Step 4: Run** the integration gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat: relay the cool-down and skip_cooldown to the cards`.

### Task 7: The end-of-work countdown bug (controller, in the fast loop)

Model: controller (Claude in this session; it needs the built-in browser) · Review: no (the fix, if any, goes to an
implementer as a `Review: yes` task)

- [ ] **Step 1:** Run the fast loop (`scripts/develop`, `scripts/seed`), open the tablet view in the built-in browser,
  and log every oscillator start (as the today-ahead spec §1 did). Run a short program (work 10 s, switch 5 s).
- [ ] **Step 2:** Compare the planned beeps at the end of work with those played. Find the root cause
  (superpowers:systematic-debugging).
- [ ] **Step 3:** A code fault: write the fix task (failing test through `workout-flow-pings.test.ts`'s public
  interface, then the fix) and dispatch it before Task 8. Not reproducible, or outside the code: record what was tried
  for the PR, open an issue, and go on (spec §2.1.1's fallback).

### Task 8: Sounds (cards)

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/audio.ts` (`TONES`), `cards/src/workout-flow.ts` (`changeTone`, `tonesOf`, the quiet windows)
- Test: `cards/test/workout-flow-pings.test.ts`, `cards/test/audio.test.ts`

**Interfaces:**
- Produces: `ToneKind = "beep" | "work" | "chime"` (`rest` goes); `work` is 1320 Hz for 1.5 s.

- [ ] **Step 1: Write the failing tests** with the file's fake audio and frozen clock:
  - `end of work: five beeps then the long beep`: a 45 s work phase followed by a switch plans `beep` at 5, 4, 3, 2,
    1 s left and `work` at the end.
  - `start of switch and rest: no beep in the first 1.6 s`: a 6 s switch plans beeps only at 4, 3, 2, 1 s left
    (5 s left falls at +1.0 s).
  - `countdown keeps its beeps`: a 5 s countdown plans 4 beeps (4, 3, 2, 1 s left) and `work` at its end.
  - `last work phase ends with the chime`: the circuit's last work (no next phase) plans 5 beeps and no `work`; the
    chime plays on completion as today. The same for the last stretch.
  - `older add-on`: a view without `part` plans as above.
  - Update the existing tests that expect the `rest` tone or a 1 s `work` tone.
- [ ] **Step 2: Run** `npm test --prefix cards`. Expected: the new tests fail.
- [ ] **Step 3: Implement.** Every boundary into or out of a work phase plays `work`; a phase starting with `work`
  has a 1.6 s quiet window; the countdown keeps `QUIET_MS`.
- [ ] **Step 4: Run** the cards gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(cards): five beeps and a 1.5 s long beep at both ends of work`.

### Task 9: The cool-down on the tablet (cards)

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/overlay.ts` (types: `part?`, `totals.stretches?`, `skip_cooldown`), `cards/src/flow/timer.ts`,
  `cards/src/flow/details.ts` (`Program.cooldown?`), `cards/src/workout-flow.ts` (the Skip command and its
  question), `cards/src/i18n/en.json`, `cards/src/i18n/da.json`
- Test: `cards/test/workout-flow-timer.test.ts`, `cards/test/workout-flow-details.test.ts`

- [ ] **Step 1: Write the failing tests** by rendered text and role, for one and two people, following spec §4.7's
  table row by row:
  - Last circuit work: "Next: cool-down · <first stretch>" (two people); the NEXT card titled "COOL-DOWN" (one).
  - Rest before the cool-down: "COOL-DOWN NEXT" in place of "GO TO THE NEXT STATION"; no station badge; a "Skip
    cool-down" button.
  - A hold: ring word "STRETCH", a "Cool-down" pill with "2 / 4", no Round/Interval pills, no station badge, "Next:
    <stretch>" and none after the last; "seconds left" under the number.
  - A change: ring word "CHANGE", "NEXT STRETCH".
  - Skip: the button asks "Skip the cool-down?"; Yes sends `skip_cooldown`; a tap within `ARM_MS` of showing does
    nothing; No closes the question.
  - Circuit details: the stretches below the stations with the hold and change times; the total includes them; no
    cool-down section when `cooldown` is null or missing.
  - An older add-on (no `part`, no `totals.stretches`) renders the circuit as today.
  - Danish texts exist for every new key (the i18n test covers key parity).
- [ ] **Step 2: Run** `npm test --prefix cards`. Expected: fail.
- [ ] **Step 3: Implement.** Ring word for a cool-down `switch` is CHANGE, for a cool-down `work` STRETCH. The rest
  before the cool-down is found from `next_phase.part === "cooldown"` while `phase.part` is `circuit`.
- [ ] **Step 4: Run** the cards gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(cards): the cool-down on the tablet, with Skip cool-down`.

### Task 10: The cool-down in the program editor (website)

Model: opus · Review: yes

**Files:**
- Modify: `addon/web/src/api.ts` (types, defaults), `addon/web/src/pages/program-editor.ts` (the section, the total,
  `placeOf`), `addon/web/src/i18n/en.json`, `addon/web/test/fake-api.ts`
- Test: `addon/web/test/editor.test.ts`

**Interfaces:**
- Consumes: Task 1's REST shape and refusal codes; Task 2's rule (the TS total mirrors `build_timeline`).

- [ ] **Step 1: Write the failing tests:**
  - A "Cool-down" section below the stations: add two stretches with the exercise picker, set hold 40 and change 5,
    Save sends `cooldown: {stretches: [{exercise}, …], hold_seconds: 40, change_seconds: 5}`.
  - Removing the last stretch and saving sends `cooldown: null`.
  - Opening a program with a cool-down shows its stretches and times.
  - A `stretch_unknown` refusal at `cooldown.stretches.1` shows at the second stretch.
  - The total: the same cases as Task 2's `test_timeline.py` (no switch before the rest, rest 0, one station, a
    cool-down with and without rest and change) give the same minutes.
- [ ] **Step 2: Run** `npm test --prefix addon/web`. Expected: fail.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the website gates. Expected: all pass.
- [ ] **Step 5: Commit** `feat(addon): the cool-down in the program editor`.

### Task 11: Docs and decisions

Model: sonnet · Review: no

**Files:**
- Modify: `docs/domain-language.md`, `docs/architecture.md`, `docs/decisions.md`

- [ ] **Step 1:** Make spec §7's changes: the domain terms (Interval, Rest between rounds, Phase — no longer "a
  stretch of the timer", Plan; new Cool-down, Stretch, Hold time, Change time, Timeline); the architecture's plan,
  finishing, the `skip_cooldown` command in both command lists, `part`, and `cooldown` in `ha_fitness/programs`;
  D70–D72 as spec §6 words them, and D41's status `active; total_seconds part superseded by D70`.
- [ ] **Step 2: Run** `uv run python scripts/check_links.py`. Expected: pass.
- [ ] **Step 3: Commit** `docs: the cool-down, the timeline and the break rule`.

## After the tasks

The branch review (`full-reviewer`), the gates, the fast loop with a cool-down program for two people, the Chrome
check with screenshots in `screenshots/cooldown/`, and the sounds by ear. Then the PR (`feat:` title, `Closes #106`).
