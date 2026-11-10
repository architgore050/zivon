"""Tests for SYNC-01 publish hook, SYNC-02 base backup, SYNC-03/05 nightly sync, and EVICT-01."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend import BackendConfig
from backend.sync import (
    ColdStorageSync,
    EvictionInvariantError,
    SyncVerificationError,
)
from db import DatabaseEngine


class TestSyncAndPublishHook(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.runs_dir = self.tmp_path / "runs"
        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            cold_staging_dir=str(self.tmp_path / "cold"),
            runs_dir=str(self.runs_dir),
        )
        self.db = DatabaseEngine.from_url(self.cfg.db_url)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_sync01_publish_verify_and_quarantine_on_corrupt_readback(self) -> None:
        lesson_dir = self.tmp_path / "motion"
        lesson_dir.mkdir()
        (lesson_dir / "index.html").write_text("<html>Motion</html>", encoding="utf-8")

        # 1. Corrupt read-back -> quarantined, live_pointer NOT flipped (RB-06, NFR-18)
        corrupt_sync = ColdStorageSync(
            self.db, self.cfg, corrupt_readback=True
        )
        with self.assertRaises(SyncVerificationError):
            corrupt_sync.publish_and_verify_artifact(
                lesson_dir,
                class_id="C1",
                course_id="motion",
                class_level=9,
                version="v1-bad",
            )
        obj_bad = self.db.fetchone(
            "SELECT state, cold_verified_at FROM object_catalog WHERE version_ref = 'v1-bad'"
        )
        assert obj_bad is not None
        self.assertEqual(obj_bad["state"], "quarantined")
        self.assertIsNone(obj_bad["cold_verified_at"])
        self.assertIsNone(
            self.db.fetchone(
                "SELECT * FROM live_pointer WHERE course_id = 'motion' AND class_level = 9"
            )
        )

        # 2. Healthy read-back -> cold_verified_at stamped, then live_pointer flipped
        healthy_sync = ColdStorageSync(self.db, self.cfg)
        res = healthy_sync.publish_and_verify_artifact(
            lesson_dir,
            class_id="C1",
            course_id="motion",
            class_level=9,
            version="v1-good",
            pinned=True,
        )
        self.assertEqual(res["state"], "cold_verified")
        self.assertIsNotNone(res["cold_verified_at"])
        lp = self.db.fetchone(
            "SELECT page_version_id FROM live_pointer WHERE course_id = 'motion' AND class_level = 9"
        )
        assert lp is not None
        self.assertEqual(lp["page_version_id"], res["page_version_id"])

        # 3. EVICT-01: Pinned object cannot be evicted
        with self.assertRaises(EvictionInvariantError):
            healthy_sync.evict_hot_object(res["key"])

        # 4. EVICT-01: Unpinned object cannot be evicted while cold provider is unreachable
        narration_file = self.tmp_path / "b-01.hi-IN.opus"
        narration_file.write_bytes(b"OggS-fake-opus-payload")
        res_c2 = healthy_sync.publish_and_verify_artifact(
            narration_file,
            class_id="C2",
            course_id="motion",
            class_level=9,
            locale="hi-IN",
            version="v1-good",
            pinned=False,
        )
        offline_sync = ColdStorageSync(
            self.db, self.cfg, cold_reachable=False
        )
        with self.assertRaises(EvictionInvariantError):
            offline_sync.evict_hot_object(res_c2["key"])

        # Online + unpinned + cold_verified -> eviction succeeds and removes hot file
        ev_ok = healthy_sync.evict_hot_object(res_c2["key"])
        self.assertEqual(ev_ok["state"], "evicted")
        self.assertFalse(narration_file.exists())

    def test_sync02_base_backup_and_sync03_05_nightly(self) -> None:
        run_dir = self.runs_dir / "motion-c9"
        run_dir.mkdir(parents=True)
        (run_dir / "status.json").write_text(
            json.dumps(
                {
                    "chapter": "Motion",
                    "class_level": 9,
                    "completed_at": "2026-11-08T10:00:00Z",
                    "ok": True,
                }
            ),
            encoding="utf-8",
        )
        sync = ColdStorageSync(self.db, self.cfg)
        b_res = sync.run_base_backup()
        self.assertEqual(b_res["providers"], ["b2", "r2"])
        self.assertIsNotNone(b_res["cold_verified_at"])

        n_res = sync.run_nightly_sync()
        self.assertEqual(n_res["runs_archived"], 1)
        self.assertIsNotNone(n_res["cold_verified_at"])


if __name__ == "__main__":
    unittest.main()
