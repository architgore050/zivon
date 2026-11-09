"""LLM-as-judge graders and reviewer calibration runners (`evals/judges/`).

All model calls route exclusively through `llm_manager/` (`ADR-0028`). No module
in `evals/` imports `requests`, `httpx`, or `openai` directly.
"""

from __future__ import annotations

import importlib
from typing import Any

from ..config import EvalConfig
from ..models import EvalCard
from .base import JudgeClient, JudgeOutcome, verify_source_quote


def run_judge(
    entrypoint: str,
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any] | None = None,
) -> JudgeOutcome:
    """Resolve and invoke a `module.path:callable_name` judge entrypoint."""
    if ":" not in entrypoint:
        raise ValueError(f"invalid judge entrypoint {entrypoint!r}; expected 'module:func'")
    mod_name, func_name = entrypoint.split(":", 1)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, func_name, None)
    if fn is None or not callable(fn):
        raise ValueError(f"callable {func_name!r} not found in module {mod_name!r}")
    res = fn(cfg, card, judge_client, context or {})
    if not isinstance(res, JudgeOutcome):
        raise TypeError(f"judge {entrypoint} must return JudgeOutcome")
    return res


__all__ = [
    "JudgeClient",
    "JudgeOutcome",
    "run_judge",
    "verify_source_quote",
]
