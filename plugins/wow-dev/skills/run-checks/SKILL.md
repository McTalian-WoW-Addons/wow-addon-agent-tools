---
name: run-checks
description: Run the repo's full local check sequence (tests, i18n, toc, untracked-file guard, trunk) with capability detection, in canonical order, and record the result the commit hook reads. Use before any commit or PR, after any Lua/locale/toc change, or when asked whether the tree is green. Trigger on /wow-dev:run-checks [--fmt|--only NAMES], or "run the checks", "is it green", "run tests and lint".
---

# /wow-dev:run-checks — run the repo's check sequence and record the result

## Command

Default run, records result for the commit hook:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json
```

Format first, then run everything:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json --fmt
```

Run one named check only (does not record):

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json --only test
```

Run every check even after a failure:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/checks.py" --json --keep-going
```

## Read the result

`ok:false` is a stop. Print the failing check's `tail` and fix that check before doing
anything else. Never re-run with `--only` on just the failing check to make the overall
run look green — a `--only` run does not record and does not satisfy the commit hook.
`--fmt` mutates files; after it finishes, run:

```bash
git diff --stat
```

and review what changed before staging.

## Narrowing

When `has.tests` is true, narrow to one file or one description instead of the full
suite while iterating:

```bash
make test-file FILE=<spec>
```

```bash
make test-pattern PATTERN="<text>"
```

## Do not

- Never run `busted` or `luacov` directly; always go through `checks.py` or the `make`
  targets above.
- Never pass `--no-record` before committing — the commit hook reads the recorded
  result.
- Never hand-list the check sequence in prose; `repo_profile.py --text` shows it:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" --text
```
