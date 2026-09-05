---
name: work-item
description: Drive one GitHub issue end to end in an addon repo — intake, research fan-out, contract-first plan with one owner per file, branch, implement with boundary review, run-checks join gate, claim verification, reviewer fan-out, typed commits and PR with validated title and labels. Trigger on /wow-dev:work-item <issue-number> [--worktree] [--manual-check], or "work issue N through the pipeline".
argument-hint: <issue-number> [--worktree] [--manual-check]
disable-model-invocation: true
---

# /wow-dev:work-item — drive one GitHub issue from intake to PR

## Flags

`/wow-dev:work-item <issue-number> [--worktree] [--manual-check]`

- `--worktree`: isolate implementation in a new git worktree (Stage 4).
- `--manual-check`: force the Stage 9 hard stop even when Stage 1 asked no questions.

## 1. Intake

```bash
gh issue view <issue-number> --json title,body,labels,comments
```

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" --json
```

Batch every blocking question into one `AskUserQuestion` call. Record `ASKED=true` if any
question was asked, else `ASKED=false`. Stage 9 reads `ASKED`.

## 2. Research

In one message, dispatch:

- `wow-dev:wow-api-researcher` (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Researchers) for every
  WoW API symbol named in the issue.
- `wow-dev:impl-researcher` (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Researchers), one instance
  per file the plan will create or change.

## 3. Plan

Build the contract table, columns `File | Owner | Symbols/signatures | Spec file`. Owner
comes from `${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Implementers, one row per file, one owner per
file. Reuse the contract table's text verbatim in every downstream agent prompt that names
one of its files.

**Hard stop.** Show the contract table. Wait for plan approval before Stage 4.

## 4. Branch

```bash
git fetch origin && git switch -c <type>/<issue-number>-<slug> origin/main
```

Type and slug come from Stage 3's plan; see `/wow-dev:git-workflow` §Branch.

- `--worktree`: call `EnterWorktree`, then set `TREE` to the absolute path it returns.
- No `--worktree`: set `TREE=${CLAUDE_PROJECT_DIR}`.

Every command and every agent prompt from here on runs against `TREE`.

## 5. Implement

In one message, dispatch each contract-table owner (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md`
§Implementers) with `TREE` and its contract table row.

Immediately after an owner finishes, run its boundary reviewer (same roster row) against:

```bash
git -C <TREE> diff -- <owner's files>
```

Loop findings back to the owner once, then continue.

## 6. Join gate

Run in `TREE`:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json
```

`ok:false` stops the pipeline. Do not retry with `--only`.

## 7. Verify

Dispatch `wow-dev:claim-evidence-reviewer` (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Verifiers)
with the contract table's claims and `TREE`.

## 8. Review

In one message, spawn every `${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Reviewers entry whose
trigger saw a diff in `TREE`. Name the ones skipped and why. A `⛔` finding blocks Stage 9
until fixed and re-reviewed.

## 9. Land

Run in `TREE`:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" touches-packaged --staged
```

Commit using the type from the previous command's output.

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" lint-commits origin/main..HEAD
```

If `ASKED=true` or `--manual-check`: **Hard stop.** Show the commit log, the diff stat,
and the PR body below. Wait for approval before pushing.

```bash
git log --oneline origin/main..HEAD
```

```bash
git diff --stat
```

```bash
git push -u origin HEAD
```

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" create --title "<title>" --body-file <file>
```

The PR body includes `Closes #N`.

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" labels <pr-number>
```

## 10. Stop

- `--worktree`: call `ExitWorktree` on `TREE`.
- Report the PR URL, its labels, and every reviewer skipped in Stage 8.
