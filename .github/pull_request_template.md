## What and why

<!-- One or two sentences. For non-trivial work, link the spec and plan. -->

Closes #

## Checklist

- [ ] Gates pass (`CLAUDE.md` → *Commands*: lint, types, tests, build; Python coverage is reported, with no threshold)
- [ ] Title type per `docs/releasing.md`: `feat`, `fix`, `docs`, `test`, `chore`, `refactor` or `ci`; user-visible →
  `feat` or `fix`; only `scripts/` or `.github/` → a non-releasing type
- [ ] UI change → Chrome screenshot at 1368×912 attached, no console errors
- [ ] Docs updated (same PR as the code)
- [ ] Lasting decision → `docs/decisions.md` entry
- [ ] Nothing from the real HA: tokens, hostnames, IPs, entity IDs, data
- [ ] `full-reviewer` run on the branch
