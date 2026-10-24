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
4. On a fresh `config/`: `uv run python scripts/dev_onboard.py`. It onboards HA with the user `dev` / `dev`, sets that
   user's language to Danish, sets the dev HA's timezone to Europe/Copenhagen (the server's zone) and adds the HA
   Fitness entry. It also writes a long-lived token for the dev user to `local/dev-ha-token` (mode 600), or keeps the
   one there when HA still accepts it. It is safe to run again, and the server needs no restart after it.
5. Check: `curl -s http://localhost:8765/api/v1/health` gives the health JSON,
   `http://localhost:8123/ha_fitness_frontend/ha-fitness-cards.js` answers 200, and
   `curl -s http://localhost:8765/api/v1/people` has a list in `ha_persons`, not `null`.
6. For dev data: `scripts/seed`. It creates the HA persons "Thomas" and "Elin", sets them as the people, and creates
   the program "Sample" (Wednesday, 5 body-weight stations). A second run changes nothing. It refuses any host but
   `localhost` or `127.0.0.1`, so it never touches a real HA or add-on. Use the wrapper: run directly,
   `scripts/seed.py` fails on its import. Two flags make a training day on purpose, through the dev routes; "today" is
   the date in Europe/Copenhagen. Both refuse, before any change, when the server has no dev routes.
   - `scripts/seed --today` makes Sample due today: it adds today's weekday to Sample, switches Sample on when it is
     off, and opens (or reopens, after a skip) its day for today.
   - `scripts/seed --late` makes Sample late, with yesterday's day open. It refuses, before it changes anything, when
     another active program trains today: that program's day would close the late one.

   The dev routes exist only with `HA_FITNESS_DEV=1`. Without it they answer 404 and aren't in OpenAPI, so the add-on
   never has them. `POST /api/v1/dev/training-days` with `{"program_id", "date"}` opens a day on today or an earlier
   date, or reopens the one there is. `DELETE /api/v1/dev/training-days?date=` removes every training day of that date,
   open or closed.
7. `scripts/develop stop` stops all three.

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
   onboards it (user `dev` / `dev`, Danish, no entry). The first start takes several minutes.
2. `scripts/full-loop install` copies `addon/` to `local/full-loop/ha_fitness/` without its `image:` line, then
   installs and starts the add-on as the local app `local_ha_fitness`, or rebuilds it when it is installed
   ([why the copy](ha-notes.md#the-supervisor)). Run it again after each add-on change.
3. `scripts/full-loop check` prints the add-on's health from `http://localhost:8765/api/v1/health`. The version must be
   the working tree's.
4. `scripts/seed --ha-url http://localhost:7123` creates the persons and the sample program there. Then
   `curl -s http://localhost:8765/api/v1/people` lists them: the add-on reaches its HA through the Supervisor.
   `GET /api/v1/library` reaches media state `done`.
5. Check Ingress in Chrome (below): the add-on's page at `http://localhost:7123/app/local_ha_fitness`, in Danish for
   the Danish user. Check discovery and the cards there too, once those exist.
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

## MCP check from Claude Code

From step 3 on the add-on serves MCP at `/mcp`; the tools are spec §8
([step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md)). The dev entry is named
`ha-fitness-dev`. The real add-on's entry is another one, kept outside this repo ([`addon/DOCS.md`](../addon/DOCS.md)).

1. Add the endpoint: `claude mcp add --transport http ha-fitness-dev http://localhost:8765/mcp` (local scope: it goes
   in `~/.claude.json`, not the repo). `claude mcp get ha-fitness-dev` shows `Connected`.
2. List the tools and call one from a headless session, for example `claude -p "List the ha-fitness-dev tools and
   call <tool>" --allowedTools "mcp__ha-fitness-dev__<tool>"`.
3. Ask in plain words for a program, for example "Make a program for Wednesday with five body-weight exercises, five
   rounds, 45 s work". Claude searches the library and creates it.
4. `list_programs` shows it, and so does the add-on's page at `http://localhost:8765/`. From step 4 on, also see it
   on the card in the dev HA.
5. Delete the test programs again, then `claude mcp remove ha-fitness-dev -s local`.

The same works against the full loop: the add-on's port 8765 is mapped to the Mac.

## Waiting for a server

Wait with `curl --retry … --retry-connrefused --retry-all-errors`, not with `sleep`. Docker Desktop's port proxy
accepts a connection and then resets it until the server listens; only `--retry-all-errors` retries that. To see what
listens on a port, use `lsof -nP -iTCP:<port> -sTCP:LISTEN`: plain `lsof -i :<port>` also lists outgoing connections.
