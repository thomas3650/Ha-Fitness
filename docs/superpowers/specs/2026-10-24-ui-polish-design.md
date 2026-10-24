# UI polish: Thomas's screen review, and closer to the mockups

**Status:** direction approved by Thomas in chat on 2026-10-24. Before he left, he asked Claude to apply the review
decisions (§2) to the rest of the screens and to move them closer to the mockups (§3). The §3 calls are Claude's.
Thomas reviews them on the open PR before it merges.

**Real Home Assistant:** no update needed beyond the next release of the integration (cards only).

**Builds on:** the UI refresh ([spec](2026-10-24-ui-refresh-design.md), D51). The add-on, the API and the integration
don't change.

## 1. Why

Thomas reviewed the built screens one by one against `docs/mockups/` and decided changes for the today card, details
and get ready. He wants the same look carried to the timer, two people, complete and ended screens, and those screens
moved closer to their mockups. All of it stays in HA's light theme with HA's icons (D51).

## 2. Thomas's decisions (his review, screenshots 1–6)

1. **Today card, a day row:** Start and Spring over sit left-aligned under the text and don't stretch across the
   row. The same holds for the late day and for Spring over's Ja / Nej.
   - **The double-tap rule stays** (training-today spec: Nej sits where Spring over was, so a wake tap's second tap
     lands on Nej). Start and Ja share one fixed width, and Spring over and Nej share the `.slot` width (9em). So Ja
     lands in Start's place and Nej in Spring over's. These fixed widths, rather than each button's natural width,
     are Claude's call; Thomas checks them on the PR.
   - **While asking,** the question "Spring over?" takes the state line's place ("I dag" / "Forfalden · fredag")
     above the buttons, instead of sitting in the button row. This is Claude's call; Thomas checks it on the PR.
2. **Today card while a workout runs:** the row is built like a day row.
   - The title is the program's name.
   - Line 1: "I gang · runde 2 af 5". While paused it reads "Pauset · runde 2 af 5". Without a phase it reads
     "I gang" or "Pauset" alone.
   - Line 2: the people and the planned length, "Thomas og Elin · 29 min".
     - One person reads "Thomas · 29 min". Two are joined by a language-file text ("{first} og {second}").
     - The minutes are rounded to the nearest minute, as get ready's summary and the add-on's `total_minutes` are,
       so the row and get ready agree. Thomas's "rounded up" becomes this through Claude's call; Thomas checks it on
       the PR.
   - ▶ Fortsæt, left-aligned under the text.
3. **Details:** "Du skal bruge" always shows. With no equipment it reads "Intet udstyr" ("No equipment"). It stays
   hidden when an older add-on sends no `equipment`. Button heights don't change.
4. **Get ready:**
   - "GÅ TIL DIN STARTSTATION" and the person cards are top-aligned with the top of the ring.
   - Each person card is white inside with a grey border.
   - There's no coloured stripe on the left. The person's colour is only on the numbered badge.
   - The same holds while paused.
5. **Button heights stay:** 48 px for normal buttons, 64 for the feeling buttons, 72 / 104 for the timer, 96 for the
   main action.

6. **Today card layout, second look (Thomas, evening 2026-10-24).** Thomas compared the built card with the
   `StatusCard` mockup on screenshots and chose a trial layout ("G"). It replaces the button placement of §2.1:
   - **Top line:** unchanged. The streak stays at the card's right edge.
   - **The ring and the text:** the week ring (96 px) at the left, beside the name and the two lines, centred
     against them. The name is bold (600) and 1.5em; the lines are 1.0625em.
   - **The buttons:** a row under the ring and the text, starting at the card's left edge (under the ring). Start,
     Spring over, Ja, Nej and Fortsæt all have one fixed width of 10em, so Ja lands in Start's place and Nej in
     Spring over's: the double-tap rule of §2.1 holds. The button text is 1.0625em and bold (600). The 48 px height
     stays.
   - **More days:** the ring sits beside the first row only. A later row's text starts at the card's left edge.
     This is Claude's call; the late-plus-due case is rare.
   - **Spacing:** 20 px at the sides.
   - **Grid rows:** the card is taller, so HA's grid rows become one for the top line plus three per row: 4 for one
     day or a session, 7 for two days.

## 3. Carried to the rest, closer to the mockups (Claude's calls)

### 3.1 The card look (every screen)

- **Cards:** a card or tile is white inside (`--card-background-color`) with a 1 px grey border (`--divider-color`).
  This covers the timer's picture and NÆSTE card, the two-person cards, details' exercise tiles, get ready's cards
  and complete's tiles.
- **The person's colour:** on a card it shows only on the numbered badge. The two-person cards lose their coloured
  top bar. The streak list's colour dots and details' people chips stay as they are, since they aren't cards.
- **Soft buttons:** Slut on the timer and Annullér on get ready become soft buttons, like the mockup's End. They are
  filled grey (`--secondary-background-color`), have no border, are 48 px high and keep the pill shape. Slut's
  question keeps its Ja / Nej as they are.

### 3.2 The timer, one person (`Timer`, `TimerRest`)

- **Pills:** the label is plain and the numbers are bold, as in the mockup: "Runde **1 / 5**", "Station **1 / 5**",
  "Interval **3 / 8**".
  - The label and the numbers render as separate parts, so each language file holds only the label word.
  - Without a total from an older add-on, only the current number shows.
- **Elapsed time:** the elapsed part is bold, and "/ 28:45" is in the secondary text colour.
- **The ring's word:** ARBEJD / SKIFT / PAUSE take the phase's colour, in a darker shade that keeps 4.5:1 contrast on
  the light background: orange `#B54708` for work, blue `#1F5FAD` for switch, rest and the countdown. The ring gets
  the word's colour as an option of its own.
  - "GÅ TIL NÆSTE STATION" takes the same blue.
  - So do get ready's GØR KLAR and "GÅ TIL DIN STARTSTATION".
- **The ring itself:** the ring's own colours (`RING_COLORS`) don't change.
- **Countdown size:** the seconds grow in landscape: 10rem in the one-person ring (400 px). Portrait stays as it is.
- **Picture:** the exercise picture is a white card with the grey border.
- **NÆSTE / DEREFTER card:** the card look of §3.1.

### 3.3 The timer, two people (`TimerDuo`)

- **The cards:** each card has the card look of §3.1, with no coloured top bar. The colour is only on the numbered
  badge.
- **Text:** the name grows to 1.5rem. The station reads "Station **3**", with the number bold.
- **The ring:** in landscape it grows from 320 to 360 px, with 7rem seconds. Portrait stays at 320 px with 6rem
  seconds.

### 3.4 Complete and ended (`Complete`)

- **Tiles:** the card look, with larger values (2.5rem; the names tile stays smaller so two names fit).
- **The streak tile:** a warm tint like the mockup's.
  - The background is orange at 10 % (`color-mix(in srgb, #FF8A3D 10%, var(--card-background-color))`).
  - The label is in the dark orange `#B54708`.
- **Hint:** a line under the feeling buttons, in the secondary text colour, small.
  - Danish: "Gemmes med træningen – Claude bruger det, når du beder om at justere programmet".
  - English: "Saved with the session – Claude uses it when you ask it to adjust the program".
- **Width:** the done column widens from 720 to 960 px, the mockup's width, so the four tiles fit in one row in
  landscape.
- **Portrait:** below a 900 px column (an 800 px tablet gives about 736 px), the tiles wrap two per row.

### 3.5 Details (`WorkoutDetails`)

- **Exercise tiles:** the card look instead of the grey fill. Nothing else changes; Thomas found details good.

## 4. Not in scope

- Music, which is parked.
- Colours from the dark mockups: the screens stay in HA's light theme (D51).
- New data from the add-on, and any change to the timer's behaviour.
- The stats card.

## 5. Testing

- **Tests:** they pin what changes in rendered text and roles:
  - the session row's lines;
  - "Intet udstyr";
  - the split pill texts, as the pill's text content;
  - the hint.
- **Chrome check:** the visual changes are checked in Chrome on the fast loop, at 1368×912 and in the 800×1280 frame.
  New screenshots go next to each mockup for Thomas's review.

## 6. Delivery

- **One PR:** `feat: UI polish from the screen review` (cards only, an integration minor bump).
- **Decision:** a new entry, D52, for the card look of §3.1 and the phase text colours of §3.2.
- **Merge:** the PR stays open until Thomas has reviewed the new screenshots.
