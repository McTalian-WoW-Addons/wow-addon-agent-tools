# Per-repo context contract

Consumers: **S** = plugin scripts, **M** = model via skills/agents.

| File | Required | Reader | Content |
|---|---|---|---|
| `Makefile` | yes (addon/lib/go-tool) | S | Target names are the capability signal: `test`, `all_checks`, `i18n_check`, `toc_check`, `check_untracked_files`, `build`, `dev`. Only targets that exist are run. |
| `<Addon>/<Addon>.toc` | addon kind | S | `## Interface:` → flavors. Dir name → `addonDir`. |
| `.busted` | if tests | S | `has.tests` = `.busted` exists **or** (a top-level `*_spec/` directory exists and the Makefile has a `test` target). The first `*_spec/` directory found (sorted) also supplies `specDir` when no addon-specific spec dir applies. |
| `<Addon>/locale/enUS.lua` | if i18n | S | presence → `has.i18n`; `--#region` blocks → `i18n.py` |
| `./trunk` or `.trunk/trunk.yaml` | if lint | S | presence → `has.trunk` |
| `.github/workflows/*.yml` | if CI | S | `uses: McTalian-WoW-Addons/wow-build-tools/.github/workflows/<name>.yml` → `ci.{prChecks,releaseChecks,ci,tocUpdater}` |
| `go.mod` | go-tool | S | kind = `go-tool`; `guardPaths` default `cmd/ internal/ go.mod go.sum` |
| `.claude/repo.json` | optional | S | Override keys only: `kind`, `addonDir`, `checks` (ordered shell commands replacing detection), `guardPaths` (globs that require checks before commit), `localeVersionStyle` (`"v"` or `""`), `skipChecks` (names to drop, e.g. `all_checks`). Unknown keys are an error. |
| `.claude/settings.json` | yes | harness | `extraKnownMarketplaces` + `enabledPlugins` block (verbatim from `onboard-repo/templates/settings.json`). |
| `CLAUDE.md` | yes | M | ≤2048 B. Required H2s in order: `## Commands` (only commands that differ from `make help`/plugin defaults, ≤8 lines), `## Conventions` (≤8 imperative one-liners; last line `Full list: docs/agent/conventions.md`), `## Docs` (bullet list `path — when to read`, ≤8 bullets). Optional first line: one-sentence description. No other H2s. |
| `docs/agent/conventions.md` | yes when repo has Lua source | M | ≤4096 B. H1 + flat bullet list of imperative rules, each ≤160 chars, grouped under H2s `Structure`, `WoW API`, `Strings`, `Testing`, `Packaging`. Read by `lua-feature-builder`, `spec-author`, `lua-convention-reviewer`. |
| `docs/agent/decisions.md` | optional | humans | Free-form rationale. Never cited by a skill or agent. |

`repo_profile.py` output schema (all readers depend on these keys):
```json
{"root":"/abs","kind":"addon|lib|go-tool|unknown","addonDir":"RPGLootFeed|null",
 "toc":"RPGLootFeed/RPGLootFeed.toc|null","specDir":"RPGLootFeed_spec|null","localeDir":"RPGLootFeed/locale|null",
 "interfaces":[11509,20506,50504,120100],
 "flavors":[{"interface":11509,"name":"classic_era","ref":"classic_era","product":"wow_classic_era"},
            {"interface":20506,"name":"tbc_anniversary","ref":"origin/classic_anniversary","product":"wow_anniversary"},
            {"interface":50504,"name":"mop_classic","ref":"classic","product":"wow_classic"},
            {"interface":120100,"name":"retail","ref":"live","product":"wow"}],
 "makeTargets":["all_checks","test","toc_check","..."],
 "has":{"tests":true,"i18n":true,"trunk":true,"tocCheck":true,"untrackedCheck":true,"allChecks":true,"wbtBinary":true},
 "ci":{"prChecks":true,"releaseChecks":true,"ci":true,"tocUpdater":true},
 "checks":[{"name":"test","cmd":"make test"},{"name":"i18n","cmd":"make all_checks"},{"name":"toc","cmd":"make toc_check"},
           {"name":"untracked","cmd":"make check_untracked_files"},{"name":"trunk","cmd":"./trunk check --no-fix"}],
 "guardPaths":["RPGLootFeed/"],"localeVersionStyle":"","overrides":{}}
```
Flavor table (owned by `_common.py`, single source): interface `1xxxx`→`classic_era`/`classic_era`/`wow_classic_era`; `2xxxx`→`tbc_anniversary`/`origin/classic_anniversary`/`wow_anniversary`; `5xxxx`→`mop_classic`/`classic`/`wow_classic`; `11xxxx|12xxxx`→`retail`/`live`/`wow`; other bands → `name:"unknown-<n>"`, `ref:null`. Check order when detected: `test` → `all_checks` (else `i18n_check`) → `toc_check` → `check_untracked_files` → `./trunk check --no-fix`; go-tool: `make test` → `./trunk check --no-fix`.
