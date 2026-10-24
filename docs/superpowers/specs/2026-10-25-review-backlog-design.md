# Review backlog: hardening from earlier reviews

- **Date:** 2026-10-25 · **Status:** under Thomas's delegation for the night of 2026-10-24 ("do the issues you can do
  alone, you are allowed to merge"), Claude approves this spec after `full-reviewer` rates it Ready.
- **Issues:** #39, #19, #22, #27 and #14 (the parts below). #21 stays open: it needs Thomas's choice between an
  allow-list and a token.
- **Needs an update on the real Home Assistant:** no change there, but both components get a patch release, so both
  reach the house with the next `fitness` issue.
- **Contract:** `api_version` stays 1. No contract change.

## 1. Why

Earlier reviews parked small findings as issues. None is a bug today, but each is cheap to close, and v1 is near.

## 2. What changes

### 2.1 A stats failure never breaks a write (#39)

- `TrainingDays._publish_today` calls `on_change`, which runs the stats. Today an exception there turns `/today`, a
  skip, a session finish or a people write into a 500, after the write has committed.
- The call of `on_change` is wrapped: an exception is logged with its traceback (`_LOGGER.exception`) and swallowed.
- **Scope:** writes. `GET /stats`, MCP `get_stats` and the push channel's connect snapshot still fail with broken
  stats; a follow-up issue covers the connect path.
- **Test:** break only the stats: set a counted session's `started_at` to NULL with sqlite (it trips the assert in
  `stats.py`), then a skip, `/today` and a session finish still answer 200.

### 2.2 A stored exercise that left the library (#19)

- `programs.py` `_out` names each station through `library.get`, which raises `NotFound` for a missing id. So
  `GET /programs` would answer 404 for every program.
- **The change:** a missing exercise is named by its id, and adds no equipment. The same holds wherever a stored
  station is named: a session's plan at the start, and MCP's program tools. Claude's call: the id, because exercise
  names are never translated and a made-up text would need a language file in the add-on's API.
- **An update** that still holds a missing id is refused with 422 `invalid` (from `library.resolve`) until the station
  is swapped. MCP's `get_program` text ("a valid document as it stands") says this exception.
- Naming happens in one place (`Programs._out`); sessions and MCP name stations through it, so they need no change.
- **Test:** create a custom exercise through the API, store a program that uses it, then delete its
  `custom_exercises` row with sqlite (the future case #19 names). Then `GET /programs`, `GET /programs/{id}` and a
  session start answer 200 with the id as the station's name, and an update of the unchanged document is 422.

### 2.3 The Ingress page (#22)

- **The separator:** the weekday list's `", "` comes from the language files, as a `list_separator` key in the
  add-on's i18n files (English and Danish).
- **The page test** checks the whole formatted exercises text, the custom-exercise count included.
- **`HEAD /`** answers like `GET /`, through `api_route("/", methods=["GET", "HEAD"])`, instead of falling through to
  the MCP mount's 404.

### 2.4 Push queues and two missing tests (#27)

- **Bounded queues:** each push subscriber's queue gets `maxsize=100`. On `QueueFull` the subscriber is dropped and
  its websocket closed with code 1013 ("try again later"), logged at WARNING. The integration reconnects after 1 s and
  gets the full snapshot, as after any clean close. Claude's call: a dropped client recovers on its own, while
  dropping single messages would leave it out of date.
  - **The mechanism:** `subscribe()` also yields a per-subscriber `asyncio.Event`. `broadcast` loops over a copy of
    the subscribers; on `QueueFull` it sets that event and discards the queue. The ws handler waits on `event.wait()`
    as a third task under `FIRST_COMPLETED`, then closes with 1013.
- **Tests:**
  - On `Hub` directly (its `subscribe()` and `broadcast()` are the interface here, because the test transport has no
    backpressure): one subscriber never reads, the other reads between broadcasts; after 101 broadcasts the first is
    dropped (its event set, no more messages) and the second got every message.
  - An unset `TZ` (and no `HA_FITNESS_TIMEZONE`) logs at INFO and gives UTC. This test passes at once (coverage).
- Left in #27: the scheduler's failure test (it needs a failure inside `reconcile` that survives §2.1; a later
  change), and the dev POST item (dev only). The LAN item is #21.

### 2.5 Small step 1 items (#14)

- **Fixed here:**
  - a test that `main()` creates the data folder (with `uvicorn.run` monkeypatched; it passes at once, coverage);
  - `cards/eslint.config.js`: `tseslint.config(...)` becomes `defineConfig(...)` from `eslint/config`;
  - coverage floors: `fail_under` under `[tool.coverage.report]` in the root `pyproject.toml` (95; today 99 %) and in
    `addon/server/pyproject.toml` (90; today 95 %). The gate lines stay as they are.
- **Already fixed:** `app.state.settings` is set (`app.py`); the pickers' names and descriptions come from the
  language files (`localize("en", …)` in each card).
- **Left in #14:** the Dockerfile's `UV_PYTHON`; tsconfig including `eslint.config.js` without `checkJs`; the Card
  type cast in tests; the untested picker description; the release workflow's concurrency group and its `HEAD^1`
  compare (a workflow change better made with Thomas); the `uv run python scripts/dev_onboard.py` item (the music
  branch changes those files tonight); the manifest's `categories`; the skipped #9 review (every later PR had a full
  branch review, so this one can close as overtaken).

### 2.6 House details in a public spec (hard rule 2)

- Several merged files name details of Thomas's Home Assistant: entity ids, an HA user, a dashboard id, the host
  model and versions, and how remote access works. Hard rule 2 forbids that in the repo. They are in the design spec
  (§2 and later lines), other specs, `docs/architecture.md`, `docs/notes.md`, a docstring in
  `custom_components/ha_fitness/websocket_api.py`, and a comment in `tests/test_session_services.py`.
- **The change:** those details are replaced with generic wording ("a person entity for each trainer", "the tablet's HA
  user", "the kitchen dashboard", "Music Assistant with a few speakers, none in the kitchen", "the host is aarch64",
  "remote access must not expose the add-on's port"). The tablet's size, theme, language and touch behaviour stay,
  since the design needs them and they identify nothing.
- **Verification:** a repo-wide `git grep` (lock files excluded) for the house's entity ids, HA user, dashboard id,
  host model and remote-access tools returns no hits outside justified generic words. The list of strings is in the
  SDD dispatch, never in a committed file, so this PR doesn't republish what it removes.
- Specs are snapshots, but a hard rule wins. **D56** records this lasting exception: house details are removed from
  merged docs; rewriting git history is Thomas's call. (D53–D55 are taken by the music spec.) The PR also calls out
  a remote-access detail as a security disclosure, without naming it.

## 3. Delivery

- One PR: `fix: hardening from the review backlog`, with `Closes #39, closes #19, closes #22` and `Refs #27` (items
  are left in #27), and a comment on #14 listing what is left. Both components get a patch release.
- Decisions: D56 (§2.6).
