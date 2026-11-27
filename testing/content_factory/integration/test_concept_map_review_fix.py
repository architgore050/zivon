"""Review->fix chain for missing concepts (the deterministic concept-map gate).

A `concept_map` finding that is FATAL routes to the existing bounded 10-reviewfix
catcher (not a whole-pipeline re-run); the fixer's optional `concept_map` output
becomes the effective map for re-review; re-review re-derives the SAME
deterministic `factory.concept_map_verify.concept_coverage_problems` findings
on the corrected blocks + manifest + effective map; on final verdict=pass the
effective map is persisted via `factory.syllabus.write_tracked_map`; a map that
never becomes clean exhausts the bounded loop -> `factory.repair.exhausted` +
`ErrorClass.REPAIR_EXHAUSTED`. No model calls; no Chromium; key-free.
"""

from __future__ import annotations

import dataclasses
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, cast
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import stages
from factory.artifacts import RunContext
from factory.errors import StageError
from factory.llm import LLMClient
from factory.render import run as render_run
from testing.content_factory.unit.test_render import make_cfg, minimal_inputs

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"

KNOWN = ["k1"]  # one curated concept the synthetic syllabus reports

# The synthetic tracked syllabus the tests aim the syllabus path at: the
# canonical resolver (factory.syllabus.resolve_chapter -> canonical_chapter_id)
# runs for REAL against this data instead of being mocked out (issue #118).
SYNTH_CHAPTER = {
    "chapter_id": "class-9-motion",
    "title": "Motion",
    "concepts": [
        {
            "concept_id": "k1",
            "title": "Motion basics",
            "description": "Distance, displacement and speed of a moving body",
        }
    ],
}


def _write_test_syllabus(tmp: Path, chapter: dict[str, Any] | None = None) -> Path:
    path = tmp / "sources" / "syllabus" / "syllabus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"classes": [{"class": 9, "chapters": [chapter or SYNTH_CHAPTER]}]}),
        encoding="utf-8",
    )
    return path


def _seeded_sections(run_ctx: RunContext) -> list[dict[str, Any]]:
    """The manifest sections of the seeded 06-render artifact."""
    return list(run_ctx.load_stage_output("06-render")["manifest"]["sections"])


def load(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class MockLLM:
    """No model calls: 09-review's two calls return no extra issues; the
    10-reviewfix call returns a fixed plan."""

    def __init__(self, reviewfix_plan: dict[str, Any]):
        self.reviewfix_plan = reviewfix_plan
        self.calls: list[str] = []

    def call(self, stage_id, messages, schema, schema_name, **kw):
        self.calls.append(stage_id)
        if stage_id == "10-reviewfix":
            return json.loads(json.dumps(self.reviewfix_plan))
        return {"issues": []}


def _seed(
    tmp: Path, run_ctx: RunContext, cfg, concept_map: dict[str, Any]
) -> dict[str, Any]:
    """Render a real page once; seed 02-generate + 06-render artifacts."""
    source_pack, lesson, blocks, interactive = minimal_inputs()
    render_out = render_run(
        cfg, run_ctx, "Motion", source_pack, lesson, blocks, interactive
    )
    sections = [s["id"] for s in render_out["manifest"]["sections"]]
    generated = {
        "ground_truth": load("gt.json"),
        "lesson": lesson,
        "blocks": blocks,
        "concept_map": concept_map,
    }
    run_ctx.save_stage_output("02-generate", generated)
    run_ctx.mark_stage("02-generate", "ok")
    run_ctx.save_stage_output("01-locate", source_pack)
    run_ctx.mark_stage("01-locate", "ok")
    run_ctx.save_stage_output("06-render", render_out)
    run_ctx.mark_stage("06-render", "ok")
    run_ctx.set_fingerprint("fp")  # matches the patched run_fingerprint
    return {"render_out": render_out, "sections": sections, "blocks": blocks}


class ConceptMapReviewFixIntegration(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, _ = make_cfg(self.tmp)
        self.cfg = dataclasses.replace(self.cfg, root=self.tmp)
        # doctrine is repo-relative; keep repo root for reads.
        self.cfg = dataclasses.replace(self.cfg, root=REPO_ROOT)
        self.cfg = dataclasses.replace(
            self.cfg, data={**self.cfg.data, "paths": {**self.cfg.paths}}
        )
        (self.tmp / "frontend").mkdir(exist_ok=True)
        self.run_id = "concept-map-fix"
        self.runs_dir = self.cfg.repo_path(self.cfg.paths["runs"])
        self.run_ctx = RunContext(self.runs_dir, self.run_id)
        # The synthetic tracked syllabus (canonical resolution runs for real)
        # and the tracked-map write target both live in this test's tmp dir.
        self.syllabus_path = _write_test_syllabus(self.tmp)
        self.tracked_out = (
            REPO_ROOT / "tmp" / "concept-map-test" / f"tracked-{id(self)}.json"
        )
        self.tracked_out.parent.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: self.tracked_out.unlink(missing_ok=True))

    def _run(self, llm: MockLLM, run_id: str | None = None) -> dict[str, Any]:
        tracked = (
            self.tracked_path
            if getattr(self, "tracked_path", None)
            else self.tracked_out
        )
        with (
            mock.patch("factory.stages.LLMClient", return_value=cast(LLMClient, llm)),
            mock.patch("factory.stages.run_fingerprint", return_value="fp"),
            mock.patch("factory.review.shots.capture", return_value=[]),
            # aim the tracked-syllabus READ at the synthetic file so review,
            # reviewfix, agents and persistence all resolve the chapter
            # canonically through the real resolver (issue #118)
            mock.patch(
                "factory.syllabus._syllabus_path", return_value=self.syllabus_path
            ),
            mock.patch(
                "factory.reviewfix._harness",
                return_value=lambda url, profile: {"pass": True, "failures": []},
            ),
            mock.patch("factory.syllabus.tracked_map_path", return_value=tracked),
        ):
            return stages.run_pipeline(
                self.cfg,
                "Motion",
                None,
                run_id or self.run_id,
                only_stages=["09-review", "10-reviewfix"],
            )

    # ------------------------------------------------- concept_map fatal routing
    def test_concept_map_fatal_routes_to_reviewfix_correction_applied_and_persisted(
        self,
    ) -> None:
        seeded = _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = seeded["sections"]
        corrected = {sid: "k1" for sid in sections}
        llm = MockLLM(
            {
                "analysis": "map every section to the one curated concept; no "
                "orphan, no unknown id, keys match current section ids",
                "files": {},
                "concept_map": corrected,
            }
        )

        self._run(llm)

        # a concept_map fatal routed to 10-reviewfix once, then re-review passed
        self.assertIn("10-reviewfix", llm.calls)
        review_out = json.loads(
            (self.run_ctx.stage_dir("09-review") / "output.json").read_text()
        )
        self.assertEqual(review_out["verdict"], "pass")
        # no concept_map fatals remain on the final round
        self.assertFalse(
            any(
                i.get("category") == "concept_map" and i["severity"] == "fatal"
                for i in review_out["issues"]
            )
        )
        # 10-reviewfix emitted the optional concept_map; correction applied
        fix_out = json.loads(
            (self.run_ctx.stage_dir("10-reviewfix") / "output.json").read_text()
        )
        self.assertEqual(fix_out["concept_map"], corrected)
        # map persisted on final verdict=pass
        self.assertTrue(self.tracked_out.exists())
        tracked = json.loads(self.tracked_out.read_text())
        self.assertEqual(tracked["section_concept_map"], corrected)
        self.assertTrue(
            json.loads((self.run_ctx.dir / "status.json").read_text())["stages"][
                "09-review"
            ]["state"]
            == "ok"
        )

    def test_initial_round_emits_fatal_concept_map_before_any_fix(self) -> None:
        # first 09-review (no 10-reviewfix yet) reports fatal concept_map
        seeded = _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = seeded["sections"]
        corrected = {sid: "k1" for sid in sections}
        llm = MockLLM(
            {
                "analysis": "map every section to the one curated concept; no "
                "orphan, no unknown id, keys match current section ids",
                "files": {},
                "concept_map": corrected,
            }
        )
        self._run(llm)
        # the persisted final output is a pass; evidence of first-round fail is
        # in issues_ledger; assert a concept_map fatal was recorded
        ledger = (
            (self.run_ctx.dir / "issues_ledger.jsonl").read_text().strip().splitlines()
        )
        rows = [json.loads(line) for line in ledger]
        self.assertTrue(
            any(
                r["category"] == "concept_map"
                and r["severity"] == "fatal"
                and r["call"] == "concept_map"
                for r in rows
            ),
            rows,
        )

    # ------------------------------------------------------- bounded + exhausted
    def test_map_that_never_becomes_clean_exhausts_and_repair_exhausted(self) -> None:
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        # fixer never fixes the concept map and never adds content
        llm = MockLLM(
            {
                "analysis": "no concept map fix applied; output nothing useful",
                "files": {},
            }
        )
        events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        with (
            mock.patch(
                "factory.stages.log_event",
                side_effect=lambda name, fields=None, **kw: events.append(
                    (name, fields or {}, kw)
                ),
            ),
            self.assertRaises(StageError),
        ):
            self._run(llm)
        exhausted = [e for e in events if e[0] == "factory.repair.exhausted"]
        self.assertTrue(exhausted, events)
        # closed error class REPAIR_EXHAUSTED (factory.repair.exhausted)
        self.assertTrue(
            any(
                getattr(kw.get("error_class"), "value", kw.get("error_class"))
                == "repair_exhausted"
                for _, _, kw in exhausted
            ),
            exhausted,
        )
        # nothing persisted on a non-pass
        self.assertFalse(self.tracked_out.exists())

    def test_stall_limit_and_round_cap_are_bounded(self) -> None:
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        llm = MockLLM({"analysis": "noop no concept map fix", "files": {}})
        with self.assertRaises(StageError):
            self._run(llm)
        # bounded: at most repair.code_rounds 10-reviewfix rounds, never a
        # whole-pipeline re-run
        n = len([c for c in llm.calls if c == "10-reviewfix"])
        self.assertLessEqual(n, self.cfg.repair["code_rounds"])
        self.assertGreaterEqual(n, 1)

    # ------------------------------------------------------- resume threading
    def test_resume_judges_the_reviewfix_correction_without_a_new_fix_round(
        self,
    ) -> None:
        # Attempt 1: the fixer never corrects the map -> bounded loop exhausts.
        seeded = _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = seeded["sections"]
        corrected = {sid: "k1" for sid in sections}
        with self.assertRaises(StageError):
            self._run(MockLLM({"analysis": "noop", "files": {}}))
        # The dead attempt's LAST fixer round had returned the corrected map
        # (the artifact on disk) but the process died before the re-review:
        # replay exactly that artifact state.
        fix_dir = self.run_ctx.stage_dir("10-reviewfix")
        fix_out = json.loads((fix_dir / "output.json").read_text())
        fix_out["concept_map"] = corrected
        (fix_dir / "output.json").write_text(json.dumps(fix_out))
        # Attempt 2 (resume, same deterministic run dir): the first re-review
        # judges the corrected map and PASSES - no new fixer round is spent,
        # and the map is persisted from the resumed pass.
        llm2 = MockLLM({"analysis": "noop", "files": {}})
        self._run(llm2)
        self.assertNotIn("10-reviewfix", llm2.calls, llm2.calls)
        tracked = json.loads(self.tracked_out.read_text())
        self.assertEqual(tracked["section_concept_map"], corrected)

    # --------------------------------------------- durable persistence (#118)
    def test_persistence_writes_durable_artifact_and_tracked_map_before_ok(
        self,
    ) -> None:
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = [s["id"] for s in _seeded_sections(self.run_ctx)]
        corrected = {sid: "k1" for sid in sections}
        llm = MockLLM(
            {
                "analysis": "map every section to the one curated concept",
                "files": {},
                "concept_map": corrected,
            }
        )
        self._run(llm)
        # the durable run artifact exists and carries the exact tracked payload
        artifact = self.run_ctx.stage_dir("09-review") / "concept-map.json"
        self.assertTrue(artifact.exists())
        durable = json.loads(artifact.read_text())
        tracked = json.loads(self.tracked_out.read_text())
        self.assertEqual(durable, tracked)
        self.assertEqual(durable["chapter_id"], "class-9-motion")  # canonical key
        # the stage is ok only AFTER both writes: ok + artifact + tracked all present
        status = json.loads((self.run_ctx.dir / "status.json").read_text())
        self.assertEqual(status["stages"]["09-review"]["state"], "ok")

    def test_tracked_write_failure_fails_the_stage_and_keeps_the_artifact(
        self,
    ) -> None:
        # Failure injection (issue #118): the tracked-sources path is not
        # writable (here: its parent is a FILE, like a missing/locked mount).
        # The run must fail loudly with the durable artifact still on disk and
        # 09-review NOT ok - never silently resume without a map.
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = [s["id"] for s in _seeded_sections(self.run_ctx)]
        corrected = {sid: "k1" for sid in sections}
        llm = MockLLM(
            {
                "analysis": "map every section to the one curated concept",
                "files": {},
                "concept_map": corrected,
            }
        )
        blocked = self.tmp / "blocked-sources"  # a FILE, not a directory
        blocked.write_text("not a directory", encoding="utf-8")
        self.tracked_path = blocked / "concept-map.json"
        self.addCleanup(lambda: setattr(self, "tracked_path", None))
        events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        with (
            mock.patch(
                "factory.artifacts.log_event",
                side_effect=lambda name, fields=None, **kw: events.append(
                    (name, fields or {}, kw)
                ),
            ),
            self.assertRaises(StageError) as ctx,
        ):
            self._run(llm)
        self.assertIn("tracked concept map persistence failed", str(ctx.exception))
        status = json.loads((self.run_ctx.dir / "status.json").read_text())
        self.assertEqual(status["stages"]["09-review"]["state"], "failed")
        # the failure carries its OWN reason code (PersistenceError, issue
        # #118): an operational fix (mount/volume), not a review plateau
        self.assertTrue(
            any(
                name == "factory.stage.fail"
                and kw.get("stage") == "09-review"
                and (fields or {}).get("reason_code") == "map_persistence_failed"
                for name, fields, kw in events
            ),
            events,
        )
        # the durable artifact was written BEFORE the tracked write failed
        artifact = self.run_ctx.stage_dir("09-review") / "concept-map.json"
        self.assertTrue(artifact.exists())
        durable = json.loads(artifact.read_text())
        self.assertEqual(durable["section_concept_map"], corrected)

    def test_resume_retries_persistence_from_the_saved_passing_report(
        self,
    ) -> None:
        # A run that passed review and lost its tracked write (readonly
        # rootfs): re-triggering RESUMES the persistence from the saved
        # passing report instead of resuming without a map.
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = [s["id"] for s in _seeded_sections(self.run_ctx)]
        corrected = {sid: "k1" for sid in sections}
        llm = MockLLM(
            {
                "analysis": "map every section to the one curated concept",
                "files": {},
                "concept_map": corrected,
            }
        )
        self._run(llm)
        self.assertTrue(self.tracked_out.exists())
        self.tracked_out.unlink()  # the tracked write was lost after the pass
        # re-trigger: 09-review is ok -> the gate retries persistence only
        llm2 = MockLLM({"analysis": "noop", "files": {}})
        self._run(llm2)
        self.assertEqual(llm2.calls, [])  # no review, no fixer: resume only
        tracked = json.loads(self.tracked_out.read_text())
        self.assertEqual(tracked["section_concept_map"], corrected)

    # ---------------------------------- new-block section identity + manifest
    def test_fixer_appended_block_lands_in_its_declared_section_and_manifest(
        self,
    ) -> None:
        # issue #118: a teaching block the fixer appends with an explicit
        # section_id is rendered under THAT section (never silently inherited
        # by reader order) and the refreshed manifest names it (sections'
        # block_ids, block map, counts, content hash) before the re-review.
        seeded = _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = [s["id"] for s in _seeded_sections(self.run_ctx)]
        first = sections[0]
        last = sections[-1]
        corrected = {sid: "k1" for sid in sections}
        teaching_block = {
            "id": "b-09",
            "type": "text",
            "spec": {
                "paragraphs": [
                    "The motor spins because the commutator reverses the current in the coil."
                ]
            },
            "citations": [],
            "section_id": first,  # declared: appended at the END of the draft
        }
        llm = MockLLM(
            {
                "analysis": "add a real teaching block under the mapped section",
                "files": {},
                "blocks": [teaching_block],
                "concept_map": corrected,
            }
        )
        self._run(llm)
        manifest = json.loads(
            (
                Path(self.run_ctx.load_stage_output("06-render")["topic_dir"])
                / "manifest.json"
            ).read_text()
        )
        # the appended block sits in its DECLARED section, not the last one
        self.assertIn("b-09", manifest["blocks"])
        self.assertEqual(manifest["blocks"]["b-09"]["section_id"], first)
        by_section = {s["id"]: s["block_ids"] for s in manifest["sections"]}
        self.assertIn("b-09", by_section[first])
        self.assertNotIn("b-09", by_section.get(last, []))
        self.assertEqual(
            manifest["counts"]["lesson_blocks"],
            seeded["render_out"]["manifest"]["counts"]["lesson_blocks"] + 1,
        )
        # the rebuilt page renders the block inside the declared section wrapper
        html = (
            Path(self.run_ctx.load_stage_output("06-render")["topic_dir"])
            / "index.html"
        ).read_text()
        self.assertIn('id="b-09"', html)
        # the scoped keyword gate passes on the teaching content: re-review ok
        review_out = json.loads(
            (self.run_ctx.stage_dir("09-review") / "output.json").read_text()
        )
        self.assertEqual(review_out["verdict"], "pass")

    # ------------------------------- section-scoped keyword coverage (#118)
    def test_remap_without_teaching_is_flagged_by_the_scoped_gate(self) -> None:
        # seeded "remap without teaching" defect: k1's keyword (commutator)
        # appears ONLY in a block under sec-02 while k1 is mapped to sec-01.
        # The SECTION-SCOPED gate must flag it (a global text search would
        # pass - that was the pre-#118 behavior).
        two_concepts = {
            "chapter_id": "class-9-motion",
            "title": "Motion",
            "concepts": [
                {
                    "concept_id": "k1",
                    "title": "Motion basics",
                    "description": "Distance, displacement and speed",
                },
                {
                    "concept_id": "k2",
                    "title": "Forces",
                    "description": "How forces change motion",
                },
            ],
        }
        self.syllabus_path = _write_test_syllabus(self.tmp, two_concepts)
        self.addCleanup(lambda: setattr(self, "syllabus_path", None))
        _seed(self.tmp, self.run_ctx, self.cfg, concept_map={})
        sections = [s["id"] for s in _seeded_sections(self.run_ctx)]
        remap = {sections[0]: "k1", sections[-1]: "k2"}
        # remap everything to k1 EXCEPT the section that owns the keyword text
        remap = {sid: "k1" for sid in sections}
        remap[sections[-1]] = "k2"
        plan = {
            "analysis": "remap without teaching",
            "files": {},
            "blocks": [
                {
                    "id": "b-10",
                    "type": "text",
                    "spec": {"paragraphs": ["A motor uses a commutator."]},
                    "citations": [],
                    "section_id": sections[-1],
                }
            ],
            "concept_map": remap,
        }
        llm = MockLLM(plan)
        with (
            mock.patch(
                "factory.concept_map_verify.TOPIC_KEYWORDS",
                {"k1 motor": ("k1", ("commutator",))},
            ),
            self.assertRaises(StageError),
        ):
            self._run(llm)
        review_out = json.loads(
            (self.run_ctx.stage_dir("09-review") / "output.json").read_text()
        )
        self.assertEqual(review_out["verdict"], "fail")
        self.assertTrue(
            any(
                i["category"] == "concept_map" and "keywords" in i["message"]
                for i in review_out["issues"]
            ),
            review_out["issues"],
        )


class EffectiveConceptMapResume(unittest.TestCase):
    """`factory.stages._effective_concept_map` re-derives the map a resumed
    review loop must judge from run artifacts, in the order the events
    happened (fixer correction > last judged map > 02-generate's map)."""

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, _ = make_cfg(self.tmp)
        self.cfg = dataclasses.replace(self.cfg, root=REPO_ROOT)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-eff-map"
        )
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _seed(self, **stage_outputs: Any) -> None:
        for stage_id, output in stage_outputs.items():
            self.run_ctx.save_stage_output(stage_id, output)

    def test_fixer_correction_wins_over_stale_sources(self) -> None:
        self._seed(
            **{
                "02-generate": {"concept_map": {"sec-01": "m1"}},
                "09-review": {"concept_map": {"sec-01": "m2"}},
                "10-reviewfix": {"concept_map": {"sec-01": "m3"}},
            }
        )
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {"sec-01": "m3"})

    def test_last_judged_report_map_is_the_second_source(self) -> None:
        # the fixer's LAST round kept the previous map (concept_map: None)
        self._seed(
            **{
                "02-generate": {"concept_map": {"sec-01": "m1"}},
                "09-review": {"concept_map": {"sec-01": "m2"}},
                "10-reviewfix": {"concept_map": None},
            }
        )
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {"sec-01": "m2"})

    def test_falls_back_to_the_generated_map(self) -> None:
        self._seed(**{"02-generate": {"concept_map": {"sec-01": "m1"}}})
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {"sec-01": "m1"})

    def test_missing_artifacts_yield_an_empty_map(self) -> None:
        self._seed(**{"02-generate": {"blocks": {"blocks": []}}})
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {})

    def test_explicit_empty_fixer_correction_is_never_discarded(self) -> None:
        # issue #118 (minor): presence of the field, not truthiness, decides -
        # an explicit `{}` correction replaces a stale map instead of being
        # silently dropped in favour of the last judged map.
        self._seed(
            **{
                "02-generate": {"concept_map": {"sec-01": "m1"}},
                "09-review": {"concept_map": {"sec-01": "m1"}},
                "10-reviewfix": {"concept_map": {}},
            }
        )
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {})

    def test_explicit_empty_judged_map_is_the_second_source(self) -> None:
        self._seed(
            **{
                "02-generate": {"concept_map": {"sec-01": "m1"}},
                "09-review": {"concept_map": {}},
            }
        )
        self.assertEqual(stages._effective_concept_map(self.run_ctx), {})


if __name__ == "__main__":
    unittest.main()
