# /// script
# requires-python = ">=3.12"
# ///
"""Look up WoW API symbols, events and constants across wow-ui-source flavor refs.

Grep/show only: never fetches, checks out, or switches branches in the
wow-ui-source checkout. See docs/contract.md and PLAN.md §4.2 for the CLI
contract and skills/wow-api/SKILL.md for the commands the model runs.

Source root: $WOW_UI_SOURCE, default ~/code/wow-ui-source. Refs come from
_common.FLAVORS (retail/mop_classic/classic_era/tbc_anniversary); --ref adds
an arbitrary extra ref (ptr, ptr2, beta, classic_ptr, classic_beta,
classic_era_ptr, ...).
"""

import argparse
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common as C

DOC_DIR = "Interface/AddOns/Blizzard_APIDocumentationGenerated"
DEPRECATED_DIR = "Interface/AddOns/Blizzard_Deprecated"
USAGE_ROOT = "Interface/AddOns"

_NS_RE = re.compile(r"^(C_[A-Za-z0-9_]+|Enum)\.(.+)$")
_NAMESPACE_LINE_RE = re.compile(r'Namespace\s*=\s*"([^"]+)"')
_TYPE_EVENT_RE = re.compile(r'Type\s*=\s*"Event"')
_NAME_LINE_RE = re.compile(r'Name\s*=\s*"([^"]+)"')
_LITERAL_NAME_RE = re.compile(r'LiteralName\s*=\s*"([^"]+)"')


# --------------------------------------------------------------------------
# Source / git plumbing
# --------------------------------------------------------------------------


def resolve_source() -> Path:
    """Return the wow-ui-source checkout root, or exit USAGE naming the env var."""
    raw = os.environ.get("WOW_UI_SOURCE", str(Path.home() / "code" / "wow-ui-source"))
    src = Path(raw).expanduser()
    if not (src / ".git").exists():
        C.die(
            f"WOW_UI_SOURCE not found or not a git repository: {src} (set $WOW_UI_SOURCE)",
            C.USAGE,
        )
    return src.resolve()


def ref_exists(src: Path, ref: str) -> bool:
    proc = C.run(["git", "rev-parse", "--verify", "--quiet", ref], cwd=src)
    return proc.returncode == 0


def is_local_branch(src: Path, ref: str) -> bool:
    proc = C.run(["git", "show-ref", "--quiet", "--verify", f"refs/heads/{ref}"], cwd=src)
    return proc.returncode == 0


def git_log_date(src: Path, ref: str) -> str | None:
    proc = C.run(["git", "log", "-1", "--format=%ci", ref], cwd=src)
    if proc.returncode != 0 or not proc.stdout.strip():
        return None
    return proc.stdout.strip()


def rev_list_count(src: Path, range_expr: str) -> int | None:
    proc = C.run(["git", "rev-list", "--count", range_expr], cwd=src)
    if proc.returncode != 0:
        return None
    try:
        return int(proc.stdout.strip())
    except ValueError:
        return None


def git_show(src: Path, ref: str, path: str) -> str | None:
    proc = C.run(["git", "show", f"{ref}:{path}"], cwd=src)
    if proc.returncode != 0:
        return None
    return proc.stdout


def read_version_txt(src: Path, ref: str) -> str | None:
    text = git_show(src, ref, "version.txt")
    return text.strip() if text is not None else None


def git_grep(
    src: Path,
    ref: str,
    pattern: str,
    paths: list[str],
    *,
    fixed: bool = True,
) -> list[tuple[str, int, str]]:
    """Run ``git grep -n [-F|-E] -e pattern ref -- paths`` and parse hits.

    Returns a list of (path, line, content); [] when the ref has no matches
    (git grep exit 1) or any other error occurs.
    """
    cmd = ["git", "grep", "-n", "-F" if fixed else "-E", "-e", pattern, ref, "--", *paths]
    proc = C.run(cmd, cwd=src)
    if proc.returncode not in (0, 1):
        return []
    hits: list[tuple[str, int, str]] = []
    for line in proc.stdout.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4:
            continue
        _ref, path, lineno, content = parts
        try:
            lineno_i = int(lineno)
        except ValueError:
            continue
        hits.append((path, lineno_i, content))
    return hits


# --------------------------------------------------------------------------
# Symbol / Lua-table parsing
# --------------------------------------------------------------------------


def split_symbol(symbol: str) -> tuple[str | None, str]:
    """Split a ``C_Xxx.Fn`` or ``Enum.X`` symbol into (namespace, bare).

    A symbol with no such prefix (a bare function name or an event name)
    returns (None, symbol) unchanged.
    """
    m = _NS_RE.match(symbol)
    if m:
        return m.group(1), m.group(2)
    return None, symbol


def enclosing_namespace(text: str, line_no: int) -> str | None:
    """Return the nearest ``Namespace = "..."`` at or before *line_no* (1-indexed)."""
    lines = text.splitlines()
    for i in range(min(line_no, len(lines)) - 1, -1, -1):
        m = _NAMESPACE_LINE_RE.search(lines[i])
        if m:
            return m.group(1)
    return None


def find_block_bounds(text: str, line_no: int) -> tuple[int, int] | None:
    """Return the 0-indexed (start, end) line bounds of the ``{ ... }`` Lua
    table block enclosing *line_no* (1-indexed).

    Scans backward from line_no for the nearest line that is exactly an
    opening brace (Blizzard's generated docs put each table entry on its own
    ``{`` line), then counts braces forward to the matching close.
    """
    lines = text.splitlines()
    start_idx = None
    for i in range(min(line_no, len(lines)) - 1, -1, -1):
        if lines[i].strip() == "{":
            start_idx = i
            break
    if start_idx is None:
        return None
    depth = 0
    end_idx = None
    for i in range(start_idx, len(lines)):
        depth += lines[i].count("{") - lines[i].count("}")
        if depth == 0:
            end_idx = i
            break
    if end_idx is None:
        return None
    return start_idx, end_idx


def extract_balanced_table(text: str, line_no: int) -> str | None:
    """Return the ``{ ... }`` Lua table block enclosing *line_no* (1-indexed)."""
    bounds = find_block_bounds(text, line_no)
    if bounds is None:
        return None
    lines = text.splitlines()
    return "\n".join(lines[bounds[0] : bounds[1] + 1])


def dedupe_hits_by_block(
    hits: list[tuple[str, int, str]], read_file
) -> list[dict]:
    """Resolve raw grep hits to their enclosing Lua table block and keep only
    the first hit per (path, block) pair.

    Blizzard's generated docs have fields like ``LiteralName`` whose value
    line contains ``Name = "<value>"`` as a plain substring, so a fixed-string
    grep for ``Name = "<value>"`` can match twice inside the same table
    entry. Collapsing to one row per block avoids double-counting those.
    """
    seen: set[tuple[str, int]] = set()
    out: list[dict] = []
    for path, line, _content in hits:
        text = read_file(path)
        if text is None:
            continue
        bounds = find_block_bounds(text, line)
        if bounds is None:
            continue
        key = (path, bounds[0])
        if key in seen:
            continue
        seen.add(key)
        out.append(
            {
                "path": path,
                "line": line,
                "blockStart": bounds[0],
                "blockEnd": bounds[1],
                "text": text,
            }
        )
    return out


# --------------------------------------------------------------------------
# Flavor resolution
# --------------------------------------------------------------------------


def resolve_flavor_list(
    flavors_arg: str | None,
    repo_flavors: bool,
    root_arg: Path | None,
    extra_refs: list[str] | None,
) -> list[dict]:
    """Return an ordered, deduped list of {"name", "ref"} targets."""
    result: list[dict] = []
    if repo_flavors:
        root = root_arg.resolve() if root_arg else C.repo_root(Path.cwd())
        profile = C.load_profile(root)
        seen: set[str] = set()
        for f in profile["flavors"]:
            if f["name"] not in seen:
                seen.add(f["name"])
                result.append({"name": f["name"], "ref": f["ref"]})
    else:
        names: list[str] | None = None
        if flavors_arg and flavors_arg != "all":
            names = [n.strip() for n in flavors_arg.split(",") if n.strip()]
        if names is None:
            result = [{"name": f["name"], "ref": f["ref"]} for f in C.FLAVORS]
        else:
            by_name = {f["name"]: f for f in C.FLAVORS}
            for n in names:
                if n not in by_name:
                    C.die(f"unknown flavor: {n}", C.USAGE)
                result.append({"name": n, "ref": by_name[n]["ref"]})

    if extra_refs:
        existing = {r["name"] for r in result}
        for r in extra_refs:
            if r not in existing:
                result.append({"name": r, "ref": r})
                existing.add(r)
    return result


# --------------------------------------------------------------------------
# branches
# --------------------------------------------------------------------------


def cmd_branches(args: argparse.Namespace) -> int:
    src = resolve_source()
    rows: list[dict] = []
    for f in C.FLAVORS:
        ref = f["ref"]
        exists = ref_exists(src, ref)
        last_commit = None
        version = None
        behind = None
        if exists:
            last_commit = git_log_date(src, ref)
            version = read_version_txt(src, ref)
            if is_local_branch(src, ref):
                behind = rev_list_count(src, f"{ref}..origin/{ref}")
        rows.append(
            {
                "name": f["name"],
                "ref": ref,
                "exists": exists,
                "lastCommit": last_commit,
                "version": version,
                "behind": behind,
            }
        )
    obj = {"root": str(src), "branches": rows}

    def _text(o: dict) -> None:
        for row in o["branches"]:
            line = f"{row['name']:16} ref={row['ref']:32} exists={row['exists']}"
            if row["exists"]:
                line += f" lastCommit={row['lastCommit']}"
                if row["version"]:
                    line += f" version={row['version']}"
                if row["behind"] is not None:
                    line += f" behind={row['behind']}"
            print(line)

    C.emit(obj, args.json, _text)
    return C.OK


# --------------------------------------------------------------------------
# find
# --------------------------------------------------------------------------


def _find_one_flavor(
    src: Path, flavor: dict, bare: str, namespace: str | None, usages: int
) -> dict:
    ref = flavor["ref"]
    exists = ref_exists(src, ref)
    result = {
        "flavor": flavor["name"],
        "ref": ref,
        "exists": exists,
        "present": False,
        "namespace": None,
        "docHits": [],
        "deprecated": False,
        "deprecatedHits": [],
        "usageHits": [],
    }
    if not exists:
        return result

    file_cache: dict[str, str | None] = {}

    def read_file(path: str) -> str | None:
        if path not in file_cache:
            file_cache[path] = git_show(src, ref, path)
        return file_cache[path]

    doc_hits = git_grep(src, ref, f'Name = "{bare}"', [DOC_DIR], fixed=True)
    kept_hits = []
    found_namespace = None
    for block in dedupe_hits_by_block(doc_hits, read_file):
        ns = enclosing_namespace(block["text"], block["line"])
        if namespace is not None and ns != namespace:
            continue
        kept_hits.append({"path": block["path"], "line": block["line"], "namespace": ns})
        if found_namespace is None:
            found_namespace = ns

    result["docHits"] = kept_hits
    result["present"] = len(kept_hits) > 0
    result["namespace"] = found_namespace

    deprecated_hits = git_grep(src, ref, f'Name = "{bare}"', [DEPRECATED_DIR], fixed=True)
    deprecated_blocks = dedupe_hits_by_block(deprecated_hits, read_file)
    result["deprecated"] = len(deprecated_blocks) > 0
    result["deprecatedHits"] = [
        {"path": b["path"], "line": b["line"]} for b in deprecated_blocks
    ]

    if usages > 0:
        pattern = rf"{re.escape(bare)}\(|\b{re.escape(bare)}\b"
        usage_hits = git_grep(
            src,
            ref,
            pattern,
            [USAGE_ROOT, f":!{DOC_DIR}", f":!{DEPRECATED_DIR}"],
            fixed=False,
        )
        result["usageHits"] = [
            {"path": p, "line": l} for p, l, _c in usage_hits[:usages]
        ]

    return result


def _summary_line(results: list[dict]) -> str:
    present = [r["flavor"] for r in results if r["present"]]
    absent = [r["flavor"] for r in results if not r["present"]]
    deprecated = [r["flavor"] for r in results if r["deprecated"]]
    return (
        f"present: {', '.join(present) or '(none)'}; "
        f"absent: {', '.join(absent) or '(none)'}; "
        f"deprecated-in: {', '.join(deprecated) or '(none)'}"
    )


def cmd_find(args: argparse.Namespace) -> int:
    src = resolve_source()
    namespace, bare = split_symbol(args.symbol)
    flavors = resolve_flavor_list(args.flavors, args.repo_flavors, args.root, args.ref)

    results = [_find_one_flavor(src, f, bare, namespace, args.usages) for f in flavors]
    summary = _summary_line(results)

    obj = {
        "root": str(src),
        "symbol": args.symbol,
        "namespace": namespace,
        "name": bare,
        "usages": args.usages,
        "flavors": results,
        "summary": summary,
    }

    def _text(o: dict) -> None:
        header = f"symbol: {o['symbol']}"
        if o["namespace"]:
            header += f" (namespace={o['namespace']})"
        print(header)
        for f in o["flavors"]:
            if not f["exists"]:
                status = "missing-ref"
            elif f["present"]:
                status = "present"
            else:
                status = "absent"
            print(f"  {f['flavor']:16} ref={f['ref']:32} {status}")
            for h in f["docHits"]:
                print(f"    doc: {h['path']}:{h['line']}")
            if f["deprecated"]:
                print(f"    deprecated: {len(f['deprecatedHits'])} hit(s)")
            for u in f["usageHits"]:
                print(f"    usage: {u['path']}:{u['line']}")
        print(o["summary"])

    C.emit(obj, args.json, _text)
    return C.OK


# --------------------------------------------------------------------------
# show
# --------------------------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    src = resolve_source()
    namespace, bare = split_symbol(args.symbol)

    if args.ref:
        ref = args.ref
        flavor_name = args.ref
    else:
        flavor_name = args.flavor or "retail"
        by_name = {f["name"]: f for f in C.FLAVORS}
        if flavor_name not in by_name:
            C.die(f"unknown flavor: {flavor_name}", C.USAGE)
        ref = by_name[flavor_name]["ref"]

    if not ref_exists(src, ref):
        obj = {
            "root": str(src),
            "symbol": args.symbol,
            "flavor": flavor_name,
            "ref": ref,
            "exists": False,
            "found": False,
        }
        C.emit(obj, args.json, lambda _o: print(f"ref not found: {ref}", file=sys.stderr))
        return C.FAIL

    doc_hits = git_grep(src, ref, f'Name = "{bare}"', [DOC_DIR], fixed=True)
    chosen = None
    for path, line, _content in doc_hits:
        text = git_show(src, ref, path)
        if text is None:
            continue
        ns = enclosing_namespace(text, line)
        if namespace is not None and ns != namespace:
            continue
        chosen = (path, line, text, ns)
        break

    if chosen is None:
        obj = {
            "root": str(src),
            "symbol": args.symbol,
            "flavor": flavor_name,
            "ref": ref,
            "exists": True,
            "found": False,
        }

        def _text_missing(_o: dict) -> None:
            print(f"not found: {args.symbol} at {flavor_name} ({ref})", file=sys.stderr)

        C.emit(obj, args.json, _text_missing)
        return C.FAIL

    path, line, text, ns = chosen
    block = extract_balanced_table(text, line)

    obj = {
        "root": str(src),
        "symbol": args.symbol,
        "flavor": flavor_name,
        "ref": ref,
        "exists": True,
        "found": True,
        "path": path,
        "line": line,
        "namespace": ns,
        "block": block or "",
    }

    def _text(o: dict) -> None:
        print(f"# {o['symbol']} — {o['flavor']} ({o['ref']}) — {o['path']}:{o['line']}")
        print(o["block"])

    C.emit(obj, args.json, _text)
    return C.OK


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------


def cmd_events(args: argparse.Namespace) -> int:
    src = resolve_source()
    flavors = resolve_flavor_list(args.flavors, False, None, args.ref)

    results: list[dict] = []
    for flavor in flavors:
        ref = flavor["ref"]
        exists = ref_exists(src, ref)
        events: list[dict] = []
        if exists:
            hits = git_grep(src, ref, f'Name = "{args.pattern}"', [DOC_DIR], fixed=False)
            file_cache: dict[str, str | None] = {}

            def read_file(path: str) -> str | None:
                if path not in file_cache:
                    file_cache[path] = git_show(src, ref, path)
                return file_cache[path]

            for hit_block in dedupe_hits_by_block(hits, read_file):
                block = "\n".join(
                    hit_block["text"].splitlines()[
                        hit_block["blockStart"] : hit_block["blockEnd"] + 1
                    ]
                )
                if not _TYPE_EVENT_RE.search(block):
                    continue
                name_match = _NAME_LINE_RE.search(block)
                literal_match = _LITERAL_NAME_RE.search(block)
                events.append(
                    {
                        "name": name_match.group(1) if name_match else None,
                        "literalName": literal_match.group(1) if literal_match else None,
                        "path": hit_block["path"],
                        "line": hit_block["line"],
                    }
                )
        results.append(
            {"flavor": flavor["name"], "ref": ref, "exists": exists, "events": events}
        )

    summary = "; ".join(f"{r['flavor']}={len(r['events'])}" for r in results)
    obj = {"root": str(src), "pattern": args.pattern, "flavors": results, "summary": summary}

    def _text(o: dict) -> None:
        print(f"pattern: {o['pattern']}")
        for f in o["flavors"]:
            status = "missing-ref" if not f["exists"] else f"{len(f['events'])} event(s)"
            print(f"  {f['flavor']:16} ref={f['ref']:32} {status}")
            for e in f["events"]:
                label = e["literalName"] or e["name"]
                print(f"    {label} — {e['path']}:{e['line']}")
        print(o["summary"])

    C.emit(obj, args.json, _text)
    return C.OK


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _add_json_flag(p: argparse.ArgumentParser) -> None:
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("--json", action="store_true")
    fmt.add_argument("--text", action="store_true")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Look up WoW API symbols/events across wow-ui-source flavor refs."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_branches = sub.add_parser("branches", help="Per-flavor ref freshness")
    _add_json_flag(p_branches)
    p_branches.set_defaults(func=cmd_branches)

    p_find = sub.add_parser("find", help="Presence/deprecation/usages of a symbol")
    p_find.add_argument("symbol")
    p_find.add_argument("--flavors", default=None, metavar="all|a,b,c")
    p_find.add_argument("--repo-flavors", action="store_true")
    p_find.add_argument("--usages", type=int, default=0, metavar="N")
    p_find.add_argument("--root", type=Path, default=None)
    p_find.add_argument("--ref", action="append", default=None, metavar="REF")
    _add_json_flag(p_find)
    p_find.set_defaults(func=cmd_find)

    p_show = sub.add_parser("show", help="Print the doc table for a symbol")
    p_show.add_argument("symbol")
    p_show.add_argument("--flavor", default=None)
    p_show.add_argument("--ref", default=None, metavar="REF")
    _add_json_flag(p_show)
    p_show.set_defaults(func=cmd_show)

    p_events = sub.add_parser("events", help="Events whose name matches a pattern")
    p_events.add_argument("pattern")
    p_events.add_argument("--flavors", default=None, metavar="all|a,b,c")
    p_events.add_argument("--ref", action="append", default=None, metavar="REF")
    _add_json_flag(p_events)
    p_events.set_defaults(func=cmd_events)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
