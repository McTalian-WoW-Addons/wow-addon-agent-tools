# /// script
# requires-python = ">=3.12"
# ///
"""Manage `--#region`-versioned `enUS.lua` locale keys.

See docs/contract.md for the profile schema (``localeDir``,
``localeVersionStyle``) this depends on, and PLAN.md §4.2 for the CLI
contract this implements.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

_REGION_RE = re.compile(r"^\s*--#region\s+(.*\S)\s*$")
_ENDREGION_RE = re.compile(r"^\s*--#endregion\s*$")
_KEY_LINE_RE = re.compile(r'^\s*L\[\s*"(?:[^"\\]|\\.)*"\s*\]\s*=')
_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def _to_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _locale_file(root: Path, profile: dict) -> Path:
    locale_dir = profile.get("localeDir")
    if not locale_dir:
        C.die("no localeDir in profile", C.USAGE)
    path = root / locale_dir / "enUS.lua"
    if not path.is_file():
        C.die(f"locale file not found: {path}", C.USAGE)
    return path


def _parse_regions(lines: list[str]) -> list[dict]:
    """Return regions top-to-bottom: [{"version", "start", "end", "keys"}].

    ``start``/``end`` are line indexes (into *lines*) of the ``--#region`` and
    matching ``--#endregion`` markers. Regions are flat (never nested).
    """
    regions: list[dict] = []
    current: dict | None = None
    for i, line in enumerate(lines):
        if current is None:
            m = _REGION_RE.match(line)
            if m:
                current = {"version": m.group(1), "start": i, "end": None, "keys": 0}
            continue
        if _ENDREGION_RE.match(line):
            current["end"] = i
            regions.append(current)
            current = None
            continue
        if _KEY_LINE_RE.match(line):
            current["keys"] += 1
    return regions


def _escape_lua_string(text: str) -> str:
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _key_exists(text: str, key: str) -> bool:
    return f'L["{key}"]' in text


def _bump_minor(tag: str) -> str | None:
    m = _TAG_RE.match(tag)
    if not m:
        return None
    major, minor, _patch = (int(g) for g in m.groups())
    return f"{major}.{minor + 1}.0"


def _target_version(args, root: Path, profile: dict, top_version: str | None) -> str:
    if args.version:
        return args.version

    proc = C.run(["git", "describe", "--tags", "--abbrev=0"], cwd=root)
    if proc.returncode != 0 or not proc.stdout.strip():
        if top_version is None:
            C.die("cannot determine version: no tags and no existing region", C.USAGE)
        return top_version

    tag = proc.stdout.strip()
    bumped = _bump_minor(tag)
    if bumped is None:
        if top_version is None:
            C.die(f"cannot parse tag as semver: {tag}", C.USAGE)
        return top_version

    style = profile.get("localeVersionStyle") or ""
    if style:
        prefix = style
    elif top_version is not None:
        prefix = "v" if top_version.startswith("v") else ""
    else:
        prefix = ""
    return f"{prefix}{bumped}"


def cmd_add(args, root: Path) -> int:
    profile = C.load_profile(root)
    path = _locale_file(root, profile)
    text = path.read_text(encoding="utf-8")

    if _key_exists(text, args.key):
        C.die(f"key already exists: {args.key}", C.FAIL)

    trailing_nl = text.endswith("\n")
    lines = text.splitlines()
    regions = _parse_regions(lines)
    top_version = regions[0]["version"] if regions else None

    target_version = _target_version(args, root, profile, top_version)
    escaped_text = _escape_lua_string(args.text)
    key_line = f'L["{args.key}"] = "{escaped_text}"'

    created_region = top_version is None or target_version != top_version

    if created_region:
        insert_at = regions[0]["start"] if regions else len(lines)
        new_block = [f"--#region {target_version}", key_line, "--#endregion"]
        lines[insert_at:insert_at] = new_block
    else:
        insert_at = regions[0]["end"]
        lines.insert(insert_at, key_line)

    new_text = "\n".join(lines)
    if trailing_nl or not new_text.endswith("\n"):
        new_text += "\n"
    path.write_text(new_text, encoding="utf-8")

    make_targets = profile.get("makeTargets") or []
    if "i18n_fmt" in make_targets:
        C.run(["make", "i18n_fmt"], cwd=root)

    result = {
        "ok": True,
        "key": args.key,
        "version": target_version,
        "created_region": created_region,
        "file": _to_posix(root, path),
    }

    def _text(obj: dict) -> None:
        action = "created region" if obj["created_region"] else "added to region"
        print(f"{action} {obj['version']}: {obj['key']} -> {obj['file']}")

    C.emit(result, args.json, _text)
    return C.OK


def cmd_check(args, root: Path) -> int:
    profile = C.load_profile(root)
    make_targets = profile.get("makeTargets") or []
    cmd = ["make", "all_checks"] if "all_checks" in make_targets else ["make", "i18n_check"]

    proc = C.run(cmd, cwd=root)
    ok = proc.returncode == 0

    if args.json:
        result = {
            "ok": ok,
            "cmd": " ".join(cmd),
            "returncode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if proc.stdout:
            sys.stdout.write(proc.stdout)
        if proc.stderr:
            sys.stderr.write(proc.stderr)

    return C.OK if ok else C.FAIL


def cmd_regions(args, root: Path) -> int:
    profile = C.load_profile(root)
    path = _locale_file(root, profile)
    lines = path.read_text(encoding="utf-8").splitlines()
    regions = _parse_regions(lines)
    result = [{"version": r["version"], "keys": r["keys"]} for r in regions]

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(", ".join(r["version"] for r in result))

    return C.OK


def _add_common(p: argparse.ArgumentParser) -> None:
    # Text is always the default output mode, so the only switch that
    # matters is --json. ("add" also has its own --text argument for the
    # locale string value, so a placeholder --text flag here — as pr.py
    # carries for symmetry — would collide with it.)
    p.add_argument("--root", type=Path, default=None)
    p.add_argument("--json", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="i18n.py", description="Manage --#region-versioned enUS.lua locale keys."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add")
    p_add.add_argument("--key", required=True)
    p_add.add_argument("--text", required=True)
    p_add.add_argument("--version", default=None)
    _add_common(p_add)

    p_check = sub.add_parser("check")
    _add_common(p_check)

    p_regions = sub.add_parser("regions")
    _add_common(p_regions)

    args = parser.parse_args()
    root = args.root.resolve() if args.root else C.repo_root(Path.cwd())

    if args.command == "add":
        return cmd_add(args, root)
    if args.command == "check":
        return cmd_check(args, root)
    if args.command == "regions":
        return cmd_regions(args, root)
    return C.USAGE  # pragma: no cover - argparse `required=True` prevents this


if __name__ == "__main__":
    sys.exit(main())
