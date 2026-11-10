"""Unit tests for Stage 10b-transcheck (9 deterministic rules + LLM judge) and Stage 10c-transrepair."""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from http.server import ThreadingHTTPServer

from testing.translation._test_env import (
    ensure_test_dependencies,
    install_translation_env,
    restore_translation_env,
)

ensure_test_dependencies()

from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from factory.transcheck import (
    normalize_reviewer_issues,
    rule_trans_citations,
    rule_trans_length_budget,
    rule_trans_mcq_integrity,
    rule_trans_numbers,
    rule_trans_placeholders,
    rule_trans_schema,
    rule_trans_script_purity,
    rule_trans_svg_safety,
    rule_trans_units_and_symbols,
)
from factory.transcheck import (
    run as transcheck_run,
)
from factory.translate import run as translate_run
from factory.transrepair import run_one_round
from testing.translation.mock_translation_node import (
    MockTranslationState,
    start_translation_mock,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


class TestTranscheckRulesAndRepair(unittest.TestCase):
    server: ThreadingHTTPServer
    base_url: str
    state: MockTranslationState

    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.base_url, cls.state = start_translation_mock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-transcheck-"))
        self.saved_env = install_translation_env(self.base_url)
        self.state.calls.clear()
        self.state.scripted_review_issues.clear()
        self.state.scripted_bad_unit_first_attempt.clear()

        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"]["runs"] = str(self.tmp / "runs")
        base["paths"]["text_cache"] = str(self.tmp / "cache")
        base["translation"]["enabled"] = True
        base["translation"]["target_locales"] = ["hi", "hi-Latn"]
        cfg_path = self.tmp / "config.json"
        cfg_path.write_text(json.dumps(base), encoding="utf-8")
        self.cfg = load_config(cfg_path)
        self.lesson = json.loads((FIXTURES / "lesson.json").read_text(encoding="utf-8"))
        self.blocks = json.loads((FIXTURES / "blocks.json").read_text(encoding="utf-8"))
        self.ground_truth = json.loads(
            (FIXTURES / "gt.json").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        restore_translation_env(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_all_nine_deterministic_rules_catch_violations(self) -> None:
        en_blocks = copy.deepcopy(self.blocks["blocks"])
        b_text = copy.deepcopy(en_blocks[0])
        b_ex = copy.deepcopy(en_blocks[2])
        b_mcq = copy.deepcopy(en_blocks[3])
        b_diag = copy.deepcopy(en_blocks[4])
        b_sim = copy.deepcopy(en_blocks[5])

        # R1: rule_trans_schema (empty paragraph violates BLOCKS schema)
        bad_blocks = copy.deepcopy(en_blocks)
        bad_blocks[0]["type"] = "invalid_type"
        self.assertTrue(
            rule_trans_schema(self.lesson, en_blocks, self.lesson, bad_blocks)
        )

        # R2: rule_trans_citations (mutated claim_id)
        bad_cit = copy.deepcopy(b_text)
        bad_cit["citations"] = [{"claim_id": "claim-99"}]
        issues_r2 = rule_trans_citations([b_text], [bad_cit])
        self.assertEqual(len(issues_r2), 1)
        self.assertEqual(issues_r2[0]["severity"], "fatal")

        # R3: rule_trans_numbers (Devanagari numeral + altered number)
        bad_num = copy.deepcopy(b_ex)
        bad_num["spec"]["problem"] = "एक वस्तु ५ s में 99 m/s की चाल प्राप्त करती है।"
        issues_r3 = rule_trans_numbers(self.lesson, [b_ex], self.lesson, [bad_num])
        self.assertGreaterEqual(len(issues_r3), 2)

        # R4: rule_trans_units_and_symbols (dropped equation / SI unit)
        bad_unit = copy.deepcopy(b_ex)
        bad_unit["spec"]["steps"][1]["detail"] = "यहाँ सूत्र हटा दिया गया है।"
        issues_r4 = rule_trans_units_and_symbols(self.ground_truth, [b_ex], [bad_unit])
        self.assertTrue(issues_r4)

        # R5: rule_trans_mcq_integrity (answer string does not match options[answer_index])
        bad_mcq = copy.deepcopy(b_mcq)
        bad_mcq["spec"]["options"] = ["चाल", "त्वरण", "दूरी", "बल"]
        bad_mcq["spec"]["answer"] = "दूरी"
        issues_r5 = rule_trans_mcq_integrity([b_mcq], [bad_mcq])
        self.assertTrue(issues_r5)

        # R6: rule_trans_script_purity (Devanagari in hi-Latn and English echo in hi)
        bad_hinglish = copy.deepcopy(b_text)
        bad_hinglish["spec"]["paragraphs"][0] = "Yeh गति hai."
        issues_r6a = rule_trans_script_purity("hi-Latn", self.lesson, [bad_hinglish])
        self.assertTrue(any(i["severity"] == "fatal" for i in issues_r6a))

        echo_hi = copy.deepcopy(b_text)
        issues_r6b = rule_trans_script_purity("hi", self.lesson, [echo_hi])
        self.assertTrue(any(i["rule"] == "R6" for i in issues_r6b))

        # R7: rule_trans_placeholders (template leak)
        bad_ph = copy.deepcopy(b_text)
        bad_ph["spec"]["paragraphs"][0] = "यहाँ {{TODO}} अनुवाद लिखें [translate]।"
        issues_r7 = rule_trans_placeholders(
            self.lesson, [b_text], self.lesson, [bad_ph]
        )
        self.assertTrue(issues_r7)

        # R8: rule_trans_svg_safety (altered geometry attribute)
        bad_svg = copy.deepcopy(b_diag)
        bad_svg["spec"]["svg"] = bad_svg["spec"]["svg"].replace('x1="40"', 'x1="99"')
        issues_r8 = rule_trans_svg_safety([b_diag], [bad_svg])
        self.assertTrue(issues_r8)

        # R9: rule_trans_length_budget (slider label > 32 chars)
        bad_len = copy.deepcopy(b_sim)
        bad_len["spec"]["controls"][0]["label"] = (
            "यह नियंत्रण लेबल बत्तीस अक्षरों से बहुत बड़ा है (m/s2)"
        )
        issues_r9 = rule_trans_length_budget(
            self.lesson, [b_sim], self.lesson, [bad_len]
        )
        self.assertTrue(issues_r9)

    def test_unverified_escape_hatch_downgrades_severity_to_minor(self) -> None:
        raw_issues = [
            {
                "block_id": "b-01",
                "severity": "major",
                "category": "awkward_phrasing",
                "message": "unverified: sentence rhythm could be slightly smoother",
            }
        ]
        normalized = normalize_reviewer_issues(raw_issues)
        self.assertEqual(normalized[0]["severity"], "minor")

    def test_transrepair_recovers_flagged_block_without_rerunning_other_blocks(
        self,
    ) -> None:
        run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-repair-ok")
        llm = LLMClient(self.cfg, run_ctx)
        trans_out = translate_run(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            None,
        )

        # Script 10b-transcheck to flag b-02 in 'hi' on initial review, then pass on recheck
        self.state.scripted_review_issues["hi"] = [
            [
                {
                    "block_id": "b-02",
                    "severity": "major",
                    "category": "glossary_term",
                    "message": "Missing bilingual parenthetical gloss on first mention of displacement.",
                }
            ],
            [],
        ]
        tc_out = transcheck_run(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            trans_out,
        )
        self.assertEqual(tc_out["verdict"], "fail")
        self.assertEqual(tc_out["locales"]["hi"]["blocking_count"], 1)

        calls_before_repair = len(self.state.calls)
        repaired_trans, repaired_units, _ = run_one_round(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            trans_out,
            tc_out,
            round_no=1,
        )
        self.assertEqual(repaired_units, {"hi": {"b-02"}})
        new_calls = self.state.calls[calls_before_repair:]
        repair_calls = [c for c in new_calls if c["stage"] == "10c-transrepair"]
        self.assertEqual(len(repair_calls), 1)
        self.assertEqual(repair_calls[0]["unit_id"], "b-02")
        self.assertEqual(repair_calls[0]["locale"], "hi")

        rechecked = transcheck_run(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            repaired_trans,
            round_tag="round-01",
            only_units_by_locale=repaired_units,
        )
        self.assertEqual(rechecked["verdict"], "pass")


if __name__ == "__main__":
    unittest.main()
