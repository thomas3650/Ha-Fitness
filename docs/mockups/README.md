# Mockups (v1)

These mockups are a **reference for layout and hierarchy only**. They are dark, English and 1280×800, while the
kitchen tablet runs HA's light theme in Danish at 3:2 (1368×912). The feature specs of steps 4–6 replace the screens they
touch with light, Danish, 3:2 versions. Where a mockup and a spec disagree, the spec wins.
The built screens follow the mockups' layout and hierarchy in HA's light colours, with `mdi:` icons
([D51](../decisions.md)).
Cards are white with a grey border, and the person's colour is only on the badge ([D52](../decisions.md)).

Static HTML mockups at 1280×800 (status card 440×280), dark theme. Open the `.html` in a browser, or see the `.png`.
Exercise GIFs in `gifs/` are © Gym visual (via hasaneyldrm/exercises-dataset). Names (Thomas, Anna, Emil) are examples.

| Screen | File | Where it lives |
| --- | --- | --- |
| Today | `Main` | Lovelace today card |
| Status card | `StatusCard` | Lovelace status card |
| Skip today | `SkipDialog` | Dialog in the today card |
| Circuit details | `WorkoutDetails` | Workout overlay (page-level, D45), step 1 |
| Get ready (start stations) | `GetReady` | Workout overlay (page-level, D45), step 2 |
| Timer, 1 participant | `Timer` | Workout overlay (page-level, D45) |
| Switch / rest, paused | `TimerRest` | Workout overlay (page-level, D45) |
| Timer, 2 participants | `TimerDuo` | Workout overlay (page-level, D45) |
| Timer, 3–4 participants | `TimerSquad` | Workout overlay (page-level, D45) |
| Circuit complete | `Complete` | Workout overlay (page-level, D45), the end |
| Program (read-only + Claude draft) | `Planner` | Add-on website (Ingress); replaced by `website/` W1–W3, W5 |
| Exercise library | `Library` | Add-on website (Ingress) |
| History | `History` | Add-on website (Ingress) |

The add-on website's screens are in `website/` ([D62](../decisions.md)). They are light and English, and show the
layout the site follows:

| Screen | File |
| --- | --- |
| W1 Programs | `website/W1-programs.png` |
| W2 New program | `website/W2-new-program.png` |
| W3 Program editor | `website/W3-editor.png` |
| W4 Exercise | `website/W4-exercise.png` |
| W5 Delete program | `website/W5-delete.png` |
| W6 Setup | `website/W6-setup.png` |

Flow: Today → (Details) → Get ready → Timer (layout by participant count) ↔ pause → Complete → Today.

Design tokens used: background `#101317`, surface `#1A1F25`, raised `#232A31`, text `#F3F5F7`, muted `#A3ADB8`, work `#FF8A3D`, rest `#4DA8FF`, done `#5BD18B`; fonts Space Grotesk (numbers, headings) and Inter (body).
