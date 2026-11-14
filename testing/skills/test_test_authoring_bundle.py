"""Contract tests for the `zivon-test-authoring-skills` bundle.

The bundle is documentation, but its layout and progressive-disclosure contract
are checkable: strict validation, required files, every reference/template
mentioned from `SKILL.md`, a dated evidence block, and no placeholder tokens.

Run from the repo root:
  python -m unittest discover -s testing/skills -t .
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "zivon-test-authoring-skills"

REQUIRED = (
    "SKILL.md",
    "README.md",
    "references/test-layers.md",
    "references/fixtures-and-goldens.md",
    "references/mocking-vendor-seams.md",
    "references/browser-and-a11y-tests.md",
    "references/evals-vs-tests.md",
    "references/ci-and-path-guards.md",
    "references/test-review-checklist.md",
    "references/worked-example-voice-contract.md",
    "templates/test-plan.md",
    "templates/test-case.md",
    "templates/fixture-manifest.md",
    "templates/browser-test-checklist.md",
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


class TestAuthoringBundleTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        missing = [name for name in REQUIRED if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])
        self.assertTrue((REPO / "scripts" / "check_skills.py").is_file())

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual([skill.name for skill in skills], [BUNDLE.name])
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_cli_strict_exits_zero(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            exit_code = validator.main(["--strict", "--bundle", str(BUNDLE), "--quiet"])
        self.assertEqual(exit_code, 0)

    def test_frontmatter_records_owner_version_and_evidence_date(self) -> None:
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        header = text.split("---", 2)[1]
        self.assertIn("owner: zivon", header)
        # Shape, not the literal values: bumping the version or re-verifying the
        # evidence date is maintenance, not a test change.
        self.assertRegex(header, r'(?m)^\s+version: "\d+\.\d+"$')
        self.assertRegex(header, r'(?m)^\s+evidence_date: "\d{4}-\d{2}-\d{2}"$')

    def test_skill_md_points_to_every_reference_and_template(self) -> None:
        body = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        for name in REQUIRED:
            if name.startswith(("references/", "templates/")):
                self.assertIn(
                    name,
                    body,
                    f"{name} is not mentioned from SKILL.md; it will never be loaded",
                )

    def test_skill_md_states_the_test_eval_boundary(self) -> None:
        body = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("testing/", body)
        self.assertIn("evals/", body)
        self.assertIn("python -m evals run --suite smoke --mock", body)

    def test_worked_example_includes_failure_proof_and_scope_limits(self) -> None:
        text = (BUNDLE / "references" / "worked-example-voice-contract.md").read_text(
            encoding="utf-8"
        )
        lowered = text.lower()
        for marker in ("mutation", "does not prove", "anti-pattern"):
            self.assertIn(marker, lowered)

    def test_templates_are_usable_artifacts(self) -> None:
        for name in REQUIRED:
            if not name.startswith("templates/"):
                continue
            text = (BUNDLE / name).read_text(encoding="utf-8")
            self.assertIn("# ", text, f"{name} has no heading")
            self.assertIn("- [ ]", text, f"{name} has no checklist items")

    def test_bundle_has_no_placeholder_tokens(self) -> None:
        for path in sorted(BUNDLE.rglob("*.md")):
            text = path.read_text(encoding="utf-8")
            match = validator.PLACEHOLDER_RE.search(text)
            if match is not None:
                self.fail(
                    f"{path.relative_to(REPO)} contains placeholder {match.group(0)!r}"
                )


if __name__ == "__main__":
    unittest.main()
