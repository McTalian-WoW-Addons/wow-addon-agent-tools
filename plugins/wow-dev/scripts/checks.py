# /// script
# requires-python = ">=3.12"
# ///
"""Run a repo's detected local checks in canonical order and record the result.

See docs/contract.md for the profile schema and PLAN.md §4.2 for the CLI
contract. The record this writes (``.claude/.last-checks.json``) is read by
``guard_commit.py`` before allowing a commit that touches packaged files.
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _tail(text: str, n: int = 40) -> str:
    lines = text.splitlines()
    return "\n".join(lines[-n:])


def _run_check(check: dict, root: Path) -> dict:
    start = time.monotonic()
    proc = C.run(check["cmd"], cwd=root)
    elapsed = time.monotonic() - start
    status = "PASS" if proc.returncode == 0 else "FAIL"
    combined = (proc.stdout or "") + (proc.stderr or "")
    return {
        "name": check["name"],
        "cmd": check["cmd"],
        "status": status,
        "seconds": round(elapsed, 1),
        "tail": _tail(combined),
    }


def _print_result(result: dict) -> None:
    print(f"{result['status']} {result['name']} ({result['cmd']}) {result['seconds']:.1f}s")
    if result["status"] != "PASS" and result["tail"]:
        print(result["tail"])


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the repo's detected local checks in canonical order."
    )
    parser.add_argument("--root", type=Path, default=None)
    parser.add_argument("--only", type=str, default=None, metavar="NAME,NAME")
    parser.add_argument("--keep-going", action="store_true")
    parser.add_argument("--fmt", action="store_true")
    parser.add_argument("--no-record", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = args.root.resolve() if args.root else C.repo_root(Path.cwd())
    profile = C.load_profile(root)
    all_checks = profile["checks"]

    if not all_checks:
        print("No checks detected.")
        return C.OK

    valid_names = [c["name"] for c in all_checks]
    only_used = args.only is not None
    selected = all_checks
    if only_used:
        requested = [n.strip() for n in args.only.split(",") if n.strip()]
        unknown = [n for n in requested if n not in valid_names]
        if unknown:
            C.die(
                f"unknown check name: {', '.join(unknown)}; valid: {', '.join(valid_names)}",
                C.USAGE,
            )
        selected = [c for c in all_checks if c["name"] in requested]

    if args.fmt and profile["has"]["trunk"]:
        C.run(["./trunk", "fmt"], cwd=root)

    results: list[dict] = []
    ok = True
    for check in selected:
        result = _run_check(check, root)
        results.append(result)
        if not args.json:
            _print_result(result)
        if result["status"] != "PASS":
            ok = False
            if not args.keep_going:
                break

    recorded = False
    if not only_used and not args.no_record:
        record = {
            "ts": _now_iso(),
            "ok": ok,
            "indexHash": C.index_hash(root, profile["guardPaths"]),
            "checks": [r["name"] for r in results],
        }
        C.write_json(root / C.RECORD_REL, record)
        recorded = True

    obj = {"ok": ok, "checks": results, "recorded": recorded}
    C.emit(obj, args.json, lambda _o: None)

    return C.OK if ok else C.FAIL


if __name__ == "__main__":
    sys.exit(main())
