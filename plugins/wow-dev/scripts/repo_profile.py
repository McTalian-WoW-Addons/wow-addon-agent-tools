# /// script
# requires-python = ">=3.12"
# ///
"""Detect a WoW addon/lib/go-tool repo's capabilities and emit a JSON profile.

See docs/contract.md for the full schema and detection-rule table.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

CI_WORKFLOW_MAP = {
    "pr-checks.yml": "prChecks",
    "release-checks.yml": "releaseChecks",
    "ci.yml": "ci",
    "toc-updater.yml": "tocUpdater",
}
CI_KEYS = ("prChecks", "releaseChecks", "ci", "tocUpdater")

OVERRIDE_KEYS = {"kind", "addonDir", "checks", "guardPaths", "localeVersionStyle", "skipChecks"}

_USES_RE = re.compile(
    r"uses:\s*McTalian-WoW-Addons/wow-build-tools/\.github/workflows/([\w.-]+\.yml)@"
)
_TARGET_RE = re.compile(r"^([A-Za-z0-9_-]+)\s*:(?!=)")
_INTERFACE_RE = re.compile(r"^##\s*Interface:\s*(.+)$", re.IGNORECASE | re.MULTILINE)


def _to_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _find_addon_dir(root: Path) -> str | None:
    candidates = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        toc = child / f"{child.name}.toc"
        if toc.is_file():
            candidates.append(child.name)
    return candidates[0] if candidates else None


def _parse_make_targets(makefile_path: Path) -> list[str]:
    if not makefile_path.is_file():
        return []
    targets: list[str] = []
    try:
        text = makefile_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        if line.startswith(("\t", " ")):
            continue
        m = _TARGET_RE.match(line)
        if m:
            name = m.group(1)
            if name not in targets:
                targets.append(name)
    return targets


def _parse_interfaces(toc_path: Path) -> list[int]:
    try:
        text = toc_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    m = _INTERFACE_RE.search(text)
    if not m:
        return []
    out: list[int] = []
    for tok in m.group(1).split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.append(int(tok))
    return out


def _has_trunk(root: Path) -> bool:
    return (root / "trunk").is_file() or (root / ".trunk" / "trunk.yaml").is_file()


def _find_generic_spec_dir(root: Path) -> str | None:
    for child in sorted(root.iterdir()):
        if child.is_dir() and not child.name.startswith(".") and child.name.endswith("_spec"):
            return child.name
    return None


def _detect_ci(root: Path) -> dict:
    ci = {key: False for key in CI_KEYS}
    workflows_dir = root / ".github" / "workflows"
    if not workflows_dir.is_dir():
        return ci
    for yml in sorted(workflows_dir.glob("*.yml")):
        try:
            text = yml.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for m in _USES_RE.finditer(text):
            key = CI_WORKFLOW_MAP.get(m.group(1))
            if key:
                ci[key] = True
    return ci


def _load_override(root: Path) -> dict:
    override_path = root / C.PROFILE_REL
    obj = C.read_json(override_path)
    if obj is None:
        return {}
    for key in obj:
        if key not in OVERRIDE_KEYS:
            C.die(f"unknown key in {C.PROFILE_REL}: {key}", C.USAGE)
    return obj


def _trunk_cmd(root: Path) -> str:
    """Repo-local launcher when present, else the global CLI."""
    return "./trunk check --no-fix" if (root / "trunk").is_file() else "trunk check --no-fix"


def _build_checks(root: Path, kind: str, make_targets: list[str], has: dict) -> list[dict]:
    checks: list[dict] = []
    if "test" in make_targets:
        checks.append({"name": "test", "cmd": "make test"})
    if kind == "addon":
        if has["i18n"]:
            if "all_checks" in make_targets:
                checks.append({"name": "i18n", "cmd": "make all_checks"})
            elif "i18n_check" in make_targets:
                checks.append({"name": "i18n", "cmd": "make i18n_check"})
        if "toc_check" in make_targets:
            checks.append({"name": "toc", "cmd": "make toc_check"})
        if "check_untracked_files" in make_targets:
            checks.append({"name": "untracked", "cmd": "make check_untracked_files"})
    if has["trunk"]:
        checks.append({"name": "trunk", "cmd": _trunk_cmd(root)})
    return checks


def build_profile(root: Path) -> dict:
    """Detect the repo at *root* and return the repo_profile.py schema dict."""
    root = Path(root).resolve()

    is_go_tool = (root / "go.mod").is_file()
    addon_dir = None if is_go_tool else _find_addon_dir(root)
    has_busted = (root / ".busted").is_file()
    make_targets = _parse_make_targets(root / "Makefile")
    generic_spec_dir = _find_generic_spec_dir(root)
    has_tests = has_busted or (generic_spec_dir is not None and "test" in make_targets)

    if is_go_tool:
        kind = "go-tool"
    elif addon_dir is not None:
        kind = "addon"
    elif has_tests:
        kind = "lib"
    else:
        kind = "unknown"

    toc = None
    interfaces: list[int] = []
    flavors: list[dict] = []
    spec_dir = None
    locale_dir = None
    has_i18n = False

    if kind == "addon" and addon_dir is not None:
        addon_path = root / addon_dir
        toc_path = addon_path / f"{addon_dir}.toc"
        toc = _to_posix(root, toc_path)
        interfaces = _parse_interfaces(toc_path)
        for i in interfaces:
            f = C.flavor_for(i)
            flavors.append(
                {"interface": i, "name": f["name"], "ref": f["ref"], "product": f["product"]}
            )
        spec_candidate = root / f"{addon_dir}_spec"
        if spec_candidate.is_dir():
            spec_dir = _to_posix(root, spec_candidate)
        locale_candidate = addon_path / "locale"
        if locale_candidate.is_dir():
            locale_dir = _to_posix(root, locale_candidate)
            has_i18n = (locale_candidate / "enUS.lua").is_file()
    elif generic_spec_dir is not None:
        spec_dir = generic_spec_dir

    has_trunk = _has_trunk(root)

    has = {
        "tests": has_tests,
        "i18n": has_i18n,
        "trunk": has_trunk,
        "tocCheck": "toc_check" in make_targets,
        "untrackedCheck": "check_untracked_files" in make_targets,
        "allChecks": "all_checks" in make_targets,
        "wbtBinary": shutil.which("wow-build-tools") is not None,
    }

    ci = _detect_ci(root)

    if kind == "addon":
        guard_paths = [f"{addon_dir}/"]
    elif kind == "go-tool":
        guard_paths = ["cmd/", "internal/", "go.mod", "go.sum"]
    else:
        guard_paths = []

    checks = _build_checks(root, kind, make_targets, has)
    locale_version_style = ""

    overrides = _load_override(root)

    if "kind" in overrides:
        kind = overrides["kind"]
    if "addonDir" in overrides:
        addon_dir = overrides["addonDir"]
    if "checks" in overrides:
        checks = overrides["checks"]
    if "guardPaths" in overrides:
        guard_paths = overrides["guardPaths"]
    if "localeVersionStyle" in overrides:
        locale_version_style = overrides["localeVersionStyle"]
    if "skipChecks" in overrides:
        skip = set(overrides["skipChecks"])
        checks = [c for c in checks if c.get("name") not in skip]

    return {
        "root": str(root),
        "kind": kind,
        "addonDir": addon_dir,
        "toc": toc,
        "specDir": spec_dir,
        "localeDir": locale_dir,
        "interfaces": interfaces,
        "flavors": flavors,
        "makeTargets": make_targets,
        "has": has,
        "ci": ci,
        "checks": checks,
        "guardPaths": guard_paths,
        "localeVersionStyle": locale_version_style,
        "overrides": overrides,
    }


def _print_text(profile: dict) -> None:
    print(f"root: {profile['root']}")
    print(f"kind: {profile['kind']}")
    print(f"addonDir: {profile['addonDir']}")
    if profile["flavors"]:
        names = ", ".join(f["name"] for f in profile["flavors"])
        print(f"flavors: {names}")
    else:
        print("flavors: (none)")
    print("has:")
    for key, value in profile["has"].items():
        print(f"  {key}: {value}")
    print("checks:")
    if profile["checks"]:
        for check in profile["checks"]:
            print(f"  {check['name']}: {check['cmd']}")
    else:
        print("  (none)")


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect repo capabilities and emit JSON profile.")
    parser.add_argument("--root", type=Path, default=None)
    fmt = parser.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--text", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else C.repo_root(Path.cwd())
    profile = build_profile(root)
    C.emit(profile, args.json, _print_text)
    return C.OK


if __name__ == "__main__":
    sys.exit(main())
