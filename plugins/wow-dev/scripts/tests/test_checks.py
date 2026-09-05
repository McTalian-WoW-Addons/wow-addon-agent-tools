import json
import os
import shutil
import unittest

import _helpers
import _common as C

ADDON_FULL_COMMITS = [{"message": "chore: init"}]
RECORD_REL = (".claude", ".last-checks.json")


def _env_with(**kv):
    return dict(os.environ, **kv)


def _record_path(root):
    return root.joinpath(*RECORD_REL)


class TestOrderAndSuccess(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("addon_full", commits=ADDON_FULL_COMMITS)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_order_matches_profile(self):
        cp = _helpers.run_script("checks.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        names = [c["name"] for c in out["checks"]]
        self.assertEqual(names, ["test", "i18n", "toc", "untracked", "trunk"])
        self.assertTrue(out["ok"])
        self.assertTrue(out["recorded"])
        for check in out["checks"]:
            self.assertEqual(check["status"], "PASS")

    def test_success_writes_record_with_matching_index_hash(self):
        cp = _helpers.run_script("checks.py", "--root", str(self.root), "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        record_path = _record_path(self.root)
        self.assertTrue(record_path.is_file())
        record = json.loads(record_path.read_text(encoding="utf-8"))
        self.assertTrue(record["ok"])
        self.assertEqual(record["checks"], ["test", "i18n", "toc", "untracked", "trunk"])
        self.assertIn("ts", record)
        expected_hash = C.index_hash(self.root, ["Addon/"])
        self.assertEqual(record["indexHash"], expected_hash)

    def test_text_mode_prints_pass_lines(self):
        cp = _helpers.run_script("checks.py", "--root", str(self.root), cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("PASS test (make test)", cp.stdout)
        self.assertIn("PASS trunk (./trunk check --no-fix)", cp.stdout)


class TestStopOnFail(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("addon_full", commits=ADDON_FULL_COMMITS)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_stops_at_first_failure(self):
        env = _env_with(FAIL_TARGETS="toc_check")
        cp = _helpers.run_script(
            "checks.py", "--root", str(self.root), "--json", cwd=self.root, env=env
        )
        self.assertEqual(cp.returncode, 1, cp.stderr)
        out = _helpers.json_out(cp)
        names = [c["name"] for c in out["checks"]]
        self.assertEqual(names, ["test", "i18n", "toc"])
        self.assertEqual(out["checks"][-1]["status"], "FAIL")
        self.assertIn("boom toc_check", out["checks"][-1]["tail"])
        self.assertFalse(out["ok"])
        record = json.loads(_record_path(self.root).read_text(encoding="utf-8"))
        self.assertFalse(record["ok"])
        self.assertEqual(record["checks"], ["test", "i18n", "toc"])

    def test_keep_going_runs_all(self):
        env = _env_with(FAIL_TARGETS="toc_check")
        cp = _helpers.run_script(
            "checks.py",
            "--root",
            str(self.root),
            "--json",
            "--keep-going",
            cwd=self.root,
            env=env,
        )
        self.assertEqual(cp.returncode, 1, cp.stderr)
        out = _helpers.json_out(cp)
        names = [c["name"] for c in out["checks"]]
        self.assertEqual(names, ["test", "i18n", "toc", "untracked", "trunk"])
        statuses = {c["name"]: c["status"] for c in out["checks"]}
        self.assertEqual(statuses["toc"], "FAIL")
        self.assertEqual(statuses["untracked"], "PASS")
        self.assertEqual(statuses["trunk"], "PASS")
        self.assertFalse(out["ok"])


class TestFailTestCheck(unittest.TestCase):
    def test_fail_test_check_records_ok_false(self):
        root = _helpers.fixture_repo("addon_full", commits=ADDON_FULL_COMMITS)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        env = _env_with(FAIL_TARGETS="test")
        cp = _helpers.run_script("checks.py", "--root", str(root), "--json", cwd=root, env=env)
        self.assertEqual(cp.returncode, 1, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["checks"][0]["name"], "test")
        self.assertEqual(out["checks"][0]["status"], "FAIL")
        self.assertFalse(out["ok"])
        record = json.loads(_record_path(root).read_text(encoding="utf-8"))
        self.assertFalse(record["ok"])
        self.assertEqual(record["checks"], ["test"])


class TestOnlyAndRecording(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.fixture_repo("addon_full", commits=ADDON_FULL_COMMITS)
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_only_runs_subset_and_skips_recording(self):
        cp = _helpers.run_script(
            "checks.py", "--root", str(self.root), "--only", "test,i18n", "--json", cwd=self.root
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual([c["name"] for c in out["checks"]], ["test", "i18n"])
        self.assertFalse(out["recorded"])
        self.assertFalse(_record_path(self.root).exists())

    def test_no_record_flag_skips_recording(self):
        cp = _helpers.run_script(
            "checks.py", "--root", str(self.root), "--no-record", "--json", cwd=self.root
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertFalse(out["recorded"])
        self.assertFalse(_record_path(self.root).exists())

    def test_unknown_only_name_exits_usage(self):
        cp = _helpers.run_script(
            "checks.py", "--root", str(self.root), "--only", "bogus", "--json", cwd=self.root
        )
        self.assertEqual(cp.returncode, C.USAGE)
        self.assertIn("unknown check name: bogus", cp.stderr)
        for name in ("test", "i18n", "toc", "untracked", "trunk"):
            self.assertIn(name, cp.stderr)
        self.assertFalse(_record_path(self.root).exists())


class TestJsonShape(unittest.TestCase):
    def test_json_shape(self):
        root = _helpers.fixture_repo("addon_full", commits=ADDON_FULL_COMMITS)
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("checks.py", "--root", str(root), "--json", cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(set(out.keys()), {"ok", "checks", "recorded"})
        for check in out["checks"]:
            self.assertEqual(set(check.keys()), {"name", "cmd", "status", "seconds", "tail"})
            self.assertIn(check["status"], ("PASS", "FAIL"))
            self.assertIsInstance(check["seconds"], (int, float))


class TestEmptyChecks(unittest.TestCase):
    def test_no_checks_detected(self):
        root = _helpers.fixture_repo("checks/empty", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("checks.py", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("No checks detected.", cp.stdout)
        self.assertFalse(_record_path(root).exists())


if __name__ == "__main__":
    unittest.main()
