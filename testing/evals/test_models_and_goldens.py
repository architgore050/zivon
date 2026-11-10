"""Unit tests for `evals/config.py`, `evals/models.py`, golden sets, and package isolation."""

from __future__ import annotations

import ast
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from evals.config import EvalConfig, EvalConfigError
from evals.diff import compute_run_diff
from evals.models import (
    DIFF_REPORT_SCHEMA,
    EVAL_CARD_SCHEMA,
    EVAL_REPORT_SCHEMA,
    GOLDEN_EXPECTED_SCHEMA,
    SEEDED_DEFECT_SCHEMA,
    load_all_cards,
    validate_schema,
)
from evals.runner import compute_topic_sha256, rotate_golden, run_eval_suite
from llm_manager import LLMConfigError

REPO_ROOT = Path(__file__).resolve().parents[2]


class TestEvalConfigAndModels(unittest.TestCase):
    def test_smoke_config_loads_without_api_keys_or_urls(self) -> None:
        cfg = EvalConfig.from_env({})
        self.assertEqual(cfg.generator_model, "unconfigured")
        self.assertEqual(cfg.judge_model, "unconfigured")
        self.assertFalse(cfg.mock_mode)

    def test_judge_llm_config_enforces_temperature_zero_and_requires_url(self) -> None:
        cfg_missing = EvalConfig.from_env({})
        with self.assertRaises(LLMConfigError):
            cfg_missing.judge_llm_config()

        cfg_ok = EvalConfig.from_env(
            {
                "ZIVON_BASE_URL": "http://localhost:8000/v1",
                "ZIVON_MODEL": "qwen3-coder-30b",
                "ZIVON_EVAL_JUDGE_MODEL": "qwen3-judge-30b",
            }
        )
        llm_cfg = cfg_ok.judge_llm_config()
        self.assertEqual(llm_cfg.temperature, 0.0)
        self.assertEqual(llm_cfg.model, "qwen3-judge-30b")
        self.assertEqual(llm_cfg.base_url, "http://localhost:8000/v1")

    def test_invalid_timeout_raises_loudly(self) -> None:
        with self.assertRaises(EvalConfigError):
            EvalConfig.from_env({"ZIVON_TIMEOUT_S": "1.0"})

    def test_all_nine_eval_cards_load_and_validate_schema(self) -> None:
        cfg = EvalConfig.from_env({})
        cards = load_all_cards(cfg.cards_dir)
        expected_ids = {
            "EV-CUR-001",
            "EV-SYN-001",
            "EV-SYN-002",
            "EV-VIS-001",
            "EV-PERF-001",
            "EV-REV-001",
            "EV-REV-002",
            "EV-E2E-001",
            "EV-KID-001",
        }
        self.assertEqual(set(cards.keys()), expected_ids)

    def test_all_golden_topics_and_seeded_defects_validate_schemas(self) -> None:
        cfg = EvalConfig.from_env({})
        manifest = json.loads(
            (cfg.goldens_dir / "manifest.json").read_text(encoding="utf-8")
        )
        topics = manifest["golden_topics"]
        self.assertEqual(len(topics), 4)
        for t in topics:
            t_dir = cfg.repo_root / t["directory"]
            exp = json.loads((t_dir / "expected.json").read_text(encoding="utf-8"))
            validate_schema(exp, GOLDEN_EXPECTED_SCHEMA, t["golden_id"])
            self.assertTrue((t_dir / "source_pack_meta.json").is_file())
            self.assertTrue((t_dir / "artifact_ref.json").is_file())

        defect_files = sorted((cfg.goldens_dir / "defects").rglob("SD-*.json"))
        self.assertEqual(len(defect_files), 19)
        for df in defect_files:
            sample = json.loads(df.read_text(encoding="utf-8"))
            validate_schema(sample, SEEDED_DEFECT_SCHEMA, df.name)

    def test_rotate_golden_computes_deterministic_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            goldens_copy = tmp / "goldens"
            shutil.copytree(REPO_ROOT / "evals" / "goldens", goldens_copy)
            cfg = EvalConfig.from_env({"ZIVON_EVAL_GOLDENS_DIR": str(goldens_copy)})
            res_dry = rotate_golden(
                cfg, topic_id="GT-01", reason="unit test dry-run", dry_run=True
            )
            self.assertTrue(res_dry["dry_run"])
            self.assertEqual(len(res_dry["new_sha256"]), 64)
            expected_sha = compute_topic_sha256(
                REPO_ROOT / "evals" / "goldens" / "topics" / "class-9-motion"
            )
            self.assertEqual(res_dry["new_sha256"], expected_sha)

    def test_nested_schema_objects_reject_unknown_keys(self) -> None:
        """Additional-property typos inside nested objects must fail closed."""
        cfg = EvalConfig.from_env({})
        expected = json.loads(
            (cfg.goldens_dir / "topics" / "class-9-motion" / "expected.json").read_text(
                encoding="utf-8"
            )
        )
        validate_schema(expected, GOLDEN_EXPECTED_SCHEMA, "golden")
        for nested_key in (
            "source_provenance",
            "structure_bounds",
            "required_concepts_and_equations",
            "visual_and_kit_invariants",
            "perf_budgets",
        ):
            mutated = json.loads(json.dumps(expected))
            mutated[nested_key]["unexpected_scratch_key"] = 1
            with self.assertRaises(ValueError, msg=nested_key):
                validate_schema(mutated, GOLDEN_EXPECTED_SCHEMA, "golden")

        # `structure_bounds_note` stays a permitted root-level escape hatch.
        with_note = json.loads(json.dumps(expected))
        with_note["structure_bounds_note"] = "kit reference page is denser"
        validate_schema(with_note, GOLDEN_EXPECTED_SCHEMA, "golden")

        import yaml

        raw_card = yaml.safe_load(
            (cfg.cards_dir / "EV-SYN-001.yaml").read_text(encoding="utf-8")
        )
        raw_card["llm_judge"]["severity_ladder"]["unsupported"] = "x"
        with self.assertRaises(ValueError):
            validate_schema(raw_card, EVAL_CARD_SCHEMA, "card")
        raw_card = yaml.safe_load(
            (cfg.cards_dir / "EV-SYN-001.yaml").read_text(encoding="utf-8")
        )
        raw_card["llm_judge"]["anchor_examples"][0]["expected_issue"]["unexpected"] = (
            "x"
        )
        with self.assertRaises(ValueError):
            validate_schema(raw_card, EVAL_CARD_SCHEMA, "card")

    def test_report_and_diff_schemas_type_cards_and_diffs(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            cfg = EvalConfig.from_env(
                {"ZIVON_EVAL_RUNS_DIR": str(Path(td) / "evals_runs")}
            )
            report = run_eval_suite(cfg, card_id="EV-KID-001")
            payload = report.to_dict()
            validate_schema(payload, EVAL_REPORT_SCHEMA, "report")
            bad_report = json.loads(json.dumps(payload))
            bad_report["cards"] = ["not-an-object"]
            with self.assertRaises(ValueError):
                validate_schema(bad_report, EVAL_REPORT_SCHEMA, "report")

            diff = compute_run_diff(report, report)
            diff_payload = diff.to_dict()
            validate_schema(diff_payload, DIFF_REPORT_SCHEMA, "diff")
            bad_diff = json.loads(json.dumps(diff_payload))
            bad_diff["card_diffs"] = [42]
            with self.assertRaises(ValueError):
                validate_schema(bad_diff, DIFF_REPORT_SCHEMA, "diff")

    def test_store_backend_typo_fails_fast(self) -> None:
        with self.assertRaises(EvalConfigError):
            EvalConfig.from_env({"ZIVON_EVAL_STORE_BACKEND": "duall"})

    def test_rotate_golden_persists_reason_in_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            goldens_copy = tmp / "goldens"
            shutil.copytree(REPO_ROOT / "evals" / "goldens", goldens_copy)
            cfg = EvalConfig.from_env({"ZIVON_EVAL_GOLDENS_DIR": str(goldens_copy)})
            rotate_golden(cfg, topic_id="GT-01", reason="unit test rotation")
            manifest = json.loads(
                (goldens_copy / "manifest.json").read_text(encoding="utf-8")
            )
            entry = next(
                e for e in manifest["golden_topics"] if e["golden_id"] == "GT-01"
            )
            self.assertEqual(entry["rotations"][-1]["reason"], "unit test rotation")
            self.assertEqual(len(entry["rotations"][-1]["new_sha256"]), 64)

    def test_evals_package_has_zero_direct_http_or_openai_imports(self) -> None:
        """ADR-0028: No module in `evals/` may import `requests`, `httpx`, or `openai`."""
        forbidden = {"requests", "httpx", "openai", "langchain_openai"}
        evals_dir = REPO_ROOT / "evals"
        for py_file in sorted(evals_dir.rglob("*.py")):
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_mod = alias.name.split(".")[0]
                        self.assertNotIn(
                            root_mod,
                            forbidden,
                            f"{py_file} imports forbidden module {root_mod!r}",
                        )
                elif isinstance(node, ast.ImportFrom) and node.module:
                    root_mod = node.module.split(".")[0]
                    self.assertNotIn(
                        root_mod,
                        forbidden,
                        f"{py_file} imports from forbidden module {root_mod!r}",
                    )


if __name__ == "__main__":
    unittest.main()
