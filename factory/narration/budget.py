"""The A-15 narration build budget: a bounded one-time credit tranche.

backend-spec A-15 (adopted with C-051): narration pre-generation gets a
bounded ONE-TIME Gnani-credit tranche for factory TTS - proposed <= 1,500
credits total [ASSUMPTION], separate from the voice-agent daily tranche, and
the founder approves before the first live narration run. The guard's job:

- estimate every synthesis BEFORE it happens (chars x credits_per_char -
  Timbre bills characters, tags included),
- refuse-before-exceed: a call that would push the cumulative spend over the
  tranche is never made; the run narrates the deterministic prefix that fits
  and records the rest as budget-refused,
- persist the cumulative spend ACROSS runs (the tranche is one-time for the
  whole build, not per run) in runs/narration-budget.json, alongside a
  per-run usage roll-up for capacity-and-cost.md reconciliation,
- make resumption cheap: content-addressed assets mean a re-triggered run
  re-estimates ONLY the blocks it actually synthesizes.

Money state lives at runs/narration-budget.json (gitignored with runs/).
Factory runs are manual-only and never concurrent (the founder trigger
discipline), so a whole-file read-modify-write is safe; a torn/corrupt file
is rebuilt from zero rather than silently inflating the budget.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .env import STAGE_ID, NarrationEnv
from .errors import NarrationError

BUDGET_FILE = "narration-budget.json"
# Exact-fit is allowed: only a call that would go strictly over the tranche
# is refused. Epsilon absorbs float accumulation noise.
_EPSILON = 1e-9


def budget_path(runs_dir: Path) -> Path:
    return runs_dir / BUDGET_FILE


def load_state(runs_dir: Path, env: NarrationEnv) -> dict[str, Any]:
    """Read (or start) the cross-run budget ledger."""
    path = budget_path(runs_dir)
    if not path.exists():
        return {
            "tranche_credits": env.budget_credits,
            "total_credits_used": 0.0,
            "runs": [],
        }
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        # A torn write must never INFLATE the budget: rebuild from zero and
        # let the usage ledgers (per-run narration_usage.jsonl) reconstruct.
        return {
            "tranche_credits": env.budget_credits,
            "total_credits_used": 0.0,
            "runs": [],
        }
    if not isinstance(state, dict) or "total_credits_used" not in state:
        raise NarrationError(
            STAGE_ID,
            f"{path} is not a valid narration budget file - fix or delete it "
            "(a fresh file starts the tranche from zero; per-run usage "
            "ledgers under runs/<run_id>/ can reconstruct the spend)",
        )
    return state


def save_state(runs_dir: Path, state: dict[str, Any]) -> None:
    """Atomic write (tmp + replace) so a kill mid-write cannot tear the file."""
    path = budget_path(runs_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def estimate_credits(chars: int, env: NarrationEnv) -> float:
    """Billable estimate: Timbre bills characters (tags included), so the
    estimate uses the assembled spoken form's char count. [ASSUMPTION A-01:
    the per-character price is the capacity-model default until the founder
    reads the real prices off the Gnani dashboard.]"""
    return round(chars * env.credits_per_char, 4)


def would_exceed(state: dict[str, Any], credits: float) -> bool:
    """True only when this call would push the cumulative spend strictly
    over the tranche (exact fit is allowed)."""
    tranche = float(state.get("tranche_credits", 0.0))
    used = float(state.get("total_credits_used", 0.0))
    return used + credits > tranche + _EPSILON


def record_run_usage(
    state: dict[str, Any],
    run_id: str,
    *,
    mode: str,
    chars: int,
    credits: float,
    narrated: int,
    failed: int,
    refused: int,
) -> dict[str, Any]:
    """Fold one run's usage into the ledger and stamp it. Returns the updated
    state (caller persists)."""
    state["total_credits_used"] = round(
        float(state.get("total_credits_used", 0.0)) + credits, 4
    )
    state.setdefault("runs", []).append(
        {
            "run_id": run_id,
            "mode": mode,
            "chars": chars,
            "credits": round(credits, 4),
            "narrated": narrated,
            "failed": failed,
            "refused": refused,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    return state


def refusal_message(state: dict[str, Any], next_credits: float) -> str:
    """The operator-facing refusal: what happened, what it costs, and the
    founder-approved way forward (A-15)."""
    tranche = float(state.get("tranche_credits", 0.0))
    used = float(state.get("total_credits_used", 0.0))
    return (
        f"A-15 narration tranche exhausted: {used:.2f} of {tranche:.2f} "
        f"credits used, next block needs ~{next_credits:.2f} more. The guard "
        "refuses to exceed the tranche; the blocks already narrated this run "
        "are kept. Continue after founder approval: raise "
        "ZIVON_NARRATION_BUDGET_CREDITS (A-15 asks for founder approval "
        "before widening the tranche) and re-trigger the same chapter+class - "
        "completed blocks are skipped by content hash, so only the remainder "
        "is synthesized."
    )
