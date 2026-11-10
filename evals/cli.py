"""Command-line interface for the Zivon Evals Framework (`python -m evals`).

Subcommands (`docs/specs/evals/spec.md` §4.1):
- `run`: Run a suite (`smoke|full|calibrate`) or a single `--card`.
- `calibrate`: Run reviewer calibration suites (`03-check|09-review|all`).
- `diff`: Compare two runs (`--prev`, `--curr` or `--baseline`, `--current`); exits `2` on regression alert.
- `record-edit`: Record human intervention diff (`EV-E2E-001`).
- `record-kid-test`: Record anonymised kid comprehension session (`EV-KID-001`, DPDP check).
- `report`: Render Markdown, JSON, or Prometheus report for a run.
- `rotate-golden`: Snapshot/update a golden topic hash in `evals/goldens/manifest.json`.
- `backfill-db`: Replay JSONL ledgers into `ZIVON_DB_URL` idempotently (`ADR-0027`).
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .config import EvalConfig
from .diff import compute_run_diff
from .models import load_all_cards
from .report import (
    render_markdown_report,
    render_prometheus_metrics,
    write_run_artifacts,
)
from .runner import rotate_golden, run_eval_suite
from .store import EvalStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m evals",
        description="Zivon Content Factory Evals & Reviewer Calibration CLI",
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # 1. run
    p_run = sub.add_parser("run", help="Run an eval suite or single card")
    p_run.add_argument(
        "--suite",
        choices=("smoke", "full", "calibrate"),
        default="smoke",
        help="Suite to run (default: smoke)",
    )
    p_run.add_argument(
        "--card", default=None, help="Run a single EvalCard ID (e.g. EV-SYN-001)"
    )
    p_run.add_argument(
        "--topic", default=None, help="Filter to a single golden topic ID/slug"
    )
    p_run.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic calibrated fake judge (zero network calls)",
    )
    p_run.add_argument(
        "--out", default=None, help="Output directory for report artifacts"
    )

    # 2. calibrate
    p_cal = sub.add_parser(
        "calibrate", help="Run seeded-defect calibration against 03-check / 09-review"
    )
    p_cal.add_argument(
        "--stage",
        choices=("03-check", "09-review", "all"),
        default="all",
        help="Reviewer stage to calibrate",
    )
    p_cal.add_argument(
        "--mock",
        action="store_true",
        help="Use deterministic calibrated fake judge (zero network calls)",
    )
    p_cal.add_argument(
        "--out", default=None, help="Output directory for calibration artifacts"
    )

    # 3. diff
    p_diff = sub.add_parser(
        "diff",
        help="Compute regression diff between two runs (exits 2 on regression)",
    )
    p_diff.add_argument(
        "--prev",
        "--baseline",
        dest="prev",
        required=True,
        help="Baseline run ID or path",
    )
    p_diff.add_argument(
        "--curr", "--current", dest="curr", required=True, help="Current run ID or path"
    )
    p_diff.add_argument(
        "--out", default=None, help="Optional file path to write JSON diff"
    )

    # 4. record-edit
    p_edit = sub.add_parser(
        "record-edit", help="Record human intervention diff for EV-E2E-001"
    )
    p_edit.add_argument("--course", required=True, help="Course ID/slug")
    p_edit.add_argument("--topic", required=True, help="Topic slug")
    p_edit.add_argument(
        "--class-level", type=int, default=9, help="Class level (6..12)"
    )
    p_edit.add_argument(
        "--baseline-dir", required=True, help="Directory with raw pipeline output"
    )
    p_edit.add_argument(
        "--published-dir", required=True, help="Directory with human-published output"
    )
    p_edit.add_argument("--baseline-sha", default="0" * 40)
    p_edit.add_argument("--published-sha", default="0" * 40)
    p_edit.add_argument("--notes", default="")

    # 5. record-kid-test
    p_kid = sub.add_parser(
        "record-kid-test",
        help="Record anonymised kid comprehension session for EV-KID-001 (DPDP-validated)",
    )
    p_kid.add_argument(
        "--input",
        required=True,
        help="Path to JSON file or inline JSON object containing kid session telemetry",
    )

    # 6. report
    p_rep = sub.add_parser("report", help="Render report for a completed run")
    p_rep.add_argument("--run", required=True, help="Run ID, directory, or JSON path")
    p_rep.add_argument(
        "--format",
        choices=("markdown", "json", "prom"),
        default="markdown",
        help="Output format (default: markdown)",
    )
    p_rep.add_argument("--out", default=None, help="Optional output file path")

    # 7. rotate-golden
    p_rot = sub.add_parser(
        "rotate-golden", help="Update golden topic SHA-256 digest in manifest.json"
    )
    p_rot.add_argument(
        "--topic-id",
        required=True,
        help="Golden topic ID or slug (e.g. class-9-motion)",
    )
    p_rot.add_argument(
        "--source-dir", default=None, help="Optional source directory to copy from"
    )
    p_rot.add_argument(
        "--reason", required=True, help="Audit reason for rotating golden"
    )
    p_rot.add_argument(
        "--dry-run", action="store_true", help="Compute digest without writing"
    )

    # 8. backfill-db
    p_bf = sub.add_parser(
        "backfill-db",
        help="Idempotently replay JSONL ledgers into ZIVON_DB_URL relational store",
    )
    p_bf.add_argument(
        "--db-url", default=None, help="Override ZIVON_DB_URL for backfill"
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    cfg = EvalConfig.from_env()

    if args.subcommand == "run":
        if args.mock:
            cfg = dataclasses.replace(cfg, mock_mode=True)
        out_dir = Path(args.out) if args.out else None
        run_rec = run_eval_suite(
            cfg,
            suite=args.suite,
            card_id=args.card,
            topic_filter=args.topic,
            out_dir=out_dir,
        )
        print(render_markdown_report(run_rec), end="")
        return 0 if run_rec.overall_pass else 1

    if args.subcommand == "calibrate":
        if args.mock:
            cfg = dataclasses.replace(cfg, mock_mode=True)
        out_dir = Path(args.out) if args.out else None
        card_id: str | None = None
        if args.stage == "03-check":
            card_id = "EV-REV-001"
        elif args.stage == "09-review":
            card_id = "EV-REV-002"
        run_rec = run_eval_suite(
            cfg,
            suite="calibrate",
            card_id=card_id,
            out_dir=out_dir,
        )
        print(render_markdown_report(run_rec), end="")
        return 0 if run_rec.overall_pass else 1

    if args.subcommand == "diff":
        store = EvalStore(cfg)
        prev_run = store.load_run(args.prev)
        curr_run = store.load_run(args.curr)
        cards = load_all_cards(cfg.cards_dir)
        diff_rep = compute_run_diff(
            prev_run, curr_run, cards, fallback_dir=cfg.evals_runs_dir
        )
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(diff_rep.to_dict(), indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        print(render_markdown_report(curr_run, diff_rep), end="")
        return diff_rep.exit_code

    if args.subcommand == "record-edit":
        store = EvalStore(cfg)
        rec = store.record_human_edit(
            course_id=args.course,
            topic_slug=args.topic,
            class_level=args.class_level,
            baseline_dir=Path(args.baseline_dir),
            published_dir=Path(args.published_dir),
            generated_git_sha=args.baseline_sha,
            published_git_sha=args.published_sha,
            notes=args.notes,
        )
        print(json.dumps(rec.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.subcommand == "record-kid-test":
        store = EvalStore(cfg)
        inp = args.input.strip()
        if inp.startswith("{"):
            payload = json.loads(inp)
        else:
            payload = json.loads(Path(inp).read_text(encoding="utf-8"))
        try:
            kid_rec = store.record_kid_session(payload)
        except ValueError as exc:
            print(f"ERROR (DPDP Guardrail): {exc}", file=sys.stderr)
            return 1
        print(json.dumps(kid_rec.to_dict(), indent=2, ensure_ascii=False))
        return 0

    if args.subcommand == "report":
        store = EvalStore(cfg)
        run_rec = store.load_run(args.run)
        if args.format == "markdown":
            rendered = render_markdown_report(run_rec)
        elif args.format == "json":
            rendered = (
                json.dumps(run_rec.to_dict(), indent=2, ensure_ascii=False) + "\n"
            )
        else:
            rendered = render_prometheus_metrics(
                run_rec, human_edits=store._read_jsonl(store.human_edits_ledger)
            )
        if args.out:
            out_path = Path(args.out)
            out_path.parent.mkdir(parents=True, exist_ok=True)
            if out_path.is_dir():
                write_run_artifacts(out_path, run_rec)
            else:
                out_path.write_text(rendered, encoding="utf-8")
        print(rendered, end="")
        return 0

    if args.subcommand == "rotate-golden":
        src = Path(args.source_dir) if args.source_dir else None
        res = rotate_golden(
            cfg,
            topic_id=args.topic_id,
            source_dir=src,
            reason=args.reason,
            dry_run=args.dry_run,
        )
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0

    if args.subcommand == "backfill-db":
        if args.db_url:
            cfg = dataclasses.replace(cfg, db_url=args.db_url, store_backend="dual")
        store = EvalStore(cfg)
        counts = store.backfill_db()
        print(json.dumps(counts, indent=2, ensure_ascii=False))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
