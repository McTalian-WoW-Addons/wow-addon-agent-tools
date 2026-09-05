"""Tests for doclint.py.

Self-contained: stdlib only. Does not depend on ``_common`` or ``_helpers``
(mirrors doclint.py's own no-dependency contract) so these tests run
regardless of the state of sibling modules under active development.

Run: uv run --no-project python -m unittest \
    plugins/wow-dev/scripts/tests/test_doclint.py -v
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "doclint"

sys.path.insert(0, str(SCRIPTS_DIR))

import doclint  # noqa: E402


def pad_to(base: str, n: int) -> str:
    """Return *base* padded with filler words to exactly *n* characters."""
    words = ["thoroughly", "consistently", "carefully", "directly", "exactly"]
    s = base
    i = 0
    while len(s) < n:
        s = s + " " + words[i % len(words)]
        i += 1
    return s[:n]


class TempDirMixin:
    def make_tmp(self) -> Path:
        d = Path(tempfile.mkdtemp(prefix="doclint-test-"))
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        return d


# --- parse_frontmatter / classify -----------------------------------------


class TestParseFrontmatter(unittest.TestCase):
    def test_no_leading_dashes_returns_none(self):
        self.assertIsNone(doclint.parse_frontmatter("# Title\n\nbody\n"))

    def test_unclosed_block_returns_none(self):
        self.assertIsNone(doclint.parse_frontmatter("---\nname: x\n"))

    def test_parses_fields_in_order(self):
        text = "---\nname: foo\ndescription: bar\ntools: Read\n---\nbody\n"
        fm = doclint.parse_frontmatter(text)
        self.assertIsNotNone(fm)
        self.assertEqual(fm.order, ["name", "description", "tools"])
        self.assertEqual(fm.fields["name"], "foo")
        self.assertEqual(fm.fields["tools"], "Read")


class TestClassify(unittest.TestCase):
    def test_claude_md_by_name(self):
        self.assertEqual(doclint.classify(Path("CLAUDE.md"), None), "claude")

    def test_roster_md_by_name(self):
        self.assertEqual(doclint.classify(Path("ROSTER.md"), None), "roster")

    def test_conventions_md_by_name(self):
        self.assertEqual(doclint.classify(Path("conventions.md"), None), "conventions")

    def test_agent_by_frontmatter_tools(self):
        fm = doclint.Frontmatter(fields={"name": "x", "tools": "Read"}, order=["name", "tools"])
        self.assertEqual(doclint.classify(Path("weird.md"), fm), "agent")

    def test_skill_by_frontmatter_description_only(self):
        fm = doclint.Frontmatter(
            fields={"name": "x", "description": "d"}, order=["name", "description"]
        )
        self.assertEqual(doclint.classify(Path("weird.md"), fm), "skill")

    def test_skill_by_filename_fallback(self):
        self.assertEqual(doclint.classify(Path("SKILL.md"), None), "skill")

    def test_agent_by_parent_dir_fallback(self):
        self.assertEqual(doclint.classify(Path("agents/foo.md"), None), "agent")

    def test_other_when_nothing_matches(self):
        self.assertEqual(doclint.classify(Path("README.md"), None), "other")


class TestBudgetFor(unittest.TestCase):
    def test_claude(self):
        self.assertEqual(doclint.budget_for("claude", Path("CLAUDE.md"), None), 2048)

    def test_roster(self):
        self.assertEqual(doclint.budget_for("roster", Path("ROSTER.md"), None), 2560)

    def test_conventions(self):
        self.assertEqual(
            doclint.budget_for("conventions", Path("conventions.md"), None), 4096
        )

    def test_agent(self):
        self.assertEqual(doclint.budget_for("agent", Path("agents/foo.md"), None), 4096)

    def test_skill_default(self):
        p = Path("skills/run-checks/SKILL.md")
        self.assertEqual(doclint.budget_for("skill", p, None), 6144)

    def test_skill_large_exception_work_item(self):
        p = Path("skills/work-item/SKILL.md")
        self.assertEqual(doclint.budget_for("skill", p, None), 8192)

    def test_skill_large_exception_review_pr(self):
        p = Path("skills/review-pr/SKILL.md")
        self.assertEqual(doclint.budget_for("skill", p, None), 8192)

    def test_skill_large_exception_via_frontmatter_name(self):
        fm = doclint.Frontmatter(fields={"name": "work-item"}, order=["name"])
        p = Path("some/odd/path.md")
        self.assertEqual(doclint.budget_for("skill", p, fm), 8192)

    def test_other_has_no_budget(self):
        self.assertIsNone(doclint.budget_for("other", Path("README.md"), None))


# --- check_rationale ------------------------------------------------------


class TestCheckRationale(unittest.TestCase):
    def _rule_hits(self, text: str) -> list[str]:
        return [f["rule"] for f in doclint.check_rationale(Path("x.md"), text)]

    def test_all_fourteen_patterns_trip(self):
        samples = [
            "This exists because it is simpler.",
            "Historically this used a global.",
            "See PR 123 for details.",
            "See PR #123 for details.",
            "Landed as (#123).",
            "Bare number here #1234 in prose.",
            "we decided to use FeatureBase.",
            "the reason for this is testability.",
            "this used to be make local.",
            "at time of writing this is true.",
            "originally this was a shim.",
            "in the past this broke often.",
            "self:fn is no longer used.",
            "this is why the adapter exists.",
            "filed as an incident last week.",
        ]
        for s in samples:
            with self.subTest(s=s):
                self.assertTrue(self._rule_hits(s), f"expected a RATIONALE hit: {s!r}")

    def test_exempt_lines_with_decisions_md(self):
        text = "See docs/agent/decisions.md because that has the history."
        self.assertEqual(self._rule_hits(text), [])

    def test_exempt_lines_with_reference_md(self):
        text = "PR #123 is explained in REFERENCE.md."
        self.assertEqual(self._rule_hits(text), [])

    def test_skips_fenced_code_blocks(self):
        text = "\n".join(
            [
                "prose line",
                "```",
                "this has PR #123 inside a fence",
                "```",
                "more prose",
            ]
        )
        self.assertEqual(self._rule_hits(text), [])

    def test_skips_frontmatter_block(self):
        text = "\n".join(
            [
                "---",
                "name: x",
                "description: mentions incident here",
                "---",
                "clean body",
            ]
        )
        self.assertEqual(self._rule_hits(text), [])

    def test_closes_hash_n_is_clean(self):
        self.assertEqual(self._rule_hits("Closes #N"), [])

    def test_closes_real_number_trips(self):
        hits = self._rule_hits("Closes #123")
        self.assertIn("RATIONALE", hits)

    def test_region_marker_is_clean(self):
        self.assertEqual(self._rule_hits("--#region 1.26.0"), [])

    def test_heading_hashes_are_clean(self):
        self.assertEqual(self._rule_hits("#### Heading"), [])

    def test_line_number_reported(self):
        text = "clean line one\nclean line two\nbecause of line three\n"
        findings = doclint.check_rationale(Path("x.md"), text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 3)


# --- check_frontmatter ------------------------------------------------------


class TestCheckFrontmatterSkill(unittest.TestCase):
    def test_missing_fm_block(self):
        findings = doclint.check_frontmatter(Path("x.md"), "skill", None)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "FRONTMATTER")

    def test_missing_name_and_description(self):
        fm = doclint.Frontmatter(fields={}, order=[])
        findings = doclint.check_frontmatter(Path("x.md"), "skill", fm)
        msgs = " ".join(f["excerpt"] for f in findings)
        self.assertIn("name", msgs)
        self.assertIn("description", msgs)

    def test_description_too_short(self):
        fm = doclint.Frontmatter(
            fields={"name": "x", "description": pad_to("d", 149)},
            order=["name", "description"],
        )
        findings = doclint.check_frontmatter(Path("x.md"), "skill", fm)
        self.assertTrue(any("149" in f["excerpt"] for f in findings))

    def test_description_too_long(self):
        fm = doclint.Frontmatter(
            fields={"name": "x", "description": pad_to("d", 461)},
            order=["name", "description"],
        )
        findings = doclint.check_frontmatter(Path("x.md"), "skill", fm)
        self.assertTrue(any("461" in f["excerpt"] for f in findings))

    def test_description_boundaries_are_clean(self):
        for n in (150, 460):
            fm = doclint.Frontmatter(
                fields={"name": "x", "description": pad_to("d", n)},
                order=["name", "description"],
            )
            findings = doclint.check_frontmatter(Path("x.md"), "skill", fm)
            self.assertEqual(findings, [], f"n={n}")


class TestCheckFrontmatterAgent(unittest.TestCase):
    def _valid_fields(self, **overrides) -> dict:
        fields = {
            "name": "foo",
            "description": pad_to("d", 300),
            "tools": "Read",
            "model": "sonnet",
            "effort": "low",
        }
        fields.update(overrides)
        return fields

    def test_missing_keys(self):
        fm = doclint.Frontmatter(
            fields={"name": "x", "description": pad_to("d", 300), "tools": "Read"},
            order=["name", "description", "tools"],
        )
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        msgs = " ".join(f["excerpt"] for f in findings)
        self.assertIn("model", msgs)
        self.assertIn("effort", msgs)

    def test_extra_key(self):
        fields = self._valid_fields()
        order = ["name", "description", "tools", "model", "effort", "color"]
        fields["color"] = "blue"
        fm = doclint.Frontmatter(fields=fields, order=order)
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        msgs = " ".join(f["excerpt"] for f in findings)
        self.assertIn("color", msgs)

    def test_keys_out_of_order(self):
        fields = self._valid_fields()
        order = ["name", "tools", "description", "model", "effort"]
        fm = doclint.Frontmatter(fields=fields, order=order)
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        self.assertTrue(any("out of order" in f["excerpt"] for f in findings))

    def test_correct_order_is_not_flagged_out_of_order(self):
        fields = self._valid_fields()
        order = list(doclint.AGENT_FIELD_ORDER)
        fm = doclint.Frontmatter(fields=fields, order=order)
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        self.assertFalse(any("out of order" in f["excerpt"] for f in findings))

    def test_invalid_model(self):
        fields = self._valid_fields(model="gpt4")
        fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        self.assertTrue(any("invalid model" in f["excerpt"] for f in findings))

    def test_valid_models(self):
        for model in ("haiku", "sonnet", "opus", "inherit"):
            fields = self._valid_fields(model=model)
            fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
            findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
            self.assertFalse(
                any("invalid model" in f["excerpt"] for f in findings), model
            )

    def test_invalid_effort(self):
        fields = self._valid_fields(effort="extreme")
        fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        self.assertTrue(any("invalid effort" in f["excerpt"] for f in findings))

    def test_valid_efforts(self):
        for effort in ("low", "medium", "high", "xhigh", "max"):
            fields = self._valid_fields(effort=effort)
            fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
            findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
            self.assertFalse(
                any("invalid effort" in f["excerpt"] for f in findings), effort
            )

    def test_description_range_boundaries(self):
        for n in (250, 470):
            fields = self._valid_fields(description=pad_to("d", n))
            fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
            findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
            self.assertEqual(findings, [], f"n={n}")

    def test_description_out_of_range(self):
        for n in (249, 471):
            fields = self._valid_fields(description=pad_to("d", n))
            fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
            findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
            self.assertTrue(findings, f"n={n}")

    def test_fully_valid_agent_is_clean(self):
        fields = self._valid_fields()
        fm = doclint.Frontmatter(fields=fields, order=list(doclint.AGENT_FIELD_ORDER))
        findings = doclint.check_frontmatter(Path("x.md"), "agent", fm)
        self.assertEqual(findings, [])


# --- check_headings ---------------------------------------------------------


class TestCheckHeadings(unittest.TestCase):
    def test_correct_headings_clean(self):
        text = "# Title\n\n## Commands\n\nx\n\n## Conventions\n\ny\n\n## Docs\n\nz\n"
        self.assertEqual(doclint.check_headings(Path("CLAUDE.md"), text), [])

    def test_wrong_headings_flagged(self):
        text = "## Setup\n\n## Commands\n\n## Docs\n"
        findings = doclint.check_headings(Path("CLAUDE.md"), text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "HEADINGS")

    def test_no_headings_flagged(self):
        text = "just prose, no headings at all\n"
        findings = doclint.check_headings(Path("CLAUDE.md"), text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["line"], 1)


# --- check_roster ------------------------------------------------------------


class TestCheckRoster(unittest.TestCase):
    def test_mentions_agent_without_roster_md(self):
        text = "Spawn lua-convention-reviewer for this diff.\n"
        findings = doclint.check_roster(Path("SKILL.md"), text)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["rule"], "ROSTER")

    def test_mentions_agent_with_roster_md_cited(self):
        text = "Spawn lua-convention-reviewer per ROSTER.md.\n"
        self.assertEqual(doclint.check_roster(Path("SKILL.md"), text), [])

    def test_no_agent_mention_is_clean(self):
        text = "Run the checks and report the result.\n"
        self.assertEqual(doclint.check_roster(Path("SKILL.md"), text), [])

    def test_all_nine_names_recognised(self):
        for name in doclint.AGENT_ROSTER_NAMES:
            with self.subTest(name=name):
                text = f"Spawn {name} here.\n"
                findings = doclint.check_roster(Path("SKILL.md"), text)
                self.assertEqual(len(findings), 1)


# --- lint_file against real fixtures -----------------------------------


class TestLintFileFixtures(unittest.TestCase):
    def _lint(self, name: str, explicit: bool = True):
        return doclint.lint_file(FIXTURES / name, explicit)

    def test_rationale_because(self):
        findings = self._lint("rationale_because.md")
        self.assertTrue(any(f["rule"] == "RATIONALE" for f in findings))

    def test_rationale_pr_number(self):
        findings = self._lint("rationale_pr_number.md")
        self.assertTrue(any(f["rule"] == "RATIONALE" for f in findings))

    def test_budget_over_with_shrunk_budget(self):
        with unittest.mock.patch.object(doclint, "BUDGET_AGENT_MD", 20):
            findings = self._lint("budget_over.md")
        self.assertTrue(any(f["rule"] == "BUDGET" for f in findings))

    def test_frontmatter_missing(self):
        findings = self._lint("frontmatter_missing.md")
        hits = [f for f in findings if f["rule"] == "FRONTMATTER"]
        self.assertTrue(any("model" in f["excerpt"] for f in hits))
        self.assertTrue(any("effort" in f["excerpt"] for f in hits))

    def test_frontmatter_order(self):
        findings = self._lint("frontmatter_order.md")
        hits = [f for f in findings if f["rule"] == "FRONTMATTER"]
        self.assertTrue(any("out of order" in f["excerpt"] for f in hits))

    def test_frontmatter_bad_model(self):
        findings = self._lint("frontmatter_bad_model.md")
        hits = [f for f in findings if f["rule"] == "FRONTMATTER"]
        self.assertTrue(any("invalid model" in f["excerpt"] for f in hits))

    def test_frontmatter_bad_effort(self):
        findings = self._lint("frontmatter_bad_effort.md")
        hits = [f for f in findings if f["rule"] == "FRONTMATTER"]
        self.assertTrue(any("invalid effort" in f["excerpt"] for f in hits))

    def test_roster_uncited(self):
        findings = self._lint("roster_uncited.md")
        self.assertTrue(any(f["rule"] == "ROSTER" for f in findings))

    def test_clean_skill_is_clean(self):
        self.assertEqual(self._lint("clean_skill.md"), [])

    def test_clean_agent_is_clean(self):
        self.assertEqual(self._lint("clean_agent.md"), [])


class TestHeadingsExplicitVsDiscovered(TempDirMixin, unittest.TestCase):
    def test_explicit_path_skips_headings_rule(self):
        tmp = self.make_tmp()
        claude = tmp / "CLAUDE.md"
        claude.write_text((FIXTURES / "headings_wrong.md").read_text())
        findings = doclint.lint_file(claude, explicit=True)
        self.assertFalse(any(f["rule"] == "HEADINGS" for f in findings))

    def test_discovered_path_applies_headings_rule(self):
        tmp = self.make_tmp()
        claude = tmp / "CLAUDE.md"
        claude.write_text((FIXTURES / "headings_wrong.md").read_text())
        findings = doclint.lint_file(claude, explicit=False)
        self.assertTrue(any(f["rule"] == "HEADINGS" for f in findings))

    def test_discovered_path_with_correct_headings_is_clean_of_headings(self):
        tmp = self.make_tmp()
        claude = tmp / "CLAUDE.md"
        claude.write_text("## Commands\n\nx\n\n## Conventions\n\ny\n\n## Docs\n\nz\n")
        findings = doclint.lint_file(claude, explicit=False)
        self.assertFalse(any(f["rule"] == "HEADINGS" for f in findings))


# --- discovery -----------------------------------------------------------


class TestDiscovery(TempDirMixin, unittest.TestCase):
    def test_is_plugin_root_via_claude_plugin_dir(self):
        tmp = self.make_tmp()
        (tmp / ".claude-plugin").mkdir()
        self.assertTrue(doclint.is_plugin_root(tmp))

    def test_is_plugin_root_via_skills_and_agents(self):
        tmp = self.make_tmp()
        (tmp / "skills").mkdir()
        (tmp / "agents").mkdir()
        self.assertTrue(doclint.is_plugin_root(tmp))

    def test_is_not_plugin_root(self):
        tmp = self.make_tmp()
        (tmp / "skills").mkdir()
        self.assertFalse(doclint.is_plugin_root(tmp))

    def test_discover_repo_finds_claude_md(self):
        tmp = self.make_tmp()
        (tmp / "CLAUDE.md").write_text("## Commands\n\n## Conventions\n\n## Docs\n")
        targets = doclint.discover_repo(tmp)
        self.assertEqual(len(targets), 1)
        self.assertFalse(targets[0][1])  # not explicit

    def test_discover_repo_finds_dot_claude_skills_and_agents(self):
        tmp = self.make_tmp()
        (tmp / ".claude" / "skills" / "foo").mkdir(parents=True)
        (tmp / ".claude" / "skills" / "foo" / "SKILL.md").write_text("x")
        (tmp / ".claude" / "agents").mkdir(parents=True)
        (tmp / ".claude" / "agents" / "bar.md").write_text("x")
        (tmp / "docs" / "agent").mkdir(parents=True)
        (tmp / "docs" / "agent" / "conventions.md").write_text("x")
        targets = doclint.discover_repo(tmp)
        names = sorted(p.name for p, _ in targets)
        self.assertEqual(names, ["SKILL.md", "bar.md", "conventions.md"])

    def test_discover_plugin_finds_skills_agents_roster(self):
        tmp = self.make_tmp()
        (tmp / "skills" / "foo").mkdir(parents=True)
        (tmp / "skills" / "foo" / "SKILL.md").write_text("x")
        (tmp / "agents").mkdir()
        (tmp / "agents" / "bar.md").write_text("x")
        (tmp / "ROSTER.md").write_text("x")
        targets = doclint.discover_plugin(tmp)
        names = sorted(p.name for p, _ in targets)
        self.assertEqual(names, ["ROSTER.md", "SKILL.md", "bar.md"])

    def test_collect_targets_file_is_explicit(self):
        tmp = self.make_tmp()
        f = tmp / "note.md"
        f.write_text("x")
        targets = doclint.collect_targets([str(f)])
        self.assertEqual(targets, [(f.resolve(), True)])

    def test_collect_targets_missing_path_raises(self):
        with self.assertRaises(doclint.DoclintUsageError):
            doclint.collect_targets(["/no/such/path/at/all"])


# --- CLI end-to-end via subprocess -----------------------------------------


class TestCli(TempDirMixin, unittest.TestCase):
    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "doclint.py"), *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_usage_exit_on_missing_path(self):
        tmp = self.make_tmp()
        cp = self._run(["no-such-file.md"], tmp)
        self.assertEqual(cp.returncode, doclint.USAGE)

    def test_usage_exit_outside_git_repo_no_root(self):
        tmp = self.make_tmp()
        cp = self._run([], tmp)
        self.assertEqual(cp.returncode, doclint.USAGE)

    def test_root_flag_default_discovery_clean(self):
        tmp = self.make_tmp()
        (tmp / "CLAUDE.md").write_text("## Commands\n\n## Conventions\n\n## Docs\n")
        cp = self._run(["--root", str(tmp)], tmp)
        self.assertEqual(cp.returncode, doclint.OK)
        self.assertEqual(cp.stdout, "")

    def test_root_flag_default_discovery_dirty(self):
        tmp = self.make_tmp()
        (tmp / "CLAUDE.md").write_text("## Setup\n\n## Commands\n\n## Docs\n")
        cp = self._run(["--root", str(tmp)], tmp)
        self.assertEqual(cp.returncode, doclint.FAIL)
        self.assertIn("HEADINGS", cp.stdout)
        self.assertIn("CLAUDE.md:1", cp.stdout)
        self.assertIn(" — ", cp.stdout)

    def test_explicit_file_rationale_finding(self):
        cp = self._run([str(FIXTURES / "rationale_because.md")], Path.cwd())
        self.assertEqual(cp.returncode, doclint.FAIL)
        self.assertIn("RATIONALE", cp.stdout)

    def test_json_output_shape(self):
        cp = self._run(["--json", str(FIXTURES / "rationale_because.md")], Path.cwd())
        obj = json.loads(cp.stdout)
        self.assertIn("ok", obj)
        self.assertIn("findings", obj)
        self.assertFalse(obj["ok"])
        finding = obj["findings"][0]
        self.assertEqual(set(finding.keys()), {"path", "line", "rule", "excerpt"})

    def test_json_output_clean(self):
        cp = self._run(["--json", str(FIXTURES / "clean_skill.md")], Path.cwd())
        obj = json.loads(cp.stdout)
        self.assertTrue(obj["ok"])
        self.assertEqual(obj["findings"], [])
        self.assertEqual(cp.returncode, doclint.OK)

    def test_plugin_root_directory_discovery_clean(self):
        tmp = self.make_tmp()
        (tmp / ".claude-plugin").mkdir()
        (tmp / "skills" / "clean-skill-test").mkdir(parents=True)
        shutil.copy(
            FIXTURES / "clean_skill.md",
            tmp / "skills" / "clean-skill-test" / "SKILL.md",
        )
        (tmp / "agents").mkdir()
        shutil.copy(FIXTURES / "clean_agent.md", tmp / "agents" / "clean-agent-test.md")
        cp = self._run([str(tmp)], tmp)
        self.assertEqual(cp.returncode, doclint.OK, cp.stdout + cp.stderr)

    def test_plugin_root_directory_discovery_dirty(self):
        tmp = self.make_tmp()
        (tmp / ".claude-plugin").mkdir()
        (tmp / "skills" / "roster-test").mkdir(parents=True)
        shutil.copy(
            FIXTURES / "roster_uncited.md",
            tmp / "skills" / "roster-test" / "SKILL.md",
        )
        (tmp / "agents").mkdir()
        cp = self._run([str(tmp)], tmp)
        self.assertEqual(cp.returncode, doclint.FAIL)
        self.assertIn("ROSTER", cp.stdout)


if __name__ == "__main__":
    unittest.main()
