"""Errors for the exam/series pipeline.

Same three-way split as the assessment pipeline: a configuration error refuses
to start, a stage error means an artifact could not be produced, and a gate
error carries the deterministic report that blocked the stage (so the run
artifact explains the failure without the operator re-running anything).
"""

from __future__ import annotations

from typing import Any


class ExamError(RuntimeError):
    """Base class for every exam-pipeline failure."""


class ExamConfigError(ExamError):
    """A configuration value, mode flag or clearance reference the pipeline
    cannot run with. Raised before any stage starts (fail closed)."""


class ExamStageError(ExamError):
    """A stage could not produce its artifact."""


class ExamGateError(ExamStageError):
    """A deterministic gate refused the stage output.

    `report` is the gate report written next to the artifact; `output` is the
    artifact itself, so a failed stage stays inspectable.
    """

    def __init__(
        self,
        message: str,
        *,
        report: dict[str, Any] | None = None,
        output: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.report = report or {}
        self.output = output or {}


class ExamCopyError(ExamStageError):
    """A notice string is missing a placeholder, or a claim rule was violated."""


__all__ = [
    "ExamConfigError",
    "ExamCopyError",
    "ExamError",
    "ExamGateError",
    "ExamStageError",
]
