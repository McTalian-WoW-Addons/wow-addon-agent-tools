---
name: onboard-repo
description: Bring a McTalian addon or tool repo onto the wow-dev plugin — write .claude/settings.json, generate a ≤2KB CLAUDE.md with the contract headings from the detected profile, scaffold docs/agent/conventions.md, add gitignore entries, and verify discovery. Trigger on /wow-dev:onboard-repo, or "enable the plugin here", "set up Claude tooling for this repo".
disable-model-invocation: true
---

# /wow-dev:onboard-repo — enable the plugin in a repo

## 1. Profile

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/repo_profile.py" --json
```

Use `kind`, `addonDir`, `has.*`, and `makeTargets` from the output for every later step.

## 2. Settings

```bash
mkdir -p .claude
cp "${CLAUDE_PLUGIN_ROOT}/skills/onboard-repo/templates/settings.json" .claude/settings.json
```

If `.claude/settings.json` already exists, merge the `extraKnownMarketplaces` and
`enabledPlugins` keys into it instead of overwriting the file.

## 3. CLAUDE.md

Fill `${CLAUDE_PLUGIN_ROOT}/skills/onboard-repo/templates/CLAUDE.md.tmpl` from the
profile and write the result to `CLAUDE.md` at repo root:

- `{{description}}` — the first paragraph of `README.md`.
- `## Commands` — only targets absent from the shared default set (`make help`,
  `/wow-dev:run-checks`); ≤8 lines.
- `## Conventions` — copy the bullets of an existing `CLAUDE.md` if one exists,
  otherwise write 3 seed bullets from the profile's `has.*`; keep the closing
  `Full list: docs/agent/conventions.md.` line.
- `## Docs` — one bullet per file under `docs/**.md` and `.github/docs/**.md` that
  already exists, `path — when to read`; ≤8 bullets.

If a `CLAUDE.md` already exists at repo root: move any rationale sentences out to
`docs/agent/decisions.md`, move its convention bullets to `docs/agent/conventions.md`
(§4), then overwrite `CLAUDE.md` with the template output above — never keep the old
structure alongside the new one.

## 4. Conventions

Fill `${CLAUDE_PLUGIN_ROOT}/skills/onboard-repo/templates/conventions.md.tmpl` — one
bullet under each of `Structure`, `WoW API`, `Strings`, `Testing`, `Packaging` — and
write it to `docs/agent/conventions.md`. Skip this step only when the profile has no
Lua source.

## 5. Gitignore

Append these two lines to `.gitignore` before any check runs and writes a record:

```
.claude/worktrees/
.claude/.last-checks.json
```

## 6. Verify

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/doclint.py" --root "${CLAUDE_PROJECT_DIR}"
wc -c CLAUDE.md
```

`doclint.py` must exit clean; `wc -c` must read ≤2048.

Install the plugin for this user — `.claude/settings.json` registers the marketplace
but does not install anything for anyone:

```bash
claude plugin install wow-dev@mctalian-wow-addons
```

A teammate cloning this repo runs the same install command once. Local development
against an unpublished clone uses
`claude plugin marketplace add <path-to-clone> --scope user` in place of the GitHub
marketplace add.

Then confirm discovery:

```bash
claude -p "List every skill name available. One per line." --output-format text
```

The output must contain `wow-dev:run-checks`.

## 7. Commit

```
chore: enable wow-dev plugin
```

Commit and open the change via `/wow-dev:git-workflow`.
