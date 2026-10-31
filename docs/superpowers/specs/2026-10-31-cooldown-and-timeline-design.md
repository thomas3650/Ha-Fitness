# The cool-down, the timeline, the end-of-work beeps and the break between rounds

**Status:** Thomas handed the approval and the merge to Claude (chat, 2026-10-31). Issue #106, in one branch and one
PR.

**Real Home Assistant:** yes, after the release. Both the add-on and the integration (with the cards) change, so both
release. The release's `fitness` issue says:

- Programs can have a cool-down of stretches after the last round. Claude can add one when making a program.
- During a cool-down, the session view and the `phase_changed` event carry `part: "cooldown"`. The phase kinds stay
  `countdown`, `work`, `switch` and `rest`. The other session events don't change.
- A new session command, `skip_cooldown`, completes a session during its cool-down.
- A session no longer has a break between stations right before the rest between rounds, so a program's total time is
  shorter.

House automations that use the phase events may need a look.

**Builds on:** the session engine and the plan (step 5 spec §3.1–§3.5), the workout sounds (step 5 spec §5.4, the
start beep in the today-ahead spec §2.4), the program document (design spec §5.1), the program website (website spec)
and the MCP tools (programs-through-chat spec).

## 1. Why

Thomas did the first real training on 2026-10-30, two people at five stations in the living room. His comments, in
chat on 2026-10-31:

- **The end of work.** When the 45 s of work ended he heard one short beep. He missed the 5 countdown beeps and a
  long beep. The countdown beeps at the end of a break, before work, did play.
- **The long beep** can be 1.5 s.
- **Between rounds** there was first the 15 s break and then the 1 min rest. Only the 1 min rest is wanted.
- **The data structure** should be looked at before building, so it can take later changes.

The brainstorm that followed settled the later changes (§2.3, §3).

## 2. Goals

### 2.1 Sounds

1. **Bug:** at the end of a work phase the 5 countdown beeps (at 5, 4, 3, 2 and 1 s left) play, as they already do at
   the end of a break or rest. The cause is not known. `tonesOf` in `cards/src/workout-flow.ts` looks like it plans
   them, and the tone tests pass. The builder finds the root cause first, by reproducing it in the fast loop with the
   oscillators logged, the way the start-beep bug was found (today-ahead spec §1). The fix comes with a test that
   fails without it.
2. **The end of work** plays the 5 countdown beeps and then the long beep.
3. **The long beep** is the same at the start and at the end of work: the high tone (1320 Hz), now 1.5 s long (today
   1.0 s). So every phase change into or out of a work phase plays the long beep. The low change tone (`rest`) is no
   longer used, and goes.
4. **No countdown beep during the long beep.** Today a work phase plays no countdown beep in its first 1.1 s
   (`WORK_QUIET_MS`), because the long beep sounds there. With the long beep at both ends of work, every phase gets a
   quiet window that covers the 1.5 s long beep. A phase shorter than the window plus 5 s plays fewer countdown beeps.
5. **The end of the last work phase** of the session (the circuit's last, or the last stretch) plays the 5 countdown
   beeps and the chime, with no long beep. *Claude's call.*

### 2.2 The break between rounds

1. After the last station of a round, no break between stations follows. The rest between rounds follows directly.
2. With the rest between rounds set to 0, the next round starts straight after the last station.
3. The total time of a program (`total_seconds`, the website editor's total, `total_minutes` in MCP) follows the same
   rule.

### 2.3 The cool-down

1. A program can have a **cool-down**: a list of stretches after the last round. A program with no stretches has no
   cool-down, and runs as today.
2. In the cool-down everyone does the **same stretch at the same time**. There is no rotation.
3. Each stretch is **one hold** of the cool-down's hold time, the same for every stretch. A short break to change
   position comes between stretches.
4. **The rest before it:** after the last round, the rest between rounds comes, then the first stretch. With that rest
   at 0, the first stretch starts straight away. *Claude's call.*
5. **Skip cool-down:** during the cool-down, and during the rest right before it, the tablet shows a **Skip cool-down**
   button next to End. It completes the session as if the cool-down had run. The training counts as done, and the
   Complete screen follows, with the feeling question.
6. **Counting:** a session counts as today, by its completed circuit rounds (`rounds_completed >= 1`). The cool-down
   adds to the session's time and to `time_trained` like any other phase. HA Fitness has no per-exercise stats, so
   there is nothing more to count.
7. **Sounds:** the same as the circuit (§2.1). A stretch is a work phase.

### 2.4 The timeline is frozen at the start

1. When a session starts, the plan stores its **timeline**: the full list of phases, built once from the program.
2. The session engine, the views, the totals, `rounds_completed` and the history read the timeline. Nothing rebuilds
   it from the plan's numbers after the start.
3. **Why:** one place, the builder, knows the timing rules. A later change to them (a warm-up, another kind of part)
   changes only the builder. A running or stored session keeps the timeline it started with.

## 3. Non-goals

- **A warm-up.** Thomas and Elin don't do one (Thomas, 2026-10-31). The timeline leaves room for one later.
- **A work time per station.** All stations keep one work time (Thomas, 2026-10-31).
- **A rest per round.** All gaps between rounds keep one rest (Thomas, 2026-10-31).
- **Left and right sides of a stretch.** A stretch is one hold (Thomas, 2026-10-31).
- **A hold time per stretch.** One hold time for the whole cool-down. *Claude's call; the brainstorm's guess, which
  Thomas accepted.*
- **Clearing the history.** Thomas allowed it (2026-10-31), but it isn't needed: a migration gives the stored plans
  their timeline (§4.3). *Claude's call.*

## 4. Design

### 4.1 The program document

The program stays the circuit, as today, with one new optional field:

```text
cooldown:                    # null or missing: no cool-down
  stretches:                 # 1–10 entries; each like a station, an exercise by id or unique name
    - exercise: seated lower back stretch
    - exercise: overhead triceps stretch
  hold_seconds: 30           # 10–120, default 30
  switch_seconds: 10         # 0–60, default 10: the break to change position between stretches
```

- The ranges and defaults are *Claude's calls*. `GET /api/v1/programs/defaults` adds `cooldown_hold_seconds` and
  `cooldown_switch_seconds`.
- A stretch is any exercise of the library. The library has stretches (for example "overhead triceps stretch"), but
  nothing stops another exercise. Equipment and `station_names` cover the stretches too (`ProgramOut` gets
  `stretch_names`).
- The change is additive: a stored program, an export and an MCP write without `cooldown` stay valid.

### 4.2 The timeline

The plan gets `timeline`, a list of phases built at the start. Each entry has:

| Field | Meaning |
| --- | --- |
| `kind` | `countdown`, `work`, `switch` or `rest`, as today |
| `part` | `circuit` or `cooldown` |
| `round`, `interval` | as today in the circuit; in the cool-down, `round` is 1 and `interval` is the stretch's number from 1 |
| `duration` | seconds |
| the work it leads to | the station offset of the work phase at or after it (circuit), or the stretch's index (cool-down) |

The builder walks the program:

1. The countdown, if `countdown_seconds` > 0.
2. Per round: per station a `work`, and a `switch` after it unless it is the round's last station.
3. Between rounds: a `rest` of `round_rest_seconds`, if > 0.
4. With a cool-down: a `rest` of `round_rest_seconds` after the last round, if > 0. Then per stretch a `work` (part
   `cooldown`), and a `switch` of the cool-down's `switch_seconds` between stretches, if > 0.

`phases(plan)` reads `plan.timeline`. The plan's numbers (`rounds`, `work_seconds` …) stay in the plan for the views
and the history.

- `rounds_completed` counts only `circuit` work phases. The cool-down's `round` 1 must not count as a round.
- A program's `total_seconds` is the sum of the builder's timeline without the countdown, so it can't drift from the
  session. Today's formula counts a switch after the very last station, which the session never runs; that goes too.
  The website editor's own total mirrors the builder in TypeScript.

### 4.3 Stored sessions

An Alembic migration writes the timeline into every stored plan, built with **today's** rule (with the switch before
the rest). So a session that was running or stored before the update keeps its phases, and its phase index still
points at the same phase. After the migration every plan has a timeline, and the code has one path. The migration is
tested on a plan stored before it.

### 4.4 The session view and events

- `SessionPhase` and `NextPhase` get `part: "circuit" | "cooldown"`. The phase kinds don't change. The rest before
  the cool-down is `circuit`. `session_started`, `session_completed` and `session_ended` don't get `part`. *Claude's
  call.*
- In the cool-down every participant's `stations.current` is the stretch, and `next` the following stretch (null after
  the last). `StationRef.number` is the stretch's number from 1.
- `SessionTotals` gets `stretches` (0 with no cool-down). `planned` includes the cool-down.
- **Why this shape:** both parts are at 1.x, so neither may need a newer version of the other
  ([architecture](../../architecture.md#the-contract-between-the-add-on-and-the-integration)). An older card that
  doesn't know `part` shows a stretch as a work phase at a station, which still runs. A newer card reading an older
  add-on finds no `part` and treats it as `circuit`. So `api_version` stays 1.

### 4.5 Skip cool-down

- A new session command, `skip_cooldown`, through `POST /api/v1/session/{command}` like the others, and through the
  integration's path for session commands, which the cards use (`SESSION_COMMANDS` in
  `custom_components/ha_fitness/websocket_api.py`).
- It is allowed while the current phase is in the cool-down, or is the rest right before it. Otherwise 409
  `conflict`.
- It finishes the session as `completed`, as if the last phase had ended: the same events, the same counting, the same
  Complete screen.

### 4.6 The tablet

- **Timer during the cool-down:** the circuit's layout, chosen by Thomas from two mockups (2026-10-31, option B). Each
  person's card shows the same stretch, with its GIF, and "Next: <stretch>". The top shows "Cool-down 2 / 4" in place
  of "Round / Interval". The ring's label is "STRETCH" during a hold. The text under the number names the next phase
  as today.
- **Skip cool-down** sits next to End during the cool-down and the rest before it (§2.3.5).
- **Circuit details and Get ready:** the details list the stretches below the stations, and the total time includes
  them. *Claude's call.*
- Every new text is in `en.json` and `da.json`. Stretch names are exercise names and are not translated.

### 4.7 The website and MCP

- **The program editor** gets a Cool-down section below the stations: add, remove and reorder stretches with the same
  exercise picker as stations, and the hold and change times. The program's total includes it. The website is English
  only (D62).
- **MCP:** the program tools accept and return `cooldown`. The tool texts describe it and the new break rule. When
  Claude makes a program it may suggest a cool-down; when it shows the program before writing, it shows the cool-down
  too.

## 5. Testing

- **Add-on:** the builder's timeline for: no switch before the rest; rest 0; switch 0; a cool-down with and without
  the rest before it; one stretch; cool-down switch 0. Totals and `total_seconds` match the timeline. The session view
  in the cool-down (part, stations, next). `skip_cooldown`: allowed and refused, and what it records. The migration on
  a stored plan. MCP and REST round-trips of `cooldown`.
- **Cards:** the tone plan for a work phase's end (5 beeps then the long beep), a switch or rest's start, the quiet
  window, the last work phase (beeps then chime), and the bug's case, through the public interface as the tone tests
  do now. The cool-down screen's texts and the Skip button, by rendered text and role.
- **Website:** the Cool-down section writes and reads `cooldown`, and the total.
- **Fast loop and the Chrome check:** a program with a cool-down, run with two people, with screenshots of the
  cool-down screen. The sounds by ear in the fast loop.
- **Full loop** before the release ([releasing](../../releasing.md)).

## 6. Decisions to log

- **The plan stores the timeline**, built at the start; nothing rebuilds it later (§2.4).
- **Cool-down phases keep the phase kinds and carry a `part`**, so the contract stays at `api_version` 1 (§4.4).

## 7. Left to the builder

- The names of the timeline's model and fields, as long as §4.2's content is there.
- How the cards tell the cool-down's rest-before apart for the Skip button (the next phase's `part`, or a field on the
  view).
- The Danish texts.
