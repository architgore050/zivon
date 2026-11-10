"""Stage 10-reviewfix: the code catcher for the Code Reviewer's verdict.

Graph v2 routing: when 09-review fails, the run does NOT die and the
pipeline is NOT re-run - the reviewer's fatal/major findings come here (the
fixer paired with that gate). The model returns complete replacement
contents for topic-local files ONLY (page.js, page.css; index.html is
renderer-owned - same rule as 08-fixloop). Since 2026-11-09 it may also
return corrected BLOCK specs under "blocks" (drawn-geometry errors live in
the block specs, which the renderer re-renders index.html from); the
harness merges them by id and threads the corrected draft back through
09-review. The fixer receives the LIVE design doctrine + lesson-page
example + palette so its fixes land on the page's visual language. After
each round the stage re-lints everything, re-renders the HTML body from
the current block specs, re-emits the index.html tags and re-measures perf
(a code fix must not break the perf budget), and 09-review re-reviews.

Continuous improvement (founder decision 2026-11-06): a fix that violates a
hard lint, touches a renderer-owned file, or regresses the perf budget does
NOT kill the run - it is recorded and returned, and the NEXT fix round
receives that exact failure as its assignment (repair its own fix). The
orchestrator's progress-aware loop (repair.code_rounds cap + stall detection)
decides when a human is really needed.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context, palette_text
from .fixloop import FIXABLE, _apply_plan, _rebuild_html_if_needed, _specs_text
from .lint import lint_generated
from .llm import LLMClient
from .perf import _harness
from .schemas import FIX_PLAN

STAGE_ID = "10-reviewfix"


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    render_out: dict[str, Any],
    review_report: dict[str, Any],
    ground_truth: dict[str, Any],
    blocks: dict[str, Any],
    round_tag: str,
    extra_feedback: list[str] | None = None,
) -> dict[str, Any]:
    """extra_feedback: a previous round's own failure (lint hits / perf
    regression) that this round must repair FIRST (errors-as-context)."""
    topic_dir = Path(render_out["topic_dir"])
    site = Path(render_out["site_dir"])
    history_path = run_ctx.stage_dir(STAGE_ID) / "history.json"
    history: list[dict[str, Any]] = (
        json.loads(history_path.read_text(encoding="utf-8"))
        if history_path.exists()
        else []
    )

    current_files = {
        name: (topic_dir / name).read_text(encoding="utf-8")
        for name in sorted(FIXABLE)
        if (topic_dir / name).exists()
    }
    plan = llm.call(
        STAGE_ID,
        [
            {"role": "system", "content": _system()},
            {
                "role": "user",
                "content": _user_msg(
                    review_report,
                    current_files,
                    render_out,
                    ground_truth,
                    blocks,
                    cfg,
                    extra_feedback=extra_feedback,
                ),
            },
        ],
        FIX_PLAN,
        "review_fix_plan",
        round_tag=round_tag,
    )

    rejected, merged_blocks = _apply_plan(topic_dir, plan, blocks)
    lint_hits = [*rejected]
    if merged_blocks is not None:
        blocks = merged_blocks
    _rebuild_html_if_needed(cfg, render_out, topic_dir, blocks)

    # Files this plan wrote (renderer-owned names were dropped, same filter
    # _apply_plan applies when writing).
    files = {
        name: content
        for name, content in plan.get("files", {}).items()
        if name in FIXABLE
    }

    # Re-lint everything that changed, plus the html that embeds them.
    html_text = (topic_dir / "index.html").read_text(encoding="utf-8")
    js = (
        (topic_dir / "page.js").read_text(encoding="utf-8")
        if (topic_dir / "page.js").exists()
        else ""
    )
    css = (
        (topic_dir / "page.css").read_text(encoding="utf-8")
        if (topic_dir / "page.css").exists()
        else ""
    )
    lint_hits.extend(lint_generated(js, css, html_text))

    # A code fix must not break the perf budget the page already passed - but
    # a lint-violating round re-measures nothing: its own failure is already
    # the next round's assignment (2026-11-06: failures feed back, they do not
    # kill the run).
    if lint_hits:
        perf_after = {
            "pass": False,
            "failures": [
                "perf re-measure skipped: this round's fix violated hard lints"
            ],
        }
    else:
        run_profile = _harness()
        profile_path = cfg.repo_path(cfg.perf["profile"])
        topic_url = (topic_dir / "index.html").as_uri()
        perf_report = run_profile(topic_url, profile_path)
        perf_after = {"pass": perf_report["pass"], "failures": perf_report["failures"]}

    history.append(
        {
            "round": round_tag,
            "analysis": plan["analysis"],
            "files_changed": sorted(files),
            "lint_hits": lint_hits,
            "perf_after_fix": perf_after,
        }
    )
    run_ctx.write_json(history_path, history)

    # Sync only CLEAN fixes into the staging site copy (same dirs as
    # 08-fixloop): an intermediate that violates lint or perf never creeps
    # toward the served site.
    if not lint_hits and perf_after["pass"]:
        manifest = json.loads((topic_dir / "manifest.json").read_text(encoding="utf-8"))
        site_topic = site / "courses" / manifest["course_id"] / manifest["topic_slug"]
        if site_topic != topic_dir:
            for name in ("index.html", "page.js", "page.css", "manifest.json"):
                src = topic_dir / name
                if src.exists():
                    (site_topic / name).write_text(
                        src.read_text(encoding="utf-8"), encoding="utf-8"
                    )

    return {
        "rounds": len(history),
        "history": history,
        "analysis": plan["analysis"],
        "lint_hits": lint_hits,
        "perf_after_fix": perf_after,
        # Spec corrections merged during this run (2026-11-09): the
        # orchestrator threads them back into the page draft (09-review's
        # next round and 06-render see the corrected specs), and a resume
        # loads them as the page. None when the fix was code-only.
        "page": blocks,
    }


def _system() -> str:
    return (
        "[ZIVON STAGE: 10-reviewfix] You are the Code Repair agent in the Zivon content "
        "factory. The Code Reviewer rejected the final page; you fix exactly what it "
        "flagged.\n"
        "RULES:\n- Return exactly ONE JSON object.\n"
        "- You may only replace page.js and page.css contents; never reference external "
        "resources; never use eval/Function/fetch/import.\n"
        "- A defect in BLOCK CONTENT (wrong diagram geometry, a caption contradicting "
        "its claim, wrong numbers/spec fields) cannot be fixed in code: return the "
        'corrected FULL block objects under "blocks" (id, type, spec, citations '
        "unchanged unless the finding says otherwise). The renderer will re-draw the "
        "page body from your corrected specs. Do NOT re-specify simulation blocks - "
        "simulation behaviour is page.js draw code, fix it there.\n"
        "- The page must still TEACH: every block spec stays implemented, every "
        "simulation keeps its learning_goal, default_behaviour and controls, and the "
        "drawn behaviour must keep matching the CITED FACTS.\n"
        "- Fix the flagged issues; do not restyle the page or rewrite what was not flagged.\n"
    )


def _user_msg(
    report: dict[str, Any],
    files: dict[str, str],
    render_out: dict[str, Any],
    ground_truth: dict[str, Any],
    blocks: dict[str, Any],
    cfg: Config,
    extra_feedback: list[str] | None = None,
) -> str:
    from .review import _facts_text  # same facts view the reviewer used

    # Continuous improvement (2026-11-06): if a previous round's own fix broke
    # a lint or the perf budget, repairing that regression is THIS round's
    # first assignment - the fixer repairs its own fix.
    feedback_block = (
        "REPAIR YOUR OWN LAST FIX FIRST (it failed these checks; undo/fix that "
        "before the reviewer findings):\n"
        + "\n".join(f"- {f}" for f in extra_feedback)
        + "\n\n"
        if extra_feedback
        else ""
    )
    issues = [
        i for i in report.get("issues", []) if i["severity"] in ("fatal", "major")
    ]
    issue_lines = "\n".join(
        f"- [{i['severity']}{('/' + i['category']) if i.get('category') else ''}] "
        f"block {i.get('block_id', '(page level)')}: {i['message']}"
        for i in issues
    )
    files_text = (
        "\n\n".join(f"=== {name} ===\n{content}" for name, content in files.items())
        or "(no topic files yet)"
    )
    return (
        feedback_block
        + "REVIEWER FINDINGS TO FIX:\n"
        + issue_lines
        + "\n\nBLOCK SPECS (what the page must implement):\n"
        + _specs_text(blocks)
        + "\n\nFULL BLOCK JSON (specs the HTML already renders - do not contradict it):\n"
        + json.dumps(blocks["blocks"], indent=1, ensure_ascii=False)
        + "\n\nCITED FACTS (the drawn behaviour must keep matching these):\n"
        + _facts_text(ground_truth)
        + "\n\nMANIFEST:\n"
        + json.dumps(render_out["manifest"], indent=2, ensure_ascii=False)
        + "\n\nCURRENT TOPIC FILES:\n"
        + files_text
        + "\n\nDESIGN DOCTRINE + LESSON-PAGE EXAMPLE (the visual language of "
        "this page - fix the flagged issues TOWARD this reference; never "
        "restyle what was not flagged, and a style fix must land on this "
        "language):\n"
        + design_context(cfg, with_examples=True)
        + "\n\nPALETTE (exact values from the page stylesheet; use these, "
        "invent nothing):\n"
        + palette_text(cfg)
        + '\n\nReturn {"analysis": "what each flagged issue was and how your fix '
        'resolves it", "files": {"page.js": "<full new content>", "page.css": '
        '"<full new content>"}}. Omit files you do not change; contents must be '
        "complete replacements. Only for BLOCK-CONTENT findings: add "
        '"blocks": [<corrected full block objects>].'
    )
