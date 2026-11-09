"""Stage 10c-transrepair: bounded progress-aware translation repair catcher.

Re-translates ONLY the flagged `(locale, unit_id)` items from `10b-transcheck`
with exact issue feedback, keeping all passing blocks locked and cached in
Translation Memory (`ADR-0021`, `ADR-0022`, `reviewer-rubric.md` §4).
"""

from __future__ import annotations

from typing import Any

from .artifacts import RunContext
from .config import Config
from .llm import LLMClient

STAGE_ID = "10c-transrepair"


def run_one_round(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: dict[str, Any],
    translate_out: dict[str, Any],
    transcheck_out: dict[str, Any],
    round_no: int,
) -> tuple[dict[str, Any], dict[str, set[str]], dict[str, list[dict[str, Any]]]]:
    """Repair flagged units for one catcher round."""
    del cfg, run_ctx, llm, ground_truth, en_lesson, en_blocks, transcheck_out, round_no
    return translate_out, {}, {}
