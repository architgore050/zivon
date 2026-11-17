"""The six test series: runtime definitions, copy, and compliance notices (F7).

The product definitions live in `factory/series/__init__.py` (P3's build-time
source of truth, frozen by FEATURE-MAP §12). The backend image does **not**
ship `factory/`, so this module mirrors the runtime slice the pages need:
label, purpose, language policy, notice id, approved classes, and the approved
minimum volume. `testing/backend/test_web_tests.py` asserts the mirror stays in
step with the pipeline module (it runs from the repo root, where both are
importable), so the duplication cannot drift silently.

Compliance posture (`docs/compliance/`): generated series carry notice `N-01`
once per page, and the verbatim Exact PYQ series stays dark until
`DEC-COMP-001` has a clearance record. The copy helpers below are the exact
approved strings — never invent a claim in a template.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

TRI_LINGUAL: Final[tuple[str, ...]] = ("en", "hi", "hi-Latn")
BOARD_LINGUAL: Final[tuple[str, ...]] = ("en", "hi")

# The two classes with an approved series volume (FEATURE-MAP §12.2). Class 9
# and 11 students still get chapter/custom tests from their own bank; the
# six-series catalogue says honestly that it opens for 10 and 12 first.
APPROVED_CLASSES: Final[tuple[int, ...]] = (10, 12)

MINIMUM_VOLUME: Final[dict[int, dict[str, dict[str, int]]]] = {
    10: {
        "ai_lesson": {
            "questions_per_chapter": 20,
            "chapter_tests_per_chapter": 1,
            "mixed_tests": 2,
        },
        "pyq_pattern": {"full_papers": 5, "chapter_or_unit_tests": 10},
        "exact_pyq": {"past_years": 5},
        "board_practice": {"full_papers": 5},
        "challenge": {"questions": 100, "sets": 10},
        "loop": {"questions": 100, "sets": 10},
    },
    12: {
        "ai_lesson": {
            "questions_per_chapter": 20,
            "chapter_tests_per_chapter": 1,
            "mixed_tests": 2,
        },
        "pyq_pattern": {"full_papers": 5, "chapter_or_unit_tests": 10},
        "exact_pyq": {"past_years": 5},
        "board_practice": {"full_papers": 5},
        "challenge": {"questions": 100, "sets": 10},
        "loop": {"questions": 100, "sets": 10},
    },
}


@dataclass(frozen=True)
class SeriesDefinition:
    """One series as a page renders it."""

    kind: str
    slug: str
    label: str
    purpose: str
    coverage: str
    length: str
    languages: tuple[str, ...]
    notice_id: str | None
    board_style: bool = False
    requires_verbatim: bool = False


SERIES_ORDER: Final[tuple[str, ...]] = (
    "ai_lesson",
    "pyq_pattern",
    "exact_pyq",
    "board_practice",
    "challenge",
    "loop",
)

SERIES_DEFINITIONS: Final[dict[str, SeriesDefinition]] = {
    "ai_lesson": SeriesDefinition(
        kind="ai_lesson",
        slug="ai-lesson",
        label="AI lesson tests",
        purpose=(
            "Chapter tests and mixed practice built from the lesson concepts: "
            "does the student understand what was just taught?"
        ),
        coverage="Every chapter that has an imported lesson question bank.",
        length="Chapter tests of 10-20 questions, plus mixed tests.",
        languages=TRI_LINGUAL,
        notice_id="N-01",
    ),
    "pyq_pattern": SeriesDefinition(
        kind="pyq_pattern",
        slug="pyq-pattern",
        label="Exam-pattern practice",
        purpose=(
            "Recurring question shapes mined from the paper design - close to the "
            "paper pattern, without pretending to be a real paper."
        ),
        coverage="All syllabus chapters, weighted by the latest paper pattern.",
        length="Full papers plus chapter/unit tests.",
        languages=BOARD_LINGUAL,
        notice_id="N-01",
        board_style=True,
    ),
    "exact_pyq": SeriesDefinition(
        kind="exact_pyq",
        slug="exact-pyq",
        label="Past-year questions (CBSE)",
        purpose=(
            "Curated past-year Physics questions with the source shown on every "
            "question. Dark until a verbatim clearance is recorded."
        ),
        coverage="Past CBSE Physics papers, with per-question attribution.",
        length="Five years of main and compartment papers.",
        languages=BOARD_LINGUAL,
        notice_id=None,
        board_style=True,
        requires_verbatim=True,
    ),
    "board_practice": SeriesDefinition(
        kind="board_practice",
        slug="board-practice",
        label="Board practice",
        purpose=(
            "Full-paper rehearsal close to the CBSE paper pattern: same sections, "
            "same marks, same time."
        ),
        coverage="All syllabus chapters a full paper can carry.",
        length="Full Physics papers: sections, marks, and time close to the board paper.",
        languages=BOARD_LINGUAL,
        notice_id="N-01",
        board_style=True,
    ),
    "challenge": SeriesDefinition(
        kind="challenge",
        slug="challenge",
        label="Challenge sets",
        purpose=(
            "Harder questions drawn from the same chapter concepts, in short "
            "sets for stretch practice."
        ),
        coverage="Every chapter concept, at the harder end of the bank.",
        length="Short sets of hard questions.",
        languages=TRI_LINGUAL,
        notice_id="N-01",
    ),
    "loop": SeriesDefinition(
        kind="loop",
        slug="loop",
        label="Loop drills",
        purpose=(
            "Drill the question shapes that keep appearing across papers, in "
            "short repeating sets."
        ),
        coverage="The highest-frequency question shapes in the paper pattern.",
        length="Short repeating sets.",
        languages=TRI_LINGUAL,
        notice_id="N-01",
    ),
}


def series_by_slug(slug: str) -> SeriesDefinition | None:
    """Return the definition for a catalogue slug (`/app/series/{slug}`)."""
    cleaned = str(slug or "").strip()
    for definition in SERIES_DEFINITIONS.values():
        if definition.slug == cleaned:
            return definition
    return None


def series_copy(definition: SeriesDefinition, *, class_num: int, subject: str) -> str:
    """The approved English blurb (FEATURE-MAP SER-14 / §12.3).

    Generated series say what they are ("close to the paper pattern", "built
    for practice") and what they are not ("not an official CBSE paper"). The
    Exact PYQ series has no blueprint-mode blurb: showing one would make a
    past-paper claim while the series is dark.
    """
    if definition.kind == "ai_lesson":
        return (
            "Chapter tests and mixed practice built from the lesson concepts. "
            "Written by Zivon for practice."
        )
    if definition.kind == "challenge":
        return (
            "Harder questions drawn from the same chapter concepts. "
            "Written by Zivon for practice."
        )
    if definition.kind == "loop":
        return (
            "Drill the question shapes that keep appearing in the paper pattern. "
            "Written by Zivon for practice."
        )
    if definition.kind == "pyq_pattern":
        return (
            f"Built to the CBSE Class {class_num} {subject} paper pattern. "
            "Close to the paper pattern and built for practice; not an official "
            "CBSE paper."
        )
    if definition.kind == "board_practice":
        return (
            f"Full-paper rehearsal close to the CBSE Class {class_num} {subject} "
            "paper pattern. Built for practice; not an official CBSE paper."
        )
    return ""


def subject_label(class_num: int | None) -> str:
    """The subject as the notice/copy renders it (Class 9/10 combine sciences)."""
    return "Physics" if class_num in (11, 12) else "Science (Physics section)"


def n01_notice(class_num: int) -> str:
    """Notice `N-01` English, resolved (docs/compliance/notices.md)."""
    return (
        "These practice questions are written by Zivon in the style of the CBSE "
        f"Class {int(class_num)} {subject_label(class_num)} paper. They are not "
        "CBSE questions. Zivon is not affiliated with or endorsed by CBSE."
    )


def minimum_label(definition: SeriesDefinition, class_num: int) -> str:
    """One honest sentence naming the approved minimum a blocked series misses."""
    row = MINIMUM_VOLUME.get(int(class_num), {}).get(definition.kind)
    if not row:
        return "The approved volume for this class is not set yet."
    parts = [f"{key.replace('_', ' ')} {value}" for key, value in row.items()]
    return (
        "Approved minimum for Class "
        + str(int(class_num))
        + ": "
        + ", ".join(parts)
        + "."
    )


__all__ = [
    "APPROVED_CLASSES",
    "BOARD_LINGUAL",
    "MINIMUM_VOLUME",
    "SERIES_DEFINITIONS",
    "SERIES_ORDER",
    "TRI_LINGUAL",
    "SeriesDefinition",
    "minimum_label",
    "n01_notice",
    "series_by_slug",
    "series_copy",
    "subject_label",
]
