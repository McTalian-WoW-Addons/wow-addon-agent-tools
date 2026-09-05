import json
import shutil
import subprocess
import unittest
from pathlib import Path

import _helpers
import _common as C

ADDON_FILES = {
    "Addon/Addon.toc": "## Interface: 110100\n## Title: Addon\n",
    "Makefile": "help:\n\t@echo help\n",
}

GUARD_PATHS = ["Addon/"]


def _payload(tool_name: str, command: str | None, cwd: str) -> str:
    obj = {"tool_name": tool_name, "cwd": cwd}
    if command is not None:
        obj["tool_input"] = {"command": command}
    return json.dumps(obj)


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(root), check=True, capture_output=True)


class GuardCommitTestCase(unittest.TestCase):
    def _addon_repo(self) -> Path:
        root = _helpers.make_temp_repo(
            dict(ADDON_FILES),
            commits=[{"add": ["Addon/Addon.toc", "Makefile"], "message": "chore: init"}],
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root

    def _feature_branch(self, root: Path, name: str = "feature/test") -> None:
        _git(root, "switch", "-c", name)

    def _run(self, root: Path, command: str, tool_name: str = "Bash") -> subprocess.CompletedProcess:
        stdin = _payload(tool_name, command, str(root))
        return _helpers.run_script("guard_commit.py", cwd=root, stdin=stdin)


class TestFastPath(GuardCommitTestCase):
    def test_non_bash_tool_allows(self):
        root = self._addon_repo()
        cp = self._run(root, "git commit -m 'docs: x'", tool_name="Read")
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_non_commit_command_allows(self):
        root = self._addon_repo()
        # On main -- would block on R1 if the regex fast-path failed to
        # short-circuit before any rule logic runs.
        cp = self._run(root, "git status")
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_malformed_stdin_allows(self):
        root = self._addon_repo()
        cp = _helpers.run_script("guard_commit.py", cwd=root, stdin="{not valid json")
        self.assertEqual(cp.returncode, 0, cp.stderr)


class TestR1Branch(GuardCommitTestCase):
    def test_blocks_on_main(self):
        root = self._addon_repo()
        cp = self._run(root, 'git commit -m "docs: x"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R1", cp.stderr)
        lines = [l for l in cp.stderr.splitlines() if l]
        self.assertLessEqual(len(lines), 6)


class TestR2NoVerify(GuardCommitTestCase):
    def test_blocks_on_no_verify(self):
        root = self._addon_repo()
        self._feature_branch(root)
        cp = self._run(root, 'git commit --no-verify -m "docs: x"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R2", cp.stderr)

    def test_no_verify_inside_message_text_is_not_a_flag(self):
        root = self._addon_repo()
        self._feature_branch(root)
        cp = self._run(root, 'git commit -m "docs: mention --no-verify in prose"')
        self.assertEqual(cp.returncode, 0, cp.stderr)


class TestR3Untracked(GuardCommitTestCase):
    def test_blocks_on_untracked_packaged_file(self):
        root = self._addon_repo()
        self._feature_branch(root)
        (root / "Addon" / "New.lua").write_text("-- new\n", encoding="utf-8")
        cp = self._run(root, 'git commit -m "docs: add file"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R3", cp.stderr)
        lines = [l for l in cp.stderr.splitlines() if l]
        self.assertLessEqual(len(lines), 6)


class TestR4ChecksRecord(GuardCommitTestCase):
    def _stage_addon_change(self, root: Path) -> None:
        toc = root / "Addon" / "Addon.toc"
        toc.write_text(toc.read_text(encoding="utf-8") + "## Notes: bump\n", encoding="utf-8")
        _git(root, "add", "Addon/Addon.toc")

    def test_blocks_without_record(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_addon_change(root)
        cp = self._run(root, 'git commit -m "chore: bump"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R4", cp.stderr)

    def test_allows_with_fresh_valid_record(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_addon_change(root)
        record = {
            "ts": "2024-01-01T00:00:00Z",
            "ok": True,
            "indexHash": C.index_hash(root, GUARD_PATHS),
            "checks": ["test"],
        }
        C.write_json(root / C.RECORD_REL, record)
        cp = self._run(root, 'git commit -m "chore: bump"')
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_blocks_with_stale_hash(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_addon_change(root)
        record = {
            "ts": "2024-01-01T00:00:00Z",
            "ok": True,
            "indexHash": "f" * 64,
            "checks": ["test"],
        }
        C.write_json(root / C.RECORD_REL, record)
        cp = self._run(root, 'git commit -m "chore: bump"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R4", cp.stderr)

    def test_blocks_when_record_ok_false(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_addon_change(root)
        record = {
            "ts": "2024-01-01T00:00:00Z",
            "ok": False,
            "indexHash": C.index_hash(root, GUARD_PATHS),
            "checks": ["test"],
        }
        C.write_json(root / C.RECORD_REL, record)
        cp = self._run(root, 'git commit -m "chore: bump"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R4", cp.stderr)


class TestR5PublishingType(GuardCommitTestCase):
    def _stage_docs_only(self, root: Path) -> None:
        (root / "docs").mkdir(parents=True, exist_ok=True)
        (root / "docs" / "readme.md").write_text("hello\n", encoding="utf-8")
        _git(root, "add", "docs/readme.md")

    def test_fix_with_only_docs_staged_blocks(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_docs_only(root)
        cp = self._run(root, 'git commit -m "fix: bug"')
        self.assertEqual(cp.returncode, 2)
        self.assertIn("R5", cp.stderr)

    def test_docs_type_with_only_docs_staged_allows(self):
        root = self._addon_repo()
        self._feature_branch(root)
        self._stage_docs_only(root)
        cp = self._run(root, 'git commit -m "docs: update"')
        self.assertEqual(cp.returncode, 0, cp.stderr)

    def test_fix_with_packaged_staged_and_valid_record_allows(self):
        root = self._addon_repo()
        self._feature_branch(root)
        toc = root / "Addon" / "Addon.toc"
        toc.write_text(toc.read_text(encoding="utf-8") + "## Notes: bump\n", encoding="utf-8")
        _git(root, "add", "Addon/Addon.toc")
        record = {
            "ts": "2024-01-01T00:00:00Z",
            "ok": True,
            "indexHash": C.index_hash(root, GUARD_PATHS),
            "checks": ["test"],
        }
        C.write_json(root / C.RECORD_REL, record)
        cp = self._run(root, 'git commit -m "fix: bug"')
        self.assertEqual(cp.returncode, 0, cp.stderr)


class TestUnknownKind(GuardCommitTestCase):
    def test_unknown_kind_on_feature_branch_allows(self):
        root = _helpers.make_temp_repo(
            {"README.md": "hello\n"},
            commits=[{"add": ["README.md"], "message": "chore: init"}],
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        self._feature_branch(root)
        (root / "README.md").write_text("hello again\n", encoding="utf-8")
        _git(root, "add", "README.md")
        cp = self._run(root, 'git commit -m "feat: something"')
        self.assertEqual(cp.returncode, 0, cp.stderr)


if __name__ == "__main__":
    unittest.main()
