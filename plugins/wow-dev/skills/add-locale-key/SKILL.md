---
name: add-locale-key
description: Add a user-facing string as a locale key in the repo's enUS.lua inside the current version's --#region block, reference it via the repo's L table, format, and run the i18n checks. Use whenever new user-visible text is added or a hardcoded-string/missing-key check fails. Trigger on /wow-dev:add-locale-key <Key> "<English text>", or "localize this string", "add a locale key".
argument-hint: <Key> "<English text>"
---

# /wow-dev:add-locale-key — add a locale key and check i18n

## Command

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/i18n.py" add --key "<Key>" --text "<text>"
```

Then verify:

```bash
uv run --no-project "${CLAUDE_PLUGIN_ROOT}/scripts/i18n.py" check
```

Pass `--version X.Y.Z` only to target a version other than the current top region.

## In code

Reference the key through the repo's L table, not the raw string. The exact form
(`G_RLF.L["Key"]`, `ns.L["Key"]`, `L["Key"]`, …) comes from the repo's
`docs/agent/conventions.md` §Strings — read that file before writing the reference.

## Key style

Use the English text itself as the key when it is short and stable. Otherwise use a
PascalCase noun phrase. Never reuse an existing key with new text — add a new key
instead.

## Non-enUS

Do not add translations for other locales at key-add time. The missing-translation
check reports them separately; leave that to the localization reviewer.
