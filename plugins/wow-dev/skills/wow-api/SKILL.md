---
name: wow-api
description: Look up a WoW API function, event, enum or constant across every client flavor from the local wow-ui-source checkout — presence per flavor, signature block, deprecation hits and Blizzard usage sites — without switching branches. Use before calling or adapting any C_* API, registering an event, or guarding a flavor difference. Trigger on /wow-dev:wow-api <Symbol> [flavor], or "does X exist on Classic", "signature of C_Foo.Bar", "how does Blizzard use X".
argument-hint: <Symbol> [flavor]
---

# /wow-dev:wow-api — look up a WoW API symbol across flavors

## Commands

Presence, deprecation, and usage sites across the current repo's flavors:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/wow_api.py" find <Symbol> --repo-flavors --usages 5
```

Full signature block for one flavor:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/wow_api.py" show <Symbol> --flavor <name>
```

Matching events:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/wow_api.py" events <PATTERN>
```

Branch/ref freshness:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/wow_api.py" branches
```

## Flavor names

The only valid `--flavor`/`--flavors` values: `retail`, `mop_classic`, `classic_era`,
`tbc_anniversary`. PTR/beta refs go through `--ref` instead of a flavor name.

## When to delegate

A multi-symbol lookup, or a "how does Blizzard implement X" question, goes to
`wow-dev:wow-api-researcher` (`${CLAUDE_PLUGIN_ROOT}/ROSTER.md` §Researchers). Pass it the
`find` output rather than re-running the lookup inside the agent.

## Rules

- State which flavor or ref answered the question; never report a result without it.
- A symbol present on only some of the repo's flavors needs an existence guard or an
  `IsRetail()`/`IsClassic()` branch per the repo's `docs/agent/conventions.md`.
- Anything found under `Blizzard_Deprecated` is off-limits for new code.
- Assets and FileDataIDs are not covered here; use the repo's wago skill when present.
- If `branches` shows a local `live` branch behind `origin`, ask before running
  `git fetch` — this skill never fetches or checks out on its own.
