# A tidier program editor: cards, top tabs, "My equipment" in the dropdown

**Status:** Thomas chose the design in chat on 2026-10-26 (option E1 of three, with "My equipment" in the equipment
dropdown) and handed the approval of this spec and its plan to Claude ("you approve spec and plan and merge and do a
new release"). Issue #92.
The mockup is [`docs/mockups/website/W7-editor-cards.png`](../../mockups/website/W7-editor-cards.png) (1440×900). It
shows the layout; the note in its corner and the example values (exercises, counts, the household's equipment) aren't
part of the screen. Where the mockup and this text differ, the text wins: the panel's count reads "325 exercises"
(§2.3.7), the name has the breadcrumb line above it (§2.2.1), and the move buttons show on every row (§2.2.5).

**Real Home Assistant:** no change is needed there beyond the release. The 1.2.0 release carries both the website
(#86) and this change.

**Builds on:** the website spec ([`2026-10-26-program-website-design.md`](2026-10-26-program-website-design.md)): D62
(English only, Lit, its own icons and theme), the editor's rules (§2.2), the library's household filter (§2.3, D63), and
the searchable multi-select added in #86 (Task 14).

## 1. Why

Thomas, after using the website in the full loop: "i think can need some better ui/ux". Inside HA the site's own side
menu is a second sidebar, and the editor's fields are uneven (two numbers to a row, a lone "Rest between rounds", the
countdown beside the music). The editor's library panel has small native selects. The Library page needs a "Show all"
checkbox beside the equipment filter to reach exercises for equipment the household doesn't have.

## 2. Goals

### 2.1 The menu as tabs at the top (every page)

1. The site's menu becomes a bar of tabs across the top: the brand ("HA Fitness" with its icon, not a link) on the left,
   then Programs, Library, Setup and Status as links with their icons, and the version on the right. The current tab is
   marked (colour and an underline) and has `aria-current="page"`, as the side menu's links have today.
2. The side menu goes. The pages get its width.
3. On a narrow window the bar scrolls sideways; it never wraps onto two rows, and the labels stay.

### 2.2 The editor in cards (W7)

1. **The head:**
   - A breadcrumb line: "Programs" (a link) › the page's title as today ("New program", "Copy of a program", "Edit
     program"; `pageTitle()`, still the page's `h1`), and the "Created by …" badge.
   - Under it the name: today's "Name" text field, always a field, styled as a large heading (no border until hover or
     focus, a decorative pencil icon at its end). Its placeholder is "Unnamed program". A new program and a copy open
     with focus in it. A name refusal shows under it, as today (`aria-invalid`, `aria-describedby`).
   - On the right: "Not saved" while there are changes, or "Saved" (`role="status"`) right after a save, in the same
     place; Delete (only once the program is stored); Cancel; Save.
   - A conflict (`changed_elsewhere`) and other page-level refusals show full width under the head, as today.
2. **When** (a card): the seven weekday buttons and the Active switch on one row. The weekday refusal shows in it.
3. **Music** (a card beside When, marked "optional"): the playlist and the speaker dropdowns. The speaker shows its
   name; a stored speaker that Music Assistant doesn't list shows its entity id with a note, as today. The music notes
   and refusals stay inside this card.
4. **Timing** (a card, full width), one row of five fields:
   - Rounds, Work, Break between exercises and Rest between rounds are number fields with a − and a + button around
     them ("Fewer rounds"/"More rounds", "Less work"/"More work" …, from `en.json`). The buttons step by 1 for rounds and
     by 5 s for the seconds. They don't clamp to the add-on's limits: the site keeps no second set of rules (website spec
     §5); − stops at 0. On an empty field, − and + set the add-on's default (`/programs/defaults`, now read for every
     editor load); if that read failed they set 0. A typed value
     is kept as typed; an empty field is still sent as null. A refusal shows under its field, as today.
   - Countdown stays a dropdown of 0, 5 and 10 s (website spec §2.2.4), styled like the other fields.
   - The title row shows the total, composed from two plural texts: "29 min in all · 5 rounds × 5 exercises".
5. **Exercises** (a card, full width):
   - One row per station: drag handle, number, a 48 px picture, the name with equipment and body part under it, move up,
     move down and remove. The move buttons are always visible (they are the keyboard's way to reorder). The whole row
     drags, as today.
   - The title row: "Exercises", the count, the equipment summary, and the hint "drag to reorder · add from the
     library →". The empty text (`editor.no_stations`), a `stations` refusal (under the title) and per-station refusals
     (on their row) stay.
6. Everything else the editor does today stays: the rules of website spec §2.2 (weekday needed when active, the leave
   guard, `if_updated_at`, copy, the defaults for a new program, delete with its confirmation). The details dialog opens
   from the library panel's names, as today.
7. **Narrow windows:** inside Ingress on a 1280 px screen with HA's sidebar open the page is about 1024 px wide. When the
   editor column is too narrow, Music goes under When and the Timing fields wrap onto two rows. Nothing overflows or is
   clipped. The library panel keeps its width.

### 2.3 The equipment filter: My equipment, All equipment, or picked kinds

1. One dropdown chooses the equipment filter (D66). Its list has two groups:
   - **Show:** two lines, *My equipment* and *All equipment*. My equipment is the household's equipment from the setup
     plus body weight; its line lists the kinds and how many exercises of the whole library that gives. Custom exercises
     always show under it (website spec §2.3.2). All equipment is no equipment filter; its line shows the library's size.
     These counts ignore the search and the other filters.
   - **Or pick equipment:** every equipment value of the library and of the custom exercises. Values the household
     doesn't have are marked "not at home" (body weight never is); they can be picked. `band` and `resistance band`
     are one value "band" that stands for both, as on Setup. Picking values replaces the mode:
     the filter is then those values (OR), and a custom exercise shows only when its equipment matches.
2. The default is My equipment. Choosing My equipment or All equipment clears the picked values and closes the list;
   choosing the mode that is already on does nothing. Picking or unpicking a value keeps the list open. Removing the
   last picked value goes back to My equipment.
3. The field shows the choice as tags: "My equipment" (no ×), "All equipment" (its × goes back to My equipment), or one
   tag per picked value with ×. Backspace in the empty search removes the last picked value, or turns All equipment
   back into My equipment.
4. Typing filters the picked-values list by name, as the multi-select does today; the two mode lines show only while
   their label matches ("kettle" shows only kettlebell).
5. **Roles:** one listbox (`aria-multiselectable="true"`) with two `role="group"`s named "Show" and "Or pick equipment";
   every line is an `option` with `aria-selected`; "not at home" is part of the option's accessible name (e.g. "barbell,
   not at home"). The field is the combobox it is today. Whether this extends `hf-multi-select` with groups or is a new
   component is the builder's call; Setup keeps the plain multi-select.
6. **Where:** the editor's library panel and the Library page. The Library page's "Show all" checkbox goes. Its body
   part and target filters stay multi-selects.
7. Counts use `library.count` ("325 exercises") after all filters, on the Library page and in the panel, with
   `Intl.NumberFormat("en")` (1,324).

### 2.4 The editor's library panel

1. Title "Library" with the count of matching exercises (§2.3.7). A failed setup read shows at the top of the panel
   (My equipment is then body weight plus the custom exercises, as today), and its note stays in the Music card too
   (it explains missing favourites and a missing default speaker).
2. Search, then two dropdowns side by side: equipment (§2.3) and body part (a multi-select). The target filter stays on
   the Library page only.
3. Result rows: picture, name (a button that opens the details dialog), equipment · body part, and an add button. For an
   exercise already in the program the add button is a green tick with the name "Add push-up again (in the program)";
   it still adds (a station can repeat an exercise, as today).
4. The 100-row cap and its note stay.

## 3. Non-goals

- No API change. The add-on, the integration and the cards don't change.
- The Programs list, New program, Setup and Status pages change only by the menu (§2.1).
- No Danish (D62), no mobile layout, no clamping to the add-on's limits in the site.

## 4. Constraints

- Lit + TypeScript in `addon/web/`; texts in `src/i18n/en.json`; icons from `@mdi/js` via `src/icons.ts`.
- Accessibility as in §2.3.5; the tabs are a `nav` with links; the name field, the number fields, the − and + buttons
  and the dropdowns have accessible names.
- The site's styles stay scoped (the menu leak found in #86).

## 5. Tests and checks

- Tests through roles, rendered text, requests and events (hard rule 5).
- **Tests that go, replaced by the new behaviour:** the Library page's "Show all" (on, its full value lists, dropping
  picks when it goes off), the panel's "Show all", the panel's native selects and its target filter, and the panel's
  separate ✓ beside +.
- **New behaviour to test:** the three modes and their moves (§2.3.2–3), custom exercises under My equipment and only
  when they match under picked values, "not at home" in the option names, the mode lines' counts and the matching
  count, the − and + buttons (steps, the stop at 0, the start from the default on an empty field), the name field's
  placeholder and focus, the green tick's name, and `aria-current` on the tabs.
- Everything else in today's editor and library tests keeps its behaviour.
- Gates: `npm run lint --prefix addon/web && npm test --prefix addon/web && npm run build --prefix addon/web`, plus the
  link check.
- The fast loop and the Chrome check of every page with screenshots in `screenshots/2026-10-26-editor-cards/`: the
  editor against W7 at 1440 px and at about 1024 px. The full loop before the release (the panel under Ingress).

## 6. Docs

- `docs/mockups/README.md`: W7 added as the editor's current screen (W3 stays as the first version).
- `docs/domain-language.md`: "My equipment" as the website's name for the household's equipment.
- `docs/decisions.md`: D66, the equipment filter's three modes (My equipment, All equipment, picked kinds), which
  replace the "Show all" checkbox of the website spec §2.3.
