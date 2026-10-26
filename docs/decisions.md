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
- **Date:** 2026-10-23 · **Status:** active; the filtered part superseded by D64
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
- **Date:** 2026-10-24 · **Status:** active; the filtered part superseded by D64
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

### D34: The scheduler's rules
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The scheduler handles each local date from the day after the last handled one up to and including
  today, and today again on every run. The first run starts at today and makes up no past days. Program writes
  reconcile first, then act: switching off or deleting removes the program's open days (closed days stay), a rename
  renames its open days, and a weekday change leaves existing days alone. So a pause on a day the program doesn't
  train removes its late day, which then never counts as missed. `training_days` uses `AUTOINCREMENT`, so an id
  removed by a switch-off, a delete or the dev DELETE is never given out again; the card and the service skip by id.
- **Why:** A program made or switched on in the morning reminds the same day. Counting starts when the app is live.
  Reconciling first means a write right after midnight never changes a day that should already be closed.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §3.3; reconcile-first: the step 4
  build (Task A2 review); Claude, 2026-10-24 (Thomas's delegation for the night)

### D35: The push channel's protocol
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** `GET /api/v1/ws` sends `hello` (with `api_version`), then `today`. After that it sends a new `today`
  whenever `/today` changes, and one `event` (`due`, `skipped`, `missed`) per state change of a training day. The
  client sends nothing, unknown message types are ignored on both sides, and events are fire-and-forget.
- **Why:** The `today` state alone is enough to draw the card after any reconnect, and ignoring unknown types keeps
  the protocol forward compatible. This makes D6 concrete.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §3.6; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D36: The add-on's timezone comes from the environment
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The add-on's local time comes from `HA_FITNESS_TIMEZONE`, else `TZ`, else UTC with a log line. A
  change takes effect at the add-on's next start. The `tzdata` package ships the zone data.
- **Why:** The Supervisor passes HA's timezone as `TZ`, so the add-on needs no call to HA for midnight. The fast loop
  sets `HA_FITNESS_TIMEZONE`, so a `TZ` in the Mac's shell doesn't matter.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §3.2; Claude, 2026-10-24
  (Thomas's delegation for the night)

### D37: A 0.x integration may need a newer add-on, through `addon_too_old`
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** While both parts are 0.x, an integration release may need a newer add-on. It must say so through the
  `addon_too_old` repair issue, and the release's `fitness` issue states the install order. From 1.0.0 on, the
  contract rule of [`architecture.md`](architecture.md#the-contract-between-the-add-on-and-the-integration) holds
  without exception.
- **Why:** The add-on of step 3 has no push channel, and the integration of step 4 can't work without one. A repair
  issue tells the user what to update, instead of entities that stay unavailable with no reason given.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §4.2, where it is numbered D36;
  Claude, 2026-10-24 (Thomas's delegation for the night)

### D38: The card's `language` option
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** A card takes an optional `language` in its config. Its texts follow that option, else the HA user's
  language (`hass.locale.language`), else English. This extends D11.
- **Why:** The house sets `language: da` on its cards, so a card's language doesn't depend on the logged-in user's
  profile. Weekday names come from the language files too, not from `Intl`, so hard rule 6 holds.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §5, where it is numbered D37;
  Claude, 2026-10-24 (Thomas's delegation for the night)

### D39: Entry version 2, with the unique id `ha_fitness` and no `single_config_entry`
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The config entry is version 2: its data is the add-on's URL, and every flow sets the unique id
  `ha_fitness`, so a second entry aborts as `already_configured`. `manifest.json` has no `single_config_entry`. A
  version 1 entry is migrated to `http://localhost:8765` with that unique id.
- **Why:** `single_config_entry` makes HA abort a discovery before the flow runs, so an existing entry could never get
  the add-on's new address ([`ha-notes.md`](ha-notes.md#the-integration)). The unique id keeps one entry and lets the
  discovery update it.
- **Source:** [step 4 spec](superpowers/specs/2026-10-24-training-today-design.md) §4.1, where it is numbered D38;
  Claude, 2026-10-24 (Thomas's delegation for the night)

### D40: The session engine lives in the add-on
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The add-on runs sessions. A start freezes the plan (the program's timing and stations, the
  participants and their names). Phases run on deadlines chained from each other, ticked by a loop and before every
  command and read. Only one session is running or paused at a time. At shutdown a running session is paused; after a
  crash it is paused at its `last_tick_at`. A session paused for 30 minutes is ended at `paused_at + 30 min`.
- **Why:** One source of truth that survives a closed tablet or a reload, with no drift. A restart never skips phases
  or completes a workout nobody did, and a forgotten session can't keep the tablet awake for ever.
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3.1–§3.3; the pause limit's end time:
  the step 5 build (Task S3); Claude, 2026-10-24 (Thomas's delegation for the night)

### D41: No switch after the last interval
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** A session has no switch phase after the last interval of the last round; it ends when the last work
  phase ends. The program's `total_seconds` stays the planned length shown before a workout.
- **Why:** There is no station to move to, so a final switch would only be dead time before Done.
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3.1; Claude, 2026-10-24 (Thomas's
  delegation for the night)

### D42: A day under a session stays open, and its program is locked
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** Reconcile leaves an open training day alone while a session for it is running or paused, and skipping
  it gives a 409. Switching off or deleting the program of a running or paused session gives a 409, extra sessions
  included.
- **Why:** A session that crosses midnight, or a Claude edit during a workout, must not close the day as missed or
  pull the program away; no day is ever missed and then done.
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3.4; Claude, 2026-10-24 (Thomas's
  delegation for the night)

### D43: The snapshot is also written at shutdown
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The lifespan's shutdown pauses a running session, then writes the backup snapshot of D31.
- **Why:** The Supervisor runs `backup_pre` only in a running add-on, so a backup of a stopped add-on held the
  snapshot of the last backup. Now it holds the data as of the stop; only a crash leaves an older one (#20).
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §3.6; Claude, 2026-10-24 (Thomas's
  delegation for the night)

### D44: Exercise media reaches the cards only through an authenticated proxy
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The cards load an exercise's GIF or thumbnail only from the integration's view
  `/api/ha_fitness/media/{exercise_id}/{kind}`, which requires HA's login. It relays only a library or custom exercise
  id and the kinds `gif` and `thumbnail`; anything else is a 404 before any relay. The cards fetch with
  `hass.fetchWithAuth` and show object URLs.
- **Why:** The add-on's port has no auth of its own and must stay off the internet, while HA's port is reachable from
  outside. The proxy keeps the media behind HA's login, and the patterns stop it from reaching any other add-on path.
- **Source:** [workout spec](superpowers/specs/2026-10-24-the-workout-design.md) §4 and §5.2; Claude, 2026-10-24

### D45: One page-level overlay for the workout flow
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The workout flow lives in one `<dialog>` per page, opened with `showModal()` and appended to
  `document.body`. A module-level controller owns it, with its own session subscription; the today card and
  `ha-fitness-workout-card` only ask it to open or close.
- **Why:** The top layer puts the flow above HA's header and every card, whatever stacking contexts the cards sit in
  ([`ha-notes.md`](ha-notes.md#the-frontend)). The flow outlives the card that opened it, so a card that hides or a
  view change can't tear down a running session's screen.
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §5.1; Claude, 2026-10-24

### D46: The `complete` service is dropped
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The integration has no `complete` service. A training day is done only through a counted session in
  the app.
- **Why:** The [design spec](superpowers/specs/2026-10-23-ha-fitness-design.md) §3.3 and §3.9 rule out a manual
  "done" for workouts done elsewhere, and a session already closes its day.
- **Source:** [step 5 spec](superpowers/specs/2026-10-24-the-workout-design.md) §2; Claude, 2026-10-24

### D47: Which days the stats count
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** Stats count every done day, and missed and skipped days from `counting_from`. For a person, a day
  before they were added counts only when they did it, and a day belongs to its own date. This refines design §3.3's
  "days closed before the counting date are left out".
- **Why:** The first workout counts even when it was done late or crossed midnight, and someone added later doesn't
  start with a pile of misses.
- **Source:** [stats spec](superpowers/specs/2026-10-24-stats-design.md) §3.1 and §7; Claude, 2026-10-24

### D48: What adds done and time, and how the streak counts
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** Only counted sessions add done and time. The streak counts dates, and a date adds one only when every
  counted day on it is done.
- **Why:** A session ended before one round is no workout. Counting dates keeps the streak independent of the order the
  days were created in.
- **Source:** [stats spec](superpowers/specs/2026-10-24-stats-design.md) §3.1, §3.2 and §7; Claude, 2026-10-24

### D49: Per-person sensor ids come from the HA person entity's object id; names are translated with a `{person}` placeholder
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** Per-person sensor ids come from the HA person entity's object id (`person.thomas` →
  `sensor.ha_fitness_thomas_streak`); names are translated with a `{person}` placeholder, the add-on person's name. The
  streak sensor has no unit.
- **Why:** The ids stay the same when a name changes or HA's language does, so automations keep working. HA takes a
  translated unit from the English file only, so a streak in "days" would show in English on a Danish HA
  ([`ha-notes.md`](ha-notes.md#the-integration)).
- **Source:** [stats spec](superpowers/specs/2026-10-24-stats-design.md) §5.1 and §7; the unit, Claude, 2026-10-24

### D50: How a workout felt is stored with the session, for Claude
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** A completed session can be rated too easy, just right or too hard within its 5-minute finished view. The
  rating is stored on the session and shown in the session history and the MCP `list_sessions`. Only completed sessions
  are rated.
- **Why:** Claude makes the programs, so it needs to know how a workout felt to adjust the next one. A rating on the
  session survives program edits and needs no new table.
- **Source:** [UI refresh spec](superpowers/specs/2026-10-24-ui-refresh-design.md) §3.3; Claude, 2026-10-24

### D51: The screens follow the mockups' layout, with HA's light theme and HA's icons
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** The built screens follow the mockups' layout and hierarchy, in HA's light theme and with its colour
  variables. Icons are `<ha-icon icon="mdi:…">`; no icon package is added.
- **Why:** The kitchen tablet runs HA's light theme, so the dark mockups are a reference for layout only. `ha-icon`
  needs no extra bundle.
- **Source:** [UI refresh spec](superpowers/specs/2026-10-24-ui-refresh-design.md) §6; Thomas, 2026-10-24

### D52: Cards are white with a grey border; the person's colour only on the badge
- **Date:** 2026-10-24 · **Status:** active
- **Decision:** A card or tile is white (`--card-background-color`) with a 1 px grey border (`--divider-color`), and
  the person's colour shows only on the numbered badge. The phase words take darker shades of the ring's colours.
- **Why:** Thomas asked for this look on get ready's person cards in his screen review; Claude carried it to every
  card and tile. The darker shades keep 4.5:1 contrast on the light background.
- **Source:** [UI polish spec](superpowers/specs/2026-10-24-ui-polish-design.md) §2, §3.1 and §3.2; Thomas (§2, his
  screen review); Claude (§3), for Thomas's review on the PR, 2026-10-24

### D53: The integration plays the music, following the session
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** The add-on only freezes a session's music choice. The integration starts the music at a running view
  with `started_at` set, while no start was tried (including the first view of a session that started after the
  controller's start). A session already running at a restart or reload is adopted, not restarted. A failed start is
  retried.
- **Why:** Music Assistant and its speakers belong to Home Assistant, which the integration reaches directly.
  Restarting the playlist on every reload would be wrong in the middle of a workout.
- **Source:** [music spec](superpowers/specs/2026-10-24-music-design.md) §5.1 and §9

### D54: The fade restores the volume after pausing
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** The fade lowers the volume, pauses, and then sets the volume back to the starting level. It also does
  so when the integration unloads.
- **Why:** The next playback must not start silent.
- **Source:** [music spec](superpowers/specs/2026-10-24-music-design.md) §5.3 and §9

### D55: A dev-only fake Music Assistant stands in for the real one in the loops
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** The fast loop and the full loop use a fake Music Assistant: a custom integration with the domain
  `music_assistant` in `scripts/dev/fake_music_assistant/`. It is never shipped, and it copies the surface of HA
  core's `music_assistant` that HA Fitness uses.
- **Why:** Fixed players and playlists make the loops and the Chrome check repeatable with no real speakers. The real
  Home Assistant stays untouched (hard rule 4).
- **Source:** [music spec](superpowers/specs/2026-10-24-music-design.md) §7

### D56: House details are removed from merged docs
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** Details of Thomas's Home Assistant (entity ids, HA users, dashboard ids, the host model and versions,
  how remote access works) are removed from merged specs and docs, which are otherwise snapshots. Wording stays
  generic. Dev fixtures (the Thomas and Elin persons) and pinned dependency versions stay. Rewriting git history is
  Thomas's call.
- **Why:** Hard rule 2: the repo is public. A hard rule wins over the snapshot rule.
- **Source:** [Review backlog spec](superpowers/specs/2026-10-25-review-backlog-design.md) §2.6; Claude, 2026-10-25

### D57: A paused timer is blue
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** While a workout is paused, the timer's ring, its phase word and the progress bar take the rest colour
  (blue), whatever the phase. The ring keeps the phase word.
- **Why:** Orange means work. A paused work phase in orange looked like work going on.
- **Source:** Thomas, screen review on 2026-10-25

### D58: Push messages go out in batches; a subscriber is dropped only when it is already 100 behind
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** The add-on publishes one change's push messages as one batch: a reconcile's events, then `today`,
  then `stats`. A batch reaches each subscriber whole. A subscriber is dropped (close code 1013) only when its backlog
  is already 100 messages or more when a batch arrives.
- **Why:** A catch-up after a long downtime can bring over 100 events at once. With a queue capped at 100 it dropped
  even a client that kept up, and that burst's events were lost. The check keeps the memory bounded by 100 messages
  plus one batch.
- **Source:** Claude, 2026-10-25, issue #49

### D59: The cards have visual editors; layout is HA's
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** Each card has a visual editor. Options go there; layout stays HA's Layout tab, never a control of
  ours. The editor uses `getConfigElement` with native controls, not `getConfigForm` or `ha-form`. Its texts follow
  the HA user's language, a narrow exception to D38.
- **Why:** HA builds the Layout tab only around a visual editor, and the other two routes fall short. The facts are in
  [`ha-notes.md`](ha-notes.md#the-frontend).
- **Source:** [card editors spec](superpowers/specs/2026-10-25-card-editors-design.md) §2 and §6

### D60: Late days stay open per program, for `late_days` days
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** A late day closes as missed when its own program trains again, or when `late_days` days after its date
  have passed, whichever comes first. Another program's training day closes nothing. `late_days` is an add-on option
  (0–6, default 2). This replaces the any-program rule in design spec §3.2 and step 4 spec §3.3, and the one-date rule
  in step 4 spec §3.5.
- **Why:** A missed Monday should still be doable on Tuesday, even when another program trains that day. The household
  decides how long, so it is an add-on option and not a card option.
- **Source:** [today ahead spec](superpowers/specs/2026-10-25-today-ahead-and-start-beep-design.md) §2.1

### D61: A program's next training can be done early, one at a time
- **Date:** 2026-10-25 · **Status:** active
- **Decision:** The today data lists each active program's next training as `upcoming`. A start may name the program
  and that date. The add-on makes the training day at the start. A program has one early training at a time. An early
  session that doesn't count leaves no day.
- **Why:** The household wants to see what is coming and to train ahead when a day doesn't fit. One at a time keeps a
  program to one early training.
- **Source:** [today ahead spec](superpowers/specs/2026-10-25-today-ahead-and-start-beep-design.md) §2.2

### D62: The add-on's website is built into the image, English only, with its own icons
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** The add-on serves a website at the Ingress panel's root, built in the add-on image, with its assets under
  `/web/`. It is for administrators only in v2. Its texts are English only in v2, an exception to hard rule 6. It
  inlines its own `mdi:` icons and defines HA's light-theme values itself, an exception to D51's "no icon package".
- **Why:** Inside the Ingress iframe `<ha-icon>` and HA's CSS variables don't exist. Thomas chose English only for v2;
  texts in one language file keep Danish possible later.
- **Source:** [website spec](superpowers/specs/2026-10-26-program-website-design.md) §2.1; Thomas, 2026-10-26

### D63: The household setup is kept in the add-on and read by Claude
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** The household setup holds the equipment, the people on the website, the favourite playlists and the
  default speaker. Claude reads it through the MCP tool `get_setup` and the `household` flag of `search_exercises`.
- **Why:** Claude suggests exercises and music that fit the house, without asking each time. The flag defaults to false,
  so today's search stays the same.
- **Source:** [website spec](superpowers/specs/2026-10-26-program-website-design.md) §2.4

### D64: The library holds the whole dataset
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** The built-in library takes every exercise of the dataset at its pinned commit (1,324 exercises, 28
  equipment values), not only the 721 with home equipment. The household's equipment filters at search time. This
  replaces the filtered set in D13 and D30.
- **Why:** The household sets its equipment on the website, so the library no longer needs to guess it at build time.
- **Source:** [website spec](superpowers/specs/2026-10-26-program-website-design.md) §2.3a; Thomas, 2026-10-26

### D65: REST refusals carry a stable code and field
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** REST refusals the website can meet carry a stable `code`, and a `field` where there is one, beside
  `detail`. This is additive; `api_version` stays 1. The session routes keep their `{code, message}` detail.
- **Why:** The website reacts to the code and places the add-on's message at the field. The integration reads the
  session routes' codes, so they stay.
- **Source:** [website spec](superpowers/specs/2026-10-26-program-website-design.md) §2.6

### D66: The website's equipment filter has three modes
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** The website's equipment filter is My equipment (the household's equipment plus body weight; custom
  exercises always show), All equipment, or picked kinds (OR; custom exercises only when they match). It replaces the
  website spec's "Show all" checkbox.
- **Why:** One control instead of a dropdown plus a checkbox. Thomas chose it from the W7 mockup.
- **Source:** [editor cards spec](superpowers/specs/2026-10-26-editor-cards-design.md) §2.3; Thomas, 2026-10-26

### D67: The add-on image is built when GHCR lacks it, from the release commit
- **Date:** 2026-10-26 · **Status:** active
- **Decision:** `addon-image` asks GHCR whether the multi-arch manifest for the version in `addon/config.yaml` exists
  (200 skip, 404 build, anything else fail), never git. It always builds the commit that set the version.
- **Why:** A run that GitHub replaced in the queue is made up by the next run (#82). Building the release commit keeps
  unreleased code out of the image and avoids the race with release-please's tag.
- **Source:** Claude, 2026-10-26, #82 (Thomas asked Claude to do it alone)
