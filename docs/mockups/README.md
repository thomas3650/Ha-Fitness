# Mockups (v1)

These mockups are a **reference for layout and hierarchy only**. They are dark, English and 1280×800, while the
kitchen tablet runs HA's light theme in Danish at 3:2 (1368×912). The feature specs of steps 4–6 replace the screens they
touch with light, Danish, 3:2 versions. Where a mockup and a spec disagree, the spec wins.

Static HTML mockups at 1280×800 (status card 440×280), dark theme. Open the `.html` in a browser, or see the `.png`.
Exercise GIFs in `gifs/` are © Gym visual (via hasaneyldrm/exercises-dataset). Names (Thomas, Anna, Emil) are examples.

| Screen | File | Where it lives |
| --- | --- | --- |
| Today | `Main` | Lovelace today card |
| Status card | `StatusCard` | Lovelace status card |
| Skip today | `SkipDialog` | Dialog in the today card |
| Circuit details | `WorkoutDetails` | Session flow in the card, step 1 |
| Get ready (start stations) | `GetReady` | Session flow in the card, step 2 |
| Timer, 1 participant | `Timer` | Session flow in the card |
| Switch / rest, paused | `TimerRest` | Session flow in the card |
| Timer, 2 participants | `TimerDuo` | Session flow in the card |
| Timer, 3–4 participants | `TimerSquad` | Session flow in the card |
| Circuit complete | `Complete` | Session flow end |
| Program (read-only + Claude draft) | `Planner` | Add-on website (Ingress) |
| Exercise library | `Library` | Add-on website (Ingress) |
| History | `History` | Add-on website (Ingress) |

Flow: Today → (Details) → Get ready → Timer (layout by participant count) ↔ pause → Complete → Today.

Design tokens used: background `#101317`, surface `#1A1F25`, raised `#232A31`, text `#F3F5F7`, muted `#A3ADB8`, work `#FF8A3D`, rest `#4DA8FF`, done `#5BD18B`; fonts Space Grotesk (numbers, headings) and Inter (body).
