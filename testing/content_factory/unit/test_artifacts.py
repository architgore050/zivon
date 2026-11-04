"""Unit tests for RunContext artifact loading and the previous-run fallback.

Partial re-runs (--stages 03-check,06-render) must find upstream outputs in
the latest previous run, copy them in, and say so loudly. If nothing has
them, the failure must be a typed MissingArtifactError with instructions.

Resume support (graph v2): reopening a run dir must preserve status.json,
stage_ok() decides what may be skipped, the fingerprint guards against
mixing run shapes, and wipe_run() implements --fresh.
"""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.artifacts import RunContext, wipe_run
from factory.errors import MissingArtifactError


def seed_output(runs_dir: Path, run_id: str, stage_id: str, payload: dict) -> Path:
    ctx = RunContext(runs_dir, run_id)
    ctx.save_stage_output(stage_id, payload)
    path = ctx.stage_dir(stage_id) / "output.json"
    # make mtimes deterministic and clearly ordered
    stamp = payload.get("_stamp", 1000.0)
    os.utime(path, (stamp, stamp))
    return path


class TestLoadStageOutput(unittest.TestCase):
    def setUp(self):
        self.runs = Path(tempfile.mkdtemp()) / "runs"

    def test_own_run_output_wins(self):
        seed_output(self.runs, "old-run", "01-locate", {"marker": "old"})
        ctx = RunContext(self.runs, "cur")
        seed_output(self.runs, "cur", "01-locate", {"marker": "current"})
        out = ctx.load_stage_output("01-locate")
        self.assertEqual(out["marker"], "current")

    def test_falls_back_to_previous_run_and_copies(self):
        seed_output(self.runs, "old-run", "02-generate", {"marker": "old"})
        ctx = RunContext(self.runs, "cur")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = ctx.load_stage_output("02-generate")
        self.assertEqual(out["marker"], "old")
        printed = buf.getvalue()
        self.assertIn("old-run", printed)  # says where it came from
        # copied into the current run: the run is self-contained afterwards
        copied = ctx.stage_dir("02-generate") / "output.json"
        self.assertTrue(copied.exists())
        self.assertEqual(json.loads(copied.read_text())["marker"], "old")

    def test_latest_run_with_the_artifact_wins(self):
        seed_output(self.runs, "run-a", "02-generate", {"marker": "a", "_stamp": 100})
        seed_output(self.runs, "run-b", "01-locate", {"marker": "b-locate"})
        seed_output(self.runs, "run-b", "02-generate", {"marker": "b", "_stamp": 200})
        ctx = RunContext(self.runs, "cur")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = ctx.load_stage_output("02-generate")
        self.assertEqual(out["marker"], "b")  # newer mtime beats run-a
        self.assertIn("run-b", buf.getvalue())

    def test_missing_everywhere_is_typed_and_actionable(self):
        ctx = RunContext(self.runs, "cur")
        with self.assertRaises(MissingArtifactError) as ctx_err:
            ctx.load_stage_output("06-render")
        msg = str(ctx_err.exception)
        self.assertIn("06-render", msg)
        self.assertIn("--stages", msg)

    def test_missing_runs_dir_does_not_crash(self):
        ctx = RunContext(self.runs / "does-not-exist", "cur")
        with self.assertRaises(MissingArtifactError):
            ctx.load_stage_output("00-ingest")


class TestResumeSupport(unittest.TestCase):
    def setUp(self):
        self.runs = Path(tempfile.mkdtemp()) / "runs"

    def test_stage_ok_needs_both_status_and_output(self):
        ctx = RunContext(self.runs, "r1")
        self.assertFalse(ctx.status_exists())
        self.assertFalse(ctx.stage_ok("02-generate"))

        ctx.mark_stage("02-generate", "ok")  # status says ok, no artifact yet
        self.assertFalse(ctx.stage_ok("02-generate"))

        ctx.save_stage_output(
            "02-generate", {"ground_truth": {}, "lesson": {}, "blocks": {}}
        )
        self.assertTrue(ctx.stage_ok("02-generate"))

        # a FAILED stage is never resumable, even with an artifact on disk
        ctx.save_stage_output("03-check", {"verdict": "fail"})
        ctx.mark_stage("03-check", "failed")
        self.assertFalse(ctx.stage_ok("03-check"))

    def test_reopening_a_run_does_not_clobber_status(self):
        ctx = RunContext(self.runs, "r1")
        ctx.set_fingerprint("fp-123")
        ctx.save_stage_output("01-locate", {"chapter": {"title": "Motion"}})
        ctx.mark_stage("01-locate", "ok", detail="chapter=Motion")
        again = RunContext(self.runs, "r1")  # the resume path reopens the dir
        self.assertTrue(again.status_exists())
        self.assertEqual(again.get_fingerprint(), "fp-123")
        self.assertTrue(again.stage_ok("01-locate"))

    def test_fingerprint_roundtrip_and_absence(self):
        ctx = RunContext(self.runs, "r1")
        self.assertIsNone(ctx.get_fingerprint())  # old-shape run: no fingerprint
        ctx.set_fingerprint("fp-abc")
        self.assertEqual(RunContext(self.runs, "r1").get_fingerprint(), "fp-abc")

    def test_wipe_run_removes_dir_and_reports(self):
        ctx = RunContext(self.runs, "motion-c9")
        ctx.save_stage_output("02-generate", {"x": 1})
        self.assertTrue(wipe_run(self.runs, "motion-c9"))
        self.assertFalse((self.runs / "motion-c9").exists())
        self.assertFalse(wipe_run(self.runs, "never-ran"))  # idempotent


class TestStageTimingLogging(unittest.TestCase):
    """2026-11-04 observability: per-stage progress lines on stdout, measured
    per-stage wall-time in status.json, and stage_durations_s in run_report."""

    def setUp(self):
        self.runs = Path(tempfile.mkdtemp()) / "runs"

    def test_stage_transitions_print_and_measure(self):
        ctx = RunContext(self.runs, "r1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ctx.mark_stage("02-generate", "running")
            ctx.mark_stage("02-generate", "ok", detail="claims=9 blocks=12")
        printed = buf.getvalue()
        self.assertIn("[02-generate] starting", printed)
        self.assertIn("[02-generate] ok in", printed)
        self.assertIn("claims=9 blocks=12", printed)
        status = json.loads((self.runs / "r1" / "status.json").read_text())
        self.assertIsNotNone(status.get("started_at"))
        entry = status["stages"]["02-generate"]
        self.assertIn("elapsed_s", entry)

    def test_multi_round_stages_accumulate_across_rounds(self):
        ctx = RunContext(self.runs, "r1")
        buf = io.StringIO()
        with redirect_stdout(buf):
            ctx.mark_stage("03-check", "running")
            ctx.mark_stage("03-check", "failed", detail="blocking=2")
            ctx.mark_stage("03-check", "running")
            ctx.mark_stage("03-check", "ok", detail="blocking=0")
            ctx.finish(ok=True)
        report = json.loads((self.runs / "r1" / "run_report.json").read_text())
        self.assertIn("03-check", report["stage_durations_s"])
        self.assertIn("started_at", report)
        self.assertIn("completed_at", report)

    def test_started_at_survives_fingerprint_and_resume(self):
        ctx = RunContext(self.runs, "r1")
        ctx.set_fingerprint("fp-123")
        again = RunContext(self.runs, "r1")
        again.mark_stage("01-locate", "ok", detail="resumed from previous attempt")
        status = json.loads((self.runs / "r1" / "status.json").read_text())
        self.assertIsNotNone(status.get("started_at"))
        self.assertLess(abs(status["started_at"] - ctx._t0), 2.0)


if __name__ == "__main__":
    unittest.main()
