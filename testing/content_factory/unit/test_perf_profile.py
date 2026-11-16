"""Unit tests for the perf harness profile loading and verdict logic."""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from evals.checkers.perf_harness import (
    _judge,
    _soft_budget_report,
    load_profile,
    measure_asset_bytes,
)
from factory import perf as factory_perf

PROFILES = REPO_ROOT / "evals" / "goldens" / "profiles"


class TestProfiles(unittest.TestCase):
    def test_weak_android_profile_loads(self):
        p = load_profile(PROFILES / "weak-android.json")
        self.assertEqual(p["ram_budget_mb"], 750)
        self.assertEqual(p["cpu_throttle_rate"], 4)
        self.assertEqual(p["pin_cores"], 2)

    def test_mid_laptop_profile_loads(self):
        p = load_profile(PROFILES / "mid-laptop.json")
        self.assertIsNone(p["pin_cores"])

    def test_q4_runtime_and_soft_byte_keys_load(self):
        p = load_profile(PROFILES / "weak-android.json")
        # Q-4 hard runtime budget.
        self.assertLessEqual(p["interactive_budget_s"], 3.0)
        self.assertLessEqual(p["long_task_budget_ms"], 200)
        # Q-4 soft byte budget: reported, never a hard gate.
        self.assertEqual(p["soft_js_gzip_kb"], 150)
        self.assertEqual(p["soft_css_gzip_kb"], 50)

    def test_shim_profile_copies_match_the_canonical_profiles(self):
        shim = REPO_ROOT / "testing" / "content_factory" / "perf" / "profiles"
        for name in ("weak-android.json", "mid-laptop.json"):
            with self.subTest(profile=name):
                self.assertEqual(
                    json.loads((PROFILES / name).read_text(encoding="utf-8")),
                    json.loads((shim / name).read_text(encoding="utf-8")),
                    f"{name} drifted from the canonical evals/goldens/profiles copy",
                )

    def test_missing_key_rejected(self):
        bad = json.loads((PROFILES / "weak-android.json").read_text())
        del bad["fps_min"]
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

    def test_interactive_budget_fails(self):
        report = self.base_report()
        report["budgets"]["interactive_s"] = 3.0
        report["measured"]["interactive_s"] = 4.2
        _judge(report)
        self.assertFalse(report["pass"])
        self.assertTrue(any("interactive" in f for f in report["failures"]))

    def test_interaction_input_over_budget_fails(self):
        report = self.base_report()
        report["budgets"]["long_task_ms"] = 200
        report["measured"]["interaction_input_ms"] = 260
        _judge(report)
        self.assertFalse(report["pass"])
        self.assertTrue(any("interactive input" in f for f in report["failures"]))

    def test_observed_interaction_long_task_fails_the_q4_verdict(self):
        report = self.base_report()
        report["budgets"]["long_task_ms"] = 200
        report["measured"]["interaction_input_ms"] = 8.0
        report["measured"]["interaction_longest_task_ms"] = 287
        _judge(report)
        self.assertFalse(report["pass"])
        self.assertTrue(
            any("scroll/click long task" in f for f in report["q4_failures"])
        )

    def test_load_pass_keeps_the_pre_q4_contract_separate(self):
        # A Q-4 miss must be visible in `pass`/`failures` without silently
        # redefining the load-budget contract the frontend snapshot test uses.
        report = self.base_report()
        report["budgets"]["long_task_ms"] = 200
        report["measured"]["interaction_input_ms"] = 260
        _judge(report)
        self.assertTrue(report["load_pass"])
        self.assertEqual(report["load_failures"], [])
        self.assertFalse(report["pass"])
        self.assertTrue(report["q4_failures"])

    def test_load_path_long_task_is_an_advisory_not_a_failure(self):
        # Q-4 names the interaction path as the hard long-task gate; a
        # load-path task is measured and reported, but not blocking (a shared
        # CI runner adds scheduler noise that made a load-path 200 ms
        # assertion flaky: class-11 laws-of-motion/hi, 2026-11-16).
        report = self.base_report()
        report["budgets"]["long_task_ms"] = 200
        report["measured"]["longest_task_ms"] = 320
        report["measured"]["load_longest_task_ms"] = 320
        _judge(report)
        self.assertTrue(report["pass"])
        self.assertEqual(report["failures"], [])
        self.assertTrue(any("load-path long task" in a for a in report["advisories"]))

    def test_soft_byte_budget_is_an_advisory_never_a_failure(self):
        report = self.base_report()
        report["soft_budgets"] = {
            "measured": True,
            "shell_js_gzip_kb": 210.0,
            "per_topic_js_gzip_kb": 90.0,
            "css_gzip_kb": 70.0,
            "soft_js_budget_kb": 150.0,
            "soft_css_budget_kb": 50.0,
            "within_soft_budget": False,
        }
        _judge(report)
        self.assertTrue(report["pass"])
        self.assertEqual(report["failures"], [])
        self.assertTrue(any("soft byte budget" in a for a in report["advisories"]))


class TestBudgetFailEvents(unittest.TestCase):
    def test_interaction_long_task_failure_carries_measured_and_limit_ms(self):
        report = {
            "failures": ["interactive input 432.0ms > budget 200ms (interaction path)"]
        }
        with mock.patch.object(factory_perf, "log_event") as log_event:
            factory_perf._emit_budget_fails(mock.Mock(run_id="r1"), report)
        fields = log_event.call_args.args[1]
        self.assertEqual(fields["budget_name"], "interaction_input")
        self.assertEqual(fields["measured_ms"], 432)
        self.assertEqual(fields["limit_ms"], 200)
        self.assertEqual(log_event.call_args.kwargs["latency_ms"], 432)


class TestAssetBytes(unittest.TestCase):
    def test_gzip_sizes_are_split_by_role_and_query_strings_are_ignored(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "assets").mkdir()
            (root / "i18n").mkdir()
            (root / "assets" / "zivon.js").write_text("var z = 1;" * 400)
            (root / "assets" / "zivon.css").write_text("body { color: red; }" * 200)
            (root / "page.js").write_text("var p = 2;" * 200)
            (root / "i18n" / "hi.js").write_text('var strings = {"a": "b"};' * 150)
            page = root / "index.html"
            page.write_text(
                '<html><head><link rel="stylesheet" href="assets/zivon.css?v=9">'
                '</head><body><script src="assets/zivon.js?v=2"></script>'
                '<script src="page.js"></script><script src="i18n/hi.js"></script>'
                "</body></html>"
            )
            report = measure_asset_bytes(page.resolve().as_uri())
            self.assertTrue(report["measured"])
            self.assertEqual(report["files"], 4)
            for key in (
                "shell_js_gzip_kb",
                "page_js_gzip_kb",
                "i18n_js_gzip_kb",
                "css_gzip_kb",
            ):
                self.assertGreater(report[key], 0.0, key)

    def test_non_file_url_is_not_measured(self):
        self.assertFalse(
            measure_asset_bytes("https://example.com/index.html")["measured"]
        )


class TestSoftBudgetReport(unittest.TestCase):
    def test_shell_and_css_are_compared_separately_from_per_topic_js(self):
        report = _soft_budget_report(
            {
                "measured": True,
                "shell_js_gzip_kb": 58.4,
                "page_js_gzip_kb": 20.0,
                "i18n_js_gzip_kb": 12.9,
                "css_gzip_kb": 11.4,
            },
            150,
            50,
        )
        self.assertEqual(report["shell_js_gzip_kb"], 58.4)
        self.assertEqual(report["per_topic_js_gzip_kb"], 32.9)
        self.assertTrue(report["within_soft_budget"])


if __name__ == "__main__":
    unittest.main()
