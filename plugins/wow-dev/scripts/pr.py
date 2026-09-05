# /// script
# requires-python = ">=3.12"
# ///
"""PR mechanics: commit typing, title lint, merge-label read-back, PR creation.

See docs/contract.md for the repo_profile.py schema this depends on, and
docs/agent/decisions.md-style rationale (none lives here on purpose).
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

TITLE_RE = re.compile(
    r"""^(feat|fix|perf|locale|toc|build|chore|ci|docs|refactor|style|test|revert)"""
    r"""(\([a-z0-9._-]+\))?!?: [a-z0-9`'"].*$"""
)

_OK_CONCLUSIONS = {"SUCCESS", "NEUTRAL", "SKIPPED"}
_BLOCKING_MISMATCH = {"unparsable", "publishing-type-without-packaged-change", "fixup-or-wip"}


def _is_packaged_path(path: str, guard_paths: list[str]) -> bool:
    for g in guard_paths:
        if g.endswith("/"):
            if path == g[:-1] or path.startswith(g):
                return True
        elif path == g:
            return True
    return False


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def _changed_files(args, root: Path) -> list[str]:
    if args.range_:
        return _lines(C.git("diff", "--name-only", args.range_, cwd=root))
    if args.files:
        return list(args.files)
    return _lines(C.git("diff", "--cached", "--name-only", cwd=root))


def _classify(files: list[str], guard_paths: list[str]) -> tuple[list[str], list[str]]:
    packaged_files = [f for f in files if _is_packaged_path(f, guard_paths)]
    other_files = [f for f in files if not _is_packaged_path(f, guard_paths)]
    return packaged_files, other_files


def cmd_touches_packaged(args, root: Path) -> int:
    profile = C.load_profile(root)
    guard_paths = profile["guardPaths"]
    files = _changed_files(args, root)
    packaged_files, other_files = _classify(files, guard_paths)

    packaged = None if not guard_paths else bool(packaged_files)
    allowed_types = list(C.ALL_TYPES) if packaged else list(C.DEV_TYPES)

    result = {
        "packaged": packaged,
        "packagedFiles": packaged_files,
        "otherFiles": other_files,
        "allowedTypes": allowed_types,
    }

    def _text(obj: dict) -> None:
        print(f"packaged: {obj['packaged']}")
        for f in obj["packagedFiles"]:
            print(f"  packaged: {f}")
        for f in obj["otherFiles"]:
            print(f"  other: {f}")
        print("allowedTypes: " + ", ".join(obj["allowedTypes"]))

    C.emit(result, args.json, _text)
    return C.OK


def _lint_title(title: str) -> dict:
    if "\n" in title or "\r" in title:
        return {"ok": False, "type": None, "errors": ["multi-line title"]}
    m = TITLE_RE.match(title)
    if not m:
        return {
            "ok": False,
            "type": None,
            "errors": ["does not match required format: type(scope)?: description"],
        }
    errors: list[str] = []
    if len(title) > 72:
        errors.append("warning: title exceeds 72 characters")
    return {"ok": True, "type": m.group(1), "errors": errors}


def cmd_lint_title(args, root: Path) -> int:
    result = _lint_title(args.title)

    def _text(obj: dict) -> None:
        print(f"{'ok' if obj['ok'] else 'FAIL'}: type={obj['type']}")
        for e in obj["errors"]:
            print(f"  {e}")

    C.emit(result, args.json, _text)
    return C.OK if result["ok"] else C.FAIL


def _commit_touches_packaged(sha: str, root: Path, guard_paths: list[str]) -> bool | None:
    if not guard_paths:
        return None
    text = C.git("diff-tree", "--no-commit-id", "--name-only", "-r", "--root", sha, cwd=root)
    files = _lines(text)
    return any(_is_packaged_path(f, guard_paths) for f in files)


def cmd_lint_commits(args, root: Path) -> int:
    profile = C.load_profile(root)
    guard_paths = profile["guardPaths"]

    proc = C.run(["git", "log", "--format=%H%x1f%s", args.range], cwd=root)
    commits = []
    for line in _lines(proc.stdout):
        sha, _, subject = line.partition("\x1f")
        m = TITLE_RE.match(subject)
        type_ = m.group(1) if m else None
        is_fixup = subject.startswith(("fixup!", "squash!", "wip"))
        packaged = _commit_touches_packaged(sha, root, guard_paths)
        ok = type_ is not None

        mismatch: list[str] = []
        if is_fixup:
            mismatch.append("fixup-or-wip")
        elif not ok:
            mismatch.append("unparsable")
        if ok:
            if type_ in C.PUBLISHING_TYPES and packaged is False:
                mismatch.append("publishing-type-without-packaged-change")
            elif type_ in C.DEV_TYPES and packaged is True:
                mismatch.append("dev-type-with-packaged-change")

        commits.append(
            {
                "sha": sha,
                "subject": subject,
                "type": type_,
                "ok": ok,
                "packaged": packaged,
                "mismatch": mismatch,
            }
        )

    rebase_valid = all(not (_BLOCKING_MISMATCH & set(c["mismatch"])) for c in commits)
    types_present = {c["type"] for c in commits if c["type"]}
    publishes = bool(types_present & set(C.PUBLISHING_TYPES))
    if "feat" in types_present:
        release_type = "minor"
    elif types_present & (set(C.PUBLISHING_TYPES) - {"feat"}):
        release_type = "patch"
    else:
        release_type = "none"

    result = {
        "commits": commits,
        "rebaseValid": rebase_valid,
        "publishes": publishes,
        "releaseType": release_type,
    }

    def _text(obj: dict) -> None:
        for c in obj["commits"]:
            status = "ok" if c["ok"] else "FAIL"
            mismatch = ", ".join(c["mismatch"]) if c["mismatch"] else "-"
            print(
                f"{c['sha'][:7]} {status} type={c['type']} packaged={c['packaged']} "
                f"mismatch={mismatch} {c['subject']}"
            )
        print(f"rebaseValid: {obj['rebaseValid']}")
        print(f"publishes: {obj['publishes']}")
        print(f"releaseType: {obj['releaseType']}")

    C.emit(result, args.json, _text)
    return C.OK if rebase_valid else C.FAIL


def cmd_labels(args, root: Path) -> int:
    proc = C.run(
        ["gh", "pr", "view", str(args.pr_number), "--json", "labels,title,statusCheckRollup"],
        cwd=root,
    )
    if proc.returncode != 0:
        C.die(f"gh pr view failed: {proc.stderr.strip()}", C.FAIL)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        C.die("gh pr view returned invalid JSON", C.FAIL)

    label_names = {label.get("name") for label in data.get("labels", [])}
    squash_valid = "squash-valid" in label_names
    rebase_valid = "rebase-valid" in label_names

    release = None
    for name in label_names:
        if name and name.startswith("release:"):
            release = name.split("release:", 1)[1]
            break

    rollup = data.get("statusCheckRollup") or []
    if not rollup:
        checks_passed = None
    else:
        checks_passed = all(entry.get("conclusion") in _OK_CONCLUSIONS for entry in rollup)

    mismatch_suspected = bool(checks_passed) and not squash_valid and not rebase_valid

    result = {
        "squashValid": squash_valid,
        "rebaseValid": rebase_valid,
        "release": release,
        "checksPassed": checks_passed,
        "mismatchSuspected": mismatch_suspected,
    }

    def _text(obj: dict) -> None:
        for key, value in obj.items():
            print(f"{key}: {value}")

    C.emit(result, args.json, _text)
    return C.OK


def cmd_create(args, root: Path) -> int:
    if not args.body_file.is_file():
        C.die(f"body file not found: {args.body_file}", C.USAGE)

    lint = _lint_title(args.title)
    if not lint["ok"]:
        C.die(f"invalid PR title: {'; '.join(lint['errors'])}", C.FAIL)

    create_cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        args.title,
        "--body-file",
        str(args.body_file),
        "--base",
        args.base,
    ]
    if args.draft:
        create_cmd.append("--draft")
    proc = C.run(create_cmd, cwd=root)
    if proc.returncode != 0:
        C.die(f"gh pr create failed: {proc.stderr.strip()}", C.FAIL)

    view = C.run(["gh", "pr", "view", "--json", "number,title,url"], cwd=root)
    if view.returncode != 0:
        C.die(f"gh pr view failed: {view.stderr.strip()}", C.FAIL)
    try:
        data = json.loads(view.stdout)
    except json.JSONDecodeError:
        C.die("gh pr view returned invalid JSON", C.FAIL)

    if data.get("title") != args.title:
        C.die(
            f"created PR title mismatch: expected {args.title!r}, got {data.get('title')!r}",
            C.FAIL,
        )

    def _text(obj: dict) -> None:
        print(f"PR #{obj.get('number')}: {obj.get('title')}")
        print(obj.get("url", ""))

    C.emit(data, args.json, _text)
    return C.OK


def _common_parser() -> argparse.ArgumentParser:
    """A fresh --root/--json/--text parser, usable as a parent on the top-level
    parser and on every subparser, so ``--root``/``--json`` work whether given
    before or after the subcommand name."""
    p = argparse.ArgumentParser(add_help=False)
    p.add_argument("--root", type=Path, default=None)
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--text", action="store_true")
    return p


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="pr.py",
        description="Commit typing, title lint, merge labels, PR creation.",
        parents=[_common_parser()],
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_tp = sub.add_parser("touches-packaged", parents=[_common_parser()])
    g = p_tp.add_mutually_exclusive_group()
    g.add_argument("--staged", action="store_true")
    g.add_argument("--range", dest="range_", metavar="A..B")
    g.add_argument("--files", nargs="+", metavar="FILE")

    p_lt = sub.add_parser("lint-title", parents=[_common_parser()])
    p_lt.add_argument("title")

    p_lc = sub.add_parser("lint-commits", parents=[_common_parser()])
    p_lc.add_argument("range", metavar="A..B")

    p_lb = sub.add_parser("labels", parents=[_common_parser()])
    p_lb.add_argument("pr_number", type=int)

    p_cr = sub.add_parser("create", parents=[_common_parser()])
    p_cr.add_argument("--title", required=True)
    p_cr.add_argument("--body-file", required=True, type=Path)
    p_cr.add_argument("--base", default="main")
    p_cr.add_argument("--draft", action="store_true")

    args = parser.parse_args()
    root = args.root.resolve() if args.root else C.repo_root(Path.cwd())

    if args.command == "touches-packaged":
        return cmd_touches_packaged(args, root)
    if args.command == "lint-title":
        return cmd_lint_title(args, root)
    if args.command == "lint-commits":
        return cmd_lint_commits(args, root)
    if args.command == "labels":
        return cmd_labels(args, root)
    if args.command == "create":
        return cmd_create(args, root)
    return C.USAGE  # pragma: no cover - argparse `required=True` prevents this


if __name__ == "__main__":
    sys.exit(main())
