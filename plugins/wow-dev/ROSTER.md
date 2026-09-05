# wow-dev roster

Skills cite this file by path; never inline it. `<AddonDir>` and `<SpecDir>` come from `repo_profile.py`.

## Researchers
- `wow-dev:wow-api-researcher` — given symbols/flavors, returns per-flavor presence, signature, deprecation, Blizzard usage pattern.
- `wow-dev:impl-researcher` — given one target file + contract, returns the closest existing file and the pattern to copy.

## Implementers
| Owner | Owns | Self-check | Boundary reviewer |
|---|---|---|---|
| `wow-dev:lua-feature-builder` | `<AddonDir>/**/*.lua`, `*.xml`, `*.toc` | `make toc_check`; `make test` | `wow-dev:lua-convention-reviewer` |
| `wow-dev:spec-author` | `<SpecDir>/**` | `make test-file FILE=<spec>` | `wow-dev:lua-convention-reviewer` |

One owner per file; ownership never overlaps.

## Reviewers
Spawn every reviewer whose trigger saw a diff, in one message. Name the ones skipped and why.
- `wow-dev:lua-convention-reviewer` — any `<AddonDir>/**/*.lua`, `<SpecDir>/**`, `*.xml`, `*.toc`.
- `wow-dev:localization-reviewer` — `has.i18n` and any `<AddonDir>/**/*.lua` or `<AddonDir>/locale/**`.
- `wow-dev:commit-type-reviewer` — every PR (commit range).
- `wow-dev:skill-prose-reviewer` — `CLAUDE.md`, `.claude/**`, `docs/agent/**`, plugin `skills/**`, `agents/**`, `ROSTER.md`.

## Verifiers
1. `wow-dev:claim-evidence-reviewer` — after checks pass.
