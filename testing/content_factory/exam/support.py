"""Shared fixtures for the exam/series test set.

Two helpers the tests and the eval checkers both need:

- `temp_exam_config()` builds an `ExamConfig` against the real repo data but
  with a temporary run/export directory, so no test writes under `runs/`;
- `write_synthetic_banks()` writes P2-shaped item banks for **every** chapter
  of a class. It exists to prove the volume gate passes when the volume is
  real - the shipped prototype has banks for three chapters, and faking that with
  a token sample would defeat the gate. The synthetic content is clearly
  labelled and lives only in a temp directory: it is never published and never
  committed as content.
"""

from __future__ import annotations

import dataclasses
import tempfile
from pathlib import Path
from typing import Any

from evals.checkers.exam_checks import (
    synthetic_bank,
    write_synthetic_banks,
)
from factory.exam.config import ExamConfig

REPO_ROOT = Path(__file__).resolve().parents[3]


def temp_exam_config(
    root: Path | None = None, **overrides: Any
) -> tuple[ExamConfig, tempfile.TemporaryDirectory[str]]:
    """A key-free config with temp run/export dirs; caller closes the handle."""
    handle = tempfile.TemporaryDirectory()
    base = Path(root or handle.name)
    cfg = ExamConfig.for_repo(
        REPO_ROOT,
        runs_dir=base / "runs",
        export_dir=base / "exports",
    )
    if overrides:
        cfg = dataclasses.replace(cfg, **overrides)
    return cfg, handle


__all__ = [
    "REPO_ROOT",
    "synthetic_bank",
    "temp_exam_config",
    "write_synthetic_banks",
]
