"""A6-publish-export: flatten the artifacts into a versioned, consumable pack.

The pack is the assessment pipeline's public output. It is deliberately
file-based and self-describing: the DB importer (F0's later consumer), the
practice/speaking frontends, and an admin review all read the same JSON, and a
re-publish is an atomic directory replace keyed by content hash.

One authored item becomes three question rows (EN/HI/Hinglish) in the exported
`questions.json` - the shape REQUIREMENTS §7.3 pins for the question bank -
while the authored bank keeps one entry per item. `expected_time_ms` is filled
from A5, never from the authored text.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from . import ASSESSMENT_PIPELINE_VERSION, LANGUAGES
from .config import AssessmentConfig
from .errors import AssessmentGateError, AssessmentStageError
from .validators import gate_report

STAGE_ID = "A6-publish-export"
PACK_VERSION = 1

DATA_FILES = (
    "syllabus.json",
    "concepts.json",
    "questions.json",
    "speaking.json",
    "time-priors.json",
)


def _dumps(payload: Any) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def flatten_questions(
    chapter: dict[str, Any],
    items_output: dict[str, Any],
    priors_output: dict[str, Any],
    run_id: str,
) -> list[dict[str, Any]]:
    priors = {
        row["question_id"]: row["expected_time_ms"]
        for row in priors_output["questions"]
    }
    source_type = (items_output.get("source") or {}).get("source_type", "generated")
    rows: list[dict[str, Any]] = []
    for item in items_output["items"]:
        for language in LANGUAGES:
            locale = item["locales"][language]
            question_id = f"{item['item_id']}-{language}"
            if question_id not in priors:
                raise AssessmentStageError(
                    f"{question_id}: A5 produced no time prior; the pack refuses a "
                    "question without an expected time"
                )
            row: dict[str, Any] = {
                "question_id": question_id,
                "base_item_id": item["item_id"],
                "class_level": chapter["class"],
                "chapter_id": chapter["chapter_id"],
                "concept_id": item["concept_id"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "marks": int(item["marks"]),
                "language": language,
                "source_type": source_type,
                "source_ref": item["source_ref"],
                "prompt": locale["prompt"],
                "answer": item["answer"],
                "explanation": locale["explanation"],
                "expected_time_ms": int(priors[question_id]),
                # The v1 base batch publishes on technical gates (Q-6); the
                # review mode says exactly what that review was.
                "status": "reviewed",
                "review_mode": "deterministic",
                "version": 1,
                "generator": items_output["generator"],
                "run_id": run_id,
            }
            if locale.get("options"):
                row["options"] = locale["options"]
            if locale.get("misconception"):
                row["misconception"] = locale["misconception"]
            if item.get("distractor_index") is not None:
                row["distractor_index"] = int(item["distractor_index"])
            rows.append(row)
    return rows


def flatten_speaking(
    chapter: dict[str, Any], speaking_output: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for prompt in speaking_output["prompts"]:
        for language in LANGUAGES:
            locale = prompt["locales"][language]
            key_ideas = [
                {
                    "idea_id": f"{prompt['prompt_id']}-idea-{n + 1:02d}",
                    "text": text,
                }
                for n, text in enumerate(locale["key_ideas"])
            ]
            rows.append(
                {
                    "prompt_id": prompt["prompt_id"],
                    "chapter_id": chapter["chapter_id"],
                    "class_level": chapter["class"],
                    "concept_ids": prompt["concept_ids"],
                    "language": language,
                    "prompt": locale["prompt"],
                    "key_ideas": key_ideas,
                    "model_answer": locale["model_answer"],
                    "model_answer_source": prompt["source_ref"],
                    "thresholds": prompt["thresholds"],
                    "version": 1,
                }
            )
    return rows


def build_coverage(
    chapter: dict[str, Any],
    questions: list[dict[str, Any]],
    speaking_rows: list[dict[str, Any]],
    graph: dict[str, Any],
) -> dict[str, Any]:
    base_items = {
        row["base_item_id"]: row for row in questions if row["language"] == "en"
    }
    items = list(base_items.values())
    by_type: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    by_concept: dict[str, int] = {c["concept_id"]: 0 for c in chapter["concepts"]}
    for row in items:
        by_type[row["type"]] = by_type.get(row["type"], 0) + 1
        by_difficulty[row["difficulty"]] = by_difficulty.get(row["difficulty"], 0) + 1
        by_concept[row["concept_id"]] = by_concept.get(row["concept_id"], 0) + 1
    by_language: dict[str, int] = {lang: 0 for lang in LANGUAGES}
    for row in questions:
        by_language[row["language"]] = by_language.get(row["language"], 0) + 1
    speaking_by_language: dict[str, int] = {lang: 0 for lang in LANGUAGES}
    for row in speaking_rows:
        speaking_by_language[row["language"]] = (
            speaking_by_language.get(row["language"], 0) + 1
        )
    return {
        "by_type": dict(sorted(by_type.items())),
        "by_difficulty": dict(sorted(by_difficulty.items())),
        "by_language": by_language,
        "by_concept": dict(sorted(by_concept.items())),
        "speaking_by_language": speaking_by_language,
        "block_tagging": graph.get("block_tagging", "pending_lesson"),
    }


def _file_entry(payload: Any) -> tuple[str, dict[str, Any]]:
    text = _dumps(payload)
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return text, {"sha256": digest, "bytes": len(text.encode("utf-8"))}


def content_hash(files: dict[str, dict[str, Any]]) -> str:
    joined = "\n".join(
        f"{name}:{entry['sha256']}" for name, entry in sorted(files.items())
    )
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def assemble(
    *,
    chapter: dict[str, Any],
    syllabus: dict[str, Any],
    graph: dict[str, Any],
    items_output: dict[str, Any],
    speaking_output: dict[str, Any],
    priors_output: dict[str, Any],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    """Build the pack in memory: {filename: payload} plus the manifest."""
    questions = flatten_questions(chapter, items_output, priors_output, run_id)
    speaking_rows = flatten_speaking(chapter, speaking_output)
    coverage = build_coverage(chapter, questions, speaking_rows, graph)
    gates = [
        graph.get("gate") or {},
        items_output.get("gate") or {},
        speaking_output.get("gate") or {},
        priors_output.get("gate") or {},
    ]
    error_count = sum(int(g.get("error_count", 0)) for g in gates)
    warning_count = sum(int(g.get("warning_count", 0)) for g in gates)
    verdict = "pass" if all(g.get("verdict") == "pass" for g in gates) else "fail"

    payloads: dict[str, Any] = {
        "syllabus.json": syllabus,
        "concepts.json": {
            key: value for key, value in graph.items() if key not in ("gate", "counts")
        },
        "questions.json": {
            "schema_version": 1,
            "chapter_id": chapter["chapter_id"],
            "questions": questions,
        },
        "speaking.json": {
            "schema_version": 1,
            "chapter_id": chapter["chapter_id"],
            "prompts": speaking_rows,
        },
        "time-priors.json": {
            key: value
            for key, value in priors_output.items()
            if key in ("schema_version", "formula_version", "questions", "topics")
        },
    }
    texts: dict[str, str] = {}
    file_entries: dict[str, dict[str, Any]] = {}
    for name, payload in payloads.items():
        texts[name], file_entries[name] = _file_entry(payload)

    manifest = {
        "pack_version": PACK_VERSION,
        "assessment_pipeline_version": ASSESSMENT_PIPELINE_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "chapter_id": chapter["chapter_id"],
        "chapter_title": chapter["title"],
        "class_level": chapter["class"],
        "subject": "physics",
        "generator": items_output["generator"],
        "languages": list(LANGUAGES),
        "counts": {
            "base_items": len(items_output["items"]),
            "question_rows": len(questions),
            "speaking_prompts": len(speaking_output["prompts"]),
            "concepts": len(chapter["concepts"]),
            "blocks_tagged": int((graph.get("counts") or {}).get("blocks_tagged", 0)),
        },
        "coverage": coverage,
        "gate": {
            "verdict": verdict,
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "content_hash": content_hash(file_entries),
        "files": file_entries,
    }
    return {"texts": texts, "payloads": payloads, "manifest": manifest}


def write_pack(pack_dir: Path, assembled: dict[str, Any]) -> dict[str, Any]:
    """Write data files then the manifest (a reader never sees a half pack)."""
    pack_dir.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        (pack_dir / name).write_text(assembled["texts"][name], encoding="utf-8")
    (pack_dir / "manifest.json").write_text(
        _dumps(assembled["manifest"]), encoding="utf-8"
    )
    return assembled["manifest"]


def mirror_pack(pack_dir: Path, target: Path) -> Path:
    """Atomically replace the exported copy (re-publish replaces wholesale)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    staging = target.with_name(target.name + ".tmp")
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(pack_dir, staging)
    if target.exists():
        shutil.rmtree(target)
    staging.rename(target)
    return target


def run_stage(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    *,
    syllabus: dict[str, Any],
    graph: dict[str, Any],
    items_output: dict[str, Any],
    speaking_output: dict[str, Any],
    priors_output: dict[str, Any],
    run_id: str,
    generated_at: str,
    pack_dir: Path,
) -> dict[str, Any]:
    assembled = assemble(
        chapter=chapter,
        syllabus=syllabus,
        graph=graph,
        items_output=items_output,
        speaking_output=speaking_output,
        priors_output=priors_output,
        run_id=run_id,
        generated_at=generated_at,
    )
    manifest = write_pack(pack_dir, assembled)
    exported: str | None = None
    if cfg.export_dir is not None:
        exported = str(mirror_pack(pack_dir, cfg.export_dir / chapter["chapter_id"]))
    output = {
        "schema_version": 1,
        "stage": STAGE_ID,
        "chapter_id": chapter["chapter_id"],
        "pack_dir": str(pack_dir),
        "exported_dir": exported,
        "manifest": manifest,
        "files": sorted(list(DATA_FILES) + ["manifest.json"]),
        "gate": gate_report([]),
    }
    if manifest["gate"]["verdict"] != "pass":
        raise AssessmentGateError(
            "A6-publish-export refused: an upstream gate did not pass "
            f"({manifest['gate']['error_count']} blocking findings)",
            report=manifest["gate"],
            output=output,
        )
    return output


__all__ = [
    "DATA_FILES",
    "PACK_VERSION",
    "STAGE_ID",
    "assemble",
    "build_coverage",
    "content_hash",
    "flatten_questions",
    "flatten_speaking",
    "mirror_pack",
    "run_stage",
    "write_pack",
]
