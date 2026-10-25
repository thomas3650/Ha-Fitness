# Today ahead, late days, the start beep and the language fix

**Status:** approved by Thomas in chat on 2026-10-25; the full review's fixes after it are Claude's calls. Issues #70,
#71 and #72, in one branch and one PR (Thomas, 2026-10-25).

**Real Home Assistant:** yes, after the release. The release's `fitness` issue says:

- The house's today card can get the new `days_ahead` option (the dashboard belongs to the house assistant). Thomas may
  set the add-on's new `late_days` option on its Configuration tab.
- Late days stay open longer, so `sensor.ha_fitness_today`, `binary_sensor.ha_fitness_training_open` and the `missed`
  event change timing.
- Due and late days of different dates and programs can be open together in `sensor.ha_fitness_today`'s
  `training_days`.
- `sensor.ha_fitness_next_training_day` leaves out a date already done early.
- `ha_fitness_training_day_done` can fire for a date after today. `ha_fitness_training_day_due` doesn't fire for a date
  done early.
- An early session carries its training day's id from the start, in the session view and the session events.

House automations that use these may need a look.

**Builds on:** the scheduler (step 4 spec §3.3, D34), the day under a session (D42), the stats (D47, D48), the card
`language` option (D38), the card editors (D59) and the workout sounds (step 5 spec §5.4). Both the add-on and the
integration change, so both release.

## 1. Why

Thomas, 2026-10-25, in chat:

- **Ahead (#70).** He wants to see on the kitchen tablet that a training is coming tomorrow or the day after, so he
  can do it today when he knows he won't have time on the day. Today that would be an extra session: it adds done and
  time, but tomorrow's training day still comes, turns late and closes as missed, which breaks the streak.
- **Late (#70).** When a training slipped past, he wants to still do it and not have it count as missed. Today a late
  day closes as missed as soon as the next training day of **any** program begins, often the next day (design spec
  §3.2, step 4 spec §3.3).
- **The start beep (#71).** During the countdown, and at the end of every phase, the timer beeps short. When the
  exercise starts there should be one clearly long beep, so he knows without looking that it starts now. On the
  kitchen tablet he hears no such tone, although the code plays a 0.45 s tone at 1320 Hz at every work start
  (`cards/src/audio.ts`). Thomas tested it on the Mac in the fast loop (2026-10-25): the start tone plays at every
  work start after a switch or rest, but **not at the first work start after the 10 s countdown**. So there is a bug
  as well. The tone tests (`cards/test/workout-flow-pings.test.ts`, "work and switch/rest tones at local zero") pass,
  so the cause lies in something those tests don't model.
- **The language fix (#72).** A card config with a non-string `language` (for example `language: 1` in YAML) makes
  `cardLanguage()` pass a number to `localize()`, which throws, and the card doesn't render. Found by reading the code
  in the branch review of #65.

## 2. Goals

### 2.1 Late days stay open longer (#70)

1. A late training day stays open, and can still be started from the today card, until the first of these:
   - **Its own program trains again:** the start of the first later date on which that program has a training day,
     or at once when that day is made during today (a weekday edit that adds today, D34).
   - **Its days are up:** the start of the date `late_days + 1` days after its own date.

   Example, `late_days: 2`, a program on Monday and Wednesday, Monday missed: Monday is late on Tuesday and closes as
   missed at the start of Wednesday, because the program trains again. With a program on Monday and Friday only,
   Monday is late on Tuesday and Wednesday and closes as missed at the start of Thursday.
2. **Another program's training day no longer closes it.** This replaces the rule in design spec §3.2 and step 4 spec
   §3.3 that a new training day of any program closes every earlier open day. So late and due days of different
   programs and dates can be open at once, each with its own Start; the user chooses. Step 4 spec §3.5's "open days
   always share one date, so due and late never mix" is gone.
3. So a program has at most one open day, except under D42: a session for a late day that crosses midnight into the
   program's next training day keeps the late day open next to the new due day, as today.
4. A late day done in time closes as **done late**, as today. A day under a running or paused session stays open
   (D42, unchanged).
5. **`late_days`** is one household setting, an add-on option on the add-on's Configuration tab in HA. It decides what
   counts as missed, so it can't be a per-card option. Range 0–6. **Default 2** (Claude's call: it matches Thomas's
   example). 0 means a day closes as missed at the midnight after its date, so nothing is ever late. Its label and
   description are in English and Danish (the add-on's translations).
6. A change of `late_days` takes effect at the add-on's next start. Closed days never reopen. Open days already past
   the new limit close as missed at the first reconcile.
7. The dev route that makes an open day (`upsert_open`) still refuses a date after today, now because an open day dated
   after today would show as due.

### 2.2 Trainings ahead, with Start (#70)

1. The add-on's today data (`GET /api/v1/today`, the `today` message, MCP `get_today`) gains `upcoming`: one entry per
   active program, its next training after today. That is the first date after today on which the program trains and
   has no done, missed or skipped day. Each entry has the program's id and name, the date, the station count, the
   rounds and the total minutes (as an open day has), and `startable`. The search looks 14 days ahead, which always
   finds one for an active program (it trains at least weekly, and §2.2.2 allows one early training).
2. **`startable`** is false while the program has an open day (any date), or a done day dated today or later; true
   otherwise. So a program has one early training at a time: once Friday is done early, next Monday is a reminder
   until Friday has passed, and gets its Start on Saturday. Only within one program: another program's days don't
   block it (Thomas).
3. **Starting early.** A start may name a program and its upcoming date instead of a training day. The add-on accepts
   it only for that program's current upcoming entry with `startable` true; otherwise 409 `conflict`. A start with
   both a training day and a date is 422 `invalid`.
4. **What clients see during an early session.** The start makes the training day at once, open, dated on its future
   date, and the session carries its id as `training_day_id` from the start (so it is never an extra session, also in
   the stats). While the session runs:
   - The day is not in `open`, so `sensor.ha_fitness_today` and `binary_sensor.ha_fitness_training_open` don't change
     for it.
   - The program's `upcoming` entry stays on that date, with `startable` false.
   - The day shows in `GET /api/v1/training-days` as open. The week ring's `planned` doesn't change (it already counted
     that date).
   - No `due` event is sent for it, also when the session crosses midnight into its date.
5. **A counted early session closes the day as done**, with a `done` event, for its own date. On that date the
   scheduler makes no new day. In the stats the day belongs to its own date (D47), as a day done late already does:
   done and the streak follow its date, and the time follows the session's start, as today (`stats.py`). It counts in
   the week ring of its own date's week.
6. **An early session that doesn't count leaves no training day** while its date is still after today: the day is
   removed (ids are never reused, D34), and the training is upcoming again. The session itself stays in history, as
   every session does. If the session crossed midnight into the day's date, the day stays as that date's due day, and
   a `due` event is sent when the session ends.
7. The early session keeps the program and date it started with. It closes that date as done even when the program's
   weekdays changed meanwhile (D34: a weekday change leaves existing days alone). Switching off or deleting the program
   is refused while it runs (D42).
8. A day made early counts as the program's training day on its date for rule 2.1.1, even when it is already done.
9. **The next training day** (`next`, and so `sensor.ha_fitness_next_training_day`) leaves out a program's date that
   is already done (Claude's call: a house reminder for tomorrow shouldn't fire for a training already done). It looks
   14 days ahead, and is null only when no program is active.

### 2.3 The today card shows what's coming (#70)

1. **`days_ahead`**, a new option of the today card only, in its card editor (D59): how many days ahead the card shows
   upcoming trainings. Range 0–6, **default 0**, which keeps the card as it is (Claude's call: existing cards don't
   change until someone sets it; the house sets it through the `fitness` issue). The editor leaves the key out of the
   config at the default, as it does for `language`.
2. The card shows an upcoming entry when its date is at most `days_ahead` days after the today data's `date` (the
   add-on's local date, not the tablet's clock).
3. **An upcoming row** shows the program's name, when it is ("Tomorrow" / "I morgen" for the day after `date`, else the
   weekday name from the language files), and the same stations, rounds and minutes as an open row. It has **Start**
   when `startable`, and no Spring over. Not startable, it is a **reminder** only, with no buttons (Thomas: "just have
   it as a reminder so I know another one is coming").
4. Start on an upcoming row opens the workout flow at its details, as Start on an open row does, and the start carries
   the program and the date (§2.2.3). A refused start (409, for example just after midnight) shows an error text, as a
   refused start does today. (Claude's call.)
5. **Order:** the open rows by date, then program name, so a late day comes before a due one; then the upcoming rows by
   date, then name. The add-on sorts `open` that way too. (Claude's call.)
6. The card no longer hides itself when nothing is open but an upcoming row is in range. It still hides when there is
   neither, outside edit mode. `getCardSize()` counts the upcoming rows like open rows.
7. The look follows the open row, set apart enough to read as "coming, not due". It is checked with Thomas in the
   Chrome check, one screen at a time.

### 2.4 A long beep at every work start (#71)

1. Every work phase starts with one clearly **long beep, about 1 s**, that can't be mistaken for the short countdown
   beeps (Thomas: every exercise, not only the first). This is the tone at the end of the countdown, at the end of
   each switch and rest, and the change tone of Næste and Forrige into a work phase. A program without a countdown
   plays it when its first work phase starts at Start. Resuming into a work phase plays none. (Claude's calls.)
2. **The bug:** the start tone after the opening countdown is missing (§1). Its cause is found (systematic debugging,
   in the fast loop) and fixed, with a test that fails before the fix and models what the existing tests missed.
3. The short beeps in the last 5 s of every phase, the switch/rest tone and the chime stay as they are.
4. No short beep overlaps the long beep, also in a short work phase: the quiet time after a phase start (`QUIET_MS` in
   `workout-flow.ts`) is at least the long beep's length.
5. The long beep is checked in Chrome on the Mac in the fast loop, with Thomas listening, after the countdown too. The kitchen tablet check
   doesn't block the merge; if the beep doesn't play there, that becomes a new issue (Claude's call).

### 2.5 A non-string language option (#72)

1. `cardLanguage()` ignores a `language` that isn't a non-empty string, so the card falls back to the user's
   language, else English, and renders.
2. The card editor shows such a value as its own option, labelled with `String(value)`, as it shows an unknown
   language string, so it can be seen and cleared. Choosing that option again leaves the value as it was (a number
   doesn't become a string). Choosing the default removes it.

## 3. Unchanged

- Skip (Spring over) on open days, its two taps and the `ha_fitness.skip` service.
- Extra sessions from the workout card: they still close no training day.
- The session engine, the phases, the plan, the pause limit.
- The stats rules (D47, D48); only which days end up missed or done changes.
- The other two cards, apart from the language fix.

## 4. Non-goals

- Skipping an upcoming training in advance.
- More than one upcoming training per program.
- Per-card or per-person `late_days`.
- Reopening a day already closed as missed.
- Accepting a start for a date that turned into today (just after midnight); a 409 is fine.
- A sound setting (volume, pitch) or new sounds beyond the long beep.

## 5. Anti-goals

- **Doing a training twice for one date:** starting early must not leave both an early done day and a new due day on
  that date.
- **Missed and then done:** no day is closed as missed and later done (D42 holds).
- **A stray day:** an early session that didn't count must not leave an open or done day dated after today.
- **A card that breaks on an older add-on:** without `upcoming` the card shows no upcoming rows and nothing else
  changes.

## 6. Constraints

- **The contract.** `upcoming` and the start's date are additions: `api_version` stays 1, and the card hides what a
  missing field would feed (as for `week`). The today subscription already passes the add-on's data through.
- **The start's date in the integration.** `ha_fitness/session/command` (`start`) and the `ha_fitness.start_session`
  service take it as an optional field next to `training_day_id`. An older 1.x add-on doesn't know the field
  (`NewSession` forbids extra keys), and from 1.0.0 no release may need a newer other part. So the integration sends
  the date only when the add-on's last today data has `upcoming`; otherwise it refuses the start before any relay as
  `invalid`, with its own translated message. The field's texts go in `services.yaml`, `strings.json` and
  `translations/en.json` and `da.json` (hard rule 6).
- **The add-on option** follows the add-on's config (`options` and `schema` in `addon/config.yaml`, translations in a
  new `addon/translations/` with `en.yaml` and `da.yaml`), read from the Supervisor's options file. The fast loop and
  the tests need a way to set it without the Supervisor.
- Hard rules 5 (tests through public interfaces, a frozen clock) and 6 (every UI text in `en.json` and `da.json`).
- Tones are tested through the scheduled tones (the existing workout-flow tone tests), not exact audio values.
- The PR touches `addon/` and the rest, so it releases both parts. Its squash message lists each change as its own
  Conventional Commit line. release-please picks the component by the commit's paths, so both changelogs list every
  line; that is accepted.

## 7. Docs

In the same PR:

- `docs/domain-language.md`:
  - **Late** and **Missed**: the new closing rule.
  - New **Upcoming** and **Done early**.
  - **Extra session**: an early start from the today card is not one.
  - **Today card**: upcoming rows, hidden only with nothing open or upcoming.
  - **Next training day**: §2.2.9.
  - **Week ring**: a case for a day done early whose date falls in next week (this week's ring doesn't move).
  - **Stats, "Two rules surprise"**: a day dated 1 November done early on 31 October counts its done in November and
    its time in October.
- `docs/architecture.md`: `upcoming` and the order of `open` in the today data, the start's date in the session routes
  and the integration's start, the add-on option, the card's `days_ahead`.
- `docs/decisions.md`: a decision for late days (closing per program, `late_days`), and one for starting early. Both
  name the rule they replace (design spec §3.2, step 4 spec §3.3 and §3.5).
- `addon/DOCS.md`: the `late_days` option, taking effect at the add-on's next start.
- The MCP `get_today` docstring (`mcp_tools.py`) lists `upcoming`.
- `docs/testing.md`, if the fast loop gets a way to set `late_days`.

## 8. How it's checked

- The gates.
- Add-on tests with a frozen clock: the closing rule (own program, days up, other programs don't close it, the default,
  0, a lowered value, D42 across midnight), the order of `open`, `upcoming` and `startable` (open day, done day today or
  later, the 14-day search), starting early (accepted, refused, counted, not counted, crossing midnight counted and not
  counted, a weekday edit during it), what clients see during it (§2.2.4), the next training day, the stats and the
  week ring for a day done early.
- Integration tests: the date relayed through the ws command and the service, and refused when the add-on's today
  data has no `upcoming`.
- Card tests through the rendered text and roles: upcoming rows in and out of range, Start or reminder, order, hidden
  or shown, an older add-on without `upcoming`; the today editor's `days_ahead`; the language fix; the long beep
  scheduled at every work start and no beep overlapping it.
- The fast loop and the Chrome check with screenshots of the today card with upcoming rows and a late day, reviewed
  with Thomas.
- The long beep in Chrome on the Mac, with Thomas listening (§2.4.5).
- The full loop before the release: `late_days` and its translations show on the Configuration tab under the real
  Supervisor, and the add-on reads the value.

## 9. Left to the builder

- How the early start makes and removes its day inside the add-on, as long as §2.2.4–§2.2.6 and §5 hold.
- The name of the start's date field, and the exact pitch of the long beep.
- The editor control for `days_ahead` (native controls, D59).
- How the fast loop sets `late_days`.
