"""`python -m factory.exam` - the exam/series entrypoint.

Examples:
    python -m factory.exam --class 10
    python -m factory.exam --class 10 --class 12
    python -m factory.exam --class 12 --require-publishable   # CI/admin gate
    python -m factory.exam --list-papers                     # no writes
    python -m factory.exam --class 10 --fresh

Run ids are deterministic per class (`exam-class-<n>`): a re-trigger RESUMES
completed stages. `--fresh` wipes the run directory and rebuilds.

The lesson factory (`pipeline.py`) and the assessment pipeline
(`factory.assessment`) are different commands with different stage graphs; this
entrypoint never touches stages 00-12, A1-A6, `factory/render.py` or the
published frontend tree.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from . import EXAM_STAGE_ORDER
from .config import ExamConfig
from .errors import ExamError
from .pipeline import run_exam

REPO_ROOT = Path(__file__).resolve().parents[2]


def _split_stages(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [stage.strip() for stage in raw.split(",") if stage.strip()]


def _print_papers(cfg: ExamConfig) -> None:
    from .ingest import load_fixture_documents

    documents = load_fixture_documents(cfg.papers_dir)
    header = (
        f"{'class':>5}  {'year':>4}  {'type':<11} {'scope':<16} "
        f"{'q':>3}  {'marks':>5}  paper_id"
    )
    print(header)
    print("-" * len(header))
    for _, document in sorted(
        documents,
        key=lambda pair: (pair[1]["class_num"], pair[1]["year"], pair[1]["paper_id"]),
    ):
        marks = sum(int(question["marks"]) for question in document["questions"])
        print(
            f"{document['class_num']:>5}  {document['year']:>4}  "
            f"{document['paper_type']:<11} {document['scope']:<16} "
            f"{len(document['questions']):>3}  {marks:>5}  {document['paper_id']}"
        )
    print(
        "\nPattern metadata only: these fixtures carry no question text "
        "(DEC-COMP-001, blueprint_only)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zivon exam-pattern blueprint and series pipeline."
    )
    parser.add_argument(
        "--class",
        dest="classes",
        action="append",
        type=int,
        choices=(10, 12),
        help="class to build (repeatable); default: 10 and 12",
    )
    parser.add_argument(
        "--list-papers",
        action="store_true",
        help="print the ingested paper metadata (no model, no writes)",
    )
    parser.add_argument(
        "--export-dir",
        default=None,
        help="mirror a publishable pack to <export-dir>/class-<n>/",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="wipe the class's exam run and rebuild (default: resume)",
    )
    parser.add_argument(
        "--stages",
        default=None,
        help=f"comma-separated subset of {list(EXAM_STAGE_ORDER)}",
    )
    parser.add_argument("--run-id", default=None, help="override the run id")
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="alternate exam runs root (default: <repo>/runs/exam)",
    )
    parser.add_argument(
        "--require-publishable",
        action="store_true",
        help="exit non-zero when a class's pack is blocked by the publish gate",
    )
    args = parser.parse_args(argv)

    from factory.config import load_config

    try:
        # E1-E4 make no model calls; the dry run must build in CI key-free.
        cfg = load_config(require_server=False)
        exam_cfg = ExamConfig.from_config(
            cfg,
            export_dir=cfg.repo_path(args.export_dir) if args.export_dir else None,
            runs_dir=cfg.repo_path(args.runs_dir) if args.runs_dir else None,
        )
        if args.list_papers:
            _print_papers(exam_cfg)
            return 0
        classes = args.classes or [10, 12]
        result = run_exam(
            exam_cfg,
            classes,
            fresh=args.fresh,
            only_stages=_split_stages(args.stages),
            run_id=args.run_id,
            require_publishable=args.require_publishable,
        )
    except ExamError as exc:
        print(f"\nEXAM PIPELINE FAILED: {exc}", file=sys.stderr)
        print(
            "\nEvidence is under runs/exam/<run_id>/ (gate report, stage outputs).",
            file=sys.stderr,
        )
        return 1
    except Exception:  # noqa: BLE001 - last-resort crash handler: loud by design
        print(
            "\nUNEXPECTED EXAM PIPELINE CRASH (this is a bug, please report the "
            "traceback):",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1

    print("\nSUMMARY")
    for run in result["runs"]:
        status = "publishable" if run["publishable"] else "blocked"
        print(
            f"  class {run['class_num']}: {run['papers']} papers, "
            f"{run['items']} items, {run['series']} series, "
            f"{run['question_rows']} question rows | {status} | "
            f"run {run['run_id']} | content {run['content_hash'][:19]}"
        )
        print(f"    pack -> {run['pack_dir']}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
