# The add-on's website: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repo, `docs/way-of-working.md` wins over the skill: `implementer` per task, `task-reviewer` on `Review: yes`.

**Goal:** An English Lit/TypeScript website in the add-on's Ingress panel to manage programs (list, new, copy, edit,
delete), browse the whole exercise library, and set up the household (equipment, people, favourite playlists, default
speaker), with the add-on API, MCP and data changes it needs.

**Architecture:** The add-on keeps owning data and rules. It gains a setup store, "created by" on programs, stable
error codes, an opt-in conflict check, a read of all exercise summaries and of the program defaults, and a `household`
search flag (REST and MCP), and it serves the built site: its HTML at `/`, its assets under `/web/`. The site lives in
`addon/web/`, is built in a node stage of the add-on image, and talks to the REST API through Ingress with relative
URLs.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, FastMCP, pytest (add-on); Lit 3, TypeScript, Vite, Vitest
with happy-dom and @testing-library/dom, `@mdi/js` (site); Docker multi-stage build.

**Spec:** `docs/superpowers/specs/2026-10-26-program-website-design.md` (approved). Section numbers below are the spec's.
Mockups: `docs/mockups/website/W1–W6` (layout only; the site's texts are English).

## Global Constraints

- The site is **English only** in v2 (§2.1.5): every text, the page `<title>` included, from
  `addon/web/src/i18n/en.json`. D62 (written in Task 0) records the exception to hard rule 6; dispatches and reviews
  cite D62 until `CLAUDE.md` is updated (Task 13).
- Admin only through Ingress; no logic depends on `panel_admin` (§2.1.2).
- REST changes are additive, `api_version` stays 1; an existing route's `detail` keeps its type and meaning; the
  session routes keep `{code, message}` (§2.6.1). MCP error texts are unchanged, except the one ruling in Task 2.
- Every `PUT /api/v1/programs/{id}` without `if_updated_at` works as today (§2.2.6).
- No second set of rules in the site: it shows the add-on's refusals and never caps or validates a program itself
  (§5). The fake API in the site's tests holds no program rules; each test sets the refusal it needs.
- Tests through public interfaces: REST/MCP for the add-on; for the site, rendered text, roles and labels and the
  requests sent to a faked `fetch`. No component internals, snapshots or CSS selectors (hard rule 5, §6).
- The feature PR touches only `addon/`, `docs/`, `scripts/` and `.github/`; root files go in Task 13's own PR.
- **The asset layout** (fixed here, used by Tasks 5 and 6): Vite `base: "./"`, `build.assetsDir: "web"`, no `public/`
  folder; the build output is `dist/index.html` plus `dist/web/*`; every `src`/`href` in `dist/index.html` starts with
  `./web/`. The server serves `web_dir/index.html` at `/` and mounts `StaticFiles` at `/web` on `web_dir / "web"`.
- Commits: Conventional Commits with the dispatch's co-author trailer, `git commit -F <file>`.

## Review Focus

1. **A program Claude made, saved on the website:** `music.volume` and `music.shuffle` survive; `playlist_name`
   follows a newly picked playlist. Test in Task 9.
2. **Two editors at once, and two saves in a row in one editor:** the site sends `if_updated_at` and keeps each
   response's `updated_at`; MCP's `update_program` (no check) still works. Tests in Tasks 2 and 9.
3. **A refusal without a field** (session running on delete, HA unreachable on people) shows above the form, never
   lost. Tests in Tasks 8, 9 and 11.
4. **Ingress prefix:** every request and asset URL is relative (`api/v1/...`, `./web/...`). Tests in Tasks 6 and 7.
5. **The household filter with custom exercises and null equipment:** custom exercises always show; body weight is
   always on. Tests in Tasks 4 and 10.

---

### Task 0: The decisions (docs, first)

Model: sonnet · Review: no

**Files:** `docs/decisions.md`.

- [ ] **Step 1:** Add, in the format of `docs/way-of-working.md` §5 (date 2026-10-26, source the spec):
  - **D62** The add-on's website: built in the add-on image and served at the panel's root (assets under `/web/`),
    admin only in v2 through Ingress, **English only in v2 (an exception to hard rule 6)**, with its own `mdi:` icons
    and HA light-theme values (an exception to D51's "no icon package").
  - **D63** The household setup (equipment, people on the website, favourite playlists, default speaker), read by
    Claude through `get_setup` and the `household` search flag.
  - **D64** The library holds the whole dataset; set D13 and D30 to `active; <the filtered part> superseded by D64`
    (only their Status lines change).
  - **D65** REST refusals carry a stable `code` and `field` beside `detail` (additive); the session routes keep theirs.
- [ ] **Step 2:** `uv run python scripts/check_links.py`. **Commit** `docs: decisions for the add-on website`.

### Task 1: The whole dataset in the library (add-on)

Model: opus · Review: yes

**Files:** `scripts/build_library.py`, `addon/server/src/ha_fitness_server/library/exercises.json` (rebuilt),
`library/NOTICE.md`, `docs/notes.md` (the 721/1,442 note), `addon/DOCS.md` (the media size), the tests that assume
the old counts (`grep -rn "721\|1442" addon/server/tests`; `test_media.py`'s `TOTAL = 1442` becomes 2,648).

- [ ] **Step 1:** In `scripts/build_library.py` drop the equipment filter (keep every record) and update its docstring
  (the whole dataset at the pinned commit `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`).
- [ ] **Step 2:** Run `uv run python scripts/build_library.py`. Check: 1,324 records, 28 equipment values, sorted by
  id; a second run gives the same file.
- [ ] **Step 3: Tests first:** add `test_library_has_the_whole_dataset` (`GET /api/v1/library` counts 1,324;
  `GET /api/v1/exercises?equipment=cable` finds a cable exercise) and `test_shared_name_asks_for_the_id` (a station
  given by one of the six shared names, found with a one-off script, is refused with the existing "shared; give the id"
  error). Update count, order and match-count expectations that the bigger dataset changes; any other failure is a
  finding for the report.
- [ ] **Step 4:** Update `NOTICE.md`, `docs/notes.md` and `addon/DOCS.md` ("filtered", 721, 1,442, about 72 MB → the
  whole dataset, 1,324, 2,648, about 137 MB). Run the add-on gates and `check_links`.
- [ ] **Step 5: Commit** `feat(addon): the library holds the whole exercise dataset`.

### Task 2: Stable error codes and the opt-in conflict check (add-on)

Model: opus · Review: yes

**Files:** `errors.py`, `api/errors.py`, `programs.py`, `people.py`, `library/service.py`, `schemas.py`,
`api/programs.py`; tests `test_errors.py` (new), `test_session_finish.py` (line ~291 asserts the whole delete body:
update it for the added keys), and the program/people tests.

**Interfaces:**
- `NotFound`, `Conflict`, `Invalid`, `Unavailable` take optional keyword arguments `code: str | None = None` and
  `field: str | None = None`. REST bodies for these four become `{"detail": <unchanged>, "code": <str>, "field":
  <str | null>}`; `code` is always present (the given one, else `not_found`, `conflict`, `invalid`, `unavailable`).
- Codes and fields: `name_taken` (`name`); `session_running` (null); `weekday_needed` (`weekdays`, for `set_active`);
  `station_unknown` / `station_shared` (`stations.<index from 0>`); `too_many_people`, `person_twice`, `person_unknown`
  (`people`); `ha_unavailable` (null); `changed_elsewhere` (null).
- The weekday rule moves from the model validator to `field_validator("weekdays")` reading `info.data["active"]` (it is
  declared before `weekdays`), still raising `ValueError` with the same message, so a REST 422 item has
  `loc: ["body", "weekdays"]`. **Ruling (to record in the PR):** MCP's text for this one rule changes only its location
  line (from the program to `weekdays`).
- `Programs.replace(program_id, document, client, if_updated_at: datetime | None = None)`; the check runs inside
  `_replace`'s transaction, under the training-days lock, comparing instants. `PUT /api/v1/programs/{id}` takes the
  query parameter `if_updated_at: datetime | None`. Given and different → 409 `changed_elsewhere`; omitted → as today.

- [ ] **Step 1: Write the failing tests** in `test_errors.py` (REST unless named):
  - taken name on create and replace → 409, `code == "name_taken"`, `field == "name"`, `detail` the same string;
  - delete and `active: false` during a running session → 409 `session_running`, `field is None`;
  - active without weekdays on create → 422 with an item whose `loc == ["body", "weekdays"]`; `PUT /active` on a
    program without weekdays → 422 `code == "weekday_needed"`, `field == "weekdays"`;
  - unknown third station → 422 `station_unknown`, `field == "stations.2"`, `detail` the same dict;
  - three people → `too_many_people`; the same person twice → `person_twice`; an unknown HA person →
    `person_unknown`; HA unreachable → 503 `ha_unavailable`;
  - `if_updated_at` equal → 200; different → 409 `changed_elsewhere`; omitted after another write → 200; two saves in
    a row, each with the previous response's `updated_at` → both 200;
  - a session route's refusal body has no top-level `code`;
  - MCP: two existing refusals (a taken name, a session running) give the same `ToolError` text as before.
- [ ] **Step 2–4:** fail, implement, run the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): stable error codes and an opt-in conflict check for program writes`.

### Task 3: "Created by", the setup store and the defaults read (add-on)

Model: opus · Review: yes

**Files:** `migrations/versions/0006_setup_and_created_by.py`, `models.py`, `schemas.py`, `programs.py`, `setup.py`
(new service), `services.py`, `app.py` (wire the service), `api/setup.py` (new), `api/programs.py`,
`api/__init__.py`; tests `test_setup.py`, `test_programs_created_by.py` (new).

**Interfaces:**
- `programs.created_by` column, `"claude"` or `"you"`, nullable. Set at create from the client: `mcp:` → `"claude"`,
  anything else → `"you"`. The migration fills it from the change log's `program.created` row (`target ==
  "program:<id>"`): `mcp:` → `"claude"`, else `"you"`; no row → null. The downgrade is a native
  `ALTER TABLE programs DROP COLUMN created_by` and `DROP TABLE setup` (no batch rebuild: `training_days.program_id`
  has `ondelete="SET NULL"`, as 0005's downgrade avoids). `ProgramOut.created_by: Literal["claude", "you"] | None`.
- `class FavouritePlaylist(BaseModel): uri: str; name: str`. `class Setup(BaseModel)`: `equipment: list[str]` (sorted,
  unique, each in `Library.facets()["equipment"]`; `body weight` always included on read and write),
  `favourite_playlists: list[FavouritePlaylist]` (unique by uri, at most 20), `default_speaker: str | None`
  (`^media_player\.[a-z0-9_]+$`). Stored as one JSON document in a `setup` table with one row.
- `SetupService.get() -> Setup`; `SetupService.set(setup: Setup, client: str) -> Setup` logs `setup.updated`.
- REST: `GET /api/v1/setup` (defaults `["body weight"]`, `[]`, null); `PUT /api/v1/setup`; an unknown equipment
  value → 422 `code == "equipment_unknown"`, `field == "equipment"`.
- REST: `GET /api/v1/programs/defaults` → `{rounds, work_seconds, switch_seconds, round_rest_seconds,
  countdown_seconds}` from `ProgramDocument`'s defaults (5, 45, 15, 60, 5), registered before `/{program_id}`.

- [ ] **Step 1: Write the failing tests:**
  - create via REST → `created_by == "you"`; via MCP → `"claude"`;
  - the backfill, as `test_storage.py::test_migration_0002_keeps_programs`: `db.migrate(engine, "0005_session_feeling")`,
    insert raw `programs` and `change_log` rows, start the app, read `GET /api/v1/programs/<id>`: an `mcp:` row →
    `"claude"`, a `rest:` row → `"you"`, no row → null; the downgrade to 0005 keeps every training day's `program_id`;
  - setup round trip; `body weight` always present; an unknown value → `equipment_unknown`; a custom exercise's
    equipment is accepted; `setup.updated` in the change log;
  - `GET /api/v1/programs/defaults` returns 5/45/15/60/5.
- [ ] **Step 2–4:** fail, implement, run the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): programs know who created them, a household setup, and the program defaults`.

### Task 4: Library reads, the household filter and `get_setup` (add-on, MCP)

Model: opus · Review: yes

**Files:** `library/service.py`, `schemas.py` (`Facets.target`), `api/exercises.py`, `mcp_tools.py`; tests
`test_exercises_all.py` (new), `test_mcp.py`.

**Interfaces:**
- `GET /api/v1/exercises/all` → `list[ExerciseSummary]`, every library and custom exercise by name, registered before
  `/{exercise_id}`.
- `Facets.target: list[str]`.
- `GET /api/v1/exercises` and MCP `search_exercises` take `household: bool = False`: only exercises whose equipment is in
  the setup's equipment (with `body weight`), plus every custom exercise.
- MCP `get_setup()` → `Setup`, read-only. The `create_program`, `update_program` and `search_exercises` descriptions
  say to prefer the household's equipment (`get_setup`, or `household: true`) and to offer the favourite playlists and
  the default speaker first when asking about music.

- [ ] **Step 1: Write the failing tests:** `/exercises/all` has every exercise with `target`; facets have `target`;
  `household=true` with setup `["dumbbell"]` → body weight, dumbbell and a custom exercise with null equipment, no
  cable exercise; MCP `get_setup` returns the stored setup; MCP `search_exercises(household=true)` matches REST; the
  descriptions contain `get_setup` and "favourite playlists".
- [ ] **Step 2–4:** fail, implement, run the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): read every exercise, filter by household equipment, and get_setup for Claude`.

### Task 5: The server serves the site (add-on)

Model: opus · Review: yes

**Files:** `settings.py`, `app.py`, `ingress.py` (the fallback page only), `i18n/en.json` (its text), delete
`i18n/da.json`, `tests/test_ingress.py` → `tests/test_site_serving.py`.

**Interfaces:**
- `Settings.web_dir: Path`, default `Path("/opt/ha-fitness/web")`, from `HA_FITNESS_WEB_DIR`.
- `GET`/`HEAD /`: `web_dir/index.html`, read on each request, with `Cache-Control: no-cache`; when it doesn't exist,
  the English fallback page ("The HA Fitness website isn't built." and the version).
- `StaticFiles` mounted at `/web` on `web_dir / "web"` with `check_dir=False` (so a missing folder doesn't fail app
  creation), after the `/api` catch-all and before the MCP mount.

- [ ] **Step 1: Write the failing tests:** with a temp `web_dir` holding `index.html` and `web/app.js`: `/` returns the
  HTML with `no-cache`; `/web/app.js` returns the file; `/web/missing.js` → 404 whose body isn't MCP's plain text
  (assert the JSON `{"detail": "Not Found"}`); with an explicit missing `web_dir`: `/` returns the fallback with the
  version; `/mcp` still answers MCP; an unknown `/api/x` still a JSON 404.
- [ ] **Step 2–4:** fail, implement, run the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): serve the website at the panel's root, with a fallback page`.

### Task 6: The site's skeleton and Status page (web)

Model: opus · Review: yes

**Files:** create `addon/web/`: `package.json`, `package-lock.json`, `tsconfig.json` (no comments: the `check-json`
hook), `eslint.config.js` (ignores `node_modules/` and `dist/`), `vite.config.ts`, `index.html`, `.gitignore`
(`dist/`, `node_modules/`), `src/main.ts`, `src/app-shell.ts`, `src/api.ts`, `src/i18n.ts`, `src/i18n/en.json`,
`src/theme.ts`, `src/icons.ts`, `src/pages/status-page.ts`, `scripts/check-dist.mjs`, `test/fake-api.ts`,
`test/shell.test.ts`, `test/status.test.ts`, `test/api.test.ts`.

**Interfaces:**
- Tool versions as `cards/package.json` (lit 3.3.3, vite, vitest, happy-dom, @testing-library/dom, typescript 6.0.3,
  eslint, typescript-eslint) plus `@mdi/js`. Scripts: `build` (vite build, then `node scripts/check-dist.mjs`), `watch`,
  `test`, `lint`.
- `check-dist.mjs` fails the build when any `src`/`href` in `dist/index.html` doesn't start with `./web/`.
- `api.ts`: `createApi(fetchFn = fetch)` with typed functions for every route the site uses; paths relative
  (`api/v1/...`). Errors: `class ApiError { status; code: string | null; field: string | null; message: string;
  detail: unknown }`. `message`: a string `detail`; else `detail.message`; else the first 422 item's `msg`. For a 422
  list: `field` is the first item's `loc` without `body`, joined with `.` (null when only `body`), `code` its `type`;
  otherwise `code` and `field` from the body.
- `app-shell.ts`: `<hf-app>` with the menu **Programs, Library, Setup, Status** and hash routes `#/programs`,
  `#/programs/new`, `#/programs/new/copy/<id>`, `#/programs/<id>`, `#/library`, `#/setup`, `#/status` (default
  `#/programs`); it renders the route of the hash it starts with.
- `i18n.ts`: `t(key: string, vars?: Record<string, string | number>): string`; `document.title` from `en.json`.
- `icons.ts`: `icon(path: string)` → an inline `<svg>` of an `@mdi/js` path. `theme.ts`: the HA light-theme values
  (background `#fafafa`, card `#fff`, border `#e0e0e0`, primary HA blue as the mockups).
- `test/fake-api.ts`: a fake `fetch` with programs, exercises, setup, people, speakers, playlists and defaults in
  memory, recording each request (method, path with query, body), and able to answer a set status and body per route.
  It holds no program rules.

- [ ] **Step 1: Write the failing tests:** the shell's four menu links and switching by hash; starting at
  `#/programs/5` renders that route; the Status page shows the version (`api/v1/health`), the library counts and media
  state (`api/v1/library`), the people and the programs, and links `api/v1/library` and `api/v1/health`; `createApi`
  calls relative paths; `ApiError` for D65's body, a 422 list (with and without a field), and a plain string `detail`.
- [ ] **Step 2–4:** fail, implement, run `npm run lint --prefix addon/web && npm test --prefix addon/web && npm run
  build --prefix addon/web`.
- [ ] **Step 5: Commit** `feat(addon): the website's skeleton and Status page`.

### Task 7: Build and tooling (image, CI, scripts)

Model: opus · Review: yes

**Files:** `addon/Dockerfile`, `addon/.dockerignore` (`web/node_modules`, `web/dist`), `.github/workflows/ci.yml` (a
`web` job like `cards`: lint, test, build), `.github/dependabot.yml` (npm `/addon/web`, with the TypeScript hold),
`scripts/setup` (`npm ci` in `addon/web`), `scripts/develop` (build the site once, run its watch with its own pidfile,
stop it in `stop_background`, and start the server with `HA_FITNESS_WEB_DIR="$root/addon/web/dist"`),
`scripts/full-loop` (rsync `--exclude node_modules --exclude dist`), `docs/notes.md` (the node pin is bumped by hand),
`docs/testing.md` (the site in the fast loop).

**Interfaces:** a stage `FROM --platform=$BUILDPLATFORM node:24-alpine@sha256:<the multi-arch index digest from
docker buildx imagetools inspect node:24-alpine> AS web` that runs `npm ci` and `npm run build` in the site's folder;
the final stage `COPY --from=web <site>/dist /opt/ha-fitness/web`.

- [ ] **Step 1:** Make the changes.
- [ ] **Step 2: Check:** `docker build -t ha-fitness-web-check addon` and `docker run --rm --entrypoint ls
  ha-fitness-web-check /opt/ha-fitness/web /opt/ha-fitness/web/web` lists `index.html` and the assets; remove the
  image. `uv run actionlint && uv run zizmor --offline .github/workflows`; `bash -n` on the changed scripts;
  `scripts/develop` serves the site at `http://localhost:8765/`.
- [ ] **Step 3: Commit** `ci: build the website into the add-on image, with its CI job and scripts`.

### Task 8: Programs list, switch and delete (web)

Model: opus · Review: yes

**Files:** `src/pages/programs-page.ts`, `src/components/confirm-dialog.ts`, `en.json`; `test/programs.test.ts`.

**Interfaces:** produces `#/programs` (W1) and `<hf-confirm-dialog>` (W5), reused by Tasks 9 and 11. Copy only
navigates to `#/programs/new/copy/<id>` (Task 9 builds the copy).

- [ ] **Step 1: Write the failing tests:**
  - rows show name, length, weekdays, thumbnails (an `img` per station, alt = the exercise name, `src` relative
    `api/v1/exercises/<id>/thumbnail`, `loading="lazy"`, a placeholder when the media is missing), music name or
    "None", "Created by" "Claude"/"You"/nothing, and an active switch;
  - search by name and All/Active/Off narrow the rows;
  - the switch sends `PUT api/v1/programs/<id>/active`; a 409 `session_running` shows the message by the row and the
    switch stays as it was;
  - Copy navigates to `#/programs/new/copy/<id>` and sends nothing;
  - Delete opens a dialog (role `dialog`) with the history, open days and can't-be-undone text and "Turn it off
    instead"; confirming sends `DELETE`; "Turn it off instead" sends `PUT .../active {active: false}`; a 409
    `session_running` shows the message in the dialog;
  - "New program" goes to `#/programs/new`.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website lists, switches and deletes programs`.

### Task 9: New program, copy and the editor (web)

Model: opus · Review: yes

**Files:** `src/pages/program-editor.ts`, `src/pages/new-program.ts`, `src/components/exercise-picker.ts` (the
library panel, also used by Task 10), `src/components/exercise-details.ts` (W4, also used by Task 10), `en.json`;
`test/editor.test.ts`.

**Interfaces:** consumes Task 8's dialog; `api/v1/programs/defaults`, `api/v1/exercises/all`, `api/v1/setup`,
`api/v1/music/speakers`, `api/v1/music/playlists`; Task 2's codes and `if_updated_at`.

- [ ] **Step 1: Write the failing tests:**
  - `#/programs/new` (W2): "Start empty" and "Copy a program"; empty starts active, no weekdays, no music, with the
    defaults from `api/v1/programs/defaults` shown (5 rounds, 45 s, 15 s, 60 s, countdown 5 of the choices 0/5/10);
  - `#/programs/new/copy/<id>` opens prefilled with `"<name> (copy)"`, `active: false`, the stations and the music;
    nothing is sent before Save; Save sends one `POST`; a 409 `name_taken` shows at the name field;
  - saving an empty program without a weekday shows the add-on's message at the weekdays; nothing typed is lost;
  - editing loads `GET api/v1/programs/<id>`; Save sends `PUT …?if_updated_at=<url-encoded updated_at>` with the
    whole document; a second Save uses the first response's `updated_at`;
  - `music: {playlist, playlist_name, speaker, volume: 35, shuffle: true}` → saved with volume 35 and shuffle true;
    picking another playlist sets `playlist` and `playlist_name`; favourites are listed first; a speaker not in the list
    still shows and is kept; music reads answering 503 or empty lists say so and the rest saves;
  - a new program's speaker is the setup's `default_speaker`; music is sent only once a playlist is picked;
  - add (+), remove (×), move up/down with buttons; the sent `stations` follow; 16 stations → the add-on's 422 shown;
  - the panel searches and filters, shows only household exercises by default (setup `["dumbbell"]`: a cable exercise
    absent, a custom exercise present), "Show all" shows the rest, ✓ marks exercises in the program;
  - a click on a panel exercise opens the details dialog (GIF `img` with the attribution text, equipment, body part,
    target, secondary muscles, steps);
  - the summary line for 5 stations, 4 rounds, 45 s, 15 s, 60 s says 5 exercises and 23 min (1,380 s: the add-on's
    `total_seconds` formula) and the equipment needed without body weight;
  - "Not saved" after a change; leaving within the site asks first (a dialog); the `beforeunload` event is cancelled
    while there are unsaved changes and not otherwise; Cancel returns to `#/programs` (asking first when dirty);
  - a 409 `changed_elsewhere` shows a message with "Reload" and keeps the form's values; a refusal without a field
    shows above the form; Delete uses Task 8's dialog.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's new-program page and editor`.

### Task 10: Library page (web)

Model: opus · Review: yes

**Files:** `src/pages/library-page.ts`, `en.json`; `test/library.test.ts`.

- [ ] **Step 1: Write the failing tests:** search by name; filters by equipment, body part and target with several
  values each (from the facets); the household filter on by default with "Show all"; custom exercises always shown;
  values as the dataset names them; the details dialog opens on click; thumbnails lazy with a placeholder.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's library page`.

### Task 11: Setup page (web)

Model: opus · Review: yes

**Files:** `src/pages/setup-page.ts`, `en.json`; `test/setup.test.ts`.

- [ ] **Step 1: Write the failing tests:**
  - equipment chips for every facet value, `band` and `resistance band` as one "band" chip (toggling sends both);
    body weight on and not removable; Save sends `PUT api/v1/setup`;
  - favourite playlists added from `api/v1/music/playlists` and removed; the default speaker from
    `api/v1/music/speakers`; music reads answering empty or 503 say so and the rest saves;
  - people from `GET api/v1/people`: add, reorder, save on their own (`PUT api/v1/people`); a third person is sent and
    the add-on's `too_many_people` shown (no cap in the site); removing a person opens a confirmation explaining
    stats/history/sensors/new person; a 503 `ha_unavailable` shows the message and keeps the choice.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's setup page`.

### Task 12: Docs

Model: sonnet · Review: no

**Files:** `docs/architecture.md`, `docs/domain-language.md`, `addon/DOCS.md`, `docs/testing.md`,
`docs/mockups/README.md`.

- [ ] **Step 1:** Per spec §7: the website, the routes (setup, programs/defaults, exercises/all, `household`,
  `if_updated_at`, D65's error body), `get_setup`, serving and routing ("Routing in the add-on server"), the setup terms,
  `created_by` in `ProgramOut` (also in MCP's program outputs), the full loop check of the panel.
- [ ] **Step 2:** `check_links`. **Commit** `docs: the add-on website, the setup and the whole dataset`.

### Task 13 (after the feature PR merges): root files

Model: sonnet · Review: no · A separate branch and PR, `docs:` type.

- [ ] `CLAUDE.md`: layout (`addon/web/`), the web gates, and hard rule 6 naming the website's English-only exception in
  v2 with D62. Commit `docs: CLAUDE.md for the add-on website`.

### After the tasks (controller)

- `full-reviewer` on the branch; the fast loop with the site; the Chrome check of the six pages with screenshots in
  `screenshots/2026-10-26-program-website/`; the full loop builds the image with the site and shows it in the panel.
- Ask Thomas whether the new `web` CI job becomes a required check (a GitHub setting).
- The PR `feat(addon): the website to manage programs, the library and the setup`, with the rulings; then Task 13's PR.
- The release's `fitness` issue says the panel now holds the editor and asks the house to check "show in sidebar".
