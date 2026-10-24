# Step 5: The workout – design

- **Date:** 2026-10-24 · **Status:** approved by Claude 2026-10-24 (full-reviewer Ready after 3 rounds), on Thomas's
  delegation for the night of 2026-10-23; Thomas reviews it on 2026-10-24
- **Implements:** [design spec](2026-10-23-ha-fitness-design.md) §10 step 5, with §3.1 (how a session runs), §3.3
  (done, ended early, extra sessions, counting from), §3.4 (the workout flow, the screen during a workout) and §3.8.
  Builds on [step 3](2026-10-24-programs-through-chat-design.md) and [step 4](2026-10-24-training-today-design.md).
  Issue #5. Also closes #20.
- **Needs an update on the real Home Assistant:** **yes, both parts**, plus house work (§8).
- `api_version` stays 1: this step only adds to the contract.
- "Claude's call" marks choices made without Thomas; he may overrule them.

## 1. Goal

On a training day they tap **Start** on "Træning i dag". A full-screen flow opens on the tablet:

1. **Details:** they pick who trains, then tap **Start**.
2. **Get ready:** a countdown.
3. **Timer:** it runs the circuit for one or two people, showing each person's current and next exercise. It pings in
   the last 5 seconds of every phase, and has pause, back, skip and end.
4. **Done.**

Finishing marks the training day done. The workout tab can also start any active program as an extra session.

## 2. What ships, in three PRs

Each PR releases one component (D29).

1. **`feat: sessions`.** It touches `addon/`, `docs/` and `scripts/`.
   - The session engine, one session at a time.
   - The REST API, the push message and the MCP read tools.
   - Closing training days as done, and the "counting from" date.
   - The rules for restarts and pauses.
   - The snapshot on shutdown (#20).
   - `scripts/seed --short`.
2. **`feat: session entities and media proxy`.** It touches `custom_components/`, `tests/` and `docs/`.
   - `binary_sensor.ha_fitness_session_running`.
   - The services `start_session` and `end_session`.
   - The events.
   - The websocket commands.
   - The authenticated media proxy.
3. **`feat: the workout flow`.** It touches `cards/` and `docs/`.
   - Start and Fortsæt on the today card.
   - `ha-fitness-workout-card`.
   - The full-screen flow.
   - The pings.

The integration's release PR waits until PR 3 is merged, so the services and the cards reach the house together. The
add-on is installed first, then the integration (§8). Music comes in step 7, stats in step 6.

The design's `complete` service (design §3.8, and step 4 §4.4's "comes with step 5") is **dropped**. A day is done only
through a session in the app, and design §3.3 and §3.9 rule out a manual "done" (Claude's call).

## 3. Sessions (add-on)

### 3.1 The plan of a session

When a session starts, the add-on freezes its **plan**. A later program edit, or a person's removal, changes nothing in a
running session or in history. The plan holds:

- the program id and name;
- the stations: for each, the exercise id and name;
- `rounds`, `work_seconds`, `switch_seconds`, `round_rest_seconds` and `countdown_seconds`;
- the participants: 1 or 2 people, each with id and **name**, in people order.

The plan's **phases** are computed from those values:

```
countdown                       (countdown_seconds; left out when 0)
for round 1..R:
  for interval 1..S:
    work                        (work_seconds)
    switch                      (switch_seconds; left out when 0, and after the last interval of the last round)
  rest                          (round_rest_seconds; after rounds 1..R-1 only; left out when 0)
```

**No switch after the very last interval** (Claude's call; a new decision). The session ends when the last work phase ends.
The program's `total_seconds` (step 3, design §3.1) stays the planned length shown before a workout, r seconds longer
than the timer.

**Stations** (design §3.1). In interval i of a round (0-based), participant p (0-based) works at station
`(p + i) mod S`.

`current` per phase kind:

| Phase | `current` |
| --- | --- |
| countdown | the first station `p` |
| work at station s | s |
| switch after s | `s + 1`, the station moved to |
| rest after a round | `p`, the first station of the next round |

`next` is the station of the work phase that follows the work phase `current` names, or **null** when there is none
(the last work phase of the session, and every phase leading only to it). All station numbers are `mod S`.

Each phase carries `round` (1..R) and `interval` (1..S). A rest carries the round just finished, with `interval = S`.

### 3.2 State and the tick

A session is stored with:

- `id`;
- the frozen `plan`;
- `training_day_id`, or null for an extra session;
- `status`: `running`, `paused`, `completed` or `ended`;
- `counted` (bool);
- `phase_index`;
- `phase_started_at`: UTC, the time the current phase would have started without later pauses;
- `paused_at`, or null;
- `paused_seconds`: only pauses after `started_at` count; a pause during the countdown just delays the start;
- `last_tick_at`, written every 5 s and at every phase change;
- `started_at`: the start of the first **work** phase. The countdown isn't training time.
- `ended_at`;
- `rounds_completed`;
- `revision`: an integer that goes up with every change.

**One session at a time.** Only one session can be `running` or `paused` at once (Claude's call: there is one tablet).
Starting another gives a 409.

**The tick.**

- It runs under step 4's lock and clock, for `running` sessions only. Every command and every read of the session runs a
  tick first, so a command just after a deadline acts on the right phase.
- It wakes at the current phase's deadline, and at least every second.
- When `now ≥ phase_started_at + duration`, it moves on. Each new `phase_started_at` is the previous one plus its
  duration, so no time drifts. Several phases can pass in one tick, for example after the loop was blocked.
- It records `last_tick_at`.
- One tick that moves on publishes **one** `session` message and **one** `phase_changed` event, for the phase it ends on.
- Passing the last work phase completes the session (§3.4).

**After a restart** (Claude's call):

- **Shutdown.** The lifespan pauses a running session (`paused_at = now`) before it writes the shutdown snapshot.
- **Start.** If a session is still `running` (after a crash), it is paused with `paused_at = last_tick_at`. The time the
  add-on was down then counts as a pause.

So a restart never skips phases or completes a workout that nobody did.

**Pause limit** (Claude's call): the loop also checks paused sessions; a session that stays paused for **30 minutes** is
ended (after a crash restart that was down longer than that, at once) (§3.4's counting rules apply).
That way a forgotten session can't keep the tablet awake for ever, block house updates, or block the next start.

### 3.3 Commands

| Command | Allowed when | Effect |
| --- | --- | --- |
| `start(program_id, participants, training_day_id?)` | no session is running or paused | Freezes the plan. Starts at phase 0 (the countdown, or the first work phase). Errors: §3.5. |
| `pause` | running | Sets `paused_at`. |
| `resume` | paused | Adds the pause to `paused_seconds` and moves `phase_started_at` on by the same amount. |
| `next` | running or paused | Jumps to the start of the next **work** phase. During the countdown that is the first work phase ("Start nu"). On the last work phase it completes the session. |
| `previous` | running or paused | Goes to the start of the current work phase. If less than 3 s of it has run, or during a switch or rest, it goes to the start of the previous work phase instead (Claude's call, like a music player's back button). During the countdown, or on the first work phase, it restarts that phase. |
| `end` | running or paused | Ends early (§3.4). An open pause is closed first, so `ended_at − paused_seconds` is right. |

- `next` and `previous` while paused keep the session paused, with the new phase at its full length.
- `next` and `previous` publish a `session` message and a `phase_changed` event.
- A command that isn't allowed in the current status gives a 409 `conflict`.
- The change log records `session.started`, `session.completed` and `session.ended`, with the client of the command.
  A completion by the tick or by the pause limit is logged with the client `addon`. Pause, resume, next and previous
  aren't logged: they change no stored data that matters later.

### 3.4 Finishing

- **Completed:** the tick passes the last work phase, or `next` is used on it. `status = completed`,
  `rounds_completed = R`, `counted = true`.
- **Ended:** `end`, or the pause limit. `status = ended`. `rounds_completed` is the number of rounds whose last work
  phase is behind the current position. `counted` is true when that is at least 1 (design §3.3: "done if at least one
  full round was completed").
- **Time trained** is `ended_at − started_at − paused_seconds`, or 0 if the countdown never finished.
- **A counted session with a training day** closes that day as `done` and fires the `done` event. It is **done late**
  when the day's date is before the local date of `started_at`. A session that crosses midnight is therefore not late.
- **A training day under a session:**
  - Reconcile leaves it open: rule 2 of step 4 §3.3 skips a day while a session for it is running or paused.
  - If the session ends without counting, the next reconcile treats the day like any other open day.
  - Switching off or deleting the program of a running or paused session gives a 409 with the message "A session for
    this program is running", so Claude reads why. This holds for extra sessions too. A `PUT` with `active: false`
    counts as switching off.
  - Skipping a day that has a running or paused session gives a 409 (REST and MCP).

  This replaces the "set to done anyway" idea: no `missed` then `done` pair ever happens.
- **Counting from** (design §3.3): the first counted session sets `counting_from` once, to the local date of
  `ended_at`. Step 6 uses it.
- **Participants:** every finished session stores one row per participant: the person's id and **name**, and their order.
  There is no foreign key, so removing a person later keeps the history (D33 keeps the ids unique).

### 3.5 The API and the push channel

REST, in `api_router`, above the catch-all:

| Method and path | Does |
| --- | --- |
| `GET /api/v1/session` | The running or paused session. Otherwise the last finished one if it finished less than 5 minutes ago, so a card that reconnects right after the finish still gets the done view. Otherwise `null`. |
| `POST /api/v1/session` | Start: `{"program_id", "participants": [person ids], "training_day_id"?}` → the session (201). |
| `POST /api/v1/session/{command}` | `pause`, `resume`, `next`, `previous`, `end` → the session. |
| `GET /api/v1/sessions?limit=` | `{"counting_from": date or null, "sessions": [finished views, newest first]}`; `limit` default 20, 1–100. A finished view's participants come from the stored participant rows; its `phase`, `next_phase` and `stations` are null. |

**Start validation.**

| Status | Code | When |
| --- | --- | --- |
| 404 | `not_found` | The program, a person or the training day doesn't exist. |
| 409 | `conflict` | A session is already running or paused; the program isn't active; the training day isn't open, or belongs to another program. |
| 422 | `invalid` | `participants` is empty, has more than 2, has duplicates, or has more than the program's station count. |

The session routes' `detail` is `{"code", "message"}` (steps 3–4 routes keep their current error shapes). The
participant rules are checked by the service, so a bad list is a 422 with that shape, not FastAPI's field list. The
other commands answer 409 `conflict` when they aren't allowed.

**The session view.**

- `id`, `revision`, `status` and `counted`;
- `program_name` and `training_day_id`;
- `participants`: `[{id, name}]`;
- `phase`: `{index, kind: countdown|work|switch|rest, round, interval, duration, ends_at, remaining}`.
  - `ends_at` is UTC ISO with milliseconds. It is null while paused or finished.
  - `remaining` is the seconds left, set while paused.
- `next_phase`: `{kind, duration}`, or null;
- `stations`: one per participant, `{current: {number, exercise_id, name}, next: {…} | null}`, per §3.1's table;
- `totals`: `{planned, rounds}`. `planned` is the sum of all work, switch and rest phase lengths; the countdown is left
  out.
- `started_at`, `ended_at`, `rounds_completed`;
- `time_trained`: the active seconds so far at the moment of the view while running or paused, the final value when
  finished;
- `server_time`: the add-on's UTC ISO with milliseconds.

**The websocket** (step 4 §3.6) gains:

- `{"type": "session", "data": <view or null>}`.
  - It is sent on connect, after `today`, and after every change: phase, command, finish, pause limit.
  - Once a session finishes, its finished view is sent once.
  - `null` follows when the finished view's 5 minutes are over; the add-on's loop sends it. A new session sends its own
    view.
- Events, each `{"type": "event", "event": …, "session": {id, program_name, training_day_id, phase?, counted?}}`:
  - `session_started`;
  - `session_completed`;
  - `session_ended`, with `counted`;
  - `phase_changed`.
- `{"type": "event", "event": "done", "training_day": {…}}`.

**MCP** gets two read tools:

- `get_session` (the current or recent one);
- `list_sessions` (finished ones).

There are no MCP tools that start or steer a workout. The workout runs on the tablet.

### 3.6 Snapshot on shutdown (#20)

The lifespan's shutdown writes the snapshot (step 3 §10), after pausing a running session. A backup of a stopped add-on
then holds the data as of the shutdown; only a crash leaves the last backup's snapshot. Its decision refers to D31.

## 4. The integration

- **`binary_sensor.ha_fitness_session_running`** ("Session running" / "Træning i gang") is:
  - `on` while a session is running or paused;
  - `off` when there is none;
  - `unavailable` while the add-on can't be reached, and until the first `session` message after a connect. That
    matches step 4's entities, and the house automation never sees a false off.

  The attributes `program` and `participants` are unrecorded.
- **Services:**
  - `ha_fitness.start_session`: `program_id`, `participants` (person ids), optional `training_day_id`;
  - `ha_fitness.end_session`.

  The translated errors are `not_found`, `conflict`, `invalid` and `unavailable`.
- **Events:**
  - `ha_fitness_session_started`;
  - `ha_fitness_session_completed`;
  - `ha_fitness_session_ended`;
  - `ha_fitness_phase_changed`;
  - `ha_fitness_training_day_done`.
- **Websocket commands** (a logged-in user, not necessarily an admin; the tablet's user isn't one):
  - **`ha_fitness/session/subscribe`** sends `{"available": bool, "session": <view or null>}`.
    - It sends at once and after each change.
    - The integration compares views without `server_time` to decide whether something changed, then replaces
      `server_time` with its own current time **on every send**. While the session is running and past the countdown it
      also advances `time_trained` by the same difference (HA's now minus the add-on's `server_time`), so the header's
      elapsed time stays right for a card that subscribes mid-phase.
    - While the add-on is unreachable it sends `available: false` with the **last known view** (not null), so the card
      can keep counting down. HA and the add-on share the
      host's clock, so a card that subscribes in the middle of a phase still gets a fresh offset.
  - **`ha_fitness/session/command`**: `command` (`start`, `pause`, `resume`, `next`, `previous`, `end`) and the start
    arguments. It returns the view, or the error codes `not_found`, `conflict`, `invalid` and `unavailable`.
  - **`ha_fitness/programs`**: the active programs, each `{id, name, rounds, work_seconds, switch_seconds,
    round_rest_seconds, countdown_seconds, total_minutes, stations: [{exercise_id, name}]}`, built from the add-on's
    `GET /api/v1/programs`.
  - **`ha_fitness/people`**: `[{id, name}]` from the add-on's `GET /api/v1/people`.
- **An older add-on.** On each connect, after `hello`, the integration probes `GET /api/v1/session`. If it gives 404 while
  `/health` answers, the add-on predates sessions. The
  integration raises the `addon_too_old` repair issue (step 4 §4.2, D36), and the subscription stays at
  `available: false`.
- **Media proxy** at `GET /api/ha_fitness/media/{exercise_id}/{kind}`:
  - It **requires authentication**.
  - It accepts `exercise_id` only in the library's form (four digits) or the custom form (`custom-<n>`), and `kind`
    only as `gif` or `thumbnail`. Anything else gives 404, never a relay to another path.
  - It relays the add-on's file with `Cache-Control: private, max-age=86400`.
  - A 404 stays 404. An unreachable add-on gives 503.
- **`ha_fitness.skip`** refuses a day that has a running session; the add-on gives 409, shown as `not_open`.

## 5. The cards

### 5.1 One overlay for the whole page

- The flow lives in **one overlay per page**, a `<dialog>` opened with `showModal()` and appended to `document.body`.
  - The browser's top layer puts it above HA's header and any card, whatever stacking contexts or transforms the cards
    sit in.
  - It inherits HA's theme variables from `html`.
  - While it is open, the page behind it doesn't scroll.
  - Escape and backdrop taps do nothing. Only the flow's own buttons close it (Luk also appears after 10 s unreachable,
    §5.3).
- A module-level controller owns the overlay, with its own session subscription and its own `hass` reference (the latest
  one any card handed it). Cards ask it to open or close; they don't contain it. The overlay outlives
  the card that opened it: when the today card hides because the day closed, the done screen stays.
- **The today card:**
  - It gains **Start** next to Spring over, the same size.
  - While a session runs or is paused, its rows are replaced by "Træning i gang · <program>" and **Fortsæt**, which
    reopens the overlay at the timer.
  - The card **stays visible while a session is active** (running or paused), even with nothing open, for example
    during an extra session. A finished view kept for 5 minutes is not active.
- **`ha-fitness-workout-card`**, for the workout tab, a panel view:
  - It shows the active programs, each with its line and **Start**, which opens the overlay. A start from here is an
    extra session (design §3.3).
  - While a session exists it shows "Træning i gang" and Fortsæt.
  - It has no flow of its own, so a view change (the screensaver) can't tear down a running flow; the overlay is page-level.
- When the page is reloaded while a session runs, nothing opens by itself. Fortsæt on either card opens the overlay.

### 5.2 The flow

1. **Details.**
   - It shows:
     - the program name, "ca. N min" and the rounds;
     - the work, switch and rest seconds;
     - the stations in order, with thumbnails and names.
   - **Who's training:** a chip per person. The colour follows the person in people order: the first person is purple
     `#B18CFF`, the second teal `#3DD6C6` (design §3.4). The participant order is people order.
     - With 2 people and at least 2 stations, both are preselected. With 1 station, only the first person is.
     - 1–2 can be selected, never more than the station count.
   - With no people, it says "Ingen personer – bed Claude oprette dem", and Start is disabled.
   - **Start** (96 px) sends `start`. It passes `training_day_id` when the flow was opened from the today card's row.
     **Tilbage** closes the overlay.
   - **Idle guard** (Claude's call): with no tap for **60 s** the details step closes the overlay. The house confirms its
     dim and screensaver times are longer (the `fitness` issue); the top layer sits above the screensaver, so
     this guard is the protection. A wake tap after the
     screen dims can then never land on Start (design §1).
   - A failed start shows a text from the card's language files and stays on the details step: `conflict` with a
     session known → "already running"; other `conflict` → "can't start now" (day closed or program off); `not_found`,
     `invalid` and `unavailable` each have their own text.
2. **Get ready.**
   - The countdown, from the session, shows who starts where: "Thomas · station 1 · Push-up".
   - **Start nu** sends `next`. **Annullér** sends `end`, which gives an uncounted ended session, and closes the overlay.
   - Pause works here too.
   - With a countdown of 0 this step is skipped.
3. **Timer.**
   - **The ring.**
     - It empties as the phase runs: orange `#FF8A3D` for work, blue `#4DA8FF` for switch and rest.
     - It is exposed as `role="progressbar"` with its value.
     - In the middle: the seconds left, rounded **up**, so 1 shows during the last second. Over them the phase word
       ("ARBEJD", "SKIFT", "PAUSE"), under them the next phase ("så 15 s skift").
   - **Header:**
     - "Runde x/R" and "Interval y/S";
     - the elapsed time against `totals.planned`: `time_trained` from the view, plus the time since `server_time` while
      running and past the countdown;
     - **Slut**, which asks once ("Afslut træningen?" Ja/Nej) with step 4 §6's wake-tap guards.
   - **One participant** (mockup `Timer`): the current station big, with GIF and name; "Næste" beside it, with
     thumbnail and name. During a switch the big one is the station being moved to (mockup `TimerRest`).
   - **Two participants** (mockup `TimerDuo`): a panel per person with the person's colour as a border or badge. Each
     panel shows the name, station number, GIF and exercise name, and "Næste: station n · name". The ring is in the
     middle.
   - **Controls:**
     - pause/resume, big; tapping the ring also pauses;
     - previous and skip.
   - There is no other way out than Slut, except Luk after 10 s unreachable (§5.3).
   - **Paused:** the ring stops and shows "PAUSE", and the play button resumes.
4. **Done.**
   - **Counted:** "Godt gået!", the time trained, the rounds (x/R), and who trained.
   - **Not counted:** "Træningen blev afsluttet", with no counting.
   - **Luk** closes the overlay. It also closes by itself after 60 s.

**Theme and size:**
- Surfaces and text use HA's theme variables. The fixed colours are used only for the ring, borders and badges. On the
  light theme they are too pale for text, so all text uses theme colours, and no meaning rests on colour alone.
- It is sized for 1368×912 and readable at 1–2 m. Targets are at least 48 px; the main buttons are 96 px. No hover.

**Language:** every text comes from the cards' language files. Exercise and program names come from the data.

**Images:**
- They load through the media proxy with `hass.fetchWithAuth`.
- A page-wide cache keeps one object URL per exercise and kind.
- A missing image shows a neutral placeholder.

### 5.3 Timing on the tablet

- The card counts down locally (design §3.4) from `phase.ends_at`. It corrects by `server_time − local time`, computed
  on every message, so the subscription's fresh stamp keeps the offset right.
- It redraws at least 4 times a second; the ring moves smoothly.
- It applies a message only if its `revision` is higher than the last applied one for that session. Command results and
  pushes can arrive in either order.
- At local zero it shows the next phase's word and plays its change tone right away, from `next_phase`. The message that
  follows confirms or corrects it.
- While unreachable (`available: false`), the timer keeps counting the current phase down locally and shows "HA Fitness
  kan ikke nås". At zero it holds; the add-on keeps running the session, and the next message after the connection is
  back corrects everything. After 10 s unreachable, a **Luk** button appears, so a touch-only kiosk is never trapped
  behind the modal; Fortsæt reopens the overlay later.

### 5.4 Pings (design §3.4)

- **The sounds** come from the Web Audio API, as short sine tones; there are no sound files.
  - One short beep at 5, 4, 3, 2 and 1 s left of every phase (Thomas: pings in the last 5 seconds). A phase shorter than
    5 s gets only its own seconds. No beep falls in the first 0.3 s of a phase, where it would clash with the change
    tone.
  - A longer, higher tone when work starts.
  - A lower tone when a switch or rest starts.
  - A three-tone chime when the session completes.
- **Scheduling.** Beeps are scheduled ahead from the local countdown. On every pause, resume, next, previous or newer
  revision, the scheduled ones are cancelled and scheduled again.
- **Unlocking audio.**
  - One `AudioContext` is shared by the page (module level).
  - It is created, or resumed, **synchronously** in the tap handlers of Start and Fortsæt, before anything awaits. The
    browser only allows audio after a gesture.
  - If it is still suspended (for example after a reload without a tap), the timer shows a small "Tryk for lyd" button.
- The pings come from the tablet's browser only (design §3.4).

## 6. Tests

**Add-on** (frozen clock, through REST, ws and MCP):

- **The plan:**
  - phases for edge values: countdown 0, switch 0, rest 0, 1 round, 1 station;
  - `current` and `next` for each phase kind (§3.1's table), for 1 and 2 participants.
- **The tick:**
  - it waking at a deadline;
  - several phases passing at once, with no drift and one event.
- **Commands:**
  - pause and resume, and how `ends_at` moves;
  - `next` and `previous` at each phase kind, while running and while paused, including the 3 s rule and the countdown;
  - `end` while paused, so time trained has no open pause.
- **Finishing:**
  - an end with 0 rounds: not counted, and the day stays open;
  - an end with 1 round: counted, and the day is done;
  - completed;
  - done late;
  - a session across midnight is not late;
  - reconcile skips the in-session day;
  - deactivate or delete during a session gives 409;
  - an extra session closes no day.
- **Start validation:** 404, 409 and 422.
- **One session at a time.**
- **Restarts and the pause limit:**
  - shutdown pauses;
  - a crash restart pauses at `last_tick_at` without skipping phases;
  - the 30-minute pause limit ends the session.
- **History:**
  - `counting_from` is set once;
  - participant rows keep the name after the person is removed.
- **The revision** goes up.
- **The API:**
  - `GET /session` keeps the finished view for 5 minutes;
  - the push messages and events.
- **The snapshot on shutdown** holds a program created just before.
- **The MCP tools.**

**Integration:**

- the sensor: unavailable before the first message, then on and off, then unavailable when disconnected;
- the services and their errors;
- the events;
- the subscription's `available` flag and the fresh `server_time` it sends;
- the commands relayed, with their errors;
- `addon_too_old` on a `/session` 404;
- the media proxy:
  - requires auth;
  - checks the id and kind patterns;
  - relays bytes;
  - gives 404 and 503;
- skip refuses a day in session.

**Cards** (Vitest with fake timers, a fake `hass` and a fake AudioContext):

- **Overlay:**
  - Start opens it, with nothing started;
  - it survives the today card hiding;
  - Fortsæt reopens it;
  - Escape does nothing.
- **Details:**
  - the chips: colours, preselection, 1–2, at most the station count, no people;
  - the 60 s idle guard;
  - Start sends the right participants and training day;
  - errors.
- **Get ready:** Start nu and Annullér.
- **Timer:**
  - text and ring from a view with a clock offset;
  - the seconds rounded up;
  - the change at local zero;
  - an older revision ignored;
  - pause and resume;
  - previous and next;
  - Slut's two taps;
  - the 1-person and 2-person layouts, including during a switch;
  - counting down locally while unreachable, holding at zero, and Luk after 10 s.
- **Done:** counted, and not counted.
- **The today card:**
  - it stays visible during an extra session;
  - Fortsæt.
- **The workout card:** the programs and Start.
- **Beeps:**
  - at 5, 4, 3, 2 and 1;
  - short phases;
  - none in the first 0.3 s;
  - cancelled and scheduled again after a pause;
  - the change tones.
- **Audio:**
  - unlocked synchronously in the tap;
  - "Tryk for lyd" after a reload.
- **Images** through `fetchWithAuth`, with the placeholder on 404.
- **Danish and English.**

**Chrome check** at 1368×912 (fast loop, the Danish user, a sections view with the header showing):

- the overlay above the header;
- details, get ready, the timer for 1 and 2 people in work and in switch, paused, and done;
- Fortsæt after a reload;
- the today card staying visible;
- a clean console;
- a real short run with `seed --short` (work 10 s, switch 0 s, 1 round, countdown 5 s), to hear the beeps line up with
  the numbers.

**Full loop:**

- a session from the today card;
- the sensor on and off;
- the GIFs through the proxy;
- **#20**: stop the add-on, run `ha backups new`, and the archive's snapshot holds the latest program.

## 7. Docs and decisions

The decisions are numbered next at merge; step 4 takes D34–D39 before them.

**PR 1** (add-on):
- `docs/architecture.md`: sessions and their protocol. Step 4's "due and late never mix" no longer always holds: a
  session across midnight into another training day keeps its late day open next to the new due day.
- `docs/domain-language.md`:
  - phase and plan;
  - done late;
  - ended early;
  - the interval's switch, now "except after the last";
  - counting from: the first **counted** session.
- `docs/testing.md`: `seed --short` and a short run. Kort's day for today closes any earlier late day, and makes
  `seed --late` refuse on that weekday.
- `addon/DOCS.md`: the snapshot is also written on stop.
- Decisions:
  - the session engine in the add-on, with frozen plans, deadlines, one session at a time, and the restart and
    pause-limit rules;
  - no switch after the last interval;
  - the in-session day is left open by reconcile, and programs are locked during a session;
  - the shutdown snapshot, referring to D31.
- `scripts/seed --short` makes a program "Kort" (2 body-weight stations, 1 round, work 10 s, switch 0 s, countdown 5 s),
  active with today's weekday only, and reopens its day for today through the dev route. So the short run starts from
  the today card, the whole real path. It is dev data only.

**PR 2** (integration):
- `docs/architecture.md`: the media proxy and the session relay.
- `docs/ha-notes.md`: authenticated images through `fetchWithAuth`.
- Decision: the authenticated media proxy.

**PR 3** (cards):
- `docs/testing.md`: the Chrome check of the flow.
- `docs/ha-notes.md`: `<dialog>.showModal()` escapes stacking contexts; audio needs a gesture.
- Decision: one page-level overlay for the flow; the `complete` service dropped.

The mockups (dark, 1280×800) stay a reference. The Chrome screenshots in PR 3 are the updated light, Danish, 3:2 screens
(`docs/mockups/README.md`).

## 8. The house

The `fitness` issue after the releases, for ha-claude-a8 and Thomas's yes, covers these.

**Install order:** the add-on first, then the integration.

**The workout tab:** a panel view with `ha-fitness-workout-card`, plus the clock and the sidebar button like the other
tabs.

**The today card's visibility rule** changes. The card shows when `binary_sensor.ha_fitness_training_open` isn't `off`,
**or** `binary_sensor.ha_fitness_session_running` is `on`.

**While `binary_sensor.ha_fitness_session_running` is on** (design §3.4):
- keep the tablet awake;
- hold the photo slideshow;
- hold the screensaver's return to the overview;
- the install script refuses.

**Asked of the house, optional:** allow autoplay for HA's origin in Edge (`AutoplayAllowed` or an allowlist). Then the
pings work after a reload without a tap.

## 9. Left to the plan

Module layout, the tick loop's code, the ring's SVG, the tone parameters, the overlay controller's API, test fixtures,
and the order of tasks.
