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

## 2026-10-23: The exercise library's size (spike, step 2)

Measured at `hasaneyldrm/exercises-dataset` commit `7455efae41b330c265e7cd4b78dfa848e7ce5ebd`. The dataset has 1,324
exercises. The equipment filter of spec §3.6 (body weight, band, resistance band, dumbbell, kettlebell) keeps **721**:
**67.5 MB of GIFs** (median 89 kB, largest 233 kB) and **4.6 MB of thumbnails**, 1,442 files. All GIFs together are
129 MB. `data/exercises.json` is 17 MB with ten languages; the 721 records with English steps only are about 0.5 MB.

Since D64 the library holds the whole dataset: **1,324** exercises with 28 equipment values, about 1 MB with English
steps only. The media is **2,648 files**, about 137 MB (the GIFs' 129 MB and the thumbnails).

From raw.githubusercontent.com to the Mac on the home network: **39 s** with 8 downloads in parallel. One at a time
takes about 0.25 s per file, so about 6 minutes for the set. The HA host's time is not measured.

## 2026-10-24: Alembic batch rebuilds fire foreign-key actions

The add-on turns on `PRAGMA foreign_keys=ON` for every connection (`db.py`). An Alembic batch operation rebuilds a
table and drops the old one. With foreign keys on, that drop fires the actions of the tables that reference it:
`sessions` deletes every `session_participants` row on cascade, `training_days` sets `sessions.training_day_id` to
null, and `programs` sets `training_days.program_id` to null. Drop a column with a native
`ALTER TABLE … DROP COLUMN` instead (SQLite 3.35 or later; the add-on image has 3.53).

## 2026-10-26: The website's node image is bumped by hand

The add-on's `Dockerfile` builds the website in a `node:24-alpine` stage, pinned to the multi-arch index digest.
Dependabot doesn't watch the Dockerfile, so bump the pin by hand: take the new digest from
`docker buildx imagetools inspect node:24-alpine`. The website (`addon/web/package.json`) holds TypeScript at 6.0.x
too, for the same reason as the cards.
