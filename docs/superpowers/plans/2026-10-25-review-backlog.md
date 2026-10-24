# Review backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Close the small hardening findings of #39, #19, #22, #27 and part of #14, and remove house details from the
repo's files.

**Architecture:** Local changes in the add-on (training days, programs, push, ingress), one cards config
file, CI coverage floors, and a docs edit.

**Tech Stack:** Python 3.14 (FastAPI, pytest), TypeScript ESLint config.

**Spec:** [`docs/superpowers/specs/2026-10-25-review-backlog-design.md`](../specs/2026-10-25-review-backlog-design.md)

## Global Constraints

- Hard rule 5: tests through public interfaces (REST, MCP, ws, logs through `caplog` only for the log-level facts the
  issues name).
- Hard rule 6: the separator from the add-on's language files.
- Hard rule 7: nothing under `config/` or `local/`; no hook bypass.
- Branch `fix/review-backlog` in the worktree `../Ha-Fitness-H`. Commit with `git commit -F <file>` and the trailer.

## Review Focus

1. A stats failure during a session finish: the session still finishes (Task 1 test).
2. A missing exercise: list, get and start answer 200; an update is 422 (Task 1 test).
3. A slow push client: the others keep getting messages (Task 2 test).
4. A house detail left in some doc (Task 3's grep).
5. Coverage floors that fail CI by accident: set below today's numbers (Task 3 step).

---

### Task 1: Stats failures and missing exercises (#39, #19)

Model: opus · Review: yes

**Files:** `addon/server/src/ha_fitness_server/training_days.py`, `programs.py` (`_out` only), `mcp_tools.py` (the
`get_program` text only); tests in `addon/server/tests/test_stats.py` (or `test_stats_push.py`), `test_programs.py`,
`test_session_start.py`.

- [ ] **Step 1:** Write the failing tests of spec §2.1 and §2.2, with the setups the spec names:
  `test_stats_failure_never_breaks_a_write` (skip and `/today` answer 200), `test_stats_failure_during_session_finish`,
  `test_missing_exercise_named_by_id` (list, get, start), `test_update_with_missing_exercise_is_422`.
- [ ] **Step 2:** Run them. Expected: all FAIL except the 422 test, which already passes (coverage).
- [ ] **Step 3:** Implement: wrap the `on_change` call (`_LOGGER.exception`, swallowed); in `_out`, name a missing
  exercise by its id with no equipment; update the `get_program` text.
- [ ] **Step 4:** Run the add-on gates. Expected: PASS.
- [ ] **Step 5:** Commit `fix(addon): stats failures and missing exercises never break a request`.

### Task 2: Ingress leftovers and push queues (#22, #27)

Model: opus · Review: yes

**Files:** `addon/server/src/ha_fitness_server/ingress.py`, the add-on's i18n files (`i18n/`), `push.py`, `api/ws.py`
(closing a dropped subscriber); tests in `test_ingress.py`, `test_ws.py` (the `Hub` test), and
`test_settings_timezone.py`.

- [ ] **Step 1:** Write the tests of spec §2.3 and §2.4: the `list_separator` key read (a plain assertion: the weekdays
  joined with `texts["list_separator"]`; it accepts it can't tell the key from a hard-coded `", "`), the whole exercises text, `HEAD /`
  200; the INFO log for an unset TZ; the `Hub` drop test as the spec describes it.
- [ ] **Step 2:** Run them. Expected: FAIL for the separator, `HEAD /` and the queue drop; the exercises text and the
  TZ log pass at once (coverage).
- [ ] **Step 3:** Implement the mechanism of spec §2.4 (the per-subscriber `Event`, the copy of the subscribers, the
  third task, close code 1013, the WARNING log).
- [ ] **Step 4:** Run the add-on gates. Expected: PASS.
- [ ] **Step 5:** Commit `fix(addon): ingress leftovers and bounded push queues`.

### Task 3: Step 1 leftovers and the design spec (#14, hard rule 2)

Model: sonnet · Review: no

**Files:** `addon/server/tests/test_health.py` (or the test of `main()`), `cards/eslint.config.js`, `pyproject.toml`
and `addon/server/pyproject.toml` (`[tool.coverage.report] fail_under`), the files spec §2.6 names (the design spec,
`2026-10-24-training-today-design.md`, `2026-10-24-the-workout-design.md`, `2026-10-24-programs-through-chat-design.md`,
`docs/architecture.md`, `docs/notes.md`, the `websocket_api.py` docstring, `tests/test_session_services.py`, and any
other hit of the grep),
`docs/decisions.md` (D56).

- [ ] **Step 1:** Add `test_main_creates_data_dir` (`uvicorn.run` monkeypatched; passes at once, coverage).
- [ ] **Step 2:** `defineConfig` in the ESLint config; run `npm ci --prefix cards` first in this worktree, then
  `npm run lint --prefix cards` passes.
- [ ] **Step 3:** `fail_under = 95` (root) and `fail_under = 90` (add-on). Both pytest jobs still pass.
- [ ] **Step 4:** Remove the house details as spec §2.6 says. Run the grep of spec §2.6 with the list from the dispatch, over the
  whole repo (`-- .`, lock files excluded): expected no hits (or only justified ones, listed in the report). Add D56 in
  the log's format; D56, the commit and the report never quote the removed strings. Run the link check.
- [ ] **Step 5:** Run all gates of `CLAUDE.md`. Commit `chore: step 1 leftovers and no house details in the docs`.
