# git-workflow — reference

Rationale and provenance. Not loaded with the skill.

## Why this matters

Commit messages and PR titles are not internal bookkeeping — release notes generated
from them appear on GitHub, CurseForge, WoWInterface, and Wago. A dev-only change typed
`fix:` invents a bug players never had and forces an unnecessary patch release; a
genuinely player-visible change typed `chore:` vanishes from the notes and may ship with
no release at all. That's the reasoning behind the packaged-dir test in `SKILL.md`
§Commit type: did this change a file inside the packaged `<AddonName>/` directory?
Nothing outside it reaches the client.

Adapted from `RPGLootFeed/docs/pr-title-rules.md`, the fullest write-up of these rules.

## Where the type→release mapping comes from

The shared config is `wow-build-tools/.releaserc.json`. The reusable `ci.yml` workflow
unconditionally overwrites any repo-local copy with it before running semantic-release:

```yaml
cp .wbt/.releaserc.json .releaserc.json    # .wbt = wow-build-tools checked out at wbt-ref
npx --prefix .wbt semantic-release
```

Two consequences:

- `BeaconUnitFrames/.releaserc.json` and `DeviceLayoutPreset/.releaserc.json` are dead
  config. They declare a `build` + `scope: toc` rule that never takes effect, because the
  shared file replaces them at release time. Don't edit them expecting release behavior
  to change, and don't read them as evidence of how releases work.
- The release config is versioned with `wbt-ref`. Bumping `v1-beta` → `v1` also switched
  the semantic-release preset from `conventionalcommits` to `angular`.

## Moving vs frozen tags

`v1` is a moving major tag that the `move-major-tag` job in
`wow-build-tools/.github/workflows/wbt-release-published.yml` force-updates to each
published release. Pin to `v1`, not to `v1-beta` (frozen at `1.0.0-beta.44`) and not to a
specific patch.

The `wbt_setup` target that both `make i18n_check`/`make i18n_fmt` and this plugin's
scripts depend on shallow-clones `wow-build-tools` to `../wow-build-tools` at ref
`$WBT_REF` (default `v1`) only if `scripts/i18n/` isn't already there. In a workspace
where `~/code/wow-build-tools` already exists at some other checked-out branch, that
clone no-ops — locally the i18n targets run against the working copy, not `$WBT_REF`.
`WBT_REF` only takes effect on a fresh clone or in CI. If i18n behaves differently
locally than in CI, that gap is why.

## Squash vs rebase publish different things

- **Squash merge** collapses the branch into one commit on `main`, titled with the PR
  title plus a `(#N)` suffix. Branch commit messages are discarded and never reach the
  changelog — they can be scrappy. Only the PR title must be well-formed.
- **Rebase merge** replays every commit onto `main` verbatim, no `(#N)` suffix, and each
  commit is evaluated for the release. The PR title is recorded nowhere.

So on a branch destined for rebase merge, every commit must independently follow the
format, every type must be honest about player impact, and `fixup!`/`wip` commits must
be autosquashed away or they get evaluated as release commits. Assume a multi-commit
feature branch will be rebase merged unless told otherwise.

## PR labels gate which merge button is legal

`release-checks.yml` (currently only wired up in RPGLootFeed) re-runs on every PR open,
push, reopen, and title edit, then applies labels:

- `squash-valid` — the PR title parses; squash merge is allowed.
- `rebase-valid` — every commit in the range parses; rebase merge is allowed.
- `release:major` / `minor` / `patch` / `no-release` — the resulting bump.

Only `rebase-valid` makes a rebase merge safe. The check fails only when neither path is
valid, so a PR with one malformed commit still passes on its title alone and is thereby
squash-only. If both paths are valid but disagree on release type — title says `chore:`,
but a commit in the range is a `feat:` — the workflow applies no labels at all. An
unlabelled passing PR means that mismatch, not a skipped run; that's what
`pr.py labels`'s `mismatchSuspected` field surfaces.

## Same-branch bug fix reasoning

A bug introduced and fixed within the same unreleased branch never shipped to a player,
so there is nothing to announce. Typing it `fix:` would manufacture a release note for a
bug that never existed in a release. Fold the correction into the commit that introduced
the bug (squash), or type the standalone correction `chore:` if squashing isn't practical.
