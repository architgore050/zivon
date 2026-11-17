"""Deterministic rules for assessment artifacts (the technical gate).

Every rule here is a harness guarantee, not prompt prose (the factory's
operating stance): a missing answer, an off-chapter concept, a duplicate item,
a missing language or a prior outside its bounds fails the stage and is
reported with a stable rule id, so `evals/checkers/assessment_checks.py` can
reuse the exact same code path on golden packs and seeded defects.

Rule ids are stable strings (`area.subject`). Severity scale matches the repo:
`fatal` / `major` block, `minor` is recorded debt.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import jsonschema

from . import DIFFICULTIES, ITEM_TYPES, LANGUAGES
from .schemas import (
    ASSESSMENT_DEFECT_SAMPLE,
    ASSESSMENT_ITEM,
    ASSESSMENT_ITEM_BANK,
    ASSESSMENT_SPEAKING_BANK,
    SYLLABUS,
    TIME_PRIORS,
)

_SEVERITY_RANK = {"minor": 1, "major": 2, "fatal": 3}
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097f]")

LANGUAGES_ORDER = tuple(LANGUAGES)


@dataclass(frozen=True)
class Issue:
    """One gate finding. `rule` is the stable id the eval cards assert on."""

    rule: str
    severity: str
    message: str
    item_id: str | None = None
    concept_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }
        if self.item_id is not None:
            out["item_id"] = self.item_id
        if self.concept_id is not None:
            out["concept_id"] = self.concept_id
        return out


@dataclass(frozen=True)
class ItemGatePolicy:
    """The tunable part of the assessment gate (config `assessment.*`)."""

    min_items: int = 15
    max_items: int = 20
    min_type_counts: Mapping[str, int] = field(
        default_factory=lambda: {"mcq": 5, "numeric": 2, "assertion_reason": 1}
    )
    difficulty_share: Mapping[str, tuple[float, float]] = field(
        default_factory=lambda: {
            "easy": (0.15, 0.45),
            "medium": (0.30, 0.60),
            "hard": (0.10, 0.35),
        }
    )
    max_items_per_concept: int = 6
    speaking_prompts_min: int = 3
    time_prior_min_ms: int = 15_000
    time_prior_max_ms: int = 300_000


def _schema_issue(prefix: str, exc: Exception, **kwargs: Any) -> Issue:
    return Issue(rule=f"{prefix}.schema", severity="fatal", message=str(exc), **kwargs)


def validate_schema(instance: Any, schema: dict[str, Any], name: str) -> None:
    """Draft-07 validation with the first error's path in the message."""
    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        first = errors[0]
        path = "/".join(str(p) for p in first.absolute_path) or "(root)"
        raise ValueError(
            f"{name} schema validation failed at '{path}': {first.message}"
        )


# ------------------------------------------------------------------ text helpers
def normalize_text(text: str) -> str:
    """Lowercase, punctuation-free, whitespace-collapsed text for duplicate
    detection. Devanagari is preserved (a Hindi duplicate is still a duplicate)."""
    return re.sub(r"[^a-z0-9\u0900-\u097f]+", " ", str(text).lower()).strip()


def count_words(text: str) -> int:
    return len(re.findall(r"\w+", str(text), flags=re.UNICODE))


# ------------------------------------------------------------------ syllabus
def validate_syllabus(
    syllabus: dict[str, Any],
    *,
    catalog_book_ids: set[str] | None = None,
) -> list[Issue]:
    """A1 gate: the four-class map is complete, ids resolve, weights honest."""
    try:
        validate_schema(syllabus, SYLLABUS, "SYLLABUS")
    except ValueError as exc:
        return [_schema_issue("syllabus", exc)]

    issues: list[Issue] = []
    classes = syllabus["classes"]
    if sorted(c["class"] for c in classes) != [9, 10, 11, 12]:
        issues.append(
            Issue(
                "syllabus.classes",
                "fatal",
                "the syllabus must cover classes 9, 10, 11 and 12 exactly once",
            )
        )

    chapter_ids: set[str] = set()
    concept_ids: set[str] = set()
    for class_entry in classes:
        class_level = class_entry["class"]
        numbers: list[int] = []
        orders: list[int] = []
        for chapter in class_entry["chapters"]:
            cid = chapter["chapter_id"]
            numbers.append(chapter["number"])
            orders.append(chapter["order"])
            if cid in chapter_ids:
                issues.append(
                    Issue(
                        "syllabus.chapter_duplicate",
                        "fatal",
                        f"duplicate chapter id {cid}",
                    )
                )
            chapter_ids.add(cid)
            if chapter["class"] != class_level:
                issues.append(
                    Issue(
                        "syllabus.chapter_class",
                        "fatal",
                        f"{cid}: chapter class {chapter['class']} != parent class {class_level}",
                    )
                )
            if (
                catalog_book_ids is not None
                and chapter["book_id"] not in catalog_book_ids
            ):
                issues.append(
                    Issue(
                        "syllabus.book_unknown",
                        "fatal",
                        f"{cid}: book_id {chapter['book_id']!r} is not in sources/catalog.json",
                    )
                )
            chapter_concepts = [c["concept_id"] for c in chapter["concepts"]]
            if chapter["concepts_status"] == "curated":
                if len(chapter_concepts) < 3:
                    issues.append(
                        Issue(
                            "syllabus.concepts_thin",
                            "fatal",
                            f"{cid}: a curated chapter needs at least 3 concepts",
                        )
                    )
            elif chapter_concepts:
                issues.append(
                    Issue(
                        "syllabus.concepts_unexpected",
                        "fatal",
                        f"{cid}: concepts_status is pending_r1_5 but concepts are listed",
                    )
                )
            for concept in chapter["concepts"]:
                concept_id = concept["concept_id"]
                if concept_id in concept_ids:
                    issues.append(
                        Issue(
                            "syllabus.concept_duplicate",
                            "fatal",
                            f"duplicate concept id {concept_id}",
                        )
                    )
                concept_ids.add(concept_id)
                if not concept_id.startswith(cid + "-"):
                    issues.append(
                        Issue(
                            "syllabus.concept_prefix",
                            "fatal",
                            f"{concept_id}: a concept id must start with its chapter id '{cid}-'",
                            concept_id=concept_id,
                        )
                    )
                prefix = f"{chapter['number']}."
                for ref in concept["section_refs"]:
                    if not ref.startswith(prefix):
                        issues.append(
                            Issue(
                                "syllabus.section_ref",
                                "fatal",
                                f"{concept_id}: section ref {ref!r} does not belong to "
                                f"chapter {chapter['number']}",
                                concept_id=concept_id,
                            )
                        )
            weight = chapter.get("exam_weight")
            weight_status = chapter.get("exam_weight_status")
            if weight_status == "curated" and weight is None:
                issues.append(
                    Issue(
                        "syllabus.exam_weight",
                        "fatal",
                        f"{cid}: exam_weight_status is curated but exam_weight is null",
                    )
                )
            if weight_status == "pending_p3_blueprint" and weight is not None:
                issues.append(
                    Issue(
                        "syllabus.exam_weight",
                        "fatal",
                        f"{cid}: exam_weight is set but its status says P3 owns it",
                    )
                )
            if weight is not None and not (0 < float(weight) <= 1):
                issues.append(
                    Issue(
                        "syllabus.exam_weight",
                        "fatal",
                        f"{cid}: exam_weight must be in (0, 1] (got {weight})",
                    )
                )
        if len(set(numbers)) != len(numbers):
            issues.append(
                Issue(
                    "syllabus.chapter_number",
                    "fatal",
                    f"class {class_level}: duplicate textbook chapter numbers {sorted(numbers)}",
                )
            )
        if sorted(orders) != list(range(1, len(orders) + 1)):
            issues.append(
                Issue(
                    "syllabus.chapter_order",
                    "fatal",
                    f"class {class_level}: order must be contiguous 1..n (got {sorted(orders)})",
                )
            )

    # Prerequisites resolve (across chapters is allowed) and never self-loop.
    for class_entry in classes:
        for chapter in class_entry["chapters"]:
            for concept in chapter["concepts"]:
                for prereq in concept["prerequisites"]:
                    if prereq == concept["concept_id"]:
                        issues.append(
                            Issue(
                                "syllabus.prerequisite_self",
                                "fatal",
                                f"{concept['concept_id']}: concept lists itself as a prerequisite",
                                concept_id=concept["concept_id"],
                            )
                        )
                    elif prereq not in concept_ids:
                        issues.append(
                            Issue(
                                "syllabus.prerequisite_unknown",
                                "fatal",
                                f"{concept['concept_id']}: prerequisite {prereq!r} does not exist",
                                concept_id=concept["concept_id"],
                            )
                        )
    return issues


def chapter_by_id(syllabus: dict[str, Any], chapter_id: str) -> dict[str, Any] | None:
    for class_entry in syllabus["classes"]:
        for chapter in class_entry["chapters"]:
            if chapter["chapter_id"] == chapter_id:
                return chapter
    return None


def concept_ids_of(chapter: dict[str, Any]) -> list[str]:
    return [c["concept_id"] for c in chapter["concepts"]]


# ------------------------------------------------------------------ concept graph
def validate_concept_graph(
    graph: dict[str, Any], chapter: dict[str, Any]
) -> list[Issue]:
    """A2 gate: every P1 block lands on a curated concept, no orphan concept."""
    issues: list[Issue] = []
    known = set(concept_ids_of(chapter))
    mapping: dict[str, str] = graph.get("section_concept_map") or {}
    for section_id, concept_id in mapping.items():
        if concept_id not in known:
            issues.append(
                Issue(
                    "concept.mapping_unknown",
                    "fatal",
                    f"section {section_id} maps to unknown concept {concept_id!r}",
                    concept_id=concept_id,
                )
            )
    lesson = graph.get("lesson")
    if lesson is None:
        issues.append(
            Issue(
                "concept.manifest_missing",
                "minor",
                "no published lesson manifest for this chapter yet: question tagging "
                "is enforced, block tagging is pending (content-quality debt)",
            )
        )
        return issues

    sections = lesson.get("sections") or []
    for section in sections:
        section_id = section.get("id")
        if section_id not in mapping:
            issues.append(
                Issue(
                    "concept.section_unmapped",
                    "fatal",
                    f"lesson section {section_id} has no curated concept mapping",
                )
            )
    covered: set[str] = set()
    for block_id, block in (graph.get("blocks") or {}).items():
        section_id = block.get("section_id")
        if section_id not in mapping:
            issues.append(
                Issue(
                    "concept.block_unmapped",
                    "fatal",
                    f"lesson block {block_id} belongs to unmapped section {section_id}",
                )
            )
        else:
            covered.add(mapping[section_id])
    for concept_id in known:
        if concept_id not in covered:
            issues.append(
                Issue(
                    "concept.orphan",
                    "fatal",
                    f"curated concept {concept_id} owns no lesson block",
                    concept_id=concept_id,
                )
            )
    return issues


# ------------------------------------------------------------------ practice items
def _locale_texts(item: dict[str, Any]) -> list[tuple[str, str]]:
    texts: list[tuple[str, str]] = []
    for lang, payload in item["locales"].items():
        texts.append((lang, payload.get("prompt", "")))
        for option in payload.get("options") or []:
            texts.append((lang, option))
        texts.append((lang, payload.get("explanation", "")))
    return texts


def validate_item(
    item: dict[str, Any],
    chapter: dict[str, Any],
    *,
    catalog_book_ids: set[str] | None = None,
) -> list[Issue]:
    """Item-level rules (also used as the live generator's `extra_validator`)."""
    issues: list[Issue] = []
    item_id = item.get("item_id")
    try:
        validate_schema(item, ASSESSMENT_ITEM, f"item {item_id}")
    except ValueError as exc:
        return [_schema_issue("item", exc, item_id=item_id)]

    known = set(concept_ids_of(chapter))
    concept_id = item["concept_id"]
    if concept_id not in known:
        issues.append(
            Issue(
                "item.concept_unknown",
                "fatal",
                f"{item_id}: concept {concept_id!r} is not taught by chapter "
                f"{chapter['chapter_id']}",
                item_id=item_id,
                concept_id=concept_id,
            )
        )

    source = item["source_ref"]
    if catalog_book_ids is not None and source["book_id"] not in catalog_book_ids:
        issues.append(
            Issue(
                "item.source_unknown_book",
                "fatal",
                f"{item_id}: source book {source['book_id']!r} is not in sources/catalog.json",
                item_id=item_id,
            )
        )
    if not source["section"].startswith(f"{chapter['number']}."):
        issues.append(
            Issue(
                "item.source_off_chapter",
                "fatal",
                f"{item_id}: source section {source['section']!r} is not a section of "
                f"chapter {chapter['number']}",
                item_id=item_id,
            )
        )

    answer = item["answer"]
    for lang, payload in item["locales"].items():
        options = payload.get("options") or []
        if item["type"] == "numeric":
            if options:
                issues.append(
                    Issue(
                        "item.answer.options",
                        "fatal",
                        f"{item_id}[{lang}]: a numeric item must not carry options",
                        item_id=item_id,
                    )
                )
        else:
            if len(options) != 4:
                issues.append(
                    Issue(
                        "item.answer.options",
                        "fatal",
                        f"{item_id}[{lang}]: expected exactly 4 options, got {len(options)}",
                        item_id=item_id,
                    )
                )
            if "index" not in answer:
                issues.append(
                    Issue(
                        "item.answer.index",
                        "fatal",
                        f"{item_id}[{lang}]: MCQ/assertion-reason needs an option index",
                        item_id=item_id,
                    )
                )
            elif not 0 <= int(answer["index"]) < len(options):
                issues.append(
                    Issue(
                        "item.answer.index",
                        "fatal",
                        f"{item_id}[{lang}]: answer index {answer['index']} is outside "
                        f"the {len(options)} options",
                        item_id=item_id,
                    )
                )
        if len(payload["explanation"].strip()) < 15:
            issues.append(
                Issue(
                    "item.explanation",
                    "fatal",
                    f"{item_id}[{lang}]: explanation is too short to teach why",
                    item_id=item_id,
                )
            )
        if item["type"] == "numeric":
            if "value" not in answer:
                issues.append(
                    Issue(
                        "item.answer.numeric",
                        "fatal",
                        f"{item_id}: a numeric item needs a value answer",
                        item_id=item_id,
                    )
                )
            if "tolerance" in answer and float(answer["tolerance"]) < 0:
                issues.append(
                    Issue(
                        "item.answer.numeric",
                        "fatal",
                        f"{item_id}: tolerance must not be negative",
                        item_id=item_id,
                    )
                )

    distractor = item.get("distractor_index")
    if distractor is not None:
        if item["type"] == "numeric":
            issues.append(
                Issue(
                    "item.answer.distractor",
                    "fatal",
                    f"{item_id}: numeric items do not have distractor options",
                    item_id=item_id,
                )
            )
        elif not 0 <= int(distractor) < 4:
            issues.append(
                Issue(
                    "item.answer.distractor",
                    "fatal",
                    f"{item_id}: distractor_index must be a 0..3 option index",
                    item_id=item_id,
                )
            )
        elif "index" in answer and int(distractor) == int(answer["index"]):
            issues.append(
                Issue(
                    "item.answer.distractor",
                    "fatal",
                    f"{item_id}: distractor_index points at the correct answer",
                    item_id=item_id,
                )
            )

    issues.extend(_language_issues(str(item_id), item["locales"]))
    return issues


def _language_issues(item_id: str, locales: Mapping[str, Any]) -> list[Issue]:
    issues: list[Issue] = []
    missing = [lang for lang in LANGUAGES_ORDER if lang not in locales]
    if missing:
        issues.append(
            Issue(
                "item.language_missing",
                "fatal",
                f"{item_id}: missing language variant(s) {missing}",
                item_id=item_id,
            )
        )
        return issues
    for lang, payload in locales.items():
        text = " ".join(
            [payload.get("prompt", ""), payload.get("explanation", "")]
            + list(payload.get("options") or [])
        )
        has_devanagari = bool(_DEVANAGARI_RE.search(text))
        if lang == "hi" and not has_devanagari:
            issues.append(
                Issue(
                    "item.language_script",
                    "fatal",
                    f"{item_id}: the Hindi variant contains no Devanagari text",
                    item_id=item_id,
                )
            )
        if lang in ("en", "hi-Latn") and has_devanagari:
            issues.append(
                Issue(
                    "item.language_script",
                    "fatal",
                    f"{item_id}: the {lang} variant contains Devanagari text",
                    item_id=item_id,
                )
            )
    return issues


def _difficulty_share_issues(
    items: Sequence[dict[str, Any]], policy: ItemGatePolicy
) -> list[Issue]:
    issues: list[Issue] = []
    total = len(items)
    counts = {d: sum(1 for i in items if i["difficulty"] == d) for d in DIFFICULTIES}
    for difficulty, (low, high) in policy.difficulty_share.items():
        share = counts[difficulty] / total
        if not low <= share <= high:
            issues.append(
                Issue(
                    "bank.difficulty_mix",
                    "fatal",
                    f"{difficulty} share {share:.2f} outside [{low}, {high}] "
                    f"({counts[difficulty]} of {total} items)",
                )
            )
    return issues


def validate_item_bank(
    bank: dict[str, Any],
    chapter: dict[str, Any],
    policy: ItemGatePolicy,
    *,
    catalog_book_ids: set[str] | None = None,
) -> list[Issue]:
    """The full A3 technical gate: per-item rules plus bank-level coverage."""
    try:
        validate_schema(bank, ASSESSMENT_ITEM_BANK, "ASSESSMENT_ITEM_BANK")
    except ValueError as exc:
        return [_schema_issue("bank", exc)]

    issues: list[Issue] = []
    if bank["chapter_id"] != chapter["chapter_id"]:
        issues.append(
            Issue(
                "bank.chapter_mismatch",
                "fatal",
                f"bank chapter_id {bank['chapter_id']!r} != requested "
                f"{chapter['chapter_id']!r}",
            )
        )
    if bank["class"] != chapter["class"]:
        issues.append(
            Issue(
                "bank.class_mismatch",
                "fatal",
                f"bank class {bank['class']} != chapter class {chapter['class']}",
            )
        )
    if bank["source"]["book_id"] != chapter["book_id"]:
        issues.append(
            Issue(
                "bank.source_mismatch",
                "fatal",
                f"bank source book {bank['source']['book_id']!r} != chapter book "
                f"{chapter['book_id']!r}",
            )
        )

    items = bank["items"]
    seen_ids: set[str] = set()
    by_prompt: dict[tuple[str, str], str] = {}
    for item in items:
        item_id = item["item_id"]
        if item_id in seen_ids:
            issues.append(
                Issue(
                    "item.duplicate_id",
                    "fatal",
                    f"item_id {item_id!r} appears more than once",
                    item_id=item_id,
                )
            )
        seen_ids.add(item_id)
        issues.extend(validate_item(item, chapter, catalog_book_ids=catalog_book_ids))
        for lang, payload in item["locales"].items():
            key = (lang, normalize_text(payload["prompt"]))
            other = by_prompt.get(key)
            if other is not None:
                issues.append(
                    Issue(
                        "item.duplicate_prompt",
                        "fatal",
                        f"{item_id} duplicates the {lang} prompt of {other}",
                        item_id=item_id,
                    )
                )
            else:
                by_prompt[key] = item_id

    total = len(items)
    if not policy.min_items <= total <= policy.max_items:
        issues.append(
            Issue(
                "bank.count",
                "fatal",
                f"{total} items outside the required {policy.min_items}-"
                f"{policy.max_items} per chapter",
            )
        )
    type_counts = {t: sum(1 for i in items if i["type"] == t) for t in ITEM_TYPES}
    for item_type, minimum in policy.min_type_counts.items():
        if type_counts.get(item_type, 0) < minimum:
            issues.append(
                Issue(
                    "bank.type_mix",
                    "fatal",
                    f"{item_type} count {type_counts.get(item_type, 0)} is below the "
                    f"minimum {minimum}",
                )
            )
    issues.extend(_difficulty_share_issues(items, policy))

    concept_counts = {c: 0 for c in concept_ids_of(chapter)}
    for item in items:
        if item["concept_id"] in concept_counts:
            concept_counts[item["concept_id"]] += 1
    for concept_id, count in concept_counts.items():
        if count == 0:
            issues.append(
                Issue(
                    "bank.concept_coverage",
                    "fatal",
                    f"concept {concept_id} has no practice item",
                    concept_id=concept_id,
                )
            )
        elif count > policy.max_items_per_concept:
            issues.append(
                Issue(
                    "bank.concept_density",
                    "minor",
                    f"concept {concept_id} carries {count} items (>{policy.max_items_per_concept}); "
                    "coverage is uneven",
                    concept_id=concept_id,
                )
            )

    # Answer-letter balance: a bank where most MCQs answer option 0 trains the
    # test, not the concept. A warning, never a gate.
    mcq_answers = [
        int(i["answer"]["index"])
        for i in items
        if i["type"] in ("mcq", "assertion_reason") and "index" in i["answer"]
    ]
    if len(mcq_answers) >= 4:
        dominant = max(mcq_answers.count(x) for x in set(mcq_answers))
        if dominant / len(mcq_answers) > 0.6:
            issues.append(
                Issue(
                    "bank.answer_balance",
                    "minor",
                    f"one option index is the answer in {dominant}/{len(mcq_answers)} "
                    "objective items; rebalance during the quality pass",
                )
            )
    return issues


# ------------------------------------------------------------------ speaking
def validate_speaking_bank(
    bank: dict[str, Any],
    chapter: dict[str, Any],
    policy: ItemGatePolicy,
    *,
    catalog_book_ids: set[str] | None = None,
) -> list[Issue]:
    try:
        validate_schema(bank, ASSESSMENT_SPEAKING_BANK, "ASSESSMENT_SPEAKING_BANK")
    except ValueError as exc:
        return [_schema_issue("rubric", exc)]

    issues: list[Issue] = []
    if bank["chapter_id"] != chapter["chapter_id"]:
        issues.append(
            Issue(
                "rubric.chapter_mismatch",
                "fatal",
                f"speaking bank chapter_id {bank['chapter_id']!r} != requested "
                f"{chapter['chapter_id']!r}",
            )
        )
    known = set(concept_ids_of(chapter))
    if len(bank["prompts"]) < policy.speaking_prompts_min:
        issues.append(
            Issue(
                "rubric.prompt_count",
                "fatal",
                f"{len(bank['prompts'])} speaking prompts, need at least "
                f"{policy.speaking_prompts_min}",
            )
        )
    seen: set[str] = set()
    for prompt in bank["prompts"]:
        pid = prompt["prompt_id"]
        if pid in seen:
            issues.append(
                Issue("rubric.duplicate_id", "fatal", f"duplicate prompt id {pid}")
            )
        seen.add(pid)
        for concept_id in prompt["concept_ids"]:
            if concept_id not in known:
                issues.append(
                    Issue(
                        "rubric.concept_unknown",
                        "fatal",
                        f"{pid}: concept {concept_id!r} is not taught by this chapter",
                        concept_id=concept_id,
                    )
                )
        source = prompt["source_ref"]
        if catalog_book_ids is not None and source["book_id"] not in catalog_book_ids:
            issues.append(
                Issue(
                    "rubric.source_unknown_book",
                    "fatal",
                    f"{pid}: source book {source['book_id']!r} is not in sources/catalog.json",
                )
            )
        if not source["section"].startswith(f"{chapter['number']}."):
            issues.append(
                Issue(
                    "rubric.source_off_chapter",
                    "fatal",
                    f"{pid}: source section {source['section']!r} is not a section of "
                    f"chapter {chapter['number']}",
                )
            )
        idea_counts = {
            lang: len(payload["key_ideas"])
            for lang, payload in prompt["locales"].items()
        }
        if len(set(idea_counts.values())) != 1:
            issues.append(
                Issue(
                    "rubric.key_ideas",
                    "fatal",
                    f"{pid}: key-idea counts differ across languages {idea_counts}",
                )
            )
        thresholds = prompt["thresholds"]
        if thresholds["strong_ratio"] < thresholds["pass_ratio"]:
            issues.append(
                Issue(
                    "rubric.thresholds",
                    "fatal",
                    f"{pid}: strong_ratio must be >= pass_ratio",
                )
            )
        for lang, payload in prompt["locales"].items():
            if thresholds["min_key_ideas"] > len(payload["key_ideas"]):
                issues.append(
                    Issue(
                        "rubric.thresholds",
                        "fatal",
                        f"{pid}[{lang}]: min_key_ideas exceeds the key-idea count",
                    )
                )
            if lang == "hi" and not _DEVANAGARI_RE.search(payload["prompt"]):
                issues.append(
                    Issue(
                        "rubric.language_script",
                        "fatal",
                        f"{pid}: the Hindi prompt contains no Devanagari text",
                    )
                )
            if lang in ("en", "hi-Latn") and _DEVANAGARI_RE.search(
                payload["model_answer"]
            ):
                issues.append(
                    Issue(
                        "rubric.language_script",
                        "fatal",
                        f"{pid}: the {lang} model answer contains Devanagari text",
                    )
                )
    return issues


# ------------------------------------------------------------------ time priors
def validate_time_priors(
    priors: dict[str, Any],
    chapter: dict[str, Any],
    issues_source: Sequence[dict[str, Any]],
    policy: ItemGatePolicy,
) -> list[Issue]:
    """A5 gate: every question row has a sane prior; topic priors agree."""
    try:
        validate_schema(priors, TIME_PRIORS, "TIME_PRIORS")
    except ValueError as exc:
        return [_schema_issue("time_prior", exc)]

    issues: list[Issue] = []
    expected_rows = {
        f"{item['item_id']}-{lang}"
        for item in issues_source
        for lang in LANGUAGES_ORDER
    }
    seen: set[str] = set()
    for row in priors["questions"]:
        qid = row["question_id"]
        if qid in seen:
            issues.append(
                Issue("time_prior.duplicate", "fatal", f"duplicate prior row {qid}")
            )
        seen.add(qid)
        value = int(row["expected_time_ms"])
        if not policy.time_prior_min_ms <= value <= policy.time_prior_max_ms:
            issues.append(
                Issue(
                    "time_prior.bounds",
                    "fatal",
                    f"{qid}: prior {value} ms outside "
                    f"[{policy.time_prior_min_ms}, {policy.time_prior_max_ms}]",
                    item_id=qid,
                )
            )
    missing = sorted(expected_rows - seen)
    if missing:
        issues.append(
            Issue(
                "time_prior.missing",
                "fatal",
                f"{len(missing)} question rows have no prior (e.g. {missing[0]})",
            )
        )
    known_concepts = set(concept_ids_of(chapter))
    for topic in priors["topics"]:
        if topic["scope"] == "chapter" and topic["scope_id"] != chapter["chapter_id"]:
            issues.append(
                Issue(
                    "time_prior.topic_scope",
                    "fatal",
                    f"chapter prior scoped to {topic['scope_id']!r}",
                )
            )
        if topic["scope"] == "concept" and topic["scope_id"] not in known_concepts:
            issues.append(
                Issue(
                    "time_prior.topic_scope",
                    "fatal",
                    f"topic prior scoped to unknown concept {topic['scope_id']!r}",
                    concept_id=topic["scope_id"],
                )
            )
    return issues


# ------------------------------------------------------------------ seeded defects
def apply_defect_mutations(
    bank: dict[str, Any], defect: dict[str, Any]
) -> dict[str, Any]:
    """Apply one seeded-defect mutation to a real item bank (deep copy).

    Seeded defects are PATCHES against the shipped bank, never a second
    hand-written bank: the defect stays realistic when the seed content
    changes, and the mutation is reviewable in one place.
    """
    try:
        validate_schema(
            defect, ASSESSMENT_DEFECT_SAMPLE, f"defect {defect.get('sample_id')}"
        )
    except ValueError as exc:
        raise ValueError(str(exc)) from exc
    mutated = copy.deepcopy(bank)
    items = mutated["items"]
    operation = defect["mutations"]["operation"]
    if operation == "patch_item":
        item_id = defect["mutations"]["item_id"]
        patch = defect["mutations"].get("patch") or {}
        for item in items:
            if item["item_id"] == item_id:
                _deep_merge(item, patch)
                return mutated
        raise ValueError(f"defect {defect['sample_id']}: item {item_id!r} not found")
    if operation == "delete_locale":
        item_id = defect["mutations"]["item_id"]
        locale = defect["mutations"]["locale"]
        for item in items:
            if item["item_id"] == item_id:
                item["locales"].pop(locale, None)
                return mutated
        raise ValueError(f"defect {defect['sample_id']}: item {item_id!r} not found")
    if operation == "duplicate_item":
        source_id = defect["mutations"]["source_item_id"]
        new_id = defect["mutations"]["new_item_id"]
        for item in items:
            if item["item_id"] == source_id:
                clone = copy.deepcopy(item)
                clone["item_id"] = new_id
                items.append(clone)
                return mutated
        raise ValueError(f"defect {defect['sample_id']}: item {source_id!r} not found")
    raise ValueError(f"defect {defect['sample_id']}: unknown operation {operation!r}")


def _deep_merge(target: dict[str, Any], patch: Mapping[str, Any]) -> None:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def apply_prior_defect(
    priors: dict[str, Any], defect: dict[str, Any]
) -> dict[str, Any]:
    """Apply a `patch_prior` seeded defect to a priors payload (deep copy)."""
    mutated = copy.deepcopy(priors)
    question_id = defect["mutations"]["question_id"]
    value = defect["mutations"]["value"]
    for row in mutated["questions"]:
        if row["question_id"] == question_id:
            row["expected_time_ms"] = int(value)
            return mutated
    raise ValueError(
        f"defect {defect['sample_id']}: prior row {question_id!r} not found"
    )


# ------------------------------------------------------------------ gate report
def gate_report(
    issues: Sequence[Issue], *, counts: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The artifact every gated stage writes: verdict + stable findings."""
    blocking = [i for i in issues if i.severity in ("fatal", "major")]
    warnings = [i for i in issues if i.severity == "minor"]
    report: dict[str, Any] = {
        "verdict": "fail" if blocking else "pass",
        "error_count": len(blocking),
        "warning_count": len(warnings),
        "issues": [i.to_dict() for i in issues],
        "counts": dict(counts or {}),
    }
    return report


def blocking_issues(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [i for i in report.get("issues", []) if i["severity"] in ("fatal", "major")]


def issues_for_reasons(report: Mapping[str, Any]) -> list[str]:
    """Human-readable one-line summaries for a gate failure message."""
    return [
        f"[{i['severity']}] {i['rule']}: {i['message']}"
        for i in blocking_issues(report)
    ]


__all__ = [
    "Issue",
    "ItemGatePolicy",
    "apply_defect_mutations",
    "apply_prior_defect",
    "blocking_issues",
    "chapter_by_id",
    "concept_ids_of",
    "count_words",
    "gate_report",
    "issues_for_reasons",
    "normalize_text",
    "validate_concept_graph",
    "validate_item",
    "validate_item_bank",
    "validate_schema",
    "validate_speaking_bank",
    "validate_syllabus",
    "validate_time_priors",
]
