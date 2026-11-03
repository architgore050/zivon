"""Stage registry and orchestrator: the singular pipeline.

Run everything with one command:
    python pipeline.py "Motion" [--class 9]

Graph v2 (2026-11-03), founder decision after the first measured runs:
- The reasoning layer is ONE giant call (02-generate: ground truth + lesson +
  blocks), so it pays one thinking cycle instead of three.
- The review gates (03-check, 09-review) stay SEPARATE model calls: a
  reviewer must never be the author.
- Gate failures route to catchers (04-repair, 08-fixloop, 10-reviewfix): the
  agent that caught an issue hands its verdict to the agent that fixes it,
  bounded by repair.*_rounds. A downstream failure NEVER re-runs upstream
  stages, and the run process never dies just because a gate complained.
- Resume: run ids are deterministic per (chapter, class). A re-triggered run
  (after an infra kill) skips every stage already marked ok and loads its
  output from disk; a fingerprint guard refuses to mix old-graph artifacts.
Every stage's evidence lives in runs/<run_id>/<NN-stage>/.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from . import (
    agents,
    checks,
    fixloop,
    ingest,
    interactive,
    link,
    locate,
    perf,
    render,
    review,
    reviewfix,
)
from .artifacts import RunContext, slugify, wipe_run
from .config import Config
from .errors import BudgetError, ConfigError, FactoryError, StageError
from .llm import LLMClient

# Bump when the stage graph or stage contracts change: old run dirs then
# refuse resume instead than mixing artifacts from two pipeline shapes.
PIPELINE_VERSION = "3"

STAGE_ORDER = [
    "00-ingest",
    "01-locate",
    "02-generate",
    "03-check",
    "04-repair",
    "05-interactive",
    "06-render",
    "07-perf",
    "08-fixloop",
    "09-review",
    "10-reviewfix",
    "11-link",
]


def make_run_id(chapter: str, class_filter: int | None) -> str:
    """Deterministic per (chapter, class): re-triggering the same topic RESUMES
    the previous attempt instead of re-deriving completed stages. Use --fresh
    to force a clean generation, --run-id to keep parallel attempts."""
    parts = [slugify(chapter)]
    if class_filter:
        parts.append(f"c{class_filter}")
    return "-".join(parts)


def run_fingerprint(cfg: Config, chapter: str, class_filter: int | None) -> str:
    """What a run dir's artifacts are valid FOR. Any change here invalidates
    resume (by design: the operator must decide via --fresh)."""
    payload = {
        "pipeline_version": PIPELINE_VERSION,
        "chapter": chapter,
        "class": class_filter,
        "model": cfg.server["model"],
        "limits": cfg.limits,
        "retrieval": cfg.retrieval,
        "repair": cfg.repair,
        "learner": cfg.learner,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]


def _blocking_issues(combined: dict[str, Any]) -> list[dict[str, Any]]:
    """What must be FIXED before the page may proceed: any fatal or major
    issue from the model reviewer or the code rules. Minor issues are
    advisory and ride along in the report."""
    return [
        i
        for i in combined["model_issues"] + combined["rule_issues"]
        if i["severity"] in ("fatal", "major")
    ]


def run_pipeline(
    cfg: Config,
    chapter: str,
    class_filter: int | None,
    run_id: str | None,
    only_stages: list[str] | None = None,
    fresh: bool = False,
) -> dict[str, Any]:
    runs_dir = cfg.repo_path(cfg.paths["runs"])
    run_id = run_id or make_run_id(chapter, class_filter)
    if fresh and wipe_run(runs_dir, run_id):
        print(f"[resume] --fresh: previous run '{run_id}' wiped; generating clean")
    run_ctx = RunContext(runs_dir, run_id)
    llm = LLMClient(cfg, run_ctx)

    fingerprint = run_fingerprint(cfg, chapter, class_filter)
    resume = False
    if run_ctx.status_exists():
        saved = run_ctx.get_fingerprint()
        if saved != fingerprint:
            raise ConfigError(
                f"run '{run_id}' already exists with a different fingerprint "
                f"({saved or 'pre-fingerprint run'}). Refusing to mix stage "
                "artifacts from different pipeline shapes. Start clean: "
                "python pipeline.py <chapter> --fresh   (or keep the old run "
                "alongside: --run-id <new-name>)"
            )
        resume = True
        print(f"[resume] run '{run_id}' found: completed stages will be reused")
    run_ctx.set_fingerprint(fingerprint)

    # In-memory handoffs; also persisted to each stage dir for inspection.
    source_pack: dict[str, Any] | None = None
    ground_truth: dict[str, Any] | None = None
    lesson: dict[str, Any] | None = None
    blocks: dict[str, Any] | None = None
    render_out: dict[str, Any] | None = None

    def wanted(stage: str) -> bool:
        return only_stages is None or stage in only_stages

    def resumed(stage: str) -> bool:
        if resume and run_ctx.stage_ok(stage):
            run_ctx.mark_stage(stage, "ok", detail="resumed from previous attempt")
            return True
        return False

    try:
        if wanted("00-ingest") and not resumed("00-ingest"):
            run_ctx.mark_stage("00-ingest", "running")
            ingest_out = ingest.run(cfg, run_ctx)
            run_ctx.save_stage_output("00-ingest", ingest_out)
            run_ctx.mark_stage("00-ingest", "ok")
        if wanted("01-locate") and not resumed("01-locate"):
            run_ctx.mark_stage("01-locate", "running")
            source_pack = locate.run(cfg, run_ctx, chapter, class_filter)
            run_ctx.save_stage_output("01-locate", source_pack)
            run_ctx.mark_stage(
                "01-locate",
                "ok",
                detail=f"chapter={source_pack['chapter']['title']} supplements={len(source_pack['supplements'])}",
            )

        if (
            wanted("02-generate")
            or wanted("03-check")
            or wanted("04-repair")
            or wanted("09-review")
        ) and source_pack is None:
            source_pack = run_ctx.load_stage_output("01-locate")

        if wanted("02-generate"):
            assert source_pack is not None, (
                "02-generate requires stage 01-locate output"
            )
            if not resumed("02-generate"):
                run_ctx.mark_stage("02-generate", "running")
                generated = agents.run_generate(cfg, run_ctx, llm, source_pack)
                run_ctx.save_stage_output("02-generate", generated)
                run_ctx.mark_stage(
                    "02-generate",
                    "ok",
                    detail=(
                        f"claims={len(generated['ground_truth']['claims'])} "
                        f"blocks={len(generated['blocks']['blocks'])}"
                    ),
                )
            generated = run_ctx.load_stage_output("02-generate")
            ground_truth = generated["ground_truth"]
            lesson = generated["lesson"]
            blocks = generated["blocks"]

        # ---- 03-check + 04-repair: the fact gate and its catcher -----------
        def run_check_once(round_tag: str | None) -> dict[str, Any]:
            assert (
                blocks is not None
                and lesson is not None
                and ground_truth is not None
                and source_pack is not None
            ), "03-check requires 01-locate and 02-generate outputs"
            run_ctx.mark_stage("03-check", "running")
            model_report = agents.run_check(
                cfg,
                run_ctx,
                llm,
                source_pack,
                ground_truth,
                lesson,
                blocks,
                round_tag=round_tag,
            )
            rule_report = checks.run_all_rules(
                blocks["blocks"], lesson, ground_truth, source_pack
            )
            combined = {
                "model_verdict": model_report["verdict"],
                "model_issues": model_report["issues"],
                "rule_verdict": rule_report["verdict"],
                "rule_issues": rule_report["rule_issues"],
                "verdict": "fail"
                if model_report["verdict"] == "fail" or rule_report["verdict"] == "fail"
                else "pass",
            }
            run_ctx.save_stage_output("03-check", combined)
            if round_tag:
                run_ctx.write_json(
                    run_ctx.stage_dir("03-check") / f"combined-{round_tag}.json",
                    combined,
                )
            blocking = _blocking_issues(combined)
            run_ctx.mark_stage(
                "03-check",
                "ok" if not blocking else "failed",
                detail=(
                    f"model={model_report['verdict']} rules={rule_report['verdict']} "
                    f"blocking={len(blocking)}"
                ),
            )
            return combined

        if wanted("03-check") or wanted("04-repair"):
            if blocks is None:
                generated = run_ctx.load_stage_output("02-generate")
                ground_truth = generated["ground_truth"]
                lesson = generated["lesson"]
                blocks = generated["blocks"]
            if resumed("03-check"):
                # The validated unit already passed; pick up repaired blocks if any.
                if run_ctx.stage_ok("04-repair"):
                    blocks = run_ctx.load_stage_output("04-repair")["page"]
            else:
                if run_ctx.stage_ok("04-repair"):
                    # Pod died between a repair and its recheck: resume mid-loop.
                    blocks = run_ctx.load_stage_output("04-repair")["page"]
                combined = run_check_once(None)
                rounds = 0
                max_rounds = cfg.repair["content_rounds"]
                history: list[dict[str, Any]] = []
                while (
                    _blocking_issues(combined)
                    and rounds < max_rounds
                    and wanted("04-repair")
                ):
                    issues = _blocking_issues(combined)
                    rounds += 1
                    tag = f"round-{rounds:02d}"
                    assert (
                        source_pack is not None
                        and ground_truth is not None
                        and lesson is not None
                    ), "04-repair requires the source pack and the draft"
                    run_ctx.mark_stage("04-repair", "running")
                    repair_out = agents.run_repair(
                        cfg,
                        run_ctx,
                        llm,
                        source_pack,
                        ground_truth,
                        lesson,
                        blocks,
                        issues,
                        round_tag=tag,
                    )
                    flagged = {i["block_id"] for i in issues if i.get("block_id")}
                    merged = agents.merge_blocks(blocks, repair_out["blocks"])
                    omitted = flagged - {b["id"] for b in repair_out["blocks"]}
                    if omitted:
                        merged = agents.remove_blocks(merged, omitted)
                    blocks = merged
                    history.append(
                        {
                            "round": rounds,
                            "issues_fixed": issues,
                            "analysis": repair_out["analysis"],
                            "replaced": [b["id"] for b in repair_out["blocks"]],
                            "removed": sorted(omitted),
                        }
                    )
                    run_ctx.save_stage_output(
                        "04-repair", {"page": blocks, "history": history}
                    )
                    run_ctx.mark_stage("04-repair", "ok", detail=f"rounds={rounds}")
                    combined = run_check_once(tag)
                if _blocking_issues(combined):
                    raise StageError(
                        "03-check",
                        f"review still failing after {rounds} repair round(s) - "
                        "model: "
                        + "; ".join(
                            i["message"][:200]
                            for i in combined["model_issues"]
                            if i["severity"] in ("fatal", "major")
                        )
                        + " | rules: "
                        + "; ".join(
                            i["message"][:200]
                            for i in combined["rule_issues"]
                            if i["severity"] in ("fatal", "major")
                        ),
                        artifacts_dir=str(run_ctx.stage_dir("03-check")),
                    )

        if wanted("05-interactive"):
            if blocks is None:
                generated = run_ctx.load_stage_output("02-generate")
                ground_truth = generated["ground_truth"]
                blocks = generated["blocks"]
            assert ground_truth is not None, "05-interactive requires the ground truth"
            if not resumed("05-interactive"):
                run_ctx.mark_stage("05-interactive", "running")
                interactive_out = interactive.run(
                    cfg, run_ctx, llm, blocks, ground_truth
                )
                run_ctx.save_stage_output("05-interactive", interactive_out)
                run_ctx.mark_stage(
                    "05-interactive", "ok", detail=f"built={len(interactive_out)}"
                )

        if wanted("06-render"):
            if blocks is None:
                generated = run_ctx.load_stage_output("02-generate")
                lesson = generated["lesson"]
                blocks = generated["blocks"]
            if lesson is None:
                lesson = run_ctx.load_stage_output("02-generate")["lesson"]
            if source_pack is None:
                source_pack = run_ctx.load_stage_output("01-locate")
            interactive_out = (
                run_ctx.load_stage_output("05-interactive")
                if wanted("05-interactive")
                or (run_ctx.stage_dir("05-interactive") / "output.json").exists()
                else {}
            )
            run_ctx.mark_stage("06-render", "running")
            render_out = render.run(
                cfg,
                run_ctx,
                chapter,
                source_pack,
                lesson,
                blocks,
                interactive_out,
            )
            run_ctx.save_stage_output("06-render", render_out)
            run_ctx.mark_stage("06-render", "ok", detail=render_out["topic_dir"])

        perf_report: dict[str, Any] | None = None
        if wanted("07-perf"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("06-render")
            if not resumed("07-perf"):
                run_ctx.mark_stage("07-perf", "running")
                try:
                    perf_out = perf.run(cfg, run_ctx, render_out)
                    perf_report = perf_out["pages"]["topic_page"]
                    run_ctx.mark_stage("07-perf", "ok")
                except BudgetError as exc:
                    # A topic-page miss is ROUTED to 08-fixloop (the Performance
                    # Engineer's repair loop) instead of killing the run.
                    # Unfixable misses (e.g. the landing page) stop immediately.
                    perf_report = exc.report
                    run_ctx.mark_stage("07-perf", "failed", detail=str(exc))
                    if not (exc.fixable and wanted("08-fixloop")):
                        raise

        if wanted("08-fixloop"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("06-render")
            if blocks is None:
                blocks = run_ctx.load_stage_output("02-generate")["blocks"]
            if not resumed("08-fixloop"):
                run_ctx.mark_stage("08-fixloop", "running")
                fix_out = fixloop.run(
                    cfg, run_ctx, llm, render_out, perf_report, blocks
                )
                run_ctx.save_stage_output("08-fixloop", fix_out)
                run_ctx.mark_stage(
                    "08-fixloop", "ok", detail=f"rounds={fix_out['rounds']}"
                )

        # ---- 09-review + 10-reviewfix: the code gate and its catcher -------
        def run_review_once(round_tag: str | None) -> dict[str, Any]:
            assert (
                blocks is not None
                and ground_truth is not None
                and render_out is not None
            )
            run_ctx.mark_stage("09-review", "running")
            report = review.run(
                cfg, run_ctx, llm, blocks, render_out, ground_truth, round_tag=round_tag
            )
            run_ctx.mark_stage(
                "09-review",
                "ok" if report["verdict"] == "pass" else "failed",
                detail=f"verdict={report['verdict']} issues={len(report['issues'])}",
            )
            return report

        gate_active = wanted("09-review") or wanted("10-reviewfix")
        if gate_active and not resumed("09-review"):
            if blocks is None:
                generated = run_ctx.load_stage_output("02-generate")
                ground_truth = generated["ground_truth"]
                blocks = generated["blocks"]
            if ground_truth is None:
                ground_truth = run_ctx.load_stage_output("02-generate")["ground_truth"]
            if render_out is None:
                render_out = run_ctx.load_stage_output("06-render")
            report = run_review_once(None)
            rounds = 0
            max_rounds = cfg.repair["code_rounds"]
            while (
                report["verdict"] == "fail"
                and rounds < max_rounds
                and wanted("10-reviewfix")
            ):
                rounds += 1
                tag = f"round-{rounds:02d}"
                run_ctx.mark_stage("10-reviewfix", "running")
                fix_out = reviewfix.run(
                    cfg, run_ctx, llm, render_out, report, ground_truth, blocks, tag
                )
                run_ctx.save_stage_output("10-reviewfix", fix_out)
                run_ctx.mark_stage(
                    "10-reviewfix", "ok", detail=f"rounds={fix_out['rounds']}"
                )
                report = run_review_once(tag)
            if report["verdict"] == "fail":
                raise StageError(
                    "09-review",
                    f"code review still failing after {rounds} fix round(s): "
                    + "; ".join(i["message"][:160] for i in report["issues"]),
                    artifacts_dir=str(run_ctx.stage_dir("09-review")),
                )

        if wanted("11-link"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("06-render")
            if not resumed("11-link"):
                run_ctx.mark_stage("11-link", "running")
                link_out = link.run(cfg, run_ctx, render_out)
                run_ctx.save_stage_output("11-link", link_out)
                run_ctx.mark_stage(
                    "11-link",
                    "ok",
                    detail=f"{link_out['course_count']} course(s) listed",
                )

        run_ctx.finish(ok=True, detail="pipeline complete")
        return {"run_id": run_ctx.run_id, "ok": True}

    except FactoryError as exc:
        run_ctx.mark_stage(
            getattr(exc, "stage_id", "pipeline"), "failed", detail=str(exc)
        )
        run_ctx.finish(ok=False, detail=str(exc))
        raise
