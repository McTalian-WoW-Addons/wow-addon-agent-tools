# wow-addon-agent-tools

Claude Code plugin marketplace for McTalian WoW addon repos: `wow-dev` — checks, commit typing, PR labels, WoW API lookup, i18n.

## Install (per consuming repo)

Add to the repo's `.claude/settings.json` (committed):

```json
{
  "extraKnownMarketplaces": {
    "mctalian-wow-addons": {
      "source": {
        "source": "github",
        "repo": "McTalian-WoW-Addons/wow-addon-agent-tools"
      }
    }
  },
  "enabledPlugins": {
    "wow-dev@mctalian-wow-addons": true
  }
}
```

Or from the CLI:

```bash
claude plugin marketplace add McTalian-WoW-Addons/wow-addon-agent-tools
```

## Local development

Register this working copy as the same marketplace name, so it resolves locally instead of GitHub:

```bash
claude plugin marketplace add ~/code/wow-addon-agent-tools --scope user
```

## Layout

```
.claude-plugin/marketplace.json            marketplace "mctalian-wow-addons"
plugins/wow-dev/.claude-plugin/plugin.json plugin manifest
plugins/wow-dev/hooks/hooks.json           PreToolUse Bash hook -> guard_commit.py
plugins/wow-dev/scripts/                   Python scripts (contract: docs/contract.md)
plugins/wow-dev/skills/                    SKILL.md per skill
plugins/wow-dev/agents/                    agent .md per role
docs/contract.md                           per-repo context contract
docs/decisions.md                          rationale for each decision in this repo
```

See `docs/contract.md` for what a consuming repo must provide (Makefile targets, `.toc`, locale layout, optional `.claude/repo.json` overrides) and what `repo_profile.py` emits.

## Commands

```bash
make help       # list targets
make test       # run plugin script unit tests
make lint       # doclint.py over plugins/wow-dev
make validate   # claude plugin validate --strict, both manifests
make probe REPO=<path>   # print repo_profile.py output for REPO
```

## Release

1. Bump `version` in `plugins/wow-dev/.claude-plugin/plugin.json`.
2. `claude plugin tag plugins/wow-dev`
3. `git push --tags`

## License

MIT, see `LICENSE`.
