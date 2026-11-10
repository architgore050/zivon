"""Unit tests for stage 07-perf routing and stage 08-fixloop behaviour.

Note: `test_fix_prompt_carries_specs_and_teaching_guard` was migrated to
`evals/checkers/prompt_contract_checks.py` (`EV-PERF-001`) per
`docs/specs/evals/migration-map.csv` row 29.
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
from factory.errors import BudgetError
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
  <header class="zn-header">
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


def make_cfg(tmp: Path, fix_rounds: int = 2, stall_rounds: int | None = None):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    base["perf"]["fix_rounds"] = fix_rounds
    if stall_rounds is not None:
        base["repair"]["stall_rounds"] = stall_rounds
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
    canned fix plan. Pass `plans` (a list) to script a different plan per
    round - the last one repeats if the loop runs longer."""

    def __init__(
        self,
        plan: dict[str, Any] | None = None,
        plans: list[dict[str, Any]] | None = None,
    ):
        default = {
            "analysis": "draw loop allocates per frame; simplify it.",
            "files": {"page.js": 'ZivonSim.register("b-06", {}); // fixed'},
        }
        self.plans = plans if plans is not None else [plan or default]
        self.calls = 0
        self.messages: list[list[dict[str, str]]] = []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.calls += 1
        self.messages.append(messages)
        plan = self.plans[min(self.calls - 1, len(self.plans) - 1)]
        return json.loads(json.dumps(plan))


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

    def test_rebuild_html_does_not_nest_the_shell(self):
        # Regression (2026-11-09, class-11 Units page): _rebuild_html_if_needed
        # used to feed the whole <main> content (old header + glossary +
        # footer included) back in as the body, so _page_html wrapped it in a
        # FRESH shell and every fixloop round doubled the header/glossary.
        cfg = make_cfg(self.tmp)
        fixloop_mod._rebuild_html_if_needed(cfg, self.render_out, self.topic)
        html = (self.topic / "index.html").read_text(encoding="utf-8")
        for marker in (
            '<header class="zn-lang-bar">',
            '<header class="zn-header">',
            '<section class="zn-glossary">',
            '<footer class="zn-footer">',
        ):
            self.assertEqual(html.count(marker), 1, marker)
        # objectives/glossary survive the rebuild (re-extracted from the old
        # page), and a second rebuild is a no-op in shape (idempotent).
        self.assertIn("Use &amp; apply v = u + at", html)
        self.assertIn("Speed &amp; direction", html)
        fixloop_mod._rebuild_html_if_needed(cfg, self.render_out, self.topic)
        html2 = (self.topic / "index.html").read_text(encoding="utf-8")
        for marker in (
            '<header class="zn-lang-bar">',
            '<header class="zn-header">',
            '<section class="zn-glossary">',
            '<footer class="zn-footer">',
        ):
            self.assertEqual(html2.count(marker), 1, marker)

    def test_fix_plan_touching_renderer_files_costs_a_round_not_the_run(self):
        # 2026-11-06 founder decision: renderer-owned files are skipped and
        # the violation is fed back - the model gets a round to repair its own
        # fix instead of the run dying on a LintError.
        cfg = make_cfg(self.tmp, fix_rounds=2)
        llm = StubLLM(
            plan={"analysis": "x" * 30, "files": {"index.html": "<html></html>"}}
        )
        with self.assertRaises(BudgetError):
            self._run(
                cfg,
                fake_report(False, ["load 3.0s > 2.0s"]),
                [
                    fake_report(False, ["load 3.0s > 2.0s"]),
                    fake_report(False, ["load 3.0s > 2.0s"]),
                ],
                llm,
            )
        self.assertEqual(llm.calls, 2, "the rejected fix consumed rounds, not the run")
        html = (self.topic / "index.html").read_text(encoding="utf-8")
        self.assertNotIn("<html></html>", html, "the model's html was never applied")
        self.assertIn("zn-objectives", html, "the page still teaches")
        round2 = next(m["content"] for m in llm.messages[1] if m["role"] == "user")
        self.assertIn("renderer-owned", round2)  # its own failure is the assignment
        self.assertIn("index.html", round2)

    def test_lint_violating_fix_is_repaired_by_the_next_round(self):
        # A fix that violates a hard lint consumes a ROUND: the violation
        # becomes the next round's assignment, and the loop continues with a
        # clean fix (2026-11-06: failures feed back, they do not kill the run).
        cfg = make_cfg(self.tmp, fix_rounds=3)
        llm = StubLLM(
            plans=[
                {
                    "analysis": "cache the loop bounds",
                    "files": {"page.js": "eval('speed');"},
                },
                {
                    "analysis": "drop the eval, use plain math",
                    "files": {"page.js": 'ZivonSim.register("b-06", {}); // clean'},
                },
            ]
        )
        out = self._run(
            cfg,
            fake_report(False, ["FPS 12 < 24"]),
            [fake_report(True)],  # only the clean round re-measures
            llm,
        )
        self.assertTrue(out["pass"])
        self.assertEqual(out["rounds"], 2)
        self.assertEqual(llm.calls, 2)
        round2 = next(m["content"] for m in llm.messages[1] if m["role"] == "user")
        self.assertIn("violated hard lints", round2)
        self.assertIn("eval", round2)
        self.assertIn("// clean", (self.topic / "page.js").read_text())

    def test_plateau_stops_the_loop_before_the_cap(self):
        # Progress-aware (2026-11-06): consecutive no-improvement retests are
        # a genuine plateau - the loop stops there instead of burning the
        # whole generous cap, and says so.
        cfg = make_cfg(self.tmp, fix_rounds=6, stall_rounds=2)
        llm = StubLLM()
        with self.assertRaises(BudgetError) as ctx:
            self._run(
                cfg,
                fake_report(False, ["FPS 12 < 24"]),
                [
                    fake_report(False, ["FPS 14 < 24"]),
                    fake_report(False, ["FPS 13 < 24"]),
                ],
                llm,
            )
        self.assertEqual(llm.calls, 2, "stopped at the plateau, not at the cap")
        self.assertIn("progress plateaued", str(ctx.exception))

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


class TestSpecCorrectionChannel(unittest.TestCase):
    """2026-11-09 (this repo's own failed run): review findings about block
    CONTENT are unfixable in page code - the fix plan gained a "blocks"
    channel. The harness merges corrections by id and re-renders the page
    body from the merged specs, so index.html has exactly one writer."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg = make_cfg(self.tmp)
        self.site, self.topic, self.render_out = make_page(self.tmp)
        self.blocks = load("blocks.json")

    def _apply(self, plan, blocks=None):
        return fixloop_mod._apply_plan(self.topic, plan, blocks)

    def test_corrected_blocks_merge_by_id_and_keep_others(self):
        corrected = json.loads(json.dumps(self.blocks["blocks"][4]))  # b-05 diagram
        corrected["spec"] = dict(corrected["spec"], caption="fixed caption")
        rejected, merged = self._apply(
            {"analysis": "x" * 30, "files": {}, "blocks": [corrected]}, self.blocks
        )
        self.assertEqual(rejected, [])
        assert merged is not None
        by_id = {b["id"]: b for b in merged["blocks"]}
        self.assertEqual(by_id["b-05"]["spec"]["caption"], "fixed caption")
        self.assertEqual(len(merged["blocks"]), len(self.blocks["blocks"]))
        self.assertEqual(by_id["b-01"], self.blocks["blocks"][0])

    def test_simulation_spec_edits_are_rejected_with_feedback(self):
        corrected = json.loads(json.dumps(self.blocks["blocks"][5]))  # b-06 sim
        rejected, merged = self._apply(
            {"analysis": "x" * 30, "files": {}, "blocks": [corrected]}, self.blocks
        )
        self.assertTrue(any("simulation block(s) b-06" in r for r in rejected))
        self.assertIsNone(merged, "rejected corrections must not reach the draft")

    def test_renderer_file_in_plan_is_a_rejection_sentence(self):
        rejected, merged = self._apply(
            {"analysis": "x" * 30, "files": {"index.html": "<html></html>"}},
            self.blocks,
        )
        self.assertTrue(any("renderer-owned" in r for r in rejected))
        self.assertIsNone(merged)
        self.assertNotIn("<html></html>", (self.topic / "index.html").read_text())

    def test_rebuild_from_blocks_writes_corrected_geometry_without_nesting(self):
        # spelling guard on the method name below (lowercase w caught by lint)
        corrected = json.loads(json.dumps(self.blocks["blocks"][4]))
        corrected["spec"] = dict(corrected["spec"], caption="fixed caption")
        _, merged = self._apply(
            {"analysis": "x" * 30, "files": {}, "blocks": [corrected]}, self.blocks
        )
        assert merged is not None
        fixloop_mod._rebuild_html_if_needed(
            self.cfg, self.render_out, self.topic, merged
        )
        html = (self.topic / "index.html").read_text(encoding="utf-8")
        self.assertIn("fixed caption", html)
        for marker in (
            '<header class="zn-lang-bar">',
            '<header class="zn-header">',
            '<section class="zn-glossary">',
            '<footer class="zn-footer">',
        ):
            self.assertEqual(html.count(marker), 1, marker)
        # idempotent: a second rebuild from the same specs changes nothing
        fixloop_mod._rebuild_html_if_needed(
            self.cfg, self.render_out, self.topic, merged
        )
        self.assertIn("fixed caption", (self.topic / "index.html").read_text())

    def test_rebuild_without_blocks_still_collapses_nested_shells(self):
        # A page left poisoned by an older runner (shells nested; seen in the
        # wild 2026-11-09) must be normalized, not joined again.
        _, topic, render_out = make_page(self.tmp / "poison")
        good = (topic / "index.html").read_text(encoding="utf-8")
        (topic / "index.html").write_text(good + good, encoding="utf-8")
        fixloop_mod._rebuild_html_if_needed(self.cfg, render_out, topic)
        html = (topic / "index.html").read_text(encoding="utf-8")
        self.assertEqual(html.count('<header class="zn-header">'), 1)
        self.assertEqual(html.count('<section class="zn-glossary">'), 1)


if __name__ == "__main__":
    unittest.main()
