# Step 7: Music – design

- **Date:** 2026-10-24 · **Status:** direction from Thomas in chat (about 23:30: "try your best with the music … use a
  fake for the first go"). Under his delegation for the night, Claude approves this spec after `full-reviewer` rates it
  Ready, and merges. Thomas tests it on 2026-10-25. "Claude's call" marks choices made without him; he may overrule them.
- **Implements:** [design spec](2026-10-23-ha-fitness-design.md) §10 step 7, with:
  - §3.1, a program's playlist and speaker;
  - §3.4, the speaker choice on the details step and the music in the header;
  - §3.5, the music itself;
  - §3.7, listing the playlists and speakers over MCP.
- **Builds on:**
  - [step 3](2026-10-24-programs-through-chat-design.md), the program's `music` field;
  - [step 5](2026-10-24-the-workout-design.md), sessions and the workout flow;
  - the [UI refresh](2026-10-24-ui-refresh-design.md) and [UI polish](2026-10-24-ui-polish-design.md), the screens as
    they are now.
- **Issue:** #7.
- **Needs an update on the real Home Assistant:** yes, both parts.
  - Music Assistant must run there.
  - Each program needs its music set through Claude (§9).
- **Contract:** `api_version` stays 1. This step only adds to the contract.

## 1. Goal

A workout plays the program's playlist on a speaker (design §3.5):

- On the details step, a dropdown picks the speaker. It defaults to the program's speaker.
- The music starts when the first work phase starts.
- It pauses and resumes with the workout.
- When the workout completes or ends, it fades out over about 5 s.
- If the speaker is unavailable, the workout still runs and the header says "Musik utilgængelig".
- Without Music Assistant, the music UI is hidden.
- Claude can list the speakers and the playlists, so it can set a program's music.
- The timer's header has a small music player, as in the `Timer` mockup: the playlist, the speaker, and Pause / Play
  and Next buttons.

**There is no Music Assistant on the dev machine.** A fake Music Assistant, a dev-only custom integration (§7), stands in
for it in the fast loop and the full loop. The real one is first met on the house, in Thomas's test.

## 2. What ships, in two PRs

Each PR releases one component (D29). Merge order 1 → 2, and on the house the add-on is installed first (D37). PR 2
also works against an older add-on, without music (§5.6).

1. **`feat: music in the add-on`.** It touches `addon/`, `scripts/` and `docs/`.
   - A session start (`POST /api/v1/session`) takes an optional `speaker`.
   - The session's frozen plan keeps the music, and the view shows it.
   - It adds `list_speakers` and `list_playlists` over MCP and REST, read from HA, and the `GET /api/v1/music` route
     for the probe.
   - It adds the fake Music Assistant and the seed's music (§7).
   - It adds D55.
2. **`feat: music on the tablet`.** It touches `custom_components/`, `cards/`, `tests/` and `docs/`.
   - The integration plays, pauses, resumes and fades the music, following the session.
   - It adds the ws commands `ha_fitness/speakers` and `ha_fitness/music`, and `speaker` in
     `ha_fitness/session/command`.
   - The session subscription gets the music state.
   - `ha_fitness/programs` gets each program's music.
   - The cards get the music row with the speaker dropdown on details, and the header's music player.
   - It adds D53 and D54.

## 3. Facts about Music Assistant

These come from Home Assistant core's `music_assistant` integration and HA's REST API, in the version the repo pins.
They go into `docs/ha-notes.md` with PR 1. The fake (§7) copies them.

- **Players:** Music Assistant's players are `media_player` entities of the `music_assistant` platform. The integration
  also creates button, number, select, switch and text entities, so the `media_player.` filter matters.
- **`mass_player_type`:** while a player is available, its state has the attribute `mass_player_type`. An unavailable
  entity has no extra attributes, so it is missing then. So a speaker isn't found through the attribute.
- **`integration_entities('music_assistant')`** (a template function):
  - It answers the registry entries of a config entry whose **title** is the argument.
  - Otherwise it falls back to `entity_sources`: the entities loaded on the platform, unavailable ones included.
  - Music Assistant's entry is titled "Music Assistant", so the fallback applies: loaded players, not disabled ones.
- **`config_entry_id('<entity>')`** (a template function) reads the entity registry. So an entity needs a unique id to
  have one.
- **Volume and shuffle:** `VOLUME_SET` is supported only when the player can set its volume. `SHUFFLE_SET` is always
  supported. But setting shuffle returns silently when the player has no active queue yet.
- **`music_assistant.play_media`:** an entity service on Music Assistant's players.
  - It takes `media_id`, required (a string or a list).
  - It takes `media_type` (`playlist`, …).
  - It takes `enqueue` (`play`, `replace`, `next`, `replace_next`, `add`).
  - It also takes `artist`, `album`, `radio_mode` and `username`.
- **`music_assistant.get_library`:** it supports a response only.
  - It needs `config_entry_id` and `media_type`, both required.
  - It also takes `favorite`, `search`, `limit` (default 25; no maximum in the schema; `services.yaml` caps the UI at
    500), `offset` and `order_by`.
  - The response is `{items: [{media_type, uri, name, version, image, favorite, explicit}], limit, offset, order_by,
    media_type}`.
- **HA's REST API:**
  - `POST /api/services/<domain>/<service>?return_response` answers `{"changed_states": [...], "service_response":
    {...}}`.
  - `POST /api/template` renders a template and answers plain text. It needs an admin user. The Supervisor's HA user is
    in the admin group, so the add-on's proxy token should pass. PR 1's first task checks it (§4.3).

## 4. The add-on (PR 1)

### 4.1 A program's music

The `music` field exists since step 3: `{playlist, speaker, volume, shuffle}` or null (step 3 spec §5.1). This step
adds one optional key:

- **`playlist_name`:** a string of 1–200 characters, or null (the default).
  - It is the name to show. `playlist` stays the URI or name that is played.
  - Claude fills it from `list_playlists`. Without it, the screens show `playlist`.
  - This is Claude's call, because a URI such as `library://playlist/12` means nothing on the tablet.

The other rules stay. `music` is still not checked against HA when it is written, since Music Assistant may be offline
while Claude edits a program.

- **MCP:** the program rules shown to Claude (`_PROGRAM_RULES` in `mcp_tools.py`) mention `playlist_name`, and point to
  `list_speakers` and `list_playlists`.
- **Without music:** the program has `music: null`, plays nothing, and its screens show no music UI.
- **Storage:** no migration is needed. Program documents are JSON, and `playlist_name` defaults to null when read. A
  test reads a stored document without the key.

### 4.2 Sessions

- `POST /api/v1/session` takes an optional `speaker`.
  - It must match `Music.speaker`'s pattern (`^media_player\.[a-z0-9_]+$`); otherwise the answer is 422 `invalid`.
  - It overrides the program's speaker for this session.
- At the start, the plan freezes `music`:
  - the program's music, with the speaker replaced by `speaker` when one is given;
  - or null when the program has no music.
- **Claude's call:** a `speaker` for a program without music is ignored.
- The session view gets `music: {playlist, playlist_name, speaker, volume, shuffle} | null`, from the plan. A finished
  session in history keeps it.
- **Storage:** no migration is needed.
  - The plan is a JSON column, and `Plan` allows unknown keys.
  - `Plan.music` defaults to null, so a session stored before this step reads as `music: null`.
  - A test reads such a plan.

### 4.3 Speakers and playlists for Claude

Both are read-only and read HA through the add-on's HA client (the Supervisor's proxy, or the dev token). Each has one
service function, shared by the MCP tool and the REST route.

- **The template:** one template, rendered through `POST /api/template`.
  - It lists the `media_player.` entities in `integration_entities('music_assistant')`.
  - For each, it gives the friendly name, the state and `config_entry_id()`, as JSON.
  - The plan writes its text.
- **`list_speakers`** (MCP), `GET /api/v1/music/speakers` (REST):
  - It answers `[{entity_id, name, available}]`, sorted by name.
  - `available` is false when the state is `unavailable` or `unknown`.
- **`list_playlists`** (MCP), `GET /api/v1/music/playlists?search=` (REST):
  - It answers `[{name, uri}]`, sorted by name.
  - It takes the config entry id of the first speaker from the template.
  - It calls `music_assistant.get_library` with `?return_response`, `media_type: playlist`, `limit: 500`, and `search`
    when given. The items come from `service_response.items`.
- **Without speakers:** both answer `[]`. This covers no Music Assistant, and Music Assistant loaded with no players.
- **Errors:** HA unreachable, HA refusing, or a malformed answer from HA all raise the add-on's `Unavailable`, as the
  people routes do.
  - REST answers 503 `{"detail": "<text>"}`.
  - MCP answers a `ToolError` with the text (`api/errors.py`, `mcp_tools.py`).
- **`GET /api/v1/music`** answers `{"speakers": "/api/v1/music/speakers", "playlists": "/api/v1/music/playlists"}`. It
  doesn't call HA. The integration's probe uses it (§5.6).
- **The spike:** PR 1's first task runs the template and the `return_response` call through the Supervisor's proxy, on
  the full loop with the fake installed (§7).
  - If the proxy refuses the template, the controller rules on it before the tools are built.
  - The fallback is `GET /api/states`, keeping the players that carry `mass_player_type`. Unavailable speakers are then
    left out.
  - `list_playlists` then needs a speaker argument. Its config entry comes from the entity registry over HA's
    websocket.
  - The ruling and the change go in the PR.

### 4.4 Docs (PR 1)

- `architecture.md`: the session's music, the routes and tools.
- `domain-language.md`: speaker, playlist and music player.
- `ha-notes.md`: the facts of §3.
- `testing.md`: the fake and how to use it (§7).
- `decisions.md`: D55.

## 5. The integration (PR 2)

### 5.1 Following the session

A music controller (`music.py`) listens to the coordinator's session view. Per session id, it keeps one of these
states:

- **`waiting`:** no start was tried yet, and the session wasn't adopted. `started_at` may be null or set.
- **`started`:** the start (§5.2) succeeded, or the session was adopted.
- **`failed`:** the start failed. The speaker was unavailable, or a call failed.

It acts on these events:

| Event | Condition | Action |
| --- | --- | --- |
| A session with `music` is first seen with `started_at` null | — | it is `waiting` |
| A session with `music` is first seen with `started_at` set, at or after the controller's own start | — | it is `waiting` (then the next row applies) |
| A session with `music` is first seen with `started_at` set, before the controller's own start | — | it is adopted: `started`, with no call |
| A view is running with `started_at` set | `waiting` | the start |
| running → paused | `started` | `media_player.media_pause` |
| paused → running | `started` | `media_player.media_play` |
| paused → running | `failed` | the start |
| The speaker's state becomes available again | `failed`, and the session is running | the start |
| The view becomes `completed` or `ended`, or the session disappears (no view, or another id) | `started` | the fade (§5.3) |

- **Where:** every call goes to the plan's speaker.
- **The start trigger is a running view with `started_at` set, while `waiting`.** That covers:
  - the countdown's end;
  - "Start nu" while running;
  - Resume after "Start nu" while paused (the add-on sets `started_at` then, but the session stays paused);
  - a countdown of 0, first seen already started after the controller's start.
- **Adoption** (first seen started before the controller's own start) covers an HA restart and an entry reload in the
  middle of a workout.
  - Pause, Resume and the fade apply, but no music is started.
  - The music may be playing already, and starting it again would restart the playlist. This is Claude's call.
  - If the music isn't playing, the header's Play button plays it (§5.5).
- **Failed calls after a start** (`media_pause`, `media_play`, `media_next_track`) are logged as warnings. The state
  stays `started`.
- **Annullér during the countdown** started no music, so nothing happens.
- **Pause and Resume** act only after a start or an adoption, never during the countdown.
- **A failed start is retried:**
  - on Resume;
  - when the speaker comes back while the workout runs;
  - on the header's Play.

### 5.2 The start

1. When `volume` is set and the speaker supports `VOLUME_SET`, call `media_player.volume_set` with `volume / 100`.
2. Call `music_assistant.play_media` with `media_id: playlist`, `media_type: playlist` and `enqueue: replace`.
3. Then call `media_player.shuffle_set` with `shuffle`. It comes after `play_media`, because `replace` makes a new
   queue. Whether it takes on the real Music Assistant goes on the house test list (§9).

- A start on a speaker that is `unavailable` or `unknown`, or that isn't a Music Assistant player, isn't tried. The
  session goes to `failed`.
- A call that raises goes to `failed`, logged as a warning.

### 5.3 The fade

- **When the speaker isn't playing** (for example the workout ended while paused), there is no fade and no pause.
- **Otherwise:**
  1. It lowers the volume over 5 s, in 10 steps, from the speaker's `volume_level` down to 0, with
     `media_player.volume_set`. The steps are paced by time, every 0.5 s from the fade's start, not one after another,
     so slow calls don't stretch the fade.
  2. Then it calls `media_player.media_pause`.
  3. Then it sets the volume back to the starting level, so the next playback isn't silent.
- Without `VOLUME_SET`, or without a `volume_level`, the fade is only the pause.
- A start on the same speaker during a fade cancels the fade and sets the starting volume back first. Then the start
  runs.
- A fade on another speaker runs on.
- **Unloading the integration** cancels running fades. For each, it calls `media_player.media_pause`, then sets the
  starting volume back.
- A fade isn't started twice for one session.

### 5.4 The music state

The session subscription (`ha_fitness/session/subscribe`) gets a third key: `{available, session, music}`.

- **`music`:** `{playlist_name, speaker, speaker_name, state} | null`.
  - `playlist_name` is the plan's `playlist_name`, or its `playlist`.
  - `speaker_name` is the speaker's friendly name, or its entity id.
- **`music` is null when:**
  - there is no active session (running or paused), or the session has no music;
  - Music Assistant isn't loaded: no loaded config entry of `music_assistant`;
  - the add-on doesn't support music (§5.6).
- **`state`** is one of:
  - `waiting`: the controller's state is `waiting`, and the speaker is available;
  - `unavailable`: the speaker's state is `unavailable` or `unknown`, the speaker isn't a Music Assistant player, or
    the controller's state is `failed`;
  - `playing`: otherwise, when the speaker's state is `playing`;
  - `paused`: otherwise, for any other speaker state (paused, idle …).
- **A failure** is logged as a warning. It is never raised to the card, and the workout goes on.
- **When it sends:** the subscription's de-duplication key includes `music`. So it sends when the speaker's state or
  the controller's state changes.

### 5.5 Commands for the cards

- **`ha_fitness/speakers`** answers `{speakers: [{entity_id, name, available}]}`.
  - **The rule** is the same as the add-on's (§3, §4.3): the `media_player` entities in `entity_sources` with the
    domain `music_assistant`. That means the loaded players of a loaded entry, unavailable ones included, and disabled
    ones left out.
  - `available` is false for `unavailable` or `unknown`. The list is sorted by name.
  - The list is empty without Music Assistant.
- **`ha_fitness/music`** takes `{action: "pause" | "play" | "next"}` for the active session's speaker.
  - **pause:** `media_player.media_pause`.
  - **play:** `media_player.media_play`. While the controller's state is `failed`, or `waiting` with `started_at` set
    (after "Start nu" while paused), it runs the start (§5.2) instead. While `waiting` in the countdown (`started_at`
    null), the card's Play is disabled (§6.2); the command then fails with `not_found`.
  - **next:** `media_player.media_next_track`.
  - It fails with `not_found` when there is no active session with music.
  - It fails with `unavailable` when the call fails or the speaker is unavailable.
  - **It doesn't change the workout.** This is Claude's call: Pause on the music player pauses only the music, as in
    the mockup. The workout's own Pause pauses both, and the workout's next Resume plays the music again.
- **`ha_fitness/session/command`** with `start` takes an optional `speaker`, checked with the add-on's pattern for
  `Music.speaker` (`^media_player\.[a-z0-9_]+$`).
  `async_start_session` passes it on only when given and the add-on supports music (§5.6).
- **`ha_fitness/programs`** gets `music` for each program, as the add-on sends it, or null (§5.6).

### 5.6 An older add-on

- The coordinator's probe (D37) also asks for `GET /api/v1/music`.
  - A 404 while health answers raises `addon_too_old`.
  - The coordinator keeps a flag, `music_supported`, set from each probe's answer. It survives a disconnect, so a
    reconnect leaves no gap.
- **While `music_supported` is false:**
  - `ha_fitness/programs` sends `music: null`, so the card shows no music row;
  - a start drops `speaker`;
  - the subscription's `music` is null;
  - the controller does nothing.
- So PR 2 against an older add-on works, without music.

### 5.7 Docs (PR 2)

- `architecture.md`: the controller, the fade, the music state, and the ws commands.
- `testing.md`: the music check with the fake.
- `decisions.md`: D53 and D54.

## 6. The cards (PR 2)

Every text comes from the language files (hard rule 6), in English and Danish.

### 6.1 Details: the music row

The row appears when the program has music, Music Assistant is loaded, and `ha_fitness/speakers` lists at least one
speaker. It sits above "Du skal bruge", as in the `WorkoutDetails` mockup.

- **The label:** "Musik" / "Music". **The value:** the music icon (`mdi:music`), then the playlist name.
- **The speaker dropdown:** a native `<select>`, labelled "Højttaler" / "Speaker".
  - It lists the speakers by name. An unavailable one reads "<name> (utilgængelig)" / "<name> (unavailable)".
  - It defaults to the program's speaker. If that one isn't listed, it falls back to the first available speaker.
- **Start** passes the chosen `speaker`.
- Without music or without speakers, there is no row and no `speaker`.

### 6.2 The timer: the music player

The player sits in the header row, after the pills, as in the `Timer` and `TimerDuo` mockups. It is a white card with
the grey border (D52), pill-shaped:

- **On the left:** the music icon in a round badge.
- **Two lines:**
  - the playlist name;
  - the speaker's name, or "Musik utilgængelig" / "Music unavailable" while `unavailable`.
- **The buttons:** 44 px round, soft.
  - **Pause music** (`mdi:pause`) while `playing`. Otherwise **Play music** (`mdi:play`).
  - **Next track** (`mdi:skip-next`).
  - Both send `ha_fitness/music`.
- **Which buttons work in each state:**
  - while `waiting` (the countdown), both are disabled;
  - while `unavailable`, Play is enabled, so a failed start can be retried (§5.5), and Next is disabled;
  - while `playing` or `paused`, both work.
- **When `music` is null,** there is no player.
- **Width:** at most 400 px. It shrinks with ellipsis before the pills or Slut do.
- **In portrait,** the player goes on its own line under the pills.
- **Get ready** shows no player. The music starts with the first work phase.

### 6.3 Texts

New keys:

| Key | English | Danish |
| --- | --- | --- |
| music label | "Music" | "Musik" |
| speaker label | "Speaker" | "Højttaler" |
| unavailable mark | "{name} (unavailable)" | "{name} (utilgængelig)" |
| music unavailable | "Music unavailable" | "Musik utilgængelig" |
| pause music | "Pause music" | "Pause musik" |
| play music | "Play music" | "Afspil musik" |
| next track | "Next track" | "Næste nummer" |

The plan names the exact keys.

## 7. The fake Music Assistant (dev only)

A custom integration in `scripts/dev/fake_music_assistant/`, with the domain `music_assistant`. It is never shipped:

- it isn't under `custom_components/`, so hassfest, HACS and the release never see it;
- it isn't in the add-on.

**It copies Music Assistant's surface (§3):**

- **A config flow** with no fields. The entry is titled "Fake Music Assistant", which isn't the domain, so
  `integration_entities()` takes the `entity_sources` path, as on the house.
- **Three players**, each with a unique id, so `config_entry_id()` works:
  - `media_player.fake_kitchen` "Kitchen speaker";
  - `media_player.fake_living_room` "Living room speaker";
  - `media_player.fake_garage` "Garage speaker".
- **`mass_player_type: player`** comes through `extra_state_attributes`, so it disappears while a player is
  unavailable.
- **The garage speaker has no `VOLUME_SET`,** to exercise the fade without volume.
- **The media player features:** play media, pause, play, next track, volume set and shuffle set.
  - The state and attributes really change: `playing` or `paused`, `volume_level`, `shuffle`, and `media_title` (the
    playlist's name, then "Track 2" …).
  - So the fade and the pause show in Chrome.
- **Its own services:**
  - `music_assistant.play_media`: a platform entity service with §3's schema. So a speaker that isn't one of its
    players fails as on the house.
  - `music_assistant.get_library`: §3's schema and response shape, with `SupportsResponse.ONLY`. It answers four
    playlists, filtered by `search`:
    - "Workout Mix", `library://playlist/1`;
    - "Cardio Beats", `library://playlist/2`;
    - "Calm Stretch", `library://playlist/3`;
    - "Rock Classics", `library://playlist/4`.
  - `music_assistant.fake_set_available` `{entity_id, available}` makes a player unavailable, or available again, to
    check the unavailable path.

**Wiring it in:**

- **The fast loop:**
  - `scripts/develop` links the fake into `config/custom_components/music_assistant`, next to `ha_fitness`.
  - A custom integration with a core domain overrides the core one, and HA logs a warning.
  - `scripts/dev_onboard.py` adds the fake's config entry when it has none, as it does HA Fitness's.
- **The full loop:**
  - a new `scripts/full-loop music` copies the fake into the Supervisor's HA config folder in the container;
  - it restarts Core;
  - it runs `dev_onboard.py --fake-music-only`, a new option that adds only the fake's entry.
  - The spike (§4.3) uses this.
- **The seed:** `scripts/seed` gives Sample this music:
  - `playlist: library://playlist/1`;
  - `playlist_name: Workout Mix`;
  - `speaker: media_player.fake_living_room`;
  - `volume: 30`.

  It also writes the music onto an existing Sample that has none.

**Two fakes:**

- the dev fake above, for the loops and Chrome;
- the pytest fakes, which the integration tests register in the test HA as services, platform entities and states.

They are separate. The pytest fakes follow §3 too.

## 8. Tests

All tests go through public interfaces (hard rule 5), with a frozen clock where time matters.

### The add-on

- **Starts:**
  - a start with `speaker` freezes the music with that speaker;
  - a start without one freezes the program's speaker;
  - a program without music gives `music: null`;
  - a bad speaker gives 422.
- **Old data:**
  - an old plan without `music` reads as `music: null`;
  - an old program document without `playlist_name` reads it as null.
- **`playlist_name`** is accepted, null by default, and validated.
- **`list_speakers` and `list_playlists`** run against a fake HA (respx), over MCP and REST:
  - the template's answer;
  - sorting and `search`;
  - empty without speakers;
  - a malformed answer;
  - HA down (503 and `ToolError`).
- **`GET /api/v1/music`.**

### The integration

These use pytest fakes of `music_assistant.play_media`, the `media_player` services, and players loaded on a mock
`music_assistant` platform (not HA core's integration, which needs `music-assistant-client`). The plan says how.

- **The start:** a running view with `started_at` set, while `waiting`, plays the playlist, with volume, then shuffle.
  - It also runs for a countdown of 0 (first seen started, after the controller's start), and for "Start nu" from a
    paused countdown.
  - Adoption: a session first seen with an earlier `started_at` starts nothing, but Pause, Resume and the fade work.
- **Pause and Resume.**
- **The fade:**
  - its steps, paced by time, then the pause and the restored volume;
  - without `VOLUME_SET`, only the pause;
  - no fade when the speaker isn't playing;
  - cancelled by a new start on the same speaker;
  - at unload: the pause, then the restored volume;
  - an end by disappearance.
- **Nothing happens** for a program without music, after Annullér, or while `music_supported` is false.
- **A failed start:**
  - an unavailable speaker, and a failing call, give `unavailable`, and the workout goes on;
  - it is retried on Resume, when the speaker comes back, and on Play.
- **`ha_fitness/speakers`.**
- **`ha_fitness/music`:** each action, `not_found`, `unavailable`, and Play running the start after a failure.
- **`music` in the subscription:** each state, sent when the speaker's state changes, and null without Music
  Assistant.
- **An older add-on:** the probe's `addon_too_old` and `music_supported`. While it is false, `ha_fitness/programs`
  sends `music: null`, a start drops `speaker`, and `music` is null.
- **`ha_fitness/programs`** with `music`, and a start passing `speaker`.

### The cards

- **The music row:** shown and hidden; the default and the fallback; the unavailable mark; the start command's
  `speaker`.
- **The music player:** each state; the buttons' commands; which buttons are enabled per state.
- Both languages.

### The fast loop with the fake, in Chrome

- details with the dropdown;
- the countdown, then the music playing (the fake's state);
- Pause and Resume;
- Next;
- the fade at Slut;
- the unavailable path, through `fake_set_available`, and its recovery.

Screenshots go in the PR.

## 9. Decisions and the house

**Decisions**, numbered next:

- **D53 (PR 2): the integration plays the music, following the session.** The add-on only freezes the choice. The music
  starts at a running view with `started_at` set, while no start was tried (including the first view of a session that
  started after the controller's start).
  A session already running at a restart or reload is adopted, not restarted. A failed start is retried.
- **D54 (PR 2): the fade restores the volume after pausing.** It also does so at unload.
- **D55 (PR 1): a dev-only fake Music Assistant stands in for the real one in the loops.** It lives in `scripts/dev/`,
  is never shipped, and copies the surface of HA core's `music_assistant`.

**The house** gets a `fitness` issue after the releases, for ha-claude-a8 and Thomas's yes:

- install the add-on first;
- set each program's music through Claude, with `list_speakers` and `list_playlists`;
- check the music on the kitchen tablet. It's the first test against a real Music Assistant. Check:
  - the start;
  - shuffle right after `play_media`;
  - the header's Play on an adopted session whose speaker went idle;
  - the fade's timing;
  - an unavailable speaker.

## 10. Review findings, answered

### Round 1

| Finding | Where |
| --- | --- |
| Speakers through the platform's entities, not `mass_player_type` | §3, §4.3, §5.5 |
| Pause, resume and fade only after a start | §5.1 |
| The start trigger | §5.1 |
| A vanishing session is an end | §5.1 |
| The fade's cancel and restore, the same speaker, unload | §5.3 |
| `VOLUME_SET` is optional | §3, §5.2, §5.3 |
| Shuffle after `play_media` | §5.2 |
| The D37 probe and the install order | §2, §5.6 |
| `ha_fitness/programs` includes `music` | §5.5 |
| REST facts and a proxy spike first | §3, §4.3 |
| A local Music Assistant for testing | §7 (the fake), §8 |
| One MCP error shape | §4.3 |
| The music state's definition and its subscription key | §5.4 |

### Round 2

| Finding | Where |
| --- | --- |
| An older add-on and `speaker` | §5.6 (`music_supported`) |
| `waiting` against the restart rule; reloads | §5.1 (adoption), §5.4 |
| No way back from a failed start | §5.1, §5.5, §6.2 |
| The start command is the integration's | §2, §4.2, §5.5 |
| `integration_entities` and one rule | §3, §4.3, §5.5 |
| The pause at unload | §5.3 |
| No storage migration | §4.1, §4.2 |
| The music row's place | §6.1 |
| The fake's entry in the full loop | §7 |

### Round 3

| Finding | Where |
| --- | --- |
| `waiting` and the event table against "Start nu" while paused and a countdown of 0 | §5.1 |

## 11. Left to the plan

- The exact language-file keys.
- The template's text.
- How the fade is tested against a frozen clock.
- The header's layout details, checked in Chrome.
