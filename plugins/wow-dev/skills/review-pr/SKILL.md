---
name: review-pr
description: Review one open PR in an addon repo without changing it — check out the head in a worktree, run the canonical checks and commit lint, fan out the reviewer roster by changed paths, verify claims in the PR body, and post one findings report comment. Trigger on /wow-dev:review-pr <pr-number>, or "review PR N", "self-review before merge".
argument-hint: <pr-number>
disable-model-invocation: true
---

# /wow-dev:review-pr — review one open PR without changing it

## 1. Fetch

```bash
gh pr view <pr-number> --json number,title,body,headRefName,baseRefName,files
```

Use `EnterWorktree` to get an isolated checkout, then run inside it:

```bash
gh pr checkout <pr-number>
```

Record the worktree's absolute path as `TREE`. Every command and every reviewer prompt
below runs against `TREE`.

## 2. Mechanical

Run in `TREE`:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json --keep-going --no-record
```

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" lint-commits origin/<base>..HEAD --json
```

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" lint-title "<title>"
```

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/pr.py" labels <pr-number>
```

`<base>` is `baseRefName` from step 1; `<title>` is `title` from step 1.

## 3. Fan-out

Take the changed-file list from step 1. In one message, spawn every reviewer listed in
`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Reviewers whose trigger matches a changed file. Give
each reviewer `TREE`, the changed-file list, and the `REPORT.md` finding-line format
(`${CLAUDE_PLUGIN_ROOT}/skills/review-pr/REPORT.md`). List any roster reviewer whose
trigger did not match, and why, under `### Skipped reviewers` in the report.

## 4. Verify

Spawn `wow-dev:claim-evidence-reviewer` (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Verifiers)
against `TREE`, the PR body, and the commit messages in the range from step 2. It settles
each checkable claim in the body against a read-only probe.

## 5. Report

Fill `${CLAUDE_PLUGIN_ROOT}/skills/review-pr/REPORT.md` from steps 2 through 4. Write the
filled report to a temp file, then post it:

```bash
gh pr comment <pr-number> --body-file <tmpfile>
```

Never `gh pr comment --edit-last`. Never pass the report inline with `--body`.

## 6. Teardown

Use `ExitWorktree` to release `TREE`, then report the PR URL, its labels, and the skipped
reviewers. Never fix, commit, or push anything in `TREE` — this skill only posts findings.
