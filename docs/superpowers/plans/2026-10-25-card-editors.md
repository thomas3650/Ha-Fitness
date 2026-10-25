# Card editors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Give the three cards a visual editor with the `language` field, so HA shows its Layout tab, and make the
today card's height follow its content.

**Architecture:** One editor class in `cards/src/card-editor.ts`, with a subclass defined per card tag from each
card's `register*Card()`. Each card gets `static getConfigElement()` and `static getStubConfig()`. The editor is a
native `<select>` styled with HA's CSS variables, and its texts follow the HA user's language. The today card's
`getGridOptions()` returns `rows: "auto"`.

**Tech Stack:** Lit 3, TypeScript, Vitest with happy-dom and `@testing-library/dom`.

**Status:** approved by Claude on 2026-10-25, after `full-reviewer` rated it Ready (round 2).

**Spec:** [`docs/superpowers/specs/2026-10-25-card-editors-design.md`](../specs/2026-10-25-card-editors-design.md)

## Global Constraints

- Hard rule 5: tests through public interfaces — the `config-changed` event's config, roles and rendered text,
  `getGridOptions()` / `getCardSize()` / `getStubConfig()` results. No snapshot or CSS-selector tests.
- Hard rule 6: every editor text from `cards/src/i18n/en.json` and `da.json`.
- Spec §6: no HA-internal elements (`ha-form`, `ha-select` …) in the editor; no new runtime dependency.
- Spec §6: editors are defined inside the `register*Card()` functions, guarded with `customElements.get`, never at
  module load.
- Hard rule 7: nothing under `config/` or `local/`; no hook bypass.
- Branch `feat/card-editors` in the main checkout (the fast loop runs from it). Commit with `git commit -F <file>` and
  the trailer the dispatch gives.

## Review Focus

1. A config with keys the editor doesn't know (`grid_options`, `visibility`, `foo`): a change keeps them all (Task 1
   test `keeps the rest of the config`).
2. A config with `language: da-DK` typed in YAML: shown, and unchanged until the field changes (Task 1 test
   `keeps an unknown language until changed`).
3. Opening the editor without touching it: no `config-changed` at all (Task 1 test `sends nothing until changed`).
4. A card config whose `language` is English while the user is Danish: the editor still speaks Danish (Task 1 test
   `follows the user's language, not the card's`).
5. Two programs due on one day: the today card isn't cut off after a width change (Task 2 test, plus the controller's
   Chrome check §8.2).

---

### Task 1: The editor, wired into the three cards

Model: opus · Review: yes

**Files:**
- Create: `cards/src/card-editor.ts`
- Modify: `cards/src/today-card.ts`, `cards/src/workout-card.ts`, `cards/src/stats-card.ts` (statics and the
  `register*Card()` functions only)
- Modify: `cards/src/i18n/en.json`, `cards/src/i18n/da.json`
- Test: `cards/test/card-editor.test.ts` (new); `cards/test/register-wait.test.ts`, `register-now.test.ts`,
  `register-cap.test.ts` (the three editor tags added to their tag lists)

**Interfaces:**
- Produces, in `card-editor.ts`:
  - `export function registerCardEditor(tag: string): void` — defines a fresh subclass of the editor class under
    `tag` unless `customElements.get(tag)`.
  - The element's public surface (HA's contract): `hass` property (`{ locale?: { language?: string } }`),
    `setConfig(config: Record<string, unknown>): void`, and a `config-changed` `CustomEvent` with
    `detail: { config }`, `bubbles: true`, `composed: true`.
- Editor tags: `ha-fitness-today-card-editor`, `ha-fitness-workout-card-editor`, `ha-fitness-stats-card-editor`.
- Each card class gets `static getConfigElement(): HTMLElement` (creates its editor tag) and
  `static getStubConfig(): Record<string, unknown>` returning `{}`.
- Language-file keys (`editor.*`), exact texts:

  | Key | en | da |
  | --- | --- | --- |
  | `editor.language` | Language | Sprog |
  | `editor.language_default` | Follow the user's language | Følg brugerens sprog |
  | `editor.language_en` | English | English |
  | `editor.language_da` | Dansk | Dansk |

- [ ] **Step 1: Write the failing tests** in `cards/test/card-editor.test.ts`. Import `../src/index` (it registers
  everything at once outside HA). The file has its own typed interfaces in the style of `CardElement` (no `any`; the
  lint gate's `no-explicit-any` is an error): `CardClass` (`getConfigElement(): HTMLElement`,
  `getStubConfig(): Record<string, unknown>`), reached as `customElements.get(tag) as unknown as CardClass`, and
  `EditorElement` (`hass`, `setConfig`, `updateComplete`). For each of the three card tags (`test.each`), create the
  editor with `getConfigElement()`, append it to `document.body`, set `hass` and call `setConfig` with an
  `Object.freeze`d config (nested objects frozen too, so an editor that mutates HA's config throws), await
  `updateComplete`, and find the field with `getByRole(root(editor), "combobox", { name })`, where `root()` is
  `editor.shadowRoot as unknown as HTMLElement` as in `today-card.test.ts`. Change it by setting `value` and
  dispatching a bubbling `change` event. An `afterEach` clears `document.body`. Tests:
  - `opens with the language field in Danish`: hass `da`, config `{type}` → the combobox named "Sprog" has options
    `["Følg brugerens sprog", "English", "Dansk"]`, the first selected.
  - `labels in English`: hass `en` → named "Language", options `["Follow the user's language", "English", "Dansk"]`.
  - `follows the user's language, not the card's`: hass `da`, config `{type, language: "en"}` → named "Sprog",
    "English" selected.
  - `choosing English sets language`: from `{type}` → one `config-changed` with `{type, language: "en"}`.
  - `choosing the default removes language`: from `{type, language: "da"}` → `{type}` (no `language` key).
  - `keeps the rest of the config`: from `{type, language: "da", grid_options: {columns: 6, rows: "auto"},
    visibility: [{condition: "user", users: ["x"]}], foo: 1}` choose English → the same object with only
    `language: "en"`.
  - `keeps an unknown language until changed`: from `{type, language: "da-DK"}` → an option reading `da-DK` is
    selected; no event; choosing "Dansk" sends `language: "da"`.
  - `sends nothing until changed`: `setConfig` twice and a `hass` change → no `config-changed`.
  - `the stub config adds no options`: `getStubConfig()` equals `{}`. (The existing card tests already mount and
    render each card with `{type}` alone, which is the stub config HA's picker builds; they are the render evidence.)
  - `labels in English before hass`: `setConfig` with no `hass` set → named "Language" (HA may set the config
    first).

  In `register-wait.test.ts`, `register-now.test.ts` and `register-cap.test.ts`, add `ha-fitness-today-card-editor`,
  `ha-fitness-workout-card-editor` and `ha-fitness-stats-card-editor` to the tag lists, so an editor defined at module
  load fails `register-wait`.
- [ ] **Step 2: Run** `npm test --prefix cards -- card-editor`. Expected: FAIL (`getConfigElement` is not a function).
- [ ] **Step 3: Implement** `card-editor.ts` and the language keys. The editor renders a `<label>` tied to a native
  `<select>` (accessible name from `editor.language`), its texts from `localize(hass?.locale?.language, …)`. Options:
  default (value `""`), `en`, `da`, plus the config's own value as an extra option when it is set and not `en`/`da`.
  **Set the selection in `updated()`:** `this.renderRoot.querySelector("select")!.value = <current>`. Lit's
  `.value=` on the `<select>` is committed before its options exist (it shows the first option on first render, in
  browsers too), `?selected` on mapped options is broken in happy-dom, and a `selected` attribute stops moving the
  selection once the user has changed it. Setting `value` from code fires no `change`. On `change`, build
  `{...config}` with `language` set, or deleted for `""`, store it as the editor's config, and fire `config-changed`
  (so a re-render before HA calls `setConfig` back keeps the new choice); never fire from
  `setConfig` or a `hass` change. Style with HA's CSS variables (`--primary-text-color`, `--secondary-text-color`,
  `--divider-color`, `--card-background-color`, `--primary-color` on focus), 56 px high, full width, so it sits like
  HA's own fields in the light theme.
- [ ] **Step 4: Wire the cards.** Add the two statics to each card class, and call `registerCardEditor(<editor tag>)`
  inside each `register*Card()`, after its early-return guard, so the card and its editor are defined together or
  neither is.
- [ ] **Step 5: Run** the cards gates: `npm run lint --prefix cards && npm test --prefix cards && npm run build
  --prefix cards`. Expected: PASS, the existing tests unchanged.
- [ ] **Step 6: Commit** `feat(cards): a visual editor for each card, with the language option`.

### Task 2: The today card's height follows its content

Model: sonnet · Review: yes

**Files:**
- Modify: `cards/src/today-card.ts` (`getGridOptions()`, its return type and its doc comment)
- Test: `cards/test/today-card.test.ts` (the existing `the grid rows follow the days`)

**Interfaces:**
- `getGridOptions(): { columns: "full"; rows: "auto" }` returns `{ columns: "full", rows: "auto" }`.
  `getCardSize()` keeps `1 + 3 * rowCount`.

- [ ] **Step 1: Replace the existing test.** Rename `the grid rows follow the days` to `full width, the height follows
  the content` and keep its four cases (before data, one day, two days, a session): `getGridOptions()` equals
  `{ columns: "full", rows: "auto" }` in each, and `getCardSize()` is 4, 4, 7 and 4.
- [ ] **Step 2: Run** `npm test --prefix cards -- today-card`. Expected: FAIL on `rows`.
- [ ] **Step 3: Implement:** return `rows: "auto"`; update the doc comment (the height follows the content, so a
  width set in HA's Layout tab doesn't fix it).
- [ ] **Step 4: Run** the cards gates as in Task 1 Step 5. Expected: PASS.
- [ ] **Step 5: Commit** `feat(cards): the today card's height follows its content`.

### Task 3: Docs

Model: sonnet · Review: no

**Files:** `docs/architecture.md`, `docs/decisions.md`, `docs/ha-notes.md`, `docs/testing.md`.

- [ ] **Step 1:** Edit per spec §7, in the docs' plain style (`docs/way-of-working.md` §5):
  - `architecture.md`, the **Cards** bullet: the bundle now also registers the three editors (the sentence naming
    "the three cards and `ha-fitness-workout-flow`"); each card has a visual editor with the `language` option; width
    and height are HA's Layout tab; the today card's height is `auto` (grid rows), and `getCardSize()` still counts.
  - `decisions.md`: **D59: The cards have visual editors; layout is HA's**, dated 2026-10-25, status active. Decision:
    each card has a visual editor; options go there, layout stays HA's Layout tab, never a control of ours. The
    editor uses `getConfigElement` with native controls, not `getConfigForm` or `ha-form`, and its texts follow the
    HA user's language (a narrow exception to D38). Why: HA builds the Layout tab only around a visual editor;
    `getConfigForm` has no `hass`; `ha-form` loads lazily and doesn't render in tests. Source: the card editors
    spec §2, §6, linked from `decisions.md` as `superpowers/specs/2026-10-25-card-editors-design.md`.
  - `ha-notes.md`, **The frontend**: four facts — HA builds the Layout and Visibility tabs only around a visual
    editor; `getConfigForm()` is called without `hass`, so its labels are static; `ha-form` and the like load lazily,
    so a custom editor can't count on them; the Layout tab's size slider stores `rows` with `columns` (taken from the
    card's defaults), the "Full width" switch only `columns`.
  - `testing.md`, the Chrome check: for a card change, open each card's editor; check the Layout tab and the language
    field.
- [ ] **Step 2: Run** `uv run python scripts/check_links.py`. Expected: exit 0.
- [ ] **Step 3: Commit** `docs: the card editors (D59)`.

### After the tasks (controller)

The branch review (`full-reviewer`), then the gates and the Chrome check of spec §8 in the fast loop, with screenshots
in `screenshots/2026-10-25-card-editors/`, before the PR. The PR notes, and the release's `fitness` issue later, say
that a house today card without its own `rows` changes to its content's height.
