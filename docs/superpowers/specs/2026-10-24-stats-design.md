# Step 6: Stats – design

- **Date:** 2026-10-24 · **Status:** approved by Claude 2026-10-24 (full-reviewer Ready after 3 rounds), on Thomas's
  delegation for the night of 2026-10-23; Thomas reviews it on 2026-10-24
- **Implements:** [design spec](2026-10-23-ha-fitness-design.md) §10 step 6, with §3.3 (stats per person), §3.4 (stats
  on the workout tab), §3.7 (get stats over MCP) and §3.8 (per-person entities). Builds on
  [step 4](2026-10-24-training-today-design.md) (training days) and [step 5](2026-10-24-the-workout-design.md)
  (sessions, participants, counting from). Issue #6.
- **Needs an update on the real Home Assistant:** **yes, both parts**, plus one house change: the stats card on the
  workout tab (§7).
- `api_version` stays 1: this step only adds to the contract.
- "Claude's call" marks choices made without Thomas; he may overrule them.

## 1. Goal

After a month they can see, per person, the **streak**, **workouts done**, **workouts missed** and **total time
trained** (design §1, §3.3). The stats show on the workout tab, for **this month** and **all time** (design §3.4). Claude
can read them over MCP, and Home Assistant gets one sensor per person and number.

Stats are computed from the logs, never stored (design §3.3).

## 2. What ships, in two PRs

Each PR releases one component (D29).

1. **`feat: stats`.** It touches `addon/` and `docs/`.
   - The stats computation, from training days, sessions and participants.
   - `GET /api/v1/stats` and the read-only MCP tool `get_stats`.
   - The `stats` message on the push channel.
   - People get an `added_at` (migration 0004).
2. **`feat: stats card and sensors`.** It touches `custom_components/`, `cards/`, `tests/` and `docs/`.
   - The relay of the `stats` message and the ws command `ha_fitness/stats/subscribe`.
   - Four sensors per person.
   - The card `custom:ha-fitness-stats-card`.

Merge order 1 → 2. Installing PR 1 before PR 2 is safe: the step 5 integration drops unknown message types.

## 3. The numbers (add-on)

### 3.1 What counts

All of this is design §3.3, made exact. Before the first counted session, `counting_from` is null and every number is
0.

- **Which days count.** **Claude's call**, refining design §3.3 ("days closed before the counting date are left out"):
  - every `done` day counts. A day is only done through a counted session (D46), and the first counted session is what
    sets `counting_from`, so no done day is ever left out. This keeps the very first workout when it was done late
    (Monday's day trained on Tuesday sets `counting_from` to Tuesday) or crossed midnight;
  - a `missed` or `skipped` day counts when its `date` is on or after `counting_from`;
  - open days (due, late) count nowhere.
  - A day belongs to its own `date`, not to `closed_at`: Monday's day closed on Tuesday belongs to Monday.
- **For one person and one counted day**, the outcome is exactly one of:
  - **done**: the day is `done`, and the person is a participant of **any** counted session whose `training_day_id` is
    the day (normally there is exactly one);
  - **skipped**: the day is `skipped`;
  - **missed**: anything else (the day is `missed`, or it is `done` without the person).
- **An extra session** is a counted session with no `training_day_id`. Each participant gets one **done**, dated by the
  local date of `started_at`. It adds no day and doesn't touch the streak (design §3.3). A day session whose day was
  deleted (only the dev routes do that; `training_day_id` becomes null) counts as an extra session. An uncounted
  session (ended before one round) counts nowhere.
- **Time trained** is the sum of `time_trained` (whole seconds; step 5 §3.5) over the person's **counted** sessions:
  day sessions and extra sessions. **Claude's call:** an uncounted session adds no time, like it adds no done.
- **When a person was added.** People get a nullable `added_at` (UTC). For one person, a counted day whose `date` is
  before the local date of their `added_at` counts only when that person did it. Any other outcome (missed, skipped,
  or a done day without them) counts nothing for them, so someone added later doesn't start with a pile of misses.
  Null means "from the start": migration 0004 leaves `added_at` null for existing people, so an upgrade keeps all
  history. People added after the upgrade get the time they were added. **Claude's call.**
- **Removed people** have no stats. Their participant rows stay in the history (step 5).
- **Re-linking a person** to another HA person entity makes a new add-on person (`People.set` keys on the entity id,
  D33), so that person's stats start over.

### 3.2 The streak

- The streak counts **dates**, so it doesn't depend on the order days were created in. Take the dates that have at
  least one of the person's counted days (§3.1), newest first. A date **adds one** when every counted day on it is done
  by the person. Any other outcome on a date (missed or skipped) **ends** the streak there. The streak is the number of
  dates added before the first that ends it.
- So with two programs on one date, doing only one of them breaks the streak. A skip breaks it, like a miss (design
  §3.3, Thomas). Open days neither add nor break (design §3.3).
- Extra sessions don't count (design §3.3).
- **Claude's call:** the streak is all-time only. There is no "this month" streak and no best streak in v1.

### 3.3 This month and all time

- **All time:** everything §3.1 counts.
- **This month:** the same, limited to the current local calendar month. For a day, its `date` decides. For an extra
  session, the local date of `started_at` decides. For time trained, the local date of the session's `started_at`
  decides, so a session that crosses midnight belongs to the day it started.
- The month is the add-on's local month (D36), the same clock as the scheduler.

### 3.4 The result

```text
Stats
  counting_from: date | null
  month: "YYYY-MM"                  the add-on's current local month
  people: [PersonStats]             in the people's order (D33)

PersonStats
  id, name, person_entity_id
  streak: int
  all_time:   Totals
  this_month: Totals

Totals
  done: int                         days done + extra sessions done
  extra: int                        of done, how many were extra sessions
  missed: int                       missed days
  skipped: int                      skipped days
  time_trained: int                 whole seconds
```

**Claude's call:** `missed` and `skipped` stay apart in the data, so Claude can tell them apart. The card shows missed
and skipped as one number, "Missede", with skipped as a note (§5).

## 4. The API and the push channel (add-on)

- **Reads reconcile and tick first.** `GET /api/v1/stats`, `get_stats` and the connect snapshot reconcile the
  training days and tick the session first, under the lock, like every step 4 and 5 read. So a read just after
  midnight already sees yesterday's open day as missed.
- **REST:** `GET /api/v1/stats` → `Stats`.
- **MCP:** `get_stats`, read-only, returning the same `Stats`. The tool count goes from 16 to 17.
- **The push channel** sends a `stats` message with the whole `Stats`:
  - on connect, after `hello`, `today` and `session`. Like those, a newer queued `stats` replaces the snapshot. The
    connect snapshot is always sent;
  - after anything that can change it: a training day closed (missed, skipped or done), a session finished (completed or
    ended), people changed (added, removed, renamed or reordered), and `counting_from` set;
  - when the local month changes, so "this month" starts over. The scheduler's minute loop already notices a new local
    date; on a new month it publishes `stats`.
- Outside the connect snapshot, a `stats` message is published only when its content differs from the last one the
  hub published (one memory for the whole hub). **Claude's call:** this keeps the minute loop from pushing the same
  numbers.
- Stats are computed in the service layer under the same lock as the scheduler and sessions, so a push never shows a
  half-written change. **People writes** (`People.set`) now take that lock too, and publish `stats` after the commit;
  today they take no lock and publish nothing. They check the people against HA first, outside the lock (that call can
  take 10 s), and take the lock only for the database write and the publish, so a people change never holds up a
  running workout's ticks.
- **Performance:** a household has at most a few hundred days and sessions a year. Computing everything from the logs
  on each change is fine; no cache.

## 5. The integration and the card

### 5.1 The integration

- The coordinator keeps the last `stats` message.
- **Available** means connected **and** a `stats` message received since the last `hello`, like the session's "seen"
  (step 5 §4). Between a connect and the first `stats`, and while the add-on is unreachable, stats are unavailable.
- **An older add-on (D37).** A step 5 add-on never sends `stats`. After `hello`, the coordinator probes
  `GET /api/v1/stats`, as step 5 probes `/session`. A 404 while health answers raises the `addon_too_old` repair issue,
  and stats stay unavailable.
- **The ws command `ha_fitness/stats/subscribe`** sends `{available, stats}` at once and after each change, the same
  shape and rules as `ha_fitness/session/subscribe` (step 5 §4): while unavailable, `available` is false and `stats` is
  the last one known (null before the first).
- **Sensors**, four per person, on the "HA Fitness" device. Each has an explicit entity id, a translated name with a
  `{person}` placeholder, and a unique id:

  | Key | Entity id | Name (en / da) | State | Attributes |
  | --- | --- | --- | --- | --- |
  | `streak` | `sensor.ha_fitness_<person>_streak` | "{person} streak" / "{person} i træk" | the streak (§3.2), state class measurement, unit "days" / "dage" through a unit translation key only (no native unit; HA shows it in the system language) | — |
  | `done` | `sensor.ha_fitness_<person>_done` | "{person} done" / "{person} gennemført" | all-time done, state class total | `this_month` (done), `extra` (all time), `extra_this_month` |
  | `missed` | `sensor.ha_fitness_<person>_missed` | "{person} missed" / "{person} missede" | all-time missed **plus** skipped, state class total | `this_month` (missed + skipped), `skipped` (all time), `skipped_this_month` |
  | `time_trained` | `sensor.ha_fitness_<person>_time_trained` | "{person} time trained" / "{person} træningstid" | all-time time, device class duration, in minutes rounded down, state class total | `this_month` (minutes, rounded down) |

  - `<person>` is the object id of the person's HA person entity (`person.thomas` → `thomas`), so the ids stay the same
    when a name changes. `{person}` is the add-on person's name. Attribute names are keys, not translated texts; their
    names in the UI come from the translation files.
  - The unique id is `{entry_id}_person_{id}_{key}`, with the add-on person id, the same prefix as every existing
    entity. The translation key is the number's key; the entity id suffix is set separately.
  - **Claude's call:** state class `total`, not `total_increasing`: the dev routes can lower a count.
  - The attributes are not recorded.
  - Sensors come and go with the people: a person added in the add-on gets four new entities; a removed person's
    entities are removed from the registry.
  - While the add-on is unreachable, the sensors are unavailable.
- **Claude's call:** the sensors are all time; "this month" is an attribute. Automations like "streak ≥ 10" use the
  state.

### 5.2 The card

`custom:ha-fitness-stats-card`, for the workout tab, below the workout card.

- **One panel per person**, side by side (stacked below about 600 px), in the people's order and colours (purple
  `#B18CFF`, teal `#3DD6C6`, then the primary colour, as in step 5).
- **In each panel:**
  - the name, with the person's colour as a dot (never colour alone; design §3.4);
  - the streak, large, as "7 i træk" (plural rules);
  - a two-column table, "Denne måned" and "I alt", with rows **Gennemført**, **Missede** and **Tid**:
    - Gennemført: done; when there are extra sessions, "· 2 ekstra" after the number;
    - Missede: missed + skipped; when there are skips, "· 1 sprunget over";
    - Tid: hours and minutes, "4 t 35 min" (minutes only under an hour).
- **Which line shows**, the first that applies:
  1. never had stats and unavailable: "HA Fitness kan ikke nås";
  2. no people: "Ingen personer";
  3. `counting_from` null: "Statistikken starter ved første træning";
  4. otherwise the panels. While unavailable they keep the last numbers, with "HA Fitness kan ikke nås" as a small
     note, like the today card.
- Every text comes from the language files (hard rule 6), with the card's `language` option (D38). The card registers
  after HA's frontend boots, like the others.
- The card picker lists it in English, like the other cards ("HA Fitness stats"); there is no `hass` at module load.
- **Claude's call:** no history list on the tablet in v1. The history lives in the add-on's data and over MCP
  (`list_sessions`).

## 6. Tests

All through public interfaces (hard rule 5), with a frozen clock.

- **Add-on (`GET /stats` and MCP):**
  - Everything is 0 before the first counted session, with `counting_from` null.
  - The first counted session done late (Monday's day trained on Tuesday) counts as done; so does a first session that
    crosses midnight, for a day and as an extra session.
  - A read after midnight, before the minute loop, sees yesterday's open day as missed.
  - A day done by both: done +1 for each, streak 1.
  - A day done by one: done for that person, missed for the other; the streak breaks only for the other.
  - A missed day and a skipped day: missed and skipped counted; both break the streak.
  - A day done late (done on a later date) counts for its own date, and as done.
  - Open days (due, late) count nowhere and don't break the streak.
  - Two programs on the same date: two days. Doing only one breaks the streak, whichever day has the lower id (both id
    orders).
  - An extra session: done +1, extra +1, time added, streak unchanged.
  - An uncounted session: nothing.
  - Days before `counting_from` are left out.
  - A person added later: days before their `added_at` date count only when they did them. A missed day, a skipped
    day and a done day without them count nothing for them; a done day with them counts. A null `added_at` counts from
    the start.
  - A removed person has no stats.
  - This month vs all time across a month boundary, for days, extra sessions and a session started before midnight.
  - The order follows the people's positions.
- **Push:**
  - `stats` follows `session` on connect.
  - A skip, a miss (reconcile), a finished session, a people change and `counting_from` each push one `stats`; a newer
    queued `stats` replaces the connect snapshot.
  - The minute loop pushes `stats` on a new month and not otherwise; an unchanged result pushes nothing.
- **Migration 0004:** a step 5 database with counted days gives the same done, missed and time after the upgrade;
  existing people have a null `added_at`.
- **Integration:**
  - `ha_fitness/stats/subscribe`: the first message, a change, unavailable with the last stats, unavailable between a
    connect and the first `stats`.
  - The `addon_too_old` repair issue when `/stats` answers 404.
  - The sensors: states, attributes and translated names, ids from the person entity, unique ids, unavailable while
    unavailable, added and removed with the people.
- **Cards:**
  - The panels and numbers in Danish and English, plurals, the extra and skipped notes, time formatting.
  - Which line shows (§5.2's order), and the unreachable note with the last numbers.
  - The `language` option.

## 7. Docs, decisions and the house

- **Docs, PR 1:**
  - `architecture.md`: stats (computed, not stored), the route, the tool, the `stats` message, people writes under the
    lock.
  - `domain-language.md`: streak, done, missed, skipped, extra, time trained, this month, all time, made exact as in §3.
    Name two surprises there: a day dated 31 October done on 1 November counts its done in October but its time in
    November; and doing only one of two programs on a date breaks the streak.
  - `testing.md`: a stats check in the fast loop (done, a skip, an extra session).
- **Docs, PR 2:** `architecture.md`: the relay, the sensors, the probe and the card; `testing.md`: the card in the Chrome
  check.
- **Decisions** (numbered next, from D47):
  - D47 (PR 1): stats count every done day, and missed and skipped days from `counting_from`; for a person, a day
    before they were added counts only when they did it; a day belongs to its own date. This refines design §3.3's
    "days closed before the counting date are left out".
  - D48 (PR 1): only counted sessions add done and time; the streak counts dates, and a date adds one only when every
    counted day on it is done.
  - D49 (PR 2): per-person sensor ids come from the HA person entity's object id; names are translated with a
    `{person}` placeholder.
- **The house** (a `fitness` issue after the releases, for ha-claude-a8 and Thomas's yes): install the add-on before the
  integration (D37); place the stats card on the workout tab, below the workout card, with `language: da`.

## 8. Left to the plan

- The module layout (`stats.py` in the add-on), and where the "content changed" check lives.
- How the integration adds and removes per-person entities when people change. A person removed and re-added gets a
  new add-on id: remove the old registry entries before adding the new ones in the same update, so the entity ids
  don't get a `_2`.
- The card's exact layout at 1368×912 and 800×1280, checked in Chrome.
