# Home Assistant notes

Learned facts about building and testing on Home Assistant (2026.10), newest last within each section. Small facts that
fit no doc stay in [`notes.md`](notes.md).

## The Supervisor

- Under the Supervisor, HA listens on **port 80** inside the container (`SUPERVISOR_DEFAULT_PORT = 80`). Port 8123
  only redirects until onboarding is done. That is why `.devcontainer/supervisor/devcontainer.json` maps `7123:80`.
- The Supervisor builds a local app only when its `config.yaml` has no `image:`. With one, it pulls the published image
  instead. That is why `scripts/full-loop install` stages a copy of `addon/` without `image:` in `local/full-loop/`.
- The Supervisor's scan for local apps globs `**/config.*`. So only the staging folder is mounted at its local apps
  folder, never the repo: the scan would walk `cards/node_modules`, `config/` and `local/`. For the same reason the
  dev container example's `devcontainer_bootstrap` isn't used: it mounts the whole repo.
- Until HA itself answers, the container's port 80 refuses or redirects. The wait in `scripts/full-loop up` treats a
  redirect as not ready.

- The base image's `/init` (s6-overlay) starts the Dockerfile's `CMD` with an **empty environment**: only `PATH`.
  `SUPERVISOR_TOKEN` and `TZ` reach the server only when `CMD` starts with `/usr/bin/with-contenv` (spike, step 2).
- The Supervisor passes HA's timezone to every app as `TZ` (e.g. `Europe/Copenhagen`). The add-on can use it for
  midnight without asking HA.
- **Ingress:** with `ingress: true` and `ingress_port: 8765` the API port also serves Ingress. HA 2026.10 opens it at
  `/app/<slug>` (`/app/local_ha_fitness` for the local app). Requests come from the Supervisor with the
  `X-Ingress-Path` header (`/api/hassio_ingress/<token>`); a page with relative links works under it. The page is not in
  the sidebar until the user turns on "show in sidebar" (`panel_icon` and `panel_title` set its look).
- **Discovery:** an app lists its services under `discovery:` in `config.yaml`; the service name is the integration's
  domain. At start it posts `{"service": "ha_fitness", "config": {...}}` to `http://supervisor/discovery` with
  `SUPERVISOR_TOKEN`; no extra API flag is needed. HA then starts a config flow with source `hassio`
  (`async_step_hassio`) and shows it under "Discovered" (Danish "Fundet"). The app's hostname comes from
  `GET http://supervisor/addons/self/info` (`hostname`): `local-ha-fitness` for the local app, `<repo hash>-ha-fitness`
  from a repository. HA's container reaches the app at `http://<hostname>:8765`.
- If HA gets the discovery before the integration is installed, it logs `Cannot find integration ha_fitness`. After the
  integration is installed and HA restarts, HA reads the stored discovery again and the flow appears.
- A discovered card shows the integration's domain (`ha_fitness`) as its title unless the flow sets
  `title_placeholders`.
- The Supervisor's HA config folder is `/mnt/supervisor/homeassistant` inside the dev container (`/config` in HA's
  container). Copying `custom_components/ha_fitness` there and running `ha core restart` installs the integration in
  the full loop.
- The Supervisor already knows a discovery service named `mcp` (the ESPHome dev and beta apps send it).

## Testing

- The `frontend` dependency's setup imports `home-assistant-frontend`, which `pytest-homeassistant-custom-component`
  doesn't bring. It is in the dev group, pinned to HA's frontend version.
- `homeassistant.components.http` re-exports `StaticPathConfig` without `as`, so strict mypy calls it private. The
  import carries `# type: ignore[attr-defined]`.
- `uv run` and `uv sync` remove the packages HA installed into `.venv` at runtime. HA reinstalls them on the next start,
  which is then slower.

## Bumping Home Assistant

The HA version is pinned in three places that move together, by hand, in one PR: `pytest-homeassistant-custom-component`
(the release for that HA version) and `home-assistant-frontend` (HA's frontend pin) in the root `pyproject.toml`, and
`homeassistant` in `hacs.json`. Dependabot ignores these packages (and `homeassistant`) for that reason.

## CI

- `home-assistant/actions/helpers/info` returns JSON-encoded values (`"0.0.0"` with its quotes). Decode them with
  `jq -r` or `fromJSON` before use.

## macOS

- `hass` started with `&` in a non-interactive shell crashes in Bluetooth (CoreBluetooth via PyObjC). Run
  `scripts/develop` in a terminal, or with Claude Code's Bash `run_in_background`; `scripts/smoke` runs HA in the
  foreground with a timer.
- `hass` exits with 134 on SIGTERM, from the same teardown. That is harmless.
- Stop the fast loop with `scripts/develop stop`, not `pkill -f "hass -c config"`: the pattern also matches the shells
  that wrap the command.
