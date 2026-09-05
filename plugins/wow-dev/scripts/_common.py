# /// script
# requires-python = ">=3.12"
# ///
"""Shared helpers for wow-dev plugin scripts.

Stdlib only. Imported by every other script in this directory; never run
directly. See docs/contract.md for the schema this module underpins.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, NoReturn

OK: int = 0
FAIL: int = 1
USAGE: int = 2

PUBLISHING_TYPES: tuple[str, ...] = ("feat", "fix", "perf", "locale", "toc")
DEV_TYPES: tuple[str, ...] = ("build", "chore", "ci", "docs", "refactor", "style", "test")
ALL_TYPES: tuple[str, ...] = PUBLISHING_TYPES + DEV_TYPES + ("revert",)

RECORD_REL: str = ".claude/.last-checks.json"
PROFILE_REL: str = ".claude/repo.json"


def run(
    cmd: list[str] | str,
    cwd: Path,
    check: bool = False,
    timeout: int = 600,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command and return the completed process with text stdout/stderr.

    A list is executed directly (no shell). A string is executed through the
    shell (``shell=True``) so that pipes, ``&&`` and globs work; callers that
    interpolate untrusted text must pass a list.

    stdout and stderr are captured separately, decoded as UTF-8 with
    ``errors="replace"``, and never inherited from the parent.

    Args:
        cmd: argv list, or a shell command string.
        cwd: working directory; must exist.
        check: when True, raise CalledProcessError on a non-zero return code.
        timeout: seconds before the child is killed; on expiry a
            CompletedProcess with returncode 124 and stderr
            "timeout after {timeout}s" is returned (never an exception).
        env: full environment for the child; None inherits os.environ.

    Returns:
        subprocess.CompletedProcess[str] with .returncode, .stdout, .stderr.
    """
    is_shell = isinstance(cmd, str)
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            shell=is_shell,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            args=cmd, returncode=124, stdout="", stderr=f"timeout after {timeout}s"
        )
    if check and proc.returncode != 0:
        raise subprocess.CalledProcessError(
            proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr
        )
    return proc


def git(*args: str, cwd: Path) -> str:
    """Run ``git <args>`` in *cwd* and return stdout stripped of a trailing newline.

    Never raises on a non-zero exit: a failed git command returns the empty
    string. Callers that must distinguish "empty result" from "command
    failed" use ``run(["git", ...], cwd)`` directly.
    """
    proc = run(["git", *args], cwd=cwd)
    if proc.returncode != 0:
        return ""
    return proc.stdout.rstrip("\n")


def repo_root(start: Path | None = None) -> Path:
    """Return the absolute git top level containing *start* (default: cwd).

    Resolves symlinks. Raises SystemExit(USAGE) with
    "not inside a git repository: <path>" when ``git rev-parse --show-toplevel``
    fails, so every script inherits the same error text.
    """
    if start is None:
        start = Path.cwd()
    start = start.resolve()
    proc = run(["git", "rev-parse", "--show-toplevel"], cwd=start)
    if proc.returncode != 0:
        die(f"not inside a git repository: {start}", USAGE)
    return Path(proc.stdout.strip()).resolve()


def _band(lo: int, hi: int) -> Callable[[int], bool]:
    return lambda i, lo=lo, hi=hi: lo <= i < hi


FLAVORS: list[dict] = [
    {
        "band": "1xxxx",
        "name": "classic_era",
        "ref": "classic_era",
        "product": "wow_classic_era",
        "match": _band(10000, 20000),
    },
    {
        "band": "2xxxx",
        "name": "tbc_anniversary",
        "ref": "origin/classic_anniversary",
        "product": "wow_anniversary",
        "match": _band(20000, 30000),
    },
    {
        "band": "5xxxx",
        "name": "mop_classic",
        "ref": "classic",
        "product": "wow_classic",
        "match": _band(50000, 60000),
    },
    {
        "band": "11xxxx|12xxxx",
        "name": "retail",
        "ref": "live",
        "product": "wow",
        "match": _band(110000, 130000),
    },
]


def flavor_for(interface: int) -> dict:
    """Return the FLAVORS entry whose ``match`` accepts *interface*.

    For an interface in no known band, returns a fresh dict
    ``{"band": None, "name": f"unknown-{interface}", "ref": None,
       "product": None, "match": <always False>}``.
    The returned dict is a copy; mutating it never affects FLAVORS.
    """
    for entry in FLAVORS:
        if entry["match"](interface):
            return dict(entry)
    return {
        "band": None,
        "name": f"unknown-{interface}",
        "ref": None,
        "product": None,
        "match": lambda i: False,
    }


def load_profile(root: Path) -> dict:
    """Return the repo_profile.py schema dict for the repo at *root*.

    Implemented by importing ``repo_profile`` from this directory and calling
    ``repo_profile.build_profile(root)`` in-process — never as a subprocess.
    The import is done inside the function body so that ``repo_profile`` can
    import ``_common`` at module level without a cycle.

    Raises SystemExit(USAGE) when ``.claude/repo.json`` contains an unknown key,
    with the message "unknown key in .claude/repo.json: <key>".
    """
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import repo_profile

    return repo_profile.build_profile(root)


def index_hash(root: Path, paths: list[str]) -> str:
    """Return sha256 hex of ``git ls-files -s -- <paths>`` stdout, run in *root*.

    The digest covers mode, blob sha and stage for every tracked file under
    *paths*, so it changes when packaged content changes and does not change
    when an untracked or ignored file appears. An empty *paths* list yields the
    digest of the empty string (64 hex chars, never "").
    """
    if not paths:
        out = ""
    else:
        proc = run(["git", "ls-files", "-s", "--", *paths], cwd=root)
        out = proc.stdout
    return hashlib.sha256(out.encode("utf-8")).hexdigest()


def write_json(path: Path, obj: dict) -> None:
    """Write *obj* to *path* as UTF-8 JSON, creating parent directories.

    Two-space indent, ``sort_keys=False`` (declaration order is meaningful),
    ``ensure_ascii=False``, trailing newline. Writes to ``<path>.tmp`` and
    ``os.replace``s it into position so a reader never sees a partial file.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    text = json.dumps(obj, indent=2, sort_keys=False, ensure_ascii=False) + "\n"
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def read_json(path: Path) -> dict | None:
    """Return the parsed object at *path*, or None.

    None on: missing file, unreadable file, invalid JSON, or a top-level value
    that is not an object. Never raises.
    """
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def emit(obj: dict, as_json: bool, text_fn: Callable[[dict], None]) -> None:
    """Print *obj* as one JSON object, or hand it to *text_fn* for prose.

    When *as_json* is True, prints ``json.dumps(obj, indent=2,
    ensure_ascii=False)`` followed by a newline to stdout and returns.
    Otherwise calls ``text_fn(obj)``, which is responsible for all printing.
    Never exits; the caller chooses the exit code.
    """
    if as_json:
        print(json.dumps(obj, indent=2, ensure_ascii=False))
        return
    text_fn(obj)


def die(msg: str, code: int = USAGE) -> NoReturn:
    """Print *msg* to stderr (no trailing period added) and ``sys.exit(code)``."""
    print(msg, file=sys.stderr)
    sys.exit(code)


def hook_input() -> dict:
    """Read one JSON object from stdin and return it; return {} on any problem.

    Reads stdin to EOF. Returns {} when stdin is a TTY, is empty, does not
    parse, or parses to something other than an object. Never raises and never
    blocks longer than the harness hook timeout, because the harness closes the
    pipe. A hook that gets {} must exit OK — an unreadable hook payload is
    never a reason to block a tool call.
    """
    try:
        if sys.stdin.isatty():
            return {}
        data = sys.stdin.read()
    except Exception:
        return {}
    if not data:
        return {}
    try:
        obj = json.loads(data)
    except json.JSONDecodeError:
        return {}
    if not isinstance(obj, dict):
        return {}
    return obj
