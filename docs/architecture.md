# Architecture

Three parts in one repo (D1). The design, with what each part will own in v1, is spec §4
([design spec](superpowers/specs/2026-10-23-ha-fitness-design.md)). This doc says who owns what, what exists now, and
the rules for the contract between the parts.

## Who owns what

| Part | Folder | Owns | Talks to |
| --- | --- | --- | --- |
| Add-on "HA Fitness" (slug `ha_fitness`) | `addon/` | The data and the logic: programs, people, the exercise library, the scheduler, sessions, history, the change log; REST and MCP on its own port | The integration; Claude (MCP); HA through the Supervisor's HA API |
| Integration "HA Fitness" (domain `ha_fitness`) | `custom_components/ha_fitness/` | Entities, services, events, Music Assistant calls, the websocket relay for the cards, the media proxy for GIFs; serves the cards bundle | The add-on; HA |
| Cards | `cards/` | The screens: "Træning i dag", the workout flow, stats | Only HA, through the integration's websocket commands |

The cards are built into the integration: one bundle, released and versioned with it (D8).

## What exists now

- **Add-on server** (`addon/server/`, FastAPI, D2) on port 8765 (D15). It keeps its data in the data folder: `/data`
  in the add-on, `HA_FITNESS_DATA_DIR` in the fast loop. The image is built from `addon/Dockerfile` on HA's Python base
  image. The design of what it holds is the
  [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md), for training days the
  [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md), for sessions the
  [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md), and for stats the
  [stats spec](superpowers/specs/2026-10-24-stats-design.md); the code is the source for the details.
  - **Database:** SQLite in `<data folder>/ha_fitness.db`, in WAL mode (D4, D5). Alembic migrations ship in the
    package and run to `head` at start. A database at a revision the code doesn't know stops the start.
  - **Exercise library:** the 721 filtered exercises are built into the package; their GIFs and thumbnails are
    downloaded into `<data folder>/library/media/` in the background at every start (D13, D30). Custom exercises live
    in their own table.
  - **People** (at most 2) linked to HA person entities, **programs** (one validated JSON document each, D4) and the
    **change log** of every write.
    - Each person has `added_at`, the UTC time their row was created (migration 0004). A person kept by a people write
      keeps it. It is null for people from before 0004, which means "from the start". Stats use it (D47).
    - **People writes** (`People.set`) check the persons against HA first, outside the lock, because that call can
      take 10 s. Only the database write and the reconcile after it take the lock, so a people change never holds up
      a running workout's ticks. The reconcile publishes `today` and `stats` when they changed.
  - **Training days** and the **scheduler** (step 4 spec §3.3, D34). A training day is one program on one local date,
    stored as open, done, missed or skipped; only a counted session closes a day as done. Training-day ids are never reused, so a skip by id
    can't hit a later day. The scheduler reconciles at start, every minute, after every program write and before
    every read of the days. One lock serialises the scheduler, skips, program writes, people writes, sessions, stats and the dev routes.
  - **Sessions** ([below](#sessions)): the workout engine, one session at a time (D40), with history and the
    "counting from" date.
  - **Stats** ([below](#stats)): per person, computed from the training days and the sessions on each read. They are
    never stored.
  - **REST** under `/api/v1/` (the routes are step 3 spec §7). `GET /api/v1/health` answers
    `{"status": "ok", "version": "<server version>", "api_version": 1}`. Step 4 adds `GET /api/v1/today`,
    `GET /api/v1/training-days?from=&to=` and `POST /api/v1/training-days/{id}/skip` (step 4 spec §3.4–§3.5). Step 5
    adds the [session routes](#sessions). The stats add `GET /api/v1/stats` ([below](#stats)).
  - **UI-refresh fields** ([spec](superpowers/specs/2026-10-24-ui-refresh-design.md) §3). `GET /api/v1/today` and the
    `today` message carry `week: {done, planned}`: household numbers for the current local week, Monday to Sunday. A
    program (REST and MCP) carries `equipment`, the distinct equipment of its stations without "body weight". A
    completed session can be rated with `POST /api/v1/session/feeling` ([below](#the-session-routes)). A card hides
    what a missing field would feed, so there is no `addon_too_old` for these and `api_version` stays 1.
  - **MCP** at `/mcp` (the tools are step 3 spec §8, plus `get_today` and `skip_training_day` from step 4 spec §3.5,
    the read-only `get_session` and `list_sessions` from step 5 spec §3.5, and the read-only `get_stats` from the
    stats spec §4). No MCP tool starts or steers a workout.
  - **The push channel** `GET /api/v1/ws`, a websocket (D6, D35; [below](#the-push-channel)).
  - **Supervisor discovery:** at every start under the Supervisor the add-on posts the service `ha_fitness` with its
    hostname and port 8765 (D28, step 4 spec §3.7). Outside the Supervisor it does nothing. A failure is logged and
    doesn't stop the server.
  - **Dev routes** under `/api/v1/dev/` exist only with `HA_FITNESS_DEV=1`, which only `scripts/develop` sets
    ([`testing.md`](testing.md#fast-loop)).
  - **The Ingress page** at `/`: a status page, in English or Danish after the browser's language (D27).
  - **Hot backups** through a consistent snapshot, `<data folder>/backup/snapshot.db` (D31). The snapshot is also
    written at every shutdown (D43).
- **Integration** (the [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §4; the code is the
  source for the details):
  - **One entry**, version 2, with the unique id `ha_fitness` and the add-on's URL as its data (D39). It comes from
    the add-on's discovery (D28), which shows under "Discovered", or from the user step, which asks for the URL
    (`http://localhost:8765` in the fast loop) and checks `GET /api/v1/health` first. The user step aborts when any
    entry exists. A discovery for an existing entry updates its URL and reloads it. A version 1 entry (0.1.0) is
    migrated to `http://localhost:8765` at its setup. A discovery that comes before that setup gives the unmigrated
    entry the version 2 shape and its URL in place, so the setup skips the migration.
  - **The connection** to the add-on's push channel ([below](#the-integrations-side)). Setup never waits for the
    add-on.
  - **Entities** on one device "HA Fitness", whose software version is the add-on's version:
    `sensor.ha_fitness_today` (`none`, `due` or `late`, with the open days in `training_days`),
    `sensor.ha_fitness_next_training_day` (a date, with `programs`) and `binary_sensor.ha_fitness_training_open`. The
    entity ids are set in the code, so they are the same in every HA language
    ([why](ha-notes.md#the-integration)). The two attributes aren't recorded.
  - **The service** `ha_fitness.skip` (`training_day_id`) and the **events** `ha_fitness_training_day_due`,
    `_skipped` and `_missed`, with the training day as data.
  - **The card's subscription** `ha_fitness/today/subscribe`, a websocket command: the add-on's `today` data at once
    and after each change, `null` while the add-on can't be used.
  - **Sessions** (the [workout spec](superpowers/specs/2026-10-24-the-workout-design.md) §4): the entity
    `binary_sensor.ha_fitness_session_running`, the services `ha_fitness.start_session` and `ha_fitness.end_session`,
    the session events, the session relay for the cards and the websocket commands
    ([below](#sessions-in-the-integration)).
  - **Stats** (the [stats spec](superpowers/specs/2026-10-24-stats-design.md) §5.1): four sensors per person and the
    stats relay for the cards ([below](#stats-in-the-integration)).
  - **The media proxy** `GET /api/ha_fitness/media/{exercise_id}/{kind}`, an exercise's GIF or thumbnail behind HA's
    login (D44; [below](#the-media-proxy)).
  - **The cards bundle:** setting up the entry serves `custom_components/ha_fitness/frontend/` at
    `/ha_fitness_frontend/` and loads `/ha_fitness_frontend/ha-fitness-cards.js?v=<integration version>` in the
    frontend. The version in the URL busts browser caches after an update.
- **Cards:** Vite builds `cards/src/index.ts` into `custom_components/ha_fitness/frontend/ha-fitness-cards.js`.
  The bundle registers its elements, the three cards and `ha-fitness-workout-flow`, once HA's frontend has booted
  ([`ha-notes.md`](ha-notes.md#the-frontend)). The texts come from `cards/src/i18n/`
  (`en.json` is the base, `da.json` Danish) and follow the card's `language` option, else the HA user's language
  (D11, D38).
  - **"Træning i dag"** (`custom:ha-fitness-today-card`) has a top line with the streak badge, the week ring, then
    one row per open training day (a two-tap Spring over, and Start), or the session row ("Træning i gang" with
    Fortsæt) while a session runs or is paused. The badge follows `ha_fitness/stats/subscribe`. It is hidden before
    counting, while the stats are unavailable and with no people. The ring comes from the `today` message's `week`.
    It is hidden without `week` or with `planned` 0. The card hides itself when nothing is open, except in edit
    mode, and shows one line while the add-on can't be reached.
  - **The workout card** (`custom:ha-fitness-workout-card`) lists the active programs with Start, for a workout on
    any day (an extra session).
  - **The workout flow** is one page-level overlay (D45), a `<dialog>` opened with `showModal()`: details and the
    people, get ready, the timer, paused and done. Its source is split by step in `cards/src/flow/`. The done step
    subscribes to the stats only while it shows a counted session. It follows the session through `ha_fitness/session/subscribe`,
    starts and steers it through `ha_fitness/session/command`, shows the media through the proxy (D44), and plays the
    beeps with Web Audio (step 5 spec §5).
  - **The stats card** (`custom:ha-fitness-stats-card`) goes on the workout tab, below the workout card. It follows
    `ha_fitness/stats/subscribe`. It has one panel per person, in the people's order and colours. The panels sit side
    by side, and stack below about 600 px of card width (a container query). A panel has the name, the streak and a
    table of this month and all time.
    - One line shows instead of the panels when there is nothing to show: unreachable before any stats, no people,
      or no counted session yet.
    - While the add-on is unreachable, the card keeps the last stats, with a small unreachable note above.
    - It shows nothing before the first message.
    - The exact texts and their order are in the [stats spec](superpowers/specs/2026-10-24-stats-design.md) §5.2
      and the language files in [`cards/src/i18n/`](../cards/src/i18n/).

### Routing in the add-on server

- The MCP app is mounted at `/`, after every other route, and serves `/mcp` itself (D26). So any path no route
  matches reaches the MCP app, which answers a plain-text 404.
- A catch-all route `/api/{path}` keeps an unknown `/api` path a JSON 404 (`{"detail": "Not Found"}`). It must stay
  after every `/api` route: a route registered below it is shadowed.
- A wrong method on a known `/api` path also gets that 404, not a 405. The catch-all matches the path and the method,
  and Starlette prefers it over a route that matches only the path.
- The dev router (only with `HA_FITNESS_DEV=1`) is included right after the `/api` routes, above the catch-all.
- The Ingress page `GET /` sits after the catch-all and before the MCP mount.

## The contract between the add-on and the integration

- The add-on reports an **API version** (`api_version` in the health response; 1 now). It goes up only with a
  breaking change to the contract.
- The integration supports the current and the previous API version. If it finds another, it raises an HA repair issue
  saying which part to update.
- No non-major release of one part may require a newer version of the other part. The two are installed and updated
  separately (D8), in any order. While both parts are 0.x, an integration release may need a newer add-on, through
  the `addon_too_old` repair issue (D37). From 1.0.0 on the rule holds without exception.
- REST and MCP are thin adapters over one service layer in the add-on; the integration uses the same REST API (D3).
- The push channel `/api/v1/ws` is part of the contract, under the same API version. Its `hello` message carries the
  `api_version`. Both sides ignore message types they don't know, so a new message type isn't a breaking change.

### The push channel

`GET /api/v1/ws` is a websocket (D6). The protocol is step 4 spec §3.6 (D35):

- The client sends nothing. Whatever it sends is ignored.
- On connect the add-on sends `hello` (`version`, `api_version`), then `today`, with the same data as
  `GET /api/v1/today`.
- After that it sends a new `today` whenever that data changes, and one `event` (`due`, `skipped`, `missed` or `done`)
  per state change of a training day.
- Step 5 adds `session` ([below](#sessions)): it follows `today` on connect, and comes again after every change.
- The stats add `stats` ([below](#stats-on-the-push-channel)): it follows `session` on connect, and comes again when
  the numbers change. A new message type isn't a breaking change, so `api_version` stays 1.
- Events are fire-and-forget: a client that isn't connected misses them. The `today` state is what counts.

```json
{"type": "event", "event": "skipped", "training_day": {"id": 12, "program_id": 3, "program_name": "Onsdag", "date": "2026-10-28"}}
```

### The integration's side

- **One client per entry** holds the websocket, with a 30 s heartbeat (a ping the add-on answers). It reconnects after
  1, 2, 5 and 10 s, then every 30 s. The first failed connect of an outage logs one warning.
- **On `hello`** it checks `api_version`. It speaks version 1. On another version it raises a repair issue, and the
  entities stay unavailable.
- **REST calls** (the skip and the session commands) send `User-Agent: ha_fitness/<integration version>`, so the
  add-on's change log names the integration.
- **While disconnected, or on an unsupported version,** every entity is unavailable and the today subscription sends
  `null`. The session and stats subscriptions send `available: false` with the last view or stats instead
  ([below](#sessions-in-the-integration), [stats](#stats-in-the-integration)).
- **The repair issues**, both errors that the user fixes by updating a part. Each is deleted once a supported add-on
  connects.
  - `unsupported_api_version`: the add-on speaks another API version. It says to update the integration.
  - `addon_too_old`: the ws handshake is refused with an HTTP status, `GET /api/v1/health` answers and
    `GET /api/v1/today` gives 404. That is an add-on from before step 4 (D37). It says to update the add-on, and the
    client keeps retrying.
    - It is also raised for an add-on from before sessions or before stats. After each supported `hello`, one
      background route probe gets `GET /api/v1/session`, then `GET /api/v1/stats`. A 404 on either while `/health`
      answers raises the issue. The connection stays up, so `today` still works. Each `hello` deletes the issue first,
      and the probe raises it again on such an add-on. A probe that can't reach the add-on does nothing; the next
      `hello` probes again.

### Sessions in the integration

The add-on's side (the session view, the `session` message, the events and the error codes) is [below](#sessions).
The integration relays it.

- **The last view.** The coordinator keeps the last `session` message's view. A disconnect keeps it, so a card can go
  on counting down. "Seen" is reset on each `hello` and each disconnect. The session is available while the add-on is
  connected and has sent a `session` message since.
- **`binary_sensor.ha_fitness_session_running`** is on while the view's status is `running` or `paused`, and off for
  `null` or a finished view. It is unavailable unless the session is available, so it is also unavailable between a
  connect and the first `session` message. Its attributes `program` (the program's name) and `participants`
  (`[{id, name}]`) are always there: the view's values while it is on, `null` and `[]` when it is off. They aren't
  recorded.
- **The events** `ha_fitness_session_started`, `_session_completed`, `_session_ended` and `_phase_changed` carry the
  add-on's event `session` as data. The add-on's `done` fires `ha_fitness_training_day_done`, with the training day.
- **The services.**
  - `ha_fitness.start_session` takes `program_id`, `participants` (person ids) and an optional `training_day_id`.
  - `ha_fitness.end_session` takes no fields.
  - The schema only checks the types. The add-on checks the rest, so its refusal is the one shown.
  - A refusal (`not_found`, `conflict` or `invalid` in the add-on's `detail.code`) raises a translated validation
    error with the key `session_<code>`. Anything else that fails is `unavailable`.
- **The websocket commands.** None needs an admin, because the wallpanel user isn't one.
  - `ha_fitness/session/subscribe` sends `{available, session}` at once and after each change. The relay is described
    below.
  - `ha_fitness/session/command` takes `command` (`start`, `pause`, `resume`, `next`, `previous`, `end` or
    `feeling`), and for `start` also `program_id`, `participants` and an optional `training_day_id`. For `feeling` it
    takes a `feeling` field, which the integration passes on to the add-on. It returns the add-on's view. Its
    error codes are `not_found`, `conflict`, `invalid` and `unavailable`. A `start` without its arguments is
    `invalid` before any relay. A field of the wrong type fails HA's own schema, as `invalid_format`.
  - `ha_fitness/programs` gives the active programs, in the add-on's order, in the shape of workout spec §4. It is
    built from `GET /api/v1/programs`. `total_minutes` rounds a half minute up. It also relays `total_seconds` and
    `equipment` (`[]` from an older add-on).
  - `ha_fitness/people` gives `[{id, name}]` from `GET /api/v1/people`.
  - The lists answer `unavailable` when the add-on can't be used, or sends an item they can't read.

#### The session relay

- **What counts as a change** is the pair (available, the add-on's view without `server_time`). A message from the
  add-on that changes only `server_time` sends nothing.
- **Every send** copies the view and sets `server_time` to HA's current time (UTC ISO with milliseconds).
- **`time_trained` moves on** by HA's now minus the add-on's `server_time`, in whole seconds. That happens only while
  the status is `running` and the phase isn't the countdown. So a card that subscribes in the middle of a phase gets
  the right elapsed time. HA and the add-on share the host's clock.
- **While the add-on can't be used** it sends `available: false` with the last view, not `null`. With no loaded entry
  it sends `{available: false, session: null}`.
- It follows the dispatcher, not one coordinator, so it survives an entry reload.

### Stats in the integration

The add-on's side (what counts, the route and the `stats` message) is [below](#stats). The integration relays it and
makes sensors of it.

- **The last stats.** The coordinator keeps the last `stats` message's data, also across a disconnect. A `stats`
  message whose `data` isn't an object is ignored. The stats are available while the add-on is connected and has sent
  a `stats` message since the last `hello`. So they are unavailable between a connect and the first `stats`, and while
  the add-on is unreachable.
- **`ha_fitness/stats/subscribe`** sends `{available, stats}` at once and after each change of the pair. While
  unavailable, `stats` is the last one known, or `null` before the first. With no loaded entry it sends
  `{available: false, stats: null}`. It follows the dispatcher, so it survives an entry reload. It needs no admin.
- **An older add-on** never sends `stats`. The route probe raises `addon_too_old` for it
  ([above](#the-integrations-side)), and the stats stay unavailable.
- **Four sensors per person**, on the "HA Fitness" device. `<person>` is the object id of the person's HA person
  entity (`person.thomas` → `thomas`), so the ids stay the same when a name changes (D49). The unique id is
  `{entry_id}_person_{id}_{key}`, with the add-on person's id.

  | Key | Entity id | Name (en / da) | State | Attributes |
  | --- | --- | --- | --- | --- |
  | `streak` | `sensor.ha_fitness_<person>_streak` | "{person} streak" / "{person} i træk" | the streak; state class measurement; no unit | — |
  | `done` | `sensor.ha_fitness_<person>_done` | "{person} done" / "{person} gennemført" | all-time done; state class total | `this_month`, `extra`, `extra_this_month` |
  | `missed` | `sensor.ha_fitness_<person>_missed` | "{person} missed" / "{person} missede" | all-time missed plus skipped; state class total | `this_month` (missed plus skipped), `skipped`, `skipped_this_month` |
  | `time_trained` | `sensor.ha_fitness_<person>_time_trained` | "{person} time trained" / "{person} træningstid" | all-time minutes, rounded down; device class duration; state class total | `this_month` (minutes, rounded down) |

  - The names are translated, with the add-on person's name as `{person}`. HA caches a name, so a rename in the
    add-on shows after the entry is reloaded. The ids stay.
  - The streak has no unit: HA takes a translated unit from the English file only
    ([`ha-notes.md`](ha-notes.md#the-integration)), so "dage" would never show.
  - State class `total`, not `total_increasing`, because the dev routes can lower a count.
  - The attribute names are keys; the UI's names for them come from the translation files. The attributes aren't
    recorded.
  - A sensor is unavailable unless the stats are available and hold its person.
- **Added and removed with the people.** On each update while the stats are available, the entry's person sensors in
  the registry are compared with the people in the stats. A person added in the add-on gets four sensors. A removed
  person's sensors are removed from the registry and the state machine. The removals come before any add, so a person
  removed and added again with a new add-on id keeps the entity ids (no `_2`). One update runs at a time, and running
  it twice changes nothing. A disconnect keeps the sensors, unavailable.

### The media proxy

`GET /api/ha_fitness/media/{exercise_id}/{kind}` relays the add-on's
`GET /api/v1/exercises/{exercise_id}/{kind}` (D44).

- **Auth:** it is an HA view with `requires_auth`. A request without a valid token gets 401. The cards fetch through
  `hass.fetchWithAuth` ([why](ha-notes.md#the-frontend)).
- **Patterns:** `exercise_id` must be a library id (four digits) or a custom id (`custom-<n>`, n from 1), and `kind`
  must be `gif` or `thumbnail`. The match is whole and ASCII only. Anything else gives 404 before any relay, so the
  proxy never reaches another add-on path. HA's own request filter answers 400 for some paths before the view runs
  ([`ha-notes.md`](ha-notes.md#the-integration)).
- **The add-on** is found through any loaded entry, even while the push channel is down. With no loaded entry the
  answer is 503.
- **Answers:** a 404 from the add-on stays 404. A connection error, a timeout (30 s) or any other status gives 503. A
  file comes back with the add-on's `Content-Type` and `Cache-Control: private, max-age=86400`.
- The view is registered once per HA run, in the integration's `async_setup`.

## Data the add-on reads from HA

HA's timezone (for midnight), the person entities, and Music Assistant's speakers and playlists.

- **The timezone** comes from the environment, not from HA's API (D36): `HA_FITNESS_TIMEZONE`, else `TZ`, else UTC
  with a log line. Under the Supervisor, `TZ` is HA's timezone ([`ha-notes.md`](ha-notes.md#the-supervisor)). The
  fast loop sets `HA_FITNESS_TIMEZONE`. A change takes effect at the next start.
- **The rest** the add-on reads itself through HA's REST API, so its MCP tools work even when the integration isn't
  connected. So far it reads only the persons: `GET /api/states`, filtered to `person.*`.

- **Under the Supervisor:** `http://supervisor/core/api` with `SUPERVISOR_TOKEN` (`homeassistant_api: true`). The
  server only sees the token because the Dockerfile's `CMD` starts with `with-contenv`
  ([why](ha-notes.md#the-supervisor)). `SUPERVISOR_TOKEN` wins over the variables below.
- **Elsewhere (the fast loop):** `HA_FITNESS_HA_URL` is HA's base URL (the server adds `/api`), and
  `HA_FITNESS_HA_TOKEN_FILE` names a file with a token. The file is read at each call, so a token written after the
  server started works without a restart. `scripts/dev_onboard.py` keeps the dev token in `local/dev-ha-token` (D32).
- Without a URL or a token, HA is "not configured". A read still answers, with `ha_persons: null` and `ha_error`; a
  write that needs HA fails with 503.

## Sessions

The design is the [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3 (D40–D43); the code is
`addon/server/src/ha_fitness_server/sessions.py`.

- **The plan.** A start freezes the plan: the program's name and timing, its stations with their names, and the
  participants with their names. A later program edit or a removed person changes no running session and no history.
  The phases follow from the plan: countdown, then per round work and switch per station, then rest. There is no
  switch after the last interval of the last round (D41), so the session ends with the last work phase.
- **Deadlines, not counters.** A session stores its phase and the time that phase started. Each next phase starts at
  the previous one's deadline, so no time drifts, and several phases can pass in one tick.
- **One at a time.** Only one session can be running or paused. Another start gives a 409.
- **The loop.** The lifespan runs the tick in a worker thread. It wakes at the current phase's deadline, and at least
  every `session_tick_max` seconds (1 s; a field of `Settings` with no environment variable, which tests change). Every command and every read ticks first, under
  the scheduler's lock. A tick that moves on publishes one `session` message and one `phase_changed` event, for the
  phase it ends on. `last_tick_at` is written every 5 s and at every phase change.
- **Restarts.** At shutdown the lifespan pauses a running session, then writes the snapshot (D43). At start a session
  still running (after a crash) is paused at its `last_tick_at`, so the time the add-on was down counts as a pause.
  A restart never skips phases or completes a workout nobody did.
- **The pause limit.** A session paused for 30 minutes is ended, at `paused_at + 30 min`, with the client `addon`.
  After a crash that was down longer than that, it is ended at the start. The usual counting rules apply.
- **Finishing.** The tick passing the last work phase, or `next` on it, completes the session. `end` or the pause
  limit ends it early; it counts when at least one full round is behind it. A counted session with a training day
  closes the day as done (done late when the day's date is before the local date of `started_at`). The first counted
  session sets `counting_from`. Each finished session keeps one row per participant, with the name and no foreign key.
- **The day under a session** (D42). Reconcile leaves an open day alone while a session for it is running or paused.
  Skipping that day gives a 409. Switching off or deleting the program of a running or paused session gives a 409 with
  "A session for this program is running"; this holds for extra sessions too.
- **Due and late can mix.** Step 4's rule that a new training day closes a late one waits while a session runs for the
  late day. A session that crosses midnight into another training day keeps its late day open next to the new due day.

### The session routes

| Method and path | Does |
| --- | --- |
| `GET /api/v1/session` | The running or paused session; else the last finished one for 5 minutes after it finished; else `null`. |
| `POST /api/v1/session` | Start: `{"program_id", "participants": [person ids], "training_day_id"?}` → the session view (201). |
| `POST /api/v1/session/{command}` | `pause`, `resume`, `next`, `previous` or `end` → the session view. |
| `POST /api/v1/session/feeling` | `{"feeling": "too_easy" \| "just_right" \| "too_hard"}` on a completed session within its 5-minute finished view → the session view. It is declared before `{command}`. A later call changes the rating. Any other current view gives 409 `conflict`; an unknown value gives 422 `invalid`. |
| `GET /api/v1/sessions?limit=` | `{"counting_from", "sessions": [finished views, newest first]}`; `limit` 1–100, default 20. |

- **Errors.** These routes answer `{"detail": {"code", "message"}}`. The codes are `not_found` (404), `conflict` (409)
  and `invalid` (422). An unknown command is a 404 `not_found`; a command not allowed now is a 409 `conflict`. Steps
  3–4's routes keep their own error shapes, and so do the skip and program 409s above. A start body that doesn't
  parse (a missing field, an extra key, a participant that isn't a number) gets FastAPI's own 422 list. So does a
  feeling body that isn't `{"feeling": <text>}`.
- **The view** (`SessionView` in `schemas.py`) has the phase with `ends_at` (UTC with milliseconds, null while paused)
  or `remaining` (while paused), the next phase, each participant's current and next station, `totals`
  (`planned`, `rounds`, `stations`), `time_trained` in whole seconds, `revision`, which goes up with every change, and
  `server_time`. A finished view has no phase, next phase or stations.
- **The feeling** is stored on the session (a nullable column) and shown in the view, in `GET /api/v1/sessions` and in
  the MCP `list_sessions`. A write raises `revision` and publishes `session`.
- **The change log** records `session.started`, `session.completed`, `session.ended` and `session.feeling`. Pause,
  resume, next and previous aren't logged.

### Session messages on the push channel

- `{"type": "session", "data": <view or null>}`. It is sent on connect after `today`, and after every change: a phase,
  a command, a finish or the pause limit. A finished view is sent once. When its 5 minutes are over, the loop sends
  `null`, unless a new session has started.
- Events: `{"type": "event", "event": …, "session": {"id", "program_name", "training_day_id", …}}` for
  `session_started`, `session_completed`, `session_ended` (with `counted`) and `phase_changed` (with `phase`).
- `{"type": "event", "event": "done", "training_day": {…}}` when a counted session closes its day, then a new
  `today`, then `stats` ([below](#stats-on-the-push-channel)).

## Stats

The design is the [stats spec](superpowers/specs/2026-10-24-stats-design.md) §3 and §4 (D47, D48); the code is
`addon/server/src/ha_fitness_server/stats.py`. What the numbers mean is in
[`domain-language.md`](domain-language.md#stats).

- **Computed, not stored.** Each read computes every person's numbers from the training days, the counted sessions
  and their participants, `counting_from` and the people. There is no cache: a household has at most a few hundred
  days and sessions a year.
- **Reads tick and reconcile first.** `GET /api/v1/stats`, `get_stats` and the connect snapshot tick the session,
  then reconcile the training days, under the lock. So a read just after midnight already sees yesterday's open day as
  missed.
- **REST:** `GET /api/v1/stats` → `Stats` (`counting_from`, `month` as `YYYY-MM` in the add-on's local time, and
  `people` in the people's order). Each person has `streak`, `all_time` and `this_month`; the totals are `done`,
  `extra`, `missed`, `skipped` and `time_trained` (whole seconds). `Stats` in `schemas.py` is the shape.
- **MCP:** `get_stats`, read-only, returns the same `Stats`.

### Stats on the push channel

- `{"type": "stats", "data": <Stats>}`. On connect it follows `hello`, `today` and `session`, and it is always sent.
  Like those, a newer `stats` queued while the snapshot was read replaces it.
- **When it is sent.** Every reconcile, and so every training-day change, ends by calling the stats hook
  (`TrainingDays.on_change`) after `today`. So on the stream the order is the events, then `today` if it changed,
  then `stats`. A finished session (completed or ended) also runs it, with or without a `done` event, so an extra
  session counts at once. A people write runs it through its reconcile.
- **Only when changed.** Outside the connect snapshot, `stats` goes out only when it differs from the last one the hub
  published: one memory for the whole hub. The minute loop reconciles every minute, so it runs the hook too, but it
  sends nothing while the numbers stay the same.
- **A new month.** The first minute-loop run in a new local month changes `month` and resets `this_month`, so it
  sends `stats`.
