"""The separate assessment entrypoint end to end: A1-A6, resume, gates, events."""

from __future__ import annotations

import dataclasses
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from factory.assessment.config import AssessmentConfig
from factory.assessment.errors import AssessmentGateError, AssessmentStageError
from factory.assessment.pipeline import (
    assemble_chapter_pack,
    make_run_id,
    run_assessment,
)
from logging_manager import sink
from testing.observability.support import capture_events, reset_context

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAPTER = "class-9-describing-motion-around-us"
ALL_STAGES = [
    "A1-syllabus",
    "A2-concept-tag",
    "A3-practice-items",
    "A4-speaking-rubrics",
    "A5-time-priors",
    "A6-publish-export",
]


class PipelineTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.runs = self.root / "runs"
        self.exports = self.root / "exports"
        sink.reset_for_tests(runs_dir=str(self.root / "logs"))
        reset_context()

    def tearDown(self) -> None:
        sink.reset_for_tests()
        reset_context()
        self._tmp.cleanup()

    def cfg(self, **overrides) -> AssessmentConfig:
        cfg = AssessmentConfig.for_repo(
            REPO_ROOT, runs_dir=self.runs, export_dir=self.exports
        )
        if overrides:
            cfg = dataclasses.replace(cfg, **overrides)
        return cfg

    def stage_dir(self, run_id: str, stage: str) -> Path:
        return self.runs / run_id / stage


class TestFullRun(PipelineTestBase):
    def test_run_writes_every_stage_status_and_pack(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            result = run_assessment(cfg, [CHAPTER])
        self.assertTrue(result["ok"])
        run_id = result["runs"][0]["run_id"]
        self.assertEqual(run_id, make_run_id(CHAPTER))
        status = json.loads((self.runs / run_id / "status.json").read_text())
        self.assertEqual(set(status["stages"]), set(ALL_STAGES))
        for stage in ALL_STAGES:
            self.assertEqual(status["stages"][stage]["state"], "ok", stage)
            self.assertTrue((self.stage_dir(run_id, stage) / "output.json").is_file())
        pack_dir = self.stage_dir(run_id, "A6-publish-export") / "pack"
        manifest = json.loads((pack_dir / "manifest.json").read_text())
        self.assertEqual(manifest["gate"]["verdict"], "pass")
        self.assertEqual(manifest["counts"]["base_items"], 15)
        self.assertEqual(len(manifest["files"]), 5)
        report = json.loads((self.runs / run_id / "run_report.json").read_text())
        self.assertTrue(report["ok"])
        self.assertEqual(set(report["stage_durations_s"]), set(ALL_STAGES))
        names = [event["event"] for event in events]
        self.assertIn("factory.assessment.run.started", names)
        self.assertIn("factory.assessment.pack.written", names)
        self.assertIn("factory.assessment.run.completed", names)
        self.assertIn("factory.stage.ok", names)

    def test_export_dir_mirrors_one_directory_per_chapter(self) -> None:
        result = run_assessment(self.cfg(), [CHAPTER])
        exported = Path(result["runs"][0]["exported_dir"])
        self.assertEqual(exported, self.exports / CHAPTER)
        self.assertTrue((exported / "manifest.json").is_file())
        self.assertTrue((exported / "questions.json").is_file())

    def test_events_carry_no_content_fields(self) -> None:
        with capture_events() as events:
            run_assessment(self.cfg(), [CHAPTER])
        allowed = {
            "chapter_id",
            "class_level",
            "generator",
            "languages",
            "fresh",
            "resumed",
            "chapters_count",
            "items_count",
            "speaking_prompts_count",
            "question_rows",
            "content_hash",
            "base_items",
            "exported",
            "failed_stage",
            "reason_code",
            "error_count",
            "blocks",
            "attempts",
        }
        for event in events:
            if event.get("component") not in ("factory", "evals"):
                continue  # the logging module's own sink-health events
            for key in event.get("fields") or {}:
                self.assertIn(key, allowed, event["event"])

    def test_run_started_event_declares_the_generator_and_languages(self) -> None:
        with capture_events() as events:
            run_assessment(self.cfg(), [CHAPTER])
        started = next(
            e for e in events if e["event"] == "factory.assessment.run.started"
        )
        self.assertEqual(started["fields"]["chapter_id"], CHAPTER)
        self.assertEqual(started["fields"]["generator"], "seed")
        self.assertEqual(started["fields"]["languages"], "en,hi,hi-Latn")


class TestResume(PipelineTestBase):
    def test_second_run_reuses_every_stage(self) -> None:
        cfg = self.cfg()
        first = run_assessment(cfg, [CHAPTER])
        run_id = first["runs"][0]["run_id"]
        snapshot = {
            stage: (self.stage_dir(run_id, stage) / "output.json").read_bytes()
            for stage in ALL_STAGES
        }
        with capture_events() as events:
            second = run_assessment(cfg, [CHAPTER])
        self.assertTrue(second["ok"])
        started = next(
            e for e in events if e["event"] == "factory.assessment.run.started"
        )
        self.assertTrue(started["fields"]["resumed"])
        self.assertNotIn("factory.stage.start", [event["event"] for event in events])
        for stage, payload in snapshot.items():
            self.assertEqual(
                (self.stage_dir(run_id, stage) / "output.json").read_bytes(),
                payload,
                stage,
            )

    def test_export_dir_is_honoured_on_a_resumed_run(self) -> None:
        cfg = self.cfg(export_dir=None)
        run_assessment(cfg, [CHAPTER])
        with capture_events():
            result = run_assessment(self.cfg(), [CHAPTER])
        exported = Path(result["runs"][0]["exported_dir"])
        self.assertEqual(exported, self.exports / CHAPTER)
        self.assertTrue((exported / "manifest.json").is_file())
        run_id = make_run_id(CHAPTER)
        stage_output = json.loads(
            (self.stage_dir(run_id, "A6-publish-export") / "output.json").read_text()
        )
        self.assertEqual(stage_output["exported_dir"], str(exported))

    def test_a_different_fingerprint_refuses_resume(self) -> None:
        run_assessment(self.cfg(), [CHAPTER])
        with self.assertRaises(AssessmentStageError) as ctx:
            run_assessment(self.cfg(generator="llm"), [CHAPTER])
        self.assertIn("different fingerprint", str(ctx.exception))

    def test_partial_stage_rerun_loads_upstream_from_disk(self) -> None:
        cfg = self.cfg()
        run_assessment(cfg, [CHAPTER])
        run_id = make_run_id(CHAPTER)
        status_path = self.runs / run_id / "status.json"
        status = json.loads(status_path.read_text())
        status["stages"].pop("A5-time-priors")
        status_path.write_text(json.dumps(status))
        shutil.rmtree(self.stage_dir(run_id, "A5-time-priors"))
        with capture_events() as events:
            result = run_assessment(cfg, [CHAPTER], only_stages=["A5-time-priors"])
        self.assertTrue(result["ok"])
        starts = [
            (event.get("stage"), event["event"])
            for event in events
            if event["event"] == "factory.stage.start"
        ]
        self.assertEqual(starts, [("A5-time-priors", "factory.stage.start")])


class TestGates(PipelineTestBase):
    def _broken_cfg(self) -> AssessmentConfig:
        chapters = self.root / "chapters"
        chapters.mkdir()
        source = AssessmentConfig.for_repo(REPO_ROOT).chapters_dir
        for path in source.glob(f"{CHAPTER}.*"):
            shutil.copy2(path, chapters / path.name)
        items_path = chapters / f"{CHAPTER}.items.json"
        bank = json.loads(items_path.read_text(encoding="utf-8"))
        bank["items"][0]["answer"] = {"index": 99}
        items_path.write_text(json.dumps(bank), encoding="utf-8")
        return self.cfg(chapters_dir=chapters)

    def test_gate_failure_writes_the_report_and_marks_the_stage_failed(self) -> None:
        cfg = self._broken_cfg()
        with capture_events() as events, self.assertRaises(AssessmentGateError) as ctx:
            run_assessment(cfg, [CHAPTER])
        report = ctx.exception.report
        self.assertEqual(report["verdict"], "fail")
        rules = {issue["rule"] for issue in report["issues"]}
        self.assertIn("item.answer.index", rules)
        run_id = make_run_id(CHAPTER)
        status = json.loads((self.runs / run_id / "status.json").read_text())
        self.assertEqual(status["stages"]["A3-practice-items"]["state"], "failed")
        stage_output = json.loads(
            (self.stage_dir(run_id, "A3-practice-items") / "output.json").read_text()
        )
        self.assertEqual(stage_output["gate"]["verdict"], "fail")
        run_report = json.loads((self.runs / run_id / "run_report.json").read_text())
        self.assertFalse(run_report["ok"])
        failed = [e for e in events if e["event"] == "factory.assessment.run.failed"]
        self.assertEqual(failed[0]["fields"]["failed_stage"], "A3-practice-items")
        self.assertEqual(failed[0]["fields"]["reason_code"], "practice_gate_failed")

    def test_the_lesson_stage_order_is_never_touched(self) -> None:
        from factory.assessment import ASSESSMENT_STAGE_ORDER
        from factory.stages import STAGE_ORDER

        self.assertFalse(set(ASSESSMENT_STAGE_ORDER) & set(STAGE_ORDER))
        self.assertEqual(STAGE_ORDER[-1], "12-narration")


class TestPureAssembly(PipelineTestBase):
    def test_assemble_chapter_pack_runs_every_stage_without_a_run_dir(self) -> None:
        result = assemble_chapter_pack(self.cfg(), CHAPTER)
        self.assertEqual(result["items"]["gate"]["verdict"], "pass")
        self.assertEqual(result["assembled"]["manifest"]["counts"]["question_rows"], 45)
        self.assertFalse(self.runs.exists())

    def test_unknown_chapter_is_refused(self) -> None:
        with self.assertRaises(AssessmentStageError):
            assemble_chapter_pack(self.cfg(), "class-10-nope")

    def test_pending_class_11_chapter_is_refused(self) -> None:
        with self.assertRaises(AssessmentStageError):
            assemble_chapter_pack(self.cfg(), "class-11-motion-in-a-straight-line")


if __name__ == "__main__":
    unittest.main()
