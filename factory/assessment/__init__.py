"""`factory.assessment` - the separate assessment-content pipeline (Q-1).

Practice items, speaking rubrics, concept tagging, time priors and the
versioned export pack do not belong in a lesson run: a lesson must never spend
assessment credits, and an assessment re-run must never re-derive a published
page. This package is its own entrypoint (`python -m factory.assessment`),
with its own run directory, ledger and stage graph (A1-A6).

The lesson factory (`pipeline.py` + `factory/stages.py`) is untouched: it
still owns stages 00-12. This package reads its artifacts (the P1 manifest)
and never writes them.

Spec: `docs/content-factory/assessment.md`.
"""

from __future__ import annotations

# Bump when the assessment stage graph or an artifact's MEANING changes: a
# mismatched fingerprint refuses resume rather than mixing two pipeline shapes.
# 1 (2026-11-17): first A1-A6 graph (syllabus, concept tag, practice items,
# speaking rubrics, time priors, publish/export).
ASSESSMENT_PIPELINE_VERSION = "1"

ASSESSMENT_STAGE_ORDER = [
    "A1-syllabus",
    "A2-concept-tag",
    "A3-practice-items",
    "A4-speaking-rubrics",
    "A5-time-priors",
    "A6-publish-export",
]

# The languages every practice item and speaking prompt must carry (FEATURE-MAP
# #3: lessons, UI, AI-generated tests and non-CBSE practice are EN/HI/Hinglish;
# CBSE-style series are P3 and EN/HI only).
LANGUAGES = ("en", "hi", "hi-Latn")

ITEM_TYPES = ("mcq", "numeric", "assertion_reason")
DIFFICULTIES = ("easy", "medium", "hard")

__all__ = [
    "ASSESSMENT_PIPELINE_VERSION",
    "ASSESSMENT_STAGE_ORDER",
    "DIFFICULTIES",
    "ITEM_TYPES",
    "LANGUAGES",
]
