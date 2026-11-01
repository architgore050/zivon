"""Stage registry and orchestrator: the singular pipeline.

Run everything with one command:
    python pipeline.py "Motion" [--class 9]

Stages run strictly in order. Any stage failure stops the run immediately -
downstream stages never execute on unverified output. Every stage's evidence
lives in runs/<run_id>/<NN-stage>/.
"""

from __future__ import annotations

import time
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
)
from .artifacts import RunContext, slugify
from .config import Config
from .errors import FactoryError, StageError
from .llm import LLMClient

STAGE_ORDER = [
    "00-ingest",
    "01-locate",
    "02-synth",
    "03-explain",
    "04-draft",
    "05-check",
    "06-interactive",
    "07-render",
    "08-perf",
    "09-fixloop",
    "10-review",
    "11-link",
]


def make_run_id(chapter: str, class_filter: int | None) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%S", time.gmtime())
    parts = [stamp, slugify(chapter)]
    if class_filter:
        parts.append(f"c{class_filter}")
    return "-".join(parts)


def run_pipeline(
    cfg: Config,
    chapter: str,
    class_filter: int | None,
    run_id: str | None,
    only_stages: list[str] | None = None,
) -> dict[str, Any]:
    run_ctx = RunContext(
        cfg.repo_path(cfg.paths["runs"]), run_id or make_run_id(chapter, class_filter)
    )
    llm = LLMClient(cfg, run_ctx)

    # In-memory handoffs; also persisted to each stage dir for inspection.
    source_pack: dict[str, Any] | None = None
    ground_truth: dict[str, Any] | None = None
    lesson: dict[str, Any] | None = None
    blocks: dict[str, Any] | None = None
    render_out: dict[str, Any] | None = None

    def wanted(stage: str) -> bool:
        return only_stages is None or stage in only_stages

    try:
        if wanted("00-ingest"):
            run_ctx.mark_stage("00-ingest", "running")
            ingest_out = ingest.run(cfg, run_ctx)
            run_ctx.save_stage_output("00-ingest", ingest_out)
            run_ctx.mark_stage("00-ingest", "ok")
        if wanted("01-locate"):
            run_ctx.mark_stage("01-locate", "running")
            source_pack = locate.run(cfg, run_ctx, chapter, class_filter)
            run_ctx.save_stage_output("01-locate", source_pack)
            run_ctx.mark_stage(
                "01-locate",
                "ok",
                detail=f"chapter={source_pack['chapter']['title']} supplements={len(source_pack['supplements'])}",
            )

        if (
            wanted("02-synth")
            or wanted("03-explain")
            or wanted("04-draft")
            or wanted("05-check")
        ) and source_pack is None:
            source_pack = run_ctx.load_stage_output("01-locate")
        if wanted("02-synth"):
            # load_stage_output raises if the artifact is missing, so reaching
            # here with source_pack=None is impossible; assert documents it.
            assert source_pack is not None, "02-synth requires stage 01-locate output"
            run_ctx.mark_stage("02-synth", "running")
            ground_truth = agents.run_synth(cfg, run_ctx, llm, source_pack)
            run_ctx.save_stage_output("02-synth", ground_truth)
            run_ctx.mark_stage(
                "02-synth",
                "ok",
                detail=f"claims={len(ground_truth['claims'])} uncertain={len(ground_truth['uncertain'])}",
            )
        if wanted("03-explain"):
            if ground_truth is None:
                ground_truth = run_ctx.load_stage_output("02-synth")
            run_ctx.mark_stage("03-explain", "running")
            lesson = agents.run_explain(cfg, run_ctx, llm, ground_truth)
            run_ctx.save_stage_output("03-explain", lesson)
            run_ctx.mark_stage(
                "03-explain", "ok", detail=f"sections={len(lesson['sections'])}"
            )
        if wanted("04-draft"):
            if lesson is None:
                lesson = run_ctx.load_stage_output("03-explain")
            if ground_truth is None:
                ground_truth = run_ctx.load_stage_output("02-synth")
            run_ctx.mark_stage("04-draft", "running")
            blocks = agents.run_draft(cfg, run_ctx, llm, lesson, ground_truth)
            run_ctx.save_stage_output("04-draft", blocks)
            run_ctx.mark_stage(
                "04-draft", "ok", detail=f"blocks={len(blocks['blocks'])}"
            )
        if wanted("05-check"):
            assert source_pack is not None, "05-check requires stage 01-locate output"
            if blocks is None:
                blocks = run_ctx.load_stage_output("04-draft")
            if lesson is None:
                lesson = run_ctx.load_stage_output("03-explain")
            if ground_truth is None:
                ground_truth = run_ctx.load_stage_output("02-synth")
            run_ctx.mark_stage("05-check", "running")
            model_report = agents.run_check(
                cfg, run_ctx, llm, source_pack, ground_truth, blocks
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
            run_ctx.save_stage_output("05-check", combined)
            run_ctx.mark_stage(
                "05-check",
                "ok" if combined["verdict"] == "pass" else "failed",
                detail=f"model={model_report['verdict']} rules={rule_report['verdict']}",
            )
            if combined["verdict"] == "fail":
                raise StageError(
                    "05-check",
                    "review failed - model verdict: "
                    + "; ".join(i["message"][:200] for i in model_report["issues"])
                    + "; rule verdict: "
                    + "; ".join(
                        i["message"][:200]
                        for i in rule_report["rule_issues"]
                        if i["severity"] == "fatal"
                    ),
                    artifacts_dir=str(run_ctx.stage_dir("05-check")),
                )

        if wanted("06-interactive"):
            if blocks is None:
                blocks = run_ctx.load_stage_output("04-draft")
            run_ctx.mark_stage("06-interactive", "running")
            interactive_out = interactive.run(cfg, run_ctx, llm, blocks)
            run_ctx.save_stage_output("06-interactive", interactive_out)
            run_ctx.mark_stage(
                "06-interactive", "ok", detail=f"built={len(interactive_out)}"
            )

        if wanted("07-render"):
            if blocks is None:
                blocks = run_ctx.load_stage_output("04-draft")
            if lesson is None:
                lesson = run_ctx.load_stage_output("03-explain")
            if source_pack is None:
                source_pack = run_ctx.load_stage_output("01-locate")
            interactive_out = (
                run_ctx.load_stage_output("06-interactive")
                if wanted("06-interactive")
                or (run_ctx.stage_dir("06-interactive") / "output.json").exists()
                else {}
            )
            run_ctx.mark_stage("07-render", "running")
            render_out = render.run(
                cfg,
                run_ctx,
                chapter,
                source_pack,
                ground_truth or {},
                lesson,
                blocks,
                interactive_out,
            )
            run_ctx.save_stage_output("07-render", render_out)
            run_ctx.mark_stage("07-render", "ok", detail=render_out["topic_dir"])

        if wanted("08-perf"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("07-render")
            run_ctx.mark_stage("08-perf", "running")
            perf.run(cfg, run_ctx, render_out)
            run_ctx.mark_stage("08-perf", "ok")

        if wanted("09-fixloop"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("07-render")
            run_ctx.mark_stage("09-fixloop", "running")
            fix_out = fixloop.run(cfg, run_ctx, llm, render_out)
            run_ctx.save_stage_output("09-fixloop", fix_out)
            run_ctx.mark_stage("09-fixloop", "ok", detail=f"rounds={fix_out['rounds']}")

        if wanted("10-review"):
            if blocks is None:
                blocks = run_ctx.load_stage_output("04-draft")
            if render_out is None:
                render_out = run_ctx.load_stage_output("07-render")
            run_ctx.mark_stage("10-review", "running")
            review.run(cfg, run_ctx, llm, blocks, render_out)
            run_ctx.mark_stage("10-review", "ok")

        if wanted("11-link"):
            if render_out is None:
                render_out = run_ctx.load_stage_output("07-render")
            run_ctx.mark_stage("11-link", "running")
            link_out = link.run(cfg, run_ctx, render_out)
            run_ctx.save_stage_output("11-link", link_out)
            run_ctx.mark_stage(
                "11-link", "ok", detail=f"{link_out['course_count']} course(s) listed"
            )

        run_ctx.finish(ok=True, detail="pipeline complete")
        return {"run_id": run_ctx.run_id, "ok": True}

    except FactoryError as exc:
        run_ctx.mark_stage(
            getattr(exc, "stage_id", "pipeline"), "failed", detail=str(exc)
        )
        run_ctx.finish(ok=False, detail=str(exc))
        raise
