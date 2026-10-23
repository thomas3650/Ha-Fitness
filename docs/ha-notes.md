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
