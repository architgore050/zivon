"""Unit tests for stage 07-perf routing and stage 08-fixloop behaviour.

The perf harness is faked (no Chromium here); the integration test exercises
the real one. What we prove: a topic-page miss is routed to the fix loop,
an unfixable miss stops the run, and the fix loop repairs, re-lints, retests
and gives up loudly.
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import fixloop as fixloop_mod
from factory import perf as perf_mod
from factory.artifacts import RunContext
from factory.config import load_config
from factory.errors import BudgetError, LintError
from factory.llm import LLMClient
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


PAGE_HTML = """<!doctype html>
<html lang="en">
<head><meta http-equiv="Content-Security-Policy" content="default-src 'none'"></head>
<body>
<main class="zn-page">
  <header>
    <ul class="zn-objectives"><li>Use &amp; apply v = u + at</li></ul>
  </header>
  <section class="zn-glossary"><dl>
    <dt>Speed &amp; direction</dt><dd>rate &amp; how</dd>
  </dl></section>
</main>
</body>
</html>
"""


def fake_report(ok: bool, failures: list[str] | None = None) -> dict[str, Any]:
    return {
        "pass": ok,
        "failures": failures or [],
        "measured": {"load_s": 1.0},
        "budgets": {"load_s": 2.0},
    }


def make_cfg(tmp: Path, fix_rounds: int = 2):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    base["perf"]["fix_rounds"] = fix_rounds
    path = tmp / "config.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    saved = install_server_env()
    try:
        cfg = load_config(path)
    finally:
        release_server_env(saved)
    # 08-fixloop hands the LIVE doctrine + lesson example + palette to the
    # model (2026-11-04): root must be the real repo so those load.
    return dataclasses.replace(cfg, root=REPO_ROOT)


def make_page(tmp: Path) -> tuple[Path, Path, dict[str, Any]]:
    """A staged topic page + site, shaped like stage 06-render's output."""
    site = tmp / "site"
    topic = site / "courses" / "class-9-physics" / "motion"
    topic.mkdir(parents=True)
    (topic / "index.html").write_text(PAGE_HTML, encoding="utf-8")
    (topic / "page.js").write_text('ZivonSim.register("b-06", {});', encoding="utf-8")
    manifest = {
        "course_id": "class-9-physics",
        "topic_slug": "motion",
        "title": "Motion",
        "class": 9,
    }
    (topic / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    render_out = {
        "topic_dir": str(topic),
        "site_dir": str(site),
        "manifest": manifest,
        "files": sorted(p.name for p in topic.iterdir()),
    }
    return site, topic, render_out


class StubLLM:
    """Stands in for LLMClient; records every call's messages, returns a
    canned fix plan."""

    def __init__(self, plan: dict[str, Any] | None = None):
        self.plan = plan or {
            "analysis": "draw loop allocates per frame; simplify it.",
            "files": {"page.js": 'ZivonSim.register("b-06", {}); // fixed'},
        }
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.calls += 1
        self.messages.append(messages)
        return json.loads(json.dumps(self.plan))


class TestPerfStage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = make_cfg(self.tmp)
        self.run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), "t-perf")
        self.site, self.topic, self.render_out = make_page(self.tmp)

    def _run(self, topic_ok: bool, landing_ok: bool) -> dict[str, Any]:
        def fake_run_profile(url: str, profile: Any) -> dict[str, Any]:
            is_topic = "courses" in url
            return fake_report(
                topic_ok if is_topic else landing_ok, ["load 3.0s > 2.0s"]
            )

        with mock.patch.object(perf_mod, "_harness", return_value=fake_run_profile):
            return perf_mod.run(self.cfg, self.run_ctx, self.render_out)

    def test_both_pages_pass(self):
        out = self._run(True, True)
        self.assertTrue(out["pass"])
        self.assertTrue(
            (self.run_ctx.stage_dir("07-perf") / "topic_page.perf.json").exists()
        )

    def test_topic_miss_is_fixable_and_carries_report(self):
        with self.assertRaises(BudgetError) as ctx:
            self._run(False, True)
        self.assertTrue(ctx.exception.fixable)
        self.assertIsNotNone(ctx.exception.report)
        self.assertIn("08-fixloop", str(ctx.exception))

    def test_landing_miss_is_not_fixable(self):
        with self.assertRaises(BudgetError) as ctx:
            self._run(True, False)
        self.assertFalse(ctx.exception.fixable)
        self.assertIn("hand-maintained", str(ctx.exception))


class TestFixloopStage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.site, self.topic, self.render_out = make_page(self.tmp)

    def _run(
        self,
        cfg: Any,
        perf_report: dict[str, Any] | None,
        harness_results: list[dict[str, Any]],
        llm: StubLLM,
    ) -> dict[str, Any]:
        run_ctx = RunContext(cfg.repo_path(cfg.paths["runs"]), "t-fix")
        results = list(harness_results)

        def fake_run_profile(url: str, profile: Any) -> dict[str, Any]:
            return results.pop(0)

        with mock.patch.object(fixloop_mod, "_harness", return_value=fake_run_profile):
            return fixloop_mod.run(
                cfg,
                run_ctx,
                cast(LLMClient, llm),
                self.render_out,
                perf_report,
                load("blocks.json"),
            )

    def test_passed_perf_skips_model_and_harness(self):
        cfg = make_cfg(self.tmp)
        llm = StubLLM()
        out = self._run(cfg, fake_report(True), [], llm)  # harness must NOT be called
        self.assertEqual(out["rounds"], 0)
        self.assertTrue(out["pass"])
        self.assertEqual(llm.calls, 0)

    def test_fix_round_repairs_and_retests(self):
        cfg = make_cfg(self.tmp, fix_rounds=2)
        llm = StubLLM()
        out = self._run(
            cfg,
            fake_report(False, ["FPS 12 < 24"]),
            [fake_report(True)],  # retest after the fix passes
            llm,
        )
        self.assertEqual(out["rounds"], 1)
        self.assertTrue(out["pass"])
        self.assertEqual(llm.calls, 1)
        self.assertIn("// fixed", (self.topic / "page.js").read_text())
        history = json.loads(
            (
                RunContext(cfg.repo_path(cfg.paths["runs"]), "t-fix").stage_dir(
                    "08-fixloop"
                )
                / "history.json"
            ).read_text()
        )
        self.assertEqual([h["round"] for h in history], [0, 1])

    def test_exhausted_rounds_fail_loudly(self):
        cfg = make_cfg(self.tmp, fix_rounds=1)
        llm = StubLLM()
        with self.assertRaises(BudgetError) as ctx:
            self._run(
                cfg,
                fake_report(False, ["FPS 12 < 24"]),
                [fake_report(False, ["FPS 14 < 24"])],  # fix did not help
                llm,
            )
        self.assertFalse(ctx.exception.fixable)
        self.assertIn("after 1 fix rounds", str(ctx.exception))

    def test_fix_plan_touching_renderer_files_is_rejected(self):
        cfg = make_cfg(self.tmp, fix_rounds=1)
        llm = StubLLM(
            plan={"analysis": "x" * 30, "files": {"index.html": "<html></html>"}}
        )
        with self.assertRaises(LintError):
            self._run(
                cfg,
                fake_report(False, ["load 3.0s > 2.0s"]),
                [fake_report(False, ["load 3.0s > 2.0s"])],
                llm,
            )

    def test_fix_prompt_carries_specs_and_teaching_guard(self):
        # A perf fix must not be allowed to gut the page: the model sees the
        # sim specs it must preserve, the measurement context, and the budgets.
        cfg = make_cfg(self.tmp, fix_rounds=1)
        llm = StubLLM()
        with self.assertRaises(BudgetError):
            self._run(
                cfg,
                fake_report(False, ["FPS 12 < 24"]),
                [fake_report(False, ["FPS 12 < 24"])],
                llm,
            )
        system = next(m["content"] for m in llm.messages[0] if m["role"] == "system")
        user = next(m["content"] for m in llm.messages[0] if m["role"] == "user")
        self.assertIn("must still TEACH", system)
        self.assertIn("low-end Android", system)
        self.assertIn("PAGE SPECS", user)
        self.assertIn("Connect the size of acceleration", user)  # the sim's goal
        self.assertIn("budgets", user)
        # 2026-11-04: a perf fixer edits page code, so it must see the design
        # language it is preserving - doctrine + the lesson-page example + palette.
        self.assertIn("DESIGN DOCTRINE + LESSON-PAGE EXAMPLE", user)
        self.assertIn("design-doctrine-lesson-example.html", user)
        self.assertNotIn("=== design-doctrine-example.html ===", user)
        self.assertIn("PALETTE", user)
        self.assertIn("--ink:", user)

    def test_second_round_sees_previous_attempts(self):
        # Without the attempt history the model repeats a failed fix unchanged.
        cfg = make_cfg(self.tmp, fix_rounds=2)
        llm = StubLLM()
        with self.assertRaises(BudgetError):
            self._run(
                cfg,
                fake_report(False, ["FPS 12 < 24"]),
                [
                    fake_report(False, ["FPS 14 < 24"]),
                    fake_report(False, ["FPS 15 < 24"]),
                ],
                llm,
            )
        self.assertEqual(llm.calls, 2)
        round2 = next(m["content"] for m in llm.messages[1] if m["role"] == "user")
        self.assertIn("PREVIOUS ATTEMPTS", round2)
        self.assertIn("draw loop allocates per frame", round2)  # round 1's analysis
        self.assertIn("FPS 14", round2)  # and its outcome

    def test_extracted_objectives_are_unescaped_once(self):
        # Rebuilding the HTML shell must not double-escape entities from the
        # previously rendered page (& -> &amp;, never &amp;amp;).
        objectives = fixloop_mod._extract_objectives(PAGE_HTML)
        self.assertIn("Use & apply v = u + at", objectives)
        glossary = fixloop_mod._extract_glossary(PAGE_HTML)
        self.assertEqual(glossary[0]["term"], "Speed & direction")


if __name__ == "__main__":
    unittest.main()
