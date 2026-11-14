"""Tests for the review-content-quality lens bundle.

Run from the repo root:
  python -m unittest discover -s testing/skills -t . -v

The bundle is a skill, not code: these tests pin the layout, the strict
validator result, the trigger surface, and the routing/docs references so a
future edit cannot silently orphan the lens.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "code-review" / "review-content-quality"
ENTRY = REPO / "skills" / "code-review" / "code-review" / "SKILL.md"
SUITE_README = REPO / "skills" / "code-review" / "README.md"
SKILLS_README = REPO / "skills" / "README.md"
ROOT_README = REPO / "README.md"
AGENTS_MD = REPO / "AGENTS.md"

REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "references/content-quality-checklist.md",
    "references/review-procedure.md",
    "references/anti-patterns.md",
    "templates/content-review-report.md",
)


def _load_validator():
    path = REPO / "scripts" / "check_skills.py"
    spec = importlib.util.spec_from_file_location("check_skills", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


class BundleLayoutTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        for relative in REQUIRED_FILES:
            path = BUNDLE / relative
            self.assertTrue(path.is_file(), f"missing {relative}")

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual(
            [skill.name for skill in skills],
            ["review-content-quality"],
            [finding.render() for finding in findings],
        )
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_cli_strict_exit_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = validator.main(["--strict", "--bundle", str(BUNDLE), "--quiet"])
        self.assertEqual(exit_code, 0)

    def test_description_is_trigger_rich(self) -> None:
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        fields, _ = validator.parse_frontmatter(text)
        description = fields["description"]
        self.assertEqual(fields["name"], "review-content-quality")
        self.assertGreaterEqual(len(description), 80)
        self.assertLessEqual(len(description), 1024)
        self.assertIn("use when", description.lower())
        self.assertNotIn("<", description)
        self.assertNotIn(">", description)

    def test_metadata_records_evidence_date(self) -> None:
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn('evidence_date: "2026-11-14"', text)
        self.assertIn("owner: zivon", text)
        self.assertIn('version: "1.0"', text)

    def test_references_are_mentioned_from_the_entry_point(self) -> None:
        body = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        for reference in (
            "content-quality-checklist.md",
            "review-procedure.md",
            "anti-patterns.md",
            "content-review-report.md",
        ):
            self.assertIn(reference, body, f"{reference} is not mentioned")

    def test_when_not_to_use_is_explicit(self) -> None:
        body = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("When NOT to use this lens", body)
        for route in (
            "Product decisions",
            "Visual design and doctrine",
            "Voice runtime behaviour",
            "Infrastructure and deployment",
        ):
            self.assertIn(route, body)

    def test_worked_example_recomputes_an_answer(self) -> None:
        body = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("## Worked example", body)
        self.assertIn("v = u + at", body)
        self.assertIn("q-07", body)

    def test_entry_point_has_no_placeholder_tokens(self) -> None:
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        for token in ("TODO", "TBD", "FIXME", "XXX"):
            self.assertNotIn(token, text, f"{token} in SKILL.md")


class ChecklistCoverageTests(unittest.TestCase):
    def test_required_areas_are_present(self) -> None:
        text = (BUNDLE / "references" / "content-quality-checklist.md").read_text(
            encoding="utf-8"
        )
        for heading in (
            "## 1. Schema and ID integrity",
            "## 2. Citations and source grounding",
            "## 3. Answer keys and explanations",
            "## 4. Numeric tolerance, units, and significant figures",
            "## 5. Curriculum coverage, teach order, and block budget",
            "## 6. Marks, sections, blueprints, and series volume",
            "## 7. Language coverage and script policy",
            "## 8. Copy and claim compliance",
            "## 9. Technical page integrity",
            "## 10. Accessibility and performance",
            "## 11. Narration (when the artifact includes audio)",
            "## 12. Eval, logging, and content-debt evidence",
        ):
            self.assertIn(heading, text, f"missing checklist section: {heading}")

    def test_checklist_names_the_repo_contracts(self) -> None:
        text = (BUNDLE / "references" / "content-quality-checklist.md").read_text(
            encoding="utf-8"
        )
        for contract in (
            "docs/content-factory/blocks-schema.md",
            "docs/content-factory/architecture.md",
            "docs/specs/evals/spec.md",
            "docs/specs/translation/spec.md",
            "docs/product/features.md",
            "factory/checks.py",
            "factory/lint.py",
            "weak-android",
        ):
            self.assertIn(contract, text)

    def test_anti_patterns_cover_the_required_failures(self) -> None:
        text = (BUNDLE / "references" / "anti-patterns.md").read_text(encoding="utf-8")
        for phrase in (
            "wrong answer key",
            "off-chapter",
            "missing explanation",
            "broken diagram",
            "untranslated leak",
            "marks",
            "CBSE",
            "duplicate topic",
            "thin series",
            "mixed pipeline versions",
        ):
            self.assertIn(phrase.lower(), text.lower())

    def test_report_template_uses_the_suite_scale(self) -> None:
        text = (BUNDLE / "templates" / "content-review-report.md").read_text(
            encoding="utf-8"
        )
        for severity in ("blocker", "major", "minor", "nit", "question", "praise"):
            self.assertIn(severity, text.lower())
        self.assertIn("[severity][content-quality][confidence]", text)
        self.assertIn("Why it matters:", text)
        self.assertIn("Fix:", text)
        self.assertIn("Not reviewed / assumptions", text)


class WiringTests(unittest.TestCase):
    def test_entry_point_routes_to_the_lens(self) -> None:
        text = ENTRY.read_text(encoding="utf-8")
        self.assertIn("review-content-quality", text)
        self.assertIn("content-quality", text.lower())

    def test_suite_readme_lists_the_lens(self) -> None:
        text = SUITE_README.read_text(encoding="utf-8")
        self.assertIn("review-content-quality", text)
        self.assertIn("eight skills", text)
        self.assertIn("seven specialist lenses", text)

    def test_skills_index_lists_the_lens(self) -> None:
        text = SKILLS_README.read_text(encoding="utf-8")
        self.assertIn("content-quality", text)
        self.assertIn("seven specialist lenses", text)

    def test_root_readme_lists_seven_lenses(self) -> None:
        text = ROOT_README.read_text(encoding="utf-8")
        self.assertIn("entry point + seven lenses", text)

    def test_agents_md_mentions_the_lens(self) -> None:
        text = AGENTS_MD.read_text(encoding="utf-8")
        self.assertIn("review-content-quality", text)
        self.assertIn("seven specialist lenses", text)


if __name__ == "__main__":
    unittest.main()
