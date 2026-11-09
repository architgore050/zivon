"""Unit tests for the Per-Block Translation Contract (CP-TRN-001..003) and Logging Shim."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from testing.translation._test_env import ensure_test_dependencies

ensure_test_dependencies()

from factory._logging_shim import (
    Severity,
    clear_recorded_events,
    context_scope,
    current_context,
    delete_subject,
    get_recorded_events,
    log_event,
)
from factory.checks import rule_diagram_svg
import jsonschema
from factory.translate import (
    check_unit_deterministic_invariants,
    extract_diagram_payload,
    extract_sim_strings_from_js,
    extract_translatable_payload,
    reassemble_translated_unit,
    reinject_diagram_svg,
    schema_for_unit,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


class TestBlockContract(unittest.TestCase):
    def setUp(self) -> None:
        self.lesson = json.loads(
            (FIXTURES / "lesson.json").read_text(encoding="utf-8")
        )
        self.blocks = json.loads(
            (FIXTURES / "blocks.json").read_text(encoding="utf-8")
        )["blocks"]

    def test_meta_unit_extraction_and_reassembly(self) -> None:
        page_js = (
            'ZivonSim.register("b-06", {\n'
            "  draw: function(ctx) {\n"
            '    var lbl = ctx.t_str("slope_lbl", "Slope = acceleration");\n'
            '    var rd = ctx.t_str("readout_lbl", "Velocity v (m/s)");\n'
            "  }\n"
            "});"
        )
        sim_strings = extract_sim_strings_from_js(page_js)
        self.assertEqual(
            sim_strings,
            {
                "b-06": {
                    "slope_lbl": "Slope = acceleration",
                    "readout_lbl": "Velocity v (m/s)",
                }
            },
        )
        payload = extract_translatable_payload(
            "b-00-meta", "meta", self.lesson, sim_strings=sim_strings
        )
        schema, name = schema_for_unit("b-00-meta", "meta", self.lesson)
        self.assertEqual(name, "translated_meta")

        translated_payload = {
            "title": "गति (motion): वस्तुएँ कैसे चलती हैं",
            "objectives": [
                f"उद्देश्य {i}: {o}" for i, o in enumerate(payload["objectives"])
            ],
            "sections": [
                {
                    "id": s["id"],
                    "title": f"अनुभाग: {s['title']}",
                    "paragraphs": [f"विवरण: {p}" for p in s["paragraphs"]],
                }
                for s in payload["sections"]
            ],
            "glossary": [
                {
                    "term": f"{g['term']} (हिंदी)",
                    "definition": f"परिभाषा: {g['definition']}",
                }
                for g in payload["glossary"]
            ],
            "sim_strings": {
                "b-06": {
                    "slope_lbl": "ढाल = त्वरण",
                    "readout_lbl": "वेग v (m/s)",
                }
            },
        }
        jsonschema.Draft7Validator(schema).validate(translated_payload)
        errs = check_unit_deterministic_invariants(
            locale="hi",
            unit_id="b-00-meta",
            unit_type="meta",
            source_payload=payload,
            translated_payload=translated_payload,
        )
        self.assertEqual(errs, [])
        reassembled = reassemble_translated_unit(
            "b-00-meta", "meta", self.lesson, translated_payload
        )
        self.assertEqual(reassembled["title"], translated_payload["title"])
        self.assertEqual(
            [s["id"] for s in reassembled["sections"]],
            [s["id"] for s in self.lesson["sections"]],
        )

    def test_diagram_svg_extraction_skips_math_symbols_and_reinjects_data_i18n(
        self,
    ) -> None:
        svg = (
            '<svg viewBox="0 0 320 220" aria-label="Velocity-time graph" xmlns="http://www.w3.org/2000/svg">'
            '<line x1="20" y1="180" x2="280" y2="40" stroke="#1F3A9E" stroke-width="2"/>'
            '<text x="150" y="205">t (s)</text>'
            '<text x="15" y="100">v (m/s)</text>'
            '<text x="10" y="20">10 N</text>'
            '<text x="120" y="70">Slope = acceleration</text>'
            '<text x="140" y="130">Area under line = displacement</text>'
            "</svg>"
        )
        diagram_block = {
            "id": "b-05",
            "type": "diagram",
            "citations": [{"claim_id": "claim-06"}],
            "spec": {
                "svg": svg,
                "caption": "The slope of a velocity-time graph gives acceleration.",
            },
        }
        payload = extract_diagram_payload(diagram_block)
        extracted_sources = [item["source"] for item in payload["svg_texts"]]
        self.assertEqual(
            extracted_sources,
            ["Slope = acceleration", "Area under line = displacement"],
        )
        self.assertEqual(payload["svg_aria_label"], "Velocity-time graph")

        translated_payload = {
            "caption": "वेग-समय ग्राफ़ की ढाल त्वरण (acceleration) देती है।",
            "svg_aria_label": "वेग-समय ग्राफ़",
            "svg_texts": [
                {"id": "t-0", "text": "ढाल = त्वरण"},
                {"id": "t-1", "text": "रेखा के नीचे का क्षेत्रफल = विस्थापन"},
            ],
        }
        reinjected = reinject_diagram_svg("b-05", svg, translated_payload)
        self.assertIn('data-i18n="b-05.svg_texts.t-0"', reinjected)
        self.assertIn("ढाल = त्वरण", reinjected)
        self.assertIn(">t (s)<", reinjected)
        self.assertIn(">10 N<", reinjected)
        reassembled = reassemble_translated_unit(
            "b-05", "diagram", diagram_block, translated_payload
        )
        self.assertEqual(rule_diagram_svg([reassembled]), [])

    def test_diagram_svg_rejects_angle_bracket_injection(self) -> None:
        svg = '<svg viewBox="0 0 100 100"><text x="10" y="20">Uniform motion</text></svg>'
        block = {
            "id": "b-05",
            "type": "diagram",
            "citations": [{"claim_id": "claim-01"}],
            "spec": {"svg": svg, "caption": "Uniform motion diagram."},
        }
        payload = extract_diagram_payload(block)
        bad_translated = {
            "caption": "एकसमान गति का चित्र।",
            "svg_aria_label": "",
            "svg_texts": [{"id": "t-0", "text": "<script>alert(1)</script>"}],
        }
        errs = check_unit_deterministic_invariants(
            locale="hi",
            unit_id="b-05",
            unit_type="diagram",
            source_payload=payload,
            translated_payload=bad_translated,
        )
        self.assertTrue(any("forbidden '<' or '>'" in e for e in errs))

    def test_mcq_and_numeric_check_locks_preserve_grading_invariants(self) -> None:
        mcq_block = next(b for b in self.blocks if b["id"] == "b-04")
        mcq_trans = {
            "question": "किस भौतिक राशि को वेग में परिवर्तन की दर कहा जाता है?",
            "options": [
                "चाल (Speed)",
                "त्वरण (Acceleration)",
                "दूरी (Distance)",
                "बल (Force)",
            ],
            "explanation": "त्वरण समय के साथ वेग परिवर्तन की दर है; इसका SI मात्रक m/s2 है।",
            "expected_understanding": "विद्यार्थी त्वरण को पहचान सकता है।",
        }
        reassembled_mcq = reassemble_translated_unit(
            "b-04", "check", mcq_block, mcq_trans
        )
        self.assertEqual(reassembled_mcq["spec"]["answer_index"], 1)
        self.assertEqual(
            reassembled_mcq["spec"]["answer"], "त्वरण (Acceleration)"
        )
        self.assertEqual(reassembled_mcq["citations"], mcq_block["citations"])

        num_block = next(b for b in self.blocks if b["id"] == "b-07")
        num_payload = extract_translatable_payload("b-07", "check", num_block)
        self.assertNotIn("answer", num_payload)
        num_trans = {
            "question": "एक साइकिल 20 s में 100 m चलती है। m/s में औसत चाल क्या है?",
            "explanation": "औसत चाल कुल दूरी बटा कुल समय है: 100 / 20।",
            "expected_understanding": "विद्यार्थी औसत चाल निकाल सकता है।",
        }
        reassembled_num = reassemble_translated_unit(
            "b-07", "check", num_block, num_trans
        )
        self.assertEqual(reassembled_num["spec"]["answer"], "5")

    def test_simulation_control_label_budget_and_numeric_locks(self) -> None:
        sim_block = next(b for b in self.blocks if b["id"] == "b-06")
        sim_payload = extract_translatable_payload(
            "b-06", "simulation", sim_block
        )
        overlong = {
            "title": "एकसमान त्वरण के साथ गति",
            "description": "त्वरण बदलें और देखें कि बिंदु कैसे चलता है।",
            "learning_goal": "त्वरण और चाल के संबंध को समझें।",
            "controls": [
                {
                    "id": "a",
                    "label": "यह नियंत्रण लेबल बत्तीस अक्षरों की सीमा से बहुत अधिक लंबा है (m/s2)",
                }
            ],
            "default_behaviour": "बिंदु विराम से शुरू होकर दाईं ओर तेज़ी से बढ़ता है।",
        }
        errs = check_unit_deterministic_invariants(
            locale="hi",
            unit_id="b-06",
            unit_type="simulation",
            source_payload=sim_payload,
            translated_payload=overlong,
        )
        self.assertTrue(any("max 32" in e for e in errs))

        valid_sim = dict(overlong)
        valid_sim["controls"] = [{"id": "a", "label": "त्वरण a (m/s2)"}]
        reassembled = reassemble_translated_unit(
            "b-06", "simulation", sim_block, valid_sim
        )
        ctrl = reassembled["spec"]["controls"][0]
        self.assertEqual(ctrl["label"], "त्वरण a (m/s2)")
        self.assertEqual(ctrl["min"], -5)
        self.assertEqual(ctrl["max"], 5)
        self.assertEqual(ctrl["step"], 0.5)
        self.assertEqual(ctrl["initial"], 2)

    def test_logging_shim_json_schema_v1_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            old_log_dir = os.environ.get("ZIVON_LOG_DIR")
            os.environ["ZIVON_LOG_DIR"] = tmp
            clear_recorded_events()
            try:
                with context_scope(
                    run_id="r-123", session_id="s-999", request_id="req-1"
                ):
                    self.assertEqual(current_context()["run_id"], "r-123")
                    log_event(
                        "translator.translate.ok",
                        {
                            "src_lang": "en",
                            "tgt_lang": "hi",
                            "token": "secret-token-value",
                            "transcript_text": "hello student speech",
                            "note": "key sk-1234567890abcdef inside text",
                        },
                        severity=Severity.INFO,
                        latency_ms=42,
                        stage="10a-translate",
                    )
                events = get_recorded_events()
                self.assertEqual(len(events), 1)
                evt = events[0]
                self.assertEqual(evt["component"], "translator")
                self.assertEqual(evt["run_id"], "r-123")
                self.assertEqual(evt["stage"], "10a-translate")
                self.assertEqual(evt["fields"]["token"], "[REDACTED:key-denylist]")
                self.assertEqual(
                    evt["fields"]["transcript_text"], "[REDACTED:key-denylist]"
                )
                self.assertIn("[REDACTED:api_key]", evt["fields"]["note"])

                del_res = delete_subject("s-999")
                self.assertEqual(del_res["deleted"], 1)
            finally:
                if old_log_dir is None:
                    os.environ.pop("ZIVON_LOG_DIR", None)
                else:
                    os.environ["ZIVON_LOG_DIR"] = old_log_dir


if __name__ == "__main__":
    unittest.main()
