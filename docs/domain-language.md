# Domain language

The words used in specs, code and UI. Use them as defined here. The rules behind them (when a day turns late, how a
streak is counted) are in spec §3 ([design spec](superpowers/specs/2026-10-23-ha-fitness-design.md)); feature specs
fix the exact entity, service and tool names. Danish UI words live in the language files; the ones below are those the
spec already names.

## Programs

| Term | Meaning |
| --- | --- |
| **Program** | A named circuit with its exercises, its training days (weekdays), and its playlist and speaker. Several programs can be active at once. |
| **Active** | A program that repeats on its training days. An inactive program creates no training days. |
| **Circuit** | The only workout type in v1: S stations, R rounds, work time, switch time, rest between rounds. |
| **Station** | One exercise in the circuit (1–15). Each participant is at one station per interval. |
| **Round** | One pass through all stations: S intervals. |
| **Interval** | One work period at a station, followed by the switch time. |
| **Work time** (W) | Seconds of work per interval. |
| **Switch time** (r) | Seconds to move to the next station after an interval. |
| **Rest between rounds** | Seconds of rest after a round, except the last. |
| **Countdown** | Seconds before the first interval (0, 5 or 10). |
| **Phase** | A stretch of the timer: countdown, work, switch or rest. |

## People and sessions

| Term | Meaning |
| --- | --- |
| **Person** | Someone who trains, linked to an HA person entity. |
| **Participant** | A person taking part in one session (1 or 2, at most the number of stations). Participant 1 starts at station 1, participant 2 at station 2. |
| **Session** | One run of a program's workout, from start to done or ended early. |
| **Extra session** | A session started when nothing is due, or from the workout tab. It counts toward done and time trained, not toward the streak, and closes no training day. |
| **Ended early** | A session stopped before the last round. It counts as done if at least one full round was completed. |

## Training days

| Term | Danish UI | Meaning |
| --- | --- | --- |
| **Training day** | | One program on one of its weekdays (one local date). Created at 00:00 HA time, and also during the day when a program is created, switched on, or gets today's weekday (D34). |
| **Due** | | Today's training day, not done yet. |
| **Late** | Forfalden | A due day that has passed untouched. It stays visible until the next training day of any program begins. |
| **Missed** | | A late day closed because the next training day began. |
| **Skipped** | | A training day closed on purpose with Spring over (one confirmation, no reason). |
| **Done** | | A training day closed by a session (done late, if it was late). |
| **Open** | | Due or late. |
| **Closed** | | Done, missed or skipped. |

## Stats

| Term | Meaning |
| --- | --- |
| **Streak** | Per person: consecutive closed training days the person did. Missed and skipped break it; open days don't count. |
| **Done** / **missed** (counts) | Per person, per closed training day: done if they took part, otherwise missed (or skipped). |
| **Time trained** | Per person: time from a session's start to its end, minus pauses. |
| **Counting from** | The date of the first session completed in the app. Days closed before it are left out of all stats. |

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
