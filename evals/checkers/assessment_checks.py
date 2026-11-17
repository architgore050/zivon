"""Deterministic checkers for the assessment cards `EV-ASM-001`..`EV-ASM-004`.

Zero model calls. Each checker rebuilds the chapter pack from the tracked seed
data through `factory.assessment.pipeline.assemble_chapter_pack` - the same
A1-A6 stage functions the real entrypoint runs - and grades the exported rows,
so an eval cannot drift from the pipeline it claims to measure. Seeded defects
are applied as patches to the shipped bank (never a second hand-written bank),
and each one must make its declared rule fire.
"""

from __future__ import annotations

import json
from statistics import median
from typing import Any

from factory.assessment.config import AssessmentConfig, catalog_book_ids
from factory.assessment.errors import AssessmentError
from factory.assessment.pipeline import assemble_chapter_pack
from factory.assessment.schemas import (
    ASSESSMENT_GOLDEN_EXPECTED,
    ASSESSMENT_QUESTIONS,
    ASSESSMENT_SPEAKING_ROWS,
)
from factory.assessment.validators import (
    Issue,
    apply_defect_mutations,
    apply_prior_defect,
    validate_item_bank,
    validate_syllabus,
    validate_time_priors,
)

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord, validate_schema

CHECK_001 = "DET-ASM01-PACK-INTEGRITY"
CHECK_002 = "DET-ASM02-COVERAGE"
CHECK_003 = "DET-ASM03-TIME-PRIORS"
CHECK_004 = "DET-ASM04-LANGUAGES"

_REQUIRED_ROW_FIELDS = (
    "question_id",
    "base_item_id",
    "class_level",
    "chapter_id",
    "concept_id",
    "type",
    "difficulty",
    "marks",
    "language",
    "source_type",
    "source_ref",
    "prompt",
    "answer",
    "explanation",
    "expected_time_ms",
    "status",
    "review_mode",
    "version",
    "generator",
    "run_id",
)


def _assessment_cfg(cfg: EvalConfig) -> AssessmentConfig:
    return AssessmentConfig.for_repo(cfg.repo_root)


def _load_expected(
    cfg: EvalConfig, golden_rel: str, check_id: str, context: dict[str, Any]
) -> dict[str, Any] | None:
    expected_path = cfg.repo_root / golden_rel / "expected.json"
    if not expected_path.is_file():
        skipped = context.setdefault("skipped_checks", {})
        skipped[check_id] = f"missing assessment golden {expected_path}"
        return None
    expected = json.loads(expected_path.read_text(encoding="utf-8"))
    validate_schema(expected, ASSESSMENT_GOLDEN_EXPECTED, f"{golden_rel}/expected.json")
    return expected


def _assemble(
    cfg: EvalConfig, expected: dict[str, Any], check_id: str
) -> tuple[dict[str, Any] | None, list[IssueRecord]]:
    try:
        result = assemble_chapter_pack(_assessment_cfg(cfg), expected["chapter_id"])
    except AssessmentError as exc:
        return None, [
            IssueRecord(
                severity="fatal",
                check_id=check_id,
                category="content",
                message=f"{expected['chapter_id']}: the assessment pipeline cannot "
                f"produce a pack: {exc}",
            )
        ]
    return result, []


def _seeded_defect(
    cfg: EvalConfig, defect_id: str, check_id: str
) -> tuple[dict[str, Any] | None, IssueRecord | None]:
    path = cfg.goldens_dir / "assessment" / "defects" / f"{defect_id}.json"
    if not path.is_file():
        return None, IssueRecord(
            severity="fatal",
            check_id=check_id,
            category="content",
            message=f"seeded defect {defect_id} is registered but {path} does not exist",
        )
    return json.loads(path.read_text(encoding="utf-8")), None


def _issues_to_records(
    issues: list[Issue], check_id: str, *, prefix: str
) -> list[IssueRecord]:
    out: list[IssueRecord] = []
    for issue in issues:
        if issue.severity not in ("fatal", "major"):
            continue
        out.append(
            IssueRecord(
                severity=issue.severity,
                check_id=check_id,
                category="content",
                block_id=issue.item_id,
                message=f"{prefix}: [{issue.rule}] {issue.message}",
            )
        )
    return out


# ------------------------------------------------------------------ EV-ASM-001
def check_practice_pack_integrity(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-ASM01-PACK-INTEGRITY`: schema, one correct answer, explanation,
    source, concept, uniqueness and the exported-row contract."""
    issues: list[IssueRecord] = []
    book_ids = catalog_book_ids(cfg.repo_root / "sources" / "catalog.json")
    for golden_rel in card.golden_inputs.get("topics", []):
        expected = _load_expected(cfg, golden_rel, CHECK_001, context)
        if expected is None:
            continue
        result, assemble_issues = _assemble(cfg, expected, CHECK_001)
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        items_output = result["items"]
        questions = result["assembled"]["payloads"]["questions.json"]
        try:
            validate_schema(questions, ASSESSMENT_QUESTIONS, "questions.json")
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_001,
                    category="content",
                    message=f"{chapter['chapter_id']}: questions.json schema: {exc}",
                )
            )
            continue

        rows = questions["questions"]
        ids = [row["question_id"] for row in rows]
        if len(ids) != len(set(ids)):
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_001,
                    category="content",
                    message=f"{chapter['chapter_id']}: duplicate question_id in the export",
                )
            )
        by_base: dict[str, set[str]] = {}
        for row in rows:
            for field in _REQUIRED_ROW_FIELDS:
                if field not in row:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_001,
                            category="content",
                            message=f"{row.get('question_id', '?')}: export row is missing '{field}'",
                        )
                    )
            by_base.setdefault(row["base_item_id"], set()).add(row["language"])
            source = row.get("source_ref") or {}
            if not source.get("book_id") or not source.get("section"):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_001,
                        category="fact",
                        message=f"{row['question_id']}: every row needs a source book and section",
                    )
                )
            elif source["book_id"] not in book_ids:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_001,
                        category="fact",
                        message=f"{row['question_id']}: source {source['book_id']!r} is not in "
                        "sources/catalog.json",
                    )
                )
            elif not source["section"].startswith(f"{chapter['number']}."):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_001,
                        category="fact",
                        message=f"{row['question_id']}: source section "
                        f"{source['section']!r} is outside chapter {chapter['number']}",
                    )
                )
            if row["type"] == "numeric":
                answer = row.get("answer") or {}
                if "value" not in answer or "unit" not in answer:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_001,
                            category="content",
                            message=f"{row['question_id']}: numeric answer needs value + unit",
                        )
                    )
                if row.get("options"):
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_001,
                            category="content",
                            message=f"{row['question_id']}: numeric row carries options",
                        )
                    )
            else:
                options = row.get("options") or []
                answer = row.get("answer") or {}
                if len(options) != 4:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_001,
                            category="content",
                            message=f"{row['question_id']}: expected 4 options, got {len(options)}",
                        )
                    )
                if not isinstance(answer.get("index"), int) or not 0 <= answer[
                    "index"
                ] < len(options):
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id=CHECK_001,
                            category="answer_key",
                            message=f"{row['question_id']}: answer index outside the options",
                        )
                    )
            if not str(row.get("explanation", "")).strip():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_001,
                        category="content",
                        message=f"{row['question_id']}: explanation is empty",
                    )
                )
        for base_id, languages in by_base.items():
            if languages != {"en", "hi", "hi-Latn"}:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_001,
                        category="content",
                        message=f"{base_id}: language rows {sorted(languages)} != "
                        "['en', 'hi', 'hi-Latn']",
                    )
                )

        # The same gate the pipeline runs, asserted over the shipped bank.
        shipped_bank = {
            "schema_version": 1,
            "chapter_id": chapter["chapter_id"],
            "class": chapter["class"],
            "generator": items_output["generator"],
            "source": items_output["source"],
            "items": items_output["items"],
        }
        issues.extend(
            _issues_to_records(
                validate_item_bank(
                    shipped_bank,
                    chapter,
                    _assessment_cfg(cfg).policy,
                    catalog_book_ids=book_ids,
                ),
                CHECK_001,
                prefix=chapter["chapter_id"],
            )
        )

    # Seeded defects: each must make its declared rule fire.
    for defect_id in card.golden_inputs.get("seeded_defects", []):
        defect, defect_issue = _seeded_defect(cfg, defect_id, CHECK_001)
        if defect_issue is not None:
            issues.append(defect_issue)
            continue
        assert defect is not None
        result, assemble_issues = _assemble(
            cfg,
            {
                "chapter_id": defect["chapter_id"],
                "golden_id": "GA-00",
            },
            CHECK_001,
        )
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        bank = {
            "schema_version": 1,
            "chapter_id": chapter["chapter_id"],
            "class": chapter["class"],
            "generator": "eval-defect",
            "source": result["items"]["source"],
            "items": result["items"]["items"],
        }
        mutated = apply_defect_mutations(bank, defect)
        found = validate_item_bank(
            mutated,
            chapter,
            _assessment_cfg(cfg).policy,
            catalog_book_ids=catalog_book_ids(
                cfg.repo_root / "sources" / "catalog.json"
            ),
        )
        rules = {issue.rule for issue in found if issue.severity in ("fatal", "major")}
        if defect["expected_rule"] not in rules:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_001,
                    category="content",
                    message=f"{defect_id}: expected rule {defect['expected_rule']!r} to fire; "
                    f"fired {sorted(rules)}",
                )
            )
    return issues


# ------------------------------------------------------------------ EV-ASM-002
def check_chapter_concept_coverage(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-ASM02-COVERAGE`: four-class syllabus integrity, every concept
    practised, and every published lesson block tagged when a lesson exists."""
    issues: list[IssueRecord] = []
    asm_cfg = _assessment_cfg(cfg)
    try:
        syllabus = json.loads(asm_cfg.syllabus_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [
            IssueRecord(
                severity="fatal",
                check_id=CHECK_002,
                category="content",
                message=f"syllabus not readable at {asm_cfg.syllabus_path}: {exc}",
            )
        ]
    issues.extend(
        _issues_to_records(
            validate_syllabus(
                syllabus,
                catalog_book_ids=catalog_book_ids(asm_cfg.catalog_path),
            ),
            CHECK_002,
            prefix="syllabus",
        )
    )

    for golden_rel in card.golden_inputs.get("topics", []):
        expected = _load_expected(cfg, golden_rel, CHECK_002, context)
        if expected is None:
            continue
        result, assemble_issues = _assemble(cfg, expected, CHECK_002)
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        graph = result["graph"]
        concepts = [c["concept_id"] for c in chapter["concepts"]]
        if len(concepts) < expected["concepts_min"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_002,
                    category="content",
                    message=f"{chapter['chapter_id']}: {len(concepts)} concepts, golden "
                    f"requires at least {expected['concepts_min']}",
                )
            )
        coverage = result["assembled"]["payloads"]["questions.json"]["questions"]
        practised: dict[str, int] = {}
        for row in coverage:
            if row["language"] == "en":
                practised[row["concept_id"]] = practised.get(row["concept_id"], 0) + 1
        for concept_id in concepts:
            if practised.get(concept_id, 0) == 0:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_002,
                        category="content",
                        message=f"{chapter['chapter_id']}: concept {concept_id} has no "
                        "practice item",
                    )
                )
        unknown = set(practised) - set(concepts)
        if unknown:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_002,
                    category="content",
                    message=f"{chapter['chapter_id']}: items tagged to unknown concepts "
                    f"{sorted(unknown)}",
                )
            )
        manifest_coverage = result["assembled"]["manifest"]["coverage"]["by_concept"]
        if manifest_coverage != {c: practised.get(c, 0) for c in concepts}:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_002,
                    category="content",
                    message=f"{chapter['chapter_id']}: pack coverage.by_concept disagrees "
                    "with the questions",
                )
            )
        if graph["lesson"] is None:
            # Block-tagging debt, not a finding: the card's severity floor is
            # fatal, so a `minor` IssueRecord would (correctly) be escalated and
            # fail the suite. Record the debt as a metric instead - it is
            # visible in the run report and the manifest's coverage.block_tagging.
            context.setdefault("metrics", {})[
                f"{chapter['chapter_id']}.block_tagging"
            ] = "pending_lesson"
        else:
            blocks = graph["blocks"]
            untagged = [b for b, entry in blocks.items() if not entry.get("concept_id")]
            if graph["block_tagging"] != "complete" or untagged:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_002,
                        category="content",
                        message=f"{chapter['chapter_id']}: "
                        f"{len(untagged)} of {len(blocks)} lesson blocks are untagged",
                    )
                )
        # The chapter must exist exactly once in the class's ordered list.
        found = [
            entry
            for entry in syllabus["classes"]
            if entry["class"] == expected["class_level"]
            for entry_chapter in entry["chapters"]
            if entry_chapter["chapter_id"] == chapter["chapter_id"]
        ]
        if len(found) != 1:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_002,
                    category="content",
                    message=f"{chapter['chapter_id']}: appears {len(found)} times in the "
                    f"class {expected['class_level']} syllabus",
                )
            )
    return issues


# ------------------------------------------------------------------ EV-ASM-003
def _check_bank_shape(
    chapter: dict[str, Any],
    items: list[dict[str, Any]],
    expected: dict[str, Any],
    check_id: str,
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    total = len(items)
    if not expected["item_count"]["min"] <= total <= expected["item_count"]["max"]:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id=check_id,
                category="content",
                message=f"{chapter['chapter_id']}: {total} items outside the golden range "
                f"{expected['item_count']}",
            )
        )
    for item_type, bounds in expected["type_counts"].items():
        count = sum(1 for item in items if item["type"] == item_type)
        if not bounds["min"] <= count <= bounds["max"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{chapter['chapter_id']}: {item_type} count {count} outside "
                    f"{bounds}",
                )
            )
    for difficulty, bounds in expected["difficulty_share"].items():
        share = sum(1 for item in items if item["difficulty"] == difficulty) / max(
            1, total
        )
        if not bounds["min"] <= share <= bounds["max"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{chapter['chapter_id']}: {difficulty} share {share:.2f} "
                    f"outside {bounds}",
                )
            )
    for item in items:
        if not 1 <= int(item["marks"]) <= 2:
            issues.append(
                IssueRecord(
                    severity="major",
                    check_id=check_id,
                    category="content",
                    message=f"{item['item_id']}: practice marks {item['marks']} outside the "
                    "1-2 practice band",
                )
            )
    mean_marks = sum(int(item["marks"]) for item in items) / max(1, total)
    if not 1.0 <= mean_marks <= 2.0:
        issues.append(
            IssueRecord(
                severity="major",
                check_id=check_id,
                category="content",
                message=f"{chapter['chapter_id']}: mean marks {mean_marks:.2f} outside 1-2",
            )
        )
    return issues


def _check_priors(
    chapter: dict[str, Any],
    priors: dict[str, Any],
    items: list[dict[str, Any]],
    expected: dict[str, Any],
    check_id: str,
) -> list[IssueRecord]:
    issues: list[IssueRecord] = []
    rows = priors["questions"]
    lo, hi = expected["time_prior_ms"]["min"], expected["time_prior_ms"]["max"]
    for row in rows:
        if not lo <= int(row["expected_time_ms"]) <= hi:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{row['question_id']}: prior {row['expected_time_ms']} ms "
                    f"outside the golden range [{lo}, {hi}]",
                )
            )
    # Hard items must not be predicted to be faster than easy items on the same
    # item type: a prior that says otherwise is not a sane difficulty signal.
    for item_type in {item["type"] for item in items}:
        easy = [
            row["expected_time_ms"]
            for row in rows
            if row["basis"]["language"] == "en"
            and row["basis"]["type"] == item_type
            and row["basis"]["difficulty"] == "easy"
        ]
        hard = [
            row["expected_time_ms"]
            for row in rows
            if row["basis"]["language"] == "en"
            and row["basis"]["type"] == item_type
            and row["basis"]["difficulty"] == "hard"
        ]
        if easy and hard and median(hard) < median(easy):
            issues.append(
                IssueRecord(
                    severity="major",
                    check_id=check_id,
                    category="content",
                    message=f"{chapter['chapter_id']}: {item_type} hard median "
                    f"{median(hard)} ms < easy median {median(easy)} ms",
                )
            )
    topic_scopes = {(t["scope"], t["scope_id"]) for t in priors["topics"]}
    if ("chapter", chapter["chapter_id"]) not in topic_scopes:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id=check_id,
                category="content",
                message=f"{chapter['chapter_id']}: no chapter-level topic prior",
            )
        )
    for concept in chapter["concepts"]:
        if ("concept", concept["concept_id"]) not in topic_scopes:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=check_id,
                    category="content",
                    message=f"{chapter['chapter_id']}: no topic prior for concept "
                    f"{concept['concept_id']}",
                )
            )
    return issues


def check_difficulty_marks_time_priors(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-ASM03-TIME-PRIORS`: difficulty/type mix, marks band, prior bounds,
    difficulty monotonicity and topic priors."""
    issues: list[IssueRecord] = []
    for golden_rel in card.golden_inputs.get("topics", []):
        expected = _load_expected(cfg, golden_rel, CHECK_003, context)
        if expected is None:
            continue
        result, assemble_issues = _assemble(cfg, expected, CHECK_003)
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        items = result["items"]["items"]
        priors = result["priors"]
        issues.extend(_check_bank_shape(chapter, items, expected, CHECK_003))
        issues.extend(_check_priors(chapter, priors, items, expected, CHECK_003))
        priors_payload = {
            key: priors[key]
            for key in ("schema_version", "formula_version", "questions", "topics")
        }
        issues.extend(
            _issues_to_records(
                validate_time_priors(
                    priors_payload, chapter, items, _assessment_cfg(cfg).policy
                ),
                CHECK_003,
                prefix=chapter["chapter_id"],
            )
        )

    for defect_id in card.golden_inputs.get("seeded_defects", []):
        defect, defect_issue = _seeded_defect(cfg, defect_id, CHECK_003)
        if defect_issue is not None:
            issues.append(defect_issue)
            continue
        assert defect is not None
        result, assemble_issues = _assemble(
            cfg, {"chapter_id": defect["chapter_id"], "golden_id": "GA-00"}, CHECK_003
        )
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        mutated = apply_prior_defect(
            {
                key: result["priors"][key]
                for key in ("schema_version", "formula_version", "questions", "topics")
            },
            defect,
        )
        found = validate_time_priors(
            mutated, chapter, result["items"]["items"], _assessment_cfg(cfg).policy
        )
        rules = {issue.rule for issue in found if issue.severity in ("fatal", "major")}
        if defect["expected_rule"] not in rules:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_003,
                    category="content",
                    message=f"{defect_id}: expected rule {defect['expected_rule']!r} to fire; "
                    f"fired {sorted(rules)}",
                )
            )
    return issues


# ------------------------------------------------------------------ EV-ASM-004
def check_language_completeness(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-ASM04-LANGUAGES`: EN/HI/Hinglish rows for every item and rubric,
    with the script rules (Devanagari for hi, Latin for en/hi-Latn)."""
    issues: list[IssueRecord] = []
    for golden_rel in card.golden_inputs.get("topics", []):
        expected = _load_expected(cfg, golden_rel, CHECK_004, context)
        if expected is None:
            continue
        result, assemble_issues = _assemble(cfg, expected, CHECK_004)
        issues.extend(assemble_issues)
        if result is None:
            continue
        chapter = result["chapter"]
        payloads = result["assembled"]["payloads"]
        try:
            validate_schema(
                payloads["questions.json"], ASSESSMENT_QUESTIONS, "questions.json"
            )
            validate_schema(
                payloads["speaking.json"], ASSESSMENT_SPEAKING_ROWS, "speaking.json"
            )
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_004,
                    category="content",
                    message=f"{chapter['chapter_id']}: {exc}",
                )
            )
            continue
        base_items = len(result["items"]["items"])
        for language in expected["languages"]:
            count = sum(
                1
                for row in payloads["questions.json"]["questions"]
                if row["language"] == language
            )
            if count != base_items:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{chapter['chapter_id']}: {count} question rows in "
                        f"{language!r}, expected one per base item ({base_items})",
                    )
                )
        for row in payloads["questions.json"]["questions"]:
            text = " ".join(
                [row["prompt"], row.get("explanation", "")]
                + list(row.get("options") or [])
            )
            devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
            if row["language"] == "hi" and not devanagari:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{row['question_id']}: Hindi row has no Devanagari text",
                    )
                )
            if row["language"] in ("en", "hi-Latn") and devanagari:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{row['question_id']}: {row['language']} row contains "
                        "Devanagari text",
                    )
                )
        prompts = payloads["speaking.json"]["prompts"]
        speaking_base = len(result["speaking"]["prompts"])
        if speaking_base < expected["speaking_prompts_min"]:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_004,
                    category="content",
                    message=f"{chapter['chapter_id']}: {speaking_base} speaking prompts, "
                    f"golden requires {expected['speaking_prompts_min']}",
                )
            )
        for language in expected["languages"]:
            count = sum(1 for row in prompts if row["language"] == language)
            if count != speaking_base:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{chapter['chapter_id']}: {count} speaking rows in "
                        f"{language!r}, expected {speaking_base}",
                    )
                )
        for row in prompts:
            text = " ".join(
                [row["prompt"], row["model_answer"]]
                + [idea["text"] for idea in row["key_ideas"]]
            )
            devanagari = any("\u0900" <= ch <= "\u097f" for ch in text)
            if row["language"] == "hi" and not devanagari:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{row['prompt_id']}[hi]: no Devanagari text",
                    )
                )
            if row["language"] in ("en", "hi-Latn") and devanagari:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{row['prompt_id']}[{row['language']}]: contains "
                        "Devanagari text",
                    )
                )
            if not 3 <= len(row["key_ideas"]) <= 5:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{row['prompt_id']}[{row['language']}]: "
                        f"{len(row['key_ideas'])} key ideas (need 3-5)",
                    )
                )
        for prompt in result["speaking"]["prompts"]:
            counts = {
                lang: len(payload["key_ideas"])
                for lang, payload in prompt["locales"].items()
            }
            if len(set(counts.values())) != 1:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_004,
                        category="content",
                        message=f"{prompt['prompt_id']}: key-idea counts differ across "
                        f"languages {counts}",
                    )
                )
    return issues


__all__ = [
    "CHECK_001",
    "CHECK_002",
    "CHECK_003",
    "CHECK_004",
    "check_chapter_concept_coverage",
    "check_difficulty_marks_time_priors",
    "check_language_completeness",
    "check_practice_pack_integrity",
]
