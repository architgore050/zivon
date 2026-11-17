"""Assessment-pipeline errors.

Kept separate from `factory.errors` on purpose: the lesson factory's error
taxonomy describes stages 00-12, and an assessment failure must never be
reported as a lesson-pipeline failure. The CLI catches `AssessmentError` and
exits 1; a gate failure carries its report so the stage evidence is written
before the process stops.
"""

from __future__ import annotations

from typing import Any


class AssessmentError(Exception):
    """Base class for every assessment-pipeline failure."""


class AssessmentConfigError(AssessmentError):
    """The syllabus, chapter data or config cannot produce a valid pack."""


class AssessmentGateError(AssessmentError):
    """A deterministic gate found blocking issues.

    `output` is the stage's would-be output.json (including the full gate
    report); the orchestrator writes it before marking the stage failed, so
    the failure is inspectable after the process exits.
    """

    def __init__(self, message: str, *, report: dict[str, Any], output: Any):
        super().__init__(message)
        self.report = report
        self.output = output


class AssessmentStageError(AssessmentError):
    """A stage could not complete (missing input, unusable generator, ...)."""
