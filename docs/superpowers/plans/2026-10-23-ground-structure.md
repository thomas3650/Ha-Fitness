# Ground Structure (Step 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the `Ha-Fitness` folder into the public monorepo `thomas3650/Ha-Fitness`, with skeletons of the add-on, the integration and the cards that build, test, run locally (fast loop and full Supervisor loop) and release independently, and with the docs and agents for the way of working.

**Architecture:** Three parts in one repo. `addon/` is the HA add-on: a FastAPI server (its own uv project in `addon/server/`) packed in a multi-arch image. `custom_components/ha_fitness/` is the integration; it serves the cards bundle that `cards/` (Lit + TypeScript, Vite) builds into `custom_components/ha_fitness/frontend/`. The root uv project is the integration's dev and test environment. release-please releases the add-on and the integration+cards as two components.

**Tech Stack:** Python 3.14, uv, FastAPI + uvicorn, pytest, pytest-homeassistant-custom-component, ruff, mypy; Node 24, npm, Lit, TypeScript, Vite, Vitest; GitHub Actions, release-please, `home-assistant/builder` actions; Docker Desktop; `@devcontainers/cli` with `ghcr.io/home-assistant/devcontainer:5-apps`.

**Spec:** `docs/superpowers/specs/2026-10-23-ha-fitness-design.md` (approved 2026-10-23). This plan is §10 step 1, using §5–§9.

**Plan status:** full-reviewer Ready after 3 rounds (2026-10-23); approved by Claude (Thomas delegated plan approval, spec §6).

## Global Constraints

- Names: integration domain `ha_fitness`, integration name "HA Fitness"; add-on slug `ha_fitness`, add-on name "HA Fitness"; image `ghcr.io/thomas3650/ha-fitness-addon`; cards are custom elements `ha-fitness-<name>-card`; cards bundle file `ha-fitness-cards.js`.
- Python 3.14 everywhere. `pytest-homeassistant-custom-component` pinned to the release that matches HA 2026.10.2 (HA-NortecGo uses `==0.13.373`; check it still matches). `hacs.json` → `"homeassistant": "2026.10.2"`.
- Add-on: `arch: [aarch64, amd64]`; base image `ghcr.io/home-assistant/base-python:3.14-alpine3.24`; REST/MCP port **8765/tcp** (Claude's call for "the add-on's port", spec §11); data in `/data`; API version **1**.
- Versions start at `0.0.0` in `addon/config.yaml`, `addon/server/src/ha_fitness_server/__init__.py` (`__version__`) and `custom_components/ha_fitness/manifest.json`; release-please owns them after that, with `initial-version: 0.1.0` (otherwise its first release is 1.0.0) and `bump-minor-pre-major: true` (a breaking change during 0.x must not jump to 1.0.0, spec §8).
- Every UI text comes from a language file; English is the base, Danish ships too (spec §3.4). Exercise names are never translated.
- Never committed: exercise-library GIFs, `.env`, `config/`, `local/`, `.superpowers/`, `.DS_Store`, the built cards bundle (`custom_components/ha_fitness/frontend/*.js`), anything from the real HA (spec §7). The 12 mockup GIFs in `docs/mockups/gifs/` are the one exception (Thomas, spec §7).
- Tests check behaviour through public interfaces (HTTP responses, config flows, entity/websocket/HTTP behaviour of HA, rendered text and roles). No snapshot, CSS-selector or exact-log-text tests (spec §6).
- GitHub Actions: every `uses:` pinned to a full commit SHA with a `# vX.Y.Z` comment; top-level `permissions: {}` or `contents: read`, each job only what it needs; `actions/checkout` with `persist-credentials: false` unless the job pushes; `actionlint` and `zizmor --offline` clean.
- The repo is public: no tokens, hostnames, IPs, entity IDs or data from Thomas's HA in any file, commit or PR text.
- Commits: Conventional Commit messages, ending with the co-author trailer given in the dispatch. Never commit on or push to `main` (after Task 1's bootstrap commit).
- Agents (spec §6): `implementer` Opus/medium, `task-reviewer` Opus/medium, `full-reviewer` Opus/high. Every task below is `Model: opus`.

## Review Focus

1. **A change bumps the wrong component.** A commit touching only `cards/` must bump the integration; one touching only `addon/` must bump only the add-on; `docs:`/`ci:`/`chore:` must bump nothing. → Task 9, Step 5 (release-please dry runs).
2. **HACS offers an add-on release as an integration update.** The add-on's GitHub releases are created as **drafts** with a forced tag; HACS skips drafts (verified in HACS `repositories/base.py`), and drafts aren't public. (Prereleases were rejected: release-please marks them prerelease only while the major is 0.) → Task 11 Step 10 checks the real releases list.
3. **The add-on image can't be pulled by HA** (private GHCR package, or no arm64 variant). → Task 11 Step 9: anonymous `docker pull --platform linux/arm64`.
4. **The Supervisor dev container pulls `image:` from GHCR instead of building the local add-on** (verified: the Supervisor builds only when `image:` is absent). → Task 7 stages a copy without `image:`; Task 7 Step 3 checks that the running add-on reports a local `__version__` marker.
5. **The HACS zip lacks the cards bundle, or is never built** (the bundle is not committed; and a workflow on `release: published` would not run for a release made with `GITHUB_TOKEN`). → Task 9 builds the zip inside `release-please.yml`; Task 9 Step 4 checks the zip contents; Task 11 Step 10 downloads the real zip.
6. **release-please stalls after the first release** ("untagged, merged release PRs outstanding"). → Task 11 Step 10 checks the next release-please run and the release PR labels.

---

### Task 1: Bootstrap the repository (controller, not a subagent)

**Model:** controller · **Review:** no

Each sub-step marked **(Thomas OK)** is asked in the terminal and done only after his yes (spec §7: repo settings only in step 1, each with his OK).

- [ ] **Step 1: Install Docker Desktop (Thomas approved in the brainstorm)**

Thomas runs `! brew install --cask docker-desktop` (it needs his admin password) and starts it once (`! open -a Docker`). Then check: `docker info --format '{{.Architecture}}'` prints `aarch64`.

- [ ] **Step 2: Write `.gitignore` before anything is staged**

Contents: the HA-NortecGo `.gitignore` list (secrets, `local/`, `.claude/settings.local.json`, Python caches, `config/`, `.DS_Store`, build dirs, HA logs/state) plus `.superpowers/`, `node_modules/`, `cards/dist/`, `custom_components/ha_fitness/frontend/*.js`, `custom_components/ha_fitness/frontend/*.map`.

Run: `git init -b main && git check-ignore -q .superpowers .DS_Store && echo ignored`
Expected: `ignored`

- [ ] **Step 3: Create the GitHub repo (Thomas OK)**

Run: `gh repo create thomas3650/Ha-Fitness --public --description "Circuit training at home with Home Assistant: add-on, integration and cards"`, then (Thomas OK, HACS requires topics) `gh repo edit thomas3650/Ha-Fitness --add-topic home-assistant,hacs,homeassistant-integration,homeassistant-addon,fitness`.

- [ ] **Step 4: Bootstrap commit on `main` (the only direct commit to `main`)**

Stage only `.gitignore` and a one-line `README.md` (`# HA Fitness`), commit `chore: bootstrap repository`, add the remote, `git push -u origin main`.

- [ ] **Step 5: Milestone and issues (Thomas OK covered by "create GitHub issues" in the spec's way of working)**

Create milestone `v1`, then one issue per spec §10 step 1–8, each titled after the step and linking the spec section; label none. Note the number of the step-1 issue (`#1` expected) for the PR.

- [ ] **Step 6: Branch**

Run: `git switch -c feat/ground-structure`

---

### Task 2: Repo base, guards, and moving the initial design

**Model:** opus · **Review:** no

**Files:**
- Create: `LICENSE`, `README.md` (replace stub), `pyproject.toml`, `.pre-commit-config.yaml`, `.github/pull_request_template.md`, `.github/dependabot.yml`, `.python-version`
- Modify: `.claude/settings.json` (exists, holds `enabledPlugins`)
- Move: `Inital design/docs/mockups/` → `docs/mockups/` (all HTML, PNG, `README.md`, `gifs/`)
- Delete: `Inital design/` (everything left after the move)
- Keep: `docs/superpowers/specs/2026-10-23-ha-fitness-design.md`, `docs/superpowers/plans/2026-10-23-ground-structure.md`

**Interfaces:**
- Produces: root uv project (the integration's dev env) with dev group `pytest-homeassistant-custom-component`, `home-assistant-frontend==20260930.4` (the frontend pin of HA 2026.10.2; `frontend` setup imports it, and the test package doesn't bring it), `pytest-cov`, `ruff`, `mypy`, `pre-commit`, `actionlint-py`, `zizmor`; ruff/mypy config copied from HA-NortecGo's `pyproject.toml` with `known-first-party = ["custom_components.ha_fitness", "tests"]` and mypy `files = ["custom_components", "tests"]`.

- [ ] **Step 1: Write the files**

- `LICENSE`: MIT, © 2026 Thomas. `README.md` states that `docs/mockups/gifs/` and every exercise GIF are © Gym visual (via `hasaneyldrm/exercises-dataset`), personal use, not covered by the LICENSE.
- `README.md`: what HA Fitness is (spec §1, three sentences), status "in development", install (add the repo URL as an add-on repository; add it to HACS as a custom integration repository), link to `docs/README.md`.
- `.pre-commit-config.yaml`: HA-NortecGo's file as is (no-commit-to-branch main, check-yaml/json/toml, end-of-file, trailing-whitespace, detect-private-key, check-added-large-files excluding `uv.lock` and `docs/mockups/`, ruff via `uv run`, gitleaks, actionlint, zizmor, no-push-to-main). Ruff hooks also run on `addon/server/` (ruff reads the root config). `ruff-format` excludes `docs/superpowers/` (plan snippets are fragments, not whole programs).
- `.claude/settings.json`: `enabledPlugins` superpowers; `permissions.deny` exactly HA-NortecGo's push-to-main and `--no-verify` patterns (no `AskUserQuestion` deny, no hooks).
- PR template: What and why; `Closes #`; checklist: gates pass, PR title type per `docs/releasing.md`, UI change → Chrome screenshot at 1368×912 and no console errors, docs updated, lasting decision → `docs/decisions.md`, nothing from the real HA, `full-reviewer` run.
- `dependabot.yml`: github-actions, uv (`/` and `/addon/server`), npm (`/cards`), pre-commit; monthly, grouped, `chore` prefix.

- [ ] **Step 2: Move the mockups and delete the initial design**

Run: `mkdir -p docs && mv "Inital design/docs/mockups" docs/mockups && rm -rf "Inital design"`, then delete any `.DS_Store` under `docs/`.

- [ ] **Step 3: Verify**

Run: `git status --short` (nothing from `.superpowers/`, `config/`, `local/`), `git add -A`, then `uv sync && uv run pre-commit install && uv run pre-commit run --all-files` (pre-commit checks tracked/staged files only, hence the `git add` first)
Expected: all hooks pass (after any auto-fixes are re-staged once).
Run: `test ! -e "Inital design" && ls docs/mockups/TimerDuo.png docs/mockups/gifs/burpee.gif`
Expected: both paths listed.

- [ ] **Step 4: Commit**

`git add -A && git commit -m "chore: repo base, guards and mockups"` (check `git status` first: nothing from `.superpowers/`).

---

### Task 3: Add-on and server skeleton

**Model:** opus · **Review:** yes

**Files:**
- Create: `addon/config.yaml`, `addon/Dockerfile`, `addon/.dockerignore` (`server/.venv`, `**/__pycache__`, `**/.mypy_cache`, `**/.pytest_cache`, `**/.ruff_cache`), `addon/CHANGELOG.md`, `addon/DOCS.md`, `addon/README.md`, `addon/icon.png`, `addon/logo.png` (placeholder PNGs generated with a few lines of Python/Pillow or ImageMagick: 128×128 and 250×100, a plain orange `#FF8A3D` shape), `repository.yaml`
- Create: `addon/server/pyproject.toml`, `addon/server/uv.lock`, `addon/server/src/ha_fitness_server/__init__.py`, `.../__main__.py`, `.../app.py`, `.../settings.py`
- Test: `addon/server/tests/test_health.py`

**Interfaces:**
- Produces:
  - `ha_fitness_server.__version__: str` — `"0.0.0"`, the line ends with `# x-release-please-version`.
  - `ha_fitness_server.app.API_VERSION: int = 1`
  - `ha_fitness_server.app.create_app(settings: Settings) -> fastapi.FastAPI`
  - `ha_fitness_server.settings.Settings` — frozen dataclass: `port: int` (env `HA_FITNESS_PORT`, default `8765`), `data_dir: pathlib.Path` (env `HA_FITNESS_DATA_DIR`, default `/data`); `Settings.from_env() -> Settings`.
  - `GET /api/v1/health` → `200 {"status": "ok", "version": __version__, "api_version": 1}`.
  - `python -m ha_fitness_server` runs uvicorn on `0.0.0.0:<port>`; creates `data_dir` if missing.
  - `addon/config.yaml`: `name: HA Fitness`, `slug: ha_fitness`, `version: "0.0.0"  # x-release-please-version`, `arch: [aarch64, amd64]`, `image: ghcr.io/thomas3650/ha-fitness-addon`, `init: false`, `ports: {8765/tcp: 8765}`, `ports_description` (en), `homeassistant_api: true`, `url` to the repo's `addon/` folder, `backup: hot`. No Ingress yet (the spike adds it).
  - `repository.yaml`: `name: HA Fitness`, `url: https://github.com/thomas3650/Ha-Fitness`, `maintainer: Thomas`.

- [ ] **Step 1: Write the failing tests**

```python
# addon/server/tests/test_health.py
async def test_health_reports_version_and_api_version(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "api_version": 1}

def test_settings_from_env_reads_port_and_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("HA_FITNESS_PORT", "9999")
    monkeypatch.setenv("HA_FITNESS_DATA_DIR", str(tmp_path / "d"))
    assert Settings.from_env() == Settings(port=9999, data_dir=tmp_path / "d")

def test_settings_defaults(monkeypatch):
    monkeypatch.delenv("HA_FITNESS_PORT", raising=False)
    monkeypatch.delenv("HA_FITNESS_DATA_DIR", raising=False)
    assert Settings.from_env() == Settings(port=8765, data_dir=Path("/data"))
```

`client` is an `httpx.AsyncClient` over `ASGITransport(create_app(Settings(port=0, data_dir=tmp_path)))`, in `conftest.py`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd addon/server && uv sync && uv run pytest -q`
Expected: FAIL (module `ha_fitness_server` has no `app`/`settings`).

- [ ] **Step 3: Implement `create_app`, `Settings`, `__main__`**

Dependencies: `fastapi`, `uvicorn`; dev: `pytest`, `pytest-asyncio`, `httpx`, `mypy`, `ruff`. `requires-python = ">=3.14"`, a build backend (`hatchling`), `asyncio_mode = "auto"`, its own `[tool.mypy]` with `strict = true` (mypy doesn't read the root config); ruff uses the root config. (Write `pyproject.toml` before Step 2's `uv sync`.)

- [ ] **Step 4: Run the tests to see them pass**

Run: `cd addon/server && uv run pytest -q && uv run mypy src tests && uv run ruff check . && uv run ruff format --check .`
Expected: all pass.

- [ ] **Step 5: Dockerfile, and a local image check**

`addon/Dockerfile`: `ARG BUILD_FROM=ghcr.io/home-assistant/base-python:3.14-alpine3.24`; installs the server from `server/` with uv (`uv sync --frozen --no-dev` into a venv, or `uv export` + `pip install`; builder's choice); `CMD` runs `python -m ha_fitness_server`; `LABEL io.hass.type=app` and the OCI labels as in `home-assistant/apps-example`.

Run: `docker build -t ha-fitness-addon:dev addon && docker run -d --rm --name haf -p 8765:8765 ha-fitness-addon:dev && curl --retry 20 --retry-connrefused --retry-delay 1 -sf localhost:8765/api/v1/health; docker stop haf`
Expected: `{"status":"ok","version":"0.0.0","api_version":1}`

- [ ] **Step 6: Commit**

`git commit -m "feat: add-on skeleton with health endpoint"` (stage `addon/`, `repository.yaml`).

---

### Task 4: Integration skeleton that serves the cards

**Model:** opus · **Review:** yes

**Files:**
- Create: `custom_components/ha_fitness/__init__.py`, `const.py`, `config_flow.py`, `cards.py`, `manifest.json`, `strings.json`, `translations/en.json`, `translations/da.json`, `brand/icon.png`, `frontend/.gitkeep`
- Create: `hacs.json`
- Test: `tests/conftest.py`, `tests/test_config_flow.py`, `tests/test_frontend.py`

**Interfaces:**
- Consumes: the cards bundle at `custom_components/ha_fitness/frontend/ha-fitness-cards.js` (built by Task 5; absent in a clean checkout).
- Produces:
  - `const.DOMAIN = "ha_fitness"`; `cards.FRONTEND_DIR: Path` (the `frontend/` folder; defined in `cards.py`, which is what tests patch); `const.CARDS_FILE = "ha-fitness-cards.js"`; `const.FRONTEND_URL_BASE = "/ha_fitness_frontend"`.
  - `cards.async_register_cards(hass: HomeAssistant, version: str) -> None` — registers `FRONTEND_URL_BASE` as a static path for `FRONTEND_DIR` (once per HA run) and adds `f"{FRONTEND_URL_BASE}/{CARDS_FILE}?v={version}"` as an extra JS module URL.
  - Config flow: step `user` with no fields creates an entry titled "HA Fitness"; `manifest.json` has `"single_config_entry": true`, `"config_flow": true`, `"version": "0.0.0"`, `"iot_class": "local_push"`, `"integration_type": "service"`, `"dependencies": ["frontend", "http"]`, `codeowners`, `documentation`, `issue_tracker`.
  - `hacs.json`: `{"name": "HA Fitness", "homeassistant": "2026.10.2", "zip_release": true, "filename": "ha_fitness.zip"}`.
  - Config flow texts in `translations/en.json` and `da.json` (title and description of step `user`, abort `single_instance_allowed`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config_flow.py
async def test_user_step_creates_entry(hass):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HA Fitness"

async def test_second_entry_is_refused(hass, config_entry):  # config_entry: MockConfigEntry added to hass
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"

# tests/test_frontend.py
async def test_setup_serves_cards_bundle(hass, hass_client, setup_entry, cards_bundle):
    # cards_bundle: monkeypatches custom_components.ha_fitness.cards.FRONTEND_DIR to tmp_path and writes a small JS file there
    client = await hass_client()
    response = await client.get(f"{FRONTEND_URL_BASE}/{CARDS_FILE}")
    assert response.status == 200
    assert "customElements" in await response.text()

async def test_setup_adds_cards_module_url(hass, setup_entry):
    urls = hass.data[frontend.DATA_EXTRA_MODULE_URL].urls
    assert any(u.startswith(f"{FRONTEND_URL_BASE}/{CARDS_FILE}?v=") for u in urls)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest -q tests`
Expected: FAIL (integration not found).

- [ ] **Step 3: Implement**

`async_setup_entry` calls `async_register_cards(hass, <manifest version>)` and returns `True`; `async_unload_entry` removes the module URL with `remove_extra_js_url` and returns `True` (the static path can't be unregistered, so its registration is guarded against a second setup). Static path with `cache_headers=False`. `brand/icon.png`: a generated 256×256 placeholder like Task 3's.

- [ ] **Step 4: Run the gates**

Run: `uv run pytest -q --cov=custom_components.ha_fitness --cov-report=term-missing && uv run mypy && uv run ruff check && uv run ruff format --check`
Expected: all pass; coverage reported.

- [ ] **Step 5: Commit**

`git commit -m "feat: integration skeleton that serves the cards bundle"`

---

### Task 5: Cards skeleton with language files

**Model:** opus · **Review:** yes

**Files:**
- Create: `cards/package.json`, `cards/package-lock.json`, `cards/tsconfig.json`, `cards/vite.config.ts`, `cards/eslint.config.js`, `cards/src/index.ts`, `cards/src/today-card.ts`, `cards/src/i18n/index.ts`, `cards/src/i18n/en.json`, `cards/src/i18n/da.json`
- Test: `cards/test/i18n.test.ts`, `cards/test/today-card.test.ts`

**Interfaces:**
- Produces:
  - `localize(language: string | undefined, key: string): string` in `src/i18n/index.ts`: looks the key up in the file for `language` (`"da"` or `"da-DK"` → Danish), falls back to English, then to the key itself.
  - Custom element `ha-fitness-today-card` (Lit), with `setConfig(config)` and a `hass` property; renders a heading from key `today.title` and the text from key `common.coming_soon`; registers itself in `window.customCards` with name "HA Fitness – today".
  - `en.json`: `{"today": {"title": "Today's training"}, "common": {"coming_soon": "Coming soon"}}`; `da.json`: `{"today": {"title": "Træning i dag"}, "common": {"coming_soon": "Kommer snart"}}`.
  - `npm run build` writes one ES module to `../custom_components/ha_fitness/frontend/ha-fitness-cards.js`; `npm run watch` does the same on change; `npm test` runs Vitest (happy-dom); `npm run lint` runs ESLint + `tsc --noEmit`.

- [ ] **Step 1: Write the failing tests**

```ts
// cards/test/i18n.test.ts
test("Danish for da and da-DK", () => {
  expect(localize("da", "today.title")).toBe("Træning i dag");
  expect(localize("da-DK", "today.title")).toBe("Træning i dag");
});
test("falls back to English, then to the key", () => {
  expect(localize("fr", "today.title")).toBe("Today's training");
  expect(localize(undefined, "today.title")).toBe("Today's training");
  expect(localize("da", "no.such.key")).toBe("no.such.key");
});
test("every English key exists in Danish", () => {
  expect(keysOf(da)).toEqual(keysOf(en));
});

// cards/test/today-card.test.ts
test("shows the Danish heading for a Danish user", async () => {
  const card = await mount({ language: "da" });   // creates <ha-fitness-today-card>, sets hass, awaits updateComplete
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Træning i dag");
});
test("shows the English heading for an English user", async () => {
  const card = await mount({ language: "en" });
  expect(getByRole(card.shadowRoot!, "heading").textContent).toContain("Today's training");
});
```

(`getByRole` from `@testing-library/dom`; `mount` and `keysOf` are small helpers in the test files.)

- [ ] **Step 2: Run them to see them fail**

Run: `cd cards && npm install && npm test` (`npm install` creates `package-lock.json`; CI uses `npm ci`)
Expected: FAIL (modules missing).

- [ ] **Step 3: Implement** `localize`, the card, `index.ts` (imports the card), the Vite library build (`emptyOutDir: false`, so `frontend/.gitkeep` survives).

- [ ] **Step 4: Run the gates and the build**

Run: `cd cards && npm test && npm run lint && npm run build && ls ../custom_components/ha_fitness/frontend/ha-fitness-cards.js`
Expected: tests and lint pass; the bundle exists; `git status` does not list it (ignored).

- [ ] **Step 5: Commit**

`git commit -m "feat: cards skeleton with English and Danish"`

---

### Task 6: Fast loop (dev HA + add-on server + cards watch)

**Model:** opus · **Review:** no

**Files:**
- Create: `scripts/setup`, `scripts/develop`, `scripts/smoke`, `scripts/dev_onboard.py`
- Create: `.env.example` (documents `HA_FITNESS_DEV_HA_URL`, `HA_FITNESS_DEV_HA_TOKEN`, both unused until step 3)

**Interfaces:**
- Produces:
  - `scripts/setup`: `uv sync`, `uv sync --project addon/server`, `npm ci --prefix cards`, `uv run pre-commit install`.
  - `scripts/develop`: builds the cards once, then starts the cards watch build and the add-on server (`HA_FITNESS_DATA_DIR=local/addon-data`, port 8765) in the background with pidfiles in `local/`, and dev HA (`uv run hass -c config`, not `exec`) in the foreground on `http://localhost:8123`, with `config/custom_components/ha_fitness` symlinked to the repo. A `trap` on EXIT stops the watch and the server, so stopping HA (`pkill -f "hass -c config"`) stops all three; `scripts/develop stop` does the same from another shell. First run creates `config/configuration.yaml` with `default_config:`.
  - `scripts/dev_onboard.py [--url URL]` (default `http://localhost:8123`): on a fresh instance, completes onboarding through HA's onboarding API with user `dev` / password `dev`, sets that user's frontend language to Danish (`frontend/set_user_data`, key `language`; onboarding's `language` field does not do this), and, unless `--no-entry`, creates the HA Fitness config entry; idempotent. Task 7 uses it with `--url http://localhost:7123 --no-entry`.
  - `scripts/smoke`: like HA-NortecGo's (foreground with a timer, log in `local/`), fails if HA doesn't start, if `ha_fitness` isn't set up, or on any ERROR from `custom_components`.
- `scripts/seed` (spec §9) is not part of this step: there is no data model yet. Step 3 adds it.
- macOS fact to keep (HA-NortecGo `docs/ha-notes.md`): `hass` started with `&` in a non-interactive shell crashes in Bluetooth; Claude runs `scripts/develop` with the Bash tool's `run_in_background`, and `scripts/smoke` in the foreground.

- [ ] **Step 1: Write the scripts.**

- [ ] **Step 2: Verify the fast loop**

Run `scripts/setup`, then `scripts/develop` with `run_in_background`, wait for `curl -sf localhost:8123/manifest.json`, run `uv run python scripts/dev_onboard.py`.
Run: `curl -s localhost:8765/api/v1/health && curl -sf -o /dev/null -w '%{http_code}\n' localhost:8123/ha_fitness_frontend/ha-fitness-cards.js`
Expected: the health JSON, then `200`. Stop with `scripts/develop stop`; then `lsof -i :8765 -i :8123` prints nothing.

- [ ] **Step 3: Verify smoke**

Run: `scripts/smoke`
Expected: `smoke: OK`.

- [ ] **Step 4: Commit**

`git commit -m "chore: fast dev loop scripts"`

---

### Task 7: Full loop (Supervisor dev container)

**Model:** opus · **Review:** no

**Files:**
- Create: `.devcontainer/supervisor/devcontainer.json`, `scripts/full-loop`

**Interfaces:**
- Consumes: Docker Desktop (Task 1), the add-on (Task 3).
- Produces:
  - `.devcontainer/supervisor/devcontainer.json`: `home-assistant/apps-example`'s `.devcontainer.json` (image `ghcr.io/home-assistant/devcontainer:5-apps`, privileged), with `appPort` `["7123:8123", "7357:4357", "8765:8765"]` and VS Code customizations dropped. It does **not** mount the repo at `/mnt/supervisor/apps/local/` (the Supervisor's local scan globs `**/config.*` and would walk `cards/node_modules`, `config/`, `local/`); it mounts only the staging folder `local/full-loop/` there.
  - Staging (verified in Supervisor source: it builds a local app only when `config.yaml` has no `image:`): `scripts/full-loop install` copies `addon/` to `local/full-loop/ha_fitness/` and removes the `image:` line from the copy.
  - `scripts/full-loop up|install|check|down`, driving `npx --yes @devcontainers/cli@<pinned>`: `up` starts the container and `supervisor_run` (detached) and waits for `http://localhost:7123`; `up` first runs `mkdir -p local/full-loop` (a bind mount needs its source), and after start runs `scripts/dev_onboard.py --url http://localhost:7123 --no-entry`; `install` stages the copy (without `server/.venv` and caches), runs `ha store reload` so the Supervisor sees it, then `ha apps install local_ha_fitness` then `ha apps start local_ha_fitness` (or `rebuild` when installed); `check` prints `curl -s localhost:8765/api/v1/health`; `down` stops and removes the container. Waits use `curl --retry`, not `sleep`.

- [ ] **Step 1: Write the files.**

- [ ] **Step 2: Bring it up and install the add-on**

Run: `scripts/full-loop up && scripts/full-loop install`
Expected: the Supervisor lists `local_ha_fitness` as installed and started (`ha apps info local_ha_fitness` inside the container shows `state: started`).

- [ ] **Step 3: Prove the add-on was built from the working tree, not pulled (Review Focus 4)**

Temporarily set `__version__ = "0.0.0-local"` (do not commit), run `scripts/full-loop install` (rebuild), then `scripts/full-loop check`.
Expected: `"version":"0.0.0-local"`. Restore `__version__`. (Task 10 records the staging reason in `docs/ha-notes.md`.)

- [ ] **Step 4: `scripts/full-loop down`, then commit**

`git commit -m "chore: full loop in the Supervisor dev container"`

---

### Task 8: CI

**Model:** opus · **Review:** yes

**Files:**
- Create: `.github/workflows/pr-title.yml`, `.github/workflows/ci.yml`, `.github/workflows/gitleaks.yml`

**Interfaces:**
- Produces the required checks for branch protection (Task 11): job names `pr-title`, `python`, `addon-server`, `cards`, `hassfest`, `hacs`, `addon-lint`, `addon-build`, `workflows`, `gitleaks`.
  - `pr-title.yml` (`pull_request`, types opened/edited/synchronize/reopened; not `pull_request_target`): `amannn/action-semantic-pull-request`, types `feat, fix, docs, test, chore, refactor, ci` (spec §8; no `perf`).
  - `ci.yml` (pull_request, push to `main`): `python` (root `uv sync --locked`, ruff, ruff format check, mypy, pytest with coverage); `addon-server` (same in `addon/server`); `cards` (`npm ci`, lint, test, build); `hassfest` (`home-assistant/actions/hassfest`); `hacs` (`hacs/action`, category integration); `addon-lint` (`frenck/action-addon-linter` on `addon/`); `addon-build` (`home-assistant/builder/actions/build-image` for aarch64 and amd64, `push: false`); `workflows` (`actionlint`, `zizmor --offline .github/workflows`).
  - `gitleaks.yml`: as HA-NortecGo.

- [ ] **Step 1: Write the workflows** (pins: look up each action's latest release and its commit SHA with `gh api`).

- [ ] **Step 2: Verify locally**

Run: `uv run actionlint && uv run zizmor --offline .github/workflows`
Expected: no findings.

- [ ] **Step 3: Commit**

`git commit -m "ci: PR title check, CI and gitleaks"`

(The workflows run for real on the PR in Task 11.)

---

### Task 9: Independent releases

**Model:** opus · **Review:** yes

**Files:**
- Create: `release-please-config.json`, `.release-please-manifest.json`, `.github/workflows/release-please.yml`, `.github/workflows/addon-image.yml`, `CHANGELOG.md`

**Interfaces:**
- Produces (spec §8, with the mechanism changes the plan review found; all verified against release-please v17.11.2 source):
  - Top level: `separate-pull-requests: true`, `bump-minor-pre-major: true`, `include-component-in-tag: true`.
  - Package `addon` (component `ha-fitness-addon`, release-type `simple`): `initial-version: "0.1.0"`, `changelog-path: "CHANGELOG.md"` (paths are **relative to the package**), `extra-files`: `{"type": "generic", "path": "config.yaml"}` and `{"type": "generic", "path": "server/src/ha_fitness_server/__init__.py"}` (generic updater with `# x-release-please-version` markers; the yaml updater would strip comments), `draft: true` and `force-tag-creation: true` (a non-public draft release plus a real tag, so release-please relabels the PR `autorelease: tagged` and finds the last release; HACS skips drafts; this replaces the spec's "no GitHub release"). Tags `ha-fitness-addon-v<version>`.
  - Package `.` (component `ha-fitness`, release-type `simple`): `initial-version: "0.1.0"`, `exclude-paths: ["addon"]`, `include-component-in-tag: false` (tags `v<version>`, what HACS reads), `draft: true` and `force-tag-creation: true` (the zip job publishes the release only after the zip is attached, so HACS never sees a release without it), `extra-files`: `{"type": "json", "path": "custom_components/ha_fitness/manifest.json", "jsonpath": "$.version"}`.
  - `.release-please-manifest.json`: `{"addon": "0.0.0", ".": "0.0.0"}`.
  - `release-please.yml` (push to `main`): `googleapis/release-please-action` with `token: ${{ secrets.RELEASE_PLEASE_TOKEN }}` (a fine-grained token for this repo only — contents, pull requests and issues read/write — so CI runs on release PRs and their events trigger workflows; Thomas creates it in Task 11). A second job, `integration-zip`, runs only when `steps.<id>.outputs.release_created == 'true'` (bare output names are path `.`; the add-on's are `addon--release_created` / `addon--tag_name`; verified in release-please-action v5.0.0): checks out `tag_name`, checks it equals `v` + `manifest.json` version, builds the cards, zips the **contents** of `custom_components/ha_fitness/` as `ha_fitness.zip`, fails unless the zip root has `manifest.json` and `frontend/ha-fitness-cards.js`, uploads it with `gh release upload`, then publishes the draft with `gh release edit <tag> --draft=false --latest`. (Not a separate `release: published` workflow: it would never run for a release created by the action's token if that ever falls back to `GITHUB_TOKEN`.)
  - `addon-image.yml` (push to `main`, paths `addon/config.yaml`): if `version` changed against the parent commit, builds and pushes `ghcr.io/thomas3650/ha-fitness-addon:<version>` and `:latest` for aarch64 + amd64 with the `home-assistant/builder` actions pinned at `2026.09.0` (as in `apps-example`'s `build-app.yaml`), then the multi-arch manifest.

- [ ] **Step 1: Write the config and workflows**

- [ ] **Step 2: Lint**

Run: `uv run actionlint && uv run zizmor --offline .github/workflows && python3 -m json.tool release-please-config.json >/dev/null`
Expected: clean.

- [ ] **Step 3: Commit**

`git commit -m "ci: independent releases for the add-on and the integration"`

- [ ] **Step 4: Zip check, locally**

Run the zip commands from the `integration-zip` job on the working tree (after `npm run build --prefix cards`), then `unzip -l ha_fitness.zip`.
Expected: `manifest.json` and `frontend/ha-fitness-cards.js` at the zip root. Delete the zip.

- [ ] **Step 5: Dry runs (Review Focus 1) — run by the controller in Task 11 Step 1, because they need the pushed branch and implementers never push**

For each scenario, a separate scratch branch from `feat/ground-structure` whose `release-please-config.json` adds top-level `"last-release-sha": "<tip of feat/ground-structure>"` (otherwise release-please reads every earlier commit and all scenarios bump both components), plus one throwaway commit:
- A: `feat: x` touching only `cards/` → only `ha-fitness` would be released, as `0.1.0`, and the PR it would open changes `custom_components/ha_fitness/manifest.json`;
- B: `feat: y` touching only `addon/` → only `ha-fitness-addon`, `0.1.0`, changing `addon/config.yaml` and `addon/server/src/ha_fitness_server/__init__.py`;
- C: `docs: z` touching only `docs/` → nothing.

Run for each: `npx --yes release-please@<pinned> release-pr --dry-run --repo-url=thomas3650/Ha-Fitness --target-branch=<scratch> --token="$(gh auth token)"`. Delete the scratch branches (local and remote). A dry run cannot show releases being created; Task 11 Step 10 checks those.

---

### Task 10: Docs and agents

**Model:** opus · **Review:** no (the full-reviewer reads all of it)

**Files:**
- Create: `CLAUDE.md`, `docs/README.md`, `docs/way-of-working.md`, `docs/decisions.md`, `docs/releasing.md`, `docs/architecture.md`, `docs/domain-language.md`, `docs/testing.md`, `docs/notes.md`, `docs/ha-notes.md`
- Create: `.claude/agents/implementer.md`, `.claude/agents/task-reviewer.md`, `.claude/agents/full-reviewer.md`
- Modify: `docs/mockups/README.md` (add: reference only; dark/English/1280×800; feature specs of steps 4–6 replace screens with light/Danish/3:2)

**Interfaces:**
- Each doc holds what spec §7's docs table says, written as the current state of the repo (commands that exist after Tasks 2–9), pointing to the spec instead of copying it where it is a snapshot. One fact in one place.
- `CLAUDE.md`: what the repo is (spec §1 in three lines), layout, commands (the gates of Tasks 3–5, `scripts/*`), hard rules (from spec §6–§8 and Global Constraints: no `main`, public repo, never committed list, no HA changes from this project, tests through public interfaces, every UI text from a language file), imports `@docs/way-of-working.md` and `@docs/README.md`.
- `docs/decisions.md`: D1… one entry per lasting decision in the spec (add-on + integration + cards; FastAPI; FastMCP with hand-written tools; SQLite with program JSON documents; SQLAlchemy + Alembic; websocket push; Lit + TS; independent releases; strict semver and the house `fitness` issue; English base + Danish; public repo; GIFs downloaded, never in repo/image; port 8765; and from this plan: add-on releases are GitHub **draft** releases with a forced tag instead of no release (spec §8 said "no GitHub release"; release-please stalls with `skip-github-release`, prereleases stop being prereleases at 1.0.0, and HACS skips drafts — same goal, different mechanism); integration releases start as drafts and are published once the zip is attached, `bump-minor-pre-major`, `initial-version 0.1.0`, the `RELEASE_PLEASE_TOKEN` and why), each with Source = spec section. Format as HA-NortecGo's §7 *Decision log*.
- `docs/releasing.md`: PR titles and bumps; the two components; what each workflow does; after a release Claude opens a `fitness` issue in `thomas3650/house` (part, version, "major" when it is — and "breaking" for a 0.x minor bump that came from `!` — what changed, checks to run); until the house rule for 0.x is confirmed, every 0.x release is announced to Thomas; the full loop before every release; only the multi-arch GHCR package `ha-fitness-addon` must be public; the `RELEASE_PLEASE_TOKEN` (what it may do, its expiry date, how Thomas renews it); if the `integration-zip` job fails, the integration release stays a draft (safe: HACS doesn't see it, release-please counts it as released): re-run the failed job, or upload the zip and publish with the same two `gh` commands by hand.
- `docs/testing.md`: fast loop, full loop, Chrome at 1368×912 (dev user `dev`/`dev`, language Danish), MCP check from Claude Code (from step 2 on).
- `docs/notes.md`: the interaction-limit renewal date and the token expiry date (filled in Task 11).
- `docs/ha-notes.md`: the Supervisor builds a local app only without `image:` (why the full loop stages a copy); `frontend` setup needs `home-assistant-frontend` in tests; the macOS background-`hass` fact.
- Agents: HA-NortecGo's three agent files, adapted: repo description "HA Fitness: HA add-on + custom integration + Lovelace cards for circuit training at home"; models/effort per Global Constraints; gate commands from `CLAUDE.md`; no guard-hook, `Guarded files`, PO, `local/`/`config/` rules beyond "never read `.env`, `config/`, `local/`"; task-reviewer only for tasks marked `Review: yes`.

- [ ] **Step 1: Write the docs and agents.**

- [ ] **Step 2: Check links**

Write `scripts/check_links.py` (a few lines: for each Markdown file in `CLAUDE.md`, `README.md`, `docs/**/*.md`, resolve every relative link target and every `@path` import against the file's own folder; skip `http(s)` and `#anchor` links; print missing ones; exit 1 if any). Add it to the `workflows` CI job.
Run: `uv run python scripts/check_links.py`
Expected: no output, exit 0.

- [ ] **Step 3: Commit**

`git commit -m "docs: way of working, decisions, releasing, architecture, testing and agents"`

---


### Task 11: PR, review, merge, first release (controller)

**Model:** controller · **Review:** no

- [ ] **Step 1:** Push `feat/ground-structure`; run Task 9 Step 5 (the release-please dry runs). If they fail, an implementer fixes the config as a Task 9 fix round, reviewed by `task-reviewer`.
- [ ] **Step 2:** Open the PR, title `feat: ground structure`, body per the template, `Closes #<step-1 issue>`, links to the spec and plan by commit SHA.
- [ ] **Step 3: Chrome check.** Start the fast loop, log in as `dev`, add the `custom:ha-fitness-today-card` to a dashboard, window 1368×912; screenshot with the user's language Danish and English; no console errors. Screenshots go in the PR description.
- [ ] **Step 4:** CI green; `full-reviewer` on the branch until Ready (≤ 5 rounds); fixes via implementer.
- [ ] **Step 5 (Thomas OK):** branch protection on `main`: require the Task 8 checks and the PR title check, squash merge only, no force-push; interaction limit "collaborators only" (6 months), renewal date into `docs/notes.md` on this branch.
- [ ] **Step 6 (Thomas does it):** Thomas creates a fine-grained personal access token for `thomas3650/Ha-Fitness` only (Contents, Pull requests, Issues: read and write; expiry 1 year) and runs `! gh secret set RELEASE_PLEASE_TOKEN -R thomas3650/Ha-Fitness`. Its expiry date goes into `docs/notes.md` on this branch.
- [ ] **Step 7:** Squash-merge the PR.
- [ ] **Step 8:** release-please opens two release PRs (`0.1.0` each), and CI runs on them. Run `scripts/full-loop` once more on `main` (the pre-release full loop, spec §8), then merge both release PRs.
- [ ] **Step 9 (Thomas OK):** make the GHCR package `ha-fitness-addon` public (only the multi-arch package; the per-arch `aarch64-`/`amd64-` packages can stay private). Then, logged out (`docker logout ghcr.io`): `docker pull --platform linux/arm64 ghcr.io/thomas3650/ha-fitness-addon:0.1.0` succeeds.
- [ ] **Step 10: Release checks (Review Focus 2, 5, 6).** `gh release list` shows `v0.1.0` as Latest (not draft) and `ha-fitness-addon-v0.1.0` as Draft; `git ls-remote --tags origin ha-fitness-addon-v0.1.0` shows the tag; `gh release download v0.1.0 -p ha_fitness.zip` and `unzip -l` shows `frontend/ha-fitness-cards.js`; both release PRs carry the label `autorelease: tagged`; after the next push to `main`, the release-please run's log has no "untagged, merged release PRs outstanding".
- [ ] **Step 11:** Send ha-claude-a8 the repo URL, the add-on slug `ha_fitness` and the integration domain `ha_fitness`. Open a `fitness` issue in `thomas3650/house`: both parts 0.1.0, skeleton only, checks: the add-on starts and `http://<ha-host>:8765/api/v1/health` answers on the LAN; the integration can be added and the "HA Fitness – today" card renders in Danish on the kitchen tablet. Tell Thomas it needs his yes.
