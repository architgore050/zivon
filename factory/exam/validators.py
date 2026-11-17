"""Deterministic rules for exam/series artifacts.

Every rule here is a harness guarantee, not prompt prose. The gate is shared by
the pipeline stages and by `evals/checkers/exam_checks.py`, so an eval cannot
drift from the code it measures: the checker calls the same functions on the
same tracked fixtures, plus seeded defects that must make their declared rule
fire.

Rule ids are stable strings (`area.subject`). Severity scale is the repo's:
`fatal` / `major` block, `minor` is recorded debt.

Compliance is enforced structurally here:

- a paper document carrying a text-bearing key is rejected (`exam.paper.source_text`);
- a `verbatim_*` item is rejected unless the run is in `attributed_verbatim`
  mode with a licence basis and a permission reference that resolves
  (`series.item.verbatim_in_blueprint`, `series.item.licence_basis`);
- an item flagged `third_party_content` can never publish verbatim
  (`series.item.third_party`);
- generated items must carry a pattern reference and a similarity record
  (`series.item.pattern_ref`, `series.item.similarity_missing`).
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from typing import Any

from . import (
    PACK_LANGUAGES,
    VERBATIM_SOURCE_TYPES,
)
from .report import Issue, schema_issue, validate_schema
from .schemas import (
    EXAM_BLUEPRINT,
    EXAM_INGEST,
    EXAM_ITEM,
    EXAM_PACK_MANIFEST,
    EXAM_QUESTION_ROW,
    PAPER_FIXTURE,
    SERIES_MANIFEST,
)

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

# CBSC question types carry a marks convention in the paper template. A paper
# that breaks it is either mistyped or a different design; either way a human
# updates the template instead of the gate guessing.
MARKS_BY_TYPE: dict[str, tuple[int, ...]] = {
    "mcq": (1,),
    "assertion_reason": (1,),
    "numeric": (1, 2),
    "very_short": (2,),
    "short": (3,),
    "case_based": (4,),
    "long": (5,),
}

# Keys that would carry source expression rather than pattern metadata. The
# fixture schema already forbids them; this scan catches a document that puts
# one inside an otherwise-valid place (e.g. a nested `options` block).
FORBIDDEN_TEXT_KEYS = frozenset(
    {
        "text",
        "question",
        "question_text",
        "question_html",
        "prompt",
        "passage",
        "statement",
        "stem",
        "body",
        "content",
        "option",
        "options",
        "answer",
        "answers",
        "solution",
        "marking_scheme",
        "figure",
        "figure_caption",
        "image",
        "image_url",
        "diagram",
    }
)

# CBSE subject identity per class (CBSE curriculum codes). A Class 10 fixture
# describes the Physics section of Science (086); a Class 12 fixture describes
# the full Physics paper (042).
SUBJECT_BY_CLASS: dict[int, tuple[str, str, str]] = {
    10: ("Science", "086", "physics_section"),
    12: ("Physics", "042", "full_paper"),
}

_ALLOWED_SECTION_IDS = tuple("ABCDEF")


# --------------------------------------------------------------------- helpers
def _walk_keys(
    node: Any, path: tuple[str, ...] = ()
) -> list[tuple[str, tuple[str, ...]]]:
    found: list[tuple[str, tuple[str, ...]]] = []
    if isinstance(node, Mapping):
        for key, value in node.items():
            if str(key).lower() in FORBIDDEN_TEXT_KEYS:
                found.append((str(key), path + (str(key),)))
            found.extend(_walk_keys(value, path + (str(key),)))
    elif isinstance(node, Sequence) and not isinstance(node, (str, bytes, bytearray)):
        for index, value in enumerate(node):
            found.extend(_walk_keys(value, path + (str(index),)))
    return found


def _chapter_map(chapters: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {str(chapter["chapter_id"]): chapter for chapter in chapters}


def _sum_marks(questions: Sequence[Mapping[str, Any]]) -> int:
    return sum(int(question.get("marks", 0)) for question in questions)


# ---------------------------------------------------------------------- papers
def validate_paper_document(document: Any, *, file_name: str) -> list[Issue]:
    """The text-bearing-key scan, then schema validation for one fixture.

    The scan runs first and independently of the schema: a document that
    carries question text must fail with `exam.paper.source_text`, not only
    with a generic unknown-key error. The schema failure is still reported, so
    both problems are visible.
    """
    issues: list[Issue] = []
    paper_id = document.get("paper_id") if isinstance(document, Mapping) else None
    for _key, path in _walk_keys(document):
        issues.append(
            Issue(
                rule="exam.paper.source_text",
                severity="fatal",
                message=(
                    f"{file_name}: key {'.'.join(path)!r} could carry question or "
                    "answer text; blueprint-mode fixtures store pattern metadata "
                    "only (DEC-COMP-001)"
                ),
                paper_id=str(paper_id or file_name),
            )
        )
    try:
        validate_schema(document, PAPER_FIXTURE, file_name)
    except Exception as exc:  # noqa: BLE001 - every schema failure is one finding
        issues.append(schema_issue("exam.paper", exc, paper_id=file_name))
    return issues


def validate_papers(
    papers: Sequence[Mapping[str, Any]],
    questions: Sequence[Mapping[str, Any]],
    *,
    chapters: Sequence[Mapping[str, Any]],
    window_years: int = 5,
    latest_year: int | None = None,
) -> list[Issue]:
    """Cross-paper rules for the E1 output (the ingest gate)."""
    issues: list[Issue] = []
    chapter_index = _chapter_map(chapters)
    seen_ids: set[str] = set()

    if not papers:
        return [
            Issue(
                rule="exam.paper.missing",
                severity="fatal",
                message="no paper metadata fixtures were found",
            )
        ]

    for paper in papers:
        paper_id = str(paper["paper_id"])
        class_num = int(paper["class_num"])
        if paper_id in seen_ids:
            issues.append(
                Issue(
                    rule="exam.paper.duplicate",
                    severity="fatal",
                    message=f"paper_id {paper_id!r} appears twice",
                    paper_id=paper_id,
                )
            )
        seen_ids.add(paper_id)

        expected_subject, expected_code, expected_scope = SUBJECT_BY_CLASS[class_num]
        if paper["subject"] != expected_subject:
            issues.append(
                Issue(
                    rule="exam.paper.class_subject",
                    severity="fatal",
                    message=(
                        f"class {class_num} papers are {expected_subject}, "
                        f"got {paper['subject']!r}"
                    ),
                    paper_id=paper_id,
                )
            )
        if (paper.get("subject_code") or "") != expected_code:
            issues.append(
                Issue(
                    rule="exam.paper.class_subject",
                    severity="fatal",
                    message=(
                        f"class {class_num} {expected_subject} has subject code "
                        f"{expected_code}, got {paper.get('subject_code')!r}"
                    ),
                    paper_id=paper_id,
                )
            )
        if paper["scope"] != expected_scope:
            issues.append(
                Issue(
                    rule="exam.paper.scope",
                    severity="fatal",
                    message=(
                        f"class {class_num} fixture scope is {expected_scope!r}, "
                        f"got {paper['scope']!r}"
                    ),
                    paper_id=paper_id,
                )
            )
        if paper["paper_type"] in ("main", "compartment") and not paper.get("set_code"):
            issues.append(
                Issue(
                    rule="exam.paper.set_code",
                    severity="minor",
                    message=(
                        f"{paper['paper_type']} paper without a set code; a verbatim "
                        "item would be unidentifiable (debt, harmless in blueprint mode)"
                    ),
                    paper_id=paper_id,
                )
            )

        provenance = paper.get("provenance") or {}
        source_url = str(provenance.get("source_url") or "")
        if not source_url.startswith("https://"):
            issues.append(
                Issue(
                    rule="exam.paper.provenance",
                    severity="fatal",
                    message="provenance.source_url must be an https URL",
                    paper_id=paper_id,
                )
            )
        if not provenance.get("notes"):
            issues.append(
                Issue(
                    rule="exam.paper.provenance",
                    severity="minor",
                    message="provenance.notes is empty; record how the map was made",
                    paper_id=paper_id,
                )
            )

        paper_questions = [q for q in questions if q["paper_id"] == paper_id]
        if len(paper_questions) != int(paper["question_count"]):
            issues.append(
                Issue(
                    rule="exam.paper.question_count",
                    severity="fatal",
                    message=(
                        f"paper record says {paper['question_count']} questions, "
                        f"{len(paper_questions)} rows found"
                    ),
                    paper_id=paper_id,
                )
            )
        marks_sum = _sum_marks(paper_questions)
        if marks_sum != int(paper["scope_marks"]):
            issues.append(
                Issue(
                    rule="exam.paper.marks_sum",
                    severity="fatal",
                    message=(
                        f"question marks sum to {marks_sum}, record says "
                        f"{paper['scope_marks']}"
                    ),
                    paper_id=paper_id,
                )
            )
        if paper["scope"] == "full_paper" and marks_sum != int(paper["max_marks"]):
            issues.append(
                Issue(
                    rule="exam.paper.marks_sum",
                    severity="fatal",
                    message=(
                        f"full-paper fixture covers {marks_sum} marks but max_marks "
                        f"is {paper['max_marks']}"
                    ),
                    paper_id=paper_id,
                )
            )
        if paper["scope"] == "physics_section" and not (
            0 < marks_sum < int(paper["max_marks"])
        ):
            issues.append(
                Issue(
                    rule="exam.paper.marks_sum",
                    severity="fatal",
                    message=(
                        f"physics-section fixture covers {marks_sum} of "
                        f"{paper['max_marks']} marks; expected a strict subset"
                    ),
                    paper_id=paper_id,
                )
            )

        section_ids = [str(section["id"]) for section in paper["sections"]]
        if len(set(section_ids)) != len(section_ids):
            issues.append(
                Issue(
                    rule="exam.paper.sections",
                    severity="fatal",
                    message=f"duplicate section ids {section_ids}",
                    paper_id=paper_id,
                )
            )
        expected_order = list(_ALLOWED_SECTION_IDS[: len(section_ids)])
        if section_ids != expected_order:
            issues.append(
                Issue(
                    rule="exam.paper.sections",
                    severity="fatal",
                    message=(
                        f"section ids must be contiguous from A: expected "
                        f"{expected_order}, got {section_ids}"
                    ),
                    paper_id=paper_id,
                )
            )
        for section in paper["sections"]:
            in_section = [q for q in paper_questions if q["section"] == section["id"]]
            if len(in_section) != int(section["question_count"]):
                issues.append(
                    Issue(
                        rule="exam.paper.sections",
                        severity="fatal",
                        message=(
                            f"section {section['id']} declares "
                            f"{section['question_count']} questions, "
                            f"{len(in_section)} rows found"
                        ),
                        paper_id=paper_id,
                    )
                )
            wrong_marks = [
                q for q in in_section if int(q["marks"]) != int(section["marks_each"])
            ]
            if wrong_marks:
                issues.append(
                    Issue(
                        rule="exam.paper.sections",
                        severity="fatal",
                        message=(
                            f"section {section['id']} is {section['marks_each']} "
                            f"mark(s); {len(wrong_marks)} question(s) disagree"
                        ),
                        paper_id=paper_id,
                    )
                )

        seen_numbers: set[str] = set()
        for question in paper_questions:
            number = str(question["question_no"])
            if number in seen_numbers:
                issues.append(
                    Issue(
                        rule="exam.paper.question_no",
                        severity="fatal",
                        message=f"question number {number!r} appears twice",
                        paper_id=paper_id,
                    )
                )
            seen_numbers.add(number)
            expected_marks = MARKS_BY_TYPE.get(str(question["type"]), ())
            if int(question["marks"]) not in expected_marks:
                issues.append(
                    Issue(
                        rule="exam.question.marks_type",
                        severity="fatal",
                        message=(
                            f"question {number}: {question['type']} normally carries "
                            f"{expected_marks} mark(s), got {question['marks']}"
                        ),
                        paper_id=paper_id,
                    )
                )
            chapter = chapter_index.get(str(question["chapter_id"]))
            if chapter is None:
                issues.append(
                    Issue(
                        rule="exam.question.chapter_unknown",
                        severity="fatal",
                        message=(
                            f"question {number}: chapter "
                            f"{question['chapter_id']!r} is not in the syllabus"
                        ),
                        paper_id=paper_id,
                    )
                )
            elif int(chapter["class"]) != class_num:
                issues.append(
                    Issue(
                        rule="exam.question.chapter_class",
                        severity="fatal",
                        message=(
                            f"question {number}: chapter {question['chapter_id']!r} "
                            f"is class {chapter['class']}, paper is class {class_num}"
                        ),
                        paper_id=paper_id,
                        chapter_id=str(question["chapter_id"]),
                    )
                )

        if (
            latest_year is not None
            and int(paper["year"]) < latest_year - window_years + 1
        ):
            issues.append(
                Issue(
                    rule="exam.paper.year_window",
                    severity="minor",
                    message=(
                        f"paper year {paper['year']} is outside the "
                        f"{window_years}-year blueprint window; it is ingested but "
                        "not weighted"
                    ),
                    paper_id=paper_id,
                )
            )
    return issues


def check_fixture_directory(papers_dir: Any) -> list[Issue]:
    """No PDFs (or other binary sources) may live in the tracked fixture tree."""
    from pathlib import Path

    path = Path(papers_dir)
    if not path.exists():
        return [
            Issue(
                rule="exam.paper.missing",
                severity="fatal",
                message=f"paper fixture directory {path} does not exist",
            )
        ]
    issues: list[Issue] = []
    for entry in sorted(path.rglob("*")):
        if entry.is_file() and entry.suffix.lower() not in (".json", ".md"):
            issues.append(
                Issue(
                    rule="exam.paper.source_file",
                    severity="fatal",
                    message=(
                        f"{entry.relative_to(path)} is a {entry.suffix or 'binary'} "
                        "file; P3 stores pattern metadata only, never papers"
                    ),
                )
            )
    return issues


# ------------------------------------------------------------------- blueprint
def validate_blueprint(
    blueprint: Mapping[str, Any],
    *,
    chapters: Sequence[Mapping[str, Any]],
    papers: Sequence[Mapping[str, Any]],
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        validate_schema(dict(blueprint), EXAM_BLUEPRINT, "blueprint")
    except Exception as exc:  # noqa: BLE001
        return [schema_issue("blueprint", exc)]

    chapter_index = _chapter_map(chapters)
    paper_ids = {str(paper["paper_id"]) for paper in papers}
    used = [str(pid) for pid in blueprint.get("papers_used", [])]
    if not used:
        return [
            Issue(
                rule="blueprint.papers",
                severity="fatal",
                message="the blueprint used no papers",
            )
        ]
    unknown_papers = [pid for pid in used if pid not in paper_ids]
    if unknown_papers:
        issues.append(
            Issue(
                rule="blueprint.papers",
                severity="fatal",
                message=f"blueprint cites papers that were not ingested: {unknown_papers}",
            )
        )

    chapter_rows = {row["chapter_id"]: row for row in blueprint["chapters"]}
    for chapter in chapters:
        chapter_id = str(chapter["chapter_id"])
        row = chapter_rows.get(chapter_id)
        if row is None:
            issues.append(
                Issue(
                    rule="blueprint.chapter_unknown",
                    severity="fatal",
                    message=f"syllabus chapter {chapter_id!r} is absent from the blueprint",
                    chapter_id=chapter_id,
                )
            )
            continue
        if int(row["papers_observed"]) == 0:
            issues.append(
                Issue(
                    rule="blueprint.chapter_uncovered",
                    severity="major",
                    message=(
                        f"chapter {chapter_id!r} carries zero marks in every ingested "
                        "paper; the series gate cannot cover it"
                    ),
                    chapter_id=chapter_id,
                )
            )
    unknown_chapters = [cid for cid in chapter_rows if cid not in chapter_index]
    if unknown_chapters:
        issues.append(
            Issue(
                rule="blueprint.chapter_unknown",
                severity="fatal",
                message=f"blueprint names chapters outside the syllabus: {unknown_chapters}",
            )
        )

    total = sum(float(row["weighted_marks"]) for row in blueprint["chapters"])
    if total <= 0:
        issues.append(
            Issue(
                rule="blueprint.share_sum",
                severity="fatal",
                message="chapter weighted marks sum to zero",
            )
        )
    else:
        share_sum = sum(float(row["share"]) for row in blueprint["chapters"])
        if abs(share_sum - 1.0) > 1e-6:
            issues.append(
                Issue(
                    rule="blueprint.share_sum",
                    severity="fatal",
                    message=f"chapter shares sum to {share_sum}, expected 1.0",
                )
            )

    type_total = sum(float(row["weighted_marks"]) for row in blueprint["type_mix"])
    type_share = sum(float(row["share"]) for row in blueprint["type_mix"])
    if type_total <= 0:
        issues.append(
            Issue(
                rule="blueprint.type_mix",
                severity="fatal",
                message="type mix weighted marks sum to zero",
            )
        )
    elif abs(type_share - 1.0) > 1e-6:
        issues.append(
            Issue(
                rule="blueprint.type_mix",
                severity="fatal",
                message=f"type shares sum to {type_share}, expected 1.0",
            )
        )

    template_marks = sum(
        int(row["marks_total"]) for row in blueprint["section_template"]
    )
    template_questions = sum(
        int(row["question_count"]) for row in blueprint["section_template"]
    )
    expected_paper = None
    latest = max((int(p["year"]) for p in papers if p["paper_id"] in used), default=0)
    for paper in papers:
        if paper["paper_id"] in used and int(paper["year"]) == latest:
            expected_paper = paper
            break
    if expected_paper is not None:
        if template_marks != int(expected_paper["scope_marks"]):
            issues.append(
                Issue(
                    rule="blueprint.section_template",
                    severity="fatal",
                    message=(
                        f"section template covers {template_marks} marks, the latest "
                        f"paper covers {expected_paper['scope_marks']}"
                    ),
                )
            )
        if template_questions != int(expected_paper["question_count"]):
            issues.append(
                Issue(
                    rule="blueprint.section_template",
                    severity="fatal",
                    message=(
                        f"section template has {template_questions} questions, the "
                        f"latest paper has {expected_paper['question_count']}"
                    ),
                )
            )

    if blueprint["archetypes"]:
        archetype_share = sum(float(row["share"]) for row in blueprint["archetypes"])
        if abs(archetype_share - 1.0) > 1e-6:
            issues.append(
                Issue(
                    rule="blueprint.archetype",
                    severity="fatal",
                    message=f"archetype shares sum to {archetype_share}, expected 1.0",
                )
            )
    confidence = blueprint.get("confidence") or {}
    if int(confidence.get("unverified_papers", 0)) > 0:
        issues.append(
            Issue(
                rule="blueprint.confidence",
                severity="minor",
                message=(
                    f"{confidence['unverified_papers']} of "
                    f"{int(confidence.get('verified_papers', 0)) + int(confidence['unverified_papers'])} "
                    "papers carry an authored question-to-chapter map; the blueprint "
                    "is internally consistent but not verified against published keys"
                ),
            )
        )
    return issues


def validate_ingest(output: Mapping[str, Any]) -> list[Issue]:
    try:
        validate_schema(dict(output), EXAM_INGEST, "ingest")
    except Exception as exc:  # noqa: BLE001
        return [schema_issue("ingest", exc)]
    return []


# ---------------------------------------------------------------------- items
def _language_issues(item: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    item_id = str(item.get("item_id"))
    languages = list(item.get("languages") or [])
    locales = item.get("locales") or {}
    for language in languages:
        locale = locales.get(language)
        if not isinstance(locale, Mapping):
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=f"{item_id}: promised language {language!r} has no text",
                    item_id=item_id,
                )
            )
            continue
        prompt = str(locale.get("prompt") or "")
        if language == "hi" and not _DEVANAGARI_RE.search(prompt):
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=f"{item_id}: the Hindi prompt has no Devanagari text",
                    item_id=item_id,
                )
            )
        if language == "en" and _DEVANAGARI_RE.search(prompt):
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=f"{item_id}: the English prompt contains Devanagari text",
                    item_id=item_id,
                )
            )
        if language == "hi-Latn" and _DEVANAGARI_RE.search(prompt):
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=f"{item_id}: the Hinglish prompt contains Devanagari text",
                    item_id=item_id,
                )
            )
    for language in locales:
        if language not in languages:
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=(
                        f"{item_id}: text for {language!r} exists but the item does "
                        "not declare that language"
                    ),
                    item_id=item_id,
                )
            )
    return issues


def _answer_issues(item: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    item_id = str(item.get("item_id"))
    item_type = str(item.get("type"))
    answer = item.get("answer") or {}
    locales = item.get("locales") or {}

    if item_type in ("mcq", "assertion_reason"):
        if "index" not in answer:
            issues.append(
                Issue(
                    rule="series.item.answer",
                    severity="fatal",
                    message=f"{item_id}: {item_type} needs an option index",
                    item_id=item_id,
                )
            )
        for language, locale in locales.items():
            options = locale.get("options") or []
            if len(options) != 4:
                issues.append(
                    Issue(
                        rule="series.item.answer",
                        severity="fatal",
                        message=(
                            f"{item_id}/{language}: {item_type} needs four options, "
                            f"got {len(options)}"
                        ),
                        item_id=item_id,
                    )
                )
    elif item_type == "numeric":
        missing = {"value", "tolerance", "unit"} - set(answer)
        if missing:
            issues.append(
                Issue(
                    rule="series.item.answer",
                    severity="fatal",
                    message=f"{item_id}: numeric answer missing {sorted(missing)}",
                    item_id=item_id,
                )
            )
    else:
        if answer.get("kind") != "open":
            issues.append(
                Issue(
                    rule="series.item.answer",
                    severity="fatal",
                    message=(
                        f"{item_id}: {item_type} is a written-response item and needs "
                        "answer.kind='open'"
                    ),
                    item_id=item_id,
                )
            )
        for language, locale in locales.items():
            if not str(locale.get("model_answer") or "").strip():
                issues.append(
                    Issue(
                        rule="series.item.answer",
                        severity="fatal",
                        message=(
                            f"{item_id}/{language}: written-response item has no "
                            "model answer"
                        ),
                        item_id=item_id,
                    )
                )
    return issues


def validate_item(
    item: Mapping[str, Any],
    *,
    series: Mapping[str, Any],
    chapters: Sequence[Mapping[str, Any]],
    similarity_max_overlap: float,
    compliance: Mapping[str, Any],
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        validate_schema(dict(item), EXAM_ITEM, "item")
    except Exception as exc:  # noqa: BLE001
        return [schema_issue("series.item", exc, item_id=str(item.get("item_id")))]
    item_id = str(item["item_id"])
    chapter_ids = {str(c["chapter_id"]) for c in chapters}
    if str(item["chapter_id"]) not in chapter_ids:
        issues.append(
            Issue(
                rule="series.item.chapter",
                severity="fatal",
                message=f"{item_id}: chapter {item['chapter_id']!r} is not in the class syllabus",
                item_id=item_id,
                chapter_id=str(item["chapter_id"]),
            )
        )
    chapter = next(
        (c for c in chapters if str(c["chapter_id"]) == str(item["chapter_id"])),
        None,
    )
    concepts = [str(c["concept_id"]) for c in (chapter or {}).get("concepts", [])]
    if concepts and str(item["concept_id"]) not in concepts:
        issues.append(
            Issue(
                rule="series.item.concept",
                severity="fatal",
                message=(
                    f"{item_id}: concept {item['concept_id']!r} is not one of the "
                    f"chapter's curated concepts"
                ),
                item_id=item_id,
                chapter_id=str(item["chapter_id"]),
            )
        )
    elif not concepts:
        issues.append(
            Issue(
                rule="series.item.concept",
                severity="minor",
                message=(
                    f"{item_id}: chapter {item['chapter_id']!r} has no curated "
                    "concepts yet; the item's concept is unverified"
                ),
                item_id=item_id,
                chapter_id=str(item["chapter_id"]),
            )
        )
    expected_marks = MARKS_BY_TYPE.get(str(item["type"]), ())
    if int(item["marks"]) not in expected_marks:
        issues.append(
            Issue(
                rule="series.item.marks",
                severity="fatal",
                message=(
                    f"{item_id}: {item['type']} normally carries {expected_marks} "
                    f"mark(s), got {item['marks']}"
                ),
                item_id=item_id,
            )
        )
    language_policy = list(series["language_policy"])
    for language in language_policy:
        if language not in item["languages"]:
            issues.append(
                Issue(
                    rule="series.item.language",
                    severity="fatal",
                    message=(
                        f"{item_id}: series {series['series_id']} requires {language!r}"
                    ),
                    item_id=item_id,
                    series_id=str(series["series_id"]),
                )
            )
    extra_languages = set(item["languages"]) - set(PACK_LANGUAGES)
    if extra_languages:
        issues.append(
            Issue(
                rule="series.item.language",
                severity="fatal",
                message=f"{item_id}: unsupported languages {sorted(extra_languages)}",
                item_id=item_id,
            )
        )
    issues.extend(_language_issues(item))
    issues.extend(_answer_issues(item))

    source_type = str(item["source_type"])
    if source_type in VERBATIM_SOURCE_TYPES:
        if compliance.get("content_mode") != "attributed_verbatim":
            issues.append(
                Issue(
                    rule="series.item.verbatim_in_blueprint",
                    severity="fatal",
                    message=(
                        f"{item_id}: {source_type} item in "
                        f"{compliance.get('content_mode')} mode; verbatim CBSE "
                        "content cannot publish without a clearance (DEC-COMP-001)"
                    ),
                    item_id=item_id,
                )
            )
        if item.get("licence_basis") in (None, "none"):
            issues.append(
                Issue(
                    rule="series.item.licence_basis",
                    severity="fatal",
                    message=f"{item_id}: verbatim item has no licence basis",
                    item_id=item_id,
                )
            )
        if not item.get("permission_ref"):
            issues.append(
                Issue(
                    rule="series.item.licence_basis",
                    severity="fatal",
                    message=f"{item_id}: verbatim item has no permission reference",
                    item_id=item_id,
                )
            )
        elif item.get("permission_ref") != compliance.get("clearance_id"):
            issues.append(
                Issue(
                    rule="series.item.licence_basis",
                    severity="fatal",
                    message=(
                        f"{item_id}: permission_ref {item['permission_ref']!r} is not "
                        f"the active clearance {compliance.get('clearance_id')!r}"
                    ),
                    item_id=item_id,
                )
            )
        source_ref = item.get("source_ref") or {}
        if source_ref.get("third_party_content") is True:
            issues.append(
                Issue(
                    rule="series.item.third_party",
                    severity="fatal",
                    message=(
                        f"{item_id}: third-party content blocks verbatim publishing "
                        "even after clearance (DEC-COMP-005)"
                    ),
                    item_id=item_id,
                )
            )
        for field in ("source_url", "retrieved_at", "file_sha256", "page"):
            if source_ref.get(field) in (None, ""):
                issues.append(
                    Issue(
                        rule="series.item.source_ref",
                        severity="fatal",
                        message=f"{item_id}: verbatim item source_ref lacks {field}",
                        item_id=item_id,
                    )
                )
    else:
        if not str(item.get("pattern_ref") or "").strip():
            issues.append(
                Issue(
                    rule="series.item.pattern_ref",
                    severity="fatal",
                    message=f"{item_id}: generated item has no pattern reference",
                    item_id=item_id,
                )
            )
        similarity = item.get("similarity") or {}
        if not similarity:
            issues.append(
                Issue(
                    rule="series.item.similarity_missing",
                    severity="fatal",
                    message=f"{item_id}: generated item has no similarity record",
                    item_id=item_id,
                )
            )
        elif float(similarity.get("max_ngram_overlap", 0.0)) > similarity_max_overlap:
            issues.append(
                Issue(
                    rule="series.item.similarity",
                    severity="fatal",
                    message=(
                        f"{item_id}: 8-gram overlap "
                        f"{similarity['max_ngram_overlap']:.3f} exceeds "
                        f"{similarity_max_overlap:.2f} against "
                        f"{similarity.get('nearest_source_item_id')!r}"
                    ),
                    item_id=item_id,
                )
            )
        if item.get("licence_basis") not in (None, "none"):
            issues.append(
                Issue(
                    rule="series.item.licence_basis",
                    severity="fatal",
                    message=(
                        f"{item_id}: a generated item claims licence basis "
                        f"{item['licence_basis']!r}; generated items need none"
                    ),
                    item_id=item_id,
                )
            )
    return issues


def validate_question_row(
    row: Mapping[str, Any], *, expected_languages: Sequence[str]
) -> list[Issue]:
    try:
        validate_schema(dict(row), EXAM_QUESTION_ROW, "question_row")
    except Exception as exc:  # noqa: BLE001
        return [schema_issue("series.row", exc, item_id=str(row.get("item_id")))]
    if row["language"] not in expected_languages:
        return [
            Issue(
                rule="series.row.language",
                severity="fatal",
                message=(
                    f"{row['question_id']}: language {row['language']!r} is outside "
                    f"the series policy {list(expected_languages)}"
                ),
                item_id=str(row["item_id"]),
            )
        ]
    return []


# ----------------------------------------------------------- series manifests
def validate_series_manifest(
    manifest: Mapping[str, Any],
    *,
    items_by_id: Mapping[str, Mapping[str, Any]],
    compliance: Mapping[str, Any],
) -> list[Issue]:
    issues: list[Issue] = []
    try:
        validate_schema(dict(manifest), SERIES_MANIFEST, "series_manifest")
    except Exception as exc:  # noqa: BLE001
        return [
            schema_issue(
                "series.manifest", exc, series_id=str(manifest.get("series_id"))
            )
        ]
    from .notices import scan_claims

    series_id = str(manifest["series_id"])
    enabled = bool(manifest["enabled"])
    if series_id == "exact_pyq" and enabled and not compliance.get("exact_pyq_visible"):
        issues.append(
            Issue(
                rule="series.status.exact_pyq",
                severity="fatal",
                message=(
                    "the exact-PYQ series is enabled without a verbatim clearance "
                    "(SERIES_EXACT_PYQ_ENABLED must stay false)"
                ),
                series_id=series_id,
            )
        )
    if enabled:
        if manifest["notice_id"] not in ("N-01", "N-03"):
            issues.append(
                Issue(
                    rule="series.copy.notice",
                    severity="fatal",
                    message=(
                        f"{series_id}: an enabled series must carry N-01 (generated) "
                        f"or N-03 (verbatim), got {manifest['notice_id']!r}"
                    ),
                    series_id=series_id,
                )
            )
        if manifest["notice_id"] == "N-03" and not compliance.get("verbatim_allowed"):
            issues.append(
                Issue(
                    rule="series.copy.notice",
                    severity="fatal",
                    message=f"{series_id}: N-03 is a verbatim-series notice",
                    series_id=series_id,
                )
            )
    for field in ("label", "purpose", "copy"):
        text = str(manifest.get(field) or "")
        for finding in scan_claims(text):
            issues.append(
                Issue(
                    rule="series.copy.claim",
                    severity="fatal",
                    message=(
                        f"{series_id}.{field}: forbidden claim "
                        f"{finding['phrase']!r} ({finding['reason']})"
                    ),
                    series_id=series_id,
                )
            )
    for item_id in manifest["item_ids"]:
        if item_id not in items_by_id:
            issues.append(
                Issue(
                    rule="series.item.missing",
                    severity="fatal",
                    message=f"{series_id}: item {item_id!r} is not in the pack",
                    item_id=str(item_id),
                    series_id=series_id,
                )
            )
    for paper in manifest["papers"]:
        seen: set[str] = set()
        for slot in paper["sections"]:
            if slot["item_id"] is None:
                continue
            if slot["item_id"] not in items_by_id:
                issues.append(
                    Issue(
                        rule="series.item.missing",
                        severity="fatal",
                        message=(
                            f"{series_id}/{paper['paper_id']}: slot item "
                            f"{slot['item_id']!r} is not in the pack"
                        ),
                        paper_id=str(paper["paper_id"]),
                        series_id=series_id,
                    )
                )
            if slot["item_id"] in seen:
                issues.append(
                    Issue(
                        rule="series.item.duplicate",
                        severity="fatal",
                        message=(
                            f"{series_id}/{paper['paper_id']}: item "
                            f"{slot['item_id']!r} appears twice in one paper"
                        ),
                        item_id=str(slot["item_id"]),
                        series_id=series_id,
                    )
                )
            seen.add(str(slot["item_id"]))
    # A completed paper repeated under another paper_id is one paper counted
    # twice: five copies must never satisfy "five full papers" (SER-13). Only
    # complete papers are compared, so two honestly-empty drafts do not trip it.
    complete: dict[tuple[str, ...], str] = {}
    for paper in manifest["papers"]:
        if int(paper["filled_slots"]) != int(paper["total_slots"]):
            continue
        key = tuple(sorted(str(item_id) for item_id in paper["item_ids"]))
        if key in complete:
            issues.append(
                Issue(
                    rule="series.paper_duplicate",
                    severity="fatal",
                    message=(
                        f"{series_id}/{paper['paper_id']}: every item already "
                        f"appears in {complete[key]}; one complete paper repeated "
                        "is not a second paper"
                    ),
                    paper_id=str(paper["paper_id"]),
                    series_id=series_id,
                )
            )
        else:
            complete[key] = str(paper["paper_id"])
    return issues


def validate_pack_manifest(
    manifest: Mapping[str, Any],
    *,
    items: Sequence[Mapping[str, Any]],
    compliance: Mapping[str, Any],
) -> list[Issue]:
    try:
        validate_schema(dict(manifest), EXAM_PACK_MANIFEST, "pack_manifest")
    except Exception as exc:  # noqa: BLE001
        return [schema_issue("pack", exc)]
    issues: list[Issue] = []
    if manifest["content_mode"] != compliance.get("content_mode"):
        issues.append(
            Issue(
                rule="pack.mode_mismatch",
                severity="fatal",
                message=(
                    f"manifest says {manifest['content_mode']!r}, the run is in "
                    f"{compliance.get('content_mode')!r}"
                ),
            )
        )
    for item in items:
        if (
            item["source_type"] in VERBATIM_SOURCE_TYPES
            and compliance.get("content_mode") != "attributed_verbatim"
        ):
            issues.append(
                Issue(
                    rule="pack.verbatim_without_clearance",
                    severity="fatal",
                    message=(
                        f"pack carries verbatim item {item['item_id']!r} in "
                        "blueprint mode"
                    ),
                    item_id=str(item["item_id"]),
                )
            )
    return issues


# ------------------------------------------------------------- seeded defects
def _find(records: Sequence[dict[str, Any]], key: str, value: str) -> dict[str, Any]:
    for record in records:
        if str(record.get(key)) == value:
            return record
    raise KeyError(f"{key}={value!r} not found")


def apply_defect(artifact: dict[str, Any], defect: Mapping[str, Any]) -> dict[str, Any]:
    """Apply one seeded-defect patch to a deep copy of an in-memory artifact.

    Explicit operations, not a generic path patcher: a defect is a *test
    fixture*, and a typo in its operation must fail loudly instead of silently
    mutating nothing (which would make the defect prove nothing).
    """
    sample_id = str(defect.get("sample_id"))
    mutation = dict(defect["mutations"])
    operation = str(mutation.get("operation"))
    data = copy.deepcopy(artifact)

    if operation == "patch_paper":
        paper = _find(data["papers"], "paper_id", str(mutation["paper_id"]))
        paper.update(copy.deepcopy(mutation["patch"]))
    elif operation == "remove_paper":
        paper_id = str(mutation["paper_id"])
        data["papers"] = [p for p in data["papers"] if p["paper_id"] != paper_id]
        data["questions"] = [q for q in data["questions"] if q["paper_id"] != paper_id]
    elif operation == "add_paper":
        data["papers"].append(copy.deepcopy(mutation["record"]))
    elif operation == "patch_question":
        question = next(
            q
            for q in data["questions"]
            if q["paper_id"] == str(mutation["paper_id"])
            and q["question_no"] == str(mutation["question_no"])
        )
        question.update(copy.deepcopy(mutation["patch"]))
    elif operation == "add_question":
        data["questions"].append(copy.deepcopy(mutation["record"]))
    elif operation == "patch_blueprint_chapter":
        chapter = _find(data["chapters"], "chapter_id", str(mutation["chapter_id"]))
        chapter.update(copy.deepcopy(mutation["patch"]))
    elif operation == "patch_item":
        item = _find(data["items"], "item_id", str(mutation["item_id"]))
        item.update(copy.deepcopy(mutation["patch"]))
    elif operation == "remove_item":
        item_id = str(mutation["item_id"])
        data["items"] = [i for i in data["items"] if i["item_id"] != item_id]
    elif operation == "patch_series":
        series = _find(data["series"], "series_id", str(mutation["series_id"]))
        series.update(copy.deepcopy(mutation["patch"]))
    elif operation == "remove_series":
        series_id = str(mutation["series_id"])
        data["series"] = [s for s in data["series"] if s["series_id"] != series_id]
    elif operation == "drop_section":
        paper = _find(data["papers"], "paper_id", str(mutation["paper_id"]))
        section_id = str(mutation["section_id"])
        paper["sections"] = [s for s in paper["sections"] if s["id"] != section_id]
    elif operation == "drop_paper_slots":
        series = _find(data["series"], "series_id", str(mutation["series_id"]))
        paper = _find(series["papers"], "paper_id", str(mutation["paper_id"]))
        section_id = str(mutation["section_id"])
        paper["sections"] = [
            slot for slot in paper["sections"] if slot["section"] != section_id
        ]
        paper["filled_slots"] = sum(
            1 for slot in paper["sections"] if slot["item_id"] is not None
        )
        paper["item_ids"] = [
            slot["item_id"] for slot in paper["sections"] if slot["item_id"] is not None
        ]
    elif operation == "drop_series_items":
        series = _find(data["series"], "series_id", str(mutation["series_id"]))
        count = int(mutation.get("count", 1))
        series["item_ids"] = series["item_ids"][
            : max(0, len(series["item_ids"]) - count)
        ]
        for paper in series["papers"]:
            removed = 0
            kept = []
            for slot in paper["sections"]:
                if slot["item_id"] is not None and removed < count:
                    removed += 1
                    slot = {**slot, "item_id": None}
                kept.append(slot)
            paper["sections"] = kept
            paper["filled_slots"] = sum(
                1 for slot in kept if slot["item_id"] is not None
            )
            paper["item_ids"] = [
                slot["item_id"] for slot in kept if slot["item_id"] is not None
            ]
    else:  # pragma: no cover - schema rejects unknown operations first
        raise ValueError(f"{sample_id}: unknown defect operation {operation!r}")
    return data


__all__ = [
    "FORBIDDEN_TEXT_KEYS",
    "MARKS_BY_TYPE",
    "SUBJECT_BY_CLASS",
    "apply_defect",
    "check_fixture_directory",
    "validate_blueprint",
    "validate_ingest",
    "validate_item",
    "validate_pack_manifest",
    "validate_paper_document",
    "validate_papers",
    "validate_question_row",
    "validate_series_manifest",
]
