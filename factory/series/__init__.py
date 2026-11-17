"""`factory.series` - the six test series: definitions, assembly, gates, publish.

The six series are a frozen product decision (FEATURE-MAP §9 / §12, `SER-03` …
`SER-09`) and the approved volume is `FEATURE-MAP` §12's table. This module owns
the *definitions*: what each series is for, which languages it promises, which
source policy it follows, which notice it must carry, and the volume it must
reach before it may publish.

Numbers live here rather than in `config.json` on purpose: they are approved
product decisions, not deployment tuning. The few test-shape knobs the
assembler needs (chapter-test size, set size) are config because they do not
change what the gate promises.

Series language rules (FEATURE-MAP #3, §12):

- AI Lesson, Challenge, Loop: EN + HI + Hinglish (normal course material);
- PYQ Pattern, Exact PYQ, Board Practice: EN + HI only (CBSE-style surfaces).

No series in `blueprint_only` mode claims a past paper. Generated series carry
`N-01`; the verbatim series carries `N-03` and stays `disabled` until a
clearance record exists (`DEC-COMP-001`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from factory.exam import PACK_LANGUAGES

SERIES_ORDER = (
    "ai_lesson",
    "pyq_pattern",
    "exact_pyq",
    "board_practice",
    "challenge",
    "loop",
)

TRI_LINGUAL = ("en", "hi", "hi-Latn")
BOARD_LINGUAL = ("en", "hi")

# FEATURE-MAP §12.2 - approved minimum volume at launch. The gate holds every
# series to the row for its class; the prototype's real data is expected to
# fall short and the shortfall is published in the gap report, never smoothed.
MINIMUM_VOLUME: dict[int, dict[str, dict[str, int]]] = {
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
class SeriesSpec:
    series_id: str
    feature_id: str
    label: str
    label_key: str
    purpose: str
    language_policy: tuple[str, ...]
    source_policy: str
    notice_id: str | None
    board_style: bool = False
    requires_verbatim: bool = False
    minimum: dict[str, int] = field(default_factory=dict)

    def languages_for_pack(self) -> tuple[str, ...]:
        """Only languages the pack can actually carry."""
        return tuple(lang for lang in self.language_policy if lang in PACK_LANGUAGES)


SERIES_SPECS: dict[str, SeriesSpec] = {
    "ai_lesson": SeriesSpec(
        series_id="ai_lesson",
        feature_id="SER-04",
        label="AI lesson tests",
        label_key="series.ai_lesson.label",
        purpose=(
            "Chapter tests and mixed practice built from the lesson concepts: "
            "does the student understand what was just taught?"
        ),
        language_policy=TRI_LINGUAL,
        source_policy="generated_blueprint",
        notice_id="N-01",
    ),
    "pyq_pattern": SeriesSpec(
        series_id="pyq_pattern",
        feature_id="SER-05",
        label="Exam-pattern practice",
        label_key="series.pyq_pattern.label",
        purpose=(
            "Recurring question shapes mined from the paper design - close to the "
            "paper pattern, without pretending to be a real paper."
        ),
        language_policy=BOARD_LINGUAL,
        source_policy="generated_pattern",
        notice_id="N-01",
        board_style=True,
    ),
    "exact_pyq": SeriesSpec(
        series_id="exact_pyq",
        feature_id="SER-06",
        label="Past-year questions (CBSE)",
        label_key="series.exact_pyq.label",
        purpose=(
            "Curated past-year Physics questions with the source shown on every "
            "question. Dark until a verbatim clearance is recorded."
        ),
        language_policy=BOARD_LINGUAL,
        source_policy="curated_verbatim",
        notice_id=None,
        board_style=True,
        requires_verbatim=True,
    ),
    "board_practice": SeriesSpec(
        series_id="board_practice",
        feature_id="SER-07",
        label="Board practice",
        label_key="series.board_practice.label",
        purpose=(
            "Full-paper rehearsal close to the CBSE paper pattern: same sections, "
            "same marks, same time."
        ),
        language_policy=BOARD_LINGUAL,
        source_policy="generated_blueprint",
        notice_id="N-01",
        board_style=True,
    ),
    "challenge": SeriesSpec(
        series_id="challenge",
        feature_id="SER-08",
        label="Challenge sets",
        label_key="series.challenge.label",
        purpose=(
            "Harder questions drawn from the same chapter concepts, in short "
            "sets for stretch practice."
        ),
        language_policy=TRI_LINGUAL,
        source_policy="generated_blueprint",
        notice_id="N-01",
    ),
    "loop": SeriesSpec(
        series_id="loop",
        feature_id="SER-09",
        label="Loop drills",
        label_key="series.loop.label",
        purpose=(
            "Drill the question shapes that keep appearing across papers, in "
            "short repeating sets."
        ),
        language_policy=TRI_LINGUAL,
        source_policy="generated_pattern",
        notice_id="N-01",
    ),
}


def series_spec(series_id: str) -> SeriesSpec:
    try:
        return SERIES_SPECS[series_id]
    except KeyError as exc:  # pragma: no cover - callers iterate SERIES_ORDER
        raise KeyError(f"unknown series {series_id!r}") from exc


def minimum_volume(class_num: int, series_id: str) -> dict[str, int]:
    try:
        return dict(MINIMUM_VOLUME[class_num][series_id])
    except KeyError as exc:
        raise KeyError(
            f"no approved volume for series {series_id!r} in class {class_num}"
        ) from exc


def series_copy(spec: SeriesSpec, *, class_num: int, subject_en: str) -> str:
    """The series' approved English blurb (FEATURE-MAP SER-14 / §12.3).

    Generated series say what they are ("close to the paper pattern", "built
    for practice") and what they are not ("not an official CBSE paper").
    Localised display copy is the frontend's i18n layer; the pack carries the
    English source plus `label_key` and the notice id.
    """
    if spec.series_id == "ai_lesson":
        return (
            "Chapter tests and mixed practice built from the lesson concepts. "
            "Written by Zivon for practice."
        )
    if spec.series_id == "challenge":
        return (
            "Harder questions drawn from the same chapter concepts. "
            "Written by Zivon for practice."
        )
    if spec.series_id == "loop":
        return (
            "Drill the question shapes that keep appearing in the paper pattern. "
            "Written by Zivon for practice."
        )
    if spec.series_id == "pyq_pattern":
        return (
            f"Built to the CBSE Class {class_num} {subject_en} paper pattern. "
            "Close to the paper pattern and built for practice; not an official "
            "CBSE paper."
        )
    if spec.series_id == "board_practice":
        return (
            f"Full-paper rehearsal close to the CBSE Class {class_num} {subject_en} "
            "paper pattern. Built for practice; not an official CBSE paper."
        )
    # exact_pyq: only rendered in cleared verbatim mode, where the series intro
    # is N-03. The static blurb stays empty so no blue-print-mode page can show
    # a past-paper claim.
    return ""


__all__ = [
    "BOARD_LINGUAL",
    "MINIMUM_VOLUME",
    "SERIES_ORDER",
    "SERIES_SPECS",
    "TRI_LINGUAL",
    "SeriesSpec",
    "minimum_volume",
    "series_copy",
    "series_spec",
]
