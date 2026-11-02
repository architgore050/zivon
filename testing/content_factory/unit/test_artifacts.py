"""Unit tests for RunContext artifact loading and the previous-run fallback.

Partial re-runs (--stages 05-check,07-render) must find upstream outputs in
the latest previous run, copy them in, and say so loudly. If nothing has
them, the failure must be a typed MissingArtifactError with instructions.
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

from factory.artifacts import RunContext
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
        seed_output(self.runs, "old-run", "02-synth", {"marker": "old"})
        ctx = RunContext(self.runs, "cur")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = ctx.load_stage_output("02-synth")
        self.assertEqual(out["marker"], "old")
        printed = buf.getvalue()
        self.assertIn("old-run", printed)  # says where it came from
        # copied into the current run: the run is self-contained afterwards
        copied = ctx.stage_dir("02-synth") / "output.json"
        self.assertTrue(copied.exists())
        self.assertEqual(json.loads(copied.read_text())["marker"], "old")

    def test_latest_run_with_the_artifact_wins(self):
        seed_output(self.runs, "run-a", "02-synth", {"marker": "a", "_stamp": 100})
        seed_output(self.runs, "run-b", "01-locate", {"marker": "b-locate"})
        seed_output(self.runs, "run-b", "02-synth", {"marker": "b", "_stamp": 200})
        ctx = RunContext(self.runs, "cur")
        buf = io.StringIO()
        with redirect_stdout(buf):
            out = ctx.load_stage_output("02-synth")
        self.assertEqual(out["marker"], "b")  # newer mtime beats run-a
        self.assertIn("run-b", buf.getvalue())

    def test_missing_everywhere_is_typed_and_actionable(self):
        ctx = RunContext(self.runs, "cur")
        with self.assertRaises(MissingArtifactError) as ctx_err:
            ctx.load_stage_output("07-render")
        msg = str(ctx_err.exception)
        self.assertIn("07-render", msg)
        self.assertIn("--stages", msg)

    def test_missing_runs_dir_does_not_crash(self):
        ctx = RunContext(self.runs / "does-not-exist", "cur")
        with self.assertRaises(MissingArtifactError):
            ctx.load_stage_output("00-ingest")


if __name__ == "__main__":
    unittest.main()
