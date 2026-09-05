---
name: git-workflow
description: Branch, commit-type, PR-title and merge-strategy mechanics for McTalian addon repos — packaged-dir test decides which conventional types are allowed, squash vs rebase decides which messages must parse, release-checks labels decide the legal merge button. Use before committing, pushing, titling or merging any PR. Trigger on /wow-dev:git-workflow, or "commit this", "open a PR", "what type is this commit", "can I rebase-merge".
---

# /wow-dev:git-workflow — commit, PR, and merge mechanics for addon repos

## Branch

Never commit on `main` — the pre-commit hook blocks it.

```bash
git fetch origin && git switch -c <type>/<issue>-<slug> origin/main
```

## Commit type

Check whether this change touches the packaged addon directory:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" touches-packaged --staged
```

| Type | Release |
|---|---|
| `feat` | minor |
| `fix` | patch |
| `perf` | patch |
| `locale` | patch |
| `toc` | patch |
| `build` | none |
| `chore` | none |
| `ci` | none |
| `docs` | none |
| `refactor` | none |
| `style` | none |
| `test` | none |
| `revert` | none |

Rules:

- `packaged:false` → only `build chore ci docs refactor style test` are valid types.
- A bug introduced and fixed on the same unreleased branch is not `fix:` — squash it
  into the commit that introduced it, or type the fix `chore:`.
- Repairing a dev tool (`.scripts/`, `_spec/`, `.github/`, `docs/`) is `build:`, never `fix:`.
- `toc:` is only for `## Interface:` version bumps.

## Message format

`type: description` — one line, lowercase first letter, ≤72 chars.

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" lint-title "<title>"
```

A commit authored by Claude ends with this trailer:

```
Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
```

## Squash vs rebase

Decide before the first commit — it decides which messages must parse.

- Default to rebase merge for a multi-commit branch. Every commit in the range must pass:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" lint-commits origin/main..HEAD
```

- On squash-merge branches only the PR title must pass `lint-title`; branch commits can
  be scrappy.
- Before pushing a rebase branch, autosquash any `fixup!`/`wip` commits:

```bash
git rebase -i --autosquash origin/main
```

## Open PR

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" create --title "<title>" --body-file <file>
```

- Body follows `.github/pull_request_template.md` headings.
- `Closes #N` goes in the body only, never the title.
- Write bodies with `--body-file`; never inline `--body`.
- Never `gh pr comment --edit-last`.

## Before merging

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" labels <pr-number>
```

- `rebaseValid:false` → squash merge only.
- `mismatchSuspected:true` → title and commits disagree on release type; fix before merge.

## Pre-commit gates

The commit hook (`guard_commit.py`) blocks `git commit` on any of:

- **R1** current branch is `main` → create a branch first (`## Branch` above).
- **R2** `--no-verify`/`-n` is present → not permitted.
- **R3** untracked files sit under the packaged dir → `git add` or gitignore them first.
- **R4** staged packaged-dir content has no fresh passing check run → run `/wow-dev:run-checks`
  then retry.
- **R5** `-m` type is a publishing type with no packaged file staged → use a dev type instead.

Rationale: REFERENCE.md
