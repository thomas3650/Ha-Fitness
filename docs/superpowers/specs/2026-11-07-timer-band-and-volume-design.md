# The timer's time-left band, the music volume slider and clearer countdown beeps

**Status:** Thomas handed the spec approval, the plan, the build, the merge and the release to Claude (chat,
2026-11-07: "you take it to the release is out"). `full-reviewer` still reviews the spec, the plan and the branch until
Ready. Issue #116; also closes #110. One branch, one PR, titled `feat: …` so both components release.

**Real Home Assistant:** yes, after the release. The add-on (one new session field) and the integration (the music
volume and the cards) both change, so both release. The release's `fitness` issue says:

- The timer has no Forrige, pause and Næste buttons any more. Tapping the ring pauses and resumes. Skipping a phase
  and going back are no longer possible during a workout. Thomas chose that (chat, 2026-11-07).
- The timer's music player has a volume slider. It sets the session speaker's volume.
- The countdown beeps are longer, higher and louder. **Please check on the kitchen tablet (the Surface) at the next
  workout whether all five beeps before each phase change are heard.** This is the only place the fix can be checked.
- The session view's `totals` has a new field, `marks`. Nothing in the house needs to change for it.

**Builds on:** the workout flow and its timing core (step 5 spec §5.2–§5.4), the sounds (cool-down spec §2.1), the
ring (UI refresh spec §2.5), the music (music spec §5.3–§5.5), the timeline (cool-down spec §4.2, D71, D72), the
colours (D52) and the API contract ([`architecture.md`](../../architecture.md)).

## 1. Why

Thomas trained on 2026-11-07, two people, with music on the Sonos and the timer on the kitchen tablet, a Windows
Surface. His comments (house issue 478, and the chat that day):

- **Time left:** the whole workout's time left should be much clearer, and sit by the progress line at the bottom.
- **The countdown beeps:** several of the 5-to-1 beeps were missing, with no pattern he could see. The long beep was
  always heard.
- **The music volume:** he wanted to turn the music up and down during the workout, and couldn't.
- **The layout:** the brainstorm settled a new timer layout (§2.3), from the mockup
  [`TimerBand`](../../mockups/TimerBand.png).

**What is known about the beeps.** #110 logged every oscillator in the fast loop: all five countdown beeps were
scheduled and played, and none was cancelled. The session data gives the card everything it needs to plan them. The
long beep is planned by the same code at the same volume, and it is always heard. What differs is the tone: the
countdown beep is 0.12 s at 880 Hz, and the long beep is 1.5 s at 1320 Hz. So the likely cause is on the tablet: a
short, low, quiet tone can be lost to the Surface's audio processing or under the music from the Sonos. The data
structure is not the cause.

## 2. Goals

### 2.1 The countdown beeps

1. **Longer and higher.** The countdown beep (`beep` in `cards/src/audio.ts`) becomes **0.25 s at 1175 Hz** (today
   0.12 s at 880 Hz). That is not a note of the chime (659, 784, 1047 Hz), and stays clearly lower and shorter than
   the long beep (1320 Hz, 1.5 s). *Claude's call.*
2. **Louder.** The tones' volume (`VOLUME`) goes from 0.3 to **0.5**, for every tone. Two tones rarely overlap (a tone
   already playing is never cancelled, so a long beep from a re-plan can meet a beep); at 0.5 the sum stays at 1.0.
   *Claude's call.*
3. **Keep the audio device awake (a guess).** While a session runs (get ready and the timer, not paused) and sound is
   unlocked, the page plays a continuous tone too quiet to hear. Some Windows audio drivers power the output down after
   silence and lose the start of the next short sound. The evidence for it is thin, but it is cheap. Not below 100 Hz,
   which tablet audio processing may filter out; the gain at most 0.001. It starts when the session runs or when "Tryk
   for lyd" unlocks sound mid-session, and stops when the session pauses, ends, or the flow closes. It is its own
   audio node, separate from the tones, so the tones' tests and their counts don't see it. *Claude's call.*
4. **The schedule doesn't change.** The quiet windows stay (1.6 s after a long beep, 0.3 s in the countdown), as do
   the five beeps at 5 to 1 s left, the long beep at a phase change and the chime at the end.
5. **How it is checked.** Locally: the tone tests (kind, frequency, length, volume, the keep-alive starting and
   stopping) and one listen in the fast loop. The test audio fake (`cards/test/fake-audio.ts`) learns to record the
   gain and to report the keep-alive apart from the tones. Whether the beeps are heard on the Surface can only be
   checked there, after the release; the house issue asks for it. If they are still missed, #110 is reopened.

### 2.2 The music volume

1. **A slider in the timer's music player,** after pause and next track, with a speaker icon in front. It shows the
   session speaker's volume, 0–100. The player grows to hold it (today it is at most 400 px wide; the mockup's is about
   640 px on the tablet).
2. **It sets the volume of the session's speaker,** one speaker for the room, however many people train. It doesn't
   change the program or the workout. A (re)start of the music (the music spec's start, a Play or a resume after a
   failure, the speaker coming back) sets the program's start volume again, as today; the slider then shows that.
3. **When it shows:** only when the music state has a `volume` (§4). Otherwise the player looks as today.
4. **When it can be used:** while the music state is `playing` or `paused`. It is disabled while `waiting` and
   `unavailable`, as next track is.
5. **While dragging,** the card sends the level at most every 300 ms, and once more on release. A music state that
   arrives while the thumb is held doesn't move the thumb. After release, the slider follows the speaker again.
   *Claude's call.*
6. **A failed set shows nothing,** as a failed pause or next track today: the slider follows the next music state.
7. **The end-of-session fade** starts from the speaker's level at that moment, which may be the level the slider set,
   and sets that level back after its last step. The fade already reads the level when it begins (music spec §5.3); a
   test pins it.

### 2.3 The timer layout

The layout of the mockup [`TimerBand`](../../mockups/TimerBand.png) ([HTML](../../mockups/TimerBand.html)), in HA's
light theme, Danish on the tablet:

1. **No buttons under the ring.** Forrige, pause/resume and Næste go.
2. **Tapping the ring pauses and resumes**, as it already does.
   - The ring keeps its `progressbar` (the phase's seconds, named after the phase word, UI refresh spec §2.5).
   - A **button laid over the ring**, the ring's size, transparent, makes the tap. It is in the tab order, and is named
     "Pause" while running and "Fortsæt" while paused. The progressbar stays outside the button, so it keeps its role.
     This reverses the UI refresh spec's "no button role and no tab stop" for the timer's ring (D73).
   - Get ready's ring (same `ring()`, no tap) stays a plain progressbar.
   - While running, the ring's caption has a second line: a pause icon with "tryk for pause". While paused, it keeps
     today's "tryk på ringen for at fortsætte".
3. **The ring is bigger and centred** vertically between the top and the bottom of the participant cards.
4. **The interval pill** sits under the ring, its bottom in line with the cards' bottom. It is bigger: the label in
   normal text and the numbers ("3 / 5") large, in the numbers' font. One person: the station pill, the same way. In
   the cool-down, the cool-down pill ("Udstrækning 2 / 4") moves here from above the ring, the same way.
5. **The round pill goes.** The rounds show in the band (6).
6. **The time-left band** replaces the thin progress line at the bottom, across the full width of the content:
   - A thick band (about 44 px on the tablet), rounded at the ends.
   - Its fill is the share of the workout done, as today's line (elapsed active seconds over `totals.planned`), in the
     phase's colour, as today (blue while paused).
   - **Split into rounds:** a thin gap in the band where each round after the first starts, and where the cool-down
     starts, at its real place (`totals.marks`, §3). Without `marks` (an older add-on) the band has no gaps.
   - **On the left:** the trained time (m:ss). **On the right:** the time left, large (m:ss, in the numbers' font), then
     "tilbage" / "left". The time left is `planned` minus the elapsed active seconds, never below 0:00.
   - **Both texts are dark** (the theme's primary text colour), on the fill and on the grey alike, so they keep D52's
     4.5:1 contrast on the work orange and the rest blue. The mockup's white trained time is not followed.
     *Claude's call.*
   - It keeps the `progressbar` role, with a text value that says the time left.
7. **The top row** keeps the music player, PAUSET while paused, Skip cool-down and Slut. The small "0:01 / 28:45"
   goes; the band has it. Skip cool-down and Slut stay on the right (today the elapsed time's `margin-left: auto` does
   that; something else must).
8. **The banners** (unreachable, "Tryk for lyd", an error) go in a row between the top row and the cards. The row takes
   no height when nothing shows.
9. **Spacing:** the cards and the ring start right under the top row (or the banners), and the band sits right under
   them, on one grid with no fixed offsets. The cards and the ring column share the same top and bottom.
10. **Portrait** (about 800 px wide) keeps today's stacking, with the same changes: no buttons, the band at the
    bottom, the bigger pill.

### 2.4 What stays

- The `next` and `previous` session commands stay in the add-on (REST) and the integration's websocket command. No
  service or MCP tool offers them, and none is added. Get ready's "Start nu" still sends `next`, so the cards keep
  `playSkipTone`.
- Get ready, done, the details step, the today and stats cards: unchanged.
- The one- and two-person timers are the layouts the cards have. Nothing new for three or four.

## 3. The add-on: `totals.marks`

The band needs to know where each round starts, in the same unit as `time_trained` and `totals.planned`.

- **The field:** `SessionTotals.marks: list[int]`. It is in every view built from `_totals`: the current session
  (`GET /api/v1/session`, the push channel, MCP `get_session`) and the finished ones (`GET /api/v1/sessions`, MCP
  `list_sessions`).
- **What a mark is:** a number of seconds into `planned` (the timeline's work, switch and rest seconds, the countdown
  left out). There is one mark where each round after the first starts, and one where the cool-down starts. The marks
  come in order. A program with one round and no cool-down has none.
- **Where a round starts:** at its first work. The rest between rounds belongs to the round before it (its timeline
  entry carries that round). The rest after the last round, before the cool-down, belongs to the last round. So the
  cool-down's mark is at its first stretch.
- **How:** from the session's frozen timeline (`timeline.py`, D71), summing the durations of the entries before each
  mark, the countdown left out. It is computed in `_totals`.
- **The units line up:** `started_at` is set at the first work, so mark 0 and trained time 0 are the same moment.
- **The contract:** an additive field. `api_version` stays 1 (as with D72). An older add-on leaves it out; the cards
  then draw a band without gaps. The integration passes the view through unchanged. The cards' `SessionView.totals`
  type gets `marks?: number[]`.
- **A known gap:** the fill follows the active seconds and the marks follow the plan. After a `next` or `previous`
  through REST, the fill can be off from the round it is in. That is the same as today's line, and good enough.

## 4. The integration: the volume

- **The music state** (`music_state`, music spec §5.4) gets `volume: int | null`: the session speaker's
  `volume_level` × 100, rounded, or null when the speaker has no level or no `VOLUME_SET`. It is sent on every
  speaker change, as the other fields are today (`_handle_speaker_change`).
- **The `ha_fitness/music` command** gets an action `volume`, with a `level`, an integer 0–100. It calls
  `media_player.volume_set` on the session speaker with `level / 100`.
- **Its refusals:**
  - A `volume` without `level`, a `level` that isn't an integer 0–100 (a boolean
    is refused too), or a `level` with another action: HA's
    `invalid_format`, from the command's schema.
  - No active session with music: `not_found`, as for the other actions. That includes a fade after the session ended.
  - A speaker without `VOLUME_SET`, or a failed call: `unavailable`, as for the other actions.
- The action doesn't change the program's music settings.
- The cards' `MusicState` type gets `volume?: number | null`. An integration without it means no slider.

## 5. Texts

In `en.json` and `da.json`:

| Use | Key | English | Danish |
| --- | --- | --- | --- |
| The ring button's name, running / paused | `flow.pause` / `flow.resume` (exist) | Pause / Resume | Pause / Fortsæt |
| The ring's caption while running | new | tap to pause | tryk for pause |
| After the band's time left | new | left | tilbage |
| The band's text value | new | {time} left of the workout | {time} tilbage af træningen |
| The slider's label | new | Music volume | Musikkens lydstyrke |

The builder names the new keys. `flow.previous`, `flow.next` and `flow.round_label` go, if nothing else uses them.
`flow.pause` and `flow.resume` stay (get ready uses `flow.resume`).

## 6. Decisions

- **D73: The timer has no transport buttons; the ring is the pause control.** Tapping the ring pauses and resumes, and
  the ring has an accessible button for it, in the tab order. This reverses the UI refresh spec §2.5's "no button
  role and no tab stop" for the timer's ring. Skipping and going back are not offered during a workout. Why: Thomas
  wanted a calmer screen and doesn't need them (chat, 2026-11-07).
- **D74: `totals.marks`.** A session's totals carry where each round after the first and the cool-down start, in
  seconds into `planned`. Additive; `api_version` stays 1. Why: the band shows the rounds at their real places, which
  only the timeline knows.

## 7. Docs

- `docs/mockups/README.md`: a row for `TimerBand` (done with this spec).
- `docs/architecture.md`: `totals.marks` in the session view; the `volume` action and field in the music contract.
- `docs/testing.md`: the workout-flow Chrome check (the ring tap pauses and resumes instead of the play button; the
  band) and the music steps (the slider; the fake's speaker without `VOLUME_SET` shows none).
- `docs/decisions.md`: D73, D74.

## 8. Testing

- **Cards (Vitest, behaviour through rendered text and roles):**
  - No Forrige, Næste or pause buttons; the ring button pauses and resumes, with its names; the ring's progressbar
    still found by the phase name; get ready's ring has no button.
  - The band: the trained time and the time left with a frozen clock, never below 0:00; its text value; as many gaps
    as marks, none without the field.
  - The slider: shown only with a `volume`; disabled while `waiting` and `unavailable`; sends throttled levels and one
    on release; ignores a state while held; follows the state after release; a refused set shows nothing.
  - The tones: the beep's frequency and length, the volume; the keep-alive starts while running (and on a mid-session
    unlock) and stops on pause, end and close, and isn't counted as a tone.
  - The tests for the removed buttons go; the skip-tone tests stay.
- **Add-on (pytest):** `marks` for one round and no cool-down (none); several rounds with a round rest; several rounds
  with no round rest (0); one station; a cool-down with and without the rest before it; no countdown. The existing
  exact `totals` asserts get `marks`.
- **Integration (pytest):** the music state's `volume` (with a level; null without `VOLUME_SET`; null without a level);
  the `volume` action (sets the level; `invalid_format` for the three bad inputs and a
  boolean `level`; `not_found`; `unavailable` without
  `VOLUME_SET` and on a failed call); the fade starting from a level the action set and setting it back.
- **The fast loop and the Chrome check** at 1368×912 in Danish, with the fake Music Assistant: two people in work, a
  rest, paused and the cool-down (the cool-down pill under the ring); one person; the slider moving the fake
  speaker's volume; the fake's speaker without `VOLUME_SET` (no slider); a portrait check at about 800 px wide. One
  listen to the new beeps.

## 9. Left to the builder

- The keep-alive's exact frequency and gain, within §2.1.3.
- The band's exact height and the gap width, at the mockup's proportions.
- The names of the new keys and the CSS.
- How the slider is built (a styled native range input, or HA's slider), as long as it is touch-friendly.
