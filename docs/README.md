# Documentation map

The root [`README.md`](../README.md) is the public intro. Everything else lives here.

| Doc | Holds | Read it when |
| --- | --- | --- |
| [`../README.md`](../README.md) | What HA Fitness is, installing (add-on repository + HACS) | First look at the repo |
| [`../CLAUDE.md`](../CLAUDE.md) | What the repo is, layout, commands, hard rules | Starting any work here |
| [`way-of-working.md`](way-of-working.md) | The flow per feature, the agents and their models, conventions, how docs are kept | Doing non-trivial work |
| [`decisions.md`](decisions.md) | Lasting decisions (D1, D2 …): decision, why, source | Asking why something is the way it is |
| [`releasing.md`](releasing.md) | PR titles and bumps, the two components, the release workflows, the house issue, when a release fails | Merging a releasing PR or a release PR |
| [`architecture.md`](architecture.md) | Who owns what (add-on, integration, cards), the API contract and its version | Changing how the parts talk to each other |
| [`domain-language.md`](domain-language.md) | The words: program, station, round, training day, due/late/missed/skipped, streak … | Naming anything, or reading a spec |
| [`testing.md`](testing.md) | The fast loop, the full loop, the Chrome check, the MCP check | Testing a change beyond the gates |
| [`notes.md`](notes.md) | Small learned facts that fit no other doc, and dates to renew | Looking for a fact that isn't elsewhere |
| [`ha-notes.md`](ha-notes.md) | Learned Home Assistant facts: the Supervisor, the integration, the frontend, testing, macOS, bumping HA | Building or testing against Home Assistant |
| [`superpowers/specs/`](superpowers/specs/) | One design spec per feature; snapshots, not edited after merge | Why a feature is shaped this way |
| [`superpowers/plans/`](superpowers/plans/) | One implementation plan per feature; snapshots | How a feature was built |
| [`mockups/`](mockups/README.md) | The initial mockups (a reference only) and the updated screens | Building or changing a screen |

The design of v1 and the way of working are in the
[design spec](superpowers/specs/2026-10-23-ha-fitness-design.md).
