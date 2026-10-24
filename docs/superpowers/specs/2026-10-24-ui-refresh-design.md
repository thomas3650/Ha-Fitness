# UI refresh – design

- **Date:** 2026-10-24 · **Status:** approved by Thomas 2026-10-24
- **Why:** Thomas reviewed the built screens against the mockups (`docs/mockups/`) on 2026-10-24. He keeps the light
  colours, but wants the mockups' layout, with icons instead of text where the mockups use them. Every decision below is
  his, screen by screen, unless marked "Claude's call".
- **Builds on:** [step 4](2026-10-24-training-today-design.md) (the today card), [step 5](2026-10-24-the-workout-design.md)
  (the workout flow), [step 6](2026-10-24-stats-design.md) (stats). It replaces those specs' screen layouts where they
  differ. Their behaviour (timing, commands, rules) stays.
- **Comes before the first release to the house** (Thomas). Closes #29 and #36.
- **Needs an update on the real Home Assistant:** yes, both parts. No house configuration changes beyond step 6's.
- `api_version` stays 1: this only adds to the contract.

## 1. Rules for every screen

- **Light colours:** HA's theme variables, as today. The phase colours stay: work orange, switch and rest blue. The
  person colours stay: purple `#B18CFF`, teal `#3DD6C6`, then the primary colour.
- **Icons come from HA's frontend** (`ha-icon` with Material Design Icons), so no icon set is bundled. Every button that
  shows only an icon has an `aria-label` from the language files (hard rule 6), so it can be named and tested by role.
  - Icons: `mdi:play`, `mdi:pause`, `mdi:skip-previous`, `mdi:skip-next`, `mdi:arrow-left`, `mdi:lightning-bolt`
    (streak), `mdi:check` (complete), `mdi:debug-step-over` (Spring over). **Claude's call:** the exact icons.
- **Touch targets** stay at least 48 px. The round pause/play button is the largest control.
- **Mockup texts are English examples.** Every text comes from the language files, in Danish and English.

## 2. The screens

### 2.1 The today card (Thomas: a mix of the today card and the `StatusCard` mockup)

- **The top line:** "TRÆNING" on the left. On the right, a **streak badge**: `mdi:lightning-bolt`, then each person's
  initial and streak with their colour dot, in people order ("● T 6 · ● E 4"), so no number relies on colour alone
  (two letters when two people share an initial). Its
  accessible name spells it out ("Streak: Thomas 6, Elin 4"). It is hidden before counting starts and while the stats
  are unavailable.
- **The middle:** a **week ring** on the left: "2/4" with "denne uge" under it, filled by done / planned (§3.1); hidden
  when `planned` is 0 or the `today` message has no `week`. On the right: the program name, the state line ("I dag" for
  a due day, "Forfalden · fredag" for a late day: *Forfalden* stays the word for late, `domain-language.md`), and
  "5 øvelser · 29 min".
- **The bottom, under the text:** a big **▶ Start**, and **Spring over** beside it, smaller, with its icon. Spring over
  keeps step 4's two taps: it turns into "Spring over? Ja / Nej", with Nej where Spring over was (Thomas: no skip
  reasons).
- **Several open days** each get the middle and bottom rows; the top line and the ring are shown once.
- **During a session** (step 5 §5.1 still holds): the top line and the ring stay; every day's rows are replaced by one
  row, "Træning i gang · <program>" and **▶ Fortsæt**. An extra session with no open day shows the same.
- The streak badge and the ring come from the stats (step 6) and the `today` message (§3.1). The card subscribes to
  both. Its size in a sections view is settled in the Chrome check, including a 500 px column (#29).

### 2.2 Details (Thomas: the `WorkoutDetails` mockup)

- **The top:** a back button (`mdi:arrow-left`, label "Tilbage") and the program name.
- **The left panel:** "N øvelser · alle skifter én station hvert interval", then a grid of **big exercise pictures**
  (the still thumbnails, not the GIFs, so a long program doesn't animate a dozen GIFs at once), each with "n · name".
- **The right panel:**
  - "Hvem træner?" with the people chips (step 5's rules);
  - Runder;
  - Arbejde / skift, in the phase colours ("45 s / 15 s");
  - "Pause mellem runder" with its seconds, when the round rest is above 0;
  - **"Du skal bruge"**: equipment chips, the program's distinct equipment (§3.2), hidden when none;
  - the total time, large ("44:00"), from the program's `total_seconds` (relayed by `ha_fitness/programs`);
  - a big **▶ Start**;
  - "Ret programmet ved at spørge Claude" in small text.
- The music row comes with step 7.

### 2.3 Get ready (Thomas: the `GetReady` mockup)

- **The top:** a summary pill ("Sample · 2 personer · 5 runder · 29 min", the minutes from the view's `totals.planned`)
  and **Annullér** on the right.
- **The left:** the countdown inside a ring: "GØR KLAR" above the number.
- **The right:** "GÅ TIL DIN STARTSTATION" and one **card per person**: a numbered badge in their colour, the exercise
  picture, "name · station n", and the exercise name large.
- **The bottom:** **Start nu**.
- **No Pause button here** (Thomas). Annullér keeps step 5's rule: it ends the session and closes once `end` went through.
- **A paused countdown** (after an add-on stop or update, D40) shows a "PAUSET" pill, and **Fortsæt** in place of
  Start nu. **Claude's call.** The countdown ring isn't tappable.
- The numbered badge is the participant's place among the participants (1, 2); the colour follows the people order, as
  in step 5. The same holds on the timer.

### 2.4 The timer, one person (Thomas: the `Timer` mockup)

- **The top row:** pills "Runde 3/5" and "Station 4/8" on the left, where the station number is `phase.interval`, also
  during a switch; "18:40 / 44:00" and **Slut** on the right. Slut keeps its confirm ("Afslut træningen? Ja / Nej").
- **The left:** the big picture, and the exercise name.
- **The middle:** the big ring with the phase word ("ARBEJD"), the seconds, and "sekunder tilbage".
- **The right:** a **"NÆSTE" card** with the picture, the name, and a subtitle from `next_phase` ("efter 15 s skift",
  "efter 60 s pause"; with a 0 s switch the next phase is work, so it reads "derefter"). None on the last interval, and
  the layout stays centred then (#36).
- **The bottom:** icon buttons ⏮ (`Forrige`), a big round ⏸ (`Pause`), ⏭ (`Næste`); then a **progress bar** across the
  screen: elapsed time over the planned total, a `progressbar` named "Hele træningen", apart from the ring's
  `progressbar` (named after the phase, as in step 5).
- The music mini-player in the top row comes with step 7.

### 2.5 Switch and paused (Thomas: the `TimerRest` mockup)

- **During a switch:** "GÅ TIL NÆSTE STATION" above the picture of the next station; the right card says "DEREFTER", with
  the exercise after that.
- **While paused:**
  - a "PAUSET" pill in the top row ("PAUSE" is already the rest phase's word);
  - the ring keeps the phase word ("SKIFT 9") and says "tryk på ringen for at fortsætte";
  - the round button shows ▶ (`Fortsæt`).
- **Tapping the ring pauses and resumes** while running or paused (Thomas). It is a pointer shortcut only: the ring
  keeps its `progressbar` role, stays out of the tab order and has no button role, and the round button stays the
  accessible control. Tests tap the ring and check the command sent.

### 2.6 The timer, two people (Thomas: the `TimerDuo` mockup)

- One card per person: a **coloured bar along the top**, a **numbered badge** in their colour with the name, "Station n"
  on the right, the big picture, the **exercise name large**, and "Næste: station 4 · Burpee" small.
- The ring in the middle, and the same buttons and progress bar as §2.4. The top row's second pill is "Interval y/S"
  instead of "Station", since each person is at a different station.
- **Portrait** keeps step 5's layout fix: the two cards side by side, with the ring below.

### 2.7 Complete and ended (Thomas: the `Complete` mockup)

- A big green `mdi:check`, "Træning gennemført", then the program and the date: the local date of `started_at`, as
  "torsdag 22. oktober", with weekday and month names from the language files (D38, hard rule 6).
- **Four tiles:** Tid; Runder ("5 / 5"); Trænede (the names); Streak (each participant's name and streak with their
  colour dot, from the stats; it may update a moment after the session view, since `stats` follows the finish).
- **"Hvordan føltes det?"**: three buttons, For let / Tilpas / For hårdt, a group with `aria-pressed` on the chosen
  one, marked by more than colour (a check icon). A tap sends the command (§3.3), and the mark follows the session
  view's `feeling`. A second tap on another changes it. A failed tap shows a short error under the buttons, one text per
  code. The 60 s auto-close starts again on each tap.
- **Færdig** closes, as Luk does today.
- **Ended and counted** (ended after a round): the check and the streak tile, with the title "Afsluttet efter 2 af 5
  runder"; no feeling buttons (§3.3).
- **Ended, not counted:** no check, streak tile or feeling buttons: "Træningen blev afsluttet", Tid, Runder, Trænede,
  Færdig. **Claude's call.**

## 3. Data (add-on)

### 3.1 The week ring

- The `today` message (and `GET /today`) gets `week: {done, planned}` for the current local week, Monday to Sunday.
- **planned** is the number of training days dated this week: the existing days (any status) plus the days the active
  programs will still create from tomorrow to Sunday.
- **done** is the number of this week's days with status `done`.
- It changes with the today view's other changes, so `today` is published when it changes (the existing rule).
- **Claude's call:** household numbers, not per person. The week ring answers "did we train as planned?".
- **Named in `domain-language.md`:**
  - a late day from last week trained on Monday counts as done in last week, so the ring doesn't move;
  - after a fresh install, or a program created or switched on mid-week, `planned` counts only from today;
  - skipped and missed days count in `planned`, never in `done`;
  - extra sessions don't count;
  - the ring starts over at the Sunday→Monday midnight push.

### 3.2 Equipment

- `ProgramOut` (REST and MCP) gets `equipment: list[str]`, the distinct equipment of its stations, library and custom
  exercises alike, in station order, without "body weight" (matched case-insensitively) and without nulls. It is empty
  when there is none.
- `ha_fitness/programs` passes it to the cards, as `[]` when the add-on doesn't send it, so an older add-on keeps the
  list working.
- **The cards translate the known values** through the language files (`dumbbell` → "håndvægt", `band` → "elastik",
  `kettlebell` → "kettlebell", `resistance band` → "modstandselastik") and show any other value as stored, as exercise
  names are. **Claude's call.**

### 3.3 How it felt

- The current session view, when it is a **completed** session within its 5-minute finished view, takes a `feeling`:
  `too_easy`, `just_right` or `too_hard`, through `POST /api/v1/session/feeling` with `{"feeling": …}`.
  - It is its own route, declared before `POST /session/{command}`.
  - It answers 409 `conflict` when the current view is anything else: none, running, paused, or ended (counted or not).
  - An unknown value gives 422 `invalid` in the session routes' `{code, message}` shape, checked in the service.
  - A later call changes it.
  - A write raises `revision` and publishes a `session` message, so the card and the integration's stored view follow.
  - It adds a change-log row, like the other writes.
- Migration 0005 adds a nullable `feeling` to sessions. The session view, `GET /sessions` and the MCP `list_sessions`
  show it. The `list_sessions` and `get_program` tool descriptions mention `feeling` and `equipment`, since Claude
  reads them.
- The integration passes it through `ha_fitness/session/command` (`command: "feeling"`, `feeling: …`), mapping the
  codes like the other commands.
- **Claude's call:** only completed sessions are rated.

## 4. What ships, in two PRs

Each PR releases one component (D29).

1. **`feat: week, equipment and feeling in the add-on`** (`addon/`, `docs/`): §3.1–§3.3.
2. **`feat: the refreshed screens`** (`custom_components/`, `cards/`, `tests/`, `docs/`): the relay and command additions,
   and all of §2.

Merge order 1 → 2. Installing PR 1 first is safe: the step 6 integration passes unknown fields through or drops them.
PR 2 against an older add-on: the week ring and equipment are hidden when their fields are missing, and the feeling
buttons are hidden when the session view has no `feeling` key. **Claude's call:** no `addon_too_old` for this, since
nothing breaks.

## 5. Tests

All through public interfaces (hard rule 5), with a frozen clock where time matters.

- **Add-on:**
  - `week` across a week: past days by status, today's, and the future days of the active programs; a program switched
    off; Monday and Sunday edges.
  - `equipment`: distinct, in order, without body weight, empty.
  - `feeling`: set, changed, 409 without a completed session in its window and for an ended one, 422 for an unknown
    value in the `{code, message}` shape; a write raises `revision` and pushes `session`, and adds a change-log row;
    shown in the view and in `list_sessions` over REST and MCP; migration 0005 keeps step 6 data.
- **Integration:** the `feeling` command; `equipment` and `total_seconds` in `ha_fitness/programs`, and `[]` from an
  add-on without `equipment`.
- **Cards**, by role and text, in both languages:
  - the today card's ring, streak badge, several open days, the session state, and Spring over's two taps;
  - details' grid, chips, equipment and total;
  - get ready's cards, with no Pause, and a paused countdown's PAUSET pill and Fortsæt;
  - the timer's pills, the NÆSTE card, the icon buttons by label, the progress bar's value, and the ring as a pause
    button;
  - two people's cards;
  - complete's tiles, the date in both languages, and the feeling buttons (the command sent, `aria-pressed` from the
    view, an error per code); ended counted and not counted;
  - the compatibility of §4: no ring without `week`, no feeling buttons without a `feeling` key, no equipment chips
    without `equipment`.
- **Chrome check:** every screen at 1368×912 and 800×1280, against the mockups, with screenshots for Thomas.

## 6. Docs and decisions

- **PR 1:** `architecture.md` (`week`, `equipment`, `feeling` and its route); `domain-language.md` (the week ring and its
  named cases, feeling); **D50**: how a workout felt is stored with the session, for Claude.
- **PR 2:** `architecture.md` (the relay additions, the screens' structure); `docs/mockups/README.md` (the built screens
  follow the mockups' layout in light colours); `testing.md` (the Chrome check per screen); **D51**: the screens follow
  the mockups' layout with HA's light theme and HA's icons (Thomas, 2026-10-24).
- **The house** (the `fitness` issue after the releases): install the add-on first, so the ring, the chips and the
  feeling buttons show at once.

## 7. Left to the plan

- The component split in the cards (the workout flow is large; split it by step if that helps).
- How the icon buttons are tested by their labels.
