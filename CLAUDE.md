# CLAUDE.md

## What this repo is

HA Fitness is circuit training at home, run from Home Assistant. On a training day the kitchen tablet shows the
workout, runs it for one or two people and keeps per-person stats; programs are made by talking to Claude. The repo is
**public** and holds three parts: an add-on (the server), a custom integration, and the Lovelace cards.

## Layout

- `addon/` — the add-on: `config.yaml`, `Dockerfile`, changelog, and the server in `addon/server/` (its own uv project)
- `custom_components/ha_fitness/` — the integration; `frontend/` holds the built cards bundle (git-ignored)
- `cards/` — the cards' source (Lit + TypeScript, Vite, Vitest)
- `tests/` — the integration's tests
- `scripts/` — the fast loop, the full loop and the link check
- `.devcontainer/supervisor/` — the Supervisor dev container of the full loop
- `.github/` — CI, release workflows, Dependabot, the PR template
- `.claude/` — project settings and the agents (`implementer`, `task-reviewer`, `full-reviewer`)
- `docs/` — the docs; the map is `docs/README.md`
- `repository.yaml`, `hacs.json` — the add-on repository and HACS metadata

## Commands

Set up and run (not gates):

```bash
scripts/setup                         # once per clone, and after a dependency change: uv, npm and the git hooks
scripts/develop                       # fast loop: dev HA on :8123, add-on server on :8765, cards watch
scripts/develop stop                  # stop the fast loop (from another shell)
uv run python scripts/dev_onboard.py  # onboard the dev HA (user dev / dev, Danish), add the HA Fitness entry, write local/dev-ha-token
scripts/seed                          # dev data: HA persons Thomas and Elin, the people, a Sample program (localhost only)
scripts/smoke                         # start the dev HA once and fail on integration errors
scripts/full-loop up|install|check|down   # full loop: the add-on under a real Supervisor on :7123
```

The gates (as CI runs them; all pass before every commit):

```bash
uv run ruff check && uv run ruff format --check && uv run mypy
uv run pytest --cov=custom_components.ha_fitness --cov-report=term-missing
uv run --directory addon/server ruff check && uv run --directory addon/server ruff format --check
uv run --directory addon/server mypy && uv run --directory addon/server pytest --cov=ha_fitness_server --cov-report=term-missing
npm run lint --prefix cards && npm test --prefix cards && npm run build --prefix cards
uv run actionlint && uv run zizmor --offline .github/workflows && uv run python scripts/check_links.py
```

`hassfest`, `hacs`, the add-on linter, the add-on image build and gitleaks run in CI only. How and when to run the loops:
[`docs/testing.md`](docs/testing.md).

## Hard rules

1. Never commit on or push to `main`. Every change reaches `main` through a squash-merged PR.
2. The repo is public. No tokens, hostnames, IPs, entity IDs or data from Thomas's Home Assistant in any file, commit,
   PR, issue or screenshot.
3. Never committed: exercise-library GIFs, `.env`, `config/`, `local/`, `.superpowers/`, `.DS_Store`, the built cards
   bundle (`custom_components/ha_fitness/frontend/*.js`), anything from the real Home Assistant. The 12 mockup GIFs in
   `docs/mockups/gifs/` are the one exception.
4. No changes to Thomas's real Home Assistant from this project. What the house needs goes to the house assistant as a
   `fitness` issue ([`docs/releasing.md`](docs/releasing.md)).
5. Tests check behaviour through public interfaces: REST and MCP responses, services, websocket commands, entity
   states, events, rendered text and roles. No snapshot, CSS-selector or exact-log-text tests. A frozen clock for
   anything time-based.
6. Every UI text comes from a language file. English is the base and Danish ships too. Exercise names and
   instructions are never translated.
7. Never bypass a hook (`--no-verify`, `-n`, `SKIP=`). Never read `.env`. Subagents also never read anything under
   `config/` or `local/`.
8. GitHub Actions: every `uses:` pinned to a full commit SHA with a version comment, least permissions per job,
   `persist-credentials: false` unless the job pushes.

## Way of working

@docs/way-of-working.md

## Documentation map

@docs/README.md
