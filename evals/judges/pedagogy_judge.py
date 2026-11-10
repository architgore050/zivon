"""Pedagogy & `03-check` Calibration Judge (`EV-SYN-001`, `EV-SYN-002`, `EV-REV-001`).

Reuses `factory.agents.run_check` verbatim (Single Rubric Source of Truth,
`card-template.md` Rule 1) to evaluate Synthesizer outputs and to calibrate the
`03-check` reviewer against the 8 seeded defect/clean samples (`SD-CHK-001..008`).
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest import mock

from factory import agents
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient

from ..config import EvalConfig
from ..models import DefectSampleResult, EvalCard, IssueRecord
from .base import JudgeClient, JudgeOutcome, verify_source_quote


def _make_run_env(
    cfg: EvalConfig, tmp: Path, class_level: int = 9
) -> tuple[Any, RunContext]:
    base = json.loads((cfg.repo_root / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    (tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
    env_patch = {
        "ZIVON_BASE_URL": cfg.judge_base_url or "http://127.0.0.1:8080/v1",
        "ZIVON_MODEL": cfg.judge_model
        if cfg.judge_model != "unconfigured"
        else "eval-judge",
    }
    with mock.patch.dict("os.environ", env_patch):
        fcfg = dataclasses.replace(
            load_config(tmp / "config.json"), root=cfg.repo_root
        ).with_class_level(class_level)
    return fcfg, RunContext(tmp / "runs", "eval-pedagogy")


def evaluate_synthesizer_coverage_and_pedagogy(
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any],
) -> JudgeOutcome:
    """Run `factory.agents.run_check` on golden Synthesizer outputs (`EV-SYN-001` & `EV-SYN-002`)."""
    sample_path = cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-007.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    inputs = sample["inputs"]
    pack = context.get("source_pack") or inputs["source_pack"]
    gt = context.get("ground_truth") or inputs["ground_truth"]
    lesson = context.get("lesson") or inputs["lesson"]
    blocks = context.get("blocks") or inputs["blocks"]

    with tempfile.TemporaryDirectory(prefix="zivon-judge-syn-") as td:
        fcfg, run_ctx = _make_run_env(
            cfg, Path(td), int(pack.get("chapter", {}).get("class", 9))
        )
        adapter = judge_client.as_factory_llm()
        report = agents.run_check(
            fcfg,
            run_ctx,
            cast(LLMClient, adapter),
            pack,
            gt,
            lesson,
            blocks,
        )

    issues = [
        IssueRecord(
            severity=i["severity"],
            block_id=i.get("block_id"),
            category=i.get("category", "content"),
            message=i["message"],
            unverified=i["message"].startswith("unverified:"),
        )
        for i in report.get("issues", [])
    ]
    fatals = sum(1 for i in issues if i.severity == "fatal")
    majors = sum(1 for i in issues if i.severity == "major")
    verdict = (
        "fail"
        if fatals > 0 or majors > card.thresholds.get("major_issues_max", 0)
        else "pass"
    )
    return JudgeOutcome(
        score=1.0 if verdict == "pass" else 0.0,
        verdict=verdict,
        issues=issues,
        # Honest aggregate counts. One 03-check call returns a mixed issue
        # list; it does not measure coverage, recomputation and
        # teach-before-test independently, so we do not publish three
        # dimension scores derived from the same sums.
        metrics={
            "fatal_issues": fatals,
            "major_issues": majors,
            "blocking_issues": fatals + majors,
            "metrics_source": "derived_from_run_check_issue_counts",
        },
        stats=judge_client.stats,
    )


def calibrate_03_check(
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any],
) -> JudgeOutcome:
    """`EV-REV-001`: Calibrate `03-check` (`factory.agents.run_check`) across all 8
    seeded-defect and clean-golden samples (`SD-CHK-001..008`).

    Computes:
    - `fatal_recall` (must be >= `thresholds.recall_fatal_min`, i.e., `1.00` on `SD-CHK-001, 002, 005`)
    - `blocking_recall` (`fatal` + `major` on `SD-CHK-001..005`, must be >= `0.80`)
    - `clean_specificity` (`1 - FPR` on `SD-CHK-006..008`, must be `1.00`)
    """
    sample_Results: list[DefectSampleResult] = []
    issues: list[IssueRecord] = []

    fatal_expected = 0
    fatal_caught = 0
    blocking_expected = 0
    blocking_caught = 0
    clean_total = 0
    clean_passed = 0

    for rel_path in card.golden_inputs.get("seeded_defects", []):
        spath = cfg.repo_root / rel_path
        sample = json.loads(spath.read_text(encoding="utf-8"))
        sid = sample["sample_id"]
        inp = sample["inputs"]
        exp = sample["expected"]

        with tempfile.TemporaryDirectory(prefix=f"zivon-cal-{sid}-") as td:
            cls_lv = int(inp["source_pack"].get("chapter", {}).get("class", 9))
            fcfg, run_ctx = _make_run_env(cfg, Path(td), cls_lv)
            adapter = judge_client.as_factory_llm()
            report = agents.run_check(
                fcfg,
                run_ctx,
                cast(LLMClient, adapter),
                inp["source_pack"],
                inp["ground_truth"],
                inp["lesson"],
                inp["blocks"],
                round_tag=sid.lower(),
            )
            call_meta = adapter.last_call_meta

        actual_verdict = report.get("verdict", "pass")
        rep_issues = report.get("issues", [])
        severity_rank = {"fatal": 3, "major": 2, "minor": 1}
        actual_sev: str | None = None
        for ri in rep_issues:
            s = ri.get("severity")
            if s in severity_rank and (
                actual_sev is None or severity_rank[s] > severity_rank[actual_sev]
            ):
                actual_sev = s

        want_block = exp.get("expected_block_id")
        if want_block is None:
            block_matched = True
        else:
            block_matched = any(
                ri.get("block_id") == want_block
                and ri.get("severity") in ("fatal", "major", "minor")
                for ri in rep_issues
            )

        corpus = inp["source_pack"].get("ncert_text", "")
        if exp.get("must_quote_source"):
            fatal_msgs = [
                ri.get("message", "")
                for ri in rep_issues
                if ri.get("severity") == "fatal"
            ]
            source_quoted = any(
                verify_source_quote(m, corpus, exp.get("expected_quote_substrings"))
                for m in fatal_msgs
            )
        else:
            source_quoted = True

        if exp["outcome_type"] == "positive_defect":
            blocking_expected += 1
            if exp["expected_severity"] == "fatal":
                fatal_expected += 1
                is_tp = (
                    actual_verdict == "fail"
                    and actual_sev == "fatal"
                    and block_matched
                    and source_quoted
                )
                if is_tp:
                    fatal_caught += 1
                    blocking_caught += 1
            else:
                is_tp = actual_sev in ("major", "fatal") and block_matched
                if is_tp:
                    blocking_caught += 1
            outcome_class = "TP" if is_tp else "FN"
            if not is_tp:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="EV-REV-001-CALIBRATION",
                        block_id=want_block,
                        category="content",
                        message=(
                            f"UNCAUGHT_SEEDED_DEFECT {sid} ({sample['defect_class']}): "
                            f"expected {exp['expected_severity']} on {want_block}, "
                            f"got verdict={actual_verdict}, severity={actual_sev}, "
                            f"block_matched={block_matched}, source_quoted={source_quoted}"
                        ),
                    )
                )
        else:
            clean_total += 1
            has_blocking = any(
                ri.get("severity") in ("fatal", "major") for ri in rep_issues
            )
            is_tn = actual_verdict == "pass" and not has_blocking
            if is_tn:
                clean_passed += 1
            outcome_class = "TN" if is_tn else "FP"
            if not is_tn:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="EV-REV-001-CALIBRATION",
                        category="content",
                        message=(
                            f"FALSE_POSITIVE_ON_CLEAN_GOLDEN {sid}: "
                            f"got verdict={actual_verdict}, severity={actual_sev}"
                        ),
                    )
                )

        sample_Results.append(
            DefectSampleResult(
                sample_id=sid,
                expected_verdict=exp["expected_verdict"],
                actual_verdict=actual_verdict,
                expected_severity=exp.get("expected_severity"),
                actual_severity=actual_sev,
                target_block_matched=block_matched,
                source_quoted=source_quoted,
                outcome_class=outcome_class,
                latency_s=float(call_meta.get("latency_s", 0.0)),
                thinking_s=float(call_meta.get("thinking_s", 0.0)),
                completion_tokens=int(call_meta.get("completion_tokens", 0)),
                finish_reason=call_meta.get("finish_reason", "stop"),
            )
        )

    fatal_recall = fatal_caught / fatal_expected if fatal_expected else 1.0
    blocking_recall = blocking_caught / blocking_expected if blocking_expected else 1.0
    clean_specificity = clean_passed / clean_total if clean_total else 1.0

    min_fatal = float(card.thresholds.get("recall_fatal_min", 1.0))
    min_blocking = float(card.thresholds.get("recall_blocking_min", 0.80))
    min_spec = float(card.thresholds.get("specificity_clean_min", 1.0))

    passed = (
        fatal_recall >= min_fatal
        and blocking_recall >= min_blocking
        and clean_specificity >= min_spec
    )
    score = round((fatal_recall + blocking_recall + clean_specificity) / 3.0, 4)
    return JudgeOutcome(
        score=1.0 if passed else score,
        verdict="pass" if passed else "fail",
        issues=issues,
        metrics={
            "fatal_recall": round(fatal_recall, 4),
            "blocking_recall": round(blocking_recall, 4),
            "clean_specificity": round(clean_specificity, 4),
            "samples_tested": len(sample_Results),
        },
        defect_samples=sample_Results,
        stats=judge_client.stats,
    )
