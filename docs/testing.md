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
     `HA_FITNESS_DEV=1` (the dev routes, below) and `HA_FITNESS_TIMEZONE=Europe/Copenhagen` (D36);
   - dev Home Assistant on `http://localhost:8123`, config in `config/` (git-ignored), with
     `config/custom_components/ha_fitness` linked to the repo.
3. Wait for HA: `curl -sf -o /dev/null --retry 60 --retry-delay 2 --retry-connrefused --retry-all-errors
   http://localhost:8123/manifest.json`.
4. On a fresh `config/`: `uv run python scripts/dev_onboard.py`, while the add-on server runs. It onboards HA with the
   user `dev` / `dev`, sets that user's language to Danish and sets the dev HA's timezone to Europe/Copenhagen (the
   server's zone). It also writes a long-lived token for the dev user to `local/dev-ha-token` (mode 600), or keeps the
   one there when HA still accepts it. It is safe to run again, and the server needs no restart after it.
   - It adds the HA Fitness entry through the user step, with the URL `http://localhost:8765`. The integration checks
     that the server answers there; if it doesn't, the script stops and says so.
   - It creates the **dev dashboard** `ha-fitness-dev` ("HA Fitness dev" in the sidebar, at
     `http://localhost:8123/ha-fitness-dev`): two sections views, one holding the card `custom:ha-fitness-today-card`
     and one (Workout) `custom:ha-fitness-workout-card` with `custom:ha-fitness-stats-card` below it, with no
     visibility rule and no `language` option. A dashboard that already has a config is kept as it is.
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
   - `scripts/seed --late` makes Sample late, with yesterday's day open. It refuses, before it changes anything, when
     another active program trains today: that program's day would close the late one.
   - `scripts/seed --short` makes the short program "Kort" due today: 2 body-weight stations, 1 round, work 10 s,
     switch 0 s, countdown 5 s. It creates Kort with today's weekday only, or sets an existing Kort's weekdays to
     today's only and switches it on, then opens (or reopens) its day for today. Kort's day for today closes any
     earlier late day as missed, and makes `scripts/seed --late` refuse on that weekday until Kort is switched off.

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
3. `scripts/full-loop check` prints the add-on's health from `http://localhost:8765/api/v1/health`. The version must be
   the working tree's.
4. `scripts/seed --ha-url http://localhost:7123` creates the persons and the sample program there. Then
   `curl -s http://localhost:8765/api/v1/people` lists them: the add-on reaches its HA through the Supervisor.
   `GET /api/v1/library` reaches media state `done`.
5. Check Ingress in Chrome (below): the add-on's page at `http://localhost:7123/app/local_ha_fitness`, in Danish for
   the Danish user. Then the integration:
   - install it ([how](ha-notes.md#the-supervisor): copy `custom_components/ha_fitness`, with the built cards, and
     restart HA);
   - the Discovered card reads "HA Fitness", and setting it up from there creates the entry with no URL to type;
   - the three entities have their states, and the device shows the add-on's version;
   - the today card is on `http://localhost:7123/ha-fitness-dev`, and edit mode shows its note. The full loop has no
     dev routes, so `seed --today` refuses there: the card shows a row only when a program trains today, for example
     one made in the MCP check.
6. The MCP check (below) against `http://localhost:8765/mcp`.
7. The backup check (below).
8. `scripts/full-loop down` removes the container and its volumes. The next `up` downloads HA Core again.

The fast loop and the full loop both use port 8765: stop one before starting the other. The Supervisor's log is
`/tmp/supervisor_run.log` inside the container.

### Backup check

The Supervisor's backup rules (`backup_pre`, `backup_exclude` in `addon/config.yaml`, D31) can't be tested in pytest.
In the full loop, with at least one program stored:

1. Take a backup: `ha backups new --name t`, in the container.
2. Open the backup's tar inside the container and list the add-on's archive in it. `backup/snapshot.db` must be there.
   `ha_fitness.db`, `ha_fitness.db-wal`, `ha_fitness.db-shm` and `library/media/` must not be.
3. Restore the add-on from it: `ha backups restore <slug> --app local_ha_fitness`.
4. The programs are still listed (`GET /api/v1/programs`), and the media is downloaded again.

## Chrome check

For every UI change, in the fast loop (and in the full loop before a release):

- A new Chrome tab on the dev HA, logged in as `dev` / `dev`. The window is **1368×912**, the kitchen tablet's size.
- The user's language is Danish (`dev_onboard.py` sets it). Check English as well when texts change: switch it in the
  user's profile.
- Touch only: don't rely on hover.
- No errors in the console.
- Screenshots of the changed screens go in the PR description. They show the dev HA only, never the real one.

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
7. **Fortsæt after a reload:** reload while a session runs. Nothing opens by itself. The today card shows "Træning i
   gang" and Fortsæt, which opens the overlay at the timer.
8. **Done:** Slut, then Ja. After a full round "Godt gået!" shows; before one, "Træningen blev afsluttet". Luk closes
   it.
9. **The today card stays visible during an extra session:** with no day open, start a session from
   `custom:ha-fitness-workout-card` (the dev dashboard's Workout view). Back on the first view, the today card shows
   "Træning i gang" and Fortsæt while the session runs. `dev_onboard.py` saves the dashboard only while it has none,
   so a dev HA onboarded before the Workout view existed lacks it: delete the `ha-fitness-dev` dashboard (Settings →
   Dashboards) and run `dev_onboard.py` again.
10. **A real short run:** `scripts/seed --short`, then Start on Kort's row, with the sound on. Listen that the beeps at
    5, 4, 3, 2 and 1 s line up with the numbers, and that the change tones and the chime at the end come.
11. The console is clean throughout.

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
2. **The panels at 1368×912:** one panel per person, side by side, in the people's order. Each has the person's colour
   as a dot by the name (purple, then teal), the streak ("1 i træk"), and the table with "Denne måned" and "I alt".
   After an extra session, Gennemført shows "· 1 ekstra"; after a skip, Missede shows "· 1 sprunget over".
3. **Stacking at 800×1280:** the panels stack, one above the other.
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
4. `list_programs` shows it, and so does the add-on's page at `http://localhost:8765/`. On a day the program
   trains, it is also on the today card on the dev dashboard (`http://localhost:8123/ha-fitness-dev`).
5. Delete the test programs again, then `claude mcp remove ha-fitness-dev -s local`.

The same works against the full loop: the add-on's port 8765 is mapped to the Mac.

## Waiting for a server

Wait with `curl --retry … --retry-connrefused --retry-all-errors`, not with `sleep`. Docker Desktop's port proxy
accepts a connection and then resets it until the server listens; only `--retry-all-errors` retries that. To see what
listens on a port, use `lsof -nP -iTCP:<port> -sTCP:LISTEN`: plain `lsof -i :<port>` also lists outgoing connections.
