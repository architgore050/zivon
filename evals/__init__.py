"""Zivon Content Factory Evaluation Framework (`evals/`).

First-class evaluation package separated from deterministic software unit tests
in `testing/`. Implements stage & end-to-end eval cards (`EV-CUR-001` through
`EV-KID-001`), property-based golden topic validation, seeded-defect reviewer
calibration (`03-check` and `09-review`), run-to-run regression diffing,
human-edit-rate tracking, and Gate B kid-comprehension session logging.
"""

from __future__ import annotations

from .config import EvalConfig, EvalConfigError
from .models import (
    DIFF_REPORT_SCHEMA,
    EVAL_CARD_SCHEMA,
    EVAL_REPORT_SCHEMA,
    GOLDEN_EXPECTED_SCHEMA,
    HUMAN_EDIT_SCHEMA,
    KID_SESSION_SCHEMA,
    SEEDED_DEFECT_SCHEMA,
    CardDiff,
    CardResult,
    DefectSampleResult,
    DeterministicCheckSpec,
    DiffReport,
    EvalCard,
    EvalRunReport,
    HumanEditRecord,
    IssueRecord,
    JudgeSpec,
    KidSessionRecord,
    load_all_cards,
    load_card,
    validate_schema,
)

__version__ = "0.1.0"

__all__ = [
    "DIFF_REPORT_SCHEMA",
    "EVAL_CARD_SCHEMA",
    "EVAL_REPORT_SCHEMA",
    "GOLDEN_EXPECTED_SCHEMA",
    "HUMAN_EDIT_SCHEMA",
    "KID_SESSION_SCHEMA",
    "SEEDED_DEFECT_SCHEMA",
    "CardDiff",
    "CardResult",
    "DefectSampleResult",
    "DeterministicCheckSpec",
    "DiffReport",
    "EvalCard",
    "EvalConfig",
    "EvalConfigError",
    "EvalRunReport",
    "HumanEditRecord",
    "IssueRecord",
    "JudgeSpec",
    "KidSessionRecord",
    "__version__",
    "load_all_cards",
    "load_card",
    "validate_schema",
]
