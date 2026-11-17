"""Deterministic checkers for the exam/series cards `EV-EXM-001`, `EV-SER-001..003`.

Zero model calls. Every checker rebuilds the artifact through the real E1-E4
stage functions (`factory.exam.pipeline.assemble_class_pack`,
`factory.series.publish.assemble_pack`), so an eval cannot drift from the code
it measures. Seeded defects are patches against the shipped fixtures or the
assembled artifact, and each one must make its declared rule fire.

The volume card uses a **synthetic full-syllabus bank** (`synthetic_bank`) to
prove the gate passes when the volume is real. It is a gate fixture, not
content: ids are prefixed `q-syn-`, the bank says `generator:
synthetic_fixture`, and it is written to a temp directory that is never
published or committed.
"""

from __future__ import annotations

import dataclasses
import json
import tempfile
from pathlib import Path
from typing import Any

from factory.exam import ingest as ingest_stage
from factory.exam.config import ExamConfig
from factory.exam.notices import NOTICE_VERSION, NOTICES, scan_claims
from factory.exam.pipeline import assemble_class_pack
from factory.exam.report import report_rules
from factory.exam.schemas import EXAM_DEFECT_SAMPLE, EXAM_GOLDEN_EXPECTED
from factory.exam.syllabus import chapters_for_class, load_syllabus
from factory.exam.validators import apply_defect
from factory.series import SERIES_ORDER, minimum_volume
from factory.series.publish import assemble_pack

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord, validate_schema

CHECK_001 = "DET-EXM01-INGEST-FIDELITY"
CHECK_002 = "DET-SER01-BLUEPRINT-ALIGNMENT"
CHECK_003 = "DET-SER02-COVERAGE-VOLUME"
CHECK_004 = "DET-SER03-COPY-SOURCE-COMPLIANCE"

GOLDENS = {
    10: "evals/goldens/exam/class-10-science",
    12: "evals/goldens/exam/class-12-physics",
}

_FORBIDDEN_KEYS = {
    "text",
    "question",
    "prompt",
    "passage",
    "options",
    "answer",
    "solution",
    "marking_scheme",
}

_TYPE_CYCLE = (
    "mcq",
    "assertion_reason",
    "numeric",
    "short",
    "case_based",
    "long",
    "mcq",
    "numeric",
    "mcq",
    "short",
    "assertion_reason",
    "mcq",
)
_DIFFICULTY_CYCLE = ("easy", "medium", "hard", "hard", "medium")
_MARKS = {
    "mcq": 1,
    "assertion_reason": 1,
    "numeric": 2,
    "very_short": 2,
    "short": 3,
    "case_based": 4,
    "long": 5,
}
_VOLUME_PER_CHAPTER = {10: 70, 12: 20}


def _exam_cfg(cfg: EvalConfig) -> ExamConfig:
    return ExamConfig.for_repo(cfg.repo_root)


def _record(
    check_id: str, rule: str, message: str, severity: str = "fatal"
) -> IssueRecord:
    return IssueRecord(
        severity=severity,
        check_id=check_id,
        category="content",
        message=f"[{rule}] {message}",
    )


def _load_expected(
    cfg: EvalConfig, golden_rel: str, check_id: str, context: dict[str, Any]
) -> dict[str, Any] | None:
    path = cfg.repo_root / golden_rel / "expected.json"
    if not path.is_file():
        context.setdefault("skipped_checks", {})[check_id] = (
            f"missing exam golden {path}"
        )
        return None
    expected = json.loads(path.read_text(encoding="utf-8"))
    validate_schema(expected, EXAM_GOLDEN_EXPECTED, f"{golden_rel}/expected.json")
    return expected


def _load_defect(cfg: EvalConfig, sample_id: str, check_id: str) -> dict[str, Any]:
    path = cfg.goldens_dir / "exam" / "defects" / f"{sample_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"seeded defect {sample_id} missing at {path}")
    defect = json.loads(path.read_text(encoding="utf-8"))
    validate_schema(defect, EXAM_DEFECT_SAMPLE, sample_id)
    return defect


# --------------------------------------------------------------- EV-EXM-001
def apply_document_defect(
    document: dict[str, Any], defect: dict[str, Any]
) -> dict[str, Any]:
    """Patch a paper *fixture document* for the ingest-fidelity defects."""
    import copy

    data = copy.deepcopy(document)
    mutation = dict(defect["mutations"])
    operation = str(mutation["operation"])
    if operation == "patch_paper":
        data.update(copy.deepcopy(mutation["patch"]))
    elif operation == "patch_question":
        question = next(
            q for q in data["questions"] if q["no"] == str(mutation["question_no"])
        )
        question.update(copy.deepcopy(mutation["patch"]))
    elif operation == "set_question_key":
        question = next(
            q for q in data["questions"] if q["no"] == str(mutation["question_no"])
        )
        question[str(mutation["key"])] = copy.deepcopy(mutation["value"])
    elif operation == "set_section_count":
        section = next(
            s for s in data["sections"] if s["id"] == str(mutation["section_id"])
        )
        section["question_count"] = int(mutation["value"])
    else:  # pragma: no cover - schema rejects unknown ops first
        raise ValueError(
            f"{defect['sample_id']}: unknown document operation {operation!r}"
        )
    return data


def check_ingest_fidelity(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    exam_cfg = _exam_cfg(cfg)
    ingest = ingest_stage.run_stage(exam_cfg)
    for class_num, golden_rel in GOLDENS.items():
        expected = _load_expected(cfg, golden_rel, CHECK_001, context)
        if expected is None:
            continue
        papers = [p for p in ingest["papers"] if int(p["class_num"]) == class_num]
        questions = [
            q
            for q in ingest["questions"]
            if q["paper_id"] in {p["paper_id"] for p in papers}
        ]
        if len(papers) < int(expected["papers"]["min"]):
            issues.append(
                _record(
                    CHECK_001,
                    "exam.paper.missing",
                    f"class {class_num}: {len(papers)} papers, golden expects at "
                    f"least {expected['papers']['min']}",
                )
            )
        by_type: dict[str, int] = {}
        for paper in papers:
            by_type[paper["paper_type"]] = by_type.get(paper["paper_type"], 0) + 1
        if by_type != expected["papers"]["by_type"]:
            issues.append(
                _record(
                    CHECK_001,
                    "exam.paper.missing",
                    f"class {class_num}: paper types {by_type} != golden "
                    f"{expected['papers']['by_type']}",
                )
            )
        if not questions:
            issues.append(
                _record(
                    CHECK_001,
                    "exam.paper.missing",
                    f"class {class_num}: no question rows",
                )
            )
        for paper in papers:
            paper_questions = [
                q for q in questions if q["paper_id"] == paper["paper_id"]
            ]
            marks = sum(int(q["marks"]) for q in paper_questions)
            if marks != int(paper["scope_marks"]):
                issues.append(
                    _record(
                        CHECK_001,
                        "exam.paper.marks_sum",
                        f"{paper['paper_id']}: scope_marks {paper['scope_marks']} != "
                        f"recomputed {marks}",
                    )
                )
            if len(paper_questions) != int(paper["question_count"]):
                issues.append(
                    _record(
                        CHECK_001,
                        "exam.paper.question_count",
                        f"{paper['paper_id']}: question rows disagree with the record",
                    )
                )
            for section in paper["sections"]:
                in_section = [
                    q for q in paper_questions if q["section"] == section["id"]
                ]
                if len(in_section) != int(section["question_count"]):
                    issues.append(
                        _record(
                            CHECK_001,
                            "exam.paper.sections",
                            f"{paper['paper_id']}/{section['id']}: "
                            f"{len(in_section)} rows vs {section['question_count']}",
                        )
                    )
            provenance = paper.get("provenance") or {}
            for field in ("basis", "source_url", "retrieved_at", "verified"):
                if field not in provenance:
                    issues.append(
                        _record(
                            CHECK_001,
                            "exam.paper.provenance",
                            f"{paper['paper_id']}: provenance lacks {field}",
                        )
                    )
            for key in _FORBIDDEN_KEYS & set(paper):
                issues.append(
                    _record(
                        CHECK_001,
                        "exam.paper.source_text",
                        f"{paper['paper_id']}: text-bearing key {key!r}",
                    )
                )
            for question in paper_questions:
                for key in _FORBIDDEN_KEYS & set(question):
                    issues.append(
                        _record(
                            CHECK_001,
                            "exam.paper.source_text",
                            f"{paper['paper_id']}#{question['question_no']}: key {key!r}",
                        )
                    )
        # Seeded defects: each must make its declared rule fire.
        for sample_id in card.golden_inputs.get("seeded_defects", []):
            defect = _load_defect(cfg, sample_id, CHECK_001)
            paper_path = (
                exam_cfg.papers_dir / f"{defect['mutations'].get('paper_id')}.json"
            )
            if not paper_path.is_file():
                issues.append(
                    _record(
                        CHECK_001,
                        "exam.defect.fixture",
                        f"{sample_id}: base fixture {paper_path.name} missing",
                    )
                )
                continue
            document = json.loads(paper_path.read_text(encoding="utf-8"))
            mutated = apply_document_defect(document, defect)
            with tempfile.TemporaryDirectory() as tmp:
                tmpdir = Path(tmp)
                for source in sorted(exam_cfg.papers_dir.glob("*.json")):
                    (tmpdir / source.name).write_text(
                        source.read_text(encoding="utf-8"), encoding="utf-8"
                    )
                (tmpdir / f"{mutated['paper_id']}.json").write_text(
                    json.dumps(mutated), encoding="utf-8"
                )
                defect_cfg = dataclasses.replace(exam_cfg, papers_dir=tmpdir)
                try:
                    ingest_stage.run_stage(defect_cfg)
                except Exception as exc:  # noqa: BLE001 - the gate is the assertion
                    report = getattr(exc, "report", {})
                    fired = report_rules(report)
                    if defect["expected_rule"] not in fired:
                        issues.append(
                            _record(
                                CHECK_001,
                                "exam.defect.unfired",
                                f"{sample_id}: expected {defect['expected_rule']} to "
                                f"fire; got {sorted(fired)}",
                            )
                        )
                else:
                    issues.append(
                        _record(
                            CHECK_001,
                            "exam.defect.unfired",
                            f"{sample_id}: the ingest gate accepted the seeded defect",
                        )
                    )
    return issues


# --------------------------------------------------------------- EV-SER-001
def check_blueprint_alignment(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    exam_cfg = _exam_cfg(cfg)
    syllabus = load_syllabus(exam_cfg.syllabus_path)
    for class_num, golden_rel in GOLDENS.items():
        expected = _load_expected(cfg, golden_rel, CHECK_002, context)
        if expected is None:
            continue
        pack = assemble_class_pack(exam_cfg, class_num)
        blueprint = pack["blueprint"]
        ingest = pack["ingest"]
        chapters = chapters_for_class(syllabus, class_num)
        chapter_golden = expected["blueprint"]["chapter_ids"]
        built = [row["chapter_id"] for row in blueprint["chapters"]]
        if built != [chapter["chapter_id"] for chapter in chapters]:
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.syllabus_order",
                    f"class {class_num}: blueprint chapters do not follow the syllabus",
                )
            )
        if set(chapter_golden) - set(built):
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.chapter_unknown",
                    f"class {class_num}: golden chapters missing {sorted(set(chapter_golden) - set(built))}",
                )
            )
        share_sum = sum(float(row["share"]) for row in blueprint["chapters"])
        if abs(share_sum - 1.0) > 1e-6:
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.share_sum",
                    f"class {class_num}: shares sum to {share_sum}",
                )
            )
        # Recompute the weighted marks from the raw inputs (no trust in E2).
        weights = {int(y): float(w) for y, w in blueprint["recency"]["weights"].items()}
        paper_year = {
            paper["paper_id"]: int(paper["year"])
            for paper in ingest["papers"]
            if paper["paper_id"] in set(blueprint["papers_used"])
        }
        recomputed: dict[str, float] = {
            row["chapter_id"]: 0.0 for row in blueprint["chapters"]
        }
        for question in ingest["questions"]:
            if question["paper_id"] not in paper_year:
                continue
            recomputed[question["chapter_id"]] += (
                question["marks"] * weights[paper_year[question["paper_id"]]]
            )
        for row in blueprint["chapters"]:
            if (
                abs(row["weighted_marks"] - round(recomputed[row["chapter_id"]], 3))
                > 0.001
            ):
                issues.append(
                    _record(
                        CHECK_002,
                        "blueprint.weighted_marks",
                        f"{row['chapter_id']}: {row['weighted_marks']} != recomputed "
                        f"{round(recomputed[row['chapter_id']], 3)}",
                    )
                )
        template = blueprint["section_template"]
        if [row["id"] for row in template] != expected["blueprint"]["section_ids"]:
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.section_template",
                    f"class {class_num}: sections {[r['id'] for r in template]}",
                )
            )
        if sum(int(row["marks_total"]) for row in template) != int(
            expected["blueprint"]["scope_marks"]
        ):
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.section_template",
                    f"class {class_num}: template marks do not match the golden",
                )
            )
        type_counts = {
            row["type"]: float(row["weighted_marks"]) for row in blueprint["type_mix"]
        }
        for question_type, minimum in expected["blueprint"]["type_counts_min"].items():
            if type_counts.get(question_type, 0.0) < float(minimum):
                issues.append(
                    _record(
                        CHECK_002,
                        "blueprint.type_mix",
                        f"class {class_num}: {question_type} weight "
                        f"{type_counts.get(question_type, 0.0)} < {minimum}",
                    )
                )
        if blueprint["confidence"]["question_map_basis"] != "authored_estimate":
            issues.append(
                _record(
                    CHECK_002,
                    "blueprint.confidence",
                    "the fixture map is authored; confidence must say so",
                )
            )
        # Seeded defect: a tampered share must be refused by the gate.
        for sample_id in card.golden_inputs.get("seeded_defects", []):
            defect = _load_defect(cfg, sample_id, CHECK_002)
            target = defect["mutations"].get("chapter_id")
            if target and target not in {
                row["chapter_id"] for row in blueprint["chapters"]
            }:
                continue  # this defect targets the other class's golden
            broken = apply_defect(blueprint, defect)
            from factory.exam.validators import validate_blueprint

            fired = {
                issue.rule
                for issue in validate_blueprint(
                    broken,
                    chapters=chapters,
                    papers=[
                        paper
                        for paper in ingest["papers"]
                        if paper["paper_id"] in set(blueprint["papers_used"])
                    ],
                )
            }
            if defect["expected_rule"] not in fired:
                issues.append(
                    _record(
                        CHECK_002,
                        "exam.defect.unfired",
                        f"{sample_id}: expected {defect['expected_rule']}, got {sorted(fired)}",
                    )
                )
    return issues


# --------------------------------------------------------------- EV-SER-002
def synthetic_bank(chapter: dict[str, Any], per_chapter: int) -> dict[str, Any]:
    """A P2-shaped bank for one chapter, deterministic and clearly synthetic."""
    concepts = [concept["concept_id"] for concept in chapter.get("concepts", [])]
    if not concepts:
        concepts = [f"{chapter['chapter_id']}-uncurated"]
    items: list[dict[str, Any]] = []
    for index in range(per_chapter):
        item_type = _TYPE_CYCLE[index % len(_TYPE_CYCLE)]
        difficulty = _DIFFICULTY_CYCLE[index % len(_DIFFICULTY_CYCLE)]
        marks = _MARKS[item_type]
        options = [f"Option {label} {index}" for label in "ABCD"]
        locales: dict[str, Any] = {}
        for language in ("en", "hi", "hi-Latn"):
            prompt = {
                "en": f"Synthetic item {index + 1} for {chapter['title']}.",
                "hi": f"संश्लेषित प्रश्न {index + 1}: {chapter['title']}।",
                "hi-Latn": f"Synthetic sawaal {index + 1}: {chapter['title']}.",
            }[language]
            locale: dict[str, Any] = {
                "prompt": prompt,
                "explanation": f"Explanation for synthetic item {index + 1}.",
            }
            if item_type in ("mcq", "assertion_reason"):
                locale["options"] = options
            if item_type in ("short", "case_based", "long"):
                locale["model_answer"] = (
                    f"Model answer {index + 1}."
                    if language != "hi"
                    else f"प्रश्न {index + 1} का आदर्श उत्तर।"
                )
            locales[language] = locale
        if item_type in ("mcq", "assertion_reason"):
            answer: dict[str, Any] = {"index": index % 4}
        elif item_type == "numeric":
            answer = {"value": float(index + 1), "tolerance": 0.1, "unit": "m"}
        else:
            answer = {"kind": "open"}
        items.append(
            {
                "item_id": f"q-syn-{chapter['chapter_id']}-{index + 1:03d}",
                "concept_id": concepts[index % len(concepts)],
                "type": item_type,
                "difficulty": difficulty,
                "marks": marks,
                "computation_steps": 0,
                "source_ref": {"book_id": "synthetic", "section": "1.0"},
                "answer": answer,
                "distractor_index": 1
                if item_type in ("mcq", "assertion_reason")
                else None,
                "locales": locales,
            }
        )
    return {
        "schema_version": 1,
        "chapter_id": chapter["chapter_id"],
        "class": chapter["class"],
        "generator": "synthetic_fixture",
        "source": {
            "book_id": "synthetic",
            "chapter_number": chapter["number"],
            "chapter_title": chapter["title"],
            "source_type": "synthetic",
            "note": "Volume-gate fixture only: not publishable content.",
        },
        "items": items,
    }


def write_synthetic_banks(
    chapters_dir: Path, chapters: list[dict[str, Any]], per_chapter: int
) -> None:
    chapters_dir.mkdir(parents=True, exist_ok=True)
    for chapter in chapters:
        (chapters_dir / f"{chapter['chapter_id']}.items.json").write_text(
            json.dumps(synthetic_bank(chapter, per_chapter), indent=2) + "\n",
            encoding="utf-8",
        )


def _full_syllabus_pack(
    cfg: EvalConfig, class_num: int, per_chapter: int
) -> dict[str, Any]:
    exam_cfg = _exam_cfg(cfg)
    syllabus = load_syllabus(exam_cfg.syllabus_path)
    chapters = chapters_for_class(syllabus, class_num)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        banks = root / "chapters"
        write_synthetic_banks(banks, chapters, per_chapter)
        fixture_cfg = dataclasses.replace(
            exam_cfg, chapters_dir=banks, runs_dir=root / "runs"
        )
        ingest = ingest_stage.run_stage(fixture_cfg)
        from factory.exam.blueprint import build_blueprint
        from factory.series.assembly import assemble_class

        blueprint = build_blueprint(
            ingest, class_num=class_num, chapters=chapters, policy=fixture_cfg.blueprint
        )
        series = assemble_class(
            fixture_cfg,
            blueprint=blueprint,
            ingest=ingest,
            chapters=chapters,
            generated_at="2026-11-17T00:00:00+00:00",
        )
        return assemble_pack(
            cfg=fixture_cfg,
            blueprint=blueprint,
            ingest=ingest,
            class_series=series,
            chapters=chapters,
            run_id=f"eval-exam-class-{class_num}",
            generated_at="2026-11-17T00:00:00+00:00",
        )


def check_series_coverage_volume(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    exam_cfg = _exam_cfg(cfg)
    syllabus = load_syllabus(exam_cfg.syllabus_path)
    for class_num, golden_rel in GOLDENS.items():
        expected = _load_expected(cfg, golden_rel, CHECK_003, context)
        if expected is None:
            continue
        pack = assemble_class_pack(exam_cfg, class_num)
        chapters = chapters_for_class(syllabus, class_num)
        series = pack["series"]
        manifest = pack["pack"]["manifest"]
        series_expected = expected["series"]
        if [s["series_id"] for s in series["series"]] != list(SERIES_ORDER):
            issues.append(
                _record(
                    CHECK_003,
                    "series.order",
                    f"class {class_num}: series set is not the six approved ids",
                )
            )
        # The pipeline's minimums must equal the approved volume table.
        for series_id, minimum in series_expected["expected_minimums"].items():
            actual = minimum_volume(class_num, series_id)
            if {k: int(v) for k, v in minimum.items()} != actual:
                issues.append(
                    _record(
                        CHECK_003,
                        "series.minimum.table",
                        f"class {class_num}/{series_id}: pipeline minimum {actual} != "
                        f"approved {minimum}",
                    )
                )
        # The shipped prototype must be blocked, with the expected gaps named.
        if manifest["publish"]["status"] != "blocked":
            issues.append(
                _record(
                    CHECK_003,
                    "series.minimum",
                    f"class {class_num}: the shipped prototype claims to be "
                    "publishable; the volume gate is not doing its job",
                )
            )
        blockers = manifest["publish"]["blockers"]
        floors = {
            blocker.get("chapter_id")
            for blocker in blockers
            if blocker["rule"] == "series.chapter_floor"
        }
        expected_floors = set(
            series_expected.get("expected_gaps", {}).get("chapter_floor", [])
        )
        if floors != expected_floors:
            issues.append(
                _record(
                    CHECK_003,
                    "series.chapter_floor",
                    f"class {class_num}: chapter-floor gaps {sorted(floors)} != golden "
                    f"{sorted(expected_floors)}",
                )
            )
        minimum_rules = {
            b["rule"] for b in blockers if b["rule"].startswith("series.minimum.")
        }
        expected_minimum_rules = {
            f"series.minimum.{series_id}"
            for series_id in series_expected["expected_gaps"].get("below_minimum", [])
        }
        if not expected_minimum_rules <= minimum_rules:
            issues.append(
                _record(
                    CHECK_003,
                    "series.minimum",
                    f"class {class_num}: missing minimum findings "
                    f"{sorted(expected_minimum_rules - minimum_rules)}",
                )
            )
        for series_id in series_expected.get("dark", []):
            dark = next(s for s in series["series"] if s["series_id"] == series_id)
            if dark["status"] != "disabled" or dark["item_ids"]:
                issues.append(
                    _record(
                        CHECK_003,
                        "series.status.exact_pyq",
                        f"class {class_num}: {series_id} must be dark with no items",
                    )
                )
        # The full-syllabus fixture must pass the same gate.
        if class_num in _VOLUME_PER_CHAPTER:
            full = _full_syllabus_pack(cfg, class_num, _VOLUME_PER_CHAPTER[class_num])
            if full["manifest"]["publish"]["status"] != "ready":
                example = full["manifest"]["publish"]["blockers"][:3]
                issues.append(
                    _record(
                        CHECK_003,
                        "series.minimum",
                        f"class {class_num}: the full-syllabus fixture is not "
                        f"publishable: {[b['rule'] for b in example]}",
                    )
                )
            # "5 full papers" must be five different papers: a repeated
            # complete paper is one paper counted twice, not volume.
            for manifest_row in full["payloads"]["series.json"]["series"]:
                complete_sets: dict[tuple[str, ...], str] = {}
                for paper in manifest_row["papers"]:
                    if paper["filled_slots"] != paper["total_slots"]:
                        continue
                    key = tuple(sorted(str(item_id) for item_id in paper["item_ids"]))
                    if key in complete_sets:
                        issues.append(
                            _record(
                                CHECK_003,
                                "series.paper_duplicate",
                                f"class {class_num}/{manifest_row['series_id']}: "
                                f"{paper['paper_id']} repeats every item of "
                                f"{complete_sets[key]}",
                            )
                        )
                    complete_sets[key] = str(paper["paper_id"])
        # Seeded defects: volume shortfall and a structure break must block.
        for sample_id in card.golden_inputs.get("seeded_defects", []):
            if class_num != 10:
                continue
            defect = _load_defect(cfg, sample_id, CHECK_003)
            mutated = apply_defect(series, defect)
            broken_pack = assemble_pack(
                cfg=exam_cfg,
                blueprint=pack["blueprint"],
                ingest=pack["ingest"],
                class_series=mutated,
                chapters=chapters,
                run_id=f"eval-defect-{class_num}",
                generated_at="2026-11-17T00:00:00+00:00",
            )
            fired = {b["rule"] for b in broken_pack["manifest"]["publish"]["blockers"]}
            if defect["expected_rule"] not in fired:
                issues.append(
                    _record(
                        CHECK_003,
                        "exam.defect.unfired",
                        f"{sample_id}: expected {defect['expected_rule']} in publish "
                        f"blockers",
                    )
                )
    return issues


# --------------------------------------------------------------- EV-SER-003
def _notices_match_doc(cfg: EvalConfig) -> list[str]:
    import re

    path = cfg.repo_root / "docs" / "compliance" / "notices.md"
    if not path.is_file():
        return [f"notices.md missing at {path}"]
    blocks = re.findall(
        r"```text\n(.*?)\n```", path.read_text(encoding="utf-8"), re.DOTALL
    )
    ids = ["N-01", "N-02", "N-03", "N-04", "N-05"]
    mismatches: list[str] = []
    for index, notice_id in enumerate(ids):
        for offset, language in ((0, "en"), (1, "hi")):
            if NOTICES[notice_id][language] != blocks[index * 2 + offset]:
                mismatches.append(f"{notice_id}/{language}")
    return mismatches


def check_series_copy_compliance(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    exam_cfg = _exam_cfg(cfg)
    for mismatch in _notices_match_doc(cfg):
        issues.append(
            _record(
                CHECK_004,
                "series.copy.notice",
                f"approved notice text drifted from docs/compliance/notices.md: {mismatch}",
            )
        )
    for class_num, golden_rel in GOLDENS.items():
        expected = _load_expected(cfg, golden_rel, CHECK_004, context)
        if expected is None:
            continue
        pack = assemble_class_pack(exam_cfg, class_num)
        manifest = pack["pack"]["manifest"]
        rows = pack["pack"]["payloads"]["items.json"]["items"]
        series = pack["series"]
        if manifest["notice_version"] != NOTICE_VERSION:
            issues.append(
                _record(
                    CHECK_004,
                    "series.copy.notice",
                    f"class {class_num}: manifest notice version "
                    f"{manifest['notice_version']} != {NOTICE_VERSION}",
                )
            )
        if manifest["content_mode"] != "blueprint_only":
            issues.append(
                _record(
                    CHECK_004,
                    "pack.mode_mismatch",
                    f"class {class_num}: content mode {manifest['content_mode']!r}",
                )
            )
        compliance = manifest["compliance"]
        if compliance["verbatim_items"] or compliance["verbatim_allowed"]:
            issues.append(
                _record(
                    CHECK_004,
                    "series.item.verbatim_in_blueprint",
                    f"class {class_num}: verbatim content in blueprint mode",
                )
            )
        if compliance["third_party_items"]:
            issues.append(
                _record(
                    CHECK_004,
                    "series.item.third_party",
                    f"class {class_num}: third-party items in the pack",
                )
            )
        exact = next(s for s in series["series"] if s["series_id"] == "exact_pyq")
        if expected["series"].get("dark") and exact["status"] != "disabled":
            issues.append(
                _record(
                    CHECK_004,
                    "series.status.exact_pyq",
                    f"class {class_num}: the exact-PYQ series is not dark",
                )
            )
        for item in series["items"]:
            if item["source_type"] in (
                "verbatim_cbse_paper",
                "verbatim_cbse_sqp",
                "verbatim_cbse_ms",
            ):
                issues.append(
                    _record(
                        CHECK_004,
                        "series.item.verbatim_in_blueprint",
                        f"{item['item_id']}: verbatim source type in blueprint mode",
                    )
                )
            if not item.get("pattern_ref"):
                issues.append(
                    _record(
                        CHECK_004,
                        "series.item.pattern_ref",
                        f"{item['item_id']}: no pattern reference",
                    )
                )
            if not item.get("similarity"):
                issues.append(
                    _record(
                        CHECK_004,
                        "series.item.similarity_missing",
                        f"{item['item_id']}: no similarity record",
                    )
                )
            for finding in scan_claims(
                " ".join(
                    str(locale.get("prompt") or "")
                    for locale in item["locales"].values()
                )
            ):
                issues.append(
                    _record(
                        CHECK_004,
                        "series.copy.claim",
                        f"{item['item_id']}: forbidden claim {finding['phrase']!r}",
                    )
                )
        for manifest_row in series["series"]:
            for field in ("label", "purpose", "copy"):
                for finding in scan_claims(str(manifest_row.get(field) or "")):
                    issues.append(
                        _record(
                            CHECK_004,
                            "series.copy.claim",
                            f"{manifest_row['series_id']}.{field}: {finding['phrase']!r}",
                        )
                    )
            if manifest_row["enabled"] and manifest_row["notice_id"] not in (
                "N-01",
                "N-03",
            ):
                issues.append(
                    _record(
                        CHECK_004,
                        "series.copy.notice",
                        f"{manifest_row['series_id']}: enabled series without a notice",
                    )
                )
        # Rows must resolve their language per series policy.
        policies = {s["series_id"]: set(s["language_policy"]) for s in series["series"]}
        for row in rows:
            for series_id in row["series_ids"]:
                if row["language"] not in policies[series_id]:
                    issues.append(
                        _record(
                            CHECK_004,
                            "series.row.language",
                            f"{row['question_id']}: {row['language']} not offered by "
                            f"{series_id}",
                        )
                    )
        # Seeded defects: a claim, a flipped dark series, a verbatim item.
        for sample_id in card.golden_inputs.get("seeded_defects", []):
            if class_num != 10:
                continue
            defect = _load_defect(cfg, sample_id, CHECK_004)
            mutated = apply_defect(series, defect)
            broken = assemble_pack(
                cfg=exam_cfg,
                blueprint=pack["blueprint"],
                ingest=pack["ingest"],
                class_series=mutated,
                chapters=chapters_for_class(
                    load_syllabus(exam_cfg.syllabus_path), class_num
                ),
                run_id=f"eval-copy-defect-{class_num}",
                generated_at="2026-11-17T00:00:00+00:00",
            )
            fired = {b["rule"] for b in broken["manifest"]["publish"]["blockers"]}
            if defect["expected_rule"] not in fired:
                issues.append(
                    _record(
                        CHECK_004,
                        "exam.defect.unfired",
                        f"{sample_id}: expected {defect['expected_rule']} in publish "
                        f"blockers; got {sorted(fired)}",
                    )
                )
    return issues


__all__ = [
    "CHECK_001",
    "CHECK_002",
    "CHECK_003",
    "CHECK_004",
    "apply_document_defect",
    "check_blueprint_alignment",
    "check_ingest_fidelity",
    "check_series_copy_compliance",
    "check_series_coverage_volume",
    "synthetic_bank",
    "write_synthetic_banks",
]
