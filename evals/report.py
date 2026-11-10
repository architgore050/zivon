"""Report and Prometheus exposition formatters (`evals/report.py`).

Generates:
- `eval_report.json`: Schema-validated `EvalRunReport` JSON.
- `eval_summary.md`: Human-readable Markdown scorecard table + issues + diff alerts.
- `eval_metrics.prom`: Prometheus text exposition format via `format_prometheus_metrics`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import DiffReport, EvalRunReport
from .telemetry import format_prometheus_metrics


def render_markdown_report(run: EvalRunReport, diff: DiffReport | None = None) -> str:
    """Format an `EvalRunReport` (and optional `DiffReport`) as Markdown."""
    verdict_str = "PASS" if run.overall_pass else "FAIL"
    lines: list[str] = [
        f"# Zivon Eval Report — `{run.eval_run_id}`",
        "",
        f"- **Suite:** `{run.suite}`",
        f"- **Overall Verdict:** `{verdict_str}`",
        f"- **Git SHA:** `{run.git_sha}` (image `{run.factory_image_tag}`)",
        f"- **Models:** generator=`{run.generator_model}` | judge=`{run.judge_model}`",
        f"- **Window:** `{run.started_at}` -> `{run.completed_at}` (`{run.duration_s:.2f} s`)",
        "",
        "## Card Scorecard",
        "",
        "| Card ID | Stage | Verdict | Det. Score | Judge Score | Fatal | Major | Calls |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    for c in run.cards:
        j_score = f"{c.judge_score:.4f}" if c.judge_score is not None else "n/a"
        lines.append(
            f"| `{c.card_id}` | `{c.stage}` | **{c.verdict.upper()}** "
            f"| `{c.deterministic_score:.4f}` | `{j_score}` | `{c.fatal_count}` "
            f"| `{c.major_count}` | `{c.model_calls}` |"
        )

    all_issues = [(c.card_id, issue) for c in run.cards for issue in c.issues]
    if all_issues:
        lines.extend(
            [
                "",
                "## Findings & Issues",
                "",
                "| Card ID | Check / Judge | Severity | Block | Message |",
                "| --- | --- | --- | --- | --- |",
            ]
        )
        for cid, iss in all_issues:
            chk = iss.get("check_id") or "-"
            sev = iss.get("severity") or "-"
            blk = iss.get("block_id") or "-"
            msg = str(iss.get("message") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| `{cid}` | `{chk}` | `{sev}` | `{blk}` | {msg} |")

    if diff is not None:
        lines.extend(
            [
                "",
                f"## Regression Diff vs `{diff.baseline_eval_run_id}`",
                "",
                f"- **Regression Status:** `{'ALERT' if diff.regression_detected else 'CLEAN'}`",
                f"- **Exit Code:** `{diff.exit_code}`",
            ]
        )
        if diff.blocking_reasons:
            lines.append("")
            for reason in diff.blocking_reasons:
                lines.append(f"- **Blocking Alert:** {reason}")

    return "\n".join(lines) + "\n"


def render_prometheus_metrics(
    run: EvalRunReport, human_edits: list[dict[str, Any]] | None = None
) -> str:
    """Render Prometheus text exposition metrics for a completed eval run."""
    return format_prometheus_metrics(run.to_dict(), human_edits=human_edits)


def write_run_artifacts(
    out_dir: Path,
    run: EvalRunReport,
    diff: DiffReport | None = None,
    human_edits: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Write `eval_report.json`, `eval_summary.md`, and `eval_metrics.prom` to `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    report_dict = run.to_dict()

    json_path = out_dir / "eval_report.json"
    md_path = out_dir / "eval_summary.md"
    prom_path = out_dir / "eval_metrics.prom"

    json_path.write_text(
        json.dumps(report_dict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    md_path.write_text(render_markdown_report(run, diff), encoding="utf-8")
    prom_path.write_text(
        render_prometheus_metrics(run, human_edits=human_edits), encoding="utf-8"
    )
    if diff is not None:
        (out_dir / "eval_diff.json").write_text(
            json.dumps(diff.to_dict(), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "prometheus": str(prom_path),
    }
