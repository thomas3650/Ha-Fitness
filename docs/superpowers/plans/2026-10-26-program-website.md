# The add-on's website: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> In this repo, `docs/way-of-working.md` wins over the skill: `implementer` per task, `task-reviewer` on `Review: yes`.

**Goal:** An English Lit/TypeScript website in the add-on's Ingress panel to manage programs (list, new, copy, edit,
delete), browse the whole exercise library, and set up the household (equipment, people, favourite playlists, default
speaker), with the add-on API, MCP and data changes it needs.

**Architecture:** The add-on keeps owning data and rules. It gains a setup store, "created by" on programs, stable
error codes, an opt-in conflict check, a read of all exercise summaries, and a `household` search flag (REST and MCP),
and it serves the built site at `/` (assets under `/web/`). The site lives in `addon/web/`, is built in a node stage of
the add-on image, and talks to the REST API through Ingress with relative URLs.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy, Alembic, FastMCP, pytest (add-on); Lit 3, TypeScript, Vite, Vitest
with happy-dom and @testing-library/dom, `@mdi/js` (site); Docker multi-stage build.

**Spec:** `docs/superpowers/specs/2026-10-26-program-website-design.md` (approved). Section numbers below are the spec's.
Mockups: `docs/mockups/website/W1–W6` (layout only; the site's texts are English).

## Global Constraints

- The site is **English only** in v2 (§2.1.5): every text in `addon/web/src/i18n/en.json`. This is the decision's
  exception to hard rule 6; dispatches and reviews cite it until `CLAUDE.md` is updated (Task 12).
- Admin only through Ingress; no logic depends on `panel_admin` (§2.1.2).
- REST changes are additive, `api_version` stays 1; an existing route's `detail` keeps its type and meaning; the
  session routes keep `{code, message}` (§2.6.1). MCP error texts are unchanged.
- Every `PUT /api/v1/programs/{id}` without the conflict check works as today (§2.2.6).
- No second set of rules in the site: it shows the add-on's refusals (§5).
- Tests through public interfaces: REST/MCP for the add-on; for the site, rendered text, roles and labels and the
  requests sent to a faked `fetch`. No component internals, snapshots or CSS selectors (hard rule 5, §6).
- The feature PR touches only `addon/`, `docs/`, `scripts/` and `.github/`; root files go in Task 12's own PR.
- Commits: Conventional Commits with the dispatch's co-author trailer, `git commit -F <file>`.

## Review Focus

1. **A program Claude made, saved on the website:** `music.volume` and `music.shuffle` survive; `playlist_name`
   follows a newly picked playlist. Test in Task 8.
2. **Two editors at once:** the site saves with the conflict check; MCP's `update_program` (no check) still works.
   Tests in Tasks 2 and 8.
3. **A refusal without a field** (session running on delete, HA unreachable on people) shows above the form, never
   lost. Tests in Tasks 7, 8 and 10.
4. **Ingress prefix:** every request and asset URL is relative, so the site works under `/api/hassio_ingress/<token>/`.
   Test in Task 6 (the built `index.html` has no absolute `/` URLs; the API client builds `api/v1/...` paths).
5. **The household filter with custom exercises and null equipment:** custom exercises always show; body weight is
   always on. Tests in Tasks 4 and 9.

---

### Task 1: The whole dataset in the library (add-on)

Model: opus · Review: yes

**Files:** `scripts/build_library.py`, `addon/server/src/ha_fitness_server/library/exercises.json` (rebuilt),
`addon/server/src/ha_fitness_server/library/NOTICE.md`, tests that assume 721 (`grep -rn 721 addon/server/tests`).

- [ ] **Step 1:** In `scripts/build_library.py` drop the `EQUIPMENT` filter (keep every record), and update its
  docstring ("filtered" → the whole dataset at the pinned commit `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`).
- [ ] **Step 2:** Run `uv run python scripts/build_library.py` (it downloads the pinned data) and check the output:
  1,324 records, 28 equipment values, sorted by id, deterministic.
- [ ] **Step 3: Tests first:** change the tests that pin 721 to 1,324 and add
  `test_library_has_the_whole_dataset` (through `GET /api/v1/library` and `GET /api/v1/exercises?equipment=cable`:
  counts 1,324 and a cable exercise found), and `test_shared_name_asks_for_the_id` (a station given by a name two
  library exercises share, e.g. one of the six — find them with a quick script — is refused with the existing
  "shared; give the id" error). Run the add-on tests; fix only count-based expectations.
- [ ] **Step 4:** Update `NOTICE.md` ("filtered" → the whole dataset). Run the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): the library holds the whole exercise dataset`.

### Task 2: Stable error codes and the opt-in conflict check (add-on)

Model: opus · Review: yes

**Files:** `addon/server/src/ha_fitness_server/errors.py`, `api/errors.py`, `programs.py`, `people.py`,
`library/service.py`, `schemas.py` (the weekday validator), `api/programs.py`; tests `addon/server/tests/test_errors.py`
(new) and the existing program/people tests.

**Interfaces:**
- Produces: `NotFound`, `Conflict`, `Invalid`, `Unavailable` take optional keyword arguments `code: str | None` and
  `field: str | None`. REST error bodies become `{"detail": <unchanged>, "code": <str>, "field": <str | null>}` for these
  four (the `code` key is always present: the given code, else `not_found`, `conflict`, `invalid`, `unavailable`).
  The weekday rule raises `PydanticCustomError("weekday_needed", ...)` so its 422 list item has `type: "weekday_needed"`.
- Codes: `name_taken` (field `name`), `session_running` (field null), `weekday_needed` (field `active`, for
  `set_active`'s `Invalid`), `station_unknown` and `station_shared` (field `stations.<index from 0>`),
  `too_many_people`, `person_twice`, `person_unknown` (field `people`), `ha_unavailable`, `changed_elsewhere`.
- `PUT /api/v1/programs/{id}` takes an optional query parameter `if_updated_at` (the `updated_at` the client read, ISO
  8601). When it is given and differs from the stored one: 409 with code `changed_elsewhere`. Without it: as today.

- [ ] **Step 1: Write the failing tests** in `test_errors.py` (REST):
  - a taken name on create and on replace → 409, `code == "name_taken"`, `field == "name"`, `detail` is still the
    same string as before;
  - delete and `active: false` during a running session → 409, `code == "session_running"`, `field is None`;
  - an active program without weekdays on create → 422 whose list has an item with `type == "weekday_needed"`;
    `PUT /active` on a program without weekdays → 422 `code == "weekday_needed"`;
  - an unknown station → 422, `code == "station_unknown"`, `field == "stations.2"` for the third, `detail` unchanged
    (the dict with `close_matches`);
  - three people → 422 `code == "too_many_people"`; HA unreachable on the people write → 503 `code == "ha_unavailable"`;
  - `if_updated_at` equal → 200; different → 409 `code == "changed_elsewhere"`; omitted → 200 even after another
    write;
  - a session route's refusal body is unchanged: `{"detail": {"code", "message"}}` and no top-level `code`.
  - MCP: the same refusals give the same `ToolError` text as before (pick two existing MCP error tests and keep them).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement** per the Interfaces block. Raise with codes at each named place. The handler adds `code`
  and `field` beside `detail`.
- [ ] **Step 4: Run** the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): stable error codes and an opt-in conflict check for program writes`.

### Task 3: "Created by" and the setup store (add-on)

Model: opus · Review: yes

**Files:** `migrations/versions/0006_setup_and_created_by.py`, `models.py`, `schemas.py`, `programs.py`, `setup.py`
(new service), `services.py`, `api/setup.py` (new), `api/__init__.py` (router); tests `test_setup.py`,
`test_programs_created_by.py` (new).

**Interfaces:**
- `programs.created_by` column: `"claude"` or `"you"`, nullable. Set at create from the client: `mcp:` → `"claude"`,
  anything else → `"you"`. The migration fills it for existing programs from the change log's `program.created` row
  (`target == "program:<id>"`), else leaves it null. `ProgramOut.created_by: Literal["claude", "you"] | None`.
- `class Setup(BaseModel)`: `equipment: list[str]` (library equipment values, sorted, unique; `body weight` always
  included on read), `favourite_playlists: list[FavouritePlaylist]` with `FavouritePlaylist(uri: str, name: str)`
  (unique by uri, at most 20), `default_speaker: str | None` (matching `^media_player\.[a-z0-9_]+$`).
- `Setup` stored as one JSON document (a `setup` table with one row). `SetupService.get() -> Setup`,
  `SetupService.set(setup: Setup, client: str) -> Setup` (logs `setup.updated` in the change log).
- REST: `GET /api/v1/setup` → `Setup` (empty defaults: `["body weight"]`, `[]`, null). `PUT /api/v1/setup` → `Setup`;
  an unknown equipment value → 422 `code == "equipment_unknown"`, `field == "equipment"`.
- New programs created through REST without music get no music (the default speaker is the site's job, Task 8).

- [ ] **Step 1: Write the failing tests:** create via REST → `created_by == "you"`; via MCP `create_program` →
  `"claude"`; a program created before the migration (insert through the previous revision, or create, then null the
  column and add a change-log row with client `mcp:x`) → `"claude"` after the migration's backfill; setup round trip;
  `body weight` always present; unknown equipment refused with the code; the change log has `setup.updated`.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** One migration (0006) for both the column and the table.
- [ ] **Step 4: Run** the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): programs know who created them, and a setup for the household`.

### Task 4: Library reads, the household filter and `get_setup` (add-on, MCP)

Model: opus · Review: yes

**Files:** `library/service.py`, `schemas.py` (`Facets.target`), `api/exercises.py`, `mcp_tools.py`; tests
`test_exercises_all.py` (new), `test_mcp.py`.

**Interfaces:**
- `GET /api/v1/exercises/all` → `list[ExerciseSummary]`: every library and custom exercise, by name. Registered before
  `/{exercise_id}`.
- `Facets` gains `target: list[str]`.
- `GET /api/v1/exercises` and MCP `search_exercises` take `household: bool = False`. When true: only exercises whose
  equipment is in the setup's equipment, plus `body weight`, plus every custom exercise (whatever its equipment).
- MCP `get_setup()` → `Setup` (read-only). The `create_program`/`update_program` and `search_exercises` descriptions
  say: prefer the household's equipment (`get_setup`, or `household: true`) when suggesting exercises, and offer the
  favourite playlists and the default speaker first when asking about music.

- [ ] **Step 1: Write the failing tests:** `/exercises/all` returns 1,324 + customs, each with `target`; facets have
  `target`; `household=true` with setup `["dumbbell"]` returns body weight, dumbbell and a custom exercise with null
  equipment, and no cable exercise; MCP `get_setup` returns the stored setup; MCP `search_exercises(household=true)`
  matches REST; the descriptions contain `get_setup` and "favourite playlists" (key words only).
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): read every exercise, filter by household equipment, and get_setup for Claude`.

### Task 5: The server serves the site (add-on)

Model: opus · Review: yes

**Files:** `settings.py` (`web_dir`), `app.py`, `ingress.py` (→ the fallback page only), `i18n/en.json` (fallback
text), delete `i18n/da.json`, `tests/test_ingress.py` → `tests/test_site_serving.py`.

**Interfaces:**
- `Settings.web_dir: Path`, default `Path("/opt/ha-fitness/web")`, from `HA_FITNESS_WEB_DIR`.
- `GET /` (and HEAD): `web_dir/index.html` when it exists, else the fallback HTML page (English: "The HA Fitness
  website isn't built." plus the version). Static files under `/web/` from `web_dir` (`StaticFiles`), mounted before
  the MCP mount and after the `/api` catch-all.

- [ ] **Step 1: Write the failing tests:** with a temp `web_dir` holding `index.html` and `assets/app.js`: `/` returns
  that HTML; `/web/assets/app.js` returns the file; `/web/missing.js` → 404 (not MCP's plain text: assert JSON or a
  404 status only, whichever StaticFiles gives, as long as it isn't served by MCP); without `web_dir`: `/` returns the
  fallback with the version; `/mcp` still answers MCP; an unknown `/api/x` still a JSON 404.
- [ ] **Step 2: Run them to see them fail.**
- [ ] **Step 3: Implement.** Remove the status page's rendering and its Danish texts; keep `ingress.py` only if the
  fallback uses it.
- [ ] **Step 4: Run** the add-on gates.
- [ ] **Step 5: Commit** `feat(addon): serve the website at the panel's root, with a fallback page`.

### Task 6: The site's skeleton, Status page, and build (web, image, CI)

Model: opus · Review: yes

**Files:** create `addon/web/` (`package.json`, `package-lock.json`, `tsconfig.json`, `eslint.config.js`,
`vite.config.ts`, `index.html`, `.gitignore` with `dist/` and `node_modules/`, `src/main.ts`, `src/app-shell.ts`,
`src/api.ts`, `src/i18n.ts`, `src/i18n/en.json`, `src/theme.css` or a Lit `css` module, `src/icons.ts`,
`src/pages/status-page.ts`, `test/fake-api.ts`, `test/shell.test.ts`, `test/status.test.ts`, `test/build.test.ts`);
modify `addon/Dockerfile`, `addon/.dockerignore`, `.github/workflows/ci.yml` (a `web` job like `cards`),
`.github/dependabot.yml` (npm `/addon/web`, with the TypeScript hold), `scripts/setup` (npm ci in `addon/web`),
`scripts/develop` (build the site once and watch it; `HA_FITNESS_WEB_DIR=addon/web/dist` for the server),
`docs/notes.md` (the node image pin is bumped by hand).

**Interfaces:**
- Same tool versions as `cards/package.json` (lit 3.3.3, vite, vitest, happy-dom, @testing-library/dom, typescript
  6.0.3, eslint) plus `@mdi/js`. Scripts: `build`, `watch`, `test`, `lint` as in the cards.
- Vite: `base: "./"`, output `dist/` with `index.html` and `assets/` (so assets resolve to `web/…` — set
  `build.assetsDir` and the HTML's paths so the server's `/web/` mount serves them; the HTML itself is served at `/`).
- `api.ts`: `createApi(fetchFn = fetch)` returning typed functions for every route the site uses, with paths relative
  (`api/v1/...`, no leading `/`). Errors become `class ApiError { status: number; code: string | null; field: string |
  null; message: string; detail: unknown }` (for a 422 list: `code` from the first item's `type`, `field` from its `loc`
  without `body`).
- `app-shell.ts`: `<hf-app>` with the menu **Programs, Library, Setup, Status** and hash routes `#/programs`,
  `#/programs/new`, `#/programs/<id>`, `#/library`, `#/setup`, `#/status` (default `#/programs`).
- `i18n.ts`: `t(key: string, vars?: Record<string, string | number>): string` from `en.json`.
- `icons.ts`: `icon(path: string)` → an inline `<svg>` with `@mdi/js` paths; theme values defined in the site (HA's
  light theme: background `#fafafa`, card `#fff`, border `#e0e0e0`, primary `#03a9f4`-family as the mockups use).
- `test/fake-api.ts`: a fake `fetch` holding programs, exercises, setup, people, speakers and playlists in memory,
  recording each request (method, path, body), able to answer a given status and body for a route.
- Dockerfile: a stage `FROM --platform=$BUILDPLATFORM node:<24-alpine>@sha256:<digest> AS web` that runs `npm ci` and
  `npm run build` in `addon/web` and a `COPY --from=web .../dist /opt/ha-fitness/web` in the final stage.

- [ ] **Step 1: Write the failing tests:** the shell shows the four menu items as links and switches pages by hash;
  the Status page shows the version (from `api/v1/health`), the library counts and media state (`api/v1/library`), the
  people and the programs, and links to `api/v1/library` and `api/v1/health`; `createApi` calls `api/v1/health`
  (relative); `ApiError` parsing for the three error shapes (Task 2's body, a 422 list, a plain string detail);
  `build.test.ts` builds nothing but reads `vite.config.ts`'s `base` as `./` (or, if simpler, run the build in CI and
  assert in a small node script that `dist/index.html` has no `src="/` or `href="/`).
- [ ] **Step 2: Run them to see them fail** (`npm test --prefix addon/web`).
- [ ] **Step 3: Implement** the files above.
- [ ] **Step 4: Run** `npm run lint --prefix addon/web && npm test --prefix addon/web && npm run build --prefix
  addon/web`; build the image locally once (`docker build addon`) and check `/opt/ha-fitness/web/index.html` exists;
  `uv run actionlint && uv run zizmor --offline .github/workflows`.
- [ ] **Step 5: Commit** `feat(addon): the website's skeleton with the Status page, built into the image`.

### Task 7: Programs list, copy, switch and delete (web)

Model: opus · Review: yes

**Files:** `addon/web/src/pages/programs-page.ts`, `src/components/confirm-dialog.ts`, `en.json`;
`test/programs.test.ts`.

**Interfaces:** consumes `createApi`, `ApiError`, `t`, the fake API. Produces `#/programs` (W1) and the delete dialog
(W5) reused by Task 8.

- [ ] **Step 1: Write the failing tests:**
  - rows show name, length, weekdays, thumbnails (an `img` per station with alt = the exercise name, `src` relative
    `api/v1/exercises/<id>/thumbnail`), music name or "None", "Created by" "Claude"/"You", an active switch;
  - search by name and the filters All/Active/Off narrow the rows;
  - the switch sends `PUT api/v1/programs/<id>/active`; a 409 `session_running` shows the add-on's message by the row
    and leaves the switch as it was;
  - Copy sends `POST api/v1/programs` with name `"<name> (copy)"`, `active: false`, the same stations and music; a 409
    `name_taken` shows the message; on success it opens `#/programs/<new id>`;
  - Delete opens a dialog (role `dialog`) with the history/open days/can't-be-undone text and "Turn it off instead";
    confirming sends `DELETE`; "Turn it off instead" sends `PUT .../active {active: false}`; a 409 `session_running`
    shows the message in the dialog;
  - "New program" goes to `#/programs/new`.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website lists, copies, switches and deletes programs`.

### Task 8: The program editor (web)

Model: opus · Review: yes

**Files:** `src/pages/program-editor.ts`, `src/components/exercise-picker.ts` (the library panel, shared with Task 9's
filters), `src/components/exercise-details.ts` (W4 dialog, shared with Task 9), `en.json`; `test/editor.test.ts`.

**Interfaces:** consumes Task 7's confirm dialog; Task 4's `api/v1/exercises/all`, `api/v1/setup`; Task 2's error
codes and `if_updated_at`; `api/v1/music/speakers`, `api/v1/music/playlists`.

- [ ] **Step 1: Write the failing tests:**
  - `#/programs/new` (W2): "Start empty" and "Copy a program"; empty starts active with no weekdays and no music;
    saving without a weekday shows the add-on's `weekday_needed` message at the weekdays, and nothing typed is lost;
  - editing loads `GET api/v1/programs/<id>`; Save sends `PUT … ?if_updated_at=<updated_at>` with the whole document;
  - a program with `music: {playlist, playlist_name, speaker, volume: 35, shuffle: true}`: saving keeps volume 35 and
    shuffle true; picking another playlist sets both `playlist` and `playlist_name` from it; the favourite playlists
    are listed first; a speaker not in the speakers list still shows and is kept;
  - a new program's speaker is the setup's `default_speaker`; music is sent only once a playlist is picked;
  - add an exercise from the panel (+), remove one (×), move one up and down with the buttons (roles), and the order
    in the sent `stations` follows; 15 is the most the add-on allows (send 16 → its 422 is shown, nothing lost);
  - the panel shows only household exercises by default (setup `["dumbbell"]`: a cable exercise absent, a custom
    exercise present) and "Show all" shows the rest; ✓ marks exercises in the program;
  - a click on a panel exercise opens the details dialog (big GIF `img` with the attribution text, equipment, body
    part, target, secondary muscles, the steps);
  - "Not saved" shows after a change; leaving to `#/programs` with unsaved changes asks first (a dialog), and
    `beforeunload` is set while dirty;
  - a 409 `changed_elsewhere` shows a message with "Reload"; the form keeps its values;
  - a 409 `name_taken` shows at the name; a refusal without a field shows above the form;
  - Delete in the editor uses Task 7's dialog.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's program editor`.

### Task 9: Library page (web)

Model: opus · Review: yes

**Files:** `src/pages/library-page.ts`, `en.json`; `test/library.test.ts`.

- [ ] **Step 1: Write the failing tests:** search by name; filters by equipment, body part and target with several
  values each (from the facets); household filter on by default with "Show all"; custom exercises always shown;
  values shown as the dataset names them; the details dialog (Task 8's component) opens on click; thumbnails are
  `img` elements with `loading="lazy"`.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's library page`.

### Task 10: Setup page (web)

Model: opus · Review: yes

**Files:** `src/pages/setup-page.ts`, `en.json`; `test/setup.test.ts`.

- [ ] **Step 1: Write the failing tests:**
  - equipment chips for every facet value with `band` and `resistance band` as one "band" chip (toggling it sends
    both values); body weight shown on and not removable; Save sends `PUT api/v1/setup`;
  - favourite playlists: add from `api/v1/music/playlists`, remove; default speaker from `api/v1/music/speakers`;
    without Music Assistant (empty lists) the music parts say so and the rest saves;
  - people: list from `GET api/v1/people` (HA's persons and the stored people); add (at most 2), reorder; they save on
    their own (`PUT api/v1/people`); removing a person opens a confirmation explaining stats/history/sensors/new
    person; a 503 `ha_unavailable` shows the message and keeps the choice.
- [ ] **Step 2–4:** fail, implement, run the web gates.
- [ ] **Step 5: Commit** `feat(addon): the website's setup page`.

### Task 11: Docs

Model: sonnet · Review: no

**Files:** `docs/architecture.md`, `docs/domain-language.md`, `docs/decisions.md`, `addon/DOCS.md`, `docs/testing.md`,
`docs/mockups/README.md`.

- [ ] **Step 1:** Per spec §7: the website, routes (setup, exercises/all, `household`, `if_updated_at`, error codes),
  `get_setup`, serving and routing, the setup terms, and decisions D62 (the website in the image at the panel's root,
  admin only in v2, English only in v2 as an exception to hard rule 6, own icons and theme as an exception to D51),
  D63 (the setup, people on the website, `get_setup`), D64 (the whole dataset: set D13 and D30 to
  `active; <the filtered part> superseded by D64`), D65 (stable REST error codes). Check the last decision number first
  and number from there.
- [ ] **Step 2:** `uv run python scripts/check_links.py`.
- [ ] **Step 3: Commit** `docs: the add-on website, the setup and the whole dataset`.

### Task 12 (after the feature PR merges): root files

Model: sonnet · Review: no · A separate branch and PR, `docs:` type.

- [ ] `CLAUDE.md`: layout (`addon/web/`), the web gates, and hard rule 6 naming the website's English-only exception in
  v2 with D62. `.pre-commit-config.yaml` only if the web lint needs a hook. Commit `docs: CLAUDE.md for the add-on
  website`.

### After the tasks (controller)

- `full-reviewer` on the branch; the fast loop with the site; the Chrome check of W1–W6's pages with screenshots in
  `screenshots/2026-10-26-program-website/`; the full loop builds the image with the site and shows it in the panel.
- The PR (`feat(addon): the website to manage programs, the library and the setup`), then Task 12's PR.
