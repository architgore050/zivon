"""Contract tests for the pipeline-engineering skill bundle.

The validator proves format, links, placeholders, and secrets. These tests
also prove the bundle still carries the contracts it exists to teach: all
stage ids, every gate/catcher pair, the key-free commands, and the dated
provenance.

Run from the repo root:
  python -m unittest discover -s testing/skills -t .
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "zivon-pipeline-engineering-skills"
VALIDATOR = REPO / "scripts" / "check_skills.py"

STAGE_IDS = (
    "00-ingest",
    "01-locate",
    "02-generate",
    "03-check",
    "04-repair",
    "05-interactive",
    "06-render",
    "07-perf",
    "08-fixloop",
    "09-review",
    "10-reviewfix",
    "10a-translate",
    "10b-transcheck",
    "10c-transrepair",
    "10d-transrender",
    "11-link",
    "12-narration",
)

REQUIRED_FILES = (
    "SKILL.md",
    "README.md",
    "references/stage-contracts.md",
    "references/gates-and-catchers.md",
    "references/artifacts-and-schemas.md",
    "references/rendering-and-publishing.md",
    "references/quality-and-evals.md",
    "references/logging.md",
    "references/commands.md",
    "templates/stage-change-checklist.md",
    "templates/artifact-contract.md",
    "templates/eval-plan.md",
    "templates/pipeline-debug-log.md",
)


def _load_validator():
    spec = importlib.util.spec_from_file_location("check_skills", VALIDATOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _read(relative: str) -> str:
    return (BUNDLE / relative).read_text(encoding="utf-8")


class BundleStructureTests(unittest.TestCase):
    def test_required_files_exist(self) -> None:
        missing = [name for name in REQUIRED_FILES if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual([skill.name for skill in skills], [BUNDLE.name])
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_cli_strict_validation_exits_zero(self) -> None:
        result = subprocess.run(
            [sys.executable, str(VALIDATOR), "--strict", "--bundle", str(BUNDLE)],
            cwd=REPO,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK: 1 skill(s), 0 error(s), 0 warning(s)", result.stdout)

    def test_no_placeholder_tokens_anywhere(self) -> None:
        offenders: list[str] = []
        for path in BUNDLE.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for token in ("TODO", "TBD", "FIXME", "XXX"):
                if token in text:
                    offenders.append(f"{path.relative_to(BUNDLE)}: {token}")
        self.assertEqual(offenders, [])

    def test_no_runtime_dependency_or_secret_file(self) -> None:
        forbidden = {"requirements.txt", "pyproject.toml", "setup.py", ".env"}
        present = sorted(p.name for p in BUNDLE.rglob("*") if p.name in forbidden)
        self.assertEqual(present, [])


class StageContractTests(unittest.TestCase):
    def test_every_stage_id_is_documented(self) -> None:
        text = _read("references/stage-contracts.md")
        missing = [stage for stage in STAGE_IDS if f"`{stage}`" not in text]
        self.assertEqual(missing, [])

    def test_every_stage_has_an_owner_module(self) -> None:
        text = _read("references/stage-contracts.md")
        self.assertGreaterEqual(text.count("**Owner:**"), len(STAGE_IDS))

    def test_resume_and_fingerprint_rules_are_present(self) -> None:
        text = _read("references/stage-contracts.md")
        for needle in (
            "Fingerprint guard",
            "stage_ok",
            "PIPELINE_VERSION",
            "--fresh",
            "--stages",
            "load_stage_output",
        ):
            self.assertIn(needle, text)


class GateContractTests(unittest.TestCase):
    def test_gate_catcher_pairs_are_documented(self) -> None:
        text = _read("references/gates-and-catchers.md")
        for pair in ("03-check", "04-repair", "07-perf", "08-fixloop", "09-review"):
            self.assertIn(pair, text)
        for pair in ("10b-transcheck", "10c-transrepair", "12-narration"):
            self.assertIn(pair, text)

    def test_no_whole_pipeline_rerun_rule_is_explicit(self) -> None:
        text = _read("references/gates-and-catchers.md")
        self.assertIn("never re-runs an upstream stage", text)
        self.assertIn("stall_rounds", text)
        self.assertIn("2 * fatals + majors", text)

    def test_severity_ladder_and_way_out_are_documented(self) -> None:
        text = _read("references/gates-and-catchers.md")
        for needle in ("fatal", "major", "minor", "unverified:"):
            self.assertIn(needle, text)


class ArtifactAndPublishTests(unittest.TestCase):
    def test_artifact_contracts_are_documented(self) -> None:
        text = _read("references/artifacts-and-schemas.md")
        for needle in (
            "status.json",
            "run_report.json",
            "calls_ledger.jsonl",
            "issues_ledger.jsonl",
            "GENERATED",
            "BLOCKS",
            "manifest.json",
            "courses.js",
            "narration-manifest.json",
            "PIPELINE_VERSION",
        ):
            self.assertIn(needle, text)

    def test_publish_and_integrity_rules_are_documented(self) -> None:
        text = _read("references/rendering-and-publishing.md")
        for needle in (
            "06-render",
            "10d-transrender",
            "11-link",
            "stale same-chapter duplicates",
            "courses.js",
            "sitemap.xml",
            "robots.txt",
            "CSP",
        ):
            self.assertIn(needle, text)


class QualityAndLoggingTests(unittest.TestCase):
    def test_eval_boundary_and_commands_are_documented(self) -> None:
        text = _read("references/quality-and-evals.md")
        for needle in (
            "testing/",
            "evals/",
            "EV-CUR-001",
            "EV-REV-001",
            "EV-REV-002",
            "deterministic-first",
            "python -m evals run --suite smoke --mock",
        ):
            self.assertIn(needle, text)

    def test_known_gaps_are_dated_and_labeled(self) -> None:
        text = _read("references/quality-and-evals.md")
        self.assertIn("Known eval/quality gaps", text)
        self.assertIn("Re-verify", text)

    def test_logging_contract_is_documented(self) -> None:
        text = _read("references/logging.md")
        for needle in (
            "log_event",
            "run_id",
            "instrumentation-map.csv",
            "ErrorClass",
            "factory.stage.ok",
            "factory.repair.exhausted",
        ):
            self.assertIn(needle, text)


class CommandTests(unittest.TestCase):
    def test_key_free_commands_are_exact(self) -> None:
        text = _read("references/commands.md")
        for command in (
            "python -m unittest discover -s testing/content_factory/unit -t .",
            "python -m unittest discover -s testing/evals -t .",
            "python -m evals run --suite smoke --mock",
            "python -m evals run --suite smoke --fail-on-regression",
            "python -m evals calibrate --stage all --mock",
            "ruff check .",
            "ruff format --check .",
            "python3 scripts/check_specs.py",
        ):
            self.assertIn(command, text)

    def test_targeted_stage_reruns_are_documented(self) -> None:
        text = _read("references/commands.md")
        self.assertIn("--stages 06-render,11-link", text)
        self.assertIn("--stages 03-check,04-repair", text)
        self.assertIn("--stages 11-link,12-narration", text)

    def test_mock_live_boundary_is_explicit(self) -> None:
        text = _read("references/commands.md")
        self.assertIn("Key-free by default", text)
        self.assertIn("No live calls in parallel agent work", text)


class ProvenanceTests(unittest.TestCase):
    def test_evidence_date_and_pipeline_version_are_recorded(self) -> None:
        skill = _read("SKILL.md")
        readme = _read("README.md")
        self.assertIn('evidence_date: "2026-11-14"', skill)
        self.assertIn('pipeline_version: "9"', skill)
        self.assertIn("2026-11-14", readme)

    def test_external_sources_are_linked_and_counted(self) -> None:
        skill = _read("SKILL.md")
        expected_urls = (
            "https://agentskills.io/specification",
            "https://agentskills.io/skill-creation/evaluating-skills",
            "https://www.anthropic.com/engineering/building-effective-agents",
            "https://www.w3.org/TR/WCAG22/",
            "https://json-schema.org/draft/2020-12/json-schema-core",
        )
        for url in expected_urls:
            self.assertIn(url, skill)
        self.assertGreaterEqual(skill.count("https://"), len(expected_urls))

    def test_readme_is_the_layout_source_of_truth(self) -> None:
        readme = _read("README.md")
        for needle in ("Layout", "Read order", "Provenance", "Maintenance", "Licence"):
            self.assertIn(needle, readme)


if __name__ == "__main__":
    unittest.main()
