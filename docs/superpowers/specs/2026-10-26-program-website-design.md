# The add-on's website: programs, library and setup

**Status:** approved by Thomas in chat on 2026-10-26. Issue #85 (the choice of option B and Thomas's review are in its comments).
The mockups are in [`docs/mockups/website/`](../../mockups/website/) (W1–W6, 1440×900). They show the layout; their
texts are Danish, but the v2 website is in English (§2.1.5). The notes in their corner aren't part of the screens, and W6's
equipment chips are examples (§2.4.1).

**Real Home Assistant:** no change is needed there beyond the releases. The website ships in the add-on and shows in the
add-on's panel ("HA Fitness"). The release's `fitness` issue tells the house that the panel now holds the editor, and
asks it to check that the add-on's "show in sidebar" is on ([`ha-notes.md`](../../ha-notes.md)).

**Builds on:** the add-on's REST API and service layer (D3), D1 and D7 (the v2 editor is the add-on's website, in Lit),
the Ingress page (D27), the library (D13, D30), people (D33), the change log, the
music reads (`/api/v1/music/*`), and D42.

## 1. Why

Thomas, 2026-10-26, in chat:

- **Claude** must be able to create training programs (MCP, as today).
- **Thomas** must be able to create and change programs himself. He does it **on a computer or through Claude**,
  never from the kitchen tablet or the phone.
- He wants **a better overview of the exercises**: search them and filter on the equipment the household has, and
  other filters.
- **Elin** should be able to change programs later (v3 or v4). She isn't an HA administrator.
- A **setup page** for the household's equipment and the people who train ("der må gerne være en side om setup af
  udstyr og personer"), plus favourite playlists and a default speaker.

Option B was chosen over a dashboard card (issue #85): the editor is used on a computer by an administrator, Thomas and
Claude edit through the same add-on service layer, and the integration and the cards don't change.

## 2. Goals

### 2.1 Where and who

1. A website served by the add-on and shown in its Ingress panel. It replaces today's status page at the panel's root;
   the status becomes one of its pages (§2.5).
2. **Administrators only in v2**, through HA: the panel keeps HA's default (`panel_admin` true). No logic in the add-on
   or the site depends on `panel_admin`, so opening the panel to other users later (Elin) is only that setting.
3. **The boundary:** HA's login protects the site only through Ingress. On the add-on's port 8765 the same app is open
   to the LAN, as the REST API already is (D44, #21); the site adds no capability the REST API doesn't have.
4. A computer screen first (from about 1280 px wide). It needn't work on a phone or the tablet.
5. **English only in v2** (Thomas, 2026-10-26). All texts come from an English language file, so Danish can be added
   later as a second file. This is an exception to hard rule 6's "Danish ships too" for the website in v2, recorded in
   the new decision; the integration, the cards and the tablet stay Danish and English.
6. HA's light look as the cards have it (D51, D52): white cards with a grey border, HA's blue, `mdi:` icons. Inside
   the Ingress iframe HA's `<ha-icon>` and CSS variables don't exist, so the site inlines the icons it uses (e.g.
   `@mdi/js` paths) and defines HA's light-theme values itself. This is a stated exception to D51's "no icon package",
   recorded in the new decision.
7. A menu with four pages: **Programs, Library, Setup, Status**. There is no history page. Pages and the
   editor survive a reload under the changing Ingress prefix (e.g. hash routes, so `/` stays the one HTML route).

### 2.2 Programs (mockups W1, W2, W3, W5)

1. **The list (W1):**
   - search by name; filters: all, active, off;
   - one row per program: its name and length, its weekdays, its exercises as thumbnails, its music, **"Created by"**
     (Claude or You), an active switch, and edit, copy and delete;
   - a "New program" button.
2. **"Created by"** says who created the program: Claude (an MCP write) or You (the website, or any other REST
   client). It shows in the list and as a small badge in the editor (W3); there is nothing else about Claude on the
   website, and no per-program history. It is stored on the program's row at creation (not in `ProgramDocument`,
   which forbids extra keys). Programs from before this change take it from the change log's `program.created` entry
   for them (by target, not the 200-row `recent()`), or show nothing.
3. **New program (W2):** start empty, or copy a program.
   - Empty starts active, with no weekdays, and the defaults the add-on fills in (5 rounds, 45 s work, 15 s break
     between exercises, 60 s between rounds, 5 s countdown). Saving it needs a weekday or switching it off; the
     add-on's refusal says so (§2.2.4).
   - A copy is named "<name> (copy)", switched off, and is stored only when saved. Its "Created by" is You. A name the
     add-on refuses (too long, or taken) is shown at the name field.
4. **The editor (W3):**
   - at the top: name, rounds, work, break between exercises, rest between rounds;
   - weekdays; music (the setup's favourite playlists first, §2.4) and speaker; countdown (0, 5 or 10 s); active;
   - the exercises as a list, 1–15: drag to reorder, and move-up/move-down buttons as well (keyboard use, and tests
     through roles); × to remove;
   - the library beside it (search, filters, + to add, ✓ when already in the program; a click shows the exercise's
     details, W4); thumbnails load lazily;
   - a line with the number of exercises, the total time and the equipment needed, and "Not saved" while there are
     unsaved changes;
   - Save, Cancel and Delete. Leaving the editor with unsaved changes, inside the site or by closing the tab, asks
     first. (A click in HA's own sidebar can't be caught from the iframe.)
   - **No second set of rules:** the form bounds nothing beyond the controls' natural ranges; the add-on decides. A
     refused save shows the add-on's reason at the field it is about (§2.6), and nothing typed is
     lost.
   - **Music:** picking a playlist sets the music's `playlist` and `playlist_name` together. A new program's speaker is
     the setup's default speaker (§2.4.4); the music is stored once a playlist is picked, since `Music.playlist` is
     required. Saving keeps the fields the editor doesn't show (`music.volume`, `music.shuffle`), because a save
     replaces the whole program. A speaker that isn't in Music Assistant's list is still shown and kept.
5. **Delete (W5):** a confirmation that says the history and stats stay, the program's open training days go, and it
   can't be undone, with "Turn it off instead". While a session for the program runs, the add-on refuses deleting and
   switching off (D42), and the site says why (§2.6), also for W1's active switch.
6. **A change made elsewhere** (Claude, or another tab) while the editor is open: saving must not silently undo it.
   The check is **opt-in** on the write: a request without it (MCP's `update_program`, other REST clients) works as
   today. On a conflict the site says so and offers to reload, keeping what was typed visible.

### 2.3 Library (mockup W4)

1. A page to browse the exercises: search by name, and filter by equipment, body part and target muscle, several values
   per filter.
2. **The household filter:** by default it shows only exercises the household can do: those whose equipment is in the
   setup's equipment (§2.4.1), body weight always included, and custom exercises always shown. "Show all" turns it
   off. The editor's library panel works the same.
3. **Where the filtering happens:** the site loads the summaries of all exercises once (id, name, equipment, body part,
   target, custom; about 1,324 rows) from a new read route, and searches and filters them itself. The REST search and
   MCP's `search_exercises` keep their limits.
4. An exercise's details (W4): a big GIF with Gym visual's attribution beside it (the `attribution` field, D13),
   equipment, body part, target and secondary muscles, and the instructions in English.
5. Equipment, body parts and target muscles are shown as the dataset names them (English).

### 2.3a The whole dataset in the library

1. The built-in library takes **every exercise** of the dataset at its pinned commit (Thomas, 2026-10-26): 1,324
   exercises with 28 equipment values, instead of the 721 with home equipment today. The data grows from about 0.5 to
   1 MB; the downloaded media from 72 MB to about 137 MB (GIFs about 129 MB, `docs/notes.md`), so the first start after
   the update downloads about 1,200 more files.
2. `scripts/build_library.py` drops its equipment filter; the data is rebuilt and committed (D30) and the media is still
   downloaded (D13). Ids stay the dataset's, so programs and history keep their exercises.
3. Six names are shared by two exercises at the pinned commit (none among today's 721). Resolving a station by such a
   name already answers "shared; give the id". A stored custom exercise whose name equals a new library name becomes
   ambiguous by name in the same way; nothing else changes for it.
4. The tablet's cards show an equipment value they have no translation for in English (`cards/src/flow/details.ts`).
   That stays as it is; §3 keeps the cards unchanged.

### 2.4 Setup (mockup W6)

1. **Equipment:** which equipment the household has. The choices are every equipment value of the library and the
   custom exercises, with `band` and `resistance band` as one choice ("band"; Claude's call). Body weight is always
   on. W6's chips are examples, not the list.
2. **People:** which of HA's persons train, at most 2, in order (the colours follow the order), with the people write's
   rules (`PUT /api/v1/people`). It is Thomas's call to have them on the website. People **save on their own**, apart
   from the rest of the setup (the people write can fail with 503 while HA is unreachable). **Removing a person asks
   first** and says what it means: their stats and history no longer belong to them, their HA sensors go, and adding
   them again makes a new person (D33).
3. **Favourite playlists:** chosen from Music Assistant's playlists (`/api/v1/music/playlists`). They come first in the
   editor's music choice.
4. **Default speaker:** chosen from Music Assistant's speakers. Programs made on the website get it.
5. **Claude reads the setup:** a read-only MCP tool `get_setup` returns the household's equipment, the favourite
   playlists and the default speaker; `search_exercises`, and the REST search with it (D3), gets an optional
   `household` flag (default false, so today's behaviour stays) that applies the household filter. The tool
   descriptions tell Claude to use them when suggesting exercises and when asking about music (#76). (Claude's call: a guess Thomas didn't object to.)
6. Without Music Assistant the music parts show an empty list and say so; the rest of the setup works.

### 2.5 Status

The page shows what today's status page shows: the version, the library and media state, the people, the programs, and
links to the JSON library status (`/api/v1/library`) and health. It reads them through the REST API.

### 2.6 Refusals

1. The site shows the add-on's own (English) message, at the field it is about. For that the add-on gives each
   refusal the site can meet a **stable code**, and the **field** where there is one:
   a taken name, a weekday needed for an active program, a station that can't be resolved, too many people, a session
   that blocks a delete or a switch-off (D42), a conflict on save (§2.2.6), HA unreachable for the people write, and
   the field-level validation errors. This is an addition to the REST error bodies (`api_version` stays 1): an
   existing route's `detail` keeps its type and meaning, and new fields go beside it. The session routes keep their
   `{code, message}` detail and codes, which the integration reads. MCP's error texts stay as they are.
2. The code lets the site react (for example offer a reload on a conflict, or "Turn it off instead" when a delete is
   refused); the field places the message. A refusal without a field is shown above the form.

## 3. Unchanged

- The integration, the cards and the tablet's screens.
- What a program is (`ProgramDocument`) and its rules, the scheduler, sessions and stats.
- MCP's tools, apart from `get_setup`, the `household` flag and the descriptions in §2.4.5.
- The API version: everything here is an addition (`api_version` stays 1).

## 4. Non-goals

- Elin editing (v3/v4), and any user other than an administrator.
- Phone or tablet layouts.
- A history of changes per program.
- Making or editing custom exercises on the website (Claude does that).
- Starting a workout from the website.
- Protecting the LAN port (#21).

## 5. Anti-goals

- **A website that can lose work:** a refused save or a change made elsewhere must not throw away what was typed.
- **Tests pinned to the implementation** (Thomas): components and code can be refactored without rewriting the tests.
- **A second set of rules:** the site never decides what a valid program is; the add-on does.

## 6. Constraints

- **Tech: Lit and TypeScript** (D7; Thomas, 2026-10-26), with the cards' tooling (Vite, Vitest, ESLint, the
  language-file pattern). A separate app from the cards bundle.
- **Source and build:** the site's source lives under `addon/` (the image's build context). The image builds it in a
  node stage pinned by digest (built for the build platform, so both arches get the same files) and copies the output
  to a fixed folder outside the Python package (the package is built by hatchling, which would leave a git-ignored
  folder out). The server finds the folder through a setting with that default. The node pin is bumped by hand, as the
  `uv` pin is (noted in `docs/notes.md`). `addon/.dockerignore` excludes the site's `node_modules` and build output.
  The build output is never committed (hard rule 3's spirit).
- **Serving:** the site's assets get their own route or mount under a named prefix, before the MCP mount (which takes
  every unmatched path, D26); `/` serves the site's HTML. Without a built site (pytest, the CI `addon-server` job, a
  fast loop without a build), `/` serves a short English page that says the website isn't built.
  `ingress.py`'s status page and `test_ingress.py` are replaced. The server's `i18n/` keeps only `en.json`, with the
  fallback page's text; `da.json` is removed. `docs/architecture.md`'s "Routing in the add-on server" is updated.
- **Ingress:** the site uses relative URLs and calls the REST API through Ingress.
- **Tests (Thomas):** through what a user and the other parts see. The pages are tested through rendered text, roles
  and labels, and the requests they send to a faked REST API; no tests of component internals, no snapshots, no CSS
  selectors (hard rule 5). The new and changed REST routes and MCP tools are tested through REST and MCP, as today.
- **Gates and tooling:** the site gets lint, test and build commands and a CI job, a Dependabot npm entry (with the
  TypeScript hold from `docs/notes.md`), `scripts/setup` and `scripts/develop` support, and a `.gitignore` for its
  build output in its own folder. Making the new CI job a required check is a GitHub setting and needs Thomas's OK.
- **Releases:** the feature touches `addon/`, `docs/`, `scripts/` and `.github/` (none of them releases the
  integration). Changes
  to root files (`CLAUDE.md`, `.pre-commit-config.yaml`, the root `.gitignore`) go in a separate `docs:`/`chore:` PR
  that merges after the feature PR, so the integration doesn't release unchanged
  ([`releasing.md`](../../releasing.md), D29). The site's build output is ignored by a `.gitignore` inside its own
  folder under `addon/`.
- **Languages:** every text in the site's English language file (§2.1.5); the fallback page's text in the server's
  English file.

## 7. Docs

- `docs/architecture.md`: the website, the new and changed routes and MCP tools, the setup data, the error codes, the
  routing.
- `docs/domain-language.md`: setup, household equipment, favourite playlists, default speaker, "created by".
- `docs/decisions.md`:
  - the website is built into the add-on image and served at the panel's root, admin only in v2, English only in v2
    (an exception to hard rule 6), with its own icons and theme values (an exception to D51);
  - the setup (equipment, people on the website, favourites, default speaker) and `get_setup`;
  - the whole dataset, which sets D13 and D30 to `active; <the filtered part> superseded by D<n>`;
  - stable error codes for the REST API.
- `addon/DOCS.md`, `docs/testing.md` (the site in the fast loop and the full loop), `docs/mockups/README.md` (the new
  screens), `addon/server/src/ha_fitness_server/library/NOTICE.md` and `scripts/build_library.py`'s docstring (both say
  "filtered"), `docs/notes.md` (the node pin).
- `CLAUDE.md` (layout, gates, and hard rule 6 naming the website's English-only exception in v2 with the new
  decision's number): in the separate root-files PR (§6). Until it merges, the build's dispatches and reviews cite the
  new decision for the exception.

## 8. Left to the builder

- The store and REST shape of the setup, and the read route for all exercise summaries.
- The error codes' names and the error body's shape (additive), and the opt-in conflict check's mechanism.
- How "Created by" is stored and the change-log fallback is read.
- The exact layout within the mockups' structure, and drag and drop's implementation.
- How the fast loop serves the site during development.
- Splitting the feature into more than one PR, as long as the root files go in their own PR, merged last (§6).
