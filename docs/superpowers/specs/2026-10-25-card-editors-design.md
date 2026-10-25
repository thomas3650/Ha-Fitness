# Card editors: set up the cards in Home Assistant's dashboard editor

**Status:** approved by Thomas in chat on 2026-10-25. Issue #65. The today-card options he asked for after (days ahead, missed days) are #70.

**Real Home Assistant:** no update needed beyond the next release of the integration (cards only). After the update
the house's cards open in the visual editor, and a today card without its own `rows` takes its content's height
instead of a counted 4 or 7 rows (§2.3). The release's `fitness` issue mentions this.

**Builds on:** the card `language` option (D38) and the cards' grid sizes (UI polish spec §2.6). The add-on, the API
and the integration's Python don't change.

## 1. Why

Thomas tried to set the width of "Træning i dag" (the today card, with Start and Spring over) on a dashboard and
couldn't. Opening any of the three cards in the dashboard editor shows only YAML, with "Visuel redigering understøttes
ikke" ("Visual editing is not supported").

Checked in the dev HA (Chrome, 2026-10-25, screenshot
`screenshots/2026-10-25-card-editors/today-editor-before-landscape.jpg`) and in HA's frontend (20260930):

- Without a visual editor, HA's card dialog shows the YAML editor alone. The **Layout** tab (width and height in a
  sections view) and the **Visibility** tab are not shown. HA builds those tabs only around a card's visual editor
  (`hui-card-element-editor`).
- `grid_options` typed in YAML does work: HA merges the card's own `getGridOptions()` with the config's
  `grid_options`, and the config wins. So the gap is the missing editor. Thomas just wants to tell the card how to
  span the grid without writing YAML.
- The Layout tab's size slider stores both `columns` and `rows` in `grid_options`, with the rows taken from the
  card's defaults at that moment. The "Full width" switch stores only `columns`; "Auto height" stores `rows: auto`.

## 2. Goals

1. Each of the three cards has a visual editor in HA's card dialog:
   - `custom:ha-fitness-today-card` ("Træning i dag");
   - `custom:ha-fitness-workout-card` (the active programs, with Start);
   - `custom:ha-fitness-stats-card` (stats per person).
2. With the editor, HA shows its Layout tab in a sections view, so the width and height can be set there. What is set
   there is stored as `grid_options` in the card's config and wins over the card's defaults. This is HA's own
   behaviour; the cards don't change it.
3. **The today card's height follows its content.** Its default rows become `auto` instead of the counted
   `1 + 3 × rows`. Without this, setting the width with the slider would also fix the height at whatever the card
   showed that day (§1): 4 rows would cut off a day with two programs due, 7 would leave space on a normal one. With
   `auto`, the slider stores `rows: auto` and the height keeps following the open days. `getCardSize()` (masonry
   views) keeps its count. The other defaults stay (§3). This is Claude's call; Thomas checks it on the PR.
4. The editor has one field, the card's `language` (D38), the only option the cards have today:
   - **Follow the user's language** (the default): the option is left out of the config.
   - **English:** `language: en`.
   - **Dansk:** `language: da`.

   "English" and "Dansk" are each language's own name, the same in both language files; the default's label is
   translated. This is Claude's call.

   A change sends the config it got with only `language` set or removed. Every other key stays as it was: `type`,
   `grid_options`, `visibility` and keys the editor doesn't know. Choosing the default removes `language`, so it
   doesn't stay as an empty value. A config with another value typed in YAML (for example `language: da-DK`, which
   the cards read as Danish) keeps working; how the editor shows it is the builder's call, as long as it isn't
   changed until the field is.
5. Adding a card from HA's card picker gives a card that works at once: `getStubConfig()` adds no options. HA's
   picker sets the `custom:` type itself.
6. Every label and option text in the editor comes from the cards' language files, in English and Danish (hard rule
   6). The editor's texts follow the HA user's language (`hass.locale.language`), not the card's `language` option,
   because the editor is for whoever edits the dashboard. This is Claude's call, a narrow exception to D38.

## 3. Unchanged

- The other default grid sizes: the today and stats cards still default to the full width, and the stats card's
  `min_columns` stays 6. The workout card keeps having no grid defaults.
- A card set to fewer rows than its content needs is HA's normal behaviour for a fixed height; the cards don't
  guard against it.
- The card picker's names and descriptions (they come from the language files in English, as today).
- The cards' rendering and behaviour outside the editor, apart from the today card's height (§2.3).

## 4. Non-goals

- New card options, such as choosing which people the stats card shows, a title, or hiding parts of a card. Each
  can come later as its own issue.
- A custom layout control of our own. Width and height are HA's Layout tab.
- Changes to the house's dashboards. They belong to the house assistant.

## 5. Anti-goals

- An editor that rewrites a config the user didn't change: opening the editor and saving must leave an existing
  config (with or without `language`, with or without `grid_options`) as it was.
- An editor that breaks the YAML mode: the dialog's "Show code editor" still works and round-trips.
- A hard-coded English (or Danish) label anywhere in the editor.

## 6. Constraints

- Lit and TypeScript in `cards/`, as the cards are. No new runtime dependency.
- **HA's editor contract:** the card class has `static getConfigElement()` returning the editor element and
  `static getStubConfig()`. The editor takes `hass` and `setConfig(config)` and sends `config-changed` with
  `detail.config`, bubbling and composed.
  - HA's other route, `static getConfigForm()` (a schema HA renders itself), is not used. HA fetches that form
    without `hass`, so its option texts can't follow the user's language (goal 6). This is Claude's call.
- **No HA-internal elements in the editor** (`ha-form`, `ha-select` and the like). HA loads them lazily, so they may
  not be defined when our editor first renders, and they don't exist in Vitest, where no label would render. The
  editor is built from native elements styled with HA's CSS variables, so it looks at home in HA's dialog in the
  light theme (D51). The field has an accessible name from the language file. This is Claude's call; it replaces
  the issue's `ha-form` suggestion.
- **Registration:** each editor element is defined together with its card, inside the `register*Card()` function that
  `whenFrontendReady` calls (`cards/src/register.ts`, [`ha-notes.md`](../../ha-notes.md#the-frontend)), never at
  module load. Each define is guarded with `customElements.get`, as the cards are.
- **Tests** check behaviour through public interfaces (hard rule 5), per card:
  - the config the editor sends for each choice, equal to the input config with only `language` set or removed
    (including a config with `grid_options`, `visibility` and an unknown key);
  - the field's rendered label and options in English and Danish, found by role and text;
  - that the stub config renders a card.

  No snapshot or CSS-selector tests.

## 7. Docs

- `docs/architecture.md`, the cards section: each card has a visual editor with the `language` option; width and
  height are HA's Layout tab; the today card's height is `auto`.
- `docs/decisions.md`, D59: "The cards have visual editors; layout is HA's". It records §2.2 and §4 (we add options
  to the editors, never our own layout control), and the calls in §2.6 and §6 (editor element over `getConfigForm`,
  native controls, editor texts in the user's language).
- `docs/ha-notes.md`, the frontend section: HA builds the Layout and Visibility tabs only around a visual editor;
  `getConfigForm()` is called without `hass`; `ha-form` and the like load lazily; the Layout tab's slider stores
  `rows` with `columns`.
- `docs/testing.md`, the Chrome check: open each card's editor and check the Layout tab and the language field.

## 8. How it's checked

- The gates, with the Vitest tests in §6.
- The Chrome check in the fast loop, screenshots in `screenshots/2026-10-25-card-editors/`, before the PR (Thomas
  asked for this):
  1. After a full reload, open one of our editors first, before any of HA's own card editors. The language field
     shows and works. Then each card opens in the visual editor, with no "Visual editing is not supported" note.
  2. The Layout tab shows for each card in a sections view. Changing the today card's width with the slider changes
     it on the dashboard, and it stays after saving and reloading. The saved `grid_options` has `rows: auto`. The
     card's height then follows the open days, neither cut off nor padded: one day (`scripts/seed --today`), then
     two (`scripts/seed --short` after it).
  3. The language field: choosing English, Dansk and back to the default changes the card's texts and the saved
     YAML as §2.4 says, and keeps `grid_options`.
  4. The editor's labels in Danish (the dev user's language) and in English.
  5. Adding each card from the card picker gives a working card.
  6. Opening and saving an existing card without changes leaves its YAML as it was.
  7. The today card hidden (nothing open) and shown in edit mode looks as before, apart from the height.

## 9. Left to the builder

- One editor class per card, or one shared class with a subclass per tag.
- The language-file keys for the editor's texts.
- The native control (a `<select>` or radio buttons) and its exact styling, within §6.
