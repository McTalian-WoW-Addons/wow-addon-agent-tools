import os
import shutil
import tempfile
import unittest
from pathlib import Path

import _helpers
import _common as C

_MAKEFILE = "help:\n\t@echo ok\n\ntoc_check:\n\t@echo ok\n"


def _addon_repo(commits=None):
    """Temp git repo that repo_profile.py detects as kind=addon, guardPaths=['Addon/']."""
    files = {
        "Makefile": _MAKEFILE,
        "Addon/Addon.toc": "## Interface: 120100\n## Title: Addon\nCore.lua\n",
        "Addon/Core.lua": "local addonName, ns = ...\nreturn ns\n",
    }
    return _helpers.make_temp_repo(files, commits=commits)


def _unknown_repo(commits=None):
    """Temp git repo with no .toc, no tests, no go.mod: kind=unknown, guardPaths=[]."""
    files = {"README.md": "# nothing detectable\n"}
    return _helpers.make_temp_repo(files, commits=commits)


class TestTouchesPackagedStaged(unittest.TestCase):
    def setUp(self):
        self.root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def _stage(self, rel: str, content: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _helpers.subprocess.run(
            ["git", "add", rel], cwd=str(self.root), check=True, capture_output=True
        )

    def test_default_is_staged_packaged_true(self):
        self._stage("Addon/New.lua", "return {}\n")
        cp = _helpers.run_script("pr.py", "touches-packaged", "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertTrue(out["packaged"])
        self.assertEqual(out["packagedFiles"], ["Addon/New.lua"])
        self.assertEqual(out["otherFiles"], [])
        self.assertEqual(out["allowedTypes"], list(C.ALL_TYPES))

    def test_explicit_staged_flag_same_as_default(self):
        self._stage("Addon/New.lua", "return {}\n")
        cp = _helpers.run_script(
            "pr.py", "touches-packaged", "--staged", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertTrue(out["packaged"])

    def test_dev_only_change_packaged_false(self):
        self._stage("docs/x.md", "# doc\n")
        cp = _helpers.run_script("pr.py", "touches-packaged", "--json", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertFalse(out["packaged"])
        self.assertEqual(out["packagedFiles"], [])
        self.assertEqual(out["otherFiles"], ["docs/x.md"])
        self.assertEqual(out["allowedTypes"], list(C.DEV_TYPES))

    def test_mixed_change_splits_files(self):
        self._stage("Addon/New.lua", "return {}\n")
        self._stage("docs/x.md", "# doc\n")
        cp = _helpers.run_script("pr.py", "touches-packaged", "--json", cwd=self.root)
        out = _helpers.json_out(cp)
        self.assertTrue(out["packaged"])
        self.assertEqual(out["packagedFiles"], ["Addon/New.lua"])
        self.assertEqual(out["otherFiles"], ["docs/x.md"])

    def test_text_mode_smoke(self):
        self._stage("Addon/New.lua", "return {}\n")
        cp = _helpers.run_script("pr.py", "touches-packaged", "--text", cwd=self.root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("packaged: True", cp.stdout)


class TestTouchesPackagedFiles(unittest.TestCase):
    def setUp(self):
        self.root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_files_flag_no_git_state_needed(self):
        cp = _helpers.run_script(
            "pr.py",
            "touches-packaged",
            "--files",
            "Addon/x.lua",
            "docs/x.md",
            "--json",
            cwd=self.root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertTrue(out["packaged"])
        self.assertEqual(out["packagedFiles"], ["Addon/x.lua"])
        self.assertEqual(out["otherFiles"], ["docs/x.md"])


class TestTouchesPackagedRange(unittest.TestCase):
    def setUp(self):
        self.root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"docs/x.md": "# doc\n"}, "message": "docs: add doc"},
            ]
        )
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_range_only_sees_delta(self):
        cp = _helpers.run_script(
            "pr.py", "touches-packaged", "--range", "HEAD~1..HEAD", "--json", cwd=self.root
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertFalse(out["packaged"])
        self.assertEqual(out["packagedFiles"], [])
        self.assertEqual(out["otherFiles"], ["docs/x.md"])


class TestTouchesPackagedNoGuardPaths(unittest.TestCase):
    def test_packaged_null_when_guard_paths_empty(self):
        root = _unknown_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        (root / "misc.txt").write_text("x\n", encoding="utf-8")
        _helpers.subprocess.run(
            ["git", "add", "misc.txt"], cwd=str(root), check=True, capture_output=True
        )
        cp = _helpers.run_script("pr.py", "touches-packaged", "--json", cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertIsNone(out["packaged"])
        self.assertEqual(out["allowedTypes"], list(C.DEV_TYPES))


class TestLintTitle(unittest.TestCase):
    def setUp(self):
        # lint-title does not need a profile, but main() always resolves --root
        # via repo_root(cwd), so run it inside a throwaway repo rather than
        # depending on the test runner's own cwd being a git repo.
        self.root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_valid_simple(self):
        cp = _helpers.run_script(
            "pr.py", "lint-title", "fix: something", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertTrue(out["ok"])
        self.assertEqual(out["type"], "fix")
        self.assertEqual(out["errors"], [])

    def test_valid_with_scope_and_bang(self):
        cp = _helpers.run_script(
            "pr.py", "lint-title", "feat(toc)!: bump interface", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertTrue(out["ok"])
        self.assertEqual(out["type"], "feat")

    def test_invalid_type_fails(self):
        cp = _helpers.run_script(
            "pr.py", "lint-title", "nonsense: whatever", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 1)
        self.assertFalse(out["ok"])
        self.assertIsNone(out["type"])
        self.assertTrue(out["errors"])

    def test_missing_colon_fails(self):
        cp = _helpers.run_script(
            "pr.py", "lint-title", "fix something", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertFalse(out["ok"])

    def test_multiline_is_error(self):
        cp = _helpers.run_script(
            "pr.py", "lint-title", "fix: a\nb", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 1)
        self.assertFalse(out["ok"])
        self.assertEqual(out["errors"], ["multi-line title"])

    def test_long_title_is_warning_but_ok(self):
        long_desc = "x" * 70
        cp = _helpers.run_script(
            "pr.py", "lint-title", f"fix: {long_desc}", "--json", cwd=self.root
        )
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["errors"]), 1)
        self.assertTrue(out["errors"][0].startswith("warning:"))


class TestLintCommits(unittest.TestCase):
    def test_clean_range_all_types(self):
        root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"Addon/New.lua": "return {}\n"}, "message": "feat: add module"},
                {"files": {"docs/x.md": "# doc\n"}, "message": "docs: add doc"},
            ]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script(
            "pr.py", "lint-commits", "HEAD~2..HEAD", "--json", cwd=root
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(len(out["commits"]), 2)
        # git log lists newest first.
        docs, feat = out["commits"]
        self.assertEqual(feat["type"], "feat")
        self.assertTrue(feat["ok"])
        self.assertTrue(feat["packaged"])
        self.assertEqual(feat["mismatch"], [])
        self.assertEqual(docs["type"], "docs")
        self.assertFalse(docs["packaged"])
        self.assertEqual(docs["mismatch"], [])
        self.assertTrue(out["rebaseValid"])
        self.assertTrue(out["publishes"])
        self.assertEqual(out["releaseType"], "minor")

    def test_publishing_type_without_packaged_change_blocks(self):
        root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"docs/x.md": "# doc\n"}, "message": "fix: docs typo"},
            ]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("pr.py", "lint-commits", "HEAD~1..HEAD", "--json", cwd=root)
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 1)
        commit = out["commits"][0]
        self.assertTrue(commit["ok"])
        self.assertFalse(commit["packaged"])
        self.assertIn("publishing-type-without-packaged-change", commit["mismatch"])
        self.assertFalse(out["rebaseValid"])
        self.assertEqual(out["releaseType"], "patch")

    def test_dev_type_with_packaged_change_is_warning_only(self):
        root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"Addon/New.lua": "return {}\n"}, "message": "chore: tidy module"},
            ]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("pr.py", "lint-commits", "HEAD~1..HEAD", "--json", cwd=root)
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        commit = out["commits"][0]
        self.assertEqual(commit["mismatch"], ["dev-type-with-packaged-change"])
        self.assertTrue(out["rebaseValid"])
        self.assertEqual(out["releaseType"], "none")

    def test_fixup_and_unparsable_block(self):
        root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"docs/a.md": "a\n"}, "message": "fixup! chore: tidy module"},
                {"files": {"docs/b.md": "b\n"}, "message": "not conventional at all"},
            ]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("pr.py", "lint-commits", "HEAD~2..HEAD", "--json", cwd=root)
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 1)
        # git log lists newest first.
        unparsable, fixup = out["commits"]
        self.assertFalse(fixup["ok"])
        self.assertEqual(fixup["mismatch"], ["fixup-or-wip"])
        self.assertFalse(unparsable["ok"])
        self.assertEqual(unparsable["mismatch"], ["unparsable"])
        self.assertFalse(out["rebaseValid"])

    def test_empty_range_is_valid_and_publishes_nothing(self):
        root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("pr.py", "lint-commits", "HEAD..HEAD", "--json", cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["commits"], [])
        self.assertTrue(out["rebaseValid"])
        self.assertFalse(out["publishes"])
        self.assertEqual(out["releaseType"], "none")

    def test_revert_publishes_nothing(self):
        root = _addon_repo(
            commits=[
                {"message": "chore: init"},
                {"files": {"docs/x.md": "x\n"}, "message": "revert: undo docs change"},
            ]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("pr.py", "lint-commits", "HEAD~1..HEAD", "--json", cwd=root)
        out = _helpers.json_out(cp)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertFalse(out["publishes"])
        self.assertEqual(out["releaseType"], "none")
        self.assertTrue(out["rebaseValid"])


class TestLabels(unittest.TestCase):
    def setUp(self):
        self.root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bindir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.bindir, ignore_errors=True)

    def _env(self):
        return dict(os.environ, PATH=f"{self.bindir}:{os.environ['PATH']}")

    def test_rebase_valid_checks_passed_no_mismatch(self):
        _helpers.shim(
            self.bindir,
            "gh",
            "echo '{\"labels\":[{\"name\":\"rebase-valid\"},{\"name\":\"release:minor\"}],"
            "\"title\":\"feat: x\","
            "\"statusCheckRollup\":[{\"conclusion\":\"SUCCESS\"},{\"conclusion\":\"NEUTRAL\"}]}'",
        )
        cp = _helpers.run_script(
            "pr.py", "labels", "7", "--json", cwd=self.root, env=self._env()
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertTrue(out["rebaseValid"])
        self.assertFalse(out["squashValid"])
        self.assertEqual(out["release"], "minor")
        self.assertTrue(out["checksPassed"])
        self.assertFalse(out["mismatchSuspected"])

    def test_unlabelled_passing_pr_is_mismatch_suspected(self):
        _helpers.shim(
            self.bindir,
            "gh",
            "echo '{\"labels\":[],\"title\":\"chore: x\","
            "\"statusCheckRollup\":[{\"conclusion\":\"SUCCESS\"}]}'",
        )
        cp = _helpers.run_script(
            "pr.py", "labels", "9", "--json", cwd=self.root, env=self._env()
        )
        out = _helpers.json_out(cp)
        self.assertFalse(out["squashValid"])
        self.assertFalse(out["rebaseValid"])
        self.assertIsNone(out["release"])
        self.assertTrue(out["checksPassed"])
        self.assertTrue(out["mismatchSuspected"])

    def test_empty_rollup_is_null_checks_passed(self):
        _helpers.shim(
            self.bindir,
            "gh",
            "echo '{\"labels\":[{\"name\":\"squash-valid\"}],\"title\":\"fix: x\","
            "\"statusCheckRollup\":[]}'",
        )
        cp = _helpers.run_script(
            "pr.py", "labels", "3", "--json", cwd=self.root, env=self._env()
        )
        out = _helpers.json_out(cp)
        self.assertIsNone(out["checksPassed"])
        self.assertTrue(out["squashValid"])
        self.assertFalse(out["mismatchSuspected"])

    def test_failing_check_is_checks_passed_false(self):
        _helpers.shim(
            self.bindir,
            "gh",
            "echo '{\"labels\":[{\"name\":\"squash-valid\"}],\"title\":\"fix: x\","
            "\"statusCheckRollup\":[{\"conclusion\":\"FAILURE\"}]}'",
        )
        cp = _helpers.run_script(
            "pr.py", "labels", "4", "--json", cwd=self.root, env=self._env()
        )
        out = _helpers.json_out(cp)
        self.assertFalse(out["checksPassed"])
        self.assertFalse(out["mismatchSuspected"])

    def test_gh_failure_exits_fail(self):
        _helpers.shim(self.bindir, "gh", "echo 'boom' >&2; exit 1")
        cp = _helpers.run_script(
            "pr.py", "labels", "5", "--json", cwd=self.root, env=self._env()
        )
        self.assertEqual(cp.returncode, 1)
        self.assertIn("gh pr view failed", cp.stderr)


class TestCreate(unittest.TestCase):
    def setUp(self):
        self.root = _addon_repo(commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.bindir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.bindir, ignore_errors=True)
        self.body_file = self.root / "body.md"
        self.body_file.write_text("Closes #N\n", encoding="utf-8")

    def _env(self):
        return dict(os.environ, PATH=f"{self.bindir}:{os.environ['PATH']}")

    def test_create_success(self):
        _helpers.shim(
            self.bindir,
            "gh",
            (
                'if [ "$1 $2" = "pr create" ]; then\n'
                "  echo '{\"url\":\"https://example.com/pr/7\"}'\n"
                "  exit 0\n"
                'fi\n'
                'if [ "$1 $2" = "pr view" ]; then\n'
                "  echo '{\"number\":7,\"title\":\"feat: add thing\","
                "\"url\":\"https://example.com/pr/7\"}'\n"
                "  exit 0\n"
                'fi\n'
                'echo "unexpected: $*" >&2\n'
                "exit 1"
            ),
        )
        cp = _helpers.run_script(
            "pr.py",
            "create",
            "--title",
            "feat: add thing",
            "--body-file",
            str(self.body_file),
            "--json",
            cwd=self.root,
            env=self._env(),
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["number"], 7)
        self.assertEqual(out["title"], "feat: add thing")
        self.assertEqual(out["url"], "https://example.com/pr/7")

    def test_invalid_title_never_calls_gh(self):
        _helpers.shim(self.bindir, "gh", 'echo "gh should not be called" >&2; exit 1')
        cp = _helpers.run_script(
            "pr.py",
            "create",
            "--title",
            "not a valid title",
            "--body-file",
            str(self.body_file),
            "--json",
            cwd=self.root,
            env=self._env(),
        )
        self.assertEqual(cp.returncode, 1)
        self.assertIn("invalid PR title", cp.stderr)
        self.assertNotIn("gh should not be called", cp.stderr)

    def test_title_mismatch_after_create_fails(self):
        _helpers.shim(
            self.bindir,
            "gh",
            (
                'if [ "$1 $2" = "pr create" ]; then\n'
                "  echo '{\"url\":\"https://example.com/pr/8\"}'\n"
                "  exit 0\n"
                'fi\n'
                'if [ "$1 $2" = "pr view" ]; then\n'
                "  echo '{\"number\":8,\"title\":\"feat: something else\","
                "\"url\":\"https://example.com/pr/8\"}'\n"
                "  exit 0\n"
                'fi\n'
                "exit 1"
            ),
        )
        cp = _helpers.run_script(
            "pr.py",
            "create",
            "--title",
            "feat: add thing",
            "--body-file",
            str(self.body_file),
            "--json",
            cwd=self.root,
            env=self._env(),
        )
        self.assertEqual(cp.returncode, 1)
        self.assertIn("title mismatch", cp.stderr)

    def test_missing_body_file_is_usage_error(self):
        cp = _helpers.run_script(
            "pr.py",
            "create",
            "--title",
            "feat: add thing",
            "--body-file",
            str(self.root / "nope.md"),
            "--json",
            cwd=self.root,
        )
        self.assertEqual(cp.returncode, C.USAGE)


if __name__ == "__main__":
    unittest.main()
