# Today ahead, late days, the start beep and the language fix

**Status:** approved by Thomas in chat on 2026-10-25. Issues #70, #71 and #72, in one branch and one PR (Thomas,
2026-10-25).

**Real Home Assistant:** yes, after the release. The house's today card gets the new `days_ahead` option (the
dashboard belongs to the house assistant), and Thomas may set the add-on's new `late_days` option. Late days stay open
longer, so `sensor.ha_fitness_today`, `binary_sensor.ha_fitness_training_open` and the `missed` event change timing;
house automations that use them may need a look. The release's `fitness` issue says all this.

**Builds on:** the scheduler (step 4 spec §3.3, D34), the day under a session (D42), the stats (D47, D48), the card
`language` option (D38), the card editors (D59) and the workout sounds (step 5 spec §5.4). Both the add-on and the
integration change, so both release.

## 1. Why

Thomas, 2026-10-25, in chat:

- **Ahead (#70).** He wants to see on the kitchen tablet that a training is coming tomorrow or the day after, so he
  can do it today when he knows he won't have time on the day. Today that would be an extra session: it adds done and
  time, but tomorrow's training day still comes, turns late and closes as missed, which breaks the streak.
- **Late (#70).** When a training slipped past, he wants to still do it and not have it count as missed. Today a late
  day closes as missed as soon as the next training day of **any** program begins, often the next day.
- **The start beep (#71).** During the countdown, and at the end of every phase, the timer beeps short. When the
  exercise starts there should be one clearly long beep, so he knows without looking that it starts now. On the
  kitchen tablet he hears no such tone, although the code plays a 0.45 s tone at 1320 Hz at every work start
  (`cards/src/audio.ts`). Either it doesn't play on the tablet, or it is too short to stand out; not known yet.
- **The language fix (#72).** A card config with a non-string `language` (for example `language: 1` in YAML) makes
  `cardLanguage()` pass a number to `localize()`, which throws, and the card doesn't render. Found by reading the code
  in the branch review of #65.

## 2. Goals

### 2.1 Late days stay open longer (#70)

1. A late training day stays open, and can still be started from the today card, until the first of these comes:
   - **Its own program trains again:** the start of the first later date on which that program has a training day.
   - **Its days are up:** the start of the date `late_days + 1` days after its own date.

   Example, `late_days: 2`, a program on Monday and Wednesday, Monday missed: Monday is late on Tuesday and closes as
   missed at the start of Wednesday, because the program trains again. With a program on Monday and Friday only,
   Monday is late on Tuesday and Wednesday and closes as missed at the start of Thursday.
2. **Another program's training day no longer closes it.** This replaces step 4 spec §3.3's rule that a new training
   day of any program closes every earlier open day. So late and due days of different programs can be open at once,
   each with its own Start; the user chooses.
3. A program never has two open days: rule 1 closes the old one when the new one is made.
4. A late day done in time closes as **done late**, as today. A day under a running or paused session stays open
   (D42, unchanged).
5. **`late_days`** is one household setting, an add-on option on the add-on's Configuration tab in HA. It decides what
   counts as missed, so it can't be a per-card option. Range 0–6. **Default 2** (Claude's call: it matches Thomas's
   example; 0 means a day closes as missed at the midnight after its date, so nothing is ever late). Its label and
   description are in English and Danish (the add-on's translations).
6. A change of `late_days` takes effect at the next start of the add-on, as the Supervisor restarts it after a save.
   Closed days never reopen. Open days already past the new limit close as missed at the first reconcile.

### 2.2 Trainings ahead, with Start (#70)

1. The add-on's today data (`GET /api/v1/today`, the `today` message, MCP `get_today`) gains `upcoming`: per active
   program, its next training after today. That is the first date after today on which the program trains and has no
   training day yet. Each entry has the program's id and name, the date, the station count, the rounds and the total
   minutes (as an open day has), and `startable`.
2. **`startable`** is false while the program has an open day (due or late), or a day done early whose date is still
   ahead; true otherwise. So a program has one early training at a time: once Friday is done early, next Monday is a
   reminder until Friday has passed. Only within one program: another program's days don't block it (Thomas).
3. **Starting early.** A start may name a program and its upcoming date instead of a training day. The add-on accepts
   it only for that program's current upcoming entry with `startable` true. Otherwise 409 `conflict`.
4. **A counted early session closes that training day as done**, for its own date. On that date the scheduler makes no
   new day and sends no `due` event for it, also when the session crosses midnight into that date. In the stats the
   day belongs to its own date (D47), as a day done late already does: done and the streak follow its date, and the
   time follows the session's start, as today (`stats.py`). It counts toward the week ring of its own date's week.
   While the early session runs, its future-dated day is not in `open`, so `sensor.ha_fitness_today` and
   `binary_sensor.ha_fitness_training_open` don't change for it. (Claude's calls.)
5. **An early session that doesn't count leaves no trace:** the training is upcoming again, as if nothing happened.
   A session that crosses midnight into its planned date is simply that date's day, under a session (D42).
6. A day made early counts as the program's training day on its date for rule 2.1.1, even when it is already done.
   (Thomas agreed that Monday closes on Wednesday morning even if Wednesday was done early. With `startable` that
   case can't arise, but the rule doesn't depend on it.)
7. **The next training day** (`next`, and so `sensor.ha_fitness_next_training_day`) leaves out a program's date that
   is already done early (Claude's call: a house reminder for tomorrow shouldn't fire for a training already done).
   A date with no program left isn't the next training day.

### 2.3 The today card shows what's coming (#70)

1. **`days_ahead`**, a new today-card option in the card editor (D59): how many days ahead the card shows upcoming
   trainings. Range 0–6, **default 0**, which keeps today's card unchanged (Claude's call: existing cards don't change
   until someone sets it; the house sets it through the `fitness` issue). The editor leaves the key out of the config
   at the default, as it does for `language`.
2. The card shows an upcoming entry when its date is at most `days_ahead` days after today.
3. **An upcoming row** shows the program's name, when it is ("Tomorrow" / "I morgen" for tomorrow, else the weekday
   name from the language files), and the same stations, rounds and minutes as an open row. It has **Start** when
   `startable`, and no Spring over. Not startable, it is a **reminder** only: no buttons (Thomas: "just have it as a
   reminder so I know another one is coming").
4. Start on an upcoming row opens the workout flow at its details, as Start on an open row does, and the start carries
   the program and the date (§2.2.3). A refused start (409, for example just after midnight) shows an error text, as a
   refused start does today. (Claude's call.)
5. **Order:** the open rows first, as today; then the upcoming rows by date, then name. (Claude's call.)
6. The card no longer hides itself when nothing is open but an upcoming row is in range. It still hides when there is
   neither, outside edit mode. `getCardSize()` counts the upcoming rows like open rows.
7. The look follows the open row, set apart enough to read as "coming, not due". It is checked with Thomas in the
   Chrome check, one screen at a time.

### 2.4 A long beep at every work start (#71)

1. Every work phase starts with one clearly **long beep, about 1 s**, that can't be mistaken for the short countdown
   beeps (Thomas: every exercise, not only the first). This is the tone at the end of the countdown, at the end of
   each switch and rest, and the change tone of Næste and Forrige into a work phase.
   A program without a countdown plays the long beep when its first work phase starts at Start. (Claude's call.)
2. The short beeps in the last 5 s of every phase, the switch/rest tone and the chime stay as they are.
3. No short beep overlaps the long beep, also in a short work phase.
4. The long beep is checked in Chrome on the Mac in the fast loop. Thomas checks it on the kitchen tablet when it suits
   him, by opening the dev HA from the tablet; that check doesn't block the merge (Claude's call, as Thomas gave no
   answer). If it doesn't play on the tablet, that becomes a new issue.

### 2.5 A non-string language option (#72)

1. `cardLanguage()` ignores a `language` that isn't a non-empty string, so the card falls back to the user's
   language, else English, and renders.
2. The card editor shows such a value as its own option, as it shows an unknown language string, so it can be seen and
   cleared. Choosing the default removes it.

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
- A sound setting (volume, pitch) or new sounds beyond the long beep.

## 5. Anti-goals

- **Doing a training twice for one date:** starting early must not leave both an early done day and a new due day on
  that date.
- **Missed and then done:** no day is closed as missed and later done (D42 holds).
- **A blocked training:** an early session that didn't count must not leave a stray open or done day.
- **A card that breaks on an older add-on:** without `upcoming` the card shows no upcoming rows and nothing else
  changes.

## 6. Constraints

- **The contract.** `upcoming` and the start's date are additions: `api_version` stays 1, and the card hides what a
  missing field would feed (as for `week`). The integration relays the date in `ha_fitness/session/command` (`start`)
  and in the `ha_fitness.start_session` service, as an optional field next to `training_day_id`. The add-on refuses a
  start with both a training day and a date (422 `invalid`). The today subscription already passes the add-on's data
  through.
- **The add-on option** follows the add-on's config (`options` and `schema` in `addon/config.yaml`, translations in
  a new `addon/translations/` with `en.yaml` and `da.yaml`), read from the Supervisor's options file. The fast loop and the tests need a way to set it
  without the Supervisor.
- Hard rules 5 (tests through public interfaces, a frozen clock) and 6 (every UI text in `en.json` and `da.json`).
- Tones are tested through the scheduled tones (the existing workout-flow tone tests), not exact audio values.
- The PR touches `addon/` and the rest, so it releases both parts. Its squash message lists each change as its own
  Conventional Commit line, so both changelogs get one entry per change.

## 7. Docs

In the same PR:

- `docs/domain-language.md`: **Late** and **Missed** (the new closing rule), new **Upcoming** and **Done early**, the
  **Today card** (upcoming rows, hidden only with nothing open or upcoming), **Next training day** (§2.2.7).
- `docs/architecture.md`: `upcoming` in the today data, the start's date in the session routes and the integration's
  start, the add-on option, the card's `days_ahead`.
- `docs/decisions.md`: a decision for late days (closing per program, `late_days`), and one for starting early. Both
  name the step 4 rule they replace.
- `addon/DOCS.md`: the `late_days` option.
- `docs/testing.md`, if the fast loop gets a way to set `late_days`.

## 8. How it's checked

- The gates.
- Add-on tests with a frozen clock: the closing rule (own program, days up, other programs don't close it, the default,
  0, a lowered value), `upcoming` and `startable`, starting early (accepted, refused, counted, not counted, crossing
  midnight), the next training day, the stats and the week ring for a day done early.
- Integration tests: the date relayed through the ws command and the service.
- Card tests through the rendered text and roles: upcoming rows in and out of range, Start or reminder, order, hidden
  or shown, an older add-on without `upcoming`; the editor's `days_ahead`; the language fix; the long beep scheduled at
  every work start and no beep overlapping it.
- The fast loop and the Chrome check with screenshots of the today card with upcoming rows and a late day, reviewed
  with Thomas.
- The long beep in Chrome on the Mac; on the tablet when Thomas can (§2.4.4).

## 9. Left to the builder

- How an early start creates and, when uncounted, removes its training day, as long as §2.2.4–§2.2.5 and §5 hold.
- The name of the start's date field, and the exact pitch of the long beep.
- The editor control for `days_ahead` (native controls, D59).
- How the fast loop sets `late_days`.
