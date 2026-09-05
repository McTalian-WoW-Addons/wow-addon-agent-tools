# /// script
# requires-python = ">=3.12"
# ///
"""PreToolUse hook: block a ``git commit`` that would break the build or lie
about its release type.

Reads one JSON hook payload from stdin (see docs/contract.md and DESIGN.md
§1.5). Exits 0 (silently) to allow the tool call; exits 2 with a short
message on stderr to block it. Never raises: any problem reading the
payload, resolving the repo, or loading the profile is treated as "let the
commit through" — this hook only blocks on its five explicit rules (R1-R5).

Deliberately has no dependency on checks.py or pr.py: the two tiny pieces it
needs from them (reading the checks record, and deciding whether a set of
files "touches packaged content") are reimplemented here directly on top of
_common.py.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

# Matches a `git commit` invocation anywhere in a shell command string,
# optionally preceded by `-C <path>`. Anchored to command start or a shell
# separator (`;`, `&`, `|`) so `git commit` embedded in unrelated text (e.g.
# inside a quoted string) mostly does not false-positive on its own -- exact
# quoting is not attempted here, this is a fast pre-filter only.
COMMIT_RE = re.compile(r"(^|[;&|]\s*)git\s+(-C\s+\S+\s+)?commit\b")

# Same shape, but capturing the -C path (if any) so the repo root can be
# resolved relative to it rather than to the hook's `cwd`.
COMMIT_CPATH_RE = re.compile(r"(?:^|[;&|]\s*)git\s+(?:-C\s+(?P<cpath>\S+)\s+)?commit\b")

_SHELL_SEPARATORS = (";", "&", "&&", "|", "||")


def _extract_commit_args(command: str) -> list[str]:
    """Return the argv tokens that follow the first `git ... commit` in
    *command*, stopping at the next shell separator token or end of input.

    Returns [] when the command cannot be tokenized (malformed quoting) or
    no `git commit` invocation is found among the tokens -- callers must
    treat that as "no flags detected", never as a reason to block.
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return []
    n = len(tokens)
    i = 0
    while i < n:
        if tokens[i] == "git":
            j = i + 1
            if j < n and tokens[j] == "-C" and j + 1 < n:
                j += 2
            if j < n and tokens[j] == "commit":
                k = j + 1
                args: list[str] = []
                while k < n and tokens[k] not in _SHELL_SEPARATORS:
                    args.append(tokens[k])
                    k += 1
                return args
        i += 1
    return []


def _parse_commit_flags(args: list[str]) -> dict:
    """Parse commit argv tokens into the flags this hook cares about.

    Returns {"no_verify": bool, "all": bool, "message": str | None}.
    The value of `-m`/`--message` (in any spelling) is taken verbatim as a
    single opaque token and never itself scanned for flags, matching the
    "not inside -m text" requirement for R2.
    """
    no_verify = False
    all_flag = False
    message: str | None = None
    skip_next = False
    for tok in args:
        if skip_next:
            message = tok
            skip_next = False
            continue
        if tok == "--":
            continue
        if tok == "--no-verify":
            no_verify = True
        elif tok == "--all":
            all_flag = True
        elif tok in ("-m", "--message"):
            skip_next = True
        elif tok.startswith("--message="):
            message = tok[len("--message=") :]
        elif tok.startswith("--"):
            pass
        elif tok.startswith("-") and len(tok) > 1:
            body = tok[1:]
            j = 0
            while j < len(body):
                ch = body[j]
                if ch == "n":
                    no_verify = True
                elif ch == "a":
                    all_flag = True
                elif ch == "m":
                    rest = body[j + 1 :]
                    if rest:
                        message = rest
                    else:
                        skip_next = True
                    break
                j += 1
    return {"no_verify": no_verify, "all": all_flag, "message": message}


def _commit_type(message: str | None) -> str | None:
    """Return the lowercase conventional-commit type from *message*'s first
    line, or None when it does not look like `type(scope)?: ...`."""
    if not message:
        return None
    first_line = message.splitlines()[0] if message else ""
    m = re.match(r"^([A-Za-z]+)(?:\([^)]*\))?!?:", first_line)
    if not m:
        return None
    return m.group(1).lower()


def _resolve_start(command: str, cwd_raw: str) -> Path:
    """Return the directory to resolve the repo root from: *cwd_raw*, or
    *cwd_raw* joined with a `-C <path>` argument found in *command*."""
    cwd = Path(cwd_raw)
    m = COMMIT_CPATH_RE.search(command)
    cpath = m.group("cpath") if m else None
    if not cpath:
        return cwd
    p = Path(cpath)
    return p if p.is_absolute() else cwd / p


def _matches_guard(path: str, guard_paths: list[str]) -> bool:
    for g in guard_paths:
        if g.endswith("/"):
            if path == g.rstrip("/") or path.startswith(g):
                return True
        elif path == g:
            return True
    return False


def _intersects_guard(paths: list[str], guard_paths: list[str]) -> bool:
    return any(_matches_guard(p, guard_paths) for p in paths)


def _staged_files(root: Path) -> list[str]:
    out = C.git("diff", "--cached", "--name-only", cwd=root)
    return [line for line in out.splitlines() if line]


def _modified_tracked_files(root: Path) -> list[str]:
    out = C.git("diff", "--name-only", cwd=root)
    return [line for line in out.splitlines() if line]


def _untracked_under(root: Path, guard_paths: list[str]) -> list[str]:
    proc = C.run(["git", "ls-files", "--others", "--exclude-standard", "--", *guard_paths], cwd=root)
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line]


def _block(*lines: str) -> None:
    for line in lines:
        print(line, file=sys.stderr)
    sys.exit(2)


def _check_rules(command: str, root: Path, profile: dict) -> None:
    kind = profile.get("kind")
    guard_paths = profile.get("guardPaths") or []

    commit_args = _extract_commit_args(command)
    flags = _parse_commit_flags(commit_args)

    # R1: current branch is main/master.
    branch = C.git("rev-parse", "--abbrev-ref", "HEAD", cwd=root)
    if branch in ("main", "master"):
        _block(
            f"R1 blocked: commit on protected branch '{branch}'",
            "create a feature branch first: /wow-dev:git-workflow",
        )

    # R2: --no-verify / -n bypasses commit hooks.
    if flags["no_verify"]:
        _block(
            "R2 blocked: --no-verify/-n bypasses commit hooks",
            "remove the flag and commit normally",
        )

    if kind == "unknown" or not guard_paths:
        return

    # R3: untracked files under the packaged dir(s) break the in-game build.
    untracked = _untracked_under(root, guard_paths)
    if untracked:
        shown = ", ".join(untracked[:5])
        _block(
            "R3 blocked: untracked files under packaged dir would break the build",
            f"files: {shown}",
            "git add them or add to .gitignore",
        )

    staged = _staged_files(root)
    effective = set(staged)
    if flags["all"]:
        effective |= set(_modified_tracked_files(root))
    effective_list = sorted(effective)

    # R4: staged packaged changes must be covered by a passing checks run.
    if _intersects_guard(effective_list, guard_paths):
        record = C.read_json(root / C.RECORD_REL)
        stale = (
            record is None
            or record.get("ok") is not True
            or record.get("indexHash") != C.index_hash(root, guard_paths)
        )
        if stale:
            _block(
                "R4 blocked: staged packaged changes aren't covered by a passing check run",
                "run /wow-dev:run-checks then retry",
            )

    # R5: a publishing type requires a packaged file in the commit.
    commit_type = _commit_type(flags["message"])
    if commit_type in C.PUBLISHING_TYPES and not _intersects_guard(effective_list, guard_paths):
        _block(
            f"R5 blocked: publishing type '{commit_type}' used but no packaged file staged",
            f"allowed dev-only types: {' '.join(C.DEV_TYPES)}",
        )


def main() -> int:
    payload = C.hook_input()
    if not payload:
        return C.OK

    tool_name = payload.get("tool_name")
    if tool_name not in ("Bash", "PowerShell"):
        return C.OK

    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return C.OK

    command = tool_input.get("command")
    if not isinstance(command, str) or not COMMIT_RE.search(command):
        return C.OK

    cwd_raw = payload.get("cwd")
    if not isinstance(cwd_raw, str) or not cwd_raw:
        return C.OK

    try:
        start = _resolve_start(command, cwd_raw)
        root = C.repo_root(start)
    except SystemExit:
        return C.OK
    except Exception:
        return C.OK

    try:
        profile = C.load_profile(root)
    except SystemExit:
        return C.OK
    except Exception:
        return C.OK

    try:
        _check_rules(command, root, profile)
    except SystemExit as exc:
        # Only our own _block() raises SystemExit(2) inside _check_rules;
        # propagate that (and only that) as the hook's real exit code.
        return exc.code if isinstance(exc.code, int) else C.FAIL
    except Exception:
        # Any unexpected failure while evaluating the rules (e.g. a git
        # command misbehaving) must never block a commit.
        return C.OK

    return C.OK


if __name__ == "__main__":
    sys.exit(main())
