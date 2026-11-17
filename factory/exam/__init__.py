"""`factory.exam` - exam-pattern content: metadata ingest, blueprint, series.

P3's pipeline. It is a **separate entrypoint** from the lesson factory
(`pipeline.py`, stages `00-12`) and from the assessment pipeline
(`factory.assessment`, stages `A1-A6`), for the same reason both of those are
separate: a lesson run must never spend exam-pipeline work, and an exam/series
rebuild must never re-derive a published page or a practice bank.

The pipeline has four stages:

    E1-ingest    read the tracked paper *metadata* fixtures, validate them
    E2-blueprint chapter weightage, type mix, section structure, recency-weighted
    E3-series    assemble the six series from the blueprint + the P2 item pools
    E4-publish   flatten the pack, run the publish gate, write the manifest

**Compliance posture is structural, not a setting** (`docs/compliance/`,
`DEC-COMP-001`): this pipeline never stores question text from a paper. A paper
fixture is metadata only - year, paper type, section, question number, type,
marks, chapter - and the ingest gate fails if a text-bearing field appears.
`EXAM_CONTENT_MODE` defaults to `blueprint_only`; `attributed_verbatim` is
refused unless `EXAM_VERBATIM_CLEARANCE_ID` names a row in the compliance
clearance register, and `SERIES_EXACT_PYQ_ENABLED` is refused while verbatim
mode is not cleared. The exact-PYQ series exists in the catalogue as `disabled`
so the product can say what it is waiting for instead of pretending.

Spec: `docs/content-factory/exam.md`.
"""

from __future__ import annotations

# Bump when the E1-E4 stage graph or an artifact's MEANING changes: a
# mismatched fingerprint refuses resume rather than mixing two pipeline shapes.
# 1 (2026-11-17): first E1-E4 graph (metadata ingest, blueprint, series,
# publish gate).
EXAM_PIPELINE_VERSION = "1"

EXAM_STAGE_ORDER = (
    "E1-ingest",
    "E2-blueprint",
    "E3-series",
    "E4-publish",
)

# `docs/compliance/cbse-exam-content.md` §7.1. The mode is a compliance state,
# never a convenience flag; unknown values fail closed.
CONTENT_MODES = ("blueprint_only", "attributed_verbatim")

# The paper a metadata fixture describes. `sample` is an official sample
# question paper (SQP); `main`/`compartment` are board papers.
PAPER_TYPES = ("main", "compartment", "sample")

# What a fixture covers: a whole paper, or only the Physics section of a
# combined-science paper (CBSE Class 10 Science carries Physics, Chemistry and
# Biology in one paper; SERIES only rehearses the Physics part).
PAPER_SCOPES = ("full_paper", "physics_section")

# CBSE-style response modes. `numeric` is the P2 practice type that can fill a
# 2-mark very-short-answer slot in the assembled pack; the rest are the paper
# template's own modes.
QUESTION_TYPES = (
    "mcq",
    "assertion_reason",
    "numeric",
    "very_short",
    "short",
    "case_based",
    "long",
)

# Which pool item types may fill a paper slot of a given type. Objective slots
# accept only objective items; a 2-mark numerical is a real CBSE section-B
# question, a 3-mark short answer is not something an MCQ can stand in for.
SLOT_ITEM_TYPES: dict[str, tuple[str, ...]] = {
    "mcq": ("mcq",),
    "assertion_reason": ("assertion_reason",),
    "very_short": ("numeric", "very_short"),
    "short": ("short",),
    "case_based": ("case_based",),
    "long": ("long",),
}

# `docs/compliance/cbse-exam-content.md` §7.2. The `verbatim_*` values exist in
# the vocabulary so a mode switch is a publish-time decision, not a migration;
# they are unreachable while the clearance register is empty.
SOURCE_TYPES = (
    "generated_blueprint",
    "generated_pattern",
    "verbatim_cbse_paper",
    "verbatim_cbse_sqp",
    "verbatim_cbse_ms",
)
VERBATIM_SOURCE_TYPES = (
    "verbatim_cbse_paper",
    "verbatim_cbse_sqp",
    "verbatim_cbse_ms",
)

# CBSE-style surfaces are EN/HI only (FEATURE-MAP #3, `notices.md`).
EXAM_LANGUAGES = ("en", "hi")

# The item pack carries more than the notices do: FEATURE-MAP §12 keeps
# Hinglish for the non-board series (AI lesson, Challenge, Loop) and disables it
# only for the CBSE-style ones. A series' `language_policy` decides which of
# these its items must carry; the notices remain English/Hindi.
PACK_LANGUAGES = ("en", "hi", "hi-Latn")

# The licence bases a verbatim item may claim (`cbse-exam-content.md` §7.2).
# `none` is the only value blueprint-mode items carry.
LICENCE_BASES = (
    "none",
    "cbse_website_policy",
    "written_permission",
    "counsel_opinion",
)

__all__ = [
    "CONTENT_MODES",
    "EXAM_LANGUAGES",
    "EXAM_PIPELINE_VERSION",
    "EXAM_STAGE_ORDER",
    "LICENCE_BASES",
    "PACK_LANGUAGES",
    "PAPER_SCOPES",
    "PAPER_TYPES",
    "QUESTION_TYPES",
    "SLOT_ITEM_TYPES",
    "SOURCE_TYPES",
    "VERBATIM_SOURCE_TYPES",
]
