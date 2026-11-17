"""E1-ingest: turn tracked paper *metadata* fixtures into validated records.

What this stage reads is a paper's design, not its text: year, paper type, set
code, language, section structure, and one metadata row per question (number,
section, type, marks, chapter). `docs/compliance/cbse-exam-content.md` §5 lists
derived pattern metadata as reusable in blueprint mode and source text as not,
so the fixture schema simply has no field that could carry a question.

The gate is the ingest contract: a fixture that carries a text-bearing key, a
paper whose section marks do not add up, a question mapped to a chapter of the
wrong class, or a directory holding a PDF fails the stage with a stable rule id.

Output (`E1-ingest/output.json`):

    papers     one record per valid fixture (incl. its provenance + file hash)
    questions  flat metadata rows, `(paper_id, question_no)` keyed
    counts     paper/question counts by class and paper type
    gate       the ingest gate report
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .config import ExamConfig
from .errors import ExamGateError, ExamStageError
from .report import gate_report
from .syllabus import load_syllabus
from .validators import (
    check_fixture_directory,
    validate_paper_document,
    validate_papers,
)

STAGE_ID = "E1-ingest"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_fixture_documents(papers_dir: Path) -> list[tuple[Path, dict[str, Any]]]:
    if not papers_dir.is_dir():
        raise ExamStageError(f"paper fixture directory not found: {papers_dir}")
    documents: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(papers_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ExamStageError(f"{path.name} is not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise ExamStageError(f"{path.name} must contain a JSON object")
        documents.append((path, payload))
    return documents


def build_paper_record(document: dict[str, Any], file_sha256: str) -> dict[str, Any]:
    questions = list(document["questions"])
    sections = [
        {
            "id": str(section["id"]),
            "marks_each": int(section["marks_each"]),
            "question_count": int(section["question_count"]),
        }
        for section in document["sections"]
    ]
    return {
        "paper_id": str(document["paper_id"]),
        "board": str(document["board"]),
        "class_num": int(document["class_num"]),
        "subject": str(document["subject"]),
        "subject_code": document.get("subject_code"),
        "year": int(document["year"]),
        "paper_type": str(document["paper_type"]),
        "set_code": document.get("set_code"),
        "language": str(document["language"]),
        "scope": str(document["scope"]),
        "max_marks": int(document["max_marks"]),
        "scope_marks": sum(int(question["marks"]) for question in questions),
        "duration_min": int(document["duration_min"]),
        "sections": sections,
        "question_count": len(questions),
        "provenance": dict(document["provenance"]),
        "file_sha256": file_sha256,
    }


def build_question_rows(document: dict[str, Any]) -> list[dict[str, Any]]:
    paper_id = str(document["paper_id"])
    return [
        {
            "paper_id": paper_id,
            "question_no": str(question["no"]),
            "section": str(question["section"]),
            "type": str(question["type"]),
            "marks": int(question["marks"]),
            "chapter_id": str(question["chapter_id"]),
        }
        for question in document["questions"]
    ]


def run_stage(cfg: ExamConfig) -> dict[str, Any]:
    documents = load_fixture_documents(cfg.papers_dir)
    syll = load_syllabus(cfg.syllabus_path)
    chapter_index = {
        str(chapter["chapter_id"]): chapter
        for entry in syll.get("classes", [])
        for chapter in entry.get("chapters", [])
    }
    latest_year = max(
        (int(document["year"]) for _, document in documents), default=None
    )

    issues = check_fixture_directory(cfg.papers_dir)
    paper_records: list[dict[str, Any]] = []
    question_rows: list[dict[str, Any]] = []
    for path, document in documents:
        document_issues = validate_paper_document(document, file_name=path.name)
        issues.extend(document_issues)
        if any(issue.rule == "exam.paper.schema" for issue in document_issues):
            # A schema-invalid document has no reliable fields to project.
            continue
        paper_records.append(build_paper_record(document, _file_sha256(path)))
        question_rows.extend(build_question_rows(document))

    # Cross-paper rules run on the projected rows, per class, against that
    # class's chapter universe: a class-10 paper cannot cite a class-12 chapter
    # even though both are in the syllabus.
    for class_num in sorted({record["class_num"] for record in paper_records}):
        class_papers = [p for p in paper_records if p["class_num"] == class_num]
        class_paper_ids = {p["paper_id"] for p in class_papers}
        class_questions = [q for q in question_rows if q["paper_id"] in class_paper_ids]
        # The full chapter index goes in: `validate_papers` distinguishes a
        # chapter that does not exist at all from one that belongs to another
        # class, and both are fatal for different reasons.
        issues.extend(
            validate_papers(
                class_papers,
                class_questions,
                chapters=list(chapter_index.values()),
                window_years=cfg.blueprint.years_window,
                latest_year=latest_year,
            )
        )

    by_class: dict[str, int] = {}
    by_type: dict[str, int] = {}
    for record in paper_records:
        by_class[str(record["class_num"])] = (
            by_class.get(str(record["class_num"]), 0) + 1
        )
        by_type[record["paper_type"]] = by_type.get(record["paper_type"], 0) + 1

    report = gate_report(
        issues,
        counts={
            "papers": len(paper_records),
            "questions": len(question_rows),
            "fixtures": len(documents),
        },
    )
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "papers": sorted(
            paper_records, key=lambda p: (p["class_num"], p["year"], p["paper_id"])
        ),
        "questions": sorted(
            question_rows, key=lambda q: (q["paper_id"], q["question_no"])
        ),
        "counts": {
            "papers": len(paper_records),
            "questions": len(question_rows),
            "by_class": dict(sorted(by_class.items())),
            "by_paper_type": dict(sorted(by_type.items())),
        },
        "source_text_stored": False,
        "gate": report,
    }
    if report["verdict"] != "pass":
        raise ExamGateError(
            f"E1-ingest refused: {report['error_count']} blocking finding(s)",
            report=report,
            output=output,
        )
    return output


__all__ = [
    "STAGE_ID",
    "build_paper_record",
    "build_question_rows",
    "load_fixture_documents",
    "run_stage",
]
