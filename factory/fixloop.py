"""Stage 08-fixloop: the Performance Engineer agent, back-and-forth.

Stage 07 hands the failing perf report here (the orchestrator routes a
fixable BudgetError instead of dying). Loop: hand the report + page specs +
previous attempts + current topic files + the LIVE design doctrine and its
lesson-page example (+ palette) to the model, apply its replacement
contents (topic-local files ONLY: page.js, page.css; index.html is
renderer-owned), re-lint, re-render the HTML shell, re-test. After
perf.fix_rounds rounds without a pass, the stage fails with the full history
so a human can look. The prompt guards the pedagogy: a perf fix may not
delete or neuter what the page teaches.

When stage 07 already passed, this stage verifies nothing new is broken and
returns immediately (rounds=0, no model call, no extra Chromium launch).
"""

from __future__ import annotations

import html as html_mod
import json
import shutil
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context, palette_text
from .errors import BudgetError, LintError
from .lint import lint_generated
from .llm import LLMClient
from .perf import _harness
from .schemas import FIX_PLAN

STAGE_ID = "08-fixloop"

FIXABLE = {"page.js", "page.css"}  # topic-local only; index.html is renderer-owned


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    render_out: dict[str, Any],
    initial_perf: dict[str, Any] | None = None,
    blocks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """initial_perf: stage 07's topic-page report (or None when 08 is run
    standalone - then we measure once ourselves).
    blocks: the 04-draft output - the page specs the fix loop must preserve."""
    run_profile = _harness()
    profile_path = cfg.repo_path(cfg.perf["profile"])
    topic_dir = Path(render_out["topic_dir"])
    site = Path(render_out["site_dir"])
    topic_url = (topic_dir / "index.html").as_uri()

    history: list[dict[str, Any]] = []
    if initial_perf is not None and initial_perf.get("pass"):
        # Stage 07 just measured this exact page and it passed: nothing to fix.
        history = [{"round": 0, "perf": initial_perf}]
        _finish(cfg, run_ctx, history, topic_dir, site, ok=True)
        return {"rounds": 0, "history": history, "pass": True}

    report = (
        initial_perf
        if initial_perf is not None
        else run_profile(topic_url, profile_path)
    )
    history = [{"round": 0, "perf": report}]
    rounds = cfg.perf["fix_rounds"]
    specs = _specs_text(blocks)
    attempts: list[str] = []

    for round_no in range(1, rounds + 1):
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
                        cfg,
                        report,
                        current_files,
                        round_no,
                        rounds,
                        specs,
                        attempts,
                    ),
                },
            ],
            FIX_PLAN,
            "fix_plan",
        )

        run_ctx.write_json(
            run_ctx.stage_dir(STAGE_ID) / f"round-{round_no:02d}-plan.json", plan
        )

        _apply_plan(topic_dir, plan)
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
                f"round {round_no}: fixed code violates hard lints:\n"
                + "\n".join(hits),
                artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            )

        report = run_profile(topic_url, profile_path)
        history.append({"round": round_no, "perf": report})
        attempts.append(
            f"round {round_no}: {plan['analysis'][:240]} -> "
            + ("pass" if report["pass"] else "; ".join(report["failures"])[:240])
        )
        if report["pass"]:
            _finish(cfg, run_ctx, history, topic_dir, site, ok=True)
            return {"rounds": round_no, "history": history, "pass": True}

    _finish(cfg, run_ctx, history, topic_dir, site, ok=False)
    raise BudgetError(
        STAGE_ID,
        f"performance budgets still missed after {rounds} fix rounds: "
        + "; ".join(report["failures"])
        + " - human review required (full history in the stage artifacts).",
        artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        fixable=False,
    )


def _apply_plan(topic_dir: Path, plan: dict[str, Any]) -> None:
    files = plan.get("files", {})
    illegal = set(files) - FIXABLE
    if illegal:
        raise LintError(
            STAGE_ID,
            f"fix plan tries to modify non-topic files: {sorted(illegal)}. "
            f"Only {sorted(FIXABLE)} may change.",
        )
    for name, content in files.items():
        (topic_dir / name).write_text(content, encoding="utf-8")


def _rebuild_html_if_needed(
    cfg: Config, render_out: dict[str, Any], topic_dir: Path
) -> None:
    """index.html is renderer-owned; after a fix round, re-emit it so the
    page.js/page.css script/link tags match the files that actually exist."""
    from .render import _page_html  # renderer owns this template

    html_path = topic_dir / "index.html"
    old = html_path.read_text(encoding="utf-8")
    title = render_out["manifest"]["title"]
    course_id = render_out["manifest"]["course_id"]
    # Re-extract the body between the known markers instead of re-rendering blocks.
    start = old.index('<main class="zn-page">') + len('<main class="zn-page">')
    end = old.index("</main>")
    body = old[start:end]
    has_js = (topic_dir / "page.js").exists()
    has_css = (topic_dir / "page.css").exists()
    new_html = _page_html(
        cfg,
        {
            "title": title,
            "objectives": _extract_objectives(old),
            "glossary": _extract_glossary(old),
        },
        body,
        render_out["manifest"]["topic_slug"],
        course_id,
        has_page_js=has_js,
        has_page_css=has_css,
    )
    html_path.write_text(new_html, encoding="utf-8")
    # copy into the staging landing tree as well
    site_topic = (
        Path(render_out["site_dir"])
        / "courses"
        / course_id
        / render_out["manifest"]["topic_slug"]
    )
    if site_topic != topic_dir:
        shutil.copy2(html_path, site_topic / "index.html")
        for name in ("page.js", "page.css"):
            src = topic_dir / name
            if src.exists():
                shutil.copy2(src, site_topic / name)


def _strip_tags(text: str) -> str:
    """Drop markup and decode entities, so re-rendering escapes exactly once."""
    import re

    return html_mod.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _extract_objectives(html_text: str) -> list[str]:
    import re

    block = re.search(r'<ul class="zn-objectives">(.*?)</ul>', html_text, re.DOTALL)
    if not block:
        return ["(objectives unavailable)"]
    return [
        _strip_tags(li)
        for li in re.findall(r"<li>(.*?)</li>", block.group(1), re.DOTALL)
    ]


def _extract_glossary(html_text: str) -> list[dict[str, str]]:
    import re

    block = re.search(
        r'<section class="zn-glossary">(.*?)</section>', html_text, re.DOTALL
    )
    if not block:
        return [{"term": "n/a", "definition": "n/a"}]
    pairs = re.findall(r"<dt>(.*?)</dt><dd>(.*?)</dd>", block.group(1), re.DOTALL)
    if not pairs:
        return [{"term": "n/a", "definition": "n/a"}]
    return [{"term": _strip_tags(t), "definition": _strip_tags(d)} for t, d in pairs]


def _specs_text(blocks: dict[str, Any] | None) -> str:
    """What the page must STILL do after a perf fix: the simulation specs."""
    if not blocks:
        return "(specs unavailable: preserve the page's teaching behaviour)"
    lines = []
    for b in blocks.get("blocks", []):
        if b["type"] == "simulation":
            s = b["spec"]
            controls = (
                ", ".join(
                    f"{c.get('id')} ({c.get('min')}..{c.get('max')})"
                    for c in s.get("controls", [])
                )
                or "none (animation)"
            )
            lines.append(
                f'- {b["id"]} "{s.get("title")}": goal: {s.get("learning_goal")}; '
                f"shows: {s.get('default_behaviour')}; controls: {controls}"
            )
    return "\n".join(lines) or "(no simulations on this page)"


def _system() -> str:
    return (
        "[ZIVON STAGE: 08-fixloop] You are the Performance Engineer agent. A generated study "
        "page missed its performance budget on weak-hardware simulation (Chromium under CPU "
        "throttling and core pinning, simulating a low-end Android phone).\n"
        "RULES:\n- Return exactly ONE JSON object.\n"
        "- You may only replace page.js and page.css contents; never reference external "
        "resources; never use eval/Function/fetch/import.\n"
        "- The page must still TEACH after your fix: every simulation keeps its spec's "
        "learning_goal, default_behaviour and controls. Do not delete or neuter required "
        "behaviour to gain speed; if the only way to meet the budget is to remove required "
        "behaviour, say so in analysis instead of doing it.\n"
        "- Prefer fixing JS hot paths: avoid per-frame allocations, avoid layout thrash, "
        "cache 2d context state, reduce draw complexity.\n"
    )


def _user_msg(
    cfg: Config,
    report: dict[str, Any],
    files: dict[str, str],
    round_no: int,
    rounds: int,
    specs: str,
    attempts: list[str],
) -> str:
    measurements = json.dumps(
        {
            "budgets": report.get("budgets", {}),
            "failures": report["failures"],
            "measured": report["measured"],
        },
        indent=1,
    )
    files_text = (
        "\n\n".join(f"=== {name} ===\n{content}" for name, content in files.items())
        or "(no topic files yet)"
    )
    attempts_text = "\n".join(f"- {a}" for a in attempts) or "- (none yet)"
    return (
        f"ROUND {round_no} of {rounds}.\n\n"
        f"PERF REPORT (budgets vs measured):\n{measurements}\n\n"
        f"PAGE SPECS (what the page must still do after your fix):\n{specs}\n\n"
        f"PREVIOUS ATTEMPTS (do not repeat a failed fix unchanged):\n{attempts_text}\n\n"
        f"CURRENT TOPIC FILES:\n{files_text}\n\n"
        "DESIGN DOCTRINE + LESSON-PAGE EXAMPLE (the visual language of this "
        "page - this is a PERFORMANCE fix: keep the look exactly, optimize the "
        "code, do not redesign or restyle):\n"
        + design_context(cfg, with_examples=True)
        + "\n\nPALETTE (exact values from the page stylesheet; use these, "
        "invent nothing):\n"
        + palette_text(cfg)
        + '\n\nReturn {"analysis": "what is slow and why", "files": {"page.js": '
        '"<full new content>", "page.css": "<full new content or omit>"}}. Omit files '
        "you do not change. File contents must be complete replacements."
    )


def _finish(
    cfg: Config,
    run_ctx: RunContext,
    history: list,
    topic_dir: Path,
    site: Path,
    ok: bool,
) -> None:
    run_ctx.write_json(run_ctx.stage_dir(STAGE_ID) / "history.json", history)
    if ok:
        # sync final files into the staging site copy
        manifest = json.loads((topic_dir / "manifest.json").read_text(encoding="utf-8"))
        course_id = manifest["course_id"]
        slug = manifest["topic_slug"]
        site_topic = site / "courses" / course_id / slug
        if site_topic != topic_dir:
            for name in ("index.html", "page.js", "page.css", "manifest.json"):
                src = topic_dir / name
                if src.exists():
                    shutil.copy2(src, site_topic / name)
