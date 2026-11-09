"""Code & Design Judge and `09-review` Calibration (`EV-VIS-001`, `EV-REV-002`).

Reuses `factory.review.run` verbatim (`_FACTS_TASK` and `_DESIGN_TASK`,
`card-template.md` Rule 1) to evaluate rendered visual pages and to calibrate the
two-call `09-review` gate against `SD-REV-001..006`.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any, cast
from unittest import mock

from factory import review
from factory.artifacts import RunContext
from factory.config import load_config
from factory.llm import LLMClient

from ..config import EvalConfig
from ..models import DefectSampleResult, EvalCard, IssueRecord
from .base import JudgeClient, JudgeOutcome


def _make_review_env(cfg: EvalConfig, tmp: Path) -> tuple[Any, RunContext]:
    base = json.loads((cfg.repo_root / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    (tmp / "config.json").write_text(json.dumps(base), encoding="utf-8")
    env_patch = {
        "ZIVON_BASE_URL": cfg.judge_base_url or "http://127.0.0.1:8080/v1",
        "ZIVON_MODEL": cfg.judge_model if cfg.judge_model != "unconfigured" else "eval-judge",
    }
    with mock.patch.dict("os.environ", env_patch):
        fcfg = dataclasses.replace(
            load_config(tmp / "config.json"), root=cfg.repo_root
        ).with_class_level(11)
    return fcfg, RunContext(tmp / "runs", "eval-review")


def _stage_files(tmp_topic: Path, files: dict[str, Any]) -> dict[str, Any]:
    tmp_topic.mkdir(parents=True, exist_ok=True)
    for name in ("index.html", "page.js", "page.css"):
        if name in files:
            (tmp_topic / name).write_text(str(files[name]), encoding="utf-8")
    manifest = files.get("manifest.json") or {
        "course_id": "class-11-physics",
        "class": 11,
        "topic_slug": "motion-in-a-straight-line",
        "title": "Motion in a Straight Line",
        "chapter": {"title": "MOTION IN A STRAIGHT LINE", "pages": [1, 14]},
        "sources": [{"id": "ncert-physics-11-part1", "title": "Physics Part I"}],
    }
    (tmp_topic / "manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    return {
        "topic_dir": str(tmp_topic),
        "site_dir": str(tmp_topic.parent),
        "manifest": manifest,
    }


def evaluate_visual_and_code(
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any],
) -> JudgeOutcome:
    """Run `factory.review.run` (`09-review-facts` + `09-review-design`) on golden
    rendered topic files (`EV-VIS-001`).
    """
    clean_sample_path = cfg.goldens_dir / "defects" / "09-review" / "SD-REV-006.json"
    sample = json.loads(clean_sample_path.read_text(encoding="utf-8"))
    inp = sample["inputs"]

    with tempfile.TemporaryDirectory(prefix="zivon-judge-vis-") as td:
        tmp = Path(td)
        fcfg, run_ctx = _make_review_env(cfg, tmp)
        render_out = _stage_files(tmp / "topic", inp["files"])
        adapter = judge_client.as_factory_llm()
        report = review.run(
            fcfg,
            run_ctx,
            cast(LLMClient, adapter),
            inp["blocks"],
            render_out,
            inp["ground_truth"],
        )

    issues = [
        IssueRecord(
            severity=i["severity"],
            block_id=i.get("block_id"),
            category=i.get("category", "other"),
            message=i["message"],
            unverified=i["message"].startswith("unverified:"),
        )
        for i in report.get("issues", [])
    ]
    fatals = sum(1 for i in issues if i.severity == "fatal")
    majors = sum(1 for i in issues if i.severity == "major")
    max_majors = int(card.thresholds.get("major_issues_max", 1))
    verdict = "fail" if fatals > 0 or majors > max_majors else "pass"
    return JudgeOutcome(
        score=1.0 if verdict == "pass" else 0.0,
        verdict=verdict,
        issues=issues,
        metrics={
            "fatal_issues": fatals,
            "major_issues": majors,
        },
        stats=judge_client.stats,
    )


def calibrate_09_review(
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any],
) -> JudgeOutcome:
    """`EV-REV-002` Part B: Calibrate `09-review` (`09-review-facts` + `09-review-design`)
    across `SD-REV-001..006` (`12` model calls total: `2` per sample).

    Verifies:
    - `fatal_recall == 1.00` (`3/3` on `SD-REV-001..003`)
    - `blocking_recall == 1.00` (`5/5` on `SD-REV-001..005`, matching expected `category`)
    - `clean_specificity == 1.00` (`SD-REV-006` returns `verdict == 'pass'`, `0` fatals)
    - Thinking-loop guard: `max_completion_tokens <= 35000` and `length_cuts == 0`
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
        if "SD-REV-" not in rel_path:
            continue
        spath = cfg.repo_root / rel_path
        sample = json.loads(spath.read_text(encoding="utf-8"))
        sid = sample["sample_id"]
        inp = sample["inputs"]
        exp = sample["expected"]

        with tempfile.TemporaryDirectory(prefix=f"zivon-cal-{sid}-") as td:
            tmp = Path(td)
            fcfg, run_ctx = _make_review_env(cfg, tmp)
            render_out = _stage_files(tmp / "topic", inp["files"])
            adapter = judge_client.as_factory_llm()
            report = review.run(
                fcfg,
                run_ctx,
                cast(LLMClient, adapter),
                inp["blocks"],
                render_out,
                inp["ground_truth"],
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
        want_cat = exp.get("expected_category")
        if want_block is None:
            block_matched = True
        else:
            block_matched = any(
                ri.get("block_id") == want_block
                and (want_cat is None or ri.get("category") == want_cat)
                for ri in rep_issues
            )

        if exp["outcome_type"] == "positive_defect":
            blocking_expected += 1
            if exp["expected_severity"] == "fatal":
                fatal_expected += 1
                is_tp = (
                    actual_verdict == "fail"
                    and actual_sev == "fatal"
                    and block_matched
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
                        check_id="EV-REV-002-CALIBRATION",
                        block_id=want_block,
                        category=want_cat or "other",
                        message=(
                            f"UNCAUGHT_SEEDED_DEFECT {sid} ({sample['defect_class']}): "
                            f"expected {exp['expected_severity']}/{want_cat} on {want_block}, "
                            f"got verdict={actual_verdict}, severity={actual_sev}, block_matched={block_matched}"
                        ),
                    )
                )
        else:
            clean_total += 1
            has_fatal = any(ri.get("severity") == "fatal" for ri in rep_issues)
            is_tn = actual_verdict == "pass" and not has_fatal
            if is_tn:
                clean_passed += 1
            outcome_class = "TN" if is_tn else "FP"
            if not is_tn:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="EV-REV-002-CALIBRATION",
                        category="other",
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
                source_quoted=True,
                outcome_class=outcome_class,
                latency_s=float(call_meta.get("latency_s", 0.0)),
                thinking_s=float(call_meta.get("thinking_s", 0.0)),
                completion_tokens=int(call_meta.get("completion_tokens", 0)),
                finish_reason=call_meta.get("finish_reason", "stop"),
            )
        )

    # Check thinking-loop guard (spec.md §2.2 EV-REV-002)
    max_tokens_budget = int(
        card.cost_budget.get("max_completion_tokens_per_call", 35000)
    )
    if judge_client.stats.max_completion_tokens > max_tokens_budget:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="EV-REV-002-THINKING-GUARD",
                category="other",
                message=(
                    f"max_completion_tokens={judge_client.stats.max_completion_tokens} "
                    f"exceeded budget {max_tokens_budget}"
                ),
            )
        )
    if judge_client.stats.length_cuts > 0:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="EV-REV-002-THINKING-GUARD",
                category="other",
                message=f"length_cuts={judge_client.stats.length_cuts} > 0",
            )
        )

    fatal_recall = fatal_caught / fatal_expected if fatal_expected else 1.0
    blocking_recall = blocking_caught / blocking_expected if blocking_expected else 1.0
    clean_specificity = clean_passed / clean_total if clean_total else 1.0

    min_fatal = float(card.thresholds.get("recall_fatal_min", 1.0))
    min_blocking = float(card.thresholds.get("recall_blocking_min", 1.0))
    min_spec = float(card.thresholds.get("specificity_clean_min", 1.0))

    passed = (
        fatal_recall >= min_fatal
        and blocking_recall >= min_blocking
        and clean_specificity >= min_spec
        and not issues
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
            "max_completion_tokens": judge_client.stats.max_completion_tokens,
            "length_cuts": judge_client.stats.length_cuts,
        },
        defect_samples=sample_Results,
        stats=judge_client.stats,
    )
