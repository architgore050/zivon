"""Stage 10-reviewfix: the code catcher for the Code Reviewer's verdict.

Graph v2 routing: when 09-review fails, the run does NOT die and the
pipeline is NOT re-run - the reviewer's fatal/major findings come here (the
fixer paired with that gate). The model returns complete replacement
contents for topic-local files ONLY (page.js, page.css; index.html is
renderer-owned - same rule as 08-fixloop), and it receives the LIVE design
doctrine + lesson-page example + palette so its fixes land on the page's
visual language. After each round the stage
re-lints everything, re-emits the index.html tags, re-measures perf (a code
fix must not break the perf budget), and 09-review re-reviews. After
repair.code_rounds rounds without a pass, the run fails with the full
history so a human can look.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context, palette_text
from .errors import BudgetError, LintError
from .fixloop import FIXABLE, _rebuild_html_if_needed, _specs_text
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
) -> dict[str, Any]:
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
                ),
            },
        ],
        FIX_PLAN,
        "review_fix_plan",
        round_tag=round_tag,
    )

    files = plan.get("files", {})
    illegal = set(files) - FIXABLE
    if illegal:
        raise LintError(
            STAGE_ID,
            f"{round_tag}: fix tries to modify non-topic files: {sorted(illegal)}. "
            f"Only {sorted(FIXABLE)} may change.",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    for name, content in files.items():
        (topic_dir / name).write_text(content, encoding="utf-8")
    _rebuild_html_if_needed(cfg, render_out, topic_dir)

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
    hits = lint_generated(js, css, html_text)
    if hits:
        raise LintError(
            STAGE_ID,
            f"{round_tag}: fixed code violates hard lints:\n" + "\n".join(hits),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )

    # A code fix must not break the perf budget the page already passed.
    run_profile = _harness()
    profile_path = cfg.repo_path(cfg.perf["profile"])
    topic_url = (topic_dir / "index.html").as_uri()
    perf_report = run_profile(topic_url, profile_path)

    history.append(
        {
            "round": round_tag,
            "analysis": plan["analysis"],
            "files_changed": sorted(files),
            "perf_after_fix": {
                "pass": perf_report["pass"],
                "failures": perf_report["failures"],
            },
        }
    )
    run_ctx.write_json(history_path, history)

    # sync fixed files into the staging site copy (same dirs as 08-fixloop)
    manifest = json.loads((topic_dir / "manifest.json").read_text(encoding="utf-8"))
    site_topic = site / "courses" / manifest["course_id"] / manifest["topic_slug"]
    if site_topic != topic_dir:
        for name in ("index.html", "page.js", "page.css", "manifest.json"):
            src = topic_dir / name
            if src.exists():
                (site_topic / name).write_text(
                    src.read_text(encoding="utf-8"), encoding="utf-8"
                )

    if not perf_report["pass"]:
        raise BudgetError(
            STAGE_ID,
            f"{round_tag}: review fix broke the perf budget: "
            + "; ".join(perf_report["failures"])
            + " - human review required (08-fixloop already ran).",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            fixable=False,
        )

    return {"rounds": len(history), "history": history, "analysis": plan["analysis"]}


def _system() -> str:
    return (
        "[ZIVON STAGE: 10-reviewfix] You are the Code Repair agent in the Zivon content "
        "factory. The Code Reviewer rejected the final page; you fix exactly what it "
        "flagged.\n"
        "RULES:\n- Return exactly ONE JSON object.\n"
        "- You may only replace page.js and page.css contents; never reference external "
        "resources; never use eval/Function/fetch/import.\n"
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
) -> str:
    from .review import _facts_text  # same facts view the reviewer used

    issues = [
        i for i in report.get("issues", []) if i["severity"] in ("fatal", "major")
    ]
    issue_lines = "\n".join(
        f"- [{i['severity']}] block {i.get('block_id', '(page level)')}: {i['message']}"
        for i in issues
    )
    files_text = (
        "\n\n".join(f"=== {name} ===\n{content}" for name, content in files.items())
        or "(no topic files yet)"
    )
    return (
        "REVIEWER FINDINGS TO FIX:\n"
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
        "complete replacements."
    )
