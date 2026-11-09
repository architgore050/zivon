"""Tests for the 12-narration stage: graph placement + disabled no-op.

The full mock-mode narration build (assets + availability flags + resume +
budget) is covered in test_narration_build.py once the synthesis modules are
wired; this module pins the wiring contract: the stage exists in STAGE_ORDER,
is a valid --stages target, and is a clean no-op unless explicitly enabled.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from factory.config import Config
from factory.stages import STAGE_ORDER

from .narration_env import install_narration_env, release_narration_env


class TestNarrationWiring(unittest.TestCase):
    def test_stage_is_last_after_the_review_gates(self):
        # Placement contract (C-051 + GAP-015): narration runs AFTER the
        # content/perf/code review gates and after publish-link, so credits
        # are only ever spent on a page that passed every gate.
        self.assertEqual(STAGE_ORDER[-1], "12-narration")
        self.assertLess(
            STAGE_ORDER.index("10-reviewfix"), STAGE_ORDER.index("12-narration")
        )
        self.assertLess(STAGE_ORDER.index("11-link"), STAGE_ORDER.index("12-narration"))


class TestNarrationDisabledNoOp(unittest.TestCase):
    def setUp(self):
        self.saved_env = install_narration_env(enabled=False)
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-narr-test-"))
        self.runs_dir = self.tmp / "runs"
        self.runs_dir.mkdir()
        self.run_ctx = _FakeRunContext(self.runs_dir, "run-narr-disabled")

    def tearDown(self):
        release_narration_env(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_disabled_stage_returns_without_touching_anything(self):
        from factory.narration import run as run_narration

        cfg = _minimal_cfg(self.tmp)
        out = run_narration(cfg, self.run_ctx)
        self.assertFalse(out["enabled"])
        self.assertEqual(out["stage"], "12-narration")
        # A disabled stage must not create audio dirs or manifests.
        self.assertFalse((self.tmp / "frontend" / "audio").exists())

    def test_disabled_stage_does_not_raise_when_timbre_absent(self):
        # The no-Timbre default environment (every CI run, every cluster Job
        # without the narration env) must stay a clean skip, never an error.
        from factory.narration import run as run_narration

        out = run_narration(_minimal_cfg(self.tmp), self.run_ctx)
        self.assertFalse(out["enabled"])


class _FakeRunContext:
    """Minimal RunContext stand-in: the disabled stage writes nothing."""

    def __init__(self, runs_dir: Path, run_id: str):
        self.runs_dir = runs_dir
        self.run_id = run_id
        self.dir = runs_dir / run_id
        self.dir.mkdir(parents=True, exist_ok=True)

    def stage_dir(self, stage_id: str) -> Path:
        d = self.dir / stage_id
        d.mkdir(parents=True, exist_ok=True)
        return d


def _minimal_cfg(root: Path) -> Config:
    return Config(
        data={
            "learner": {"language": "en"},
            "retrieval": {},
            "limits": {},
            "paths": {
                "frontend": str(root / "frontend"),
                "runs": str(root / "runs"),
            },
            "perf": {},
            "repair": {},
            "stage_overrides": {},
        },
        server={},
        root=root,
    )
