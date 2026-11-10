"""Deterministic code-based checkers (`evals/checkers/`).

All checkers in this package execute with `0` model calls and run first in the
deterministic-first evaluation funnel (`skills/prompting-and-agent-design/SKILL.md`).
"""

from __future__ import annotations

import importlib
from typing import Any

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord


def run_deterministic_check(
    entrypoint: str,
    cfg: EvalConfig,
    card: EvalCard,
    context: dict[str, Any] | None = None,
) -> list[IssueRecord]:
    """Resolve and invoke a `module.path:callable_name` deterministic checker."""
    if ":" not in entrypoint:
        raise ValueError(
            f"invalid deterministic check entrypoint {entrypoint!r}; expected 'module:func'"
        )
    mod_name, func_name = entrypoint.split(":", 1)
    mod = importlib.import_module(mod_name)
    fn = getattr(mod, func_name, None)
    if fn is None or not callable(fn):
        raise ValueError(f"callable {func_name!r} not found in module {mod_name!r}")
    res = fn(cfg, card, context or {})
    if not isinstance(res, list):
        raise TypeError(f"checker {entrypoint} must return list[IssueRecord]")
    return res


__all__ = ["run_deterministic_check"]
