import shutil
import unittest

import _helpers
import _common as C


class TestAddonFull(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("addon_full", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_kind_and_addon_dir(self):
        self.assertEqual(self.profile["kind"], "addon")
        self.assertEqual(self.profile["addonDir"], "Addon")
        self.assertEqual(self.profile["toc"], "Addon/Addon.toc")
        self.assertEqual(self.profile["specDir"], "Addon_spec")
        self.assertEqual(self.profile["localeDir"], "Addon/locale")

    def test_interfaces_and_flavors(self):
        self.assertEqual(self.profile["interfaces"], [11509, 20506, 50504, 120100])
        names = [f["name"] for f in self.profile["flavors"]]
        self.assertEqual(names, ["classic_era", "tbc_anniversary", "mop_classic", "retail"])
        refs = [f["ref"] for f in self.profile["flavors"]]
        self.assertEqual(
            refs, ["classic_era", "origin/classic_anniversary", "classic", "live"]
        )

    def test_has_all_true_except_wbt_binary(self):
        has = self.profile["has"]
        for key in ("tests", "i18n", "trunk", "tocCheck", "untrackedCheck", "allChecks"):
            self.assertTrue(has[key], key)
        self.assertIn("wbtBinary", has)

    def test_ci(self):
        self.assertEqual(
            self.profile["ci"],
            {"prChecks": True, "releaseChecks": True, "ci": False, "tocUpdater": False},
        )

    def test_checks_canonical_order(self):
        self.assertEqual(
            self.profile["checks"],
            [
                {"name": "test", "cmd": "make test"},
                {"name": "i18n", "cmd": "make all_checks"},
                {"name": "toc", "cmd": "make toc_check"},
                {"name": "untracked", "cmd": "make check_untracked_files"},
                {"name": "trunk", "cmd": "./trunk check --no-fix"},
            ],
        )

    def test_guard_paths_and_overrides(self):
        self.assertEqual(self.profile["guardPaths"], ["Addon/"])
        self.assertEqual(self.profile["localeVersionStyle"], "")
        self.assertEqual(self.profile["overrides"], {})


class TestAddonMin(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("addon_min", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_one_flavor_retail(self):
        names = [f["name"] for f in self.profile["flavors"]]
        self.assertEqual(names, ["retail"])

    def test_has_flags(self):
        has = self.profile["has"]
        self.assertFalse(has["tests"])
        self.assertFalse(has["i18n"])
        self.assertFalse(has["trunk"])
        self.assertFalse(has["allChecks"])
        self.assertFalse(has["untrackedCheck"])

    def test_checks_only_toc(self):
        self.assertEqual(self.profile["checks"], [{"name": "toc", "cmd": "make toc_check"}])

    def test_spec_and_locale_dir_null(self):
        self.assertIsNone(self.profile["specDir"])
        self.assertIsNone(self.profile["localeDir"])


class TestLib(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("lib", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_kind_lib(self):
        self.assertEqual(self.profile["kind"], "lib")
        self.assertIsNone(self.profile["addonDir"])
        self.assertIsNone(self.profile["toc"])
        self.assertEqual(self.profile["interfaces"], [])
        self.assertEqual(self.profile["flavors"], [])

    def test_has_tests_true(self):
        self.assertTrue(self.profile["has"]["tests"])

    def test_checks_only_test(self):
        self.assertEqual(self.profile["checks"], [{"name": "test", "cmd": "make test"}])

    def test_guard_paths_empty(self):
        self.assertEqual(self.profile["guardPaths"], [])

    def test_spec_dir_generic(self):
        self.assertEqual(self.profile["specDir"], "LibThing_spec")


class TestLibNoBusted(unittest.TestCase):
    """No .busted file: has.tests/kind=lib come from a *_spec dir + a make test target."""

    def setUp(self):
        self.root = _helpers.fixture_repo("lib_nobusted", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_no_busted_file_present(self):
        self.assertFalse((self.root / ".busted").exists())

    def test_kind_lib(self):
        self.assertEqual(self.profile["kind"], "lib")
        self.assertIsNone(self.profile["addonDir"])
        self.assertIsNone(self.profile["toc"])

    def test_has_tests_true_via_widened_rule(self):
        self.assertTrue(self.profile["has"]["tests"])

    def test_spec_dir(self):
        self.assertEqual(self.profile["specDir"], "LibThing_spec")

    def test_checks_only_test(self):
        self.assertEqual(self.profile["checks"], [{"name": "test", "cmd": "make test"}])


class TestGoTool(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("gotool", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_kind_go_tool(self):
        self.assertEqual(self.profile["kind"], "go-tool")

    def test_checks(self):
        self.assertEqual(
            self.profile["checks"],
            [{"name": "test", "cmd": "make test"}, {"name": "trunk", "cmd": "./trunk check --no-fix"}],
        )

    def test_guard_paths(self):
        self.assertEqual(
            self.profile["guardPaths"], ["cmd/", "internal/", "go.mod", "go.sum"]
        )


class TestOverride(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("override", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.profile = _helpers.json_out(cp)

    def test_checks_replaced(self):
        self.assertEqual(self.profile["checks"], [{"name": "only", "cmd": "make test"}])

    def test_guard_paths_and_style(self):
        self.assertEqual(self.profile["guardPaths"], ["Addon/", "extras/"])
        self.assertEqual(self.profile["localeVersionStyle"], "v")

    def test_overrides_field(self):
        self.assertEqual(
            self.profile["overrides"],
            {
                "checks": [{"name": "only", "cmd": "make test"}],
                "guardPaths": ["Addon/", "extras/"],
                "localeVersionStyle": "v",
                "skipChecks": ["toc"],
            },
        )

    def test_unknown_override_key_exits_usage(self):
        (self.root / ".claude" / "repo.json").write_text('{"nope": 1}\n', encoding="utf-8")
        cp = _helpers.run_script(
            "repo_profile.py", "--root", str(self.root), "--json", cwd=self.root
        )
        self.assertEqual(cp.returncode, C.USAGE)
        self.assertIn("unknown key in .claude/repo.json: nope", cp.stderr)


class TestTextOutput(unittest.TestCase):
    def test_text_smoke(self):
        root = _helpers.fixture_repo("addon_full", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(root), "--text", cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("kind: addon", cp.stdout)
        self.assertIn("addonDir: Addon", cp.stdout)

    def test_default_is_text(self):
        root = _helpers.fixture_repo("addon_min", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("repo_profile.py", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("kind: addon", cp.stdout)


if __name__ == "__main__":
    unittest.main()


class TestTrunkFallback(unittest.TestCase):
    def test_trunk_yaml_without_launcher_uses_global_cli(self):
        import shutil, tempfile
        from pathlib import Path
        src = Path(__file__).parent / "fixtures" / "addon_full"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            shutil.copytree(src, root)
            (root / "trunk").unlink()
            (root / ".trunk").mkdir(exist_ok=True)
            (root / ".trunk" / "trunk.yaml").write_text("version: 0.1\n")
            import repo_profile
            profile = repo_profile.build_profile(root)
            self.assertTrue(profile["has"]["trunk"])
            trunk = [c for c in profile["checks"] if c["name"] == "trunk"]
            self.assertEqual(trunk, [{"name": "trunk", "cmd": "trunk check --no-fix"}])

