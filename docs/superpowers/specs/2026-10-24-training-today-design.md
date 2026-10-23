# Step 4: "Træning i dag" – design

- **Date:** 2026-10-24 · **Status:** approved by Claude 2026-10-24 (full-reviewer Ready after 4 rounds), on Thomas's
  delegation for the night of 2026-10-23; Thomas reviews it on 2026-10-24
- **Implements:** [design spec](2026-10-23-ha-fitness-design.md) §10 step 4, with §3.2, §3.4 (the today card),
  §3.8 and §4. Builds on [step 3](2026-10-24-programs-through-chat-design.md). Issue #4.
- **Needs an update on the real Home Assistant:** **yes, both parts.**
  - A new add-on version (the scheduler, the push channel, discovery) and a new integration version (entities, the
    service, events, the card).
  - **Order:** install the integration's new version before accepting the "Discovered" card (§4.1). Both reach the
    house together after Thomas's local test, so the `fitness` issue says it.
  - The integration is set up from that Discovered card.
  - Placing the card on `dashboard-kitchen` and the workout tab are house work: ha-claude-a8 specs them in the house
    repo, and Thomas says yes there (§9).
- "Claude's call" marks choices made without Thomas; he may overrule them.

## 1. Goal

On a training day the kitchen tablet shows a small "Træning i dag" card with the program's name and **Spring over**. A
day nobody trained stays visible as "Forfalden · onsdag" until the next training day begins. The card hides itself when
nothing is open. **Start** arrives in step 5 with the workout flow. Nothing is counted yet (design §3.3: counting starts
with the first completed session, step 5).

## 2. What ships, in two PRs

Each PR releases one component (D29).

1. **`feat: training days`.** It touches `addon/`, `scripts/` and `docs/`, and releases the add-on only.
   - Training days and the scheduler;
   - skip;
   - the today API and two MCP tools;
   - the websocket push channel (D6);
   - Supervisor discovery (D28);
   - a dev-only way to make a late day;
   - `scripts/seed --today` and `--late`.
2. **`feat: Træning i dag card and entities`.** It touches `custom_components/`, `cards/`, `tests/`, `scripts/`, `docs/`
   and root files as needed, and releases the integration.
   - Discovery and the manual URL;
   - the connection;
   - entities, the service and events;
   - the websocket subscription for the card;
   - repair issues;
   - the card;
   - `dev_onboard.py`'s URL step and the dev dashboard.

The docs each PR updates are in §10.

## 3. Training days (add-on)

### 3.1 States

A training day is one program on one date. Its stored `status` is `open`, `done`, `missed` or `skipped`. "Due" and
"late" are not stored. An open day is **due** on its own date and **late** after it (domain language).

Stored fields:
- `id`;
- `program_id` (null after the program is deleted);
- `program_name` (a copy, so history keeps the name);
- `date` (the local date);
- `status`;
- `created_at`, `closed_at`.

The pair (`program_id`, `date`) is unique.

### 3.2 The timezone

The add-on's local time comes from `HA_FITNESS_TIMEZONE`, else `TZ`, else UTC (with a log line).
- **Under the Supervisor**, `TZ` is HA's timezone (`docs/ha-notes.md`).
- **In the fast loop**, `scripts/develop` sets `HA_FITNESS_TIMEZONE=Europe/Copenhagen`, and `dev_onboard.py` sets
  the dev HA to the same zone (§8), so a `TZ` in the Mac's shell doesn't matter.

A changed timezone takes effect at the add-on's next restart. The image has the IANA zone data: the `tzdata` Python
package is a dependency.

### 3.3 The scheduler

`reconcile(today)` runs at start, every minute, after every program write, and before every read of `/today` or
`/training-days` (it is cheap and idempotent). One lock serialises every reconcile run, skip, program write and dev-route call, so none of them race.
A read can therefore create days and send events and `today` pushes; that is intended, and `get_today` keeps
`readOnlyHint: true` because it changes nothing a client asked for. It handles each local date from the day
after the last fully handled date **up to and including today**, and today again on every run. For each such date:

1. For each **active** program with that date's weekday, create an `open` training day, unless one exists for that
   program and date. A closed one counts too, so a skipped day is never made again.
2. If at least one training day exists for that date, every `open` day with an **earlier** date becomes `missed`
   (design §3.2: "until the next training day of any program begins").

What follows from re-running today (Claude's calls):
- **A program created or switched on today** gets today's day straight away if today is one of its weekdays, so a
  program made in the morning reminds the same day. The same holds for a weekday edit that adds today.
- **That new day closes earlier late days as missed** (rule 2). Example: a Thursday program created on a Thursday
  closes Wednesday's late day.
- **The first run starts at today.** No days are made up for the past, because counting starts when the app is live.
- **Days off are caught up.** After a few days with the add-on off, `reconcile` handles each missed date in order.

Program writes:
- **Switching off** (`set_program_active`, or `update_program` that sets `active: false`) and **deleting** remove the
  program's **open** days, so it no longer asks to be trained. Closed days stay, and on delete their `program_id`
  becomes null. An open day therefore always has its program.
- **A rename** (`update_program`) updates `program_name` on the program's open days. Closed days keep the name they
  had.
- **Removing today from the weekdays** leaves today's open day alone. It still asks once; it can be skipped.
- **A pause removes a late day:** switching a program off and on again on a day it doesn't train removes its late day,
  which then never counts as missed. That is accepted (D33).

Two programs on the same date give two open days. Both show, ordered by program name (design §3.2).

The scheduler's own creates and misses aren't client writes, so they aren't in the change log. A skip is.

### 3.4 Skip

`skip(training_day_id)` closes an **open** day as `skipped` (design §3.2: on purpose, no reason). Skipping a closed day
is a 409 and an unknown id a 404. A skip adds one change-log row: action `training_day.skipped`, target
`training_day:<id>`, summary "Skipped Onsdag (2026-10-28)". The confirmation step is the card's (§6).

### 3.5 What the API returns

`GET /api/v1/today`:

```json
{
  "date": "2026-10-28",
  "open": [
    {"id": 12, "program_id": 3, "program_name": "Onsdag", "date": "2026-10-28", "state": "due",
     "station_count": 5, "rounds": 5, "total_minutes": 29}
  ],
  "next": {"date": "2026-10-31", "programs": ["Lørdag"]}
}
```

- `open` holds every open day, by program name. Open days always share one date (rule 2 closes earlier ones as soon
  as a later date has a day), so due and late never mix. The program fields come from the program as it is now.
- `next` is the first date **after today** on which an active program trains, with those programs' names. It is null
  when no program is active.

Other routes:
- `POST /api/v1/training-days/{id}/skip` → the day (200), or a 404 or 409.
- `GET /api/v1/training-days?from=&to=` → the days in a date range, by date. It is for checks and the later stats.

MCP gets two tools: `get_today` (read; the same as `GET /today`) and `skip_training_day` (write,
`destructiveHint: true`, "ask first").

**Dev only:** with `HA_FITNESS_DEV=1`, `POST /api/v1/dev/training-days` with `{"program_id", "date"}` creates an open
day on any date, or reopens the existing day for that program and date. `DELETE /api/v1/dev/training-days?date=`
removes every training day of that date, open or closed. That is how the fast loop gets a late day. Without the
variable these routes don't exist: they answer 404 and aren't in OpenAPI. `scripts/develop` sets the variable; the
add-on never does.

### 3.6 The push channel (D6)

`GET /api/v1/ws` is a websocket. The client sends nothing. Unknown message types are ignored on both sides, which keeps
the protocol forward compatible.

**Messages the add-on sends:**
- **On connect:** `{"type": "hello", "version": …, "api_version": 1}`, then `{"type": "today", "data": <GET /today>}`.
- **A new `today`:** whenever what `/today` returns changes. That covers a reconcile (including the date rollover at
  midnight, where due turns late and `next` moves, even when nothing is created), a skip, and a program write.
- **One event per state change of a training day:**
  `{"type": "event", "event": "due" | "skipped" | "missed", "training_day": {"id", "program_id", "program_name", "date"}}`.
  - `due` fires when a day is created for **today**. A day created for a past date during catch-up fires nothing,
    because it is already late.
  - `missed` and `skipped` fire as they happen.
  - `done` comes in step 5.

**Delivery:** events are fire-and-forget. A client that isn't connected misses them; the `today` state is what counts.

### 3.7 Discovery

`config.yaml` gets `discovery: [ha_fitness]`. At every start the add-on posts to `http://supervisor/discovery` (D28):

```json
{"service": "ha_fitness", "config": {"host": <its hostname>, "port": 8765}}
```

- The hostname comes from `GET http://supervisor/addons/self/info`.
- Outside the Supervisor, discovery does nothing.
- A failure is logged and doesn't stop the server.

## 4. The integration

### 4.1 Setting it up

- `manifest.json` drops `single_config_entry`. HA would abort a discovery for an existing entry before the flow runs.
- Every flow sets the unique id `ha_fitness`. A second entry is aborted as `already_configured`, which is translated.
  The current test `test_second_entry_is_refused` changes to expect that.
- **Discovery** (`async_step_hassio`):
  - It calls `_abort_if_unique_id_configured(updates={"url": "http://<host>:<port>"})`, so an existing entry gets the
    add-on's address and reloads.
  - Otherwise it shows "HA Fitness add-on found" and creates the entry. `title_placeholders` make the Discovered card
    read "HA Fitness" (`docs/ha-notes.md`).
- **Manual** (`async_step_user`) has one field, `url`, with the default `http://localhost:8765` (the fast loop). It
  checks `GET <url>/api/v1/health` before creating the entry, with the error `cannot_connect`.
- **Entry version 2.** A version 1 entry (0.1.0, no `url`, no unique id) is migrated:
  - `url = http://localhost:8765`;
  - unique id `ha_fitness`.

  Under the Supervisor, the next discovery then corrects the url. That covers an entry made in the window between the
  add-on's and the integration's release.

### 4.2 The connection

- One client per entry holds the websocket. It reconnects after 1, 2, 5 and 10 s, then every 30 s.
- REST calls (the skip) send `User-Agent: ha_fitness/<integration version>`.
- **On `hello`** the client checks `api_version`.
  - The integration supports API version **1**, and the previous one once 2 exists (`docs/architecture.md`).
  - Another version raises the repair issue `unsupported_api_version`, which names the part to update. Entities stay
    unavailable.
- **An older add-on** has no `/api/v1/ws`: Starlette closes an unknown websocket path before accepting it, which
  uvicorn sends as an HTTP rejection (403). So when the handshake is rejected with any HTTP status while
  `GET /api/v1/health` answers and `GET /api/v1/today` gives 404, the client raises the repair issue `addon_too_old`
  ("update the HA Fitness add-on") and keeps retrying.
  - This is a ruling (D36): while both parts are 0.x, an integration release may need a newer add-on, as long as it
    says so through this repair issue and the `fitness` issue states the order. From 1.0.0 on, the contract rule of
    `docs/architecture.md` holds without exception.
- Each repair issue is deleted once a supported add-on connects.
- **While disconnected, or on an unsupported version,** every entity is unavailable and the card's subscription sends
  `null`.

### 4.3 Entities

There is one device, "HA Fitness". Its `sw_version` is the add-on's `version` from `hello`. The entities use
`has_entity_name`, `translation_key` and unique ids `<entry_id>_<key>`.

Entity ids are set explicitly, so they don't depend on HA's language. HA builds Danish ids from Danish names otherwise.

| Key | Entity id | Name (en / da) | State | Attributes |
| --- | --- | --- | --- | --- |
| `today` | `sensor.ha_fitness_today` | Training today / Træning i dag | enum `none`, `due`, `late` (`due` if any open day is due, else `late` if any is late) | `training_days`: the `open` list of §3.5 |
| `next_training_day` | `sensor.ha_fitness_next_training_day` | Next training day / Næste træningsdag | date `next.date`, or unknown | `programs` |
| `training_open` | `binary_sensor.ha_fitness_training_open` | Training open / Træning åben | on while any day is open | — |

- `training_days` and `programs` are in `_unrecorded_attributes`: the recorder keeps the state only.
- **While disconnected**, all three are `unavailable`. So the house's visibility rule for the card should be
  `state_not: "off"` on `binary_sensor.ha_fitness_training_open`. Then the card also shows while the add-on can't be
  reached, and says so (§6).
- The session-running sensor arrives with sessions in step 5. Per design §3.4 it is `off` whenever no session runs, and
  the house's guard follows then.

### 4.4 Service and events

- **The service** `ha_fitness.skip` takes `training_day_id` (int).
  - A 404 or 409 raises `ServiceValidationError` with the keys `not_found` and `not_open`.
  - An unreachable add-on raises `HomeAssistantError` with the key `unavailable`.
  - All three texts are translated.
  - The service is registered in `async_setup`, so `CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)`.
  - `complete`, `start_session` and `end_session` come with step 5.
- **Events,** one per add-on event. Their data is the `training_day` object:
  - `ha_fitness_training_day_due`
  - `ha_fitness_training_day_skipped`
  - `ha_fitness_training_day_missed`

### 4.5 The card's subscription

The cards talk only to HA (design §4).

- **`ha_fitness/today/subscribe`** is a websocket subscription. It sends the current `today` data at once, then again
  after each change, and `null` while the add-on is unreachable or unsupported. It needs a logged-in user.
- **Skipping** goes through the service (`hass.callService("ha_fitness", "skip", …)`). Any user may call it: the
  wallpanel user isn't an admin.

## 5. Language

The integration's texts are in `strings.json` and `translations/en.json` and `da.json`: entity names, enum states, the
config flow, the service and its errors, and the repair issues. The card's texts are in `cards/src/i18n/`.

The card picks its language in this order:
1. its `language` option, if set (the house sets `language: da` on its cards; D37 extends D11);
2. otherwise `hass.locale.language`;
3. otherwise English.

Weekday names come from the language files, not from `Intl`, so hard rule 6 holds.

## 6. The card

The step 1 placeholder becomes the real card, `ha-fitness-today-card`.

**One row for each open day:**
- the program's name, large;
- under it, a short line from the language file. In Danish: "5 øvelser · 5 runder · ca. 29 min". A late day reads
  "Forfalden · onsdag · 5 øvelser · …";
- on the right, a **Spring over** button.

**Spring over takes two taps.** A wake tap also clicks, which is a house rule.
- The first tap swaps the row's button for "Spring over?" with **Nej** and **Ja**.
  - **Nej** sits where Spring over was, so a double tap cancels.
  - **Ja** ignores taps for 0.5 s after it appears.
- Ja calls the service. Nej, or 10 s with no tap, puts the row back.
- A service error shows a text from the card's own language files for 5 s, chosen by the error's translation key
  (`not_found`, `not_open`, `unavailable`; anything else: a general error text). HA translates service errors in the
  system language, not in the card's `language`.
- Every target is at least 48 px high.

**Showing and hiding.** HA's `hui-card` hides a card when the element sets `hidden` and fires
`card-visibility-changed`. It does not hide one that is only `display: none`, which would leave an empty grid cell.
- **Nothing open:** the card sets `hidden` and fires the event.
- **When `preview` is true** (the card editor, or the dashboard in edit mode), it never hides. Instead it shows a
  one-line note, "Ingen træning i dag", so the card can be found.
- **Add-on unreachable** (the subscription sent `null`): one muted line, "HA Fitness kan ikke nås". The card is not
  hidden.

**Other details:**
- **Size:** `getGridOptions()` gives `columns: "full"` and `rows: 2` per open day (at least 2), so a name, a line and a
  48 px button fit. The Chrome check confirms it at 1368×912. `getCardSize()` is 2 per day.
- **Theme:** HA's colours only (the tablet uses the light theme). No hover effects. No meaning carried by colour alone.
- **Config:** `type` and an optional `language`. There is no editor UI in v1; it is a YAML card.
- **Picker entry:** its name and description come from the language file (this closes the step 1 item in #14).

## 7. Tests

**Add-on**, through REST, MCP and the websocket, with a frozen clock and timezone:
- midnight creates due days;
- a passed day reads as late;
- the next training day of any program closes late days as missed;
- a date with no training day closes nothing;
- catch-up after 3 days off;
- the first run makes up nothing;
- creating or switching on a program on a training day makes today's day and closes earlier late days;
- `update_program` with `active: false` removes open days;
- a rename updates open days;
- deleting removes open days and keeps closed ones;
- two programs on one date, ordered by name;
- skip, and a skipped day isn't made again;
- skipping a closed day gives a 409;
- the date rollover pushes `today` with nothing created;
- the DST Sundays in Europe/Copenhagen: one rollover each;
- the ws `hello` and `today` messages, and the events (`due` only for today);
- the dev routes: both 404 without `HA_FITNESS_DEV`; with it, `POST` creates a late day or reopens one, and `DELETE`
  removes the open and closed days of a date;
- discovery: sent with the hostname when a Supervisor is faked, skipped without one;
- the skip change-log row.

**Integration**, with `pytest-homeassistant-custom-component` and a fake add-on (an aiohttp test server with REST and
ws):
- discovery creates the entry;
- discovery for an existing entry updates the url;
- a second manual entry gives `already_configured`;
- the manual step's connection check;
- migration v1 → v2 sets the url and the unique id;
- entity ids and states from `today` messages;
- unavailable on disconnect, and back on reconnect;
- the `unsupported_api_version` repair issue for API version 3, and the issue gone after a supported connect;
- the `addon_too_old` repair issue when the ws handshake is rejected with 403 and `/today` gives 404;
- the service's errors;
- the events fired;
- the subscription sends data, and `null` on disconnect.

**Card**, with Vitest, a fake `hass` and its rendered text and roles:
- rows for due and late days, in Danish and English;
- `hidden` set and the event fired when nothing is open;
- in preview: no hiding, and the note shown;
- the two-step skip calls the service only after Ja;
- Nej and the 10 s timeout cancel;
- Ja ignores taps for 0.5 s;
- the unreachable line;
- the `language` option wins.

**Chrome check** (`docs/testing.md`), at 1368×912 in the fast loop, as the Danish user, with no console errors. Due
and late days never show together (§3.5), so they are separate scenarios:
- `seed --today`: one due day; then after a skip, nothing open (hidden);
- `seed --late`: one late day ("Forfalden · <weekday>");
- edit mode with nothing open (the note);
- the add-on stopped: the unreachable line.

**Full loop:** the Discovered card, the setup, the entities and the card.

## 8. Fast loop

- **`scripts/develop`** sets `HA_FITNESS_DEV=1` and `HA_FITNESS_TIMEZONE=Europe/Copenhagen`, and
  **`scripts/dev_onboard.py`** sets the dev HA's own timezone to the same zone (`config/core/update`), so both agree
  from the first start. (PR 1.)
- **`scripts/seed`** (PR 1):
  - `--today` adds today's weekday to the Sample program and reopens its day for today through the dev route, so it is
    due at once, also after a skip earlier that day (§3.3);
  - `--late` makes Sample late. It first refuses when another active program trains today, before changing anything.
    Then it switches Sample off (removing its open days), sets its weekdays to every day except
    today, removes every training day of today through the dev route (any day today, closed ones included, would close
    the late one), switches it on, and creates (or reopens) its day for yesterday.
- **`scripts/dev_onboard.py`** (PR 2) creates the entry through the user step with `http://localhost:8765`, and creates
  a dev dashboard `ha-fitness-dev` with the card (Claude's call: the step 1 Chrome check made one by hand).

## 9. The house

- Where the card goes on the overview, and the workout tab, are agreed with ha-claude-a8 (design §3.4). Its facts
  (2026-10-23):
  - The overview is a sections view.
  - The right column holds the task rows and the timers.
  - A card with its own visibility rule fits that pattern.
  - The workout tab would be a panel view.
- This step's `fitness` issue proposes:
  - the card goes in the right column between the tasks and the timers, with `grid_options: columns: full`,
    `language: da`, and the visibility rule `state_not: "off"` on `binary_sensor.ha_fitness_training_open`;
  - the workout tab waits for step 5, which brings what fills it;
  - install order: integration first, then accept the Discovered card;
  - the card shows "HA Fitness kan ikke nås" while the add-on is stopped or updating, and during an HA restart.

  The house specs it, and Thomas decides.
- The WallPanel slideshow returning to the overview matters from step 5, once a workout is running. It isn't part of
  this step.

## 10. Docs and decisions

**PR 1** (add-on) updates:
- `docs/architecture.md`: what exists now, the ws protocol as part of the contract, and "Data the add-on reads from HA"
  (the timezone comes from `TZ`, D35);
- `docs/domain-language.md`: a training day is also created during the day (§3.3), not only at 00:00;
- `docs/testing.md`: `seed --today` and `--late`, and the dev route;
- `addon/DOCS.md`: discovery and the timezone.

It also adds decisions:
- **D33:** the scheduler's rules (re-running today, the first run, program writes, removing open days, a pause removes
  a late day);
- **D34:** the push channel's protocol;
- **D35:** the timezone source.

**PR 2** (integration) updates:
- `docs/architecture.md`: the connection, the entities, the repair issues, and a pointer from the contract rule to
  D36's 0.x exception;
- `docs/domain-language.md`: the open-days sensor;
- `docs/testing.md`: the dev dashboard, and the Chrome check of the card;
- `docs/ha-notes.md`:
  - `single_config_entry` aborts discovery;
  - Danish entity ids;
  - `hui-card`'s `hidden` and `card-visibility-changed`.

It also adds decisions:
- **D36:** a 0.x integration may need a newer add-on, through `addon_too_old`;
- **D37:** the card's `language` option (extends D11);
- **D38:** entry version 2 with the unique id `ha_fitness` and no `single_config_entry`.

## 11. Left to the plan

Module layout, how the scheduler's clock is injected, the aiohttp client in the integration, the fake add-on for the
integration tests, the card's internal structure, and the order of tasks.
