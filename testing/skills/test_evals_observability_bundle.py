"""Contract tests for the evals-and-observability skill bundle.

Run from the repo root:
  python -m unittest discover -s testing/skills -t .
"""

from __future__ import annotations

import csv
import dataclasses
import importlib.util
import sys
import unittest
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "zivon-evals-and-observability-skills"
MAP_PATH = REPO / "docs" / "specs" / "observability" / "instrumentation-map.csv"


def _load_validator():
    path = REPO / "scripts" / "check_skills.py"
    spec = importlib.util.spec_from_file_location("check_skills_evals_obs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills_evals_obs"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


def _load_checker_template():
    path = BUNDLE / "templates" / "checker.py"
    spec = importlib.util.spec_from_file_location("zivon_eval_checker_template", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["zivon_eval_checker_template"] = module
    spec.loader.exec_module(module)
    return module


class BundleLayoutTests(unittest.TestCase):
    REQUIRED = (
        "README.md",
        "SKILL.md",
        "references/logging-manager.md",
        "references/event-map.md",
        "references/eval-authoring.md",
        "references/eval-store-and-dashboard.md",
        "references/privacy-and-redaction.md",
        "references/review-checklist.md",
        "references/worked-example.md",
        "templates/instrumentation-row.csv",
        "templates/eval-card.yaml",
        "templates/checker.py",
        "templates/eval-run-checklist.md",
        "templates/golden-fixture.md",
    )

    def test_required_files_exist(self) -> None:
        missing = [name for name in self.REQUIRED if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual(
            [skill.name for skill in skills], ["zivon-evals-and-observability-skills"]
        )
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_frontmatter_carries_the_evidence_date(self) -> None:
        text = (BUNDLE / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(text.startswith("---\n"))
        frontmatter = text.split("---", 2)[1]
        fields = yaml.safe_load(frontmatter)
        self.assertEqual(fields["name"], BUNDLE.name)
        self.assertEqual(fields["metadata"]["evidence_date"], "2026-11-14")
        self.assertGreaterEqual(len(fields["description"]), 80)
        self.assertIn("use when", fields["description"].lower())


class TemplateTests(unittest.TestCase):
    def test_eval_card_template_is_a_real_card(self) -> None:
        from evals.models import load_card

        card = load_card(BUNDLE / "templates" / "eval-card.yaml")
        self.assertEqual(card.card_id, "EV-SYN-003")
        self.assertIn("smoke", card.suites)
        self.assertEqual(card.cost_budget["smoke_model_calls"], 0)
        self.assertIsNone(card.llm_judge)

    def test_instrumentation_rows_match_the_map_contract(self) -> None:
        from logging_manager import Severity

        with MAP_PATH.open(encoding="utf-8", newline="") as handle:
            map_reader = csv.DictReader(handle)
            map_header = map_reader.fieldnames
            map_events = {row["event"] for row in map_reader}

        with (BUNDLE / "templates" / "instrumentation-row.csv").open(
            encoding="utf-8", newline=""
        ) as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(reader.fieldnames, map_header)

        self.assertGreaterEqual(len(rows), 1)
        self.assertEqual(len({row["event"] for row in rows}), len(rows))
        valid_privacy = {"L1", "L2", "L3", "CR"}
        for row in rows:
            self.assertTrue(row["component"], row)
            self.assertTrue(row["event"], row)
            self.assertIn(row["severity"], {s.value for s in Severity}, row)
            self.assertIn(row["privacy_class"], valid_privacy, row)
            self.assertNotIn(row["event"], map_events, row)
            self.assertTrue(row["emitter"], row)
            self.assertNotIn(",", row["required_fields"], row)

    def test_checker_template_runs_key_free_and_skips_honestly(self) -> None:
        from evals.config import EvalConfig
        from evals.models import load_card

        module = _load_checker_template()
        cfg = EvalConfig.from_env({})
        card = load_card(BUNDLE / "templates" / "eval-card.yaml")

        context: dict[str, Any] = {}
        issues = module.check_golden_registration(cfg, card, context)
        self.assertEqual(issues, [])

        missing = dataclasses.replace(
            card,
            golden_inputs={
                **card.golden_inputs,
                "topics": ["evals/goldens/topics/does-not-exist"],
            },
        )
        issues = module.check_golden_registration(cfg, missing, {})
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "fatal")
        self.assertIn("does-not-exist", issues[0].message)

        skipped: dict[str, Any] = {}
        empty = dataclasses.replace(
            card, golden_inputs={**card.golden_inputs, "topics": []}
        )
        self.assertEqual(module.check_golden_registration(cfg, empty, skipped), [])
        self.assertIn(module.CHECK_ID, skipped["skipped_checks"])


if __name__ == "__main__":
    unittest.main()
