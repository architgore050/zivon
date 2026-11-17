"""`python -m factory.assessment` - the separate assessment-content entrypoint.

Examples:
    python -m factory.assessment --chapter class-9-describing-motion-around-us
    python -m factory.assessment --chapter class-9-describing-motion-around-us \\
        --chapter class-10-light-reflection-and-refraction
    python -m factory.assessment --chapter class-9-describing-motion-around-us \\
        --export-dir runs/assessment-exports
    python -m factory.assessment --list-chapters
    python -m factory.assessment --chapter class-9-describing-motion-around-us \\
        --generator llm            # live generation; needs ZIVON_BASE_URL/ZIVON_MODEL

Run ids are deterministic per chapter (`assessment-<chapter_id>`): a re-trigger
RESUMES completed stages. `--fresh` wipes the run dir and rebuilds.

The lesson factory (`pipeline.py`) is a different command with a different
stage graph; this entrypoint never touches stages 00-12 or the published
frontend tree.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

from . import ASSESSMENT_STAGE_ORDER
from .config import AssessmentConfig
from .errors import AssessmentError
from .pipeline import run_assessment
from .syllabus import load_syllabus

REPO_ROOT = Path(__file__).resolve().parents[2]


def _split_stages(raw: str | None) -> list[str] | None:
    if not raw:
        return None
    return [stage.strip() for stage in raw.split(",") if stage.strip()]


def _print_chapters(syllabus: dict, class_filter: int | None) -> None:
    header = f"{'class':>5}  {'chapter_id':<48} {'#':>2}  {'concepts':<8}  title"
    print(header)
    print("-" * len(header))
    for class_entry in syllabus["classes"]:
        if class_filter is not None and class_entry["class"] != class_filter:
            continue
        for chapter in class_entry["chapters"]:
            print(
                f"{chapter['class']:>5}  {chapter['chapter_id']:<48} "
                f"{chapter['number']:>2}  {chapter['concepts_status']:<8}  "
                f"{chapter['title']}"
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Zivon assessment-content pipeline (practice + speaking)."
    )
    parser.add_argument(
        "--chapter",
        action="append",
        default=[],
        help="chapter_id to build (repeatable); e.g. class-9-describing-motion-around-us",
    )
    parser.add_argument(
        "--list-chapters",
        action="store_true",
        help="print the syllabus chapter ids (no model, no writes)",
    )
    parser.add_argument(
        "--class",
        dest="class_",
        type=int,
        default=None,
        choices=range(9, 13),
        help="filter --list-chapters by class",
    )
    parser.add_argument(
        "--generator",
        choices=("seed", "llm"),
        default=None,
        help="seed = tracked curated banks (key-free); llm = live generation (Q-10)",
    )
    parser.add_argument(
        "--export-dir",
        default=None,
        help="mirror each chapter's pack to <export-dir>/<chapter_id>/",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="wipe the chapter's assessment run and rebuild (default: resume)",
    )
    parser.add_argument(
        "--stages",
        default=None,
        help=f"comma-separated subset of {ASSESSMENT_STAGE_ORDER}",
    )
    parser.add_argument("--run-id", default=None, help="override the run id")
    parser.add_argument(
        "--runs-dir",
        default=None,
        help="alternate assessment runs root (default: <repo>/runs/assessment)",
    )
    args = parser.parse_args(argv)

    from factory.config import load_config

    try:
        # The dry run must be key-free, so load without demanding an endpoint;
        # live generation re-loads through the normal tripwire.
        cfg = load_config(require_server=False)
        resolved_generator = args.generator or cfg.data["assessment"]["generator"]
        if resolved_generator == "llm":
            cfg = load_config(require_server=True)
        assessment_cfg = AssessmentConfig.from_config(
            cfg,
            generator=args.generator,
            export_dir=cfg.repo_path(args.export_dir) if args.export_dir else None,
            runs_dir=cfg.repo_path(args.runs_dir) if args.runs_dir else None,
        )
        if args.list_chapters:
            _print_chapters(load_syllabus(assessment_cfg), args.class_)
            return 0
        if not args.chapter:
            parser.error("--chapter is required unless --list-chapters is used")
        result = run_assessment(
            assessment_cfg,
            args.chapter,
            fresh=args.fresh,
            only_stages=_split_stages(args.stages),
            run_id=args.run_id,
        )
    except AssessmentError as exc:
        print(f"\nASSESSMENT FAILED: {exc}", file=sys.stderr)
        print(
            "\nEvidence is under runs/assessment/<run_id>/ (gate report, "
            "inputs, stage outputs).",
            file=sys.stderr,
        )
        return 1
    except Exception:  # noqa: BLE001 - last-resort crash handler: loud by design
        print(
            "\nUNEXPECTED ASSESSMENT CRASH (this is a bug, please report the traceback):",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1

    print("\nSUMMARY")
    for run in result["runs"]:
        print(
            f"  {run['chapter_id']}: {run['items']} items, "
            f"{run['speaking_prompts']} speaking prompts, "
            f"{run['question_rows']} question rows | run {run['run_id']} | "
            f"content {run['content_hash'][:19]}"
        )
        if run.get("exported_dir"):
            print(f"    exported -> {run['exported_dir']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
