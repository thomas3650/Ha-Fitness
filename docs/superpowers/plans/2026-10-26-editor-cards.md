# A tidier program editor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The website's menu as top tabs, the program editor in cards (W7), and one equipment filter with My equipment,
All equipment or picked kinds on the editor's library panel and the Library page.

**Architecture:** Web only (`addon/web/`). A small filter module holds the equipment rules; a new
`<hf-equipment-filter>` component draws them; the shell, the Library page and the editor use it. No API change.

**Tech Stack:** Lit 3 + TypeScript, Vite, Vitest + Testing Library (as in `addon/web/`).

**Spec:** [`docs/superpowers/specs/2026-10-26-editor-cards-design.md`](../specs/2026-10-26-editor-cards-design.md)
(approved by Claude on Thomas's word); the website spec it builds on:
[`2026-10-26-program-website-design.md`](../specs/2026-10-26-program-website-design.md).

## Global Constraints

- Texts only from `addon/web/src/i18n/en.json`; English only (D62). Exercise names as the dataset names them.
- Icons from `@mdi/js` through `src/icons.ts`; theme tokens from `src/theme.ts`. No new bare element selectors in the
  shell; the bar's rules sit under its class (the menu leak of #86). The shell's shared base rules (`h1`, `h2`, `a`,
  `button`, `table`) stay.
- Tests through roles, rendered text, requests and events (hard rule 5); harness `test/fake-api.ts`, `test/mount.ts`,
  `test/setup.ts`. No CSS-selector tests.
- No second set of program rules in the site: no clamping to the add-on's limits (spec §2.2.4).
- Gates per task: `npm run lint --prefix addon/web && npm test --prefix addon/web && npm run build --prefix addon/web`;
  docs tasks also `uv run python scripts/check_links.py`.
- Commits: Conventional Commits with `git commit -F <file>` (file under `.superpowers/sdd/2026-10-26-editor-cards/`),
  ending with the trailer lines the dispatch gives.

## Review Focus

1. **Custom exercises:** shown under My equipment whatever their equipment; under picked kinds only when they match;
   under All always. Task 1 tests all three.
2. **Band:** `band` and `resistance band` are one value "band"; picking it matches both; "not at home" only when neither
   is in the setup. Task 1 tests it.
3. **An empty or failed setup read:** My equipment is body weight plus the custom exercises; every other kind is "not
   at home". Task 1 (the rule) and Task 4 (the panel's note) test it.
4. **An empty timing field and the steppers:** − and + set the default (0 if the defaults read failed); − stops at 0;
   an empty field is still sent as null. Task 3 tests it.
5. **The keyboard reorder:** move up/down stay reachable and named on every row after the restyle. Task 3 keeps the
   existing test green.

---

### Task 0: decision, words and mockup map

Model: sonnet · Review: no

**Files:** `docs/decisions.md`, `docs/domain-language.md`, `docs/mockups/README.md`.

- [ ] D66 (next number), date 2026-10-26, active (Source: a link to the spec's §2.3): "The website's equipment filter has three modes: My equipment (the
  household's equipment plus body weight; custom exercises always show), All equipment, or picked kinds (OR; custom
  exercises only when they match). It replaces the website spec's 'Show all' checkbox." Why: one control instead of a
  dropdown plus a checkbox; Thomas chose it from the W7 mockup.
- [ ] `domain-language.md`: "My equipment" as the website's name for the household's equipment (one line, beside the
  household setup entry).
- [ ] `docs/mockups/README.md`: add `W7 Program editor (cards) | website/W7-editor-cards.png` to the website table and
  say W3 was the first version.
- [ ] Check links; commit `docs: D66, My equipment, and the W7 mockup`.

### Task 1: the equipment filter (rules and component)

Model: opus · Review: yes

**Files:**
- Create: `addon/web/src/library-filter.ts`, `addon/web/src/components/equipment-filter.ts`,
  `addon/web/test/library-filter.test.ts`, `addon/web/test/equipment-filter.test.ts`
- Modify: `addon/web/src/components/exercise-picker.ts`, `addon/web/src/pages/library-page.ts` and
  `addon/web/src/pages/setup-page.ts` (move `inHousehold`, `searchByName`, `facetValues`, `FACETS` into
  `library-filter.ts`; every importer imports from there; closes the #88 item), `addon/web/src/i18n.ts` (`fill()`
  formats number values with `Intl.NumberFormat("en")`, so counts read "1,324" site-wide and plurals still work),
  `addon/web/src/i18n/en.json`, `addon/web/test/*.test.ts` where a count over 999 is asserted

**Interfaces (produces):**
- `type EquipmentChoice = { mode: "mine" } | { mode: "all" } | { mode: "picked"; values: string[] }`
- `const BAND = "band"`; `equipmentValues(exercises: ExerciseSummary[]): string[]` — every equipment value of the
  library and custom exercises, sorted, with `band`/`resistance band` folded into `"band"`.
- `household(setup: Setup | null): Set<string>` — the setup's equipment plus `body weight` (empty setup → body weight).
- `matchesEquipment(exercise: ExerciseSummary, choice: EquipmentChoice, home: Set<string>): boolean` — mine: custom, or
  equipment in `home` (non-custom with null equipment: no); all: true; picked: equipment in `values` (with "band"
  meaning both names).
- `atHome(value: string, home: Set<string>): boolean` ("band" is at home when either name is).
- `<hf-equipment-filter>`: properties `values: string[]`, `home: string[]`, `counts: { mine: number; all: number }`,
  `choice: EquipmentChoice`, `label: string`; event `change` with `detail: { choice: EquipmentChoice }`.

- [ ] **Test first** (an i18n test, e.g. in `test/api.test.ts` or a new `test/i18n.test.ts`): `t("library.count",
  { count: 1324 })` reads "1,324 exercises" and `count: 1` the singular.
- [ ] **Tests first** (`library-filter.test.ts`): custom exercises under mine / picked / all; a non-custom null
  equipment hidden under mine; band folding in `equipmentValues` and `matchesEquipment`; `household(null)` is body
  weight only; `atHome("band", …)`; the home kinds for the My equipment line fold band as `equipmentValues` does.
- [ ] **Tests first** (`equipment-filter.test.ts`, through roles): one listbox with groups "Show" and "Or pick
  equipment"; options "My equipment …", "All equipment …" with their counts (`Intl.NumberFormat("en")`); "barbell, not
  at home" as an option name, body weight never; the default tag "My equipment" has no remove button; choosing All
  closes the list and its tag's remove goes back to mine; choosing the active mode emits nothing; picking two values
  keeps the list open and emits `picked`; removing the last picked goes back to mine; Backspace order (spec §2.3.3);
  typing "kettle" leaves only kettlebell; the combobox's `aria-expanded`/`aria-activedescendant` as in
  `multi-select.ts`.
- [ ] Implement (reuse `multi-select.ts`'s keyboard and focus code where it fits; Setup keeps `hf-multi-select`).
- [ ] Gates; commit `feat(addon): an equipment filter with My equipment, All equipment or picked kinds`.

### Task 2: the menu as top tabs

Model: sonnet · Review: yes

**Files:** `addon/web/src/app-shell.ts`, `addon/web/test/shell.test.ts`, `en.json` if a label is new.

- [ ] Tests first: a `navigation` with links Programs, Library, Setup, Status; the current one has
  `aria-current="page"` on each route; the version text shows; the brand text "HA Fitness" is not a link.
- [ ] Implement spec §2.1: a top bar (brand, tabs, version), the side menu gone, the bar scrolls sideways when narrow
  (`overflow-x: auto`, `white-space: nowrap`). Keep the menu styles scoped to the bar's class.
- [ ] Gates; commit `feat(addon): the website's menu as tabs at the top`.

### Task 3: the editor in cards

Model: opus · Review: yes

**Files:** `addon/web/src/pages/program-editor.ts`, `addon/web/src/app-shell.ts` (its styles only if the editor's live
there), `addon/web/test/editor.test.ts`, `en.json`.

**Interfaces (consumes):** the API's `programDefaults()` (already in `src/api.ts`) — now read on every editor load.

- [ ] Tests first:
  - the breadcrumb link "Programs" and the `h1` page title stay; the "Name" textbox has the placeholder "Unnamed
    program" and has focus on a new program and a copy;
  - "Not saved" while dirty, then "Saved" (`status`) after a save, and Delete only once stored;
  - Timing: buttons "Fewer rounds"/"More rounds", "Less work"/"More work", "Shorter break"/"Longer break", "Shorter
    rest"/"Longer rest" (names from `en.json`); + on rounds 5 → 6; + on work 45 → 50; − on a 0 break stays 0; on an
    emptied work field + sets the default 45; with the defaults read failing it sets 0; an emptied field is still sent
    as null on Save (request body); Countdown is still a combobox of 0/5/10;
  - the total text "29 min in all · 5 rounds × 5 exercises" (two plural keys);
  - the setup-read note shows in the Music card;
  - the failed-defaults case ("sets 0") is tested in edit or copy mode: for a new program a failed defaults read is
    the load error, as today;
  - existing behaviour stays green (weekday rule, leave guard, conflict, copy, keyboard reorder, refusals per field and
    per station). Queries that change but keep their behaviour: the setup note now shows in Music and in the panel
    (`editor.test.ts` ~792: scope the query to the Music card); "5 exercises" and the minutes now sit in the Timing
    total or the Exercises title (~590).
- [ ] Implement spec §2.2 with W7 as the layout: the head; the When and Music cards side by side; the Timing card; the
  Exercises card with 48 px pictures and always-visible move buttons; page-level refusals under the head; at a narrow
  width Music goes under When and Timing wraps (CSS grid with `auto-fit`/`minmax` or a container query), nothing
  clipped.
- [ ] Gates; commit `feat(addon): the program editor in cards`.

### Task 4: the editor's library panel and the Library page

Model: opus · Review: yes

**Files:** `addon/web/src/components/exercise-picker.ts`, `addon/web/src/pages/library-page.ts`,
`addon/web/src/pages/program-editor.ts` (passing the setup), `addon/web/test/editor.test.ts`,
`addon/web/test/library.test.ts`, `en.json`.

**Interfaces (consumes):** Task 1's `EquipmentChoice`, `matchesEquipment`, `equipmentValues`, `household`,
`<hf-equipment-filter>`.

- [ ] Tests first (replacing the tests the spec §5 lists as gone):
  - panel: search, the equipment filter and a body-part multi-select (no target filter, no native selects); the count
    "325 exercises"-style after all filters; picking kettlebell shows kettlebell exercises even when not at home; All
    shows everything; custom exercises per Review Focus 1; the in-program row's button is named "Add push-up again (in
    the program)" and adds a station; the setup-read note at the top of the panel; the 100-row cap note stays;
  - on both: with a search typed or a body part chosen, the My equipment and All equipment option names still show the
    whole library's counts (spec §2.3.1);
  - Library page: no "Show all"; the equipment filter with the same modes; body part and target stay multi-selects; the
    count and the details dialog stay.
- [ ] Implement spec §2.3–2.4.
- [ ] Gates; commit `feat(addon): My equipment in the library filters`.

### After the tasks (controller)

- `full-reviewer` on the branch.
- The fast loop and the Chrome check of every page, screenshots in `screenshots/2026-10-26-editor-cards/`, the editor at
  1440 px and at about 1024 px against W7.
- The full loop: the panel under Ingress.
- The PR `feat(addon): a tidier program editor with My equipment in the filters` (Closes #92), with the rulings; merge;
  then the release (add-on 1.2.0) and the house's `fitness` issue (the panel holds the editor; check "show in
  sidebar").
