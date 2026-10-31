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

**Builds on:** the session engine and the plan (step 5 spec §3.1–§3.5, D40, D41), the workout sounds (step 5 spec
§5.4, the start beep in the today-ahead spec §2.4), the program document (design spec §5.1), the refusal codes (D65),
the program website (website spec) and the MCP tools (programs-through-chat spec).

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
   them, and the tone tests pass; the music on the speaker masking them is possible. The builder finds the root cause
   first, by reproducing it in the fast loop with the oscillators logged, the way the start-beep bug was found
   (today-ahead spec §1). A code fault gets a fix and a test that fails without it.
   **Fallback:** if the fast loop can't reproduce it, or the cause is outside the code, the builder records what was
   tried in the PR, opens an issue for it, and still ships §2.1.2–§2.1.5.
2. **The end of work** plays the 5 countdown beeps and then the long beep.
3. **The long beep** is the same at the start and at the end of work: the high tone (1320 Hz), now 1.5 s long (today
   1.0 s). So every phase change into or out of a work phase plays the long beep. The low change tone (`rest`) is no
   longer used, and goes.
4. **No countdown beep during the long beep.** A phase that starts with the long beep plays no countdown beep in its
   first 1.6 s (the beep plus a margin). Today only a work phase has such a window (`WORK_QUIET_MS`, 1.1 s). The
   countdown has no start tone, so it keeps today's 0.3 s window (`QUIET_MS`) and its beeps. A phase too short for its
   window plus 5 s plays fewer countdown beeps.
5. **The end of the last work phase** of the session (the circuit's last, or the last stretch) plays the 5 countdown
   beeps and the chime, with no long beep. *Claude's call.*

### 2.2 The break between rounds

1. After the last station of a round, no break between stations follows. The rest between rounds follows directly.
2. With the rest between rounds set to 0, the next round starts straight after the last station, with no break, even
   though everyone moves one station (Thomas, 2026-10-31).
3. The total time of a program (`total_seconds`, the website editor's total, `total_minutes` in MCP) follows the same
   rule (§4.2).

### 2.3 The cool-down

1. A program can have a **cool-down**: a list of stretches after the last round. A program without one runs as today.
2. In the cool-down everyone does the **same stretch at the same time**. There is no rotation.
3. Each stretch is **one hold** of the cool-down's hold time, the same for every stretch. A short **change** to move
   into the next position comes between stretches.
4. **The rest before it:** after the last round, the rest between rounds comes, then the first stretch. With that rest
   at 0, the first stretch starts straight away. *Claude's call.*
5. **Skip cool-down:** during the cool-down, and during the rest right before it, the tablet shows a **Skip cool-down**
   button next to End. It completes the session now (§4.5). The training counts as done, and the Complete screen
   follows, with the feeling question.
6. **Counting:** a session counts as today, by its completed circuit rounds (`rounds_completed >= 1`). The cool-down
   adds the time actually spent in it to the session's time and to `time_trained`. HA Fitness has no per-exercise
   stats, so there is nothing more to count.
7. **End** and the pause limit during the cool-down work as today: the session is `ended`, it counts with all its
   rounds, and there is no feeling question.
8. **Sounds:** the same as the circuit (§2.1). A stretch is a work phase.

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
  change_seconds: 10         # 0–60, default 10: the change between stretches
```

- The ranges and defaults are *Claude's calls*. `GET /api/v1/programs/defaults` adds `cooldown_hold_seconds` and
  `cooldown_change_seconds`.
- **No stretches means no cool-down,** and that is written as `cooldown: null`. `cooldown` with an empty `stretches`
  list is refused (422 `invalid`, field `cooldown.stretches`).
- A stretch is any exercise of the library. The library has stretches (for example "overhead triceps stretch"), but
  nothing stops another exercise. A stretch that can't be resolved is refused like a station, with its own codes and
  field (D65): `stretch_unknown` or `stretch_shared`, at `cooldown.stretches.<index from 0>`.
- `ProgramOut`: `station_names` stays the stations only, so 1.x integrations, which pair it with `stations`, keep
  working. A new `stretch_names` holds the stretches' names (empty with no cool-down). `equipment` includes the
  stretches' equipment.
- The change log names `cooldown` without its value, like `stations` (`_NAMED_ONLY`).
- The change is additive: a stored program, an export and an MCP write without `cooldown` stay valid.

### 4.2 The timeline

The plan gets `timeline`, a list of phases built at the start, and `stretches`, the cool-down's stretches frozen with
their names like the stations (D40), with the hold and change times. Each timeline entry has:

| Field | Meaning |
| --- | --- |
| `kind` | `countdown`, `work`, `switch` or `rest`, as today |
| `part` | `circuit` or `cooldown` |
| `round`, `interval` | the circuit as today. The rest before the cool-down keeps the last round and station count. In the cool-down `round` is 1 and `interval` is the stretch's number from 1 (a change: the stretch it follows) |
| `duration` | seconds |
| the work it leads to | the station offset of the work phase at or after it (circuit), or the stretch's index (cool-down) |

The builder walks the program:

1. The countdown, if `countdown_seconds` > 0.
2. Per round: per station a `work`, and a `switch` after it unless it is the round's last station.
3. Between rounds: a `rest` of `round_rest_seconds`, if > 0.
4. With a cool-down: a `rest` of `round_rest_seconds` after the last round, if > 0, with part `circuit`. Then per
   stretch a `work` (part `cooldown`), and a `switch` (part `cooldown`) of `change_seconds` between stretches, if > 0.

`phases(plan)` reads `plan.timeline`. The plan's numbers (`rounds`, `work_seconds` …) stay in the plan for the views
and the history.

- `rounds_completed` counts only `circuit` work phases. The cool-down's `round` 1 must not count as a round.
- `previous` from the first stretch goes back to the start of the last circuit work phase, as `previous` does across
  any phase change today.
- A program's `total_seconds` is the sum of the builder's timeline without the countdown, so it can't drift from the
  session. Today's formula counts a switch after the very last station, which the session never runs; that goes too.
- The website editor's total is a second copy of the rule, in TypeScript. Its tests use the same cases as the
  builder's.

### 4.3 Stored sessions

An Alembic migration writes the timeline into every stored plan, built with **today's** rule (with the switch before
the rest). The migration carries its own frozen copy of that rule; it doesn't import the builder or `phases`, which
would apply the new rule and move stored phase indexes. So a session that was running or stored before the update
keeps its phases, and its phase index still points at the same phase. After the migration every plan has a timeline,
and the code has one path. `downgrade` drops the `timeline` and `stretches` keys. The migration is tested on a plan
stored before it.

### 4.4 The session view and events

- `SessionPhase` and `NextPhase` get `part: "circuit" | "cooldown"`. The phase kinds don't change. The rest before
  the cool-down is `circuit`. `session_started`, `session_completed` and `session_ended` don't get `part`. *Claude's
  call.*
- In the cool-down every participant's `stations.current` is the stretch, and `next` the following stretch (null after
  the last). `StationRef.number` is the stretch's number from 1. On the last circuit work phase and the rest before
  the cool-down, `next` / `current` name the first stretch, by the "work it leads to" rule.
- `SessionTotals` gets `stretches` (0 with no cool-down). `planned` includes the cool-down.
- **Why this shape:** both parts are at 1.x, so neither may need a newer version of the other
  ([architecture](../../architecture.md#the-contract-between-the-add-on-and-the-integration)). `api_version` stays 1.
  - **An older card** with a newer add-on doesn't know `part`. It shows a stretch as a work phase at a station, and
    the rest before the cool-down as a move to the next station. The session still runs and counts.
  - **A newer card** with an older add-on finds no `part` and treats it as `circuit`; no `totals.stretches` reads as
    0, and no `cooldown` from `ha_fitness/programs` as none.

### 4.5 Skip cool-down

- A new session command, `skip_cooldown`, through `POST /api/v1/session/{command}` like the others, and through the
  integration's session command (`SESSION_COMMANDS` in `custom_components/ha_fitness/websocket_api.py`).
- It is allowed, running or paused, while the current phase is in the cool-down or is the rest right before it.
  Otherwise 409 `conflict`.
- It finishes the session **now**, as `completed`, the way `next` on the last work phase does: `ended_at` is now, so
  the skipped stretches add no time. The same events, the same change-log entry (`session.completed`), the same
  counting.
- The tablet asks first, like End, with the same guard against a wake tap (`ARM_MS`): "Skip the cool-down?" Yes / No.

### 4.6 The integration

`ha_fitness/programs` (`_program()` in `websocket_api.py`) adds `cooldown` to each program: `null` with none, else the
stretches with their ids and names, `hold_seconds` and `change_seconds`. With an older add-on, which sends no
`cooldown`, it sends `null`.

### 4.7 The tablet

The cool-down's timer is the circuit's layout, chosen by Thomas from two mockups (2026-10-31, option B, below). The
screen during each phase:

| Phase | Ring word | Above / below the ring | Person cards (two people) | One person |
| --- | --- | --- | --- | --- |
| Last circuit work | WORK | as today | "Next: cool-down · <first stretch>" in place of "Next: station …" | the NEXT card shows the first stretch, titled "COOL-DOWN" |
| Rest before the cool-down | REST | as today | the first stretch, no station badge; "COOL-DOWN NEXT" in place of "GO TO THE NEXT STATION" | as two people |
| Stretch (hold) | STRETCH | a "Cool-down" pill with `n / N` above; nothing below | the stretch with its GIF, no station badge; "Next: <stretch>" (none after the last) | the stretch; the NEXT card shows the next stretch |
| Change | CHANGE | as for a hold | the next stretch; "NEXT STRETCH" in place of "GO TO THE NEXT STATION" | as two people |

- Under the number the ring keeps "seconds left", as today. The mockup's "then 10 s to change" is not built.
- **Skip cool-down** sits next to End during the rest before the cool-down and the cool-down (§4.5).
- **Circuit details** lists the stretches below the stations, with the hold and change times, and the total time
  includes them. **Get ready** doesn't change. *Claude's calls.*
- Every new text is in `en.json` and `da.json`. Stretch names are exercise names and are not translated.

The chosen mockup (dark boxes are the GIF; the real screen follows the built screens' light theme, D51, D52):

```text
┌───────────────────────────────────────────────────────────────────┐
│ ♫ music                          38:10 / 44:00  [Skip cool-down] [End] │
│                                                                   │
│ ┌──────────────┐        ( Cool-down 2 / 4 )       ┌──────────────┐ │
│ │ (1) Thomas   │            ╭────────╮            │ (2) Elin     │ │
│ │ ┌──────────┐ │            │STRETCH │            │ ┌──────────┐ │ │
│ │ │   GIF    │ │            │   24   │            │ │   GIF    │ │ │
│ │ └──────────┘ │            │secs left│           │ └──────────┘ │ │
│ │ Seated lower │            ╰────────╯            │ Seated lower │ │
│ │ back stretch │                                  │ back stretch │ │
│ │ Next: …      │                                  │ Next: …      │ │
│ └──────────────┘                                  └──────────────┘ │
│                         [◀]  [ ❚❚ ]  [▶]                          │
└───────────────────────────────────────────────────────────────────┘
```

### 4.8 The website and MCP

- **The program editor** gets a Cool-down section below the stations: add, remove and reorder stretches with the same
  exercise picker as stations, and the hold and change times. Removing the last stretch removes the cool-down, and
  Save sends `cooldown: null`. A stretch refusal (`cooldown.stretches.<i>`) shows at that stretch, as a station's does
  (`placeOf`). The program's total includes the cool-down. The website is English only (D62).
- **MCP:** the program tools accept and return `cooldown`. The tool texts describe it, its refusal ("fails with the
  stretch number"), and the new break rule. "Leave the timing fields the user didn't mention as they are" covers the
  cool-down too: `update_program` replaces the whole document, so a cool-down left out is deleted. When Claude makes
  a program it may suggest a cool-down; when it shows the program before writing, it shows the cool-down too.

## 5. Testing

- **Add-on:** the builder's timeline for: no switch before the rest; rest 0; switch 0; a cool-down with and without
  the rest before it; one stretch; change 0. Totals and `total_seconds` match the timeline. `rounds_completed` with a
  cool-down. The session view on the last circuit work, the rest before the cool-down and in the cool-down (part,
  stations, next). `skip_cooldown`: allowed (running and paused) and refused, and what it records. `previous` from the
  first stretch. The migration on a plan stored before it, and its downgrade. MCP and REST round-trips of `cooldown`,
  the empty-list refusal, and the stretch refusal codes.
- **Integration:** `ha_fitness/programs` with and without `cooldown`; `skip_cooldown` through the session command.
- **Cards:** the tone plan for a work phase's end (5 beeps then the long beep), a switch or rest's start, the quiet
  windows (the countdown keeps its 4 beeps at 5 s), the last work phase (beeps then chime), and the bug's case if it is
  a code fault, through the public interface as the tone tests do now. The cool-down screens of §4.7's table, the Skip
  button and its question, by rendered text and role. Circuit details with a cool-down.
- **Website:** the Cool-down section writes and reads `cooldown`, removing the last stretch sends `null`, a stretch
  refusal shows at the stretch, and the total matches the builder's cases.
- **Fast loop and the Chrome check:** a program with a cool-down, run with two people, with screenshots of the
  cool-down screens. The sounds by ear in the fast loop.
- **Full loop** before the release ([releasing](../../releasing.md)).

## 6. Decisions to log

- **D70: no break before the rest between rounds.** The break between stations comes only between two stations of a
  round. `total_seconds` is the timeline's length. D41 gets the status `active; total_seconds part superseded by D70`.
- **D71: the plan stores the timeline**, built at the start; nothing rebuilds it later (§2.4).
- **D72: cool-down phases keep the phase kinds and carry a `part`**, so the contract stays at `api_version` 1 (§4.4).

## 7. Docs to update

- `docs/domain-language.md`: Interval, Rest between rounds, Phase (no longer "a stretch of the timer"), Plan (the
  timeline and the stretches); new entries for Cool-down, Stretch, Hold time, Change time and Timeline.
- `docs/architecture.md`: the plan, finishing, the session command row and the `ha_fitness/session/command` list
  (`skip_cooldown`), the `part` field, and `ha_fitness/programs`' `cooldown`.
- `docs/decisions.md`: D70–D72, and D41's status.

## 8. Left to the builder

- The names of the timeline's model and fields, as long as §4.2's content is there.
- How the cards tell the rest before the cool-down apart (the next phase's `part`, or a field on the view).
- The Danish texts.
