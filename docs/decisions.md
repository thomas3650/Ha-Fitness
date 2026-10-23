# Decisions

Lasting decisions, newest last. Each entry is short and points to where the reasoning is. Entries aren't edited, except
to set their status to `superseded by D<n>`, or to name a part a later decision superseded. How to add one:
[`way-of-working.md`](way-of-working.md) §5.

### D1: Three parts: add-on, integration, cards
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** HA Fitness is an add-on (the server: data, scheduler, sessions, MCP and REST), a custom integration
  (entities, services, events, the cards' websocket relay, the media proxy) and Lovelace cards built into the
  integration.
- **Why:** v2 needs a program editor, which gets a natural home as the add-on's website in the HA sidebar, and MCP can
  run on the add-on's own port.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §4

### D2: FastAPI on uvicorn for the add-on server
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on server is Python (uv) with FastAPI on uvicorn.
- **Why:** OpenAPI for free; its Pydantic models are the one program schema for REST, MCP, validation and
  import/export; it can mount the MCP app on the same port.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §5

### D3: FastMCP with hand-written tools
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** MCP is FastMCP mounted at `/mcp` in the same FastAPI app. Each tool is written by hand as a thin
  adapter over the service layer; REST is not converted to MCP.
- **Why:** LLMs do better with curated tools, and the tools need LLM-oriented descriptions, close-match errors and
  destructive hints.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §5

### D4: SQLite, each program one JSON document
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The database is SQLite in the add-on's `/data`. Each program is stored as one validated JSON document;
  training days, sessions, participants and the change log are ordinary tables.
- **Why:** `/data` is part of HA backups. A program is validated, imported and exported as one document with the
  API's JSON schema (spec §3.7).
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §5

### D5: SQLAlchemy 2 and Alembic, migrations from the first schema
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Database access uses SQLAlchemy 2. Alembic migrations exist from the first schema on.
- **Why:** Real data exists from step 3 on, so every schema change after that must migrate it.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §5, §10

### D6: A websocket pushes changes from the add-on to the integration
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on offers one websocket push channel; the integration subscribes to it.
- **Why:** Session state lives in the add-on, and the cards count down locally, so only changes need to be sent.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §3.4, §5

### D7: Lit and TypeScript for the cards
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The cards (and later the v2 website) are Lit + TypeScript.
- **Why:** Home Assistant's own frontend is built on Lit, and the cards run inside it.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §5

### D8: The add-on and the integration are released independently
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on and the integration with its cards are released independently, each triggered by changes in
  its own folders. release-please in manifest mode runs two components.
- **Why:** Each part updates on its own in Home Assistant (the add-on store and HACS), so a change to one part
  shouldn't release the other.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §8; [`releasing.md`](releasing.md)

### D9: Strict semver, driven by Conventional Commit PR titles
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Versions are strict semver. The PR title is a Conventional Commit and decides the bump: `feat` minor,
  `fix` patch, `!` major; other types release nothing.
- **Why:** HA's update entities show the versions, and the house assistant decides from them.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §8

### D10: A `fitness` issue in the house repo after each release
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** After each release Claude opens an issue in `thomas3650/house` with the label `fitness`: the part, the
  version, "major" when it is, what changed, and the checks to run after installing.
- **Why:** The house assistant installs the updates on the real Home Assistant; this project makes no changes there.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §8

### D11: English base, Danish shipped, every UI text from a language file
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Everything is built in English and every UI text comes from a language file. v1 ships English and
  Danish. The integration uses HA's translations; the cards have their own files and follow the HA user's language.
  Exercise names and instructions are never translated.
- **Why:** The kitchen tablet runs in Danish, while the exercise dataset is English.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §3.4

### D12: A public repo, only Thomas opens PRs
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `thomas3650/Ha-Fitness` is public. Interaction limits (collaborators only), branch protection with
  required checks and no other collaborators keep PRs to Thomas's login. A fixed list of things is never committed
  (`CLAUDE.md`, hard rule 3).
- **Why:** Thomas's choice; the add-on store and HACS install from it.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §7

### D13: Exercise GIFs are downloaded, never in the repo or the image
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on downloads the filtered GIF set from a pinned commit of `hasaneyldrm/exercises-dataset` into
  `/data` on first start. The GIFs are never committed and never built into the image. The 12 mockup GIFs in
  `docs/mockups/gifs/` are the one exception.
- **Why:** The GIFs are © Gym visual for personal use, and the repo and the image are public.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §3.6, §7

### D14: Thomas approves specs; Claude approves plans, merges and tests
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Superpowers specs and plans. Thomas approves specs; Claude approves plans after `full-reviewer` rates
  them Ready, and merges and tests. Three agents: `implementer` and `task-reviewer` on Opus/medium, `full-reviewer` on
  Opus/high. No PO or team-lead sessions.
- **Why:** A small project; the lighter flow keeps Thomas on the decisions that matter.
- **Source:** [spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §6; [`way-of-working.md`](way-of-working.md)

### D15: The add-on's port is 8765
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on serves REST (and later MCP) on port 8765/tcp. The API version starts at 1.
- **Why:** Claude's call: the spec gives the add-on its own port and leaves the number to the builder (§11).
- **Source:** [ground-structure plan](superpowers/plans/2026-10-23-ground-structure.md), Global Constraints

### D16: Add-on releases are draft GitHub releases with a forced tag
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** release-please creates the add-on's release as a **draft**, with `force-tag-creation`, so a real tag
  `ha-fitness-addon-v<version>` exists. This replaces spec §8's "no GitHub release" for the add-on.
- **Why:** The goal stays the same: HACS must never see an add-on release. Without a release (`skip-github-release`)
  release-please stalls on the next run; prereleases stop being prereleases at 1.0.0; HACS skips drafts.
- **Source:** [ground-structure plan](superpowers/plans/2026-10-23-ground-structure.md), Task 9 and Review Focus 2

### D17: Integration releases start as drafts; first version 0.1.0; a breaking 0.x change bumps minor
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The integration's release is created as a draft and published by the `integration-zip` job once
  `ha_fitness.zip` is attached. Both components use `initial-version: 0.1.0` and `bump-minor-pre-major: true`.
- **Why:** HACS never sees a release without its zip. Without `initial-version` the first release is 1.0.0; without
  `bump-minor-pre-major` a breaking change during 0.x jumps to 1.0.0.
- **Source:** [ground-structure plan](superpowers/plans/2026-10-23-ground-structure.md), Global Constraints, Task 9

### D18: release-please runs with a fine-grained token
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `release-please.yml` uses the secret `RELEASE_PLEASE_TOKEN`: a fine-grained token for this repo only
  (Contents, Pull requests, Issues: read and write). It falls back to `github.token` if the secret is gone.
- **Why:** Pull requests opened with `github.token` trigger no workflows, so CI wouldn't run on the release PRs.
- **Source:** Thomas, 2026-10-23; [`releasing.md`](releasing.md#the-release-please-token)

### D19: The house installs the same major on its own; a new major asks Thomas
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The house assistant installs any HA Fitness release with the same major as the installed one without
  asking. A new major, including 0.x → 1.0.0, asks Thomas. This supersedes spec §8's "until 1.0.0, every install needs
  his yes".
- **Why:** Thomas confirmed this rule in the house session. A 0.x release therefore reaches the house without a human
  check, so the full loop before every release is mandatory, and a breaking 0.x change is called "breaking" in the
  `fitness` issue.
- **Source:** Thomas, 2026-10-23 (house session); [`releasing.md`](releasing.md#after-a-release)

### D20: Reviewers are read-only and do no mutation testing
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Review agents never modify a file, even temporarily: no mutation testing, no stash, no checkout. A
  doubt about a test is a finding. Fixes go to an implementer.
- **Why:** A reviewer that edits the tree can leave it changed or mix its edits into the work under review.
- **Source:** Thomas, 2026-10-23

### D21: No repository topics for now
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The repo has no GitHub topics. It is added to HACS as a custom repository, and the CI `hacs` job
  ignores the topics check.
- **Why:** Topics only matter for a listing in HACS's default store. Add them if it should be listed there.
- **Source:** Thomas, 2026-10-23

### D22: `home-assistant/actions` is pinned to a `master` commit
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `home-assistant/actions` (hassfest, the add-on info helper) is pinned to a `master` commit SHA with a
  dated comment. This is the one exception to pinning to a release.
- **Why:** Its only release is 1.0.0, from 2020.
- **Source:** [ground-structure plan](superpowers/plans/2026-10-23-ground-structure.md), Task 8

### D23: Commits use Thomas's GitHub no-reply email
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** Commits in this repo use Thomas's GitHub no-reply email, set in the repo's git config.
- **Why:** GitHub refuses pushes that would publish his private email. How to set it: [`notes.md`](notes.md).
- **Source:** Thomas, 2026-10-23

### D24: The add-on server's package version comes from `__version__`
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `addon/server/pyproject.toml` has a dynamic version, read by hatchling from
  `ha_fitness_server/__init__.py`.
- **Why:** release-please bumps the server's version in one place (with `addon/config.yaml`).
- **Source:** [ground-structure plan](superpowers/plans/2026-10-23-ground-structure.md), Task 9

### D25: A breaking change during 0.x stays a minor bump
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `bump-minor-pre-major` stays on (D17): a breaking change during 0.x releases the next minor, which the
  house installs on its own (D19). The `fitness` issue calls it breaking.
- **Why:** The contract rule (the integration supports the current and the previous API version) and the house's
  refusal to install during a workout already protect the house. Jumping to 1.0.0 early would make every later 1.x
  install itself anyway.
- **Source:** Thomas, 2026-10-23

### D26: MCP is mounted at the root and serves `/mcp` itself
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** The add-on builds FastMCP's app with `http_app(path="/mcp")` and mounts it at `/`, after all FastAPI
  routes. FastMCP's lifespan is combined with the app's (`combine_lifespans`).
- **Why:** Mounted at `/mcp`, the endpoint is `/mcp/` and `/mcp` answers with a 307 redirect. Without its lifespan
  every MCP call fails.
- **Source:** step 2 spike (#2), FastMCP 4.1.3

### D27: Ingress uses the API port
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `ingress_port` is 8765, the API's port. The add-on's web page is served at `/` with relative links
  only.
- **Why:** One server and one port; Ingress requests reach the same app under `X-Ingress-Path`. The v2 program editor
  lives at the same place.
- **Source:** step 2 spike (#2)

### D28: The add-on announces itself through Supervisor discovery
- **Date:** 2026-10-23 · **Status:** active
- **Decision:** `config.yaml` lists `discovery: [ha_fitness]`. At each start the add-on posts the service `ha_fitness`
  with `{"host": <its hostname>, "port": 8765}`; the integration takes it in `async_step_hassio`. The fast loop uses a
  configured URL instead (spec §4).
- **Why:** HA offers the integration as soon as the add-on runs, with the right address, and nobody types a URL.
- **Source:** step 2 spike (#2); spec §4

### D29: Only integration paths release the integration
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The root release-please component excludes `addon`, `docs`, `scripts`, `tools`, `.github`,
  `.devcontainer` and `.claude`.
- **Why:** A feature PR changes code and its docs together (`way-of-working.md` §5). With only `addon` excluded, an
  add-on feature with docs also released an unchanged integration.
- **Source:** the step 3 spec (programs through chat) §12; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D30: The library's data is built in; its media is downloaded
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The filtered exercise data (721 records, English steps) is committed as
  `addon/server/src/ha_fitness_server/library/exercises.json` and ships in the image. Only the GIFs and thumbnails are
  downloaded, into the data folder (D13).
- **Why:** The data is MIT licensed, the media is Gym visual's. Built-in data makes search work offline from the first
  start, and tests need no network.
- **Source:** [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md) §3.1; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D31: Hot backups hold a `VACUUM INTO` snapshot, not the live database
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** Backups stay hot. `backup_pre` writes a consistent copy of the database to `backup/snapshot.db` with
  SQLite's `VACUUM INTO`, and `backup_exclude` leaves out the live database files and the media. A start with no
  database and a snapshot restores the snapshot.
- **Why:** A backup must never stop a running workout, and a raw copy of a WAL database while it runs can be
  inconsistent.
- **Source:** [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md) §10; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D32: The dev HA token lives in `local/dev-ha-token`
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** `scripts/dev_onboard.py` keeps a long-lived token for the dev user in `local/dev-ha-token` (mode 600).
  The fast loop's add-on server reads it at each call through `HA_FITNESS_HA_TOKEN_FILE`. Nothing reads `.env`. This
  replaces design spec §4's token from a git-ignored `.env`.
- **Why:** The token is made by a script, not by hand, and a token written after the server started works without a
  restart.
- **Source:** [step 3 spec](superpowers/specs/2026-10-24-programs-through-chat-design.md) §11; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D33: Person ids are never reused
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The `people` table uses `AUTOINCREMENT`, so a removed person's id is never given out again.
- **Why:** Step 5's history is keyed on the person id. A reused id would hand a removed person's history to someone new.
- **Source:** the step 3 build (Task 5 review); Claude, 2026-10-24
