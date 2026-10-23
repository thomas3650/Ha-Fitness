# Releasing

release-please releases the add-on and the integration (with its cards) independently (D8). A merged PR never releases
by itself: it updates a **release PR**, and merging that release PR makes the release. The config is
`release-please-config.json`; the current versions are in `.release-please-manifest.json`.

## Versions

- Strict semver (D9). The first release of each part is `0.1.0` (D17).
- While the major is 0, a breaking change bumps the **minor** (`bump-minor-pre-major`, D17). 1.0.0 is a deliberate
  step (spec §10, step 8).
- release-please owns the version fields. Don't edit them by hand.

## The two components

| | Add-on | Integration + cards |
| --- | --- | --- |
| Component | `ha-fitness-addon` | `ha-fitness` |
| Released by changes in | `addon/` | everything else (`exclude-paths: addon`) |
| Version in | `addon/config.yaml`, `addon/server/src/ha_fitness_server/__init__.py` | `custom_components/ha_fitness/manifest.json` |
| Changelog | `addon/CHANGELOG.md` | `CHANGELOG.md` |
| Tag | `ha-fitness-addon-vX.Y.Z` | `vX.Y.Z` (what HACS reads) |
| GitHub release | a draft that stays a draft (D16) | a draft, published once the zip is attached (D17) |
| What users get | the image `ghcr.io/thomas3650/ha-fitness-addon:X.Y.Z`; HA offers the update | the HACS zip `ha_fitness.zip`; HACS offers the update |

"Everything else" means a `fix:` that touches only `scripts/` or `.github/` releases the integration. Give such a PR a
non-releasing type.

## PR titles

PRs are squash-merged, so the PR title becomes the commit that release-please reads. The `pr-title` check allows these
types:

| Type | Release |
| --- | --- |
| `fix` | patch |
| `feat` | minor |
| `feat!`, `fix!` (breaking) | minor while the major is 0, major from 1.0.0 |
| `docs`, `test`, `chore`, `refactor`, `ci` | none |

- A user-visible change is a `feat` or a `fix`. There is no `perf`.
- A PR that touches both `addon/` and the rest releases both parts.
- release-please writes both changelogs from the commits. Don't write changelog entries by hand.
- Dependabot's PRs are titled `chore(deps): …` and release nothing. For a bump users should get, retitle it
  `fix(deps): …` before the merge.

## The workflows

- **`release-please.yml`** (every push to `main`):
  - The `release-please` job opens or updates one release PR per component. When a release PR is merged, it tags the
    merge commit and creates that component's draft release.
  - The `integration-zip` job runs only when the integration was released. It checks that the tag matches
    `manifest.json`, builds the cards, zips the contents of `custom_components/ha_fitness/` as `ha_fitness.zip`,
    checks that the zip root holds `manifest.json` and `frontend/ha-fitness-cards.js`, uploads it, and publishes the
    release as Latest.
- **`addon-image.yml`** (a push to `main` that changes `addon/config.yaml`): when the `version` differs from the parent
  commit, it builds the image for aarch64 and amd64 and pushes `X.Y.Z` and `latest` with the multi-arch manifest to
  GHCR. Only the add-on's release PR changes that version.
- **`ci.yml`** runs on every PR, the release PRs included (they need the token below).

## Cutting a release

1. Merge feature PRs as usual ([`way-of-working.md`](way-of-working.md) §2). release-please keeps the release PRs up
   to date.
2. Before merging a release PR, run the **full loop** on `main` ([`testing.md`](testing.md#full-loop)). This is
   mandatory for every release: a 0.x release reaches the house without a human check (D19).
3. Merge the release PR once its CI is green. When both components have a release PR, merge one, then expect the
   other to conflict: both bump `.release-please-manifest.json`, and release-please doesn't refresh an open release PR
   on the next run. Close the conflicting one; release-please opens a fresh one from `main` on the next push.
4. Check the result: `gh release list` shows `vX.Y.Z` as Latest (not a draft), and the add-on's release as a draft;
   for the add-on, the `addon-image` run is green.
5. Open the house issue ([After a release](#after-a-release)).

## After a release

Claude opens an issue in `thomas3650/house` with the label `fitness` (D10):

- the part: add-on, integration, or both;
- the version;
- **"major"** when the major changes (including 0.x → 1.0.0), and **"breaking"** for a 0.x minor bump that came from
  `!`;
- what changed (from the changelog);
- the checks to run after installing.

The house assistant installs a release with the same major as the installed one without asking; a new major waits
for Thomas's yes (D19). It decides from HA's update entities, not from the issue text.

The issue holds nothing private: the repo is public, and the issue links to it.

## GHCR visibility

Only the multi-arch package `ha-fitness-addon` must be public: that is what Home Assistant pulls. The per-arch
packages (`aarch64-…`, `amd64-…`) can stay private. Check with an anonymous pull: `docker logout ghcr.io`, then
`docker pull --platform linux/arm64 ghcr.io/thomas3650/ha-fitness-addon:X.Y.Z`. Changing the visibility needs
Thomas's OK.

## The release-please token

`RELEASE_PLEASE_TOKEN` is a fine-grained token for `thomas3650/Ha-Fitness` only, with Contents, Pull requests and
Issues: read and write (D18). release-please needs it so that its release PRs trigger CI. Its expiry date is in
[`notes.md`](notes.md).

- **Renewing (Thomas):** create a new fine-grained token with the same repository and permissions, then run
  `gh secret set RELEASE_PLEASE_TOKEN -R thomas3650/Ha-Fitness` and paste it. Update the date in `notes.md`.
- **If it expires,** the `release-please` job fails with bad credentials, and no release PR or release moves until
  Thomas renews it. The workflow doesn't fall back: an expired token is still set.
- **If the secret is deleted,** the workflow falls back to `github.token`. Release PRs still open, but CI doesn't run
  on them by itself: push an empty commit to the release PR's branch to start it.

## When a release fails

- **`integration-zip` fails:** the integration's release stays a draft. That is safe: HACS doesn't see drafts, and
  release-please already counts the version as released. Either re-run the failed job
  (`gh run rerun <run-id> --failed`), or do it by hand from a checkout of the tag (not the working tree):

  ```bash
  npm ci --prefix cards && npm run build --prefix cards
  (cd custom_components/ha_fitness && zip -r ../../ha_fitness.zip . -x '*__pycache__*')
  gh release upload vX.Y.Z ha_fitness.zip --clobber
  gh release edit vX.Y.Z --draft=false --latest
  ```

- **`addon-image` fails:** re-run the failed jobs (`gh run rerun <run-id> --failed`). A new push doesn't start it again,
  because the version no longer changes. Until the image is there, HA can't install the update.
