import io
import json
import shutil
import sys
import unittest
from pathlib import Path

import _helpers
import _common as C


class TestFlavors(unittest.TestCase):
    def test_classic_era_band(self):
        f = C.flavor_for(11509)
        self.assertEqual(f["name"], "classic_era")
        self.assertEqual(f["ref"], "classic_era")
        self.assertEqual(f["product"], "wow_classic_era")

    def test_tbc_anniversary_band(self):
        f = C.flavor_for(20506)
        self.assertEqual(f["name"], "tbc_anniversary")
        self.assertEqual(f["ref"], "origin/classic_anniversary")
        self.assertEqual(f["product"], "wow_anniversary")

    def test_mop_classic_band(self):
        f = C.flavor_for(50504)
        self.assertEqual(f["name"], "mop_classic")
        self.assertEqual(f["ref"], "classic")
        self.assertEqual(f["product"], "wow_classic")

    def test_retail_band_11xxxx(self):
        f = C.flavor_for(110100)
        self.assertEqual(f["name"], "retail")
        self.assertEqual(f["ref"], "live")
        self.assertEqual(f["product"], "wow")

    def test_retail_band_12xxxx(self):
        f = C.flavor_for(120100)
        self.assertEqual(f["name"], "retail")
        self.assertEqual(f["ref"], "live")

    def test_unknown_band(self):
        f = C.flavor_for(99999)
        self.assertIsNone(f["band"])
        self.assertEqual(f["name"], "unknown-99999")
        self.assertIsNone(f["ref"])
        self.assertIsNone(f["product"])
        self.assertFalse(f["match"](99999))

    def test_unknown_is_a_copy(self):
        f = C.flavor_for(99999)
        f["name"] = "mutated"
        f2 = C.flavor_for(99999)
        self.assertEqual(f2["name"], "unknown-99999")

    def test_flavors_entry_is_a_copy(self):
        f = C.flavor_for(11509)
        f["name"] = "mutated"
        original = [e for e in C.FLAVORS if e["name"] == "classic_era"][0]
        self.assertEqual(original["name"], "classic_era")


class TestIndexHash(unittest.TestCase):
    def setUp(self):
        self.root = _helpers.make_temp_repo(
            {"Addon/Addon.toc": "## Interface: 120100\n", "Addon/Core.lua": "return {}\n"},
            commits=[{"message": "chore: init"}],
        )
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def test_empty_paths_yields_hash_of_empty_string(self):
        import hashlib

        h = C.index_hash(self.root, [])
        self.assertEqual(h, hashlib.sha256(b"").hexdigest())
        self.assertEqual(len(h), 64)

    def test_stable_when_unchanged(self):
        h1 = C.index_hash(self.root, ["Addon/"])
        h2 = C.index_hash(self.root, ["Addon/"])
        self.assertEqual(h1, h2)

    def test_changes_when_tracked_content_changes(self):
        h1 = C.index_hash(self.root, ["Addon/"])
        (self.root / "Addon" / "Core.lua").write_text("return {1}\n", encoding="utf-8")
        C.run(["git", "add", "Addon/Core.lua"], cwd=self.root)
        C.run(["git", "commit", "-m", "chore: change"], cwd=self.root)
        h2 = C.index_hash(self.root, ["Addon/"])
        self.assertNotEqual(h1, h2)

    def test_unchanged_when_untracked_file_appears(self):
        h1 = C.index_hash(self.root, ["Addon/"])
        (self.root / "Addon" / "New.lua").write_text("return {}\n", encoding="utf-8")
        h2 = C.index_hash(self.root, ["Addon/"])
        self.assertEqual(h1, h2)


class TestReadJson(unittest.TestCase):
    def test_missing_file_returns_none(self):
        self.assertIsNone(C.read_json(Path("/nonexistent/path/does-not-exist.json")))

    def test_invalid_json_returns_none(self):
        import tempfile

        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "bad.json"
        p.write_text("{not valid json", encoding="utf-8")
        self.assertIsNone(C.read_json(p))

    def test_non_object_top_level_returns_none(self):
        import tempfile

        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "list.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertIsNone(C.read_json(p))

    def test_valid_object_roundtrip(self):
        import tempfile

        d = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        p = d / "obj.json"
        C.write_json(p, {"a": 1, "b": [1, 2]})
        self.assertEqual(C.read_json(p), {"a": 1, "b": [1, 2]})


class TestHookInput(unittest.TestCase):
    def _run_with_stdin(self, data: str | None):
        old_stdin = sys.stdin
        try:
            if data is None:
                sys.stdin = io.StringIO("")
                sys.stdin.isatty = lambda: True  # type: ignore[attr-defined]
            else:
                sys.stdin = io.StringIO(data)
                sys.stdin.isatty = lambda: False  # type: ignore[attr-defined]
            return C.hook_input()
        finally:
            sys.stdin = old_stdin

    def test_tty_returns_empty(self):
        self.assertEqual(self._run_with_stdin(None), {})

    def test_empty_stdin_returns_empty(self):
        self.assertEqual(self._run_with_stdin(""), {})

    def test_invalid_json_returns_empty(self):
        self.assertEqual(self._run_with_stdin("{not json"), {})

    def test_non_object_returns_empty(self):
        self.assertEqual(self._run_with_stdin("[1,2,3]"), {})

    def test_valid_object_returned(self):
        payload = {"tool_name": "Bash", "tool_input": {"command": "ls"}}
        self.assertEqual(self._run_with_stdin(json.dumps(payload)), payload)


if __name__ == "__main__":
    unittest.main()
