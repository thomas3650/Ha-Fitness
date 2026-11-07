# The timer's time-left band, the music volume slider and clearer countdown beeps

**Status:** Thomas handed the spec approval, the plan, the build, the merge and the release to Claude (chat,
2026-11-07: "you take it to the release is out"). `full-reviewer` still reviews the spec, the plan and the branch until
Ready. Issue #116; also closes #110. One branch, one PR.

**Real Home Assistant:** yes, after the release. The add-on (one new session field) and the integration (the music
volume and the cards) both change, so both release. The release's `fitness` issue says:

- The timer has no Forrige, pause and Næste buttons any more. Tapping the ring pauses and resumes. Skipping and going
  back are still possible through the session services and MCP, but not on the tablet.
- The timer's music player has a volume slider. It sets the session speaker's volume.
- The countdown beeps are longer, higher and louder. **Please check on the kitchen tablet (the Surface) at the next
  workout whether all five beeps before each phase change are heard.** This is the only place the fix can be checked.
- The session view's `totals` has a new field, `marks`. Nothing in the house needs to change for it.

**Builds on:** the workout flow and its timing core (step 5 spec §5.2–§5.4), the sounds (cool-down spec §2.1), the music (music spec §5.3–§5.5), the timeline (cool-down spec §4.2, D71, D72) and the API contract
([`architecture.md`](../../architecture.md)).

## 1. Why

Thomas trained on 2026-11-07, two people, with music on the Sonos and the timer on the kitchen tablet, a Windows
Surface. His comments (house issue 478, and the chat that day):

- **Time left:** the whole workout's time left should be much clearer, and sit by the progress line at the bottom.
- **The countdown beeps:** several of the 5-to-1 beeps were missing, with no pattern he could see. The long beep was
  always heard.
- **The music volume:** he wanted to turn the music up and down during the workout, and couldn't.
- **The layout:** the brainstorm settled a new timer layout (§4), from the mockup
  [`TimerBand`](../../mockups/TimerBand.png).

**What is known about the beeps.** #110 logged every oscillator in the fast loop: all five countdown beeps were
scheduled and played, and none was cancelled. The session data gives the card everything it needs to plan them. The
long beep is planned by the same code at the same volume, and it is always heard. What differs is the tone: the
countdown beep is 0.12 s at 880 Hz, and the long beep is 1.5 s at 1320 Hz. So the likely causes are on the tablet: a
short, low, quiet tone can be lost to the Surface's audio processing, to the audio device waking from idle, or under
the music from the Sonos. The data structure is not the cause.

## 2. Goals

### 2.1 The countdown beeps

1. **Longer, higher, louder.** The countdown beep (`beep` in `cards/src/audio.ts`) becomes **0.25 s at 1047 Hz**
   (today 0.12 s at 880 Hz). It stays clearly lower and shorter than the long beep (1320 Hz, 1.5 s). *Claude's call.*
2. **Louder overall.** The tones' volume (`VOLUME`) goes from 0.3 to **0.6**, for every tone. The tones don't overlap,
   so nothing clips. *Claude's call.*
3. **Keep the audio device awake.** While a session runs (get ready and the timer, not paused), the page plays a
   continuous tone too quiet to hear (gain about 0.0005, a low frequency). Windows audio drivers, the Surface's
   included, can power the output down after a moment of silence and lose the start of the next short sound. The long
   beep always follows other sound, which fits this cause. It stops when the session pauses, ends or the flow closes.
   *Claude's call.*
4. **The schedule doesn't change.** The quiet windows stay (1.6 s after a long beep, 0.3 s in the countdown), as do
   the five beeps at 5 to 1 s left, the long beep at a phase change and the chime at the end.
5. **How it is checked.** Locally: the tone tests (kind, frequency, length, volume, the keep-alive starting and
   stopping) and one listen in the fast loop. Whether the beeps are heard on the Surface can only be checked there,
   after the release. The house issue asks for it (above). If they are still missed, #110 stays the place for it: it
   is closed by this PR and reopened on a report.

### 2.2 The music volume

1. **A slider in the timer's music player,** after pause and next track, with a speaker icon in front. It shows the
   session speaker's volume, 0–100.
2. **It sets the volume of the session's speaker** (one speaker for the room, however many people train). Nothing
   else changes: not the program's start volume, not the workout.
3. **No slider without volume.** The slider shows only when the speaker reports a volume and supports `VOLUME_SET`.
   Otherwise the player looks as today.
4. **While dragging,** the card sends the level at most every 300 ms, and once more on release. A music state that
   arrives while the thumb is held doesn't move the thumb. After release, the slider follows the speaker again.
   *Claude's call.*
5. **The end-of-session fade** starts from the speaker's level at that moment, which may be the level the slider set.
   It sets that level back after its last step, as today. The fade already reads the level when it begins (music spec
   §5.3); a test pins it.
6. **A failed set** shows the player's error, as a failed pause or next track does today.

### 2.3 The timer layout

The layout of the mockup [`TimerBand`](../../mockups/TimerBand.png) ([HTML](../../mockups/TimerBand.html)), in HA's
light theme, Danish on the tablet:

1. **No buttons under the ring.** Forrige, pause/resume and Næste go. **Tapping the ring pauses and resumes**, as it
   already does. While running, the ring's caption has a second line, a pause icon with "tryk for pause". While
   paused, it keeps today's "tryk på ringen for at fortsætte". The ring is a button whose accessible name says what a
   tap does (pause, or resume).
2. **The ring is bigger and centred** vertically between the top and the bottom of the participant cards.
3. **The interval pill** sits under the ring, its bottom in line with the cards' bottom. It is bigger: the label in
   normal text and the numbers ("3 / 5") large, in the numbers' font. One person: the station pill, the same way. In
   the cool-down, the cool-down pill ("Udstrækning 2 / 4") takes this place, the same way.
4. **The round pill goes.** The rounds show in the band (5).
5. **The time-left band** replaces the thin progress line at the bottom, across the full width of the content:
   - A thick band (about 44 px on the tablet), rounded at the ends.
   - Its fill is the share of the workout done, as today's line (elapsed active seconds over `totals.planned`), in the
     phase's colour, as today (blue while paused).
   - **Split into rounds:** a thin gap in the band where each round after the first starts, and where the cool-down
     starts, at its real place (`totals.marks`, §3). With an add-on that doesn't send `marks`, the band has no gaps.
   - **On the left, inside the fill:** the trained time (m:ss). When the fill is too narrow to hold it, it shows on the
     grey part instead, in dark text. *Claude's call.*
   - **On the right:** the time left, large (m:ss, in the numbers' font), then "tilbage" / "left". The time left is
     `planned` minus the elapsed active seconds, never below 0:00.
   - It keeps the `progressbar` role, with a text value that says the time left.
6. **The top row** keeps the music player, PAUSET while paused, Skip cool-down and Slut. The small "0:01 / 28:45"
   goes; the band has it.
7. **Spacing:** the cards and the ring start right under the top row, and the band sits right under them, on one grid
   (no fixed offsets). The cards and the ring column share the same top and bottom.
8. **Portrait** (about 800 px wide) keeps today's stacking, with the same changes: no buttons, the band at the bottom,
   the bigger pill.

### 2.4 What stays

- The `next` and `previous` session commands stay in the add-on, the integration's services and MCP. The cards keep
  `playSkipTone`, so a skip from elsewhere still plays the long beep.
- Get ready, done, the details step, the today and stats cards: unchanged.
- The one- and two-person timers are the layouts the cards have. Nothing new for three or four.

## 3. The add-on: `totals.marks`

The band needs to know where each round starts, in the same unit as `time_trained` and `totals.planned`.

- **The field:** `SessionView.totals.marks: list[int]`, in the session view of `GET /api/v1/session` and the push
  channel.
- **What a mark is:** a number of seconds into `planned` (the timeline's work, switch and rest seconds, the countdown
  left out). There is one mark where each round after the first starts, and one where the cool-down starts. The marks
  come in order. A program with one round and no cool-down has none.
- **Where a round starts:** at its first work. The rest between rounds belongs to the round before it (its timeline
  entry carries that round, D71). The rest after the last round, before the cool-down, belongs to the last round. So
  the cool-down's mark is at its first stretch.
- **How:** from the session's frozen timeline (`timeline.py`, D71), summing the durations of the entries before each
  mark, the countdown left out. It is computed where `_totals` is today.
- **The contract:** an additive field. `api_version` stays 1 (as with D72). An older add-on leaves it out; the cards
  then draw a band without gaps. The integration passes the view through unchanged.
- **A known gap:** the fill follows the active seconds, and the marks follow the plan. After a skip (`next` from a
  service), the fill can be ahead of or behind the round it is in. That is the same as today's line, and good enough.

## 4. The integration: the volume

- **The music state** (`music_state`, music spec §5.4) gets `volume: int | null`: the session speaker's
  `volume_level` × 100, rounded, or null when the speaker has no level or no `VOLUME_SET`. It is sent on every
  speaker change, as the other fields are today (`_handle_speaker_change`).
- **The `ha_fitness/music` command** gets an action `volume`, with a required `level`, an integer 0–100, only with
  that action. It calls `media_player.volume_set` on the session speaker with `level / 100`. The errors are those of
  the other actions: `not_found` without an active session with music, `unavailable` when the speaker can't take it
  or the call fails. A speaker without `VOLUME_SET` is `unavailable`. The action doesn't change the program's music
  settings.
- **During a fade** (the session has ended), a `volume` is `not_found`, as the session is no longer active.
- The cards' `MusicState` type gets `volume?: number | null`. An integration without it means no slider.

## 5. Texts

New keys in `en.json` and `da.json` (the builder picks the key names):

| Use | English | Danish |
| --- | --- | --- |
| The ring's caption while running | tap to pause | tryk for pause |
| After the band's time left | left | tilbage |
| The band's text value | {time} left of the workout | {time} tilbage af træningen |
| The slider's label | Music volume | Musikkens lydstyrke |
| The ring's name while running / paused | Pause / Resume | Pause / Fortsæt |

Keys no longer used go: the buttons' labels, if nothing else uses them, and the round pill's.

## 6. Decisions

- **D73: The timer has no transport buttons.** Tapping the ring pauses and resumes. Skipping and going back aren't on
  the tablet; they stay in the services and MCP. Why: Thomas wanted a calmer screen and doesn't use them.
- **D74: `totals.marks`.** The session view's totals carry where each round after the first and the cool-down start,
  in seconds into `planned`. Additive; `api_version` stays 1. Why: the band shows the rounds at their real places,
  which only the timeline knows.

## 7. Docs

- `docs/mockups/README.md`: a row for `TimerBand` (the timer from 2026-11, which replaces the controls and the progress
  line of `Timer` and `TimerDuo`).
- `docs/architecture.md`: `totals.marks` in the session view; the `volume` action and field in the music contract.
- `docs/domain-language.md`: if it names the progress line or the controls, the band and the ring tap.
- `docs/decisions.md`: D73, D74.

## 8. Testing

- **Cards (Vitest, behaviour through rendered text and roles):** no Forrige/Næste/pause buttons; the ring tap pauses
  and resumes; the ring's names and captions; the band's time left and trained time with a frozen clock; the gaps
  from `marks` (as many as marks; none without the field); the slider shows only with a `volume`, sends throttled
  levels and one on release, ignores state while held; the tone shapes and volume; the keep-alive starts while
  running and stops on pause, end and close. The tests for the removed buttons go; the skip-tone tests stay.
- **Add-on (pytest):** `marks` for: one round and no cool-down (none), several rounds with and without a round rest,
  a round rest of 0, a cool-down with and without the rest before it, and no countdown.
- **Integration (pytest):** the music state's `volume` (with a level; null without `VOLUME_SET`; null without a
  level); the `volume` action (sets the level; `not_found`; `unavailable` without `VOLUME_SET` and on a failed call;
  `level` required and 0–100); the fade starting from a level the slider set and setting it back.
- **The fast loop and the Chrome check** at 1368×912 in Danish, with the fake Music Assistant: two people in work, a
  rest, paused and the cool-down; one person; the slider moving the fake speaker's volume; a portrait check at about
  800 px wide. One listen to the new beeps.

## 9. Left to the builder

- The keep-alive's exact frequency and gain, within "inaudible".
- The band's exact height and the gap width, at the mockup's proportions.
- The names of the new keys and the CSS.
- How the slider is built (a native range input styled, or HA's slider), as long as it is touch-friendly.
