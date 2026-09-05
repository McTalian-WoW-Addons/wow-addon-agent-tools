# /// script
# requires-python = ">=3.12"
# ///
"""Lint hot-path agent-facing docs for budget, rationale, frontmatter, headings, roster rules.

Self-contained: stdlib only. Does NOT import ``_common`` — this script runs in
CI against hot-path files alone, so it duplicates the tiny ``OK/FAIL/USAGE``
exit-code contract locally instead of depending on the rest of the plugin.

See docs/contract.md and DESIGN.md §4.4 for the rule table this module
implements.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import NoReturn

OK: int = 0
FAIL: int = 1
USAGE: int = 2

# --- Byte budgets, by file kind -------------------------------------------

BUDGET_CLAUDE_MD: int = 2048
BUDGET_SKILL_MD: int = 6144
BUDGET_SKILL_MD_LARGE: int = 8192
BUDGET_AGENT_MD: int = 4096
BUDGET_ROSTER_MD: int = 2560
BUDGET_CONVENTIONS_MD: int = 4096

LARGE_SKILLS: frozenset[str] = frozenset({"work-item", "review-pr"})

# --- Frontmatter value ranges/enums ----------------------------------------

SKILL_DESC_RANGE: tuple[int, int] = (150, 460)
AGENT_DESC_RANGE: tuple[int, int] = (250, 470)

VALID_MODELS: frozenset[str] = frozenset({"haiku", "sonnet", "opus", "inherit"})
VALID_EFFORTS: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max"})

AGENT_FIELD_ORDER: tuple[str, ...] = ("name", "description", "tools", "model", "effort")

# --- Roster of agent names that a SKILL.md must not mention uncited --------

AGENT_ROSTER_NAMES: tuple[str, ...] = (
    "wow-api-researcher",
    "impl-researcher",
    "lua-feature-builder",
    "spec-author",
    "lua-convention-reviewer",
    "localization-reviewer",
    "commit-type-reviewer",
    "skill-prose-reviewer",
    "claim-evidence-reviewer",
)

# --- Rationale/history regexes (case-insensitive, per line) ----------------

RATIONALE_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"\bbecause\b",
        r"\bhistorically\b",
        r"\bPR #?\d+",
        r"\(#\d+\)",
        r"(?<![-#])#\d{2,}\b",
        r"\bwe decided\b",
        r"\bthe reason\b",
        r"\bused to\b",
        r"\bat time of writing\b",
        r"\boriginally\b",
        r"\bin the past\b",
        r"\bno longer\b",
        r"\bthis is why\b",
        r"\bincident\b",
    )
)

RATIONALE_EXEMPT_RE: re.Pattern[str] = re.compile(r"decisions\.md|REFERENCE\.md")

HEADING_RE: re.Pattern[str] = re.compile(r"^##\s+(.*\S)\s*$")
FENCE_RE: re.Pattern[str] = re.compile(r"^\s*```")
CLAUDE_MD_HEADINGS: tuple[str, ...] = ("Commands", "Conventions", "Docs")


# --- Frontmatter -------------------------------------------------------


@dataclass
class Frontmatter:
    fields: dict[str, str] = field(default_factory=dict)
    order: list[str] = field(default_factory=list)
    end_line: int = -1  # 0-indexed index of the closing '---' line


def parse_frontmatter(text: str) -> Frontmatter | None:
    """Parse a leading ``---`` YAML-ish block of simple ``key: value`` lines.

    Returns None when the file does not open with ``---`` on its first line,
    or the block is never closed. Only scalar ``key: value`` lines are
    recognised; anything else inside the block is ignored (this plugin's
    frontmatter never nests).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return None
    fm = Frontmatter(end_line=end)
    key_re = re.compile(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$")
    for line in lines[1:end]:
        if not line.strip() or line.startswith((" ", "\t", "-")):
            continue
        m = key_re.match(line)
        if not m:
            continue
        key, val = m.group(1), m.group(2).strip()
        fm.fields[key] = val
        fm.order.append(key)
    return fm


def classify(path: Path, fm: Frontmatter | None) -> str:
    """Return one of claude/roster/conventions/skill/agent/other for *path*."""
    name = path.name
    if name == "CLAUDE.md":
        return "claude"
    if name == "ROSTER.md":
        return "roster"
    if name == "conventions.md":
        return "conventions"
    if fm is not None:
        if any(k in fm.fields for k in ("tools", "model", "effort")):
            return "agent"
        if "description" in fm.fields or "name" in fm.fields:
            return "skill"
    if name == "SKILL.md":
        return "skill"
    if path.parent.name == "agents":
        return "agent"
    return "other"


def budget_for(kind: str, path: Path, fm: Frontmatter | None) -> int | None:
    """Return the byte budget for *kind*, or None when no budget applies."""
    if kind == "claude":
        return BUDGET_CLAUDE_MD
    if kind == "roster":
        return BUDGET_ROSTER_MD
    if kind == "conventions":
        return BUDGET_CONVENTIONS_MD
    if kind == "agent":
        return BUDGET_AGENT_MD
    if kind == "skill":
        skill_name = None
        if path.name == "SKILL.md":
            skill_name = path.parent.name
        elif fm is not None:
            skill_name = fm.fields.get("name")
        if skill_name in LARGE_SKILLS:
            return BUDGET_SKILL_MD_LARGE
        return BUDGET_SKILL_MD
    return None


# --- Findings ----------------------------------------------------------


def _display_path(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(Path.cwd().resolve())
        return rel.as_posix()
    except ValueError:
        return path.as_posix()


def _finding(path: Path, line: int, rule: str, excerpt: str) -> dict:
    return {"path": _display_path(path), "line": line, "rule": rule, "excerpt": excerpt[:120]}


# --- Individual rules ----------------------------------------------------


def check_budget(path: Path, raw: bytes, kind: str, fm: Frontmatter | None) -> list[dict]:
    budget = budget_for(kind, path, fm)
    if budget is None or len(raw) <= budget:
        return []
    return [
        _finding(
            path,
            1,
            "BUDGET",
            f"{len(raw)} bytes exceeds {budget} byte budget ({kind})",
        )
    ]


def check_rationale(path: Path, text: str) -> list[dict]:
    lines = text.splitlines()
    fm_end = -1
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                fm_end = i
                break
    out: list[dict] = []
    in_fence = False
    for idx, line in enumerate(lines):
        if idx <= fm_end:
            continue
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if RATIONALE_EXEMPT_RE.search(line):
            continue
        for pat in RATIONALE_PATTERNS:
            if pat.search(line):
                out.append(_finding(path, idx + 1, "RATIONALE", line.strip()))
                break
    return out


def check_frontmatter(path: Path, kind: str, fm: Frontmatter | None) -> list[dict]:
    if fm is None:
        return [_finding(path, 1, "FRONTMATTER", "missing frontmatter block")]

    out: list[dict] = []
    if kind == "skill":
        if "name" not in fm.fields:
            out.append(_finding(path, 1, "FRONTMATTER", "missing required key: name"))
        if "description" not in fm.fields:
            out.append(_finding(path, 1, "FRONTMATTER", "missing required key: description"))
        else:
            desc = fm.fields["description"]
            lo, hi = SKILL_DESC_RANGE
            if not (lo <= len(desc) <= hi):
                out.append(
                    _finding(
                        path,
                        1,
                        "FRONTMATTER",
                        f"description is {len(desc)} chars, need {lo}-{hi}",
                    )
                )
        return out

    if kind == "agent":
        missing = [k for k in AGENT_FIELD_ORDER if k not in fm.fields]
        if missing:
            out.append(
                _finding(
                    path,
                    1,
                    "FRONTMATTER",
                    f"missing required key(s): {', '.join(missing)}",
                )
            )
        extra = [k for k in fm.order if k not in AGENT_FIELD_ORDER]
        if extra:
            out.append(
                _finding(path, 1, "FRONTMATTER", f"unexpected key(s): {', '.join(extra)}")
            )
        actual_known = [k for k in fm.order if k in AGENT_FIELD_ORDER]
        if not missing and not extra and actual_known != list(AGENT_FIELD_ORDER):
            out.append(
                _finding(
                    path,
                    1,
                    "FRONTMATTER",
                    f"keys out of order: {', '.join(fm.order)}",
                )
            )
        if "model" in fm.fields and fm.fields["model"] not in VALID_MODELS:
            out.append(
                _finding(path, 1, "FRONTMATTER", f"invalid model: {fm.fields['model']}")
            )
        if "effort" in fm.fields and fm.fields["effort"] not in VALID_EFFORTS:
            out.append(
                _finding(path, 1, "FRONTMATTER", f"invalid effort: {fm.fields['effort']}")
            )
        if "description" in fm.fields:
            desc = fm.fields["description"]
            lo, hi = AGENT_DESC_RANGE
            if not (lo <= len(desc) <= hi):
                out.append(
                    _finding(
                        path,
                        1,
                        "FRONTMATTER",
                        f"description is {len(desc)} chars, need {lo}-{hi}",
                    )
                )
        return out

    return out


def check_headings(path: Path, text: str) -> list[dict]:
    headings: list[str] = []
    heading_lines: list[int] = []
    for idx, line in enumerate(text.splitlines()):
        m = HEADING_RE.match(line)
        if m:
            headings.append(m.group(1))
            heading_lines.append(idx + 1)
    if tuple(headings) == CLAUDE_MD_HEADINGS:
        return []
    lineno = heading_lines[0] if heading_lines else 1
    return [
        _finding(
            path,
            lineno,
            "HEADINGS",
            f"H2s are {headings!r}, need {list(CLAUDE_MD_HEADINGS)!r}",
        )
    ]


def check_roster(path: Path, text: str) -> list[dict]:
    if "ROSTER.md" in text:
        return []
    for idx, line in enumerate(text.splitlines()):
        for name in AGENT_ROSTER_NAMES:
            if re.search(rf"\b{re.escape(name)}\b", line):
                return [_finding(path, idx + 1, "ROSTER", line.strip())]
    return []


def lint_file(path: Path, explicit: bool) -> list[dict]:
    """Run every applicable rule against *path* and return its findings.

    *explicit* is True when *path* was named directly on the command line
    (as opposed to discovered via a default/plugin glob) — the HEADINGS rule
    only fires on a discovered ``CLAUDE.md``.
    """
    try:
        raw = path.read_bytes()
    except OSError as exc:
        return [_finding(path, 1, "READ", f"cannot read file: {exc}")]
    text = raw.decode("utf-8", errors="replace")
    fm = parse_frontmatter(text)
    kind = classify(path, fm)

    findings: list[dict] = []
    findings.extend(check_budget(path, raw, kind, fm))
    findings.extend(check_rationale(path, text))
    if kind in ("skill", "agent"):
        findings.extend(check_frontmatter(path, kind, fm))
    if kind == "claude" and not explicit:
        findings.extend(check_headings(path, text))
    if kind == "skill":
        findings.extend(check_roster(path, text))
    return findings


# --- Target discovery ------------------------------------------------------


class DoclintUsageError(Exception):
    pass


def is_plugin_root(path: Path) -> bool:
    if (path / ".claude-plugin").is_dir():
        return True
    return (path / "skills").is_dir() and (path / "agents").is_dir()


_EXCLUDED_DIRS = {"worktrees", ".venv", "node_modules", "__pycache__"}


def _excluded(path: Path, base: Path) -> bool:
    """True when any directory between *base* and *path* is a nested checkout or vendored tree."""
    return any(part in _EXCLUDED_DIRS for part in path.relative_to(base).parts[:-1])


def discover_repo(root: Path) -> list[tuple[Path, bool]]:
    """Default hot-path file set for a normal repo rooted at *root*."""
    out: list[tuple[Path, bool]] = []
    claude = root / "CLAUDE.md"
    if claude.is_file():
        out.append((claude, False))
    claude_dir = root / ".claude"
    if claude_dir.is_dir():
        for p in sorted(claude_dir.glob("**/SKILL.md")):
            if _excluded(p, claude_dir):
                continue
            out.append((p, False))
        agents_dir = claude_dir / "agents"
        if agents_dir.is_dir():
            for p in sorted(agents_dir.glob("*.md")):
                out.append((p, False))
    conventions = root / "docs" / "agent" / "conventions.md"
    if conventions.is_file():
        out.append((conventions, False))
    return out


def discover_plugin(root: Path) -> list[tuple[Path, bool]]:
    """Hot-path file set for a plugin root (``.claude-plugin/`` or skills+agents)."""
    out: list[tuple[Path, bool]] = []
    skills_dir = root / "skills"
    if skills_dir.is_dir():
        for p in sorted(skills_dir.glob("**/SKILL.md")):
            out.append((p, False))
    agents_dir = root / "agents"
    if agents_dir.is_dir():
        for p in sorted(agents_dir.glob("*.md")):
            out.append((p, False))
    roster = root / "ROSTER.md"
    if roster.is_file():
        out.append((roster, False))
    return out


def collect_targets(paths: list[str]) -> list[tuple[Path, bool]]:
    targets: list[tuple[Path, bool]] = []
    for raw in paths:
        p = Path(raw)
        if not p.is_absolute():
            p = Path.cwd() / p
        p = p.resolve()
        if p.is_file():
            targets.append((p, True))
        elif p.is_dir():
            if is_plugin_root(p):
                targets.extend(discover_plugin(p))
            else:
                targets.extend(discover_repo(p))
        else:
            raise DoclintUsageError(f"path not found: {raw}")
    return targets


def git_toplevel(start: Path) -> Path | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=str(start),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except OSError:
        return None
    if proc.returncode != 0:
        return None
    out = proc.stdout.strip()
    if not out:
        return None
    return Path(out).resolve()


# --- CLI ---------------------------------------------------------------


def die(msg: str, code: int = USAGE) -> NoReturn:
    print(msg, file=sys.stderr)
    sys.exit(code)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="doclint.py",
        description="Lint hot-path agent-facing docs for budget/rationale/frontmatter/headings/roster rules.",
    )
    parser.add_argument("paths", nargs="*", metavar="PATH")
    parser.add_argument("--root", default=None)
    parser.add_argument("--json", action="store_true")
    return parser


def run(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)  # argparse exits(2) itself on a bad invocation

    if args.paths:
        try:
            targets = collect_targets(args.paths)
        except DoclintUsageError as exc:
            die(str(exc), USAGE)
    else:
        if args.root is not None:
            root = Path(args.root)
            if not root.is_absolute():
                root = Path.cwd() / root
            root = root.resolve()
            if not root.is_dir():
                die(f"--root is not a directory: {args.root}", USAGE)
        else:
            root = git_toplevel(Path.cwd())
            if root is None:
                die("not inside a git repository; pass PATH or --root", USAGE)
        targets = discover_repo(root)

    findings: list[dict] = []
    for path, explicit in targets:
        findings.extend(lint_file(path, explicit))
    findings.sort(key=lambda f: (f["path"], f["line"], f["rule"]))

    ok = not findings
    if args.json:
        print(json.dumps({"ok": ok, "findings": findings}, indent=2, ensure_ascii=False))
    else:
        for f in findings:
            print(f"{f['path']}:{f['line']} — {f['rule']} — {f['excerpt']}")
    return OK if ok else FAIL


def main(argv: list[str] | None = None) -> int:
    try:
        return run(argv)
    except SystemExit:
        raise
    except Exception as exc:  # pragma: no cover - defensive
        die(f"doclint.py: internal error: {exc}", USAGE)


if __name__ == "__main__":
    sys.exit(main())
