# Notes

Small learned facts that fit no other doc, and the dates to renew, newest last. When a topic passes about three
entries, move it to its own doc. Home Assistant facts live in [`ha-notes.md`](ha-notes.md).

## Dates to renew

| What | Expires | How to renew |
| --- | --- | --- |
| Interaction limit (collaborators only) | set 2026-10-23, **expires 2027-04-23** — renew before then | `gh api -X PUT repos/thomas3650/Ha-Fitness/interaction-limits -f limit=collaborators_only -f expiry=six_months`; check with `gh api repos/thomas3650/Ha-Fitness/interaction-limits` |
| `RELEASE_PLEASE_TOKEN` | 2027-10-23 (created 2026-10-23) | Thomas, see [`releasing.md`](releasing.md#the-release-please-token) |

Update the row when you renew.

## 2026-10-23: Commit email

Commits use Thomas's GitHub no-reply email (D23). It is set in this repo's git config, which a fresh clone doesn't
have. Set it once per clone:

```bash
git config user.email 24604147+thomas3650@users.noreply.github.com
```

## 2026-10-23: TypeScript is held at 6.0.x

`typescript-eslint` 8.x supports TypeScript below 6.1, so `cards/package.json` pins TypeScript 6.0.x. Dependabot
ignores TypeScript's minor and major updates. Lift the hold when `typescript-eslint` supports the newer version.

## 2026-10-23: Branch protection requires `addon-build`

The add-on image build runs per architecture as `addon-build (amd64)` and `addon-build (aarch64)`. The required check is
the gate job `addon-build`, which passes only when both do. Requiring the per-arch names breaks when the matrix
changes.
