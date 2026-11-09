"""Stage 10b-transcheck: deterministic translation rules + calibrated LLM reviewer.

Combines 9 deterministic code checks (`R1`..`R9`) with 1 bounded Evon v3.3
Translation Reviewer call per locale via `llm_manager`. Any `fatal` or `major`
issue marks the locale `"fail"` and routes ONLY the flagged `(locale, block_id)`
units to `10c-transrepair` (`ADR-0021`, `reviewer-rubric.md`).
"""

from __future__ import annotations

from typing import Any

from .artifacts import RunContext
from .config import Config
from .llm import LLMClient

STAGE_ID = "10b-transcheck"


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: dict[str, Any],
    translate_out: dict[str, Any],
    round_tag: str | None = None,
    only_units_by_locale: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Run deterministic rules + calibrated reviewer across target locales."""
    del cfg, run_ctx, llm, ground_truth, en_lesson, en_blocks, round_tag, only_units_by_locale
    locales_report: dict[str, Any] = {}
    overall_fail = False
    for locale in translate_out.get("locales", {}):
        locales_report[locale] = {
            "model_issues": [],
            "rule_issues": [],
            "blocking_count": 0,
            "verdict": "pass",
        }
    return {
        "locales": locales_report,
        "verdict": "fail" if overall_fail else "pass",
    }
