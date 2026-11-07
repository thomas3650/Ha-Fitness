# The timer's time-left band, the music volume slider and clearer beeps: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** the timer shows the whole workout's time left in a thick band split into rounds, has no transport buttons
(the ring pauses and resumes), a music volume slider, and longer, higher, louder countdown beeps with an inaudible
keep-alive.

**Architecture:** the add-on adds `totals.marks` from the frozen timeline. The integration adds `volume` to the music
state and a `volume` action to `ha_fitness/music`. The cards change the tones, add the keep-alive, rebuild the timer
layout and add the slider.

**Tech Stack:** Python 3 / FastAPI / pydantic (add-on), Home Assistant custom integration (Python), Lit + TypeScript +
Vitest (cards).

**Spec:** [`docs/superpowers/specs/2026-11-07-timer-band-and-volume-design.md`](../specs/2026-11-07-timer-band-and-volume-design.md)
and the mockup [`docs/mockups/TimerBand.png`](../../mockups/TimerBand.png). Every task reads the spec section it names.

## Global Constraints

- CLAUDE.md's hard rules: tests through public interfaces (REST, websocket, rendered text and roles; no snapshot,
  CSS-selector or exact-log tests), a frozen clock for anything time-based, every UI text from a language file (`en`
  and `da`).
- The gates in CLAUDE.md pass before every commit for the part touched.
- `api_version` stays 1. Every new field is additive; an older counterpart without it must keep working.
- Commits: Conventional Commits with the dispatch's co-author trailer, `git commit -F <file>`; never push.
- The countdown beep: **1175 Hz, 0.25 s**. `VOLUME` **0.5** for every tone. The long beep (1320 Hz, 1.5 s) and the
  chime don't change.
- The keep-alive: one oscillator, **not below 100 Hz**, gain **at most 0.001**, its own node.
- The slider: levels 0–100 (integers); sent at most every **300 ms** while dragging, and once on release.
- D52: text keeps 4.5:1 contrast; the band's texts are the theme's primary text colour.

## Review Focus

1. **A session with no music, or music on the speaker without `VOLUME_SET`:** the player shows as today, with no
   slider and no error (Task 4 test `no slider without volume`).
2. **Elapsed beyond planned** (a `previous` through REST restarts a phase): the time left shows 0:00, never negative,
   and the fill stays at 100 % (Task 3 test `time left never below zero`).
3. **An older add-on without `marks`:** the band draws with no gaps, and nothing throws (Task 3 test `no gaps without
   marks`).
4. **Sound locked, then unlocked mid-session by "Tryk for lyd":** the keep-alive starts on the unlock; while locked
   nothing starts (Task 2 test `keep-alive starts on a mid-session unlock`).
5. **A music state arriving mid-drag** (the speaker echoes the first set): the thumb doesn't jump back (Task 4 test
   `a state while held doesn't move the thumb`).

---

### Task 1: The add-on's `totals.marks`

Model: opus · Review: yes

**Files:**
- Modify: `addon/server/src/ha_fitness_server/schemas.py` (`SessionTotals`)
- Modify: `addon/server/src/ha_fitness_server/sessions.py` (`_totals`)
- Test: `addon/server/tests/test_timeline.py` or a new `addon/server/tests/test_session_marks.py`; fix the exact
  `totals` asserts in `test_session_start.py` (lines ~148, ~247) and `test_session_cooldown.py` (~160)
- Docs: `docs/architecture.md` (the session view's totals), `docs/decisions.md` (D74, text in spec §6)

**Interfaces:**
- Produces: `SessionTotals.marks: list[int]` in every session view (current and finished; REST, push, MCP).

- [ ] **Step 1: Write the failing tests** through the session REST view (`GET /api/v1/session` after a start, using
  `session_helpers.py`). Programs and expected `marks` (work `W`, switch `S`, round rest `R`, countdown 10 s):
  - `one round, no cool-down`: 1 round, 3 stations → `[]`.
  - `rounds with a round rest`: 3 rounds, 2 stations, W=40, S=10, R=60 → round length 40+10+40 = 90; marks
    `[150, 300]` (90+60, 90+60+90+60).
  - `rounds with no round rest`: 3 rounds, 2 stations, W=40, S=10, R=0 → `[90, 180]`.
  - `one station`: 2 rounds, 1 station, W=30, R=20 → `[50]`.
  - `cool-down after a rest`: 2 rounds, 2 stations, W=40, S=10, R=60, cool-down of 2 stretches → `[150, 300]`
    (the rest after round 2 belongs to round 2; the cool-down starts at 90+60+90+60).
  - `cool-down with no rest`: as above with R=0 → `[90, 180]`.
  - `no countdown`: the `rounds with a round rest` program with countdown 0 → the same marks.
  - A finished session in `GET /api/v1/sessions` carries the same `marks`.
- [ ] **Step 2: Run** `uv run --directory addon/server pytest tests/test_session_marks.py -v` → FAIL (no `marks`).
- [ ] **Step 3: Implement** `marks: list[int]` on `SessionTotals` (docstring per spec §3), and in `_totals` walk
  `plan_phases` with a running sum of non-countdown durations, appending the sum before each phase that is the first
  work of a round > 1 (part circuit) or the first phase with part `cooldown`.
- [ ] **Step 4: Run** the new tests and the whole add-on gate → PASS; update the three exact asserts.
- [ ] **Step 5: Docs:** `architecture.md` names `totals.marks` (one sentence, additive, `api_version` 1); D74 in
  `decisions.md` per spec §6.
- [ ] **Step 6: Commit** `feat(addon): totals.marks, where each round and the cool-down start`.

### Task 2: The tones and the keep-alive

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/audio.ts` (`TONES.beep`, `VOLUME`, keep-alive)
- Modify: `cards/src/workout-flow.ts` (start and stop the keep-alive)
- Modify: `cards/test/fake-audio.ts` (record each tone's peak gain; keep the keep-alive apart)
- Test: `cards/test/audio.test.ts`, `cards/test/workout-flow-pings.test.ts`

**Interfaces:**
- Produces in `audio.ts`: `export const KEEP_ALIVE_HZ: number` (≥ 100), `export function startKeepAlive(): void`
  (idempotent; does nothing with no running context), `export function stopKeepAlive(): void` (idempotent).
- Produces in `fake-audio.ts`: `FakeTone.peak: number` (the highest gain value set on the tone's gain node);
  oscillators whose frequency is set to `KEEP_ALIVE_HZ` are not in `tones` but in `context.keepAlives: FakeTone[]`.

- [ ] **Step 1: Write the failing tests:**
  - `audio.test.ts` `the countdown beep`: `scheduleTone("beep", …)` makes one tone at 1175 Hz, stopping 0.25 s after
    its start, with `peak` 0.5. `every tone at volume 0.5`: `work` and each chime note have `peak` 0.5.
  - `audio.test.ts` `keep-alive`: `startKeepAlive()` on a running context makes one keep-alive at `KEEP_ALIVE_HZ`,
    `KEEP_ALIVE_HZ >= 100`, gain ≤ 0.001, not in `tones`; a second call adds none; `stopKeepAlive()` stops it; on a
    locked context nothing starts.
  - `workout-flow-pings.test.ts`: `keep-alive while running` (a running timer view → one live keep-alive),
    `keep-alive stops on pause`, `… on end` (completed view), `… on close` (flow disconnected),
    `keep-alive starts on a mid-session unlock` (locked context, running view → none; unlock → one). Existing
    tests that read the beep's frequency (`kindOf`) get 1175.
- [ ] **Step 2: Run** `npm test --prefix cards -- audio workout-flow-pings` → FAIL.
- [ ] **Step 3: Implement:** `beep: [{ frequency: 1175, offset: 0, length: 0.25 }]`, `VOLUME = 0.5`; the keep-alive as
  one module-level oscillator → gain node (fixed gain ≤ 0.001) → destination. In `WorkoutFlow`, call
  `startKeepAlive()` from `plan()` when `counting`, unlocked and `status === "running"`, else `stopKeepAlive()`; also
  `stopKeepAlive()` in `disconnectedCallback`. Update the comments on `TONES`.
- [ ] **Step 4: Run** the cards gate (`npm run lint`, `npm test`, `npm run build` in `cards`) → PASS.
- [ ] **Step 5: Commit** `feat(cards): longer, higher, louder countdown beeps and an audio keep-alive`.

### Task 3: The timer layout: no buttons, the ring button, the pill, the band

Model: opus · Review: yes

**Files:**
- Modify: `cards/src/flow/timer.ts` (render and styles), `cards/src/ring.ts` only if the overlay button needs a hook,
  `cards/src/workout-flow.ts` (the timer context: drop `onPrevious`, `onPause`, `onResume`, `onNext`), `cards/src/overlay.ts`
  (`totals.marks?: number[]`), `cards/src/i18n/en.json`, `cards/src/i18n/da.json`
- Test: `cards/test/workout-flow-timer.test.ts`
- Docs: `docs/decisions.md` (D73, spec §6), `docs/testing.md` (the workout-flow Chrome check: the ring tap pauses and
  resumes, the band)

**Interfaces:**
- Consumes: `totals.marks` (Task 1) as optional.
- Produces: the timer's top row keeps `renderPlayer(ctx)` as the place Task 4 adds the slider; `TimerContext` keeps
  `onRingTap`, `onMusicToggle`, `onMusicNext`.

Spec §2.3 and §2.4 hold the layout; the mockup shows it. Texts per spec §5.

- [ ] **Step 1: Write the failing tests** (roles and rendered text; a frozen clock):
  - `no transport buttons`: no button named Forrige, Næste, or a pause/resume button outside the ring.
  - `the ring button pauses and resumes`: a running view has a button named "Pause"; clicking it sends `pause`; a
    paused view's button is named "Fortsæt" and sends `resume`. The progressbar named after the phase word is still
    there, outside the button. The ring's caption reads "tryk for pause" while running.
  - `get ready's ring has no button`: the ready step has the progressbar and no ring button.
  - `the interval pill`: "Interval" and "3 / 5" show; no round pill ("Runde"). One person: "Station" n / N. In the
    cool-down: the cool-down pill's text, under the ring (the only pill).
  - `the band's times`: `time_trained` 663 and planned 1725 → "11:03" and "17:42" with "tilbage"; the progressbar's
    value text "17:42 tilbage af træningen"; the old "/ 28:45" text is gone.
  - `time left never below zero`: elapsed beyond planned → "0:00".
  - `gaps from marks`: `marks: [300, 600]` → two round gaps (render each gap as an element with an accessible-hidden
    marker the test can count by role `separator`, `aria-orientation="vertical"`); `no gaps without marks`.
  - `banners above the cards`: an unreachable view shows its note; `Tryk for lyd` shows when locked.
  - Remove the tests of the removed buttons; keep the skip-tone tests (they drive `next`/`previous` through views).
- [ ] **Step 2: Run** `npm test --prefix cards -- workout-flow-timer` → FAIL.
- [ ] **Step 3: Implement** in `timer.ts`: drop `.timer-controls`; the ring wrapped with a transparent `<button>`
  laid over it (accessible name `flow.pause` / `flow.resume`; the ring's progressbar a sibling, not a child);
  `renderCentre` / `renderCooldownCentre` render only the bottom pill, big (label normal, numbers large); `renderWhole`
  becomes the band (fill share as today, phase colour, gaps at `mark / planned`, trained time left, time left right,
  both in the primary text colour, `aria-valuetext` the time-left text); the banners in a row between the top row
  and the cards that takes no height when empty; one CSS grid for the screen (top row, banners, main, band); the top
  row loses `.elapsed` and keeps Skip cool-down and Slut on the right; portrait keeps its stacking. New keys per spec
  §5; drop `flow.previous`, `flow.next`, `flow.round_label` if unused (check with grep, including `ready.ts`).
- [ ] **Step 4: Run** the cards gate → PASS.
- [ ] **Step 5: Docs:** D73 in `decisions.md`; `testing.md`'s workout-flow check: tap the ring to pause and resume
  (replacing the play button), check the band's times and gaps.
- [ ] **Step 6: Commit** `feat(cards): the timer's time-left band, the ring as the pause control, no transport buttons`.

### Task 4: The music volume: integration and slider

Model: opus · Review: yes

**Files:**
- Modify: `custom_components/ha_fitness/music.py` (`music_state`, `async_command`), `custom_components/ha_fitness/websocket_api.py`
  (`MUSIC_ACTIONS`, the `ha_fitness/music` schema)
- Modify: `cards/src/overlay.ts` (`MusicState.volume?: number | null`), `cards/src/flow/timer.ts` (`renderPlayer`),
  `cards/src/workout-flow.ts` (the volume send, throttling, hold), `cards/src/i18n/en.json`, `da.json`
- Test: `tests/test_music_controller.py`, `tests/test_websocket.py`, `cards/test/workout-flow-timer.test.ts`
- Docs: `docs/architecture.md` (the music contract), `docs/testing.md` (the music steps: the slider; `Garage speaker`
  without `VOLUME_SET` shows none)

**Interfaces:**
- Produces (websocket): `{"type": "ha_fitness/music", "action": "volume", "level": <int 0–100>}`; the music state's
  `volume: int | None`.
- Consumes: Task 3's `renderPlayer`.

Spec §2.2 and §4.

- [ ] **Step 1: Write the failing integration tests:**
  - `music state carries the volume`: the fake speaker at 0.4 → `volume == 40`; a speaker without `VOLUME_SET` →
    `None`; a speaker with no `volume_level` → `None`. The state is re-sent when the speaker's volume changes.
  - `the volume action sets the level`: `action: "volume", level: 65` → `media_player.volume_set` with 0.65 on the
    session speaker; the program's music settings unchanged.
  - `invalid_format`: `volume` without `level`; `level` 101, -1, 50.5 and `true`; `level` with `action: "play"`.
  - `not_found` with no active session with music; `unavailable` without `VOLUME_SET` and when the call fails.
  - `the fade starts from the set level`: set 70, end the session → the fade's first step is below 0.70 from 0.70,
    and the last sets 0.70 back.
- [ ] **Step 2: Run** `uv run pytest tests/test_music_controller.py tests/test_websocket.py -v` → FAIL.
- [ ] **Step 3: Implement** the integration: `volume` in `music_state` (`round(volume_level * 100)`, None per spec);
  `MUSIC_ACTIONS` gains `volume`; the schema accepts `level` only with `volume` (a `vol.Any` of two schemas, or a
  validator), integer 0–100, booleans refused; `async_command(action, level=None)` calls `SERVICE_VOLUME_SET`, raising
  `MusicUnavailable` without `VOLUME_SET`.
- [ ] **Step 4: Run** the integration gate → PASS.
- [ ] **Step 5: Write the failing card tests:**
  - `no slider without volume`: a music state without `volume` (or null) → no slider named "Musikkens lydstyrke".
  - `the slider shows the volume`: `volume: 40` → a slider with value 40.
  - `disabled while waiting and unavailable`.
  - `sends throttled levels`: with fake timers, input 50, 55, 60 within 300 ms → one send at once and one after
    300 ms with the latest; release → one more send with the final value. Each send is `{type:"ha_fitness/music",
    action:"volume", level}`.
  - `a state while held doesn't move the thumb`; `follows the state after release`.
  - `a refused set shows nothing`.
- [ ] **Step 6: Run** `npm test --prefix cards -- workout-flow-timer` → FAIL.
- [ ] **Step 7: Implement** the slider in `renderPlayer` after next track: a speaker icon and a touch-friendly range
  input (0–100) named `Musikkens lydstyrke`; the player grows to hold it. The flow keeps `held` and a throttle timer;
  the send swallows refusals like `music()`.
- [ ] **Step 8: Run** the cards gate → PASS.
- [ ] **Step 9: Docs:** `architecture.md` (the `volume` field and action, its refusals); `testing.md` music steps.
- [ ] **Step 10: Commit** `feat: the music volume slider on the timer`.

### Task 5: Fast loop, Chrome check and the release notes text

Model: opus · Review: no

Run by the controller after the branch review, not an implementer.

- [ ] Run every gate in CLAUDE.md.
- [ ] Fast loop (`scripts/develop`, `scripts/seed`), Chrome check at 1368×912 in Danish per spec §8, screenshots in
  `screenshots/timer-band/`; listen to the beeps once.
- [ ] The PR (title `feat: …`), with the rulings; after the release, the house `fitness` issue with the spec's list.
