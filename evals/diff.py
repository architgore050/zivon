"""Run-to-run regression diff engine (`evals/diff.py`).

Implements `docs/specs/evals/spec.md` §4.2 ("Regression Alert Rules"):
- Any card verdict flipping from `pass` -> `fail` triggers a blocking regression.
- Any `fatal_recall` drop `> 0.0` triggers a blocking regression.
- Any `blocking_recall` drop `> 0.05` triggers a blocking regression.
- Any `EV-PERF-001` `p95_frame_ms` increase `> 15%` or `long_tasks` increase `> 0`
  triggers a blocking regression.
- Any `human_edit_rate_rolling` increase `> 0.05` triggers a blocking regression.
- Evaluates card-defined `regression_drop_tolerance` thresholds.
- Produces a schema-validated `DiffReport` (`exit_code = 2` when `regression_detected`).
"""

from __future__ import annotations

from pathlib import Path

from .models import CardDiff, CardResult, DiffReport, EvalCard, EvalRunReport
from .telemetry import ErrorClass, Severity, emit_eval_event


def _numeric_metrics(card: CardResult) -> dict[str, float]:
    out: dict[str, float] = {
        "deterministic_score": float(card.deterministic_score),
    }
    if card.judge_score is not None:
        out["judge_score"] = float(card.judge_score)
    for k, v in card.metrics.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            out[k] = float(v)
    return out


def compute_run_diff(
    prev_run: EvalRunReport,
    curr_run: EvalRunReport,
    cards_by_id: dict[str, EvalCard] | None = None,
    *,
    fallback_dir: Path | None = None,
) -> DiffReport:
    """Compare `prev_run` and `curr_run` and return a schema-validated `DiffReport`."""
    prev_map: dict[str, CardResult] = {c.card_id: c for c in prev_run.cards}
    blocking_reasons: list[str] = []
    card_diffs: list[CardDiff] = []

    for curr_card in curr_run.cards:
        cid = curr_card.card_id
        prev_card = prev_map.get(cid)
        reasons: list[str] = []
        deltas: dict[str, float] = {}
        det_delta = 0.0
        judge_delta: float | None = None

        if prev_card is not None:
            det_delta = round(
                curr_card.deterministic_score - prev_card.deterministic_score, 4
            )
            if curr_card.judge_score is not None and prev_card.judge_score is not None:
                judge_delta = round(curr_card.judge_score - prev_card.judge_score, 4)

            if prev_card.verdict == "pass" and curr_card.verdict == "fail":
                reasons.append(f"{cid}: verdict flipped from pass to fail")

            prev_num = _numeric_metrics(prev_card)
            curr_num = _numeric_metrics(curr_card)
            for m_key, curr_val in curr_num.items():
                if m_key in prev_num:
                    deltas[m_key] = round(curr_val - prev_num[m_key], 6)

            if "fatal_recall" in prev_num and "fatal_recall" in curr_num:
                drop = prev_num["fatal_recall"] - curr_num["fatal_recall"]
                if drop > 0.0:
                    reasons.append(
                        f"{cid}: fatal_recall dropped by {drop:.4f} "
                        f"({prev_num['fatal_recall']:.4f} -> {curr_num['fatal_recall']:.4f})"
                    )

            if "blocking_recall" in prev_num and "blocking_recall" in curr_num:
                drop = prev_num["blocking_recall"] - curr_num["blocking_recall"]
                if drop > 0.05:
                    reasons.append(
                        f"{cid}: blocking_recall dropped by {drop:.4f} > 0.05 "
                        f"({prev_num['blocking_recall']:.4f} -> {curr_num['blocking_recall']:.4f})"
                    )

            if cid == "EV-PERF-001":
                for p_key in list(curr_num.keys()):
                    if "frame" in p_key and p_key in prev_num and prev_num[p_key] > 0:
                        pct_rise = (curr_num[p_key] - prev_num[p_key]) / prev_num[p_key]
                        if pct_rise > 0.15:
                            reasons.append(
                                f"{cid}: {p_key} increased by {pct_rise * 100:.1f}% > 15%"
                            )
                    if (
                        "long_tasks" in p_key
                        and p_key in prev_num
                        and curr_num[p_key] > prev_num[p_key]
                    ):
                        reasons.append(
                            f"{cid}: {p_key} increased from {prev_num[p_key]} to {curr_num[p_key]}"
                        )

            card_spec = (cards_by_id or {}).get(cid)
            tol = (
                float(card_spec.thresholds.get("regression_drop_tolerance", 0.02))
                if card_spec
                else 0.02
            )
            if det_delta < -tol:
                reasons.append(
                    f"{cid}: deterministic_score dropped by {abs(det_delta):.4f} > tolerance {tol:.4f}"
                )
            if judge_delta is not None and judge_delta < -tol:
                reasons.append(
                    f"{cid}: judge_score dropped by {abs(judge_delta):.4f} > tolerance {tol:.4f}"
                )

        regressed = len(reasons) > 0
        blocking_reasons.extend(reasons)
        card_diffs.append(
            CardDiff(
                card_id=cid,
                topic_slug=curr_card.topic_slug,
                baseline_verdict=prev_card.verdict if prev_card else None,
                current_verdict=curr_card.verdict,
                deterministic_delta=det_delta,
                judge_delta=judge_delta,
                metric_deltas=deltas,
                regressed=regressed,
                reasons=reasons,
            )
        )

    prev_edit = float(prev_run.summary.get("human_edit_rate_rolling", 0.0))
    curr_edit = float(curr_run.summary.get("human_edit_rate_rolling", 0.0))
    edit_delta = round(curr_edit - prev_edit, 4)
    if edit_delta > 0.05:
        blocking_reasons.append(
            f"human_edit_rate_rolling increased by {edit_delta:.4f} > 0.05 "
            f"({prev_edit:.4f} -> {curr_edit:.4f})"
        )

    prev_calls = float(prev_run.summary.get("model_calls_total", 0))
    curr_calls = float(curr_run.summary.get("model_calls_total", 0))
    prev_think = float(prev_run.summary.get("total_thinking_s", 0.0))
    curr_think = float(curr_run.summary.get("total_thinking_s", 0.0))

    regression_detected = len(blocking_reasons) > 0
    if regression_detected:
        emit_eval_event(
            "EVT-EVAL-REGRESSION-ALERT",
            {
                "eval_run_id": curr_run.eval_run_id,
                "baseline_eval_run_id": prev_run.eval_run_id,
                "blocking_reasons": blocking_reasons,
            },
            severity=Severity.ERROR,
            error_class=ErrorClass.gate_fail,
            run_id=curr_run.eval_run_id,
            fallback_dir=fallback_dir,
        )

    return DiffReport(
        eval_run_id=curr_run.eval_run_id,
        baseline_eval_run_id=prev_run.eval_run_id,
        pipeline_version=curr_run.pipeline_version,
        regression_detected=regression_detected,
        exit_code=2 if regression_detected else 0,
        blocking_reasons=blocking_reasons,
        card_diffs=card_diffs,
        cost_delta={
            "model_calls_delta": round(curr_calls - prev_calls, 2),
            "thinking_s_delta": round(curr_think - prev_think, 2),
        },
        human_edit_rate_delta=edit_delta,
    )
