# Domain language

The words used in specs, code and UI. Use them as defined here. The rules behind them (when a day turns late) are in
spec §3 ([design spec](superpowers/specs/2026-10-23-ha-fitness-design.md)), and the exact stats rules in the
[stats spec](superpowers/specs/2026-10-24-stats-design.md) §3; feature specs fix the exact entity, service and tool
names. Danish UI words live in the language files; the ones below are those the
spec already names.

## Programs

| Term | Meaning |
| --- | --- |
| **Program** | A named circuit with its exercises, its training days (weekdays), and its playlist and speaker. Several programs can be active at once. |
| **Active** | A program that repeats on its training days. An inactive program creates no training days. |
| **Circuit** | The only workout type in v1: S stations, R rounds, work time, switch time, rest between rounds. |
| **Station** | One exercise in the circuit (1–15). Each participant is at one station per interval. |
| **Round** | One pass through all stations: S intervals. |
| **Interval** | One work period at a station, followed by the switch time, except after the last interval of the last round (D41). |
| **Work time** (W) | Seconds of work per interval. |
| **Switch time** (r) | Seconds to move to the next station after an interval. |
| **Rest between rounds** | Seconds of rest after a round, except the last. |
| **Countdown** | Seconds before the first interval (0, 5 or 10). |
| **Phase** | A stretch of the timer: countdown, work, switch or rest. Each has a fixed length; the session ends when the last work phase ends. |
| **Plan** | What a session freezes at its start: the program's name, timing and stations, and the participants with their names. A later edit changes no running session and no history (D40). |

## People and sessions

| Term | Meaning |
| --- | --- |
| **Person** | Someone who trains, linked to an HA person entity. |
| **Participant** | A person taking part in one session (1 or 2, at most the number of stations). Participant 1 starts at station 1, participant 2 at station 2. |
| **Session** | One run of a program's workout, from start to done or ended early. |
| **Extra session** | A session started when nothing is due, or from the workout tab. It counts toward done and time trained, not toward the streak, and closes no training day. |
| **Feeling** | How a workout felt, given on the finished screen: too easy, just right or too hard. Stored with the completed session, so Claude can read it when it adjusts a program. |
| **Ended early** | A session stopped before its last work phase ended: with Slut or Annullér, or after 30 minutes paused. It counts as done if at least one full round was completed. |

## Training days

| Term | Danish UI | Meaning |
| --- | --- | --- |
| **Training day** | | One program on one of its weekdays (one local date). Created at 00:00 HA time, and also during the day when a program is created, switched on, or gets today's weekday (D34). |
| **Due** | | Today's training day, not done yet. |
| **Late** | Forfalden | A due day that has passed untouched. It stays visible until the next training day of any program begins, unless a session for it is running or paused (D42). |
| **Missed** | | A late day closed because the next training day began. |
| **Skipped** | | A training day closed on purpose with Spring over (one confirmation, no reason). |
| **Done** | | A training day closed by a counted session. |
| **Done late** | | A done day whose date is before the local date of the session's first work phase. A session that crosses midnight is not late. |
| **Week ring** | Denne uge | Done over planned training days for the current local week, Monday to Sunday, for the household. Planned counts this week's days of any status, plus the days the active programs will still create until Sunday. Done counts days with status done. |
| **Open** | | Due or late. |
| **Closed** | | Done, missed or skipped. |
| **Next training day** | Næste træningsdag | The first date after today on which an active program trains. The entity `sensor.ha_fitness_next_training_day`, with the programs of that date. |
| **Training today** (the open-days sensor) | Træning i dag | The entity `sensor.ha_fitness_today`: `due` if any open day is due, else `late` if any is late, else `none`. Its `training_days` attribute lists the open days. |
| **Training open** | Træning åben | The entity `binary_sensor.ha_fitness_training_open`: on while any training day is open. Unavailable, like every HA Fitness entity, while the add-on can't be reached. |

The week ring in five cases:

- A late day from last week, trained on Monday, counts as done in last week. The ring doesn't move.
- After a fresh install, or when a program is created or switched on mid-week, planned counts only from today.
- Skipped and missed days count in planned, never in done.
- Extra sessions don't count.
- The ring starts over at the Sunday to Monday midnight.

## Stats

All per person. The add-on computes them from the training days and the counted sessions (D47, D48).

| Term | Meaning |
| --- | --- |
| **Counting from** | The local date the first **counted** session ended, set once. Before it is set, every number is 0. It limits only missed and skipped days. |
| **Counted day** | A training day that counts in the stats: every done day, and a missed or skipped day whose date is on or after counting from. Open days count nowhere. A day belongs to its own date, not to the day it closed. |
| **Done** (count) | One per counted day the person took part in (in any counted session for that day), plus one per extra session they took part in. |
| **Extra** (count) | Of done, how many were extra sessions. An extra session is dated by the local date it started. |
| **Missed** (count) | One per counted day that is missed, or done without the person. |
| **Skipped** (count) | One per counted day that is skipped. It stays apart from missed in the data. |
| **Added later** | A counted day dated before the local date the person was added counts only when they did it. So someone added later doesn't start with a pile of misses. People from before stats count from the start. |
| **Time trained** | The sum of the time trained (start to end, minus pauses, in whole seconds) of the person's counted sessions: day sessions and extra sessions. A session ended before one full round adds no time. |
| **Streak** | The number of dates in a row, newest first, on which the person did every counted day. A date with a missed or skipped day for them ends it. Dates with no counted day, open days and extra sessions neither add nor break. All time only. |
| **All time** | Everything above, from the start. |
| **This month** | The same, limited to the add-on's current local month. A day counts in the month of its date. An extra session's done and every session's time count in the month the session started. |

Two rules surprise:

- A day dated 31 October and done on 1 November counts its done in October but its time in November.
- With two programs on one date, doing only one of them breaks the streak.

## The tablet

| Term | Danish UI | Meaning |
| --- | --- | --- |
| **Today card** | Træning i dag | The small card that shows the open training days, with Start and Spring over. Hidden when nothing is open. |
| **Workout tab** | | The dashboard tab with all active programs and the stats. |
| **Workout flow** | | Details → Get ready → Timer → Done, full screen. |
| **Skip** | Spring over | The today card's button that skips a training day. |
| **End** | Slut | Ends the session early. |
| **Music unavailable** | Musik utilgængelig | Shown in the header when the speaker can't be reached. |

## The library

| Term | Meaning |
| --- | --- |
| **Exercise library** | The exercises filtered from `hasaneyldrm/exercises-dataset`. The data is built into the add-on (D30); the GIFs and thumbnails are downloaded (D13). Names and instructions stay in English. |
| **Exercise id** | A library exercise keeps the dataset's id (`0001` …). A custom exercise gets `custom-1`, `custom-2` … in the order added. A station stores the id. |
| **Custom exercise** | An exercise added through Claude, stored apart from the library. It has no media, and its name may not equal any other exercise's name. |

## The change log

| Term | Meaning |
| --- | --- |
| **Change log** | The add-on's record of every successful write: one row each, never changed. A failed write adds none. |
| **Client** | Who made the write: `mcp:<client name>` for MCP, `rest:<User-Agent>` for REST. |
| **Summary** | One English line that says what changed, e.g. "Updated program Onsdag: rounds 5 → 4, stations". |
