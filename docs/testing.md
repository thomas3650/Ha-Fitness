# Testing

The gates are in `CLAUDE.md` → *Commands*; CI runs the same. What a test may check is `CLAUDE.md` hard rule 5. This
doc covers testing beyond the gates: the fast loop on every PR, the full loop before every release, and the checks in
Chrome and from Claude Code. Home Assistant quirks met on the way are in [`ha-notes.md`](ha-notes.md).

## Fast loop

Every PR. A dev Home Assistant with the integration and cards, and the add-on server on its own, all on the Mac.

1. `scripts/setup` once per clone, and after a dependency change.
2. `scripts/develop`. Claude starts it with the Bash tool's `run_in_background` ([why](ha-notes.md#macos)). It builds
   the cards, then starts:
   - the cards watch build (log `local/cards-watch.log`);
   - the add-on server on `http://localhost:8765`, data in `local/addon-data/` (log `local/addon-server.log`);
   - dev Home Assistant on `http://localhost:8123`, config in `config/` (git-ignored), with
     `config/custom_components/ha_fitness` linked to the repo.
3. Wait for HA: `curl -sf -o /dev/null --retry 60 --retry-delay 2 --retry-connrefused --retry-all-errors
   http://localhost:8123/manifest.json`.
4. On a fresh `config/`: `uv run python scripts/dev_onboard.py`. It onboards HA with the user `dev` / `dev`, sets that
   user's language to Danish and adds the HA Fitness entry. It is safe to run again.
5. Check: `curl -s http://localhost:8765/api/v1/health` gives the health JSON, and
   `http://localhost:8123/ha_fitness_frontend/ha-fitness-cards.js` answers 200.
6. `scripts/develop stop` stops all three.

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
4. Check Ingress, discovery and the cards in Chrome (below), once those exist.
5. `scripts/full-loop down` removes the container and its volumes. The next `up` downloads HA Core again.

The fast loop and the full loop both use port 8765: stop one before starting the other. The Supervisor's log is
`/tmp/supervisor_run.log` inside the container.

## Chrome check

For every UI change, in the fast loop (and in the full loop before a release):

- A new Chrome tab on the dev HA, logged in as `dev` / `dev`. The window is **1368×912**, the kitchen tablet's size.
- The user's language is Danish (`dev_onboard.py` sets it). Check English as well when texts change: switch it in the
  user's profile.
- Touch only: don't rely on hover.
- No errors in the console.
- Screenshots of the changed screens go in the PR description. They show the dev HA only, never the real one.

## MCP check from Claude Code

From step 2 on, when the add-on serves MCP at `/mcp`:

1. Add the endpoint: `claude mcp add --transport http ha-fitness http://localhost:8765/mcp`.
2. List the tools.
3. Create a program through a tool.
4. See it on the card in the dev HA.

## Waiting for a server

Wait with `curl --retry … --retry-connrefused --retry-all-errors`, not with `sleep`. Docker Desktop's port proxy
accepts a connection and then resets it until the server listens; only `--retry-all-errors` retries that. To see what
listens on a port, use `lsof -nP -iTCP:<port> -sTCP:LISTEN`: plain `lsof -i :<port>` also lists outgoing connections.
