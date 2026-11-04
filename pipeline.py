#!/usr/bin/env python3
"""Zivon content factory - single entry point.

Usage:
    python pipeline.py "Motion" [--class 9] [--run-id ID] [--fresh]
                                [--stages 00-ingest,01-locate]

Examples:
    python pipeline.py "Motion" --class 9
    python pipeline.py "Light - Reflection and Refraction"
    python pipeline.py "Motion" --class 9 --fresh        # force clean generation
    python pipeline.py "Motion" --stages 00-ingest,01-locate   # re-run source stages only

The chapter name is searched EXACTLY in the cached NCERT books (by title);
other catalog PDFs are searched by vector similarity. Ambiguity is an error
that lists the candidates - pass --class to disambiguate.

Run ids are deterministic per (chapter+class): re-running the same topic
RESUMES the previous attempt (completed stages are reused, a late failure
never re-derives early ones). --fresh wipes the previous attempt and
generates the page from scratch.
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(REPO_ROOT))

from factory.config import load_config
from factory.errors import FactoryError
from factory.stages import STAGE_ORDER, run_pipeline


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Zivon content factory: chapter name -> study page"
    )
    parser.add_argument("chapter", help="chapter title to search for, e.g. 'Motion'")
    parser.add_argument(
        "--class",
        dest="class_",
        type=int,
        default=None,
        choices=range(6, 13),
        help="disambiguate the chapter by class (6-12)",
    )
    parser.add_argument("--run-id", default=None, help="override the generated run id")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="wipe any previous run for this topic and generate clean "
        "(default: a re-trigger RESUMES the previous attempt's completed stages)",
    )
    parser.add_argument(
        "--stages",
        default=None,
        help=f"comma-separated subset of stages to run from {STAGE_ORDER}",
    )
    args = parser.parse_args()

    only = [s.strip() for s in args.stages.split(",")] if args.stages else None
    if only:
        unknown = [s for s in only if s not in STAGE_ORDER]
        if unknown:
            print(
                f"ERROR: unknown stage id(s) {unknown}. Valid: {STAGE_ORDER}",
                file=sys.stderr,
            )
            return 2

    try:
        cfg = load_config()
        result = run_pipeline(
            cfg, args.chapter, args.class_, args.run_id, only, fresh=args.fresh
        )
    except FactoryError as exc:
        print(f"\nPIPELINE FAILED: {exc}", file=sys.stderr)
        print(
            "\nFull evidence is under runs/<run_id>/ (requests, responses, retries, reports).",
            file=sys.stderr,
        )
        return 1
    except Exception:  # noqa: BLE001 — last-resort crash handler: prints the traceback and exits 1, loud by design
        # Unexpected bug: crash loudly with a traceback. No silent fallbacks.
        print(
            "\nUNEXPECTED PIPELINE CRASH (this is a bug, please report the traceback):",
            file=sys.stderr,
        )
        traceback.print_exc()
        return 1

    print(
        f"\nDONE: run {result['run_id']} - topic page generated, reviewed and linked."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
