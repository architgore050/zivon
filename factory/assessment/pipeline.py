"""Assessment-pipeline orchestrator (`python -m factory.assessment`).

One run per chapter (`assessment-<chapter_id>`), stages A1-A6, the same
run-artifact discipline as the lesson factory: every stage writes
`runs/assessment/<run_id>/<stage>/output.json`, `status.json` carries each
stage's state and measured time, and a deterministic fingerprint refuses to
resume a directory produced under a different graph or different inputs.

The entrypoint is separate on purpose (Q-1): a lesson run must never spend
assessment credits, and stopping an assessment run must never touch a
published page.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from factory.artifacts import RunContext, wipe_run
from logging_manager import ErrorClass, bind_context, log_event

from . import ASSESSMENT_PIPELINE_VERSION, ASSESSMENT_STAGE_ORDER
from . import concepts as concepts_stage
from . import items as items_stage
from . import pack as pack_stage
from . import speaking as speaking_stage
from . import syllabus as syllabus_stage
from . import timepriors as priors_stage
from .config import AssessmentConfig
from .errors import AssessmentError, AssessmentGateError, AssessmentStageError
from .validators import ItemGatePolicy

_REASON_CODES = {
    "A1-syllabus": "syllabus_invalid",
    "A2-concept-tag": "concept_graph_invalid",
    "A3-practice-items": "practice_gate_failed",
    "A4-speaking-rubrics": "rubric_gate_failed",
    "A5-time-priors": "time_prior_gate_failed",
    "A6-publish-export": "pack_refused",
}


def make_run_id(chapter_id: str) -> str:
    return f"assessment-{chapter_id}"


def _policy_payload(policy: ItemGatePolicy) -> dict[str, Any]:
    return {
        "min_items": policy.min_items,
        "max_items": policy.max_items,
        "min_type_counts": dict(policy.min_type_counts),
        "difficulty_share": {
            key: list(value) for key, value in policy.difficulty_share.items()
        },
        "max_items_per_concept": policy.max_items_per_concept,
        "speaking_prompts_min": policy.speaking_prompts_min,
        "time_prior_min_ms": policy.time_prior_min_ms,
        "time_prior_max_ms": policy.time_prior_max_ms,
    }


def _file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_fingerprint(
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    syllabus_sha: str,
    lesson_manifest_sha: str | None,
) -> str:
    """What a run dir's artifacts are valid FOR.

    Inputs = the assessment graph version, the chapter identity, the syllabus
    digest, the tracked chapter data (items / speaking / concept map), the
    lesson manifest A2 consumed, the generator and - only for live generation -
    the model name. Repair-round caps are runtime policy and stay out (tuning
    them must not invalidate good work).
    """
    payload: dict[str, Any] = {
        "assessment_pipeline_version": ASSESSMENT_PIPELINE_VERSION,
        "chapter_id": chapter["chapter_id"],
        "syllabus_sha256": syllabus_sha,
        "items_sha256": _file_sha(cfg.chapter_items_path(chapter["chapter_id"])),
        "speaking_sha256": _file_sha(cfg.chapter_speaking_path(chapter["chapter_id"])),
        "concept_map_sha256": _file_sha(
            concepts_stage.concept_map_path(cfg, chapter["chapter_id"])
        ),
        "lesson_manifest_sha256": lesson_manifest_sha,
        "generator": cfg.generator,
        "languages": list(cfg.languages),
        "policy": _policy_payload(cfg.policy),
    }
    if cfg.generator == "llm" and cfg.model_cfg is not None:
        payload["model"] = cfg.model_cfg.server.get("model")
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _lesson_manifest_sha(cfg: AssessmentConfig, chapter: dict[str, Any]) -> str | None:
    slug = chapter.get("lesson_topic_slug")
    if not slug:
        return None
    path = (
        cfg.frontend_dir
        / "courses"
        / f"class-{chapter['class']}-physics"
        / slug
        / "manifest.json"
    )
    return _file_sha(path)


def _stage_dir_path(run_ctx: RunContext, stage_id: str) -> Path:
    return run_ctx.stage_dir(stage_id)


def _run_one_stage(
    stage_id: str,
    cfg: AssessmentConfig,
    chapter: dict[str, Any],
    run_ctx: RunContext,
    *,
    llm_client: Any | None,
    generated_at: str,
) -> dict[str, Any]:
    if stage_id == "A1-syllabus":
        return syllabus_stage.run_stage(cfg)
    syllabus_output = run_ctx.load_stage_output("A1-syllabus")
    if stage_id == "A2-concept-tag":
        return concepts_stage.run_stage(cfg, chapter)
    graph = run_ctx.load_stage_output("A2-concept-tag")
    if stage_id == "A3-practice-items":
        return items_stage.run_stage(cfg, chapter, llm_client=llm_client)
    items_output = run_ctx.load_stage_output("A3-practice-items")
    if stage_id == "A4-speaking-rubrics":
        return speaking_stage.run_stage(cfg, chapter, llm_client=llm_client)
    speaking_output = run_ctx.load_stage_output("A4-speaking-rubrics")
    if stage_id == "A5-time-priors":
        return priors_stage.run_stage(cfg, chapter, items_output)
    priors_output = run_ctx.load_stage_output("A5-time-priors")
    if stage_id == "A6-publish-export":
        return pack_stage.run_stage(
            cfg,
            chapter,
            syllabus=syllabus_output["syllabus"],
            graph=graph,
            items_output=items_output,
            speaking_output=speaking_output,
            priors_output=priors_output,
            run_id=run_ctx.run_id,
            generated_at=generated_at,
            pack_dir=_stage_dir_path(run_ctx, "A6-publish-export") / "pack",
        )
    raise AssessmentStageError(f"unknown assessment stage {stage_id!r}")


def run_assessment(
    cfg: AssessmentConfig,
    chapter_ids: list[str],
    *,
    fresh: bool = False,
    only_stages: list[str] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Run A1-A6 for one or more chapters. Returns a summary per chapter."""
    if not chapter_ids:
        raise AssessmentStageError("no chapter requested")
    unknown = [s for s in (only_stages or []) if s not in ASSESSMENT_STAGE_ORDER]
    if unknown:
        raise AssessmentStageError(
            f"unknown assessment stage(s) {unknown}. Valid: {ASSESSMENT_STAGE_ORDER}"
        )
    stages = only_stages or ASSESSMENT_STAGE_ORDER
    # A1 is the syllabus for the whole manifest; validating it once per chapter
    # is cheap and keeps every run self-contained (each run dir carries its own
    # A1 evidence).
    if "A1-syllabus" not in stages:
        stages = ["A1-syllabus", *stages]

    results: list[dict[str, Any]] = []
    for chapter_id in chapter_ids:
        results.append(
            _run_chapter(
                cfg,
                chapter_id,
                fresh=fresh,
                stages=stages,
                run_id=run_id,
            )
        )
    return {
        "ok": all(r["ok"] for r in results),
        "assessment_pipeline_version": ASSESSMENT_PIPELINE_VERSION,
        "runs": results,
    }


def _run_chapter(
    cfg: AssessmentConfig,
    chapter_id: str,
    *,
    fresh: bool,
    stages: list[str],
    run_id: str | None,
) -> dict[str, Any]:
    syllabus = syllabus_stage.load_syllabus(cfg)
    chapter = syllabus_stage.require_chapter(syllabus, chapter_id)
    syllabus_stage.require_curated(chapter)
    run_id = run_id or make_run_id(chapter_id)
    bind_context(run_id=run_id)
    cfg.runs_dir.mkdir(parents=True, exist_ok=True)
    if fresh and wipe_run(cfg.runs_dir, run_id):
        print(f"[resume] --fresh: previous assessment run '{run_id}' wiped")
    run_ctx = RunContext(cfg.runs_dir, run_id)
    fingerprint = run_fingerprint(
        cfg,
        chapter,
        syllabus_stage.syllabus_sha256(syllabus),
        _lesson_manifest_sha(cfg, chapter),
    )
    resume = False
    if run_ctx.status_exists():
        saved = run_ctx.get_fingerprint()
        if saved != fingerprint:
            raise AssessmentStageError(
                f"assessment run '{run_id}' exists with a different fingerprint "
                f"({saved or 'pre-fingerprint'}). Refusing to mix artifacts: "
                "pass --fresh (or --run-id <new-name>)."
            )
        resume = True
        completed = [s for s in stages if run_ctx.stage_ok(s)]
        if completed:
            print(
                f"[resume] run '{run_id}': reusing {len(completed)} completed "
                f"stage(s) {completed}"
            )
    run_ctx.set_fingerprint(fingerprint)
    log_event(
        "factory.assessment.run.started",
        {
            "chapter_id": chapter_id,
            "class_level": chapter["class"],
            "generator": cfg.generator,
            "languages": ",".join(cfg.languages),
            "fresh": fresh,
            "resumed": resume,
        },
    )
    t0 = time.monotonic()
    llm_client = None
    if cfg.generator == "llm":
        if cfg.model_cfg is None:
            raise AssessmentStageError(
                "generator=llm needs the factory Config (model endpoint) - "
                "set ZIVON_BASE_URL and ZIVON_MODEL"
            )
        from factory.llm import LLMClient

        llm_client = LLMClient(cfg.model_cfg, run_ctx)
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")

    current_stage = stages[0]
    try:
        for stage_id in stages:
            current_stage = stage_id
            if run_ctx.stage_ok(stage_id):
                print(f"[{stage_id}] ok (resumed)")
                continue
            run_ctx.mark_stage(stage_id, "running")
            output = _run_one_stage(
                stage_id,
                cfg,
                chapter,
                run_ctx,
                llm_client=llm_client,
                generated_at=generated_at,
            )
            run_ctx.save_stage_output(stage_id, output)
            run_ctx.mark_stage(
                stage_id,
                "ok",
                detail=_stage_detail(stage_id, output),
                blocks=int((output.get("counts") or {}).get("items", 0)),
            )
            if stage_id == "A6-publish-export":
                manifest = output["manifest"]
                log_event(
                    "factory.assessment.pack.written",
                    {
                        "chapter_id": chapter_id,
                        "base_items": manifest["counts"]["base_items"],
                        "question_rows": manifest["counts"]["question_rows"],
                        "content_hash": manifest["content_hash"],
                        "exported": bool(output.get("exported_dir")),
                    },
                )
    except AssessmentGateError as exc:
        run_ctx.save_stage_output(current_stage, exc.output)
        run_ctx.mark_stage(
            current_stage,
            "failed",
            detail=_gate_detail(exc.report),
            reason_code=_REASON_CODES.get(current_stage, "assessment_gate"),
            error_class=ErrorClass.GATE_FAIL,
        )
        run_ctx.finish(False, detail=f"{current_stage}: {_gate_detail(exc.report)}")
        log_event(
            "factory.assessment.run.failed",
            {
                "failed_stage": current_stage,
                "reason_code": _REASON_CODES.get(current_stage, "assessment_gate"),
                "error_count": exc.report.get("error_count", 0),
            },
            error_class=ErrorClass.GATE_FAIL,
        )
        raise
    except AssessmentError as exc:
        run_ctx.mark_stage(
            current_stage,
            "failed",
            detail=str(exc)[:200],
            reason_code="stage_error",
            error_class=ErrorClass.VALIDATION_ERROR,
        )
        run_ctx.finish(False, detail=f"{current_stage}: {exc}")
        log_event(
            "factory.assessment.run.failed",
            {
                "failed_stage": current_stage,
                "reason_code": "stage_error",
                "error_count": 1,
            },
            error_class=ErrorClass.VALIDATION_ERROR,
        )
        raise

    run_ctx.finish(True)
    a6 = run_ctx.load_stage_output("A6-publish-export")
    a3 = run_ctx.load_stage_output("A3-practice-items")
    a4 = run_ctx.load_stage_output("A4-speaking-rubrics")
    elapsed_ms = int((time.monotonic() - t0) * 1000)
    log_event(
        "factory.assessment.run.completed",
        {
            "chapters_count": 1,
            "items_count": len(a3["items"]),
            "speaking_prompts_count": len(a4["prompts"]),
            "question_rows": a6["manifest"]["counts"]["question_rows"],
            "content_hash": a6["manifest"]["content_hash"],
        },
        latency_ms=elapsed_ms,
    )
    print(
        f"\n[assessment] {chapter_id}: {len(a3['items'])} items, "
        f"{len(a4['prompts'])} speaking prompts, "
        f"{a6['manifest']['counts']['question_rows']} question rows -> "
        f"{a6['pack_dir']}"
    )
    return {
        "ok": True,
        "chapter_id": chapter_id,
        "run_id": run_id,
        "items": len(a3["items"]),
        "speaking_prompts": len(a4["prompts"]),
        "question_rows": a6["manifest"]["counts"]["question_rows"],
        "content_hash": a6["manifest"]["content_hash"],
        "pack_dir": a6["pack_dir"],
        "exported_dir": a6.get("exported_dir"),
        "stage_durations_s": run_ctx.stage_durations(),
    }


def _stage_detail(stage_id: str, output: dict[str, Any]) -> str:
    counts = output.get("counts") or {}
    if stage_id == "A1-syllabus":
        return (
            f"{counts.get('chapters', 0)} chapters, "
            f"{counts.get('concepts', 0)} concepts"
        )
    if stage_id == "A2-concept-tag":
        return (
            f"{counts.get('blocks_tagged', 0)}/{counts.get('blocks', 0)} blocks tagged"
        )
    if stage_id == "A3-practice-items":
        return (
            f"{counts.get('items', 0)} items, "
            f"{output.get('gate', {}).get('warning_count', 0)} warnings"
        )
    if stage_id == "A4-speaking-rubrics":
        return f"{counts.get('prompts', 0)} prompts"
    if stage_id == "A5-time-priors":
        return f"{counts.get('question_rows', 0)} priors"
    if stage_id == "A6-publish-export":
        manifest = output.get("manifest") or {}
        return (
            f"pack {manifest.get('content_hash', '')[:19]}, "
            f"{manifest.get('counts', {}).get('question_rows', 0)} rows"
        )
    return ""


def _gate_detail(report: dict[str, Any]) -> str:
    rules = sorted(
        {
            issue["rule"]
            for issue in report.get("issues", [])
            if issue["severity"] in ("fatal", "major")
        }
    )
    return f"{report.get('error_count', 0)} blocking findings" + (
        f" ({', '.join(rules[:4])})" if rules else ""
    )


def assemble_chapter_pack(
    cfg: AssessmentConfig,
    chapter_id: str,
    *,
    run_id: str = "assessment-preview",
    generated_at: str = "1970-01-01T00:00:00+00:00",
) -> dict[str, Any]:
    """Run A1-A6's pure logic in memory (no run dir, no model, no gate skips).

    Used by the deterministic eval checkers and the unit tests: the same stage
    functions the orchestrator runs, with the same gates, so an eval cannot
    drift from the pipeline it claims to measure.
    """
    syllabus = syllabus_stage.load_syllabus(cfg)
    chapter = syllabus_stage.require_chapter(syllabus, chapter_id)
    syllabus_stage.require_curated(chapter)
    syllabus_output = syllabus_stage.run_stage(cfg)
    graph = concepts_stage.run_stage(cfg, chapter)
    items_output = items_stage.run_stage(cfg, chapter)
    speaking_output = speaking_stage.run_stage(cfg, chapter)
    priors_output = priors_stage.run_stage(cfg, chapter, items_output)
    assembled = pack_stage.assemble(
        chapter=chapter,
        syllabus=syllabus_output["syllabus"],
        graph=graph,
        items_output=items_output,
        speaking_output=speaking_output,
        priors_output=priors_output,
        run_id=run_id,
        generated_at=generated_at,
    )
    return {
        "chapter": chapter,
        "syllabus": syllabus,
        "graph": graph,
        "items": items_output,
        "speaking": speaking_output,
        "priors": priors_output,
        "assembled": assembled,
    }


__all__ = [
    "assemble_chapter_pack",
    "make_run_id",
    "run_assessment",
    "run_fingerprint",
]
