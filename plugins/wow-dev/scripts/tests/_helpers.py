"""Shared test fixtures and shims for wow-dev plugin script tests.

Not a test module itself (no test_ prefix); imported by test_*.py files.
Inserts scripts/ on sys.path so tests can `import _common`, `import
repo_profile`, etc.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

FIXTURES: Path = Path(__file__).resolve().parent / "fixtures"
SCRIPTS_DIR: Path = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

_ENV_PASSTHROUGH = ("PATH", "HOME", "LANG", "SYSTEMROOT")


def _write_file(root: Path, rel: str, content: str) -> None:
    if rel.endswith("/"):
        (root / rel).mkdir(parents=True, exist_ok=True)
        return
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    basename = path.name
    if basename == "trunk" or "bin/" in rel.replace(os.sep, "/"):
        path.chmod(0o755)
    else:
        path.chmod(0o644)


def _apply_commits(root: Path, commits: list[dict] | None) -> None:
    if not commits:
        return
    for commit in commits:
        files = commit.get("files") or {}
        for rel, content in files.items():
            _write_file(root, rel, content)
        add = commit.get("add")
        if add is None:
            add = list(files.keys())
        message = commit.get("message", "chore: commit")
        if add:
            subprocess.run(["git", "add", *add], cwd=str(root), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", message], cwd=str(root), check=True, capture_output=True
            )
        else:
            subprocess.run(
                ["git", "commit", "--allow-empty", "-m", message],
                cwd=str(root),
                check=True,
                capture_output=True,
            )


def make_temp_repo(
    files: dict[str, str],
    init_git: bool = True,
    commits: list[dict] | None = None,
) -> Path:
    """Materialise a throwaway repo in a temp dir and return its absolute root.

    files: repo-relative POSIX path -> file content. Parent directories are
        created. A path ending in "/" creates an empty directory. A path whose
        basename is "trunk" or that sits under "bin/" is written mode 0o755;
        everything else 0o644.
    init_git: run ``git init -b main`` plus ``git config user.name/user.email``
        and ``git config commit.gpgsign false`` in the new tree.
    commits: applied in order after init. Each entry is
        ``{"files": {path: content}, "message": "feat: x", "add": ["path", ...]}``.
        "files" is written first (optional), then "add" (default: every path in
        "files") is staged, then one commit is made with "message". A commit
        with no "files" and no "add" makes an empty commit (--allow-empty).

    The caller is responsible for cleanup.
    """
    root = Path(tempfile.mkdtemp(prefix="wow-dev-test-"))
    for rel, content in files.items():
        _write_file(root, rel, content)

    if init_git:
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=str(root), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        _apply_commits(root, commits)

    return root


def fixture_repo(
    name: str,
    extra: dict[str, str] | None = None,
    init_git: bool = True,
    commits: list[dict] | None = None,
) -> Path:
    """Copy ``FIXTURES/<name>`` to a temp dir, merge *extra*, then behave like
    make_temp_repo. File modes are preserved by the copy, so the ``trunk`` stub
    stays executable. Returns the temp root."""
    src = FIXTURES / name
    root = Path(tempfile.mkdtemp(prefix="wow-dev-test-"))
    root.rmdir()
    shutil.copytree(src, root, symlinks=True)

    if extra:
        for rel, content in extra.items():
            _write_file(root, rel, content)

    if init_git:
        subprocess.run(
            ["git", "init", "-b", "main"], cwd=str(root), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "config", "user.name", "Test User"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "commit.gpgsign", "false"],
            cwd=str(root),
            check=True,
            capture_output=True,
        )
        _apply_commits(root, commits)

    return root


def run_script(
    name: str,
    *args: str,
    cwd: Path,
    stdin: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run ``<SCRIPTS_DIR>/<name>`` (e.g. "repo_profile.py") with *args*.

    Executed as ``[sys.executable, str(SCRIPTS_DIR / name), *args]`` — the test
    suite does NOT shell out to ``uv``.

    env: when given, it REPLACES the child environment except that PATH,
        HOME, LANG and SYSTEMROOT are filled in from os.environ if absent.
        Always sets GIT_CONFIG_GLOBAL=/dev/null and GIT_CONFIG_SYSTEM=/dev/null.
    Returns the CompletedProcess with text stdout/stderr; never raises on a
    non-zero exit."""
    child_env = env
    if child_env is not None:
        child_env = dict(child_env)
        for key in _ENV_PASSTHROUGH:
            if key not in child_env and key in os.environ:
                child_env[key] = os.environ[key]
    child_env = child_env if child_env is not None else dict(os.environ)
    child_env["GIT_CONFIG_GLOBAL"] = "/dev/null"
    child_env["GIT_CONFIG_SYSTEM"] = "/dev/null"

    return subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / name), *args],
        cwd=str(cwd),
        input=stdin,
        capture_output=True,
        text=True,
        env=child_env,
    )


def json_out(cp: subprocess.CompletedProcess) -> dict:
    """Parse cp.stdout as one JSON object; fail the test with the full
    stdout+stderr when it does not parse."""
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(
            f"stdout did not parse as JSON: {exc}\n"
            f"--- stdout ---\n{cp.stdout}\n--- stderr ---\n{cp.stderr}"
        ) from None


def shim(bin_dir: Path, name: str, script_body: str) -> Path:
    """Write an executable POSIX-sh stub at ``bin_dir/name`` and return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(f"#!/bin/sh\n{script_body}\n", encoding="utf-8")
    st = path.stat()
    path.chmod(st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return path


def wow_ui_source_available() -> bool:
    """True when ``$WOW_UI_SOURCE`` (default ``~/code/wow-ui-source``) is a
    directory containing ``.git``."""
    root = Path(os.environ.get("WOW_UI_SOURCE", str(Path.home() / "code" / "wow-ui-source")))
    return (root / ".git").exists()
