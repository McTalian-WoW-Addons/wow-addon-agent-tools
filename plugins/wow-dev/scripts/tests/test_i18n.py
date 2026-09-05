"""Tests for i18n.py (the enUS.lua `--#region` locale-key manager).

Note: this script lives at scripts/i18n.py, not scripts/locale.py, because
the scripts dir sits at sys.path[0] for every script in this directory and
shadowing the stdlib `locale` module breaks argparse's gettext usage in
every other script. Fixture assets still live under fixtures/locale/.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import unittest
from pathlib import Path

import _helpers

MAKEFILE_ALL = """FAIL_TARGETS ?=
RUN = @case " $(FAIL_TARGETS) " in *" $@ "*) echo "boom $@" >&2; exit 1 ;; esac; echo "ok $@"

help:
\t@echo "fixture makefile"

all_checks:
\t$(RUN)

i18n_check:
\t$(RUN)

i18n_fmt:
\t$(RUN)
"""

MAKEFILE_I18N_CHECK_ONLY = """FAIL_TARGETS ?=
RUN = @case " $(FAIL_TARGETS) " in *" $@ "*) echo "boom $@" >&2; exit 1 ;; esac; echo "ok $@"

help:
\t@echo "fixture makefile"

i18n_check:
\t$(RUN)
"""

TOC = "## Interface: 120100\n## Title: Addon\nCore.lua\n"
CORE = "local addonName, ns = ...\nreturn ns\n"


def _locale_text(name: str) -> str:
    return (_helpers.FIXTURES / "locale" / name).read_text(encoding="utf-8")


def _tag(root: Path, name: str) -> None:
    subprocess.run(
        ["git", "tag", name],
        cwd=str(root),
        check=True,
        capture_output=True,
    )


class LocaleRepoMixin:
    def make_repo(
        self,
        locale_text: str,
        *,
        makefile: str = MAKEFILE_ALL,
        repo_json: dict | None = None,
    ) -> Path:
        files = {
            "Makefile": makefile,
            "Addon/Addon.toc": TOC,
            "Addon/Core.lua": CORE,
            "Addon/locale/enUS.lua": locale_text,
        }
        if repo_json is not None:
            files[".claude/repo.json"] = json.dumps(repo_json)
        root = _helpers.make_temp_repo(
            files, commits=[{"message": "chore: init"}]
        )
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        return root


class TestAddExistingTopRegion(LocaleRepoMixin, unittest.TestCase):
    """No git tags -> falls back to the top region's own version, so the key
    lands in the existing top region rather than creating a new one."""

    def test_noprefix(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "NewKey",
            "--text",
            "New Text",
            "--json",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["ok"], True)
        self.assertEqual(out["key"], "NewKey")
        self.assertEqual(out["version"], "1.2.0")
        self.assertFalse(out["created_region"])
        self.assertEqual(out["file"], "Addon/locale/enUS.lua")

        text = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        lines = text.splitlines()
        # New key sits as the last line inside the top region, before its
        # --#endregion, after the pre-existing keys.
        top_start = lines.index("--#region 1.2.0")
        top_end = lines.index("--#endregion", top_start)
        self.assertEqual(lines[top_end - 1], 'L["NewKey"] = "New Text"')
        self.assertIn('L["Newest"] = "Newest"', lines[top_start:top_end])
        self.assertIn('L["Second"] = "Second"', lines[top_start:top_end])
        # Only one region still starts with "1.2.0" (no new region created).
        self.assertEqual(lines.count("--#region 1.2.0"), 1)

    def test_vprefix(self):
        root = self.make_repo(_locale_text("enUS_vprefix.lua"))
        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "NewKey",
            "--text",
            "New Text",
            "--json",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["version"], "v1.2.0")
        self.assertFalse(out["created_region"])

        text = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        lines = text.splitlines()
        top_start = lines.index("--#region v1.2.0")
        top_end = lines.index("--#endregion", top_start)
        self.assertEqual(lines[top_end - 1], 'L["NewKey"] = "New Text"')
        self.assertEqual(lines.count("--#region v1.2.0"), 1)


class TestAddCreatesNewRegion(LocaleRepoMixin, unittest.TestCase):
    def test_explicit_version_creates_region_at_top(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "Fresh",
            "--text",
            "Fresh Text",
            "--version",
            "2.0.0",
            "--json",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["version"], "2.0.0")
        self.assertTrue(out["created_region"])

        text = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        lines = text.splitlines()
        # New region sits directly above the previously-first region.
        new_start = lines.index("--#region 2.0.0")
        new_end = lines.index("--#endregion", new_start)
        self.assertEqual(lines[new_start + 1 : new_end], ['L["Fresh"] = "Fresh Text"'])
        old_start = lines.index("--#region 1.2.0")
        self.assertGreater(old_start, new_end)
        # Old region's own keys are untouched.
        old_end = lines.index("--#endregion", old_start)
        self.assertIn('L["Newest"] = "Newest"', lines[old_start:old_end])
        self.assertIn('L["Second"] = "Second"', lines[old_start:old_end])

    def test_profile_style_overrides_mirrored_prefix(self):
        # Top region has no "v" prefix, but localeVersionStyle="v" forces one
        # on the derived (git-tag-bumped) version.
        text = _locale_text("enUS_noprefix.lua").replace("1.2.0", "1.20.0")
        root = self.make_repo(text, repo_json={"localeVersionStyle": "v"})
        _tag(root, "v1.25.0")

        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "Fresh",
            "--text",
            "Fresh Text",
            "--json",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["version"], "v1.26.0")
        self.assertTrue(out["created_region"])

    def test_mirrors_top_prefix_when_style_unset(self):
        # Top region has a "v" prefix and no override is set, so the derived
        # version mirrors that prefix even though the tag itself has none.
        text = _locale_text("enUS_vprefix.lua").replace("v1.2.0", "v1.20.0")
        root = self.make_repo(text)
        _tag(root, "1.25.0")

        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "Fresh",
            "--text",
            "Fresh Text",
            "--json",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = _helpers.json_out(cp)
        self.assertEqual(out["version"], "v1.26.0")
        self.assertTrue(out["created_region"])


class TestAddDuplicateKey(LocaleRepoMixin, unittest.TestCase):
    def test_duplicate_key_fails_and_leaves_file_unchanged(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        before = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")

        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "Newest",
            "--text",
            "Whatever",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 1)
        self.assertIn("Newest", cp.stderr)

        after = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        self.assertEqual(before, after)

    def test_idempotence_second_add_of_same_key_fails(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))

        cp1 = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "OnceOnly",
            "--text",
            "Text",
            cwd=root,
        )
        self.assertEqual(cp1.returncode, 0, cp1.stderr)
        after_first = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")

        cp2 = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "OnceOnly",
            "--text",
            "Text",
            cwd=root,
        )
        self.assertEqual(cp2.returncode, 1)

        after_second = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        self.assertEqual(after_first, after_second)
        self.assertEqual(after_second.count('L["OnceOnly"]'), 1)


class TestAddEscaping(LocaleRepoMixin, unittest.TestCase):
    def test_quotes_and_backslashes_are_escaped(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        raw_text = r'He said "hi" \ bye'
        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "Quoted",
            "--text",
            raw_text,
            cwd=root,
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)

        text = (root / "Addon" / "locale" / "enUS.lua").read_text(encoding="utf-8")
        self.assertIn(r'L["Quoted"] = "He said \"hi\" \\ bye"', text)


class TestRegions(LocaleRepoMixin, unittest.TestCase):
    def test_json(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        cp = _helpers.run_script(
            "i18n.py", "regions", "--root", str(root), "--json", cwd=root
        )
        self.assertEqual(cp.returncode, 0, cp.stderr)
        out = json.loads(cp.stdout)
        self.assertEqual(
            out,
            [
                {"version": "1.2.0", "keys": 2},
                {"version": "1.1.0", "keys": 1},
            ],
        )

    def test_text(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"))
        cp = _helpers.run_script("i18n.py", "regions", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertEqual(cp.stdout.strip(), "1.2.0, 1.1.0")


class TestCheck(LocaleRepoMixin, unittest.TestCase):
    def test_uses_all_checks_when_present(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"), makefile=MAKEFILE_ALL)
        cp = _helpers.run_script("i18n.py", "check", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("ok all_checks", cp.stdout)

    def test_falls_back_to_i18n_check(self):
        root = self.make_repo(
            _locale_text("enUS_noprefix.lua"), makefile=MAKEFILE_I18N_CHECK_ONLY
        )
        cp = _helpers.run_script("i18n.py", "check", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 0, cp.stderr)
        self.assertIn("ok i18n_check", cp.stdout)

    def test_failure_propagates_as_exit_1(self):
        root = self.make_repo(_locale_text("enUS_noprefix.lua"), makefile=MAKEFILE_ALL)
        env = dict(os.environ, FAIL_TARGETS="all_checks")
        cp = _helpers.run_script(
            "i18n.py", "check", "--root", str(root), cwd=root, env=env
        )
        self.assertEqual(cp.returncode, 1)
        self.assertIn("boom all_checks", cp.stderr)


class TestNoLocaleDir(unittest.TestCase):
    def test_add_exits_2_without_locale_dir(self):
        root = _helpers.fixture_repo("addon_min", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script(
            "i18n.py",
            "add",
            "--root",
            str(root),
            "--key",
            "K",
            "--text",
            "T",
            cwd=root,
        )
        self.assertEqual(cp.returncode, 2)
        self.assertIn("no localeDir in profile", cp.stderr)

    def test_regions_exits_2_without_locale_dir(self):
        root = _helpers.fixture_repo("addon_min", commits=[{"message": "chore: init"}])
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        cp = _helpers.run_script("i18n.py", "regions", "--root", str(root), cwd=root)
        self.assertEqual(cp.returncode, 2)
        self.assertIn("no localeDir in profile", cp.stderr)


if __name__ == "__main__":
    unittest.main()
