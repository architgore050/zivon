"""The exam/series orchestrator (`python -m factory.exam`).

One run per class (`exam-class-<n>`): E1 ingests the tracked paper metadata,
E2 derives the blueprint, E3 assembles the six series, E4 writes the pack and
the publish decision. The run-artifact discipline is the repo's
(`runs/exam/<run_id>/<stage>/output.json`, `status.json`, deterministic
fingerprint, resume), for the same reasons: a re-trigger resumes completed
stages, and a stage failure never re-runs the whole pipeline.

Why a separate entrypoint (like `factory.assessment`): a lesson run must never
spend exam-pipeline work, an assessment re-run must never re-derive a series
pack, and stopping a series rebuild must never touch a published page.

Publishing is a *decision recorded in the pack*, not a deployment. A blocked
pack still writes its evidence under the run directory; it is never mirrored to
`--export-dir`. The CLI exits non-zero only with `--require-publishable`, which
is what a CI/admin gate should use.
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

from . import EXAM_PIPELINE_VERSION, EXAM_STAGE_ORDER
from . import blueprint as blueprint_stage
from . import ingest as ingest_stage
from .config import ExamConfig
from .errors import ExamError, ExamGateError, ExamStageError
from .syllabus import chapters_for_class, load_syllabus

_STAGE_IDS = {
    "E1-ingest": "ingest_failed",
    "E2-blueprint": "blueprint_invalid",
    "E3-series": "series_gate_failed",
    "E4-publish": "pack_refused",
}


def make_run_id(class_num: int) -> str:
    return f"exam-class-{class_num}"


def _file_sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_fingerprint(cfg: ExamConfig, class_num: int, syllabus_sha: str) -> str:
    """What a run directory's artifacts are valid FOR."""
    papers = (
        sorted((path.name, _file_sha(path)) for path in cfg.papers_dir.glob("*.json"))
        if cfg.papers_dir.exists()
        else []
    )
    # The series are assembled from the P2 item banks, so a bank edit must
    # invalidate a resumed E3/E4 exactly like a paper-fixture edit does.
    item_banks = (
        sorted(
            (path.name, _file_sha(path))
            for path in cfg.chapters_dir.glob("*.items.json")
        )
        if cfg.chapters_dir.exists()
        else []
    )
    payload: dict[str, Any] = {
        "exam_pipeline_version": EXAM_PIPELINE_VERSION,
        "class_num": class_num,
        "syllabus_sha256": syllabus_sha,
        "papers": papers,
        "item_banks": item_banks,
        "content_mode": cfg.compliance.content_mode,
        "clearance_id": cfg.compliance.clearance_id,
        "exact_pyq_enabled": cfg.compliance.exact_pyq_enabled,
        "blueprint": {
            "years_window": cfg.blueprint.years_window,
            "recency_decay": cfg.blueprint.recency_decay,
            "include_paper_types": list(cfg.blueprint.include_paper_types),
        },
        "series": {
            "chapter_question_floor": cfg.series.chapter_question_floor,
            "chapter_test_size": cfg.series.chapter_test_size,
            "mixed_test_size": cfg.series.mixed_test_size,
            "unit_test_size": cfg.series.unit_test_size,
            "set_size": cfg.series.set_size,
        },
        "similarity": {
            "ngram": cfg.similarity.ngram,
            "max_overlap": cfg.similarity.max_overlap,
        },
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _syllabus_sha(path: Path) -> str:
    digest = _file_sha(path)
    if digest is None:
        raise ExamStageError(f"syllabus not found at {path}")
    return digest


def _load_stage(run_ctx: RunContext, stage_id: str, class_num: int) -> dict[str, Any]:
    output = run_ctx.load_stage_output(stage_id)
    actual = output.get("class_num")
    if actual is not None and int(actual) != int(class_num):
        raise ExamStageError(
            f"{stage_id} output belongs to class {actual}, not {class_num}; refusing "
            "to mix two classes' artifacts (pass --fresh)"
        )
    return output


def assemble_class_pack(
    cfg: ExamConfig, class_num: int, *, generated_at: str | None = None
) -> dict[str, Any]:
    """Run E1-E4 in memory (no run directory, no events) and return the artifacts.

    The deterministic evals and the unit tests use this: it is the same code
    path the entrypoint runs, minus the artifact/event plumbing, so a checker
    cannot drift from the pipeline it measures.
    """
    generated_at = generated_at or datetime.now(UTC).isoformat(timespec="seconds")
    ingest = ingest_stage.run_stage(cfg)
    syll = load_syllabus(cfg.syllabus_path)
    chapters = chapters_for_class(syll, class_num)
    if not chapters:
        raise ExamStageError(f"class {class_num} has no chapters in the syllabus")
    blueprint = blueprint_stage.build_blueprint(
        ingest, class_num=class_num, chapters=chapters, policy=cfg.blueprint
    )
    from factory.series.assembly import assemble_class
    from factory.series.publish import assemble_pack

    class_series = assemble_class(
        cfg,
        blueprint=blueprint,
        ingest=ingest,
        chapters=chapters,
        generated_at=generated_at,
    )
    pack = assemble_pack(
        cfg=cfg,
        blueprint=blueprint,
        ingest=ingest,
        class_series=class_series,
        chapters=chapters,
        run_id=make_run_id(class_num),
        generated_at=generated_at,
    )
    return {
        "class_num": class_num,
        "ingest": ingest,
        "blueprint": blueprint,
        "series": class_series,
        "pack": pack,
    }


def _stage_detail(stage_id: str, output: dict[str, Any]) -> str:
    if stage_id == "E1-ingest":
        return (
            f"{output['counts']['papers']} papers, "
            f"{output['counts']['questions']} question rows"
        )
    if stage_id == "E2-blueprint":
        return (
            f"{len(output['chapters'])} chapters, "
            f"{len(output['papers_used'])} papers used"
        )
    if stage_id == "E3-series":
        return f"{len(output['series'])} series, {len(output['items'])} items"
    manifest = output["manifest"]
    return (
        f"{manifest['counts']['question_rows']} question rows, "
        f"publish {manifest['publish']['status']}"
    )


def _stage_blocks(stage_id: str, output: dict[str, Any]) -> int:
    if stage_id != "E3-series":
        return 0
    return len(output.get("items") or [])


def _run_one_stage(
    stage_id: str,
    cfg: ExamConfig,
    class_num: int,
    chapters: list[dict[str, Any]],
    run_ctx: RunContext,
    *,
    generated_at: str,
) -> dict[str, Any]:
    if stage_id == "E1-ingest":
        return ingest_stage.run_stage(cfg)
    if stage_id == "E2-blueprint":
        return blueprint_stage.build_blueprint(
            _load_stage(run_ctx, "E1-ingest", class_num),
            class_num=class_num,
            chapters=chapters,
            policy=cfg.blueprint,
        )
    if stage_id == "E3-series":
        from factory.series.assembly import assemble_class

        return assemble_class(
            cfg,
            blueprint=_load_stage(run_ctx, "E2-blueprint", class_num),
            ingest=_load_stage(run_ctx, "E1-ingest", class_num),
            chapters=chapters,
            generated_at=generated_at,
        )
    if stage_id == "E4-publish":
        from factory.series.publish import run_stage as publish_run_stage

        return publish_run_stage(
            cfg=cfg,
            blueprint=_load_stage(run_ctx, "E2-blueprint", class_num),
            ingest=_load_stage(run_ctx, "E1-ingest", class_num),
            class_series=_load_stage(run_ctx, "E3-series", class_num),
            chapters=chapters,
            run_id=run_ctx.run_id,
            generated_at=generated_at,
            pack_dir=run_ctx.stage_dir("E4-publish") / "pack",
        )
    raise ExamStageError(f"unknown exam stage {stage_id!r}")


def run_exam(
    cfg: ExamConfig,
    class_nums: list[int],
    *,
    fresh: bool = False,
    only_stages: list[str] | None = None,
    run_id: str | None = None,
    require_publishable: bool = False,
) -> dict[str, Any]:
    if not class_nums:
        raise ExamStageError("no class requested")
    unknown = [s for s in (only_stages or []) if s not in EXAM_STAGE_ORDER]
    if unknown:
        raise ExamStageError(
            f"unknown exam stage(s) {unknown}. Valid: {list(EXAM_STAGE_ORDER)}"
        )
    stages = list(only_stages or EXAM_STAGE_ORDER)
    if "E1-ingest" not in stages:
        stages = ["E1-ingest", *stages]
    results = [
        _run_class(
            cfg,
            class_num,
            fresh=fresh,
            stages=stages,
            run_id=run_id,
            require_publishable=require_publishable,
        )
        for class_num in class_nums
    ]
    return {
        "ok": all(result["ok"] for result in results),
        "exam_pipeline_version": EXAM_PIPELINE_VERSION,
        "runs": results,
    }


def _run_class(
    cfg: ExamConfig,
    class_num: int,
    *,
    fresh: bool,
    stages: list[str],
    run_id: str | None,
    require_publishable: bool,
) -> dict[str, Any]:
    syll = load_syllabus(cfg.syllabus_path)
    chapters = chapters_for_class(syll, class_num)
    if not chapters:
        raise ExamStageError(f"class {class_num} has no chapters in the syllabus")
    resolved_run_id = run_id or make_run_id(class_num)
    bind_context(run_id=resolved_run_id)
    cfg.runs_dir.mkdir(parents=True, exist_ok=True)
    if fresh and wipe_run(cfg.runs_dir, resolved_run_id):
        print(f"[resume] --fresh: previous exam run '{resolved_run_id}' wiped")
    run_ctx = RunContext(cfg.runs_dir, resolved_run_id)
    fingerprint = run_fingerprint(cfg, class_num, _syllabus_sha(cfg.syllabus_path))
    resumed = False
    if run_ctx.status_exists():
        saved = run_ctx.get_fingerprint()
        if saved != fingerprint:
            raise ExamStageError(
                f"exam run '{resolved_run_id}' exists with a different fingerprint "
                f"({saved or 'pre-fingerprint'}). Refusing to mix artifacts: pass "
                "--fresh (or --run-id <new-name>)."
            )
        resumed = True
        completed = [stage for stage in stages if run_ctx.stage_ok(stage)]
        if completed:
            print(
                f"[resume] run '{resolved_run_id}': reusing {len(completed)} "
                f"completed stage(s) {completed}"
            )
    run_ctx.set_fingerprint(fingerprint)
    log_event(
        "factory.exam.run.started",
        {
            "class_level": class_num,
            "content_mode": cfg.compliance.content_mode,
            "exact_pyq_enabled": cfg.compliance.exact_pyq_visible,
            "clearance_id": cfg.compliance.clearance_id or "none",
            "fresh": fresh,
            "resumed": resumed,
        },
    )
    started = time.monotonic()
    generated_at = datetime.now(UTC).isoformat(timespec="seconds")
    current_stage = stages[0]
    publishable = False
    content_hash = ""
    question_rows = 0
    items_count = 0
    series_count = 0
    papers_count = 0
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
                class_num,
                chapters,
                run_ctx,
                generated_at=generated_at,
            )
            run_ctx.save_stage_output(stage_id, output)
            run_ctx.mark_stage(
                stage_id,
                "ok",
                detail=_stage_detail(stage_id, output),
                blocks=_stage_blocks(stage_id, output),
                attempts=0,
            )
            if stage_id == "E1-ingest":
                class_paper_ids = {
                    str(paper["paper_id"])
                    for paper in output["papers"]
                    if int(paper["class_num"]) == class_num
                }
                papers_count = len(class_paper_ids)
                for question in output["questions"]:
                    if question["paper_id"] not in class_paper_ids:
                        continue
                    log_event(
                        "exam.item.ingested",
                        {
                            "paper_id": question["paper_id"],
                            "class_level": class_num,
                            "chapter_id": question["chapter_id"],
                            "type": question["type"],
                            "marks": question["marks"],
                        },
                    )
            elif stage_id == "E3-series":
                items_count = len(output["items"])
                series_count = len(output["series"])
            elif stage_id == "E4-publish":
                manifest = output["manifest"]
                publishable = manifest["publish"]["status"] == "ready"
                content_hash = manifest["content_hash"]
                question_rows = int(manifest["counts"]["question_rows"])
                log_event(
                    "factory.exam.pack.written",
                    {
                        "class_level": class_num,
                        "base_items": manifest["counts"]["base_items"],
                        "question_rows": question_rows,
                        "publishable": publishable,
                        "content_hash": content_hash,
                    },
                )
                _emit_publish_blocked(class_num, manifest)
            _invalidate_downstream(run_ctx, stage_id)
    except ExamGateError as exc:
        run_ctx.save_stage_output(current_stage, exc.output)
        run_ctx.mark_stage(
            current_stage,
            "failed",
            detail=_gate_detail(exc.report),
            reason_code=_STAGE_IDS.get(current_stage, "exam_gate"),
            error_class=ErrorClass.GATE_FAIL,
        )
        run_ctx.finish(False, detail=f"{current_stage}: {_gate_detail(exc.report)}")
        log_event(
            "factory.exam.run.failed",
            {
                "failed_stage": current_stage,
                "reason_code": _STAGE_IDS.get(current_stage, "exam_gate"),
                "error_count": int(exc.report.get("error_count", 0)),
            },
            error_class=ErrorClass.GATE_FAIL,
        )
        raise
    except ExamError as exc:
        run_ctx.mark_stage(
            current_stage,
            "failed",
            detail=str(exc)[:200],
            reason_code="stage_error",
            error_class=ErrorClass.VALIDATION_ERROR,
        )
        run_ctx.finish(False, detail=f"{current_stage}: {exc}")
        log_event(
            "factory.exam.run.failed",
            {
                "failed_stage": current_stage,
                "reason_code": "stage_error",
                "error_count": 1,
            },
            error_class=ErrorClass.VALIDATION_ERROR,
        )
        raise

    # A fully resumed class run never re-enters the stage bodies, so the
    # summary must be rebuilt from the artifacts on disk (the same rule the
    # assessment pipeline follows). A partial run reports only what it has.
    e1 = (
        _local_stage_output(run_ctx, "E1-ingest")
        if "E1-ingest" in stages and run_ctx.stage_ok("E1-ingest")
        else None
    )
    if e1 is not None:
        papers_count = sum(
            1 for paper in e1["papers"] if int(paper["class_num"]) == class_num
        )
    e3 = (
        _local_stage_output(run_ctx, "E3-series")
        if "E3-series" in stages and run_ctx.stage_ok("E3-series")
        else None
    )
    if e3 is not None:
        items_count = len(e3.get("items") or [])
        series_count = len(e3.get("series") or [])
    e4 = (
        _local_stage_output(run_ctx, "E4-publish")
        if "E4-publish" in stages and run_ctx.stage_ok("E4-publish")
        else None
    )
    if e4 is not None:
        e4 = _export_resumed_pack(cfg, class_num, run_ctx, e4)
        manifest = e4["manifest"]
        publishable = manifest["publish"]["status"] == "ready"
        content_hash = str(manifest["content_hash"])
        question_rows = int(manifest["counts"]["question_rows"])

    blocked_by_requirement = require_publishable and not publishable
    # The run ledger must not say "ok" for a run the operator's gate rejected:
    # `--require-publishable` makes the publish block a failed run, not a
    # successful run with a warning.
    run_ctx.finish(
        not blocked_by_requirement,
        detail=(
            f"publish gate: class {class_num} pack is blocked (--require-publishable)"
            if blocked_by_requirement
            else ""
        ),
    )
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if blocked_by_requirement:
        log_event(
            "factory.exam.run.failed",
            {
                "failed_stage": "E4-publish",
                "reason_code": _STAGE_IDS["E4-publish"],
                "error_count": 1,
            },
            error_class=ErrorClass.GATE_FAIL,
        )
    else:
        log_event(
            "factory.exam.run.completed",
            {
                "class_level": class_num,
                "papers_count": papers_count,
                "items_count": items_count,
                "series_count": series_count,
                "question_rows": question_rows,
                "publishable": publishable,
                "content_hash": content_hash,
            },
            latency_ms=elapsed_ms,
        )
    result = {
        "ok": publishable or not require_publishable,
        "class_num": class_num,
        "run_id": resolved_run_id,
        "papers": papers_count,
        "items": items_count,
        "series": series_count,
        "question_rows": question_rows,
        "publishable": publishable,
        "content_hash": content_hash,
        "pack_dir": str(run_ctx.stage_dir("E4-publish") / "pack"),
    }
    if blocked_by_requirement:
        raise ExamStageError(
            f"class {class_num}: the pack is not publishable "
            f"({question_rows} question rows); see the pack manifest's blockers"
        )
    return result


def _local_stage_output(run_ctx: RunContext, stage_id: str) -> dict[str, Any] | None:
    path = run_ctx.stage_dir(stage_id) / "output.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _export_resumed_pack(
    cfg: ExamConfig,
    class_num: int,
    run_ctx: RunContext,
    output: dict[str, Any],
) -> dict[str, Any]:
    """Mirror a resumed, publishable pack when an export dir is configured.

    A resumed run skips E4, so without this an operator who adds `--export-dir`
    to an already-built run would get no export and no explanation.
    """
    from factory.series.publish import mirror_pack

    manifest = output.get("manifest") or {}
    if manifest.get("publish", {}).get("status") != "ready" or cfg.export_dir is None:
        return output
    target = cfg.export_dir / f"class-{class_num}"
    mirror_pack(Path(output["pack_dir"]), target)
    refreshed = {**output, "exported_dir": str(target)}
    run_ctx.save_stage_output("E4-publish", refreshed)
    return refreshed


def _emit_publish_blocked(class_num: int, manifest: dict[str, Any]) -> None:
    publish = manifest.get("publish") or {}
    if publish.get("status") == "ready":
        return
    blockers = publish.get("blockers") or []
    reason_codes = list(publish.get("reason_codes") or [])
    compliance_codes = [
        code
        for code in reason_codes
        if code in ("missing_clearance", "third_party", "similarity", "schema")
    ]
    if compliance_codes:
        log_event(
            "exam.publish.blocked",
            {
                "class_level": class_num,
                "reason_codes": ",".join(compliance_codes),
                "blockers_count": len(blockers),
            },
        )
    if any(code in ("volume", "structure") for code in reason_codes):
        log_event(
            "exam.series.blocked",
            {
                "class_level": class_num,
                "reason_codes": ",".join(
                    code for code in reason_codes if code in ("volume", "structure")
                ),
                "blockers_count": len(blockers),
            },
        )


def _gate_detail(report: dict[str, Any]) -> str:
    from .report import issues_for_reasons

    lines = issues_for_reasons(report)
    if not lines:
        return "gate failed"
    head = lines[:3]
    if len(lines) > 3:
        head.append(f"(+{len(lines) - 3} more)")
    return " | ".join(head)


def _invalidate_downstream(run_ctx: RunContext, stage_id: str) -> None:
    """A re-run upstream stage invalidates the stages that consume it.

    E1→E2→E3→E4 is a straight chain, so every later stage goes stale. Stale,
    not deleted: the old artifact stays as evidence, and `stage_ok` stops
    resuming it, so the next full run re-derives it instead of shipping a pack
    built from inputs that no longer exist.
    """
    path = run_ctx.dir / "status.json"
    if not path.exists():
        return
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return
    changed = False
    later = EXAM_STAGE_ORDER[EXAM_STAGE_ORDER.index(stage_id) + 1 :]
    for downstream in later:
        entry = status.get("stages", {}).get(downstream)
        if entry and entry.get("state") in ("ok", "failed"):
            entry["state"] = "stale"
            entry["detail"] = f"upstream {stage_id} re-ran"
            changed = True
    if changed:
        run_ctx.write_json(path, status)


__all__ = [
    "assemble_class_pack",
    "make_run_id",
    "run_exam",
    "run_fingerprint",
]
