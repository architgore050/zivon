"""Eval Card Runner and Golden Set Rotation Engine (`evals/runner.py`).

Implements:
- Deterministic-first funnel (`spec.md` §1.2 Rule 3): if any deterministic check on
  a card returns a fatal or major issue exceeding the card threshold, the LLM judge
  is skipped (`model_calls=0`, `judge_score=None`) and the card fails fast.
- Suite selection:
  - `smoke`: runs all deterministic checks across all cards with `"smoke"` in
    `card.suites` (`0` live model calls).
  - `calibrate`: runs Reviewer Calibration cards (`EV-REV-001`, `EV-REV-002`)
    including deterministic contract checks and seeded-defect calibration suites.
  - `full`: runs all 9 Eval Cards (`EV-CUR-001` through `EV-KID-001`), executing
    deterministic checks and LLM-as-judge / calibration suites.
- Golden rotation (`rotate_golden`): snapshots or updates a golden topic entry and
  recomputes its SHA-256 digest in `evals/goldens/manifest.json`.
"""

from __future__ import annotations

import hashlib
import json
import secrets
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .checkers import run_deterministic_check
from .config import EvalConfig
from .judges import JudgeClient, run_judge
from .models import (
    CardResult,
    DefectSampleResult,
    EvalCard,
    EvalRunReport,
    IssueRecord,
    load_all_cards,
)
from .report import write_run_artifacts
from .store import EvalStore, utc_now_iso
from .telemetry import emit_eval_event


def _detect_git_sha(repo_root: Path) -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except FileNotFoundError:
        pass
    return "unknown"


def _compute_prompt_bundle_sha256(repo_root: Path) -> str:
    h = hashlib.sha256()
    for rel in ("factory/agents.py", "factory/review.py", "factory/design.py"):
        p = repo_root / rel
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def compute_topic_sha256(topic_dir: Path) -> str:
    """Compute deterministic SHA-256 over `expected.json`, `source_pack_meta.json`, and `artifact_ref.json`."""
    h = hashlib.sha256()
    for fname in ("expected.json", "source_pack_meta.json", "artifact_ref.json"):
        f = topic_dir / fname
        if f.is_file():
            h.update(fname.encode("utf-8"))
            h.update(b"\0")
            h.update(f.read_bytes())
            h.update(b"\0")
    return h.hexdigest()


_SEVERITY_RANK = {"minor": 1, "major": 2, "fatal": 3, "unverified": 1}


def _apply_severity_floor(issues: list[IssueRecord], floor: str) -> None:
    """Raise each failing issue to the check's declared `severity_on_fail` floor.

    A checker that reports a `minor` result for a check the card declares `fatal`
    must still fail the card. Unverified hedges (`unverified:` way-out rule) are
    never escalated above minor.
    """
    floor_rank = _SEVERITY_RANK.get(floor, 1)
    for issue in issues:
        if issue.unverified or issue.message.startswith("unverified:"):
            continue
        if _SEVERITY_RANK.get(issue.severity, 1) < floor_rank:
            issue.severity = floor


def run_single_card(
    card: EvalCard,
    cfg: EvalConfig,
    judge_client: JudgeClient | None,
    *,
    execute_judge: bool = True,
    topic_filter: str | None = None,
    suite: str = "smoke",
) -> CardResult:
    """Execute one `EvalCard` following the deterministic-first funnel."""
    card_t0 = time.monotonic()
    det_issues: list[IssueRecord] = []
    det_metrics: dict[str, Any] = {}
    skipped_checks: dict[str, str] = {}
    checks_passed = 0
    checks_evaluated = 0

    context: dict[str, Any] = {
        "metrics": det_metrics,
        "skipped_checks": skipped_checks,
        "suite": suite,
    }
    if topic_filter:
        context["topic_filter"] = topic_filter

    for check_spec in card.deterministic_checks:
        issues = run_deterministic_check(check_spec.entrypoint, cfg, card, context)
        if check_spec.id in skipped_checks:
            # A checker with no data to grade must say so; it never silently
            # counts as a pass (that is how a broken pipeline reports 1.0).
            continue
        _apply_severity_floor(issues, check_spec.severity_on_fail)
        det_issues.extend(issues)
        checks_evaluated += 1
        has_blocking = any(i.severity in ("fatal", "major") for i in issues)
        if not has_blocking:
            checks_passed += 1

    if checks_evaluated:
        det_score = round(checks_passed / checks_evaluated, 4)
    else:
        det_score = 0.0

    fatal_count = sum(1 for i in det_issues if i.severity == "fatal")
    major_count = sum(1 for i in det_issues if i.severity == "major")
    minor_count = sum(1 for i in det_issues if i.severity == "minor")
    unverified_count = sum(
        1 for i in det_issues if i.unverified or i.message.startswith("unverified:")
    )

    fatal_max = int(card.thresholds.get("fatal_issues_max", 0))
    major_max = int(card.thresholds.get("major_issues_max", 0))
    det_min = float(card.thresholds.get("deterministic_pass_rate_min", 1.0))
    det_failed = (
        fatal_count > fatal_max or major_count > major_max or det_score < det_min
    )
    card_skipped = checks_evaluated == 0
    if skipped_checks:
        det_metrics["skipped_checks"] = dict(skipped_checks)

    judge_score: float | None = None
    model_calls = 0
    thinking_s = 0.0
    max_comp_tokens = 0
    length_cuts = 0
    defect_samples: list[DefectSampleResult] = []

    # Deterministic-first funnel (spec.md §1.2 Rule 3):
    # Only invoke LLM judge if all deterministic checks passed!
    if (
        not card_skipped
        and not det_failed
        and execute_judge
        and card.llm_judge is not None
        and judge_client is not None
    ):
        from .judges.base import JudgeCallStats

        judge_client.stats = JudgeCallStats()
        j_out = run_judge(card.llm_judge.entrypoint, cfg, card, judge_client, context)
        judge_score = round(j_out.score, 4)
        det_metrics.update(j_out.metrics)
        det_issues.extend(j_out.issues)
        defect_samples.extend(j_out.defect_samples)
        model_calls = j_out.stats.calls
        thinking_s = j_out.stats.thinking_s
        max_comp_tokens = j_out.stats.max_completion_tokens
        length_cuts = j_out.stats.length_cuts

        fatal_count = sum(1 for i in det_issues if i.severity == "fatal")
        major_count = sum(1 for i in det_issues if i.severity == "major")
        minor_count = sum(1 for i in det_issues if i.severity == "minor")
        unverified_count = sum(
            1 for i in det_issues if i.unverified or i.message.startswith("unverified:")
        )
        verdict = (
            "fail"
            if (
                j_out.verdict == "fail"
                or fatal_count > fatal_max
                or major_count > major_max
            )
            else "pass"
        )
    else:
        verdict = "skip" if card_skipped else ("fail" if det_failed else "pass")

    return CardResult(
        card_id=card.card_id,
        stage=card.stage,
        topic_slug=topic_filter,
        verdict=verdict,
        deterministic_score=det_score,
        judge_score=judge_score,
        fatal_count=fatal_count,
        major_count=major_count,
        minor_count=minor_count,
        unverified_count=unverified_count,
        model_calls=model_calls,
        thinking_s=thinking_s,
        max_completion_tokens=max_comp_tokens,
        length_cuts=length_cuts,
        duration_s=round(max(0.0, time.monotonic() - card_t0), 3),
        metrics=det_metrics,
        delta_vs_baseline={},
        issues=[i.to_dict() for i in det_issues],
        defect_samples=defect_samples,
        target_scope_label=card.title,
    )


def run_eval_suite(
    cfg: EvalConfig,
    *,
    suite: str = "smoke",
    card_id: str | None = None,
    topic_filter: str | None = None,
    out_dir: Path | None = None,
    judge_client: JudgeClient | None = None,
) -> EvalRunReport:
    """Run an evaluation suite (`smoke`, `full`, or `calibrate`)."""
    t0 = time.monotonic()
    started_at = utc_now_iso()
    all_cards = load_all_cards(cfg.cards_dir)

    if suite not in ("smoke", "full", "calibrate"):
        raise ValueError(f"Unsupported suite {suite!r}; expected smoke|full|calibrate")

    if card_id:
        if card_id not in all_cards:
            raise KeyError(f"Unknown EvalCard ID: {card_id!r}")
        selected_cards = [all_cards[card_id]]
    else:
        selected_cards = [c for c in all_cards.values() if suite in c.suites]

    ts_slug = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    git_sha = _detect_git_sha(cfg.repo_root)
    # Two runs can start inside the same wall-clock second (e.g. a smoke run
    # followed by a calibration run); add entropy so ledger keys never collide.
    eval_run_id = f"eval-{suite}-{ts_slug}-{git_sha[:7]}-{secrets.token_hex(3)}"

    if judge_client is None:
        judge_client = JudgeClient.mock(cfg) if cfg.mock_mode else JudgeClient(cfg)

    # In smoke suite without explicit --card, only deterministic checks run (0 model calls)
    execute_judge = (suite in ("full", "calibrate")) or (card_id is not None)

    emit_eval_event(
        "EVT-EVAL-RUN-STARTED",
        {
            "eval_run_id": eval_run_id,
            "suite": suite,
            "git_sha": git_sha,
            "cards_selected": [c.card_id for c in selected_cards],
            "mock_mode": cfg.mock_mode,
        },
        run_id=eval_run_id,
        fallback_dir=cfg.evals_runs_dir,
    )

    cards_out: list[CardResult] = []
    for card in selected_cards:
        res = run_single_card(
            card,
            cfg,
            judge_client,
            execute_judge=execute_judge,
            topic_filter=topic_filter,
            suite=suite,
        )
        cards_out.append(res)

    completed_at = utc_now_iso()
    duration_s = round(max(0.01, time.monotonic() - t0), 2)
    cards_passed = sum(1 for c in cards_out if c.verdict == "pass")
    cards_failed = sum(1 for c in cards_out if c.verdict == "fail")
    cards_skipped = sum(1 for c in cards_out if c.verdict == "skip")
    overall_pass = cards_failed == 0
    model_calls_total = sum(c.model_calls for c in cards_out)
    total_thinking_s = round(sum(c.thinking_s for c in cards_out), 2)

    def _measured_metric(card_id: str, key: str) -> float | None:
        card = next((c for c in cards_out if c.card_id == card_id), None)
        if card is None or card.verdict == "skip":
            return None
        value = card.metrics.get(key)
        return None if value is None else float(value)

    # null means "no measurement available" — never coerce to 0.0/1.0, which
    # would make an empty run look like a perfect run on the dashboard.
    human_edit_rate_rolling = _measured_metric("EV-E2E-001", "human_edit_rate_rolling")
    gate_b_comprehension_rate = _measured_metric("EV-KID-001", "gate_b_pass_rate")

    report = EvalRunReport(
        eval_run_id=eval_run_id,
        suite=suite,
        pipeline_version=1,
        factory_image_tag=cfg.factory_image_tag,
        git_sha=git_sha,
        prompt_bundle_sha256=_compute_prompt_bundle_sha256(cfg.repo_root),
        generator_model=cfg.generator_model,
        judge_model=cfg.judge_model,
        started_at=started_at,
        completed_at=completed_at,
        duration_s=duration_s,
        overall_pass=overall_pass,
        regression_detected=False,
        baseline_eval_run_id=None,
        summary={
            "cards_total": len(cards_out),
            "cards_passed": cards_passed,
            "cards_failed": cards_failed,
            "cards_skipped": cards_skipped,
            "model_calls_total": model_calls_total,
            "total_thinking_s": total_thinking_s,
            "human_edit_rate_rolling": human_edit_rate_rolling,
            "gate_b_comprehension_rate": gate_b_comprehension_rate,
        },
        cards=cards_out,
    )

    store = EvalStore(cfg)
    store.persist_run(report)
    target_out = out_dir or (cfg.evals_runs_dir / eval_run_id)
    write_run_artifacts(
        target_out,
        report,
        human_edits=store._read_jsonl(store.human_edits_ledger),
    )

    emit_eval_event(
        "EVT-EVAL-RUN-COMPLETED",
        {
            "eval_run_id": eval_run_id,
            "suite": suite,
            "overall_pass": overall_pass,
            "cards_total": len(cards_out),
            "cards_passed": cards_passed,
            "cards_failed": cards_failed,
            "model_calls_total": model_calls_total,
        },
        latency_ms=int(duration_s * 1000),
        run_id=eval_run_id,
        fallback_dir=cfg.evals_runs_dir,
    )
    return report


def rotate_golden(
    cfg: EvalConfig,
    *,
    topic_id: str,
    source_dir: Path | None = None,
    reason: str,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Update a golden topic's SHA-256 integrity digest in `evals/goldens/manifest.json`."""
    manifest_path = cfg.goldens_dir / "manifest.json"
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    topics = raw.get("golden_topics") or raw.get("topics") or []
    target_entry: dict[str, Any] | None = None
    for entry in topics:
        dir_rel = str(entry.get("directory") or "")
        dir_name = Path(dir_rel).name if dir_rel else ""
        if topic_id in (
            entry.get("golden_id"),
            entry.get("topic_id"),
            entry.get("slug"),
            entry.get("topic_slug"),
            dir_name,
            dir_rel,
        ):
            target_entry = entry
            break
    if target_entry is None:
        raise KeyError(f"Golden topic {topic_id!r} not found in {manifest_path}")

    dir_rel_entry = target_entry.get("directory")
    if dir_rel_entry:
        topic_dir = cfg.repo_root / dir_rel_entry
        slug = Path(dir_rel_entry).name
    else:
        slug = str(
            target_entry.get("slug") or target_entry.get("topic_slug") or topic_id
        )
        topic_dir = cfg.goldens_dir / "topics" / slug

    if source_dir is not None and not dry_run:
        for fname in ("expected.json", "source_pack_meta.json", "artifact_ref.json"):
            candidate = source_dir / fname
            if candidate.is_file():
                shutil.copyfile(candidate, topic_dir / fname)

    new_sha = compute_topic_sha256(topic_dir)
    old_sha = target_entry.get("sha256", "")
    if not dry_run:
        target_entry["sha256"] = new_sha
        # Persist the audit trail in the manifest (not only in stdout): a
        # golden rotation must be attributable months later.
        rotations = target_entry.setdefault("rotations", [])
        rotations.append(
            {
                "rotated_at": utc_now_iso(),
                "reason": reason,
                "old_sha256": old_sha,
                "new_sha256": new_sha,
                "source_dir": str(source_dir) if source_dir is not None else None,
                "tool": "python -m evals rotate-golden",
            }
        )
        manifest_path.write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return {
        "golden_id": target_entry.get("golden_id", slug),
        "topic": slug,
        "old_sha256": old_sha,
        "new_sha256": new_sha,
        "reason": reason,
        "dry_run": dry_run,
    }
