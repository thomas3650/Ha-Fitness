# Testing

The gates are in `CLAUDE.md` → *Commands*; CI runs the same. What a test may check is `CLAUDE.md` hard rule 5. This
doc covers testing beyond the gates: the fast loop on every PR, the full loop before every release, and the checks in
Chrome and from Claude Code. Home Assistant quirks met on the way are in [`ha-notes.md`](ha-notes.md).

Everything is tested on the Mac before a release (Thomas): the fast loop and the full loop need no release, no HACS
and no install on the real HA. A release only delivers a tested version to the house, and never stands in for a test.

## Fast loop

Every PR. A dev Home Assistant with the integration and cards, and the add-on server on its own, all on the Mac.

1. `scripts/setup` once per clone, and after a dependency change.
2. `scripts/develop`. Claude starts it with the Bash tool's `run_in_background` ([why](ha-notes.md#macos)). It builds
   the cards, then starts:
   - the cards watch build (log `local/cards-watch.log`);
   - the add-on server on `http://localhost:8765`, data in `local/addon-data/` (log `local/addon-server.log`). It
     reaches the dev HA with the token in `local/dev-ha-token` (D32), which it reads at each call. It runs with
     `HA_FITNESS_DEV=1` (the dev routes, below) and `HA_FITNESS_TIMEZONE=Europe/Copenhagen` (D36). It takes the
     `late_days` option from `options.json` in its data folder, or from `HA_FITNESS_LATE_DAYS` in the environment
     `scripts/develop` is started from (that wins); without either it is 2;
   - dev Home Assistant on `http://localhost:8123`, config in `config/` (git-ignored), with
     `config/custom_components/ha_fitness` linked to the repo. `config/custom_components/music_assistant` links the
     [fake Music Assistant](#the-fake-music-assistant).
3. Wait for HA: `curl -sf -o /dev/null --retry 60 --retry-delay 2 --retry-connrefused --retry-all-errors
   http://localhost:8123/manifest.json`.
4. On a fresh `config/`: `uv run python scripts/dev_onboard.py`, while the add-on server runs. It onboards HA with the
   user `dev` / `dev`, sets that user's language to Danish and sets the dev HA's timezone to Europe/Copenhagen (the
   server's zone). It also writes a long-lived token for the dev user to `local/dev-ha-token` (mode 600), or keeps the
   one there when HA still accepts it. It is safe to run again, and the server needs no restart after it.
   - It adds the HA Fitness entry through the user step, with the URL `http://localhost:8765`. The integration checks
     that the server answers there; if it doesn't, the script stops and says so.
   - It then adds the fake Music Assistant's entry, "Fake Music Assistant", when HA has no `music_assistant` entry. It
     stops with an error when the flow answers anything else, for example when the fake isn't linked yet: start the
     fast loop again after pulling the fake.
   - It creates the **dev dashboard** `ha-fitness-dev` ("HA Fitness dev" in the sidebar, at
     `http://localhost:8123/ha-fitness-dev`): two sections views, one holding the card `custom:ha-fitness-today-card`
     and one (Workout, `max_columns: 2`) with a section for `custom:ha-fitness-workout-card` and below it a
     two-column section (`column_span: 2`) for `custom:ha-fitness-stats-card`, with no visibility rule and no
     `language` option. A dashboard that already has a config is kept as it is.
5. Check: `curl -s http://localhost:8765/api/v1/health` gives the health JSON,
   `http://localhost:8123/ha_fitness_frontend/ha-fitness-cards.js` answers 200, and
   `curl -s http://localhost:8765/api/v1/people` has a list in `ha_persons`, not `null`.
6. For dev data: `scripts/seed`. It creates the HA persons "Thomas" and "Elin", sets them as the people, and creates
   the program "Sample" (Wednesday, 5 body-weight stations). A second run changes nothing. It refuses any host but
   `localhost` or `127.0.0.1`, so it never touches a real HA or add-on. Use the wrapper: run directly,
   `scripts/seed.py` fails on its import. Three flags make a training day on purpose, through the dev routes; "today"
   is the date in Europe/Copenhagen. Each refuses, before any change, when the server has no dev routes.
   - `scripts/seed --today` makes Sample due today: it adds today's weekday to Sample, switches Sample on when it is
     off, and opens (or reopens, after a skip) its day for today.
   - `scripts/seed --late` makes Sample late, with yesterday's day open. Other programs' days don't matter: only its own
     program's next training closes a late day (D60).
   - `scripts/seed --short` makes the short program "Kort" due today: 2 body-weight stations, 1 round, work 10 s,
     switch 0 s, countdown 5 s. It creates Kort with today's weekday only, or sets an existing Kort's weekdays to
     today's only and switches it on, then opens (or reopens) its day for today. Kort's day
     for today leaves a late Sample day open (D60).

   The dev routes exist only with `HA_FITNESS_DEV=1`. Without it they answer 404 and aren't in OpenAPI, so the add-on
   never has them. `POST /api/v1/dev/training-days` with `{"program_id", "date"}` opens a day on today or an earlier
   date, or reopens the one there is. `DELETE /api/v1/dev/training-days?date=` removes every training day of that date,
   open or closed.
7. **A short run**, after `scripts/seed --short`: Start on Kort's row in the today card, choose the people, and let
   it run to the end, about 25 s. When it completes, the today card no longer shows Kort. Without a browser, the same
   path through REST: `POST /api/v1/session` with `{"program_id", "participants": [person ids from
   GET /api/v1/people], "training_day_id"}` (Kort's day from `GET /api/v1/today`), then `GET /api/v1/session`.
8. **A stats check**, through REST, after `scripts/seed`. The numbers below hold on fresh data
   (`local/addon-data/` empty before `scripts/develop`); on old data, compare with the numbers before each step.
   Reopening a done day through the dev routes gives numbers no real day can, so start fresh for this check.
   - `scripts/seed --short`, then finish Kort with both people (step 7). `GET /api/v1/stats` gives each person
     `done` 1, `extra` 0, `missed` 0, `skipped` 0, `streak` 1, a `time_trained` above 0, the same in `this_month`, and
     `counting_from` today.
   - `scripts/seed --today`, then skip Sample's day: `POST /api/v1/training-days/{id}/skip`, with the id from
     `GET /api/v1/today`. Each person now has `skipped` 1 and `streak` 0: Kort is done but Sample is skipped on the
     same date, so the date breaks the streak ([why](domain-language.md#stats)).
   - An extra session: `POST /api/v1/session` with Kort and both people and no `training_day_id`, run to the end. Each
     person gets `done` +1, `extra` +1 and more `time_trained`; the streak stays.
   - The push channel sends a `stats` message after each of these, and `get_stats` over MCP
     ([below](#mcp-check-from-claude-code)) gives the same body as REST.
9. `scripts/develop stop` stops all three.

`scripts/smoke` starts the dev HA once in the foreground (150 s, `SMOKE_SECONDS` to change), and fails if HA doesn't
start, if `ha_fitness` isn't set up, or on an error from the integration. The full log is `local/smoke.log`. It needs
the entry from step 4, and refuses to run while the fast loop runs. Run it before a PR is ready.

A card change rebuilds by itself; reload the browser. A Python change in the integration needs an HA restart
(`scripts/develop stop`, then start again).

## Full loop

Before every release ([`releasing.md`](releasing.md)), and when a change touches the add-on's packaging or its
Supervisor side (Ingress, discovery). The real add-on image under a real Supervisor and HA, in HA's add-on dev
container (`.devcontainer/supervisor/devcontainer.json`), driven by `scripts/full-loop` with no clicks. Docker
Desktop must run.

1. `scripts/full-loop up` starts the container and the Supervisor, waits for HA on `http://localhost:7123`, and
   onboards it (user `dev` / `dev`, Danish, the dev dashboard, no entry). The first start takes several minutes.
2. `scripts/full-loop install` copies `addon/` to `local/full-loop/ha_fitness/` without its `image:` line, then
   installs and starts the add-on as the local app `local_ha_fitness`, or rebuilds it when it is installed
   ([why the copy](ha-notes.md#the-supervisor)). Run it again after each add-on change.
3. When the test needs music: `scripts/full-loop music` copies the [fake Music Assistant](#the-fake-music-assistant)
   into HA's `custom_components` in the container, restarts Core, and adds the fake's entry
   (`dev_onboard.py --fake-music-only`). Run it again after a change to the fake.
4. `scripts/full-loop check` prints the add-on's health from `http://localhost:8765/api/v1/health`. The version must be
   the working tree's.
5. `scripts/seed --ha-url http://localhost:7123` creates the persons and the sample program there. Then
   `curl -s http://localhost:8765/api/v1/people` lists them: the add-on reaches its HA through the Supervisor.
   `GET /api/v1/library` reaches media state `done`.
6. Check Ingress in Chrome (below): the add-on's page at `http://localhost:7123/app/local_ha_fitness`, in Danish for
   the Danish user. Then the integration:
   - install it ([how](ha-notes.md#the-supervisor): copy `custom_components/ha_fitness`, with the built cards, and
     restart HA);
   - the Discovered card reads "HA Fitness", and setting it up from there creates the entry with no URL to type;
   - the three entities have their states, and the device shows the add-on's version;
   - the today card is on `http://localhost:7123/ha-fitness-dev`, and edit mode shows its note. The full loop has no
     dev routes, so `seed --today` refuses there: the card shows a row only when a program trains today, for example
     one made in the MCP check.
7. The MCP check (below) against `http://localhost:8765/mcp`.
8. The backup check (below).
9. `scripts/full-loop down` removes the container and its volumes. The next `up` downloads HA Core again.

Both loops use port 8765. They can run at the same time only when the fast loop starts first. The full loop's
container holds `*:8765`, so a fast loop started after it can't bind its server. With the fast loop first, its server
answers on `127.0.0.1:8765` and the full loop's on `[::1]:8765`. `scripts/seed` takes only `localhost` or `127.0.0.1`,
so stop the fast loop before seeding the full loop. The Supervisor's log is `/tmp/supervisor_run.log` inside the
container.

### Backup check

The Supervisor's backup rules (`backup_pre`, `backup_exclude` in `addon/config.yaml`, D31) can't be tested in pytest.
In the full loop, with at least one program stored:

1. Take a backup: `ha backups new --name t`, in the container.
2. Open the backup's tar inside the container and list the add-on's archive in it. `backup/snapshot.db` must be there.
   `ha_fitness.db`, `ha_fitness.db-wal`, `ha_fitness.db-shm` and `library/media/` must not be.
3. Restore the add-on from it: `ha backups restore <slug> --app local_ha_fitness`.
4. The programs are still listed (`GET /api/v1/programs`), and the media is downloaded again.

## The fake Music Assistant

A dev-only stand-in for Music Assistant, in `scripts/dev/fake_music_assistant/` (D55). It is a custom integration
with the domain `music_assistant`, so it overrides core's integration, and HA logs a warning about that. It is never
shipped: it isn't under `custom_components/` and isn't in the add-on. It copies the parts of core's integration that
HA Fitness uses ([the facts](ha-notes.md#music-assistant)).

- **The entry:** a config flow with no fields makes one entry, titled "Fake Music Assistant".
- **Three players:** `media_player.fake_kitchen` "Kitchen speaker", `media_player.fake_living_room` "Living room
  speaker" and `media_player.fake_garage` "Garage speaker". Each has a unique id and the attribute
  `mass_player_type: player`. The garage speaker can't set its volume.
- **Their state changes:** play, pause, next track, volume and shuffle work. After `play_media`, `media_title` is the
  playlist's name; each next track gives "Track 2", "Track 3" and so on. As on a real Music Assistant, shuffle does
  nothing until `play_media` has given the player a queue.
- **`music_assistant.play_media`:** core's schema. It plays one of the four playlists below. Another URI fails with
  an error.
- **`music_assistant.get_library`:** core's schema and response, response only. It answers four playlists, filtered
  by `search`: "Workout Mix" (`library://playlist/1`), "Cardio Beats" (`library://playlist/2`), "Calm Stretch"
  (`library://playlist/3`) and "Rock Classics" (`library://playlist/4`).
- **`music_assistant.fake_set_available`:** `{entity_id, available}` makes a player unavailable, or available again.
  Use it to check the unavailable path:

  ```bash
  curl -s -X POST -H "Authorization: Bearer $(cat local/dev-ha-token)" \
    -d '{"entity_id": "media_player.fake_garage", "available": false}' \
    http://localhost:8123/api/services/music_assistant/fake_set_available
  ```

The integration's tests don't use this fake. They register their own fakes in the test HA, after the same facts, in
`tests/music_fakes.py`.

## Real Music Assistant (full loop)

The fake can't show how the real Music Assistant behaves, so the full loop can run the real add-on. This is for a
check before the music goes to the house, not for every change.
`scripts/full-loop music` installs the fake under the same domain (`music_assistant`), so don't run it while the real
Music Assistant is installed.

1. Install the Music Assistant add-on in the full loop's Supervisor. Its repository is built in.
2. Confirm the discovered integration in HA ("Discovered").
3. Add music. In Music Assistant, add the Filesystem provider at `/media/test-music`. Make a few test tones with
   ffmpeg and copy them into the Supervisor's media folder, in `test-music`.
4. Make a playlist from the tones.
5. Turn on "Expose this player to Home Assistant" for the browser's web player, in Music Assistant's player settings
   ([why](ha-notes.md#music-assistant)). Without it, HA has no speaker.
6. Check the add-on's `GET /api/v1/music/speakers` and `/music/playlists`, then run a workout with that speaker.

Both loops use port 8765 ([when they can run together](#full-loop)).
Music Assistant's data is part of the full loop, so `scripts/full-loop down` removes it.

## Chrome check

For every UI change, in the fast loop (and in the full loop before a release):

- A new Chrome tab on the dev HA, logged in as `dev` / `dev`. The window is **1368×912**, the kitchen tablet's size.
- The user's language is Danish (`dev_onboard.py` sets it). Check English as well when texts change: switch it in the
  user's profile.
- Touch only: don't rely on hover.
- No errors in the console.
- Screenshots of the changed screens go in `screenshots/<YYYY-MM-DD>-<topic>/` in the repo root, named
  `<screen>-<landscape|portrait>.png` (for example `screenshots/2026-10-25-paused-blue/timer-paused-landscape.png`).
  The folder is git-ignored: screenshots show exercise-library pictures, which stay out of the public repo. The PR
  description lists the screens checked and the folder. Screenshots show the dev HA only, never the real one.

For a card change, open each card's editor as well. Check the Layout tab and the language field.

### The today card

On the dev dashboard `http://localhost:8123/ha-fitness-dev`, as the Danish user, with a screenshot of each step. Due
and late days never show together, so they are separate steps.

1. `scripts/seed --today`: one due row, the program's name over "5 øvelser · 5 runder · ca. … min", and Spring over.
2. Skip with two taps: Spring over, then Ja. Wait half a second before tapping Ja: it ignores taps until then. The
   card hides, and leaves no empty cell.
3. `scripts/seed --late`: the card comes back **without a reload**, and the row reads "Forfalden · <weekday> · …".
4. Edit mode with nothing open: the card stays, with the note "Ingen træning i dag".
5. Stop the add-on server alone (`kill "$(cat local/addon-server.pid)"`): the card shows "HA Fitness kan ikke nås".
   Start the fast loop again afterwards.
6. The console is clean throughout.

### The workout flow

On the dev dashboard, as the Danish user, with the header showing (a sections view), and with a screenshot of each
step. The flow is the overlay that Start and Fortsæt open; the design is in the
[step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §5.

1. `scripts/seed --today`, then Start on the today card. The overlay covers the whole page, **above HA's header**.
2. **Details:** the program, "ca. N min", the rounds, the work, switch and rest seconds, the stations, and a chip per
   person. Both people are preselected. Tilbage closes the overlay.
3. **Get ready:** Start again, and the countdown says who starts where. Annullér closes the overlay without counting.
4. **The timer for 1 person,** in work (orange ring, "ARBEJD") and in switch (blue ring, "SKIFT"): one station big,
   with "Næste" beside it.
5. **The timer for 2 people,** in work and in switch: a panel per person, with the person's colour, and the ring in
   the middle.
6. **Paused:** tap the ring. It stops and shows "PAUSE"; the play button resumes.
7. **Fortsæt after a reload:** reload while a session runs. Nothing opens by itself. The today card shows the session
   row: the program's name, "I gang · runde …", the people with the minutes, and Fortsæt, which opens the overlay at the
   timer.
8. **Done:** Slut, then Ja. After a full round "Godt gået!" shows; before one, "Træningen blev afsluttet". Luk closes
   it.
9. **The today card stays visible during an extra session:** with no day open, start a session from
   `custom:ha-fitness-workout-card` (the dev dashboard's Workout view). Back on the first view, the today card shows
   the session row ("I gang · runde …" and Fortsæt) while the session runs. `dev_onboard.py` saves the dashboard only
   while it has none, so a dev HA onboarded before the Workout view existed lacks it: delete the `ha-fitness-dev`
   dashboard (Settings → Dashboards) and run `dev_onboard.py` again.
10. **A real short run:** `scripts/seed --short`, then Start on Kort's row, with the sound on. Listen that the beeps at
    5, 4, 3, 2 and 1 s line up with the numbers, that a long (1 s) beep sounds at every exercise start, also right after the countdown, and
    that the change tones and the chime at the end come.
11. **Music, with the fake Music Assistant** (music spec §8). `scripts/seed` gives Sample the playlist "Workout Mix" on
    the living-room speaker. Start Sample as in step 1.
    - **Details:** the row "Musik" with "Workout Mix", and the "Højttaler" dropdown with the fake's three speakers,
      the living-room speaker chosen.
    - **The player:** when the countdown ends, the player shows after the pills: "Workout Mix" over the speaker's
      name. The fake's speaker is `playing`, with the playlist as its `media_title`.
    - **Pause and Play:** Pause musik pauses the speaker and the workout goes on; Afspil musik plays it again.
    - **Next:** Næste nummer moves the speaker to "Track 2".
    - **The fade at Slut:** Slut, then Ja. The speaker's volume steps down over about 5 s, the speaker pauses, and
      the volume is set back.
    - **Unavailable:** start again. Before the countdown ends (on the details screen or during Get ready), call
      `fake_set_available` with `available: false` for the chosen speaker ([how](#the-fake-music-assistant)), so the
      start fails. The player reads "Musik utilgængelig", Afspil musik is enabled and Næste nummer is disabled.
      The fake only flips availability and keeps the player's state, so the order matters: a speaker that drops after
      the start reads `playing` again when it comes back.
    - **Recovery:** call `fake_set_available` with `available: true` while the workout runs. The speaker gets
      `play_media` (its `media_title` becomes the playlist), and the player shows Pause musik.
    - **Long names in portrait** (800×1280): give the program a long `playlist_name` and the speaker a long name
      (its name in HA's entity settings). Both lines end in an ellipsis; the pills and Slut keep their place.
12. The console is clean throughout.

### The refreshed screens

After a change to the today card or the workout flow, check each screen at 1368×912 and at 800×1280, in Danish, against
the mockups' layout ([`mockups/README.md`](mockups/README.md)). When Chrome's window can't be resized, use the
portrait frame in [`ha-notes.md`](ha-notes.md#the-frontend). The design is in the
[UI refresh spec](superpowers/specs/2026-10-24-ui-refresh-design.md).

- **The today card:** an open day, a late day, a running session and a narrow (500 px) column.
- **The flow:** details, get ready (also paused), the timer (work, switch, paused, last interval), two people, done with
  a feeling, and ended both counted and not counted.
- Every icon-only button has a name, and every touch target is at least 48 px.

### The stats card

On the dev dashboard's Workout view, as the Danish user, with a screenshot of each step. The design is in the
[stats spec](superpowers/specs/2026-10-24-stats-design.md) §5.2. A dev HA onboarded before the stats card existed lacks
it; step 9 of the workout flow check says how to get it.

1. **Each line,** in the order of spec §5.2:
   - with an empty data folder (`scripts/develop stop`, move `local/addon-data/` aside, start again), before
     `scripts/seed`: "Ingen personer";
   - after `scripts/seed`, before any counted session: "Statistikken starter ved første træning";
   - after a counted session (a [short run](#fast-loop)): the panels;
   - with no stats since the entry was loaded: stop the add-on server alone (`kill "$(cat local/addon-server.pid)"`),
     then reload the entry (Settings → Devices & services → HA Fitness → Reload). Only "HA Fitness kan ikke nås"
     shows. Start the fast loop again afterwards.
2. **The panels at 1368×912:** the view has two columns (`max_columns: 2`), so the stats section, two columns wide,
   sits below the workout card's section and is about 1030 px wide. One panel per person, side by side, in the people's
   order.
   Each has the person's colour as a dot by the name (purple, then teal), the streak ("1 i træk"), and the table with
   "Denne måned" and "I alt". After an extra session, Gennemført shows "· 1 ekstra"; after a skip, Missede shows "· 1
   sprunget over".
3. **Stacking at about 600×1000:** HA hides the sidebar (below 870 px) and shows one column, so the stats card is
   about 580 px wide and the panels stack, one above the other. The panels stack below 600 px of card width, so only
   in a one-column view: at 800 px wide HA still shows two columns and the panels sit side by side.
   - HA's rules (frontend 20260930): a sections view fits `floor((width − padding + gap) / (320 + gap))` columns, at
     most `max_columns`. A column is at most 500 px wide. The gap and the side padding are 32 px, or 8 px at 600 px
     wide and below.
   - The house should place the card the same way: a Workout view with `max_columns: 2`, and the stats card in a
     section with `column_span: 2` below the workout card's section.
4. **The unreachable note:** stop the add-on server alone (`kill "$(cat local/addon-server.pid)"`). The card keeps
   the last numbers, with "HA Fitness kan ikke nås" as a small note above them. Start the fast loop again; the note
   goes away without a reload.
5. The console is clean throughout.

## MCP check from Claude Code

From step 3 on the add-on serves MCP at `/mcp`; [`architecture.md`](architecture.md) lists the tools. The dev entry is named
`ha-fitness-dev`. The real add-on's entry is another one, kept outside this repo ([`addon/DOCS.md`](../addon/DOCS.md)).

1. Add the endpoint: `claude mcp add --transport http ha-fitness-dev http://localhost:8765/mcp` (local scope: it goes
   in `~/.claude.json`, not the repo). `claude mcp get ha-fitness-dev` shows `Connected`.
2. List the tools and call one from a headless session, for example `claude -p "List the ha-fitness-dev tools and
   call <tool>" --allowedTools "mcp__ha-fitness-dev__<tool>"`.
3. Ask in plain words for a program, for example "Make a program for Wednesday with five body-weight exercises, five
   rounds, 45 s work". Claude searches the library and creates it.
4. Ask for music on it, for example "Play a workout playlist on the kitchen speaker". Claude calls `list_speakers` and
   `list_playlists` and puts the speaker's entity id, the playlist's uri and its name in the program's `music`. With
   [the fake Music Assistant](#the-fake-music-assistant) installed, the fake's three speakers and four playlists are
   listed; without Music Assistant both lists are empty.
5. `list_programs` shows it, and so does the add-on's page at `http://localhost:8765/`. On a day the program
   trains, it is also on the today card on the dev dashboard (`http://localhost:8123/ha-fitness-dev`).
6. Delete the test programs again, then `claude mcp remove ha-fitness-dev -s local`.

The same works against the full loop: the add-on's port 8765 is mapped to the Mac.

## Waiting for a server

Wait with `curl --retry … --retry-connrefused --retry-all-errors`, not with `sleep`. Docker Desktop's port proxy
accepts a connection and then resets it until the server listens; only `--retry-all-errors` retries that. To see what
listens on a port, use `lsof -nP -iTCP:<port> -sTCP:LISTEN`: plain `lsof -i :<port>` also lists outgoing connections.
