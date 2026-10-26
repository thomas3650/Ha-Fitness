# The add-on's website: programs, library and setup

**Status:** draft for Thomas's approval. Issue #85 (the choice of option B and Thomas's review are in its comments).
The mockups are in [`docs/mockups/website/`](../../mockups/website/) (W1–W6, 1440×900). They show the layout and the
Danish texts; the mockups' notes in the corner aren't part of the screens.

**Real Home Assistant:** no change is needed there beyond the release. The website ships in the add-on and shows in the
add-on's panel in HA's sidebar ("HA Fitness"), as the status page does today. The release's `fitness` issue tells the
house that the panel now holds the editor.

**Builds on:** the add-on's REST API and service layer (D3: REST and MCP are thin adapters), the Ingress page (D27), the
library (D13, D30), the change log, people (at most 2, linked to HA persons), the music reads (`/api/v1/music/*`), and
D1, whose reason for the add-on was this editor.

## 1. Why

Thomas, 2026-10-26, in chat:

- **Claude** must be able to create training programs (MCP, as today).
- **Thomas** must be able to create and change programs himself. He does it **on a computer or through Claude**,
  never from the kitchen tablet or the phone.
- He wants **a better overview of the exercises**: search them and filter on the equipment the household has, and
  other filters.
- **Elin** should be able to change programs later (v3 or v4). She isn't an HA administrator.

Option B was chosen over a dashboard card (issue #85): the editor is used on a computer by an administrator, Thomas and
Claude edit through the same add-on service layer, and the integration and the cards don't change.

## 2. Goals

### 2.1 Where and who

1. A website served by the add-on, shown in its Ingress panel ("HA Fitness" in HA's sidebar). It replaces today's
   status page at the panel's root; the status stays as one of its pages (§2.5).
2. **Administrators only in v2:** the panel keeps HA's default (`panel_admin` true). Nothing in v2 may make it harder
   to open the website to other users later (Elin, v3/v4).
3. A computer screen first (from about 1280 px wide). It needn't work on a phone or the tablet.
4. Its texts follow the browser's language: Danish or English, as the status page does (D27). Exercise names and
   instructions are never translated (hard rule 6).
5. HA's light look, as the cards (D51, D52): white cards with a grey border, HA's blue, `mdi:` icons.
6. A menu with four pages: **Programmer, Bibliotek, Opsætning, Status**. There is no people page and no history page.

### 2.2 Programs (mockups W1, W2, W3, W5)

1. **The list (W1):**
   - search by name;
   - filters: all, active, off;
   - one row per program: its name and length, its weekdays, its exercises as thumbnails, its music, **"Oprettet af"**
     (Claude or Dig), an active switch, and edit, copy and delete;
   - a "Nyt program" button.
2. **"Oprettet af"** says who created the program: Claude (an MCP write) or Dig (the website, or any other REST client).
   It is the only place Claude is named. There is nothing else about Claude on the website, and no per-program history.
3. **New program (W2):** start empty, or copy a program.
   - Empty starts with the defaults: 5 rounds, 45 s work, 15 s break between exercises, 60 s between rounds, a 5 s
     countdown, and the setup's default speaker (§2.4).
   - A copy is named "<name> (kopi)", switched off, and is stored only when saved. Its "Oprettet af" is Dig.
4. **The editor (W3):**
   - at the top: name, rounds, work, break between exercises, rest between rounds;
   - weekdays; music (the setup's favourite playlists first, §2.4) and speaker; countdown (0, 5 or 10 s); active;
   - the exercises as a list: drag to reorder, × to remove, 1–15 exercises;
   - the library beside it (search, filters, + to add, ✓ when already in the program; a click shows the exercise's
     details, W4);
   - a line with the number of exercises, the total time and the equipment needed, and "Ikke gemt" while there are
     unsaved changes;
   - Gem, Annullér and Slet. Leaving with unsaved changes asks first.
   - The rules are the add-on's (`ProgramDocument`): a refused save shows the add-on's reason at the field it is about,
     and nothing is lost from the form.
5. **Delete (W5):** a confirmation that says the history and stats stay, the program's open training days go, and it
   can't be undone, with "Slå det fra i stedet". While a session for the program runs, the add-on refuses (D42) and
   the website says why.
6. **A change made elsewhere** (Claude, or another browser tab) while the editor is open: saving must not silently
   undo it. (How is left to the builder, §8.)

### 2.3 Library (mockup W4)

1. A page to browse the exercises: search by name, and filter by equipment, body part and target muscle. Several
   values of a filter can be chosen.
2. By default it shows only exercises the household can do: those whose equipment is in the setup's equipment
   (§2.4), body weight always included. "Vis alle" turns that off. The editor's library panel works the same.
3. An exercise's details (W4): a big GIF, equipment, body part, target and secondary muscles, and the instructions in
   English, with the dataset's attribution.
4. Custom exercises (made through Claude) are listed too, without media.

### 2.4 Setup ("Opsætning", mockup W6)

1. **Equipment:** which of the library's equipment the household has. Body weight is always there. The library's
   equipment values are English; whether the website shows them in Danish through the language files is the
   builder's call (they aren't exercise names, so hard rule 6 allows it).
2. **People:** which of HA's persons train, at most 2, in order (the colours follow the order), as `set_people` does
   today. The same rules and errors as the people write.
3. **Favourite playlists:** chosen from Music Assistant's playlists (`/api/v1/music/playlists`). They come first in
   the editor's music choice.
4. **Default speaker:** chosen from Music Assistant's speakers. New programs get it.
5. **Claude uses the setup too:** the MCP tool descriptions say to prefer the household's equipment when suggesting
   exercises, and to offer the favourite playlists and the default speaker first when asking about music (#76). (Claude's
   call: a guess Thomas didn't object to.)
6. Without Music Assistant the music parts show an empty list and say so; the rest of the setup works.

### 2.5 Status

The page shows what today's status page shows: the version, the library and media state, the people and the programs,
and the links to the JSON status and health.

## 3. Unchanged

- The integration, the cards and the tablet's screens.
- What a program is (`ProgramDocument`) and its rules, the scheduler, sessions and stats.
- MCP's tools, apart from the descriptions in §2.4.5 and whatever reading the setup needs.
- The API version: everything here is an addition (`api_version` stays 1).

## 4. Non-goals

- Elin editing (v3/v4), and any user other than an administrator.
- Phone or tablet layouts.
- A history of changes per program.
- Making custom exercises on the website (Claude does that).
- Starting a workout from the website.

## 5. Anti-goals

- **A website that can lose work:** a refused save or a change made elsewhere must not throw away what Thomas typed.
- **Tests pinned to the implementation** (Thomas): components and code can be refactored without rewriting the tests.
- **A second set of rules:** the website never decides what a valid program is; the add-on does.

## 6. Constraints

- **Tech: Lit and TypeScript** (Thomas, 2026-10-26), with the same tooling as the cards (Vite, Vitest, ESLint, the
  language-file pattern). It is a separate app from the cards bundle.
- **Built into the add-on image.** The add-on's Docker build context is `addon/`, so the website's source lives under
  `addon/` and is built in the image (a pinned build stage), not committed as a built file (hard rule 3's spirit). The
  image is built for aarch64 and amd64 in CI.
- **Ingress paths:** the panel serves the site under a changing Ingress path, so the site uses relative URLs and calls
  the add-on's REST API through Ingress (HA's login), never port 8765 directly (#21).
- **Tests (Thomas):** through what a user and the other parts see. The pages are tested through rendered text, roles
  and labels, and the requests they send to a faked REST API; no tests of component internals, no snapshots, no CSS
  selectors (hard rule 5). The new REST routes are tested through REST, as today.
- **Gates:** the website gets its lint, test and build commands in `CLAUDE.md` and a CI job, like the cards.
- **Languages:** every text in Danish and English language files (hard rule 6).

## 7. Docs

In the same PR: `docs/architecture.md` (the website, the new routes, the setup data), `docs/domain-language.md`
(setup, favourite playlists, default speaker, "created by"), `docs/decisions.md` (a decision for the website: option
B, admin only in v2, Lit in the add-on; and one for the setup), `addon/DOCS.md`, `CLAUDE.md` (layout and gates),
`docs/testing.md` (how to run the website in the fast loop and check it in the full loop), and `docs/mockups/README.md`
pointing to the new screens.

## 8. Left to the builder

- How "Oprettet af" is known: stored on the program at creation, or read from the change log's `program.created`
  client (`mcp:…` or `rest:…`). Programs from before this change show the change log's answer, or nothing.
- How the setup is stored (a table or a document) and its REST shape.
- How the library search takes several values per filter and the target muscle.
- How a change made elsewhere is caught (a revision or `updated_at` check, or a reload prompt).
- The exact layout within the mockups' structure, and drag and drop's implementation.
- How the fast loop serves the website during development.
- Splitting the work into more than one PR, if that makes review easier.
