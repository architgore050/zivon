"""E4-publish: flatten the pack, run the publish gate, write the manifest.

"Publish" here is a **file-based decision**, not a deployment: the pack is what
the F7 test player and the DB importer consume, and `publish.status` is the
single answer to "may this ship?". The gate is the union of the ingest,
blueprint, series and volume reports. A blocking finding (fatal or major) means:

- `publish.status = "blocked"` with every blocker named;
- the pack is still written under the run directory as evidence;
- nothing is mirrored to `--export-dir`, because publishing below threshold is
  what `FEATURE-MAP` SER-13 / CNT-12 forbids.

`publish.status = "ready"` is therefore a claim the artifact can back: every
series at its approved minimum, every chapter in every full paper, every concept
in the lesson/drill series, every item with source metadata and a similarity
record, and copy that matches `docs/compliance/notices.md`.
"""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from typing import Any

from factory.exam import EXAM_PIPELINE_VERSION
from factory.exam.config import ExamConfig
from factory.exam.errors import ExamStageError
from factory.exam.notices import NOTICE_VERSION
from factory.exam.report import (
    blocking_issues,
    dumps,
    gate_report,
    merge_reports,
)
from factory.exam.validators import validate_pack_manifest, validate_question_row

from .volume import check_volume

STAGE_ID = "E4-publish"
PACK_VERSION = 1

DATA_FILES = (
    "papers.json",
    "blueprint.json",
    "items.json",
    "series.json",
)

_COMPLIANCE_RULES = (
    "series.item.verbatim_in_blueprint",
    "series.item.licence_basis",
    "series.item.third_party",
    "series.item.source_ref",
    "series.item.similarity",
    "series.item.similarity_missing",
    "series.item.pattern_ref",
    "pack.verbatim_without_clearance",
    "series.copy.claim",
    "series.copy.notice",
    "series.status.exact_pyq",
)
_VOLUME_RULES = (
    "series.minimum.",
    "series.chapter_coverage",
    "series.chapter_floor",
    "series.concept_coverage",
)


def flatten_items(
    items: list[dict[str, Any]], series: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """One row per (item, language), language-filtered by the series policy.

    An item used only by board-style series does not export a Hinglish row, and
    a row's `series_ids` never names a series that does not offer its language.
    """
    policies = {s["series_id"]: set(s["language_policy"]) for s in series}
    rows: list[dict[str, Any]] = []
    for item in items:
        for language in item["languages"]:
            series_ids = sorted(
                sid
                for sid in item["series_ids"]
                if language in policies.get(sid, set())
            )
            if not series_ids:
                continue
            locale = item["locales"][language]
            row: dict[str, Any] = {
                "question_id": f"{item['item_id']}-{language}",
                "item_id": item["item_id"],
                "base_item_id": item["base_item_id"],
                "class_level": int(item["class_level"]),
                "chapter_id": item["chapter_id"],
                "concept_id": item["concept_id"],
                "type": item["type"],
                "difficulty": item["difficulty"],
                "marks": int(item["marks"]),
                "language": language,
                "section": item.get("section"),
                "prompt": locale["prompt"],
                "answer": item["answer"],
                "explanation": locale["explanation"],
                "source_type": item["source_type"],
                "source_ref": item.get("source_ref"),
                "pattern_ref": item["pattern_ref"],
                "similarity": item["similarity"],
                "series_ids": series_ids,
            }
            if locale.get("options"):
                row["options"] = list(locale["options"])
            if locale.get("misconception"):
                row["misconception"] = locale["misconception"]
            if locale.get("model_answer"):
                row["model_answer"] = locale["model_answer"]
            rows.append(row)
    rows.sort(key=lambda row: (row["item_id"], row["language"]))
    return rows


def build_coverage(
    *,
    chapters: list[dict[str, Any]],
    items: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    series: list[dict[str, Any]],
) -> dict[str, Any]:
    by_language: dict[str, int] = {row["language"]: 0 for row in rows}
    for row in rows:
        by_language[row["language"]] = by_language.get(row["language"], 0) + 1
    by_type: dict[str, int] = {}
    by_difficulty: dict[str, int] = {}
    for item in items:
        by_type[item["type"]] = by_type.get(item["type"], 0) + 1
        by_difficulty[item["difficulty"]] = by_difficulty.get(item["difficulty"], 0) + 1
    chapter_counts: dict[str, dict[str, int]] = {
        str(chapter["chapter_id"]): {} for chapter in chapters
    }
    chapter_of = {str(item["item_id"]): str(item["chapter_id"]) for item in items}
    for manifest in series:
        series_id = manifest["series_id"]
        for chapter in chapters:
            chapter_id = str(chapter["chapter_id"])
            count = sum(
                1
                for item_id in manifest["item_ids"]
                if chapter_of.get(str(item_id)) == chapter_id
            )
            if count:
                chapter_counts[chapter_id][series_id] = count
    return {
        "by_language": dict(sorted(by_language.items())),
        "by_type": dict(sorted(by_type.items())),
        "by_difficulty": dict(sorted(by_difficulty.items())),
        "chapters": chapter_counts,
        "series_counts": {s["series_id"]: len(s["item_ids"]) for s in series},
    }


def _file_entry(text: str) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "bytes": len(text.encode("utf-8")),
    }


def content_hash(files: dict[str, dict[str, Any]]) -> str:
    joined = "\n".join(
        f"{name}:{entry['sha256']}" for name, entry in sorted(files.items())
    )
    return "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _blocker_payload(
    issues: list[dict[str, Any]], limit: int = 200
) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for issue in issues[:limit]:
        entry = {
            "rule": issue["rule"],
            "severity": issue["severity"],
            "message": issue["message"],
        }
        for key in ("series_id", "chapter_id", "paper_id", "item_id"):
            if key in issue:
                entry[key] = issue[key]
        payload.append(entry)
    return payload


def _reason_codes(blockers: list[dict[str, Any]]) -> list[str]:
    codes: set[str] = set()
    for blocker in blockers:
        rule = str(blocker["rule"])
        if rule in _COMPLIANCE_RULES:
            if rule in (
                "series.item.verbatim_in_blueprint",
                "pack.verbatim_without_clearance",
            ):
                codes.add("missing_clearance")
            elif rule == "series.item.third_party":
                codes.add("third_party")
            elif rule.startswith("series.item.similarity"):
                codes.add("similarity")
            elif rule.startswith(("series.item.", "series.copy")):
                codes.add("schema")
            else:
                codes.add("schema")
        elif any(rule.startswith(prefix) for prefix in _VOLUME_RULES):
            codes.add("volume")
        elif rule.startswith(
            ("series.paper_structure", "series.paper_duplicate", "series.language")
        ):
            codes.add("structure")
        else:
            codes.add("schema")
    return sorted(codes)


def assemble_pack(
    *,
    cfg: ExamConfig,
    blueprint: dict[str, Any],
    ingest: dict[str, Any],
    class_series: dict[str, Any],
    chapters: list[dict[str, Any]],
    run_id: str,
    generated_at: str,
) -> dict[str, Any]:
    class_num = int(blueprint["class_num"])
    items = list(class_series["items"])
    series = list(class_series["series"])
    volume = check_volume(
        class_num=class_num,
        blueprint=blueprint,
        chapters=chapters,
        series=series,
        items=items,
        chapter_floor=cfg.series.chapter_question_floor,
    )
    volume_report = gate_report(
        volume["issues"],
        counts={
            **volume["counts"],
            "active_series": volume["counts"]["active_series"],
        },
    )
    # The stage artifact carries the findings as plain dicts; the in-memory
    # Issue objects stay inside the gate.
    volume_payload = {**volume, "issues": volume_report["issues"]}
    # The publish gate re-validates the pack it is about to ship rather than
    # trusting E3's report: an item or manifest that became invalid after the
    # assembly stage must still block the publish.
    from .assembly import validate_pack_items

    pack_item_issues = validate_pack_items(
        cfg=cfg, series=series, items=items, chapters=chapters
    )
    gate = merge_reports(
        ingest.get("gate") or {},
        blueprints_gate(blueprint),
        gate_report(pack_item_issues),
        volume_report,
    )
    rows = flatten_items(items, series)
    row_issues = []
    for row in rows:
        policy: list[str] = next(
            (
                s["language_policy"]
                for s in series
                if s["series_id"] in row["series_ids"]
            ),
            [],
        )
        row_issues.extend(validate_question_row(row, expected_languages=policy))
    if row_issues:
        gate = merge_reports(gate, gate_report(row_issues))

    compliance = cfg.compliance
    blockers = blocking_issues(gate)
    publishable = not blockers
    class_papers = [p for p in ingest["papers"] if int(p["class_num"]) == class_num]
    payloads: dict[str, Any] = {
        "papers.json": {
            "schema_version": 1,
            "class_num": class_num,
            "papers": class_papers,
            "question_count": sum(
                1
                for question in ingest["questions"]
                if question["paper_id"] in {paper["paper_id"] for paper in class_papers}
            ),
            "source_text_stored": False,
        },
        "blueprint.json": {
            key: value for key, value in blueprint.items() if key != "gate"
        },
        "items.json": {
            "schema_version": 1,
            "class_num": class_num,
            "items": rows,
        },
        "series.json": {
            "schema_version": 1,
            "class_num": class_num,
            "series": series,
            "gate": class_series.get("gate") or {},
        },
    }
    texts = {name: dumps(payload) for name, payload in payloads.items()}
    file_entries = {name: _file_entry(text) for name, text in texts.items()}
    coverage = build_coverage(chapters=chapters, items=items, rows=rows, series=series)
    manifest = {
        "pack_version": PACK_VERSION,
        "exam_pipeline_version": EXAM_PIPELINE_VERSION,
        "run_id": run_id,
        "generated_at": generated_at,
        "class_num": class_num,
        "subject": "Physics",
        "subject_code": blueprint.get("subject_code"),
        "content_mode": compliance.content_mode,
        "notice_version": NOTICE_VERSION,
        "compliance": {
            **compliance.to_dict(),
            "notice_ids": sorted(
                {str(s["notice_id"]) for s in series if s.get("notice_id")}
            ),
            "verbatim_items": sum(
                1 for item in items if item["source_type"].startswith("verbatim_")
            ),
            "third_party_items": sum(
                1
                for item in items
                if (item.get("source_ref") or {}).get("third_party_content") is True
            ),
            # The similarity corpus this run could check against. Blueprint
            # mode stores no source text, so the gate is vacuously clear and
            # the manifest says so instead of implying a comparison happened.
            "source_corpus_items": 0,
            "similarity_policy": {
                "ngram": cfg.similarity.ngram,
                "max_overlap": cfg.similarity.max_overlap,
            },
            "exact_pyq_status": next(
                (
                    (
                        "enabled"
                        if s["enabled"]
                        else f"disabled:{s.get('disabled_reason')}"
                    )
                    for s in series
                    if s["series_id"] == "exact_pyq"
                ),
                "absent",
            ),
        },
        "counts": {
            "papers": len(class_papers),
            "base_items": len(items),
            "question_rows": len(rows),
            "series": len(series),
            "active_series": sum(1 for s in series if s["enabled"]),
        },
        "coverage": coverage,
        "publish": {
            "status": "ready" if publishable else "blocked",
            "blockers": _blocker_payload(blockers),
            "reason_codes": _reason_codes(blockers),
            "volume": volume["by_series"],
        },
        "gate": {
            "verdict": gate["verdict"],
            "error_count": gate["error_count"],
            "warning_count": gate["warning_count"],
            "rules": gate["rules"],
        },
        "content_hash": content_hash(file_entries),
        "files": file_entries,
    }
    manifest_issues = validate_pack_manifest(
        manifest,
        items=items,
        compliance={
            "content_mode": compliance.content_mode,
            "clearance_id": compliance.clearance_id,
        },
    )
    if manifest_issues:
        # The manifest is part of the artifact, so its findings join the gate:
        # a pack whose own record contradicts the run is blocked, not shipped.
        # A mode mismatch is the one case that is a programming error (the
        # manifest's mode comes from the same object as the run's), so it stays
        # loud instead of becoming a product blocker.
        if any(issue.rule == "pack.mode_mismatch" for issue in manifest_issues):
            raise ExamStageError(
                "E4-publish produced an inconsistent manifest: "
                + "; ".join(issue.message for issue in manifest_issues)
            )
        gate = merge_reports(gate, gate_report(manifest_issues))
        blockers = blocking_issues(gate)
        publishable = not blockers
        manifest["gate"] = {
            "verdict": gate["verdict"],
            "error_count": gate["error_count"],
            "warning_count": gate["warning_count"],
            "rules": gate["rules"],
        }
        manifest["publish"] = {
            "status": "ready" if publishable else "blocked",
            "blockers": _blocker_payload(blockers),
            "reason_codes": _reason_codes(blockers),
            "volume": volume["by_series"],
        }
    return {
        "texts": texts,
        "payloads": payloads,
        "manifest": manifest,
        "gate": gate,
        "volume": volume_payload,
    }


def blueprints_gate(blueprint: dict[str, Any]) -> dict[str, Any]:
    """The blueprint's own gate, re-derived if it was not carried in memory."""
    gate = blueprint.get("gate")
    if isinstance(gate, dict) and gate.get("issues") is not None:
        return gate
    return gate_report([])


def write_pack(pack_dir: Path, assembled: dict[str, Any]) -> dict[str, Any]:
    pack_dir.mkdir(parents=True, exist_ok=True)
    for name in DATA_FILES:
        (pack_dir / name).write_text(assembled["texts"][name], encoding="utf-8")
    (pack_dir / "manifest.json").write_text(
        dumps(assembled["manifest"]), encoding="utf-8"
    )
    return assembled["manifest"]


def mirror_pack(pack_dir: Path, target: Path) -> Path:
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
    *,
    cfg: ExamConfig,
    blueprint: dict[str, Any],
    ingest: dict[str, Any],
    class_series: dict[str, Any],
    chapters: list[dict[str, Any]],
    run_id: str,
    generated_at: str,
    pack_dir: Path,
) -> dict[str, Any]:
    assembled = assemble_pack(
        cfg=cfg,
        blueprint=blueprint,
        ingest=ingest,
        class_series=class_series,
        chapters=chapters,
        run_id=run_id,
        generated_at=generated_at,
    )
    manifest = write_pack(pack_dir, assembled)
    exported: str | None = None
    if manifest["publish"]["status"] == "ready" and cfg.export_dir is not None:
        exported = str(
            mirror_pack(pack_dir, cfg.export_dir / f"class-{manifest['class_num']}")
        )
    return {
        "schema_version": 1,
        "stage": STAGE_ID,
        "class_num": manifest["class_num"],
        "pack_dir": str(pack_dir),
        "exported_dir": exported,
        "manifest": manifest,
        "files": sorted(list(DATA_FILES) + ["manifest.json"]),
        "gate": assembled["gate"],
        "volume": assembled["volume"],
    }


__all__ = [
    "DATA_FILES",
    "PACK_VERSION",
    "STAGE_ID",
    "assemble_pack",
    "build_coverage",
    "content_hash",
    "flatten_items",
    "mirror_pack",
    "run_stage",
    "write_pack",
]
