# Way of working

How changes are made in this repo. `CLAUDE.md` imports this doc, and the agents point here instead of copying it. Hard
rules live in `CLAUDE.md`; decisions in [`decisions.md`](decisions.md). The reasons are in spec §6
([design spec](superpowers/specs/2026-10-23-ha-fitness-design.md)).

## 1. Roles

- **Thomas** approves specs, answers questions and gives the OK for anything that touches GitHub settings or the real
  Home Assistant.
- **Claude** (the main session, the controller) writes specs and plans, approves plans once `full-reviewer` rates them
  Ready, runs the build with subagents, tests, merges and releases.
- There is no PO or team-lead session.

## 2. Flow per feature

1. **Issue** in the `v1` milestone.
2. **Branch** `<type>/<topic>` off `main` (`feat`, `fix`, `docs`, `chore` …).
3. **Brainstorm** with Thomas for larger features (`superpowers:brainstorming`).
4. **Spec** in `docs/superpowers/specs/`. It says up front whether the change needs an update on the real Home
   Assistant. `full-reviewer` until Ready; then **Thomas approves**.
5. **Plan** in `docs/superpowers/plans/` (`superpowers:writing-plans`). Each task has a `Model:` tag and a
   `Review: yes|no` line. `full-reviewer` until Ready; then **Claude approves**.
6. **Build** with `superpowers:subagent-driven-development`: `implementer` per task (test-first), `task-reviewer` on
   the tasks marked `Review: yes`.
7. **Branch review:** `full-reviewer` on the whole branch until Ready.
8. **Test:** the gates, the fast loop, and for UI changes the Chrome check with screenshots in the PR
   ([`testing.md`](testing.md)).
9. **PR:** title per [`releasing.md`](releasing.md#pr-titles), `Closes #n`, links to the spec and plan, the rulings and
   the decisions Claude made alone.
10. **Merge:** Claude squash-merges once CI is green and the branch review is Ready.

Before every release, the full loop runs as well ([`releasing.md`](releasing.md)).

### `Review: yes` or `no`

`yes` by default for anything with logic: the data model, the scheduler and streaks, the session engine and rotation,
the add-on↔integration contract, MCP tools, the cards' timer. `no` for scaffolding, config and docs.

### Review rounds

- After fixes the same reviewer re-reviews, up to 5 rounds. Then Claude rules.
- Every ruling goes in the PR description, because the SDD workspace (`.superpowers/`, git-ignored) is thrown away. A
  ruling that sets a lasting rule also gets an entry in `decisions.md`.
- Reviewers are read-only and do no mutation testing. A doubt about a test is a finding. Fixes go to an implementer
  (D20).

### Trivial changes

A typo or a one-line doc fix with no behaviour change goes straight to a branch and a PR, without spec or plan.

## 3. Agents

The agents live in `.claude/agents/`.

| Agent | Model / effort | Use |
| --- | --- | --- |
| `implementer` | Opus / medium | One plan task, test-first; commits, never pushes or merges |
| `task-reviewer` | Opus / medium | Review of one task marked `Review: yes` |
| `full-reviewer` | Opus / high | Specs, plans, whole branches |

- The plan's `Model:` tag picks the implementer's model in the dispatch.
- The dispatch gives the co-author trailer line for the commits.
- Subagents never dispatch other subagents.
- Where `superpowers:subagent-driven-development` differs from this doc, this doc wins: `implementer` replaces SDD's
  general-purpose implementer, and `task-reviewer` replaces its spec and quality reviewers.

## 4. Conventions

- **Commits:** Conventional Commit messages, with the co-author trailer. Subagents commit with `git commit -F <file>`,
  the message written to a unique file in the SDD workspace.
- **Git guards:** run `scripts/setup` once per clone; it installs the hooks. They refuse commits on `main` and pushes to
  `main`. `.claude/settings.json` denies pushes to `main` and `--no-verify`. Branch protection on `main` requires CI.
- **Pushing:** Claude pushes feature branches. Nobody pushes to `main` or force-pushes.
- **GitHub settings** (branch protection, secrets, interaction limits, package visibility) change only with Thomas's OK.
- **Questions to Thomas:** plain terminal text, one at a time.
- **The real Home Assistant:** this project makes no changes there. Dashboards and house automations belong to the
  house assistant (ha-claude-a8). A change the house needs is agreed with that session; a release reaches the house
  through a `fitness` issue ([`releasing.md`](releasing.md#after-a-release)).
- **Backlog:** GitHub issues. Anything found that won't be fixed now becomes an issue.

## 5. Docs

- **One fact in one place.** Elsewhere, point to it.
- **General docs** explain why, conventions and structure. The code is the source for specifics.
- **Specs and plans are snapshots.** They aren't edited after merge. A later change gets a new spec and a decision-log
  entry.
- **Same PR:** docs change in the same PR as the code they describe.
- **Plain English:** short sentences, one fact per sentence.
- **Learnings:** a fact we learn goes where a reader would look for it: the doc that owns the topic, a Home Assistant
  fact in [`ha-notes.md`](ha-notes.md), anything else small in [`notes.md`](notes.md). When a topic in `notes.md`
  passes about three entries, move it to its own doc and add it to the [map](README.md).
- **Markdown:** the `ruff-format` hook formats Python code blocks in Markdown (outside `docs/superpowers/`). Put a
  fragment in a `text` or `bash` block.
- **Links:** `uv run python scripts/check_links.py` checks every relative link and `@` import; CI runs it.
- **Decision log:** a PR that makes a lasting decision adds an entry to `decisions.md`, numbered next. Entries aren't
  edited, except to set the status to `superseded by D<n>`, or `active; <part> superseded by D<n>`. The format:

  ```markdown
  ### D<n>: <title>
  - **Date:** YYYY-MM-DD · **Status:** active | superseded by D<m> | active; <part> superseded by D<m>
  - **Decision:** one or two sentences.
  - **Why:** one or two sentences.
  - **Source:** link to the spec section, or who decided and when.
  ```
