# HA Fitness – design (v1 and way of working)

- **Date:** 2026-10-23 · **Status:** approved by Thomas 2026-10-23
- **Replaces:** the `Inital design/` folder (KICKOFF.md, CLAUDE.md, docs/requirements.md, docs/process.md). Where this
  document and those files disagree, this document wins. The folder is removed in step 1 (§10); its mockups move into the
  repo as a visual reference only.
- **Who decided what:** "Thomas:" marks his decisions from the brainstorm. "Claude's call:" marks choices Claude made that
  Thomas has not explicitly confirmed; he may overrule them while reading. Everything unmarked is carried over from his
  initial design unchanged.

## 1. Why this exists

Thomas and Elin want to do circuit training at home, 1–2 days a week. They used the Exercise Timer app and the timer was
fine. **The problem was that they forgot to train**: nothing put the workout in front of them on the day.

Success looks like:
- On a training day the kitchen tablet shows that today is a training day, and they train.
- The same tablet runs the workout for both of them, showing each person's current and next exercise.
- After a month they can see, per person, the streak, workouts done, workouts missed and total time trained.
- Programs are made by talking to Claude, without fiddling with settings screens.

Anti-goals (a failure even if it technically works):
- A reminder that is easy to overlook, or that disappears before they act on it.
- Starting or skipping a workout by accident when someone taps the tablet to wake it.
- An update that installs itself in the house and breaks the dashboard or a running workout.
- Exposing anything without a login to the internet.

## 2. The people and the place

- **Thomas:** only Thomas and Elin train. No guests. So 1 or 2 participants per session.
- They train in the combined kitchen/living room, in sight of the **kitchen tablet**.
- The kitchen tablet (facts from ha-claude-a8, the session that manages Thomas's HA): Surface Pro (2017), Windows 10,
  Edge in full screen with kiosk-mode, HA user `wallpanel`, about **1368×912 CSS px** (3:2 landscape, worked out, not
  measured), touch only (no hover), HA's default **light** theme, dashboard `dashboard-kitchen` in **Danish**. The screen
  dims when idle; **the first touch wakes it and also clicks whatever is under the finger.** A photo slideshow covers it in
  set hours.
- Person entities today: `person.thomas` only. **Thomas:** he (or ha-claude-a8) creates a person for Elin in HA. No HA
  changes are made from this project's sessions.
- HA host: Home Assistant Yellow (**aarch64**), HA OS, Core 2026.10.2, Tailscale add-on installed. Remote access by name
  goes through **Cloudflared**, so HA's own port is reachable from the internet.
- Speakers (Music Assistant 2.10.6, local build): `media_player.kids_room` (Sonos), `media_player.libratonezipp_2`
  (Libratone, living room, often unavailable), `media_player.tv` (living room). None in the kitchen.

## 3. What v1 does

### 3.1 Programs

- **Thomas:** a program has a **name, its exercises and its training days** (weekdays). While it is **active** it repeats on
  those days. **Several programs can be active at once** (e.g. one on Wednesday, another on Saturday).
- Every program is a **circuit**: S stations (one exercise each), R rounds, work time W, switch time r, rest between rounds.
- **Thomas:** each program also has a **playlist and a speaker** (and start volume, shuffle), set when it is created.
- **Thomas:** programs are created and changed **only by talking to Claude** in v1, through the add-on's MCP endpoint. No
  editing UI and no draft/Apply step. Claude shows the program in chat and writes it after Thomas says yes. A program
  editor UI is **v2**.

Circuit settings (unchanged from the initial design):

| Setting | Range | Default |
| --- | --- | --- |
| Stations (one exercise each) | 1–15 | **Thomas:** 5 |
| Rounds | 1–10 | 5 |
| Work time | 10–120 s | 45 s |
| Switch time | 0–60 s | 15 s |
| Rest between rounds | 0–180 s | 60 s |
| Countdown before start | 0 / 5 / 10 s | 5 s |
| Participants (chosen at start) | 1–2, ≤ stations | — |

How a session runs (unchanged): participant 1 starts at station 1, participant 2 at station 2. Every interval everyone
works W seconds, then has r seconds to move one station on (S wraps to 1). One round = S intervals. The session ends after
R rounds. Total time = S × R × (W + r) + (R − 1) × round rest, independent of the number of participants.

### 3.2 Training days: due, late, missed, skipped

- On each weekday a program is active for, the scheduler creates a **training day** for it at 00:00 with state `due`.
- **Thomas:** a `due` training day that passes untouched **stays visible as late** ("Forfalden · onsdag") until the next
  training day of **any** program begins. At that point it is closed as `missed` and only the new day's workout shows.
  Doing it while it is late counts as `done` for its own day (history shows it was done late).
- **Claude's call:** if two training days are open at once (two programs on the same day), the card shows both and they
  pick one; the other stays open under the same rules.
- `skipped`: chosen on purpose. **Claude's call:** no reason asked; one confirmation step.
- Logs store the target and the actual (rounds done, who trained, active time, ended early), so editing a program never
  rewrites history.

### 3.3 Stats, per person

- **Thomas:** stats are **per person**: **streak, workouts done, workouts missed, total time trained**.
- **Thomas:** **a skip breaks the streak**, like a miss.
- **Claude's call:** for each closed training day, a person counts as `done` if they took part in the session, otherwise
  as `missed` (or `skipped` if the day was skipped). If only Thomas trains, the day is done for him and missed for Elin.
- **Claude's call:** a streak is the number of consecutive closed training days the person did. A day still open (due or
  late) neither adds to nor breaks it.
- **Claude's call:** time trained = time from start to end of the session, minus pauses.
- **Claude's call:** ending a session early counts as `done` if at least one full round was completed; otherwise the
  training day stays open.
- Stats are computed from the logs, not stored.
- **Thomas:** counting starts **when the app is live**. There is no manual "done" button for workouts done elsewhere.
  **Claude's call:** the add-on stores a "counting from" date, set by the first session completed in the app. Training
  days follow the due/late/missed rules from the start (so the card works as a reminder and late days don't pile up),
  but days closed before the counting date are left out of all stats.
- **Thomas:** they can **train on any day**. **Thomas:** a session started on a day with nothing due is an **extra
  session**: it counts toward each person's done count and time trained, but not toward the streak, and closes no
  training day. **Claude's call:** the workout tab lists all active programs with a Start button; starting from the
  "Træning i dag" card does that open training day, starting from the tab is an extra session.

### 3.4 The kitchen tablet

The UI is Lovelace cards in the integration. **Thomas:** light theme (mockup A from the brainstorm). **Thomas:** the
labels are Danish, while exercise names and instructions stay in English, as in the dataset.

**Language (Thomas):** everything is built in English, and every UI text comes from a language file. v1 ships **English
(the base) and Danish**. The integration uses HA's own translations (entity, service and repair texts); the cards have
their own language files and follow the HA user's language, so the kitchen tablet (user `wallpanel`) shows Danish when
that user's language is Danish. Exercise names and instructions are never translated. The Danish words used in this
document ("Træning i dag", "Spring over", "Forfalden", "Slut", "Musik utilgængelig") are the Danish file's texts.

**"Træning i dag" card** (on the kitchen overview):
- **Thomas:** small; shows the program name with **Start** and **Spring over**. Hidden on days with nothing due or late,
  like the existing "Opgaver" box. A late day shows "Forfalden · <weekday>".
- **Claude's call:** a short line under the name (exercises · rounds · about how many minutes).
- **Claude's call:** Start never starts the clock. It opens the workout's details step, so a wake-tap can't start a
  workout. Spring over asks once to confirm.
- **Claude's call:** where this card goes on the overview, and the new **workout tab** on `dashboard-kitchen`, are agreed
  with ha-claude-a8 in step 4, because the dashboards are that session's job (the house repo's own rule: a dashboard
  change is specced there first and each HA change needs Thomas's yes). The overview has no free spot today.

**Workout flow** (full screen on the tablet):
1. **Details:** exercises, total time, **who's training** (chips for Thomas and Elin, 1–2 selected), **speaker dropdown**.
2. **Get ready:** countdown; shows who starts at which station.
3. **Timer:**
   - **Thomas:** each person sees their **current exercise** big with its animation and the **next exercise** with a
     small picture underneath.
   - Ring that empties as the phase runs: orange = work, blue = switch/rest, seconds in the middle.
   - Header: round x/R, interval y/S, music mini-player, elapsed / total, Slut (end).
   - Big pause/resume (tapping the ring also pauses), previous/skip interval, end early.
   - **Thomas:** pings in the **last 5 seconds** of each phase, and a sound at each phase change, played by the tablet's
     browser.
   - Layout for 2 people: as mockup `TimerDuo`, in light. **Claude's call:** for 1 person, as mockup `Timer` (big
     current exercise, next station beside it).
4. **Done:** **Claude's call:** time trained and who trained, then back to Today; the day is marked done.

**Screen during a workout (Claude's call):** a workout runs ~45 min untouched, and the browser can't hold a wake lock
over http. So the integration exposes a "session running" binary sensor. **To agree with ha-claude-a8 in step 5:** the
house side keeps the kitchen tablet from dimming and holds the photo slideshow while it is on, and the house assistant
never installs an update during a workout. ha-claude-a8 confirmed both are workable (2026-10-23): an automation pauses
auto-dim, holds the slideshow and sets brightness; its install script refuses while the sensor is on. **Claude's call:**
the sensor is `off` whenever no session runs; it is `unavailable` only when the add-on can't be reached, which means no
session can be running either.

Session state lives in the add-on, so another screen showing the card shows the same timer. The card counts down locally
from the session state; the add-on sends only changes.

Touch targets ≥ 48 px, readable at 1–2 m, no hover, no reliance on colour alone (names and numbers on every person card).
Person colours in order: purple `#B18CFF`, teal `#3DD6C6`.

**Stats** live on the workout tab: per person streak, done, missed, time trained. **Claude's call:** this month and all
time.

The mockups in `docs/mockups/` (dark, English, 1280×800) are a reference for layout and hierarchy only. The feature specs
of steps 4–6 update the screens they touch to light, Danish and 3:2.

### 3.5 Music

- **Thomas:** each program has a playlist and a speaker; on the details step a dropdown lets them pick another speaker,
  defaulting to the program's.
- Start (after the countdown): `music_assistant.play_media` with the playlist, `enqueue: replace`, optional shuffle.
  Pause/resume follow the workout. End/complete: fade over ~5 s, then pause.
- **Claude's call:** the dropdown lists the speakers Music Assistant knows. If the speaker is unavailable, the workout
  still starts and the header shows "Musik utilgængelig". Without Music Assistant the music UI is hidden.

### 3.6 Exercise library

- Built from `hasaneyldrm/exercises-dataset` (GIFs © Gym visual, **personal use**; keep the attribution field), filtered to
  body weight, band, resistance band, dumbbell, kettlebell. Fields: id, name, equipment, target muscle, body part,
  English instruction steps, GIF, thumbnail, attribution.
- **Claude's call:** because the repo and the add-on image are public (§7), the GIFs are **never committed and never built
  into the image**. The add-on downloads the filtered set from a pinned commit of the dataset on first start into its
  `/data` folder. Until they are there, the cards show a placeholder. Size and download time are measured in the spike.
- Custom exercises added via Claude are stored separately, so a library rebuild never overwrites them.
- GIFs reach the tablet only through the integration's media proxy (one HA path; the tablet needs no internet).

### 3.7 Claude access (MCP + REST)

- Served by the add-on on **its own port**: MCP at `http://<ha-host>:<port>/mcp` (Streamable HTTP) and REST at
  `/api/v1/` with OpenAPI. Both are thin adapters over **one service layer**, which the integration's API also uses.
- **No login.** **Thomas:** in v1 it is used **only from home, on the local network** (access over Tailscale is not a v1
  requirement). The port must **not** be published through Cloudflared (Cloudflared only forwards HA's own port today;
  the first real install confirms).
- Every change is recorded in a change log (client, time, what changed).
- **Claude's call:** v1 tools (exact names left to step 3's spec): search exercises; list/get programs; create, update,
  activate/deactivate and delete a program; set people (linked to HA persons); add a custom exercise; get history and
  stats; list playlists and speakers. Write tools carry MCP destructive-hint annotations. Unknown exercise names return
  close matches. Program import/export uses the same JSON schema as the API.

### 3.8 Entities, services, events

**Claude's call:** the initial design's set, adapted to several programs and per-person stats. Exact names are fixed in
step 4's spec (domain `ha_fitness`):
- today's training (due/late), next training day, due-today binary sensor, session-running binary sensor;
- per person: streak, done, missed, time trained;
- services: complete, skip, start session, end session;
- events: due, completed, skipped, missed, phase changed.

### 3.9 Not in v1

Phone notifications and actionable reminders (**Claude's call:** the dashboard card is the reminder; add notifications
later if it isn't enough), voice cues, 3–4 participants and guests, any editing UI (v2), other workout types (Tabata,
HIIT, sets & reps, EMOM, AMRAP), schedule types other than weekdays, `todo`/`calendar` entities, authentication, https,
watch/Health Connect import, access from outside home (Tailscale), a manual "done" for workouts done without the app.

## 4. Architecture

| Part | Owns | Talks to |
| --- | --- | --- |
| **Add-on** (`addon/`, "HA Fitness") | Database, programs, people, exercise library + GIFs, scheduler, sessions, history, change log; MCP + REST on its own port; a v1 Ingress page (**Claude's call:** a minimal status page that proves the Ingress path, ready for the v2 editor) | The integration (REST + one push channel); Claude (MCP) |
| **Integration** (`custom_components/ha_fitness/`, Python) | Entities, services, events, Music Assistant calls; websocket commands and subscriptions for the cards, relayed to the add-on; media proxy for GIFs | The add-on (Supervisor discovery; a configured URL in dev); HA services |
| **Cards** (`cards/`, built into the integration) | "Træning i dag", the workout flow, stats | Only HA (`hass` websocket via the integration). A direct add-on connection is a dev shortcut only |

**Data the add-on needs from HA (Claude's call):** HA's timezone (for midnight), person entities, and Music Assistant
speakers and playlists. The add-on reads them itself through the Supervisor's HA API (`homeassistant_api: true`), so its
MCP tools work even when the integration isn't connected. In the fast loop it uses the dev HA's URL and a token from a
git-ignored `.env`.

**Thomas:** the add-on stays (rather than an integration-only design) **because v2 needs a program editor**, which gets a
natural home as the add-on's website in the HA sidebar, and because MCP can then run on its own port.

**Compatibility (Claude's call):** the add-on reports an API version. The integration supports the current and the
previous API version; if it finds another, it raises an HA repair issue saying which part to update. No non-major release
may require a newer version of the other part.

## 5. Stack

- **Add-on server: Python** (uv), **FastAPI** on uvicorn (proposed 2026-10-23, Thomas asked to settle it now). It gives
  the REST API its OpenAPI for free; its Pydantic models are the one program JSON schema used by REST, MCP, validation
  and import/export; and it can mount the MCP app on the same port.
- **MCP: FastMCP, with hand-written tools** mounted at `/mcp` in the same FastAPI app. Each tool is a thin adapter over
  the service layer, like each REST route, so REST is **not** auto-converted to MCP. Why: FastMCP's own docs say LLMs do
  significantly better with curated tools than with tools generated from OpenAPI, and the tools need LLM-oriented
  descriptions, close-match errors and destructive hints. The same endpoint serves Claude Code on Thomas's Mac and,
  if wanted later, the house assistant on the Yellow.
- **Database access:** SQLAlchemy 2 with Alembic migrations (migrations from the first schema, §10).
- **Push channel to the integration:** a websocket on the add-on.
- **Database: SQLite** in the add-on's `/data` (included in HA backups). **Claude's call, Thomas agreed:** each program is
  stored as one validated **JSON document**; training days, sessions, participants and the change log are ordinary
  tables.
- **Cards** (and later the v2 website): **Lit + TypeScript**.
- **Integration:** Python, tested with `pytest-homeassistant-custom-component` and a fake add-on API.
- **Docker Desktop:** **Thomas:** installed on his Mac (Apple Silicon, arm64, same arch as the Yellow) in step 1.

## 6. Way of working

**Thomas:** superpowers spec and plan; Thomas approves specs; Claude approves plans, merges and tests. No PO or
team-lead sessions.

Per feature:
1. **Issue** in the `v1` milestone.
2. **Brainstorm** with Thomas for larger features.
3. **Spec** in `docs/superpowers/specs/`; `full-reviewer` until Ready; **Thomas approves**. The spec says up front whether
   the change needs an update on the real HA.
4. **Plan** in `docs/superpowers/plans/`; `full-reviewer` until Ready; **Claude approves**. Each task has a `Model:` tag
   and a `Review: yes|no` line.
5. **Build** with `superpowers:subagent-driven-development`: `implementer` per task (test-first), `task-reviewer` on tasks
   marked `Review: yes`.
6. **Branch review:** `full-reviewer` until Ready.
7. **Test:** the gates, the fast loop, and for UI changes Chrome at **1368×912** with screenshots in the PR and no console
   errors. Before every release, the full loop (§8).
8. **Merge:** Claude squash-merges once CI is green and the branch review is Ready.

Agents (`.claude/agents/`):

| Agent | Model / effort | Use |
| --- | --- | --- |
| `implementer` | **Thomas:** Opus / medium | one plan task, test-first; never pushes or merges |
| `task-reviewer` | **Thomas:** Opus / medium | review of one task marked `Review: yes` |
| `full-reviewer` | **Thomas:** Opus / high | specs, plans, whole branches |

- **Claude's call:** `Review: yes` by default for anything with logic (data model, scheduler and streaks, session engine
  and rotation, the add-on↔integration contract, MCP tools, the cards' timer); `no` for scaffolding, config and docs.
- Review rounds: up to 5, then Claude rules and records the ruling in the PR (and in `decisions.md` if it is lasting).
- **Claude's call:** trivial changes (typo, one-line doc fix, no behaviour change) go straight to a PR without spec or plan.
- **Claude's call:** guards stay simple: a pre-commit hook refusing commits on `main`, `.claude/settings.json` denying pushes
  to `main` and `--no-verify`, and branch protection with required CI. No subagent guard hook.
- Questions to Thomas: one at a time in the terminal. Decisions Claude makes alone go in the PR description.
- Tests check behaviour through public interfaces (REST/MCP responses, services, websocket commands, entity states,
  events). No snapshot or CSS-selector tests, no exact log text. Frozen clock for anything time-based, including midnight
  and DST edges.

## 7. Repository

- **Thomas:** public `thomas3650/Ha-Fitness`; only Thomas can open PRs. Claude's PRs are opened with Thomas's `gh` login.
- **Claude's call:** enforced by GitHub interaction limits set to collaborators only (expire after at most 6 months; the
  renewal date goes in `docs/notes.md`), branch protection on `main` with required checks, and no other collaborators.
  Repo settings are changed only in step 1, each with Thomas's OK.
- Never committed: the exercise library's GIFs, `.env`, `config/` (dev HA), `local/`, `.superpowers/` (brainstorm and
  SDD scratch, incl. copied GIFs), `.DS_Store`, anything from the real HA. **Thomas:** the mockups go in public, including their 12 GIFs. Checked 2026-10-23: they hold no sensitive data
  (example first names Thomas, Anna, Emil; Google Fonts links; no metadata in the images).
- **Claude's call:** names follow the repo: integration domain `ha_fitness`, add-on slug `ha_fitness` and name "HA
  Fitness", cards `ha-fitness-*-card`.

Layout:
```
addon/                        # add-on: config.yaml, Dockerfile, server, library build, tests
custom_components/ha_fitness/ # integration; frontend/ holds the built cards
cards/                        # card source (Lit + TS)
tests/                        # integration tests
tools/                        # library filter/build
.devcontainer/  scripts/      # dev HA, add-on server, Supervisor dev container; setup/develop/seed
.github/workflows/            # PR title, CI, release-please, add-on image
repository.yaml  hacs.json
docs/
```

Docs:

| File | Holds |
| --- | --- |
| `README.md` | what it is, installing (add-on repository + HACS) |
| `CLAUDE.md` | layout, commands, hard rules; imports `docs/way-of-working.md` and `docs/README.md` |
| `docs/README.md` | the map of all docs: what is where, read it when |
| `docs/way-of-working.md` | §6 of this document, the agents and models, conventions |
| `docs/decisions.md` | numbered decisions (D1, D2 …): decision, why, source |
| `docs/releasing.md` | §8 |
| `docs/architecture.md` | §4: who owns what, the API contract and its version |
| `docs/domain-language.md` | program, station, round, interval, training day, due/late/missed/skipped, streak … |
| `docs/testing.md` | the fast loop, the full loop, Chrome at 1368×912 |
| `docs/notes.md`, `docs/ha-notes.md` | small learned facts; learned HA facts |
| `docs/superpowers/specs/`, `plans/` | one spec and one plan per feature; snapshots, not edited after merge |
| `docs/mockups/` | the initial mockups (reference) and updated screens |

One fact lives in one place; elsewhere, point to it. Docs change in the same PR as the code.

## 8. Releases

- **Thomas:** the add-on and the integration+cards are **released independently**, each triggered by changes in its own
  folders.
  - **Add-on:** version in `addon/config.yaml`; a release builds and pushes the image to GHCR (aarch64 + amd64) and HA
    offers the update. **No GitHub release** for the add-on, so HACS never mistakes it for an integration release.
    Changelog in `addon/CHANGELOG.md`.
  - **Integration + cards** (one unit): version in `manifest.json` and the release tag; GitHub release with changelog
    and the HACS zip.
  - **Claude's call:** release-please in manifest mode with two components does this; the add-on component skips the
    GitHub release.
- PR titles are Conventional Commits and drive the version: `feat` minor, `fix` patch, `!`/`BREAKING CHANGE` major;
  `docs`, `test`, `chore`, `refactor`, `ci` release nothing on their own.
- **Strict semver.** HA's update entities show the versions.
- **Thomas / ha-claude-a8:** after each release Claude opens an issue in `thomas3650/house` with label **`fitness`**,
  naming the part (add-on, integration or both), the version, **"major" when it is**, what changed, and the checks to run
  after installing. The house assistant installs non-major releases on its own; a major release needs Thomas's yes.
  Standing task: thomas3650/house#244. Once the repo exists, Claude sends ha-claude-a8 the repo URL, the add-on slug and
  the integration domain.
- **Thomas:** until 1.0.0, every install needs his yes. The house assistant decides from HA's update entity, not from the
  issue text, so this has to be enforced by the house gate rule. ha-claude-a8 (2026-10-23): as #244 is written, 0.2.0 →
  0.3.0 *would* install by itself. Its proposed fix: install without asking only when both the installed and the new
  version are ≥ 1.0.0 with the same major, via a house script that reads the HA Fitness update entities. **Open: Thomas
  confirms that rule in the house session.**
- **Before every release**, the full loop: the real add-on image in the Supervisor dev container, with Ingress,
  discovery and the cards checked in Chrome.

## 9. Local development and testing

- **Fast loop** (every PR): the add-on server on its own; a dev HA on `http://localhost:8123` with the integration and
  cards, finding the add-on through a configured URL; Chrome at 1368×912. `scripts/seed` creates people (Thomas, Elin),
  a fake speaker and a sample program.
- **Full loop** (before each release, and in the spike): HA's official add-on dev container (full Supervisor + HA in
  Docker, `http://localhost:7123`), driven with the dev container CLI so it needs no clicks. The add-on is installed as a
  local app.
- MCP is checked from Claude Code: add the endpoint, list tools, create a program, see it on the card.

## 10. Order of work

Each step is one feature with its own spec (step 1 is planned straight from this document) and ends with something
Thomas can try.

**How a step reaches the real HA (Claude's call):** as a 0.x release through the normal pipeline and a `fitness` issue,
installed with Thomas's yes (§8). So step 1 must already produce a public, pullable add-on image, a HACS release and the
house-issue routine. Real data exists from step 3 on, so database migrations are in place from the first schema. The
first real install (step 3) also checks that the MCP port answers on the LAN address and is not reachable through
Cloudflared.

1. **Ground structure:** repo and settings, docs (§7), agents, CI, both release pipelines, dev HA + add-on server
   scaffolds, Supervisor dev container, Docker Desktop. Mockups (including their 12 GIFs) move to `docs/mockups/`;
   `Inital design/` is removed.
2. **Spike, on the Mac** (**Thomas**; throwaway code, findings kept in docs): in the Supervisor dev container, the
   add-on installs as a local app, Ingress and Supervisor discovery work, and Claude Code lists the add-on's MCP tools;
   GIF download size and time.
3. **Programs through chat:** database, exercise library, people linked to HA persons, MCP/REST tools. *Try it:* create
   the Wednesday and Saturday programs with Claude.
4. **"Træning i dag":** scheduler (due/late/missed/skipped), integration (discovery, entities, services, events), the
   small card, the workout tab agreed with ha-claude-a8. **Claude's call:** in this step the card shows the name and
   Spring over only; Start arrives in step 5 with the workout flow. *Try it:* the reminder shows on training days.
   Nothing is counted yet (§3.3).
5. **The workout:** session engine, details, get ready, timer for 1 and 2, pings, done; finishing marks the day done.
6. **Stats:** per person streak, done, missed, time, on the workout tab.
7. **Music:** playlist and speaker per program, the speaker dropdown, pause and fade.
8. **Release 1.0.0.**

Then v2, starting with the program editor in the add-on's website.

## 11. Left to the builder

The card test tooling;
exact entity, service, event and MCP tool names (fixed in their feature specs); the add-on's port number; CI details;
how the dev container CLI is driven.
