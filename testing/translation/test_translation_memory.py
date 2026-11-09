"""Unit tests for Two-Tier Translation Memory (ADR-0022), Alembic 0022 Migration, and Per-Block Resume."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from testing.translation._test_env import (
    ensure_test_dependencies,
    install_translation_env,
    restore_translation_env,
)

ensure_test_dependencies()

from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient
from factory.tm_store import TranslationMemoryStore, can_evict_ssd_bundle
from factory.transcheck import run as transcheck_run
from factory.translate import compute_tm_keys, run as translate_run
from testing.translation.mock_translation_node import start_translation_mock

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"
MIGRATION_PATH = REPO_ROOT / "migrations" / "versions" / "0022_translation_memory_c3.py"


class TestTranslationMemoryAndResume(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.base_url, cls.state = start_translation_mock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-tm-"))
        self.saved_env = install_translation_env(self.base_url)
        self.state.calls.clear()

        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"]["runs"] = str(self.tmp / "runs")
        base["paths"]["text_cache"] = str(self.tmp / "cache")
        base["translation"]["enabled"] = True
        base["translation"]["target_locales"] = ["hi"]
        cfg_path = self.tmp / "config.json"
        cfg_path.write_text(json.dumps(base), encoding="utf-8")
        self.cfg = load_config(cfg_path)
        self.lesson = json.loads(
            (FIXTURES / "lesson.json").read_text(encoding="utf-8")
        )
        self.blocks = json.loads(
            (FIXTURES / "blocks.json").read_text(encoding="utf-8")
        )
        self.ground_truth = json.loads(
            (FIXTURES / "gt.json").read_text(encoding="utf-8")
        )

    def tearDown(self) -> None:
        restore_translation_env(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_tm_store_verified_only_write_gate_and_human_override_retention(
        self,
    ) -> None:
        store = TranslationMemoryStore(
            self.tmp / "tm", db_path=self.tmp / "tm.sqlite3"
        )
        src_payload = {"paragraphs": ["Distance is the total path length."]}
        src_sha, tm_key_v1 = compute_tm_keys(
            "b-01", src_payload, "hi", "1.0.0", "1"
        )

        # Unverified draft must be rejected by the write gate
        with self.assertRaises(ValueError):
            store.store_verified_unit(
                {
                    "tm_key": tm_key_v1,
                    "source_content_sha256": src_sha,
                    "unit_type": "text",
                    "locale": "hi",
                    "review_status": "draft",
                }
            )

        # Store a human_approved override under glossary_version 1.0.0
        human_env = {
            "unit_id": "b-01",
            "unit_type": "text",
            "locale": "hi",
            "source_content_sha256": src_sha,
            "tm_key": tm_key_v1,
            "glossary_version": "1.0.0",
            "prompt_version": "1",
            "model_id": "human-curator",
            "translation_source": "human",
            "review_status": "human_approved",
            "source_payload": src_payload,
            "translated_payload": {
                "paragraphs": ["मानव-सत्यापित अनुवाद: दूरी कुल पथ है।"]
            },
            "reassembled_block": {
                "id": "b-01",
                "type": "text",
                "citations": [{"claim_id": "claim-01"}],
                "spec": {"paragraphs": ["मानव-सत्यापित अनुवाद: दूरी कुल पथ है।"]},
            },
        }
        store.store_verified_unit(human_env)

        # Bump glossary_version to 2.0.0 -> tm_key changes, but human_approved override
        # must still be returned via source_content_sha256 lookup!
        _, tm_key_v2 = compute_tm_keys(
            "b-01", src_payload, "hi", "2.0.0", "1"
        )
        self.assertNotEqual(tm_key_v1, tm_key_v2)
        hit = store.lookup(
            locale="hi", tm_key=tm_key_v2, source_content_sha256=src_sha
        )
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit["review_status"], "human_approved")
        self.assertEqual(
            hit["translated_payload"]["paragraphs"][0],
            "मानव-सत्यापित अनुवाद: दूरी कुल पथ है।",
        )

    def test_in_run_checkpoint_resume_and_cross_run_tm_reuse(self) -> None:
        # Run 1: translates all 9 units (b-00-meta + 8 blocks)
        run1 = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "run-cold")
        llm1 = LLMClient(self.cfg, run1)
        out1 = translate_run(
            self.cfg,
            run1,
            llm1,
            self.ground_truth,
            self.lesson,
            self.blocks,
            None,
        )
        self.assertEqual(out1["locales"]["hi"]["stats"]["model_calls"], 9)
        self.assertEqual(out1["locales"]["hi"]["stats"]["tm_hits"], 0)

        # Re-invoking translate_run on the SAME run_ctx must resume all 9 units from on-disk checkpoints
        calls_after_run1 = len(self.state.calls)
        out1_resumed = translate_run(
            self.cfg,
            run1,
            llm1,
            self.ground_truth,
            self.lesson,
            self.blocks,
            None,
        )
        self.assertEqual(
            out1_resumed["locales"]["hi"]["stats"]["resumed_in_run"], 9
        )
        self.assertEqual(
            out1_resumed["locales"]["hi"]["stats"]["model_calls"], 0
        )
        self.assertEqual(len(self.state.calls), calls_after_run1)

        # Run 10b-transcheck on run1 so verified units are promoted into Translation Memory
        tc1 = transcheck_run(
            self.cfg,
            run1,
            llm1,
            self.ground_truth,
            self.lesson,
            self.blocks,
            out1_resumed,
        )
        self.assertEqual(tc1["verdict"], "pass")

        # Run 2 (fresh run_id): all 9 units must hit Translation Memory with ZERO 10a-translate LLM calls!
        calls_before_run2 = len(self.state.calls)
        run2 = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "run-warm")
        llm2 = LLMClient(self.cfg, run2)
        out2 = translate_run(
            self.cfg,
            run2,
            llm2,
            self.ground_truth,
            self.lesson,
            self.blocks,
            None,
        )
        self.assertEqual(out2["locales"]["hi"]["stats"]["tm_hits"], 9)
        self.assertEqual(out2["locales"]["hi"]["stats"]["model_calls"], 0)
        self.assertEqual(len(self.state.calls), calls_before_run2)

    def test_storage_tiering_sync_outbox_and_ssd_eviction_guard(self) -> None:
        store = TranslationMemoryStore(
            self.tmp / "tm", db_path=self.tmp / "tm.sqlite3"
        )
        job = store.record_bundle_publish_sync(
            topic_slug="motion",
            class_level=9,
            locale="hi",
            version="v1",
            bundle_bytes=b"localized-bundle-content",
        )
        self.assertEqual(job["rule_id"], "SYNC-01")
        self.assertEqual(job["class_id"], "C1")
        self.assertFalse(can_evict_ssd_bundle(None))
        self.assertTrue(can_evict_ssd_bundle("2026-11-09T00:00:00Z", pinned=False))
        self.assertFalse(can_evict_ssd_bundle("2026-11-09T00:00:00Z", pinned=True))
        self.assertFalse(
            can_evict_ssd_bundle(
                "2026-11-09T00:00:00Z",
                pinned=False,
                cold_provider_reachable=False,
            )
        )

    def test_alembic_migration_0022_upgrade_and_downgrade(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "mig_0022", str(MIGRATION_PATH)
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        self.assertEqual(module.revision, "0022_translation_memory_c3")
        self.assertIsNone(module.down_revision)

        executed_sql: list[str] = []
        fake_op = types.SimpleNamespace(
            execute=lambda sql: executed_sql.append(str(sql))
        )
        module.op = fake_op  # type: ignore[attr-defined]
        module.upgrade(op_override=fake_op)
        joined_up = "\n".join(executed_sql)
        for tbl in (
            "locale_fallback",
            "glossary_term",
            "translation_memory_entry",
            "block_translation",
            "ui_string",
        ):
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {tbl}", joined_up)

        executed_sql.clear()
        module.downgrade(op_override=fake_op)
        joined_down = "\n".join(executed_sql)
        for tbl in (
            "ui_string",
            "block_translation",
            "translation_memory_entry",
            "glossary_term",
            "locale_fallback",
        ):
            self.assertIn(f"DROP TABLE IF EXISTS {tbl}", joined_down)


if __name__ == "__main__":
    unittest.main()
