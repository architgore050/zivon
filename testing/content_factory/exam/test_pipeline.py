"""The exam/series entrypoint end to end: E1-E4, resume, gates, events, CLI."""

from __future__ import annotations

import dataclasses
import json
import tempfile
import unittest
from pathlib import Path

from factory.exam.__main__ import main
from factory.exam.errors import ExamGateError, ExamStageError
from factory.exam.pipeline import make_run_id, run_exam
from logging_manager import sink
from testing.content_factory.exam.support import (
    REPO_ROOT,
    temp_exam_config,
)
from testing.observability.support import capture_events, reset_context

ALL_STAGES = ["E1-ingest", "E2-blueprint", "E3-series", "E4-publish"]


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

    def cfg(self, **overrides):
        cfg, handle = temp_exam_config(self.root)
        self.addCleanup(handle.cleanup)
        if overrides:
            cfg = dataclasses.replace(cfg, **overrides)
        return cfg

    def stage_dir(self, run_id: str, stage: str) -> Path:
        return self.runs / run_id / stage


class FullRunTests(PipelineTestBase):
    def test_a_run_writes_every_stage_and_the_pack(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            result = run_exam(cfg, [10])
        run_id = make_run_id(10)
        status = json.loads(
            (self.runs / run_id / "status.json").read_text(encoding="utf-8")
        )
        for stage in ALL_STAGES:
            self.assertEqual(status["stages"][stage]["state"], "ok", stage)
            self.assertTrue((self.runs / run_id / stage / "output.json").is_file())
        pack = self.runs / run_id / "E4-publish" / "pack"
        for name in (
            "papers.json",
            "blueprint.json",
            "items.json",
            "series.json",
            "manifest.json",
        ):
            self.assertTrue((pack / name).is_file(), name)
        self.assertTrue(result["ok"])
        self.assertFalse(result["runs"][0]["publishable"])
        names = [event["event"] for event in events]
        self.assertIn("factory.exam.run.started", names)
        self.assertIn("factory.exam.run.completed", names)
        self.assertIn("factory.exam.pack.written", names)
        self.assertIn("exam.series.blocked", names)

    def test_ingest_events_carry_metadata_only(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            run_exam(cfg, [10])
        allowed = {"paper_id", "class_level", "chapter_id", "type", "marks"}
        ingested = [event for event in events if event["event"] == "exam.item.ingested"]
        self.assertEqual(len(ingested), 98)  # 7 class-10 papers x 14 questions
        for event in ingested:
            self.assertEqual(set(event["fields"]), allowed)
            self.assertNotIn("class-12-", str(event["fields"]))

    def test_no_event_carries_question_text(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            run_exam(cfg, [10])
        blob = json.dumps(events, ensure_ascii=False)
        self.assertNotIn("angle of incidence", blob)
        self.assertNotIn("refractive", blob)

    def test_the_completed_event_reports_the_publish_decision(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            run_exam(cfg, [10])
        completed = [
            event for event in events if event["event"] == "factory.exam.run.completed"
        ][-1]
        self.assertFalse(completed["fields"]["publishable"])
        self.assertEqual(completed["fields"]["series_count"], 6)
        self.assertGreater(completed["fields"]["question_rows"], 0)

    def test_two_classes_run_independently(self) -> None:
        cfg = self.cfg()
        result = run_exam(cfg, [10, 12])
        self.assertEqual(len(result["runs"]), 2)
        self.assertEqual(result["runs"][0]["class_num"], 10)
        self.assertEqual(result["runs"][1]["class_num"], 12)
        self.assertEqual(result["runs"][1]["items"], 0)


class ResumeTests(PipelineTestBase):
    def test_a_second_run_reuses_every_stage(self) -> None:
        cfg = self.cfg()
        first = run_exam(cfg, [10])
        with capture_events() as events:
            second = run_exam(cfg, [10])
        self.assertEqual(
            first["runs"][0]["content_hash"], second["runs"][0]["content_hash"]
        )
        started = [event for event in events if event["event"] == "factory.stage.start"]
        self.assertEqual(started, [])
        run_started = [
            event for event in events if event["event"] == "factory.exam.run.started"
        ][-1]
        self.assertTrue(run_started["fields"]["resumed"])

    def test_a_different_fingerprint_refuses_resume(self) -> None:
        cfg = self.cfg()
        run_exam(cfg, [10])
        changed = dataclasses.replace(
            cfg,
            blueprint=dataclasses.replace(cfg.blueprint, recency_decay=0.5),
        )
        with self.assertRaises(ExamStageError) as ctx:
            run_exam(changed, [10])
        self.assertIn("different fingerprint", str(ctx.exception))

    def test_an_item_bank_edit_invalidates_the_run(self) -> None:
        # The series are assembled from the P2 banks; editing one must not be
        # silently swallowed by a resume of E3/E4 built from the old bank.
        banks = self.root / "banks"
        banks.mkdir()
        bank = banks / "class-10-light-reflection-and-refraction.items.json"
        bank.write_text('{"items": []}', encoding="utf-8")
        cfg = dataclasses.replace(self.cfg(), chapters_dir=banks)
        run_exam(cfg, [10])
        bank.write_text('{"items": [], "edited": true}', encoding="utf-8")
        with self.assertRaises(ExamStageError) as ctx:
            run_exam(cfg, [10])
        self.assertIn("different fingerprint", str(ctx.exception))

    def test_fresh_wipes_and_rebuilds(self) -> None:
        cfg = self.cfg()
        run_exam(cfg, [10])
        result = run_exam(cfg, [10], fresh=True)
        self.assertEqual(result["runs"][0]["class_num"], 10)

    def test_a_targeted_stage_reloads_upstream_from_disk(self) -> None:
        cfg = self.cfg()
        run_exam(cfg, [10])
        result = run_exam(cfg, [10], only_stages=["E4-publish"])
        self.assertEqual(result["runs"][0]["question_rows"], 45)

    def test_an_unknown_stage_is_refused(self) -> None:
        with self.assertRaises(ExamStageError):
            run_exam(self.cfg(), [10], only_stages=["E9-nope"])


class GateFailureTests(PipelineTestBase):
    def test_a_broken_fixture_fails_the_ingest_stage_with_a_report(self) -> None:
        papers = self.root / "papers"
        papers.mkdir()
        source = (
            REPO_ROOT
            / "sources"
            / "exam"
            / "papers"
            / "cbse-c12-physics-2024-main.json"
        )
        document = json.loads(source.read_text(encoding="utf-8"))
        document["questions"][0]["chapter_id"] = "class-12-not-real"
        (papers / "broken.json").write_text(json.dumps(document), encoding="utf-8")
        cfg = self.cfg(papers_dir=papers)
        with capture_events() as events, self.assertRaises(ExamGateError):
            run_exam(cfg, [12])
        status = json.loads(
            (self.runs / make_run_id(12) / "status.json").read_text(encoding="utf-8")
        )
        self.assertEqual(status["stages"]["E1-ingest"]["state"], "failed")
        output = json.loads(
            (self.runs / make_run_id(12) / "E1-ingest" / "output.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertIn(
            "exam.question.chapter_unknown",
            {issue["rule"] for issue in output["gate"]["issues"]},
        )
        failed = [
            event for event in events if event["event"] == "factory.exam.run.failed"
        ]
        self.assertTrue(failed)
        self.assertEqual(failed[-1]["fields"]["failed_stage"], "E1-ingest")

    def test_a_structural_volume_block_does_not_crash_the_run(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            result = run_exam(cfg, [10])
        self.assertFalse(result["runs"][0]["publishable"])
        blocked = [event for event in events if event["event"] == "exam.series.blocked"]
        self.assertTrue(blocked)
        self.assertIn("volume", blocked[-1]["fields"]["reason_codes"])

    def test_no_compliance_block_event_when_only_volume_is_missing(self) -> None:
        cfg = self.cfg()
        with capture_events() as events:
            run_exam(cfg, [10])
        self.assertEqual(
            [event for event in events if event["event"] == "exam.publish.blocked"], []
        )


class CliTests(PipelineTestBase):
    def test_list_papers_writes_nothing(self) -> None:
        before = set(self.root.rglob("*"))
        code = main(["--list-papers", "--runs-dir", str(self.runs)])
        self.assertEqual(code, 0)
        after = set(self.root.rglob("*"))
        self.assertEqual(before, after)

    def test_the_default_run_exits_zero_even_when_blocked(self) -> None:
        code = main(
            [
                "--class",
                "10",
                "--runs-dir",
                str(self.runs),
                "--export-dir",
                str(self.exports),
            ]
        )
        self.assertEqual(code, 0)
        self.assertTrue(
            (
                self.runs / "exam-class-10" / "E4-publish" / "pack" / "manifest.json"
            ).is_file()
        )

    def test_require_publishable_exits_non_zero_when_blocked(self) -> None:
        code = main(
            [
                "--class",
                "10",
                "--runs-dir",
                str(self.runs),
                "--require-publishable",
            ]
        )
        self.assertEqual(code, 1)
        report = json.loads(
            (self.runs / "exam-class-10" / "run_report.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertFalse(
            report["ok"],
            "a run the operator gate rejected must not be recorded as ok",
        )


if __name__ == "__main__":
    unittest.main()
