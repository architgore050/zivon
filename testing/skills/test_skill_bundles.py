"""Tests for scripts/check_skills.py — the deterministic skill-bundle validator.

Run from the repo root:
  python -m unittest discover -s testing/skills -t . -v
"""

from __future__ import annotations

import contextlib
import csv
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
BUNDLE = REPO / "skills" / "skill-creation"


def _load_validator():
    path = REPO / "scripts" / "check_skills.py"
    spec = importlib.util.spec_from_file_location("check_skills", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def codes(findings) -> set[str]:
    return {finding.code for finding in findings}


class GoodBundleTests(unittest.TestCase):
    def test_good_bundle_passes_strict(self) -> None:
        skills, findings = validator.validate_bundle(
            FIXTURES / "good-bundle", strict=True
        )
        self.assertEqual([skill.name for skill in skills], ["good-bundle"])
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_cli_strict_good_bundle_exits_zero(self) -> None:
        exit_code = validator.main(
            ["--strict", "--bundle", str(FIXTURES / "good-bundle"), "--quiet"]
        )
        self.assertEqual(exit_code, 0)


class BadBundleTests(unittest.TestCase):
    def test_bad_bundle_reports_expected_errors(self) -> None:
        _, findings = validator.validate_bundle(FIXTURES / "bad-bundle", strict=True)
        found = codes(findings)
        self.assertIn("name-format", found)
        self.assertIn("description-missing", found)
        self.assertIn("broken-link", found)
        self.assertIn("placeholder", found)
        self.assertTrue(
            all(f.path.name == "SKILL.md" for f in findings if f.level == "error")
        )

    def test_cli_strict_bad_bundle_exits_one(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = validator.main(
                ["--strict", "--bundle", str(FIXTURES / "bad-bundle")]
            )
        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL", buffer.getvalue())


class LegacyBundleTests(unittest.TestCase):
    def test_default_scan_warns_without_failing(self) -> None:
        _, findings = validator.validate_bundle(
            FIXTURES / "legacy-bundle", strict=False
        )
        self.assertEqual(codes(findings), {"no-skill"})
        self.assertTrue(all(f.level == "warning" for f in findings))

    def test_strict_requires_skill_and_readme(self) -> None:
        _, findings = validator.validate_bundle(FIXTURES / "legacy-bundle", strict=True)
        required = [f for f in findings if f.code == "required-file"]
        self.assertEqual(len(required), 1)  # README exists, SKILL.md does not
        self.assertTrue(any("SKILL.md" in f.message for f in required))


class DuplicateNameTests(unittest.TestCase):
    def test_duplicate_names_are_an_error(self) -> None:
        named = [FIXTURES / "duplicate-a", FIXTURES / "duplicate-b"]
        _, findings = validator.check(FIXTURES, named, strict=False)
        duplicates = [f for f in findings if f.code == "duplicate-name"]
        self.assertEqual(len(duplicates), 1)
        self.assertEqual(duplicates[0].level, "error")


class SecretAndPiiTests(unittest.TestCase):
    def _write_bundle(
        self, root: Path, extra_body: str = "", extra_file: str | None = None
    ) -> Path:
        bundle = root / "secret-bundle"
        (bundle / "references").mkdir(parents=True)
        (bundle / "README.md").write_text("# secret-bundle\n", encoding="utf-8")
        (bundle / "references" / "guide.md").write_text(
            "See the guide.\n", encoding="utf-8"
        )
        (bundle / "SKILL.md").write_text(
            "---\n"
            "name: secret-bundle\n"
            "description: A fixture bundle used to prove the validator catches secrets and PII. "
            "Use when testing the scanner.\n"
            "license: MIT\n"
            "---\n\n"
            "# Secret bundle\n\n"
            "Read `references/guide.md` when needed.\n" + extra_body,
            encoding="utf-8",
        )
        if extra_file:
            (bundle / extra_file).write_text("placeholder\n", encoding="utf-8")
        return bundle

    def test_aws_key_is_an_error(self) -> None:
        key = "AKIA" + "IOSFODNN7EXAMPLE"
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._write_bundle(Path(tmp), f"\nkey = {key}\n")
            _, findings = validator.validate_bundle(bundle, strict=False)
            self.assertIn("secret:aws_access_key", codes(findings))

    def test_private_key_block_is_an_error(self) -> None:
        marker = "-----BEGIN " + "PRIVATE KEY-----"
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._write_bundle(Path(tmp), f"\n{marker}\n")
            _, findings = validator.validate_bundle(bundle, strict=False)
            self.assertIn("secret:private_key", codes(findings))

    def test_email_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = self._write_bundle(
                Path(tmp), "\nContact someone@example.com for details.\n"
            )
            _, findings = validator.validate_bundle(bundle, strict=False)
            pii = [f for f in findings if f.code == "possible-pii"]
            self.assertEqual(len(pii), 1)
            self.assertEqual(pii[0].level, "warning")


class StructureTests(unittest.TestCase):
    def test_reference_never_mentioned_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "quiet-bundle"
            (bundle / "references").mkdir(parents=True)
            (bundle / "README.md").write_text("# quiet\n", encoding="utf-8")
            (bundle / "references" / "guide.md").write_text(
                "detail\n", encoding="utf-8"
            )
            (bundle / "SKILL.md").write_text(
                "---\nname: quiet-bundle\ndescription: A bundle that forgets to mention its reference file. "
                "Use when testing progressive disclosure warnings.\nlicense: MIT\n---\n\n# Quiet\n",
                encoding="utf-8",
            )
            _, findings = validator.validate_bundle(bundle, strict=False)
            self.assertIn("reference-unmentioned", codes(findings))

    def test_long_body_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "long-bundle"
            bundle.mkdir()
            (bundle / "README.md").write_text("# long\n", encoding="utf-8")
            body = "\n".join(f"line {i}" for i in range(validator.MAX_BODY_LINES + 5))
            (bundle / "SKILL.md").write_text(
                "---\nname: long-bundle\ndescription: A bundle with an overlong body used to prove the "
                "progressive-disclosure warning fires. Use when testing the line budget.\nlicense: MIT\n---\n\n"
                + body,
                encoding="utf-8",
            )
            _, findings = validator.validate_bundle(bundle, strict=False)
            self.assertIn("body-too-long", codes(findings))

    def test_link_outside_bundle_is_a_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bundle = root / "escape-bundle"
            bundle.mkdir()
            (root / "outside.md").write_text("outside\n", encoding="utf-8")
            (bundle / "README.md").write_text("# escape\n", encoding="utf-8")
            (bundle / "SKILL.md").write_text(
                "---\nname: escape-bundle\ndescription: A bundle whose link escapes its directory, used to "
                "prove the containment warning. Use when testing link checks.\nlicense: MIT\n---\n\n"
                "[outside](../outside.md)\n",
                encoding="utf-8",
            )
            _, findings = validator.validate_bundle(bundle, strict=False)
            self.assertIn("link-outside-bundle", codes(findings))

    def test_strict_warns_when_description_has_no_trigger_phrase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            bundle = Path(tmp) / "no-trigger-bundle"
            bundle.mkdir()
            (bundle / "README.md").write_text("# no trigger\n", encoding="utf-8")
            (bundle / "SKILL.md").write_text(
                "---\nname: no-trigger-bundle\ndescription: A perfectly valid description that explains the "
                "capability in detail but never says which situations should activate it.\nlicense: MIT\n---\n\n"
                "# No trigger\n",
                encoding="utf-8",
            )
            _, findings = validator.validate_bundle(bundle, strict=True)
            self.assertIn("description-no-trigger", codes(findings))


class SkillCreationBundleTests(unittest.TestCase):
    """The bundle is docs, but its catalog and layout are still checkable."""

    REQUIRED = (
        "SKILL.md",
        "README.md",
        "references/source-catalog.md",
        "references/source-catalog.csv",
        "references/search-playbook.md",
        "references/skill-format.md",
        "references/evaluation-rubric.md",
        "references/web-interaction-toolkit.md",
        "references/provenance-and-licensing.md",
        "references/security-and-prompt-injection.md",
        "references/maintenance.md",
        "templates/skill-audit.md",
        "templates/SKILL.md",
        "templates/search-log.md",
        "templates/source-entry.md",
    )

    def test_required_files_exist(self) -> None:
        missing = [name for name in self.REQUIRED if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])
        self.assertTrue((REPO / "scripts" / "check_skills.py").is_file())

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual([skill.name for skill in skills], ["skill-creation"])
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_catalog_csv_is_well_formed(self) -> None:
        path = BUNDLE / "references" / "source-catalog.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
        self.assertEqual(
            reader.fieldnames,
            [
                "source_id",
                "source",
                "url",
                "type",
                "good_for",
                "access_method_tested",
                "auth_rate_limits",
                "license_provenance",
                "last_checked",
                "quality_signal",
                "caveats",
            ],
        )
        self.assertGreaterEqual(len(rows), 40)
        ids = [row["source_id"] for row in rows]
        self.assertEqual(len(ids), len(set(ids)), "duplicate source_id in catalog")
        for row in rows:
            self.assertTrue(row["source"], row)
            self.assertTrue(row["url"].startswith("http"), row)
            self.assertEqual(row["last_checked"], "2026-11-14", row)

    def test_catalog_markdown_and_csv_agree(self) -> None:
        with (BUNDLE / "references" / "source-catalog.csv").open(
            encoding="utf-8"
        ) as handle:
            csv_ids = {row["source_id"] for row in csv.DictReader(handle)}
        markdown = (BUNDLE / "references" / "source-catalog.md").read_text(
            encoding="utf-8"
        )
        missing_from_md = sorted(
            source_id for source_id in csv_ids if f"| {source_id} |" not in markdown
        )
        self.assertEqual(missing_from_md, [])


class CliTests(unittest.TestCase):
    def test_json_output_has_summary(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = validator.main(
                ["--strict", "--bundle", str(FIXTURES / "good-bundle"), "--json"]
            )
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["summary"]["ok"])
        self.assertEqual(payload["summary"]["errors"], 0)
        self.assertEqual(payload["skills"][0]["name"], "good-bundle")

    def test_default_scan_of_fixtures_does_not_fail_on_legacy(self) -> None:
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exit_code = validator.main(["--root", str(FIXTURES), "--quiet"])
        # duplicate-a/duplicate-b share a name, so this scan must fail on the
        # duplicate even though the legacy bundle only warns.
        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
