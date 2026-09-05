"""Tests for wow_api.py: grep/show WoW API symbols across wow-ui-source refs.

A synthetic mini "wow-ui-source" repo is built locally (see
_build_wow_ui_source below) so most tests never touch the real checkout.
A handful of tests exercise the real ~/code/wow-ui-source and are skipped
when it is not present (_helpers.wow_ui_source_available()).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import _helpers

SCRIPTS_DIR = _helpers.SCRIPTS_DIR

LIVE_DOC = """FooAPI = {
\t{
\t\tName = "C_Foo",
\t\tType = "System",
\t\tNamespace = "C_Foo",
\t\tFunctions = {
\t\t\t{
\t\t\t\tName = "Bar",
\t\t\t\tType = "Function",
\t\t\t\tArguments = {
\t\t\t\t\t{ Name = "id", Type = "number" },
\t\t\t\t},
\t\t\t\tReturns = {
\t\t\t\t\t{ Name = "result", Type = "bool" },
\t\t\t\t},
\t\t\t},
\t\t},
\t\tEvents = {
\t\t\t{
\t\t\t\tName = "FOO_UPDATED",
\t\t\t\tType = "Event",
\t\t\t\tLiteralName = "FOO_UPDATED",
\t\t\t\tPayload = {
\t\t\t\t\t{ Name = "id", Type = "number" },
\t\t\t\t},
\t\t\t},
\t\t},
\t},
}
"""

CLASSIC_DOC = """FooAPI = {
\t{
\t\tName = "C_Foo",
\t\tType = "System",
\t\tNamespace = "C_Foo",
\t\tFunctions = {
\t\t},
\t\tEvents = {
\t\t\t{
\t\t\t\tName = "FOO_UPDATED",
\t\t\t\tType = "Event",
\t\t\t\tLiteralName = "FOO_UPDATED",
\t\t\t},
\t\t},
\t},
}
"""

DEPRECATED_DOC = """DeprecatedFooAPI = {
\t{
\t\tName = "C_Foo",
\t\tType = "System",
\t\tNamespace = "C_Foo",
\t\tFunctions = {
\t\t\t{
\t\t\t\tName = "Bar",
\t\t\t\tType = "Function",
\t\t\t\tDocumentation = { "Deprecated, use C_Foo.NewBar instead." },
\t\t\t},
\t\t},
\t},
}
"""

USAGE_LUA = """local ok = C_Foo.Bar(42)
print(Bar)
"""


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=str(root),
        check=True,
        capture_output=True,
        text=True,
    )


def _write(root: Path, rel: str, content: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _build_wow_ui_source() -> Path:
    """Build a throwaway repo shaped like wow-ui-source: branches ``live`` and
    ``classic`` (matching the retail/mop_classic refs in _common.FLAVORS).

    ``live`` has the ``Bar`` function, the ``FOO_UPDATED`` event, a
    Blizzard_Deprecated doc entry for ``Bar``, and one usage site.
    ``classic`` forks off before the deprecated doc is added and has its
    ``Functions`` table emptied, so it keeps the event but lacks the
    function and the deprecation hit.
    """
    root = Path(tempfile.mkdtemp(prefix="wow-ui-source-test-"))
    _git(root, "init", "-q", "-b", "live")
    _git(root, "config", "user.name", "Test User")
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "commit.gpgsign", "false")

    _write(
        root,
        "Interface/AddOns/Blizzard_APIDocumentationGenerated/FooDocumentation.lua",
        LIVE_DOC,
    )
    _write(root, "Interface/AddOns/SomeAddon/Usage.lua", USAGE_LUA)
    _write(root, "version.txt", "1.0.0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "live: add Foo API")

    _git(root, "branch", "classic")
    _git(root, "checkout", "-q", "classic")
    _write(
        root,
        "Interface/AddOns/Blizzard_APIDocumentationGenerated/FooDocumentation.lua",
        CLASSIC_DOC,
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "classic: Bar not implemented")

    _git(root, "checkout", "-q", "live")
    _write(
        root,
        "Interface/AddOns/Blizzard_Deprecated/Deprecated_Foo.lua",
        DEPRECATED_DOC,
    )
    _write(root, "version.txt", "1.1.0\n")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "live: deprecate Bar")

    return root


def _run(*args: str, cwd: Path, wow_root: Path, extra_env: dict[str, str] | None = None):
    env = dict(os.environ)
    env["WOW_UI_SOURCE"] = str(wow_root)
    if extra_env:
        env.update(extra_env)
    return _helpers.run_script("wow_api.py", *args, cwd=cwd, env=env)


class SyntheticRepoTestCase(unittest.TestCase):
    def setUp(self):
        self.wow_root = _build_wow_ui_source()
        self.addCleanup(shutil.rmtree, self.wow_root, ignore_errors=True)


class TestFind(SyntheticRepoTestCase):
    def test_bare_symbol_present_absent_deprecated(self):
        cp = _run(
            "find",
            "Bar",
            "--flavors",
            "retail,mop_classic",
            "--usages",
            "5",
            "--json",
            cwd=self.wow_root,
            wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertEqual(obj["namespace"], None)
        self.assertEqual(obj["name"], "Bar")
        self.assertEqual(obj["summary"], "present: retail; absent: mop_classic; deprecated-in: retail")

        by_flavor = {f["flavor"]: f for f in obj["flavors"]}
        retail = by_flavor["retail"]
        self.assertTrue(retail["present"])
        self.assertTrue(retail["exists"])
        self.assertEqual(len(retail["docHits"]), 1)
        self.assertEqual(
            retail["docHits"][0]["path"],
            "Interface/AddOns/Blizzard_APIDocumentationGenerated/FooDocumentation.lua",
        )
        self.assertTrue(retail["deprecated"])
        self.assertEqual(len(retail["deprecatedHits"]), 1)
        self.assertEqual(len(retail["usageHits"]), 2)

        classic = by_flavor["mop_classic"]
        self.assertFalse(classic["present"])
        self.assertFalse(classic["deprecated"])

    def test_namespaced_symbol_matches(self):
        cp = _run(
            "find", "C_Foo.Bar", "--flavors", "retail", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        obj = _helpers.json_out(cp)
        retail = obj["flavors"][0]
        self.assertTrue(retail["present"])
        self.assertEqual(retail["namespace"], "C_Foo")

    def test_wrong_namespace_is_absent(self):
        cp = _run(
            "find", "C_Wrong.Bar", "--flavors", "retail", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        obj = _helpers.json_out(cp)
        retail = obj["flavors"][0]
        self.assertFalse(retail["present"])

    def test_missing_ref_marked_and_continues(self):
        cp = _run(
            "find", "Bar", "--flavors", "all", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        by_flavor = {f["flavor"]: f for f in obj["flavors"]}
        self.assertFalse(by_flavor["classic_era"]["exists"])
        self.assertFalse(by_flavor["classic_era"]["present"])
        self.assertFalse(by_flavor["tbc_anniversary"]["exists"])
        self.assertTrue(by_flavor["retail"]["exists"])

    def test_unknown_flavor_name_is_usage_error(self):
        cp = _run(
            "find", "Bar", "--flavors", "not_a_flavor",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 2, cp.stderr)
        self.assertIn("unknown flavor", cp.stderr)

    def test_repo_flavors_uses_profile(self):
        addon_root = _helpers.make_temp_repo(
            {
                "Addon/Addon.toc": "## Interface: 110100, 50504\n",
                "Addon/Core.lua": "return {}\n",
                "Makefile": "help:\n\t@echo help\n",
            },
            commits=[{"message": "chore: init"}],
        )
        self.addCleanup(shutil.rmtree, addon_root, ignore_errors=True)
        cp = _run(
            "find", "Bar", "--repo-flavors", "--root", str(addon_root), "--json",
            cwd=addon_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        names = [f["flavor"] for f in obj["flavors"]]
        self.assertEqual(names, ["retail", "mop_classic"])

    def test_text_mode_prints_summary(self):
        cp = _run(
            "find", "Bar", "--flavors", "retail",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("present: retail", cp.stdout)


class TestShow(SyntheticRepoTestCase):
    def test_shows_balanced_table_with_arguments(self):
        cp = _run(
            "show", "C_Foo.Bar", "--flavor", "retail", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertTrue(obj["found"])
        self.assertIn("Arguments", obj["block"])
        self.assertIn('Name = "Bar"', obj["block"])
        self.assertIn('Returns', obj["block"])
        # Balanced: opens and closes evenly.
        self.assertEqual(obj["block"].count("{"), obj["block"].count("}"))

    def test_text_mode_prints_block(self):
        cp = _run(
            "show", "C_Foo.Bar", "--flavor", "retail",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("Arguments", cp.stdout)

    def test_absent_on_classic_is_fail(self):
        cp = _run(
            "show", "C_Foo.Bar", "--flavor", "mop_classic", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 1, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertTrue(obj["exists"])
        self.assertFalse(obj["found"])

    def test_missing_ref_is_fail(self):
        cp = _run(
            "show", "C_Foo.Bar", "--flavor", "classic_era", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 1, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertFalse(obj["exists"])

    def test_ad_hoc_ref(self):
        cp = _run(
            "show", "C_Foo.Bar", "--ref", "live", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertTrue(obj["found"])
        self.assertEqual(obj["flavor"], "live")


class TestEvents(SyntheticRepoTestCase):
    def test_event_found_and_typed(self):
        cp = _run(
            "events", "FOO_UPDATED", "--flavors", "retail,mop_classic", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        by_flavor = {f["flavor"]: f for f in obj["flavors"]}
        self.assertEqual(len(by_flavor["retail"]["events"]), 1)
        self.assertEqual(by_flavor["retail"]["events"][0]["name"], "FOO_UPDATED")
        self.assertEqual(len(by_flavor["mop_classic"]["events"]), 1)

    def test_function_name_is_not_an_event(self):
        cp = _run(
            "events", "^Bar$", "--flavors", "retail", "--json",
            cwd=self.wow_root, wow_root=self.wow_root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertEqual(obj["flavors"][0]["events"], [])


class TestBranches(SyntheticRepoTestCase):
    def test_branches_report(self):
        cp = _run("branches", "--json", cwd=self.wow_root, wow_root=self.wow_root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        by_name = {b["name"]: b for b in obj["branches"]}

        self.assertTrue(by_name["retail"]["exists"])
        self.assertEqual(by_name["retail"]["version"], "1.1.0")
        self.assertIsNotNone(by_name["retail"]["lastCommit"])
        self.assertIsNone(by_name["retail"]["behind"])  # no origin remote configured

        self.assertTrue(by_name["mop_classic"]["exists"])
        self.assertEqual(by_name["mop_classic"]["version"], "1.0.0")

        self.assertFalse(by_name["classic_era"]["exists"])
        self.assertIsNone(by_name["classic_era"]["version"])
        self.assertFalse(by_name["tbc_anniversary"]["exists"])


class TestMissingSource(unittest.TestCase):
    def test_missing_source_dir_exits_usage(self):
        env = dict(os.environ)
        env["WOW_UI_SOURCE"] = "/nonexistent/wow-ui-source-does-not-exist"
        cp = _helpers.run_script(
            "wow_api.py", "branches", cwd=Path(tempfile.gettempdir()), env=env
        )
        self.assertEqual(cp.returncode, 2, cp.stderr)
        self.assertIn("WOW_UI_SOURCE", cp.stderr)


@unittest.skipUnless(_helpers.wow_ui_source_available(), "wow-ui-source not present")
class TestRealWowUiSource(unittest.TestCase):
    def _wow_root(self) -> Path:
        return Path(
            os.environ.get("WOW_UI_SOURCE", str(Path.home() / "code" / "wow-ui-source"))
        ).expanduser()

    def test_find_get_currency_info_present_everywhere(self):
        cp = _helpers.run_script(
            "wow_api.py",
            "find",
            "GetCurrencyInfo",
            "--flavors",
            "all",
            "--json",
            cwd=self._wow_root(),
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        present = [f["flavor"] for f in obj["flavors"] if f["present"]]
        self.assertEqual(len(present), 4, obj["summary"])

    def test_show_get_currency_info_has_arguments(self):
        cp = _helpers.run_script(
            "wow_api.py",
            "show",
            "C_CurrencyInfo.GetCurrencyInfo",
            "--flavor",
            "tbc_anniversary",
            "--json",
            cwd=self._wow_root(),
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        self.assertTrue(obj["found"])
        self.assertIn("Arguments", obj["block"])

    def test_branches_tbc_anniversary_exists(self):
        cp = _helpers.run_script("wow_api.py", "branches", "--json", cwd=self._wow_root())
        self.assertEqual(cp.returncode, 0, cp.stderr)
        obj = _helpers.json_out(cp)
        by_name = {b["name"]: b for b in obj["branches"]}
        self.assertTrue(by_name["tbc_anniversary"]["exists"])
        self.assertEqual(by_name["tbc_anniversary"]["ref"], "origin/classic_anniversary")


if __name__ == "__main__":
    unittest.main()
