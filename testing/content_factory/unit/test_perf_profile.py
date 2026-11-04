"""Unit tests for the perf harness profile loading and verdict logic."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from testing.content_factory.perf.harness import _judge, load_profile

PROFILES = REPO_ROOT / "testing" / "content_factory" / "perf" / "profiles"


class TestProfiles(unittest.TestCase):
    def test_weak_android_profile_loads(self):
        p = load_profile(PROFILES / "weak-android.json")
        self.assertEqual(p["ram_budget_mb"], 750)
        self.assertEqual(p["cpu_throttle_rate"], 4)
        self.assertEqual(p["pin_cores"], 2)

    def test_mid_laptop_profile_loads(self):
        p = load_profile(PROFILES / "mid-laptop.json")
        self.assertIsNone(p["pin_cores"])

    def test_missing_key_rejected(self):
        bad = json.loads((PROFILES / "weak-android.json").read_text())
        del bad["fps_min"]
        # Write scratch files to a temp dir, never into the source tree:
        # cluster pods run with a read-only root filesystem and must pass too.
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "tmp-bad.json"
            tmp.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_profile(tmp)

    def test_wrong_type_rejected(self):
        bad = json.loads((PROFILES / "weak-android.json").read_text())
        bad["fps_min"] = "24"
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "tmp-bad.json"
            tmp.write_text(json.dumps(bad))
            with self.assertRaises(ValueError):
                load_profile(tmp)


class TestJudge(unittest.TestCase):
    def base_report(self):
        return {
            "budgets": {"load_s": 2.0, "fcp_s": 1.2, "ram_mb": 750, "fps_min": 24},
            "measured": {
                "load_s": 0.5,
                "fcp_s": 0.4,
                "fps_median": 55,
                "peak_browser_rss_mb": 300,
                "js_heap_mb": 5,
            },
            "console_errors": [],
            "page_errors": [],
            "failures": [],
            "pass": False,
        }

    def test_pass(self):
        report = self.base_report()
        _judge(report)
        self.assertTrue(report["pass"])

    def test_load_fail(self):
        report = self.base_report()
        report["measured"]["load_s"] = 2.5
        _judge(report)
        self.assertFalse(report["pass"])
        self.assertIn("load", report["failures"][0])

    def test_ram_fail(self):
        report = self.base_report()
        report["measured"]["peak_browser_rss_mb"] = 800
        _judge(report)
        self.assertIn("RSS", report["failures"][0])

    def test_fps_fail(self):
        report = self.base_report()
        report["measured"]["fps_median"] = 12.0
        _judge(report)
        self.assertIn("FPS", report["failures"][0])

    def test_page_errors_fail(self):
        report = self.base_report()
        report["page_errors"] = ["TypeError: boom"]
        _judge(report)
        self.assertFalse(report["pass"])


if __name__ == "__main__":
    unittest.main()
