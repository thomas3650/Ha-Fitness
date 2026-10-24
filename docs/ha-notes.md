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
- **Backups:** `backup_exclude` patterns are matched against the end of each path (`PurePath.match`), so
  `ha_fitness.db` also leaves out any file of that name in a subfolder. That is why the add-on's snapshot has a name
  none of its patterns matches (`backup/snapshot.db`). A non-zero exit of `backup_pre` fails the add-on's part of the
  backup. The add-on's `backup_pre` starts with `/usr/bin/with-contenv`, the same as its `CMD`.
- A locally built app's backup also holds its image (`image.tar`, about 80 MB for this add-on), because the Supervisor
  can't pull it again. An app installed from a repository pulls its image after a restore, so the house's backups don't
  carry it. Checked in the full loop (2026-10-24): the archive held `data/backup/snapshot.db` and neither the live
  database nor `library/media/`, and `ha backups restore <slug> --app local_ha_fitness` brought a deleted program back.

## The integration

- **`single_config_entry` blocks discovery updates.** With `"single_config_entry": true` in `manifest.json`, HA
  aborts every new flow with `single_instance_allowed` once an entry exists, before the flow's first step runs
  (checked in HA's `config_entries.py`). A Supervisor discovery for the existing entry then never reaches
  `async_step_hassio`, so `_abort_if_unique_id_configured(updates=...)` can't give the entry the add-on's new address.
  That is why HA Fitness has a unique id instead (D39).
- **Entity ids on a Danish HA.** With `has_entity_name` and a `translation_key`, HA builds a new entity's id from its
  translated name, in HA's own language. On a Danish HA that gives Danish ids, from "Træning i dag" and the others.
  So the entities set `entity_id` explicitly (`sensor.ha_fitness_today` …), and `test_entity_ids_on_danish_ha`
  checks the ids with `hass.config.language = "da"`.
- **HA's request filter runs before any view.** Its `security_filter` middleware answers 400 for a path that holds a
  tab, CR or LF once decoded (`%0A`), or a `../` after unquoting, however often it was encoded (`..%2F`). The view never sees such a
  request. A lone `%2F` isn't filtered. So the media proxy's tests expect 400 for those paths, and 404 for every other
  path outside its patterns (checked in HA's `http/security_filter.py`).

## The frontend

- **Authenticated images.** An `<img src>` request sends no `Authorization` header, so a view with `requires_auth`
  answers it 401. The cards load the media proxy's files with `hass.fetchWithAuth(url)`, which adds the token, and
  show the body through an object URL (`URL.createObjectURL`). An object URL holds its blob until it is revoked.

- **Hiding a card.** HA's `hui-card` hides a card when the card element sets the `hidden` attribute and fires
  `card-visibility-changed` (`detail: {value: <visible>}`, bubbling and composed); HA's own cards also set
  `display: none`. A card that is only `display: none` keeps its grid cell, which shows as an empty space.
- **A hidden card leaves the DOM.** `hui-card` removes a hidden card element unless the element has
  `connectedWhileHidden = true`. Without it the card is disconnected, drops its subscription, and never sees the
  data that should show it again.
- **`hass.callService(domain, service, data, target, notifyOnError, returnResponse)`.** With `notifyOnError` true
  (the default) HA shows its own toast on an error, in the system language. The today card passes `false` and shows
  its own text, chosen by the error's `translation_key`, in the card's language.
- **`connection.subscribeMessage(callback, message, {resubscribe})`.** home-assistant-js-websocket resubscribes by
  default after a reconnect. A card that also subscribes again on the connection's `ready` event then has one extra
  server subscription after each reconnect. The today card passes `{resubscribe: false}`, as HA's own frontend does,
  and subscribes again on `ready` itself.

## Testing

- The `frontend` dependency's setup imports `home-assistant-frontend`, which `pytest-homeassistant-custom-component`
  doesn't bring. It is in the dev group, pinned to HA's frontend version.
- `homeassistant.components.http` re-exports `StaticPathConfig` without `as`, so strict mypy calls it private. The
  import carries `# type: ignore[attr-defined]`.
- `uv run` and `uv sync` remove the packages HA installed into `.venv` at runtime. HA reinstalls them on the next start,
  which is then slower.
- HA allows one long-lived access token per client name: a second `auth/long_lived_access_token` with the same
  `client_name` fails with "already exists" (checked in HA's `auth/__init__.py`). So `scripts/dev_onboard.py` deletes
  the old `ha-fitness-dev` token (`auth/refresh_tokens`, `auth/delete_refresh_token`) before it makes a new one.
- **A lingering aiohttp heartbeat timer.** When the client closes a ws with a heartbeat itself, aiohttp 3.14 re-arms
  the heartbeat timer as the other side's close frame arrives. One timer then outlives the closed socket, and
  `pytest-homeassistant-custom-component` fails the test for a lingering timer. That is why
  `test_unexpected_error_does_not_stop_reconnect` sets `expected_lingering_timers`. It is harmless outside tests.
- **The frozen clock and aiohttp.** Under `freezer` the event loop's clock moves only with `freezer.tick`, and
  `async_fire_time_changed` runs aiohttp's own timers too (connect and pong timeouts). Firing 15 s or more ahead while
  a socket is connecting or waiting for a pong times it out, so `wait_for` in `tests/common.py` is used with short
  spans only.

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
