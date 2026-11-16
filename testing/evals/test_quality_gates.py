"""Tests for the P4 quality gates: a11y, numeric, glossary, publish integrity,
and the additive eval-card schema extension (Q-5)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from evals.checkers import (
    a11y_checks,
    glossary_checks,
    numeric_checks,
    publish_checks,
)
from evals.config import EvalConfig
from evals.models import EVAL_CARD_SCHEMA, EvalCard, load_all_cards, validate_schema

REPO_ROOT = Path(__file__).resolve().parents[2]


def _card(
    card_id: str, topics: list[str], stage: str = "00-ingest..11-link"
) -> EvalCard:
    return EvalCard(
        card_id=card_id,
        version=1,
        title="quality gate fixture",
        stage=stage,
        agent_role="End-to-End Pipeline",
        suites=["smoke"],
        golden_inputs={
            "topics": topics,
            "seeded_defects": [],
            "source_catalog_ref": "sources/catalog.json",
        },
        deterministic_checks=[],
        llm_judge=None,
        thresholds={},
        cost_budget={},
    )


GOLDEN_TOPICS = [
    "evals/goldens/topics/class-9-motion",
    "evals/goldens/topics/class-11-motion-in-a-straight-line",
]


class TestStaticA11y(unittest.TestCase):
    def test_clean_page_has_no_blocking_findings(self) -> None:
        html = """
        <!doctype html><html lang="en"><head><title>Motion</title></head>
        <body><main><h1>Motion</h1>
        <img src="x.png" alt="A block on a table">
        <button>Start</button>
        <label>Speed <input type="number" value="5"></label>
        <section class="zn-sim" aria-label="Net force">
          <canvas width="10" height="10" tabindex="0"></canvas>
          <p class="zn-sim-desc">Adjust the forces.</p>
          <input type="range" aria-label="Force">
          <p class="zn-sim-read" aria-live="polite">4 N</p>
        </section>
        <fieldset class="zn-check"><legend>Question</legend>
          <label><input type="radio" name="q"> A</label>
          <p class="zn-check-feedback" aria-live="polite"></p>
        </fieldset>
        </main></body></html>
        """
        findings = a11y_checks.audit_html(html)
        blocking = [f for f in findings if f.impact in ("critical", "serious")]
        self.assertEqual(blocking, [])

    def test_common_failures_are_reported_at_the_right_impact(self) -> None:
        html = """
        <html><body><h2>No lang, no title, no h1</h2>
        <img src="x.png">
        <button></button>
        <input type="text">
        <a href="#x"></a>
        <canvas></canvas>
        <div id="dup"></div><div id="dup"></div>
        <a href="#y" tabindex="3">jump</a>
        </body></html>
        """
        findings = {f.rule: f.impact for f in a11y_checks.audit_html(html)}
        self.assertEqual(findings.get("html-has-lang"), "serious")
        self.assertEqual(findings.get("document-title"), "serious")
        self.assertEqual(findings.get("image-alt"), "critical")
        self.assertEqual(findings.get("button-name"), "critical")
        self.assertEqual(findings.get("label"), "critical")
        self.assertEqual(findings.get("link-name"), "serious")
        self.assertEqual(findings.get("canvas-name"), "serious")
        self.assertEqual(findings.get("duplicate-id"), "serious")
        self.assertEqual(findings.get("tabindex-positive"), "serious")

    def test_hidden_and_submit_inputs_do_not_require_an_explicit_label(self) -> None:
        html = """
        <html lang="en"><head><title>t</title></head><body><main><h1>x</h1>
        <input type="hidden" name="answer" value="5">
        <input type="submit" value="Send">
        </main></body></html>
        """
        findings = a11y_checks.audit_html(html)
        self.assertEqual([f for f in findings if f.rule == "label"], [])

    def test_golden_pages_have_no_blocking_findings(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-VIS-002", GOLDEN_TOPICS, "05-interactive..06-render")
        context: dict = {}
        issues = a11y_checks.check_static_a11y(cfg, card, context)
        blocking = [i for i in issues if i.severity in ("fatal", "major")]
        self.assertEqual(blocking, [])
        self.assertGreaterEqual(context["metrics"]["a11y_pages_audited"], 2)

    def test_axe_check_skips_honestly_when_axe_is_absent(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-VIS-002", GOLDEN_TOPICS, "05-interactive..06-render")
        context: dict = {}
        with mock.patch.object(a11y_checks, "_resolve_axe_js", return_value=None):
            issues = a11y_checks.check_axe_serious_critical(cfg, card, context)
        self.assertEqual(issues, [])
        self.assertIn(a11y_checks.AXE_CHECK_ID, context["skipped_checks"])


class TestNumericGate(unittest.TestCase):
    def test_recompute_gate_catches_a_planted_error(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-SYN-003", GOLDEN_TOPICS[:2], "02-generate.blocks..04-repair")
        context: dict = {}
        issues = numeric_checks.check_numeric_recompute(cfg, card, context)
        self.assertEqual(issues, [])
        self.assertTrue(context["metrics"]["numeric_mutation_caught"])

    def test_way_out_contract_holds_on_goldens(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-SYN-003", GOLDEN_TOPICS[:2], "02-generate.blocks..04-repair")
        context: dict = {}
        issues = numeric_checks.check_numeric_way_out(cfg, card, context)
        self.assertEqual(issues, [])
        self.assertGreaterEqual(context["metrics"]["numeric_unverified"], 0)


class TestGlossaryGate(unittest.TestCase):
    def test_launch_locales_are_complete(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-E2E-002", GOLDEN_TOPICS)
        context: dict = {}
        issues = glossary_checks.check_launch_locale_coverage(cfg, card, context)
        self.assertEqual(issues, [])
        self.assertEqual(
            context["metrics"]["glossary_terms_total"],
            context["metrics"]["glossary_terms_launch_complete"],
        )

    def test_page_coverage_passes_for_promised_locales(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-E2E-002", GOLDEN_TOPICS)
        context: dict = {}
        issues = glossary_checks.check_page_glossary_coverage(cfg, card, context)
        self.assertEqual(issues, [])
        self.assertIn("hi", context["metrics"]["glossary_promised_locales"])


class TestPublishIntegrity(unittest.TestCase):
    def _write_tree(self, root: Path, course_js: str) -> None:
        (root / "courses").mkdir(parents=True)
        (root / "courses.js").write_text(course_js, encoding="utf-8")

    def test_published_tree_has_no_blocking_breakage(self) -> None:
        cfg = EvalConfig.from_env({})
        card = _card("EV-E2E-002", GOLDEN_TOPICS)
        context: dict = {}
        issues = publish_checks.check_catalogue_integrity(cfg, card, context)
        self.assertEqual([i for i in issues if i.severity in ("fatal", "major")], [])
        self.assertGreaterEqual(context["metrics"]["catalogue_entries"], 1)

    def test_an_href_that_does_not_resolve_is_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            frontend = Path(td)
            self._write_tree(
                frontend,
                'window.ZIVON_COURSES = [{"href": "courses/nope/index.html"}];',
            )
            cfg = EvalConfig.from_env({"ZIVON_FRONTEND_DIR": str(frontend)})
            issues = publish_checks.check_catalogue_integrity(
                cfg, _card("EV-E2E-002", GOLDEN_TOPICS), {}
            )
            self.assertTrue(any(i.severity == "fatal" for i in issues))
            self.assertIn("does not resolve", issues[0].message)

    def test_a_promised_locale_route_must_exist(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            frontend = Path(td)
            self._write_tree(
                frontend,
                'window.ZIVON_COURSES = [{"href": "courses/c9/motion/index.html"}];',
            )
            topic = frontend / "courses" / "c9" / "motion"
            topic.mkdir(parents=True)
            (topic / "index.html").write_text("<html></html>", encoding="utf-8")
            (topic / "manifest.json").write_text(
                json.dumps(
                    {
                        "course_id": "c9",
                        "class": 9,
                        "topic_slug": "motion",
                        "title": "Motion",
                        "locales_available": ["en", "hi"],
                    }
                ),
                encoding="utf-8",
            )
            cfg = EvalConfig.from_env({"ZIVON_FRONTEND_DIR": str(frontend)})
            issues = publish_checks.check_catalogue_integrity(
                cfg, _card("EV-E2E-002", GOLDEN_TOPICS), {}
            )
            fatal = [i for i in issues if i.severity == "fatal"]
            self.assertTrue(fatal)
            self.assertTrue(any("hi/index.html" in i.message for i in fatal))


class TestCardSchemaExtension(unittest.TestCase):
    def _base_card(self) -> dict:
        return yaml.safe_load(
            (REPO_ROOT / "evals" / "cards" / "EV-SYN-003.yaml").read_text(
                encoding="utf-8"
            )
        )

    def test_new_prefixes_and_roles_validate(self) -> None:
        for card_id, role, stage in [
            ("EV-ASM-001", "Assessment Author", "A3-practice-items"),
            ("EV-EXM-001", "Exam Ingest Curator", "E1-ingest"),
            ("EV-SER-001", "Series Assembler", "E3-series"),
            ("EV-ASM-002", "Speaking Rubric Author", "A1-syllabus..A6-publish-export"),
        ]:
            raw = self._base_card()
            raw["card_id"] = card_id
            raw["agent_role"] = role
            raw["stage"] = stage
            with self.subTest(card_id=card_id):
                validate_schema(raw, EVAL_CARD_SCHEMA, card_id)

    def test_unknown_prefix_or_role_still_fails(self) -> None:
        raw = self._base_card()
        raw["card_id"] = "EV-NOPE-001"
        with self.assertRaises(ValueError):
            validate_schema(raw, EVAL_CARD_SCHEMA, "bad-prefix")
        raw = self._base_card()
        raw["agent_role"] = "Not A Role"
        with self.assertRaises(ValueError):
            validate_schema(raw, EVAL_CARD_SCHEMA, "bad-role")

    def test_old_cards_stay_valid(self) -> None:
        cards = load_all_cards(EvalConfig.from_env({}).cards_dir)
        for card in cards.values():
            validate_schema(card.raw, EVAL_CARD_SCHEMA, card.card_id)


if __name__ == "__main__":
    unittest.main()
