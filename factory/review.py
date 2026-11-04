"""Stage 09-review: the Code Reviewer agent, plus a final static pass.

The model reviews the final page (HTML + JS + CSS + manifest) against the repo
checklist: correctness against the block specs AND against the cited ground
truth (the sim's drawn behaviour included - 08-fixloop may have rewritten the
code after 03-check saw the draft), the LIVE design doctrine and its reference
lesson-page example (injected via factory/design.py), safety (no eval, no
external calls - also enforced mechanically by lint), accessibility, and
performance hygiene. Fatal model
findings or fatal lints stop the run here; nothing is linked into frontend/
until this stage passes.

Graph v2: a fail verdict is ROUTED to 10-reviewfix (the paired catcher) by the
orchestrator - this stage returns the report instead of raising, so the
reviewer's findings reach the fixer instead of killing the run. Mechanical
lint hits still raise immediately (the shipped files themselves are broken).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context
from .errors import LintError
from .lint import lint_file
from .llm import LLMClient
from .schemas import REVIEW_REPORT

STAGE_ID = "09-review"

REVIEWABLE = ("index.html", "page.js", "page.css")


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    blocks: dict[str, Any],
    render_out: dict[str, Any],
    ground_truth: dict[str, Any],
    round_tag: str | None = None,
) -> dict[str, Any]:
    topic_dir = Path(render_out["topic_dir"])

    # Mechanical pass first: every shipped file must be lint-clean.
    all_hits: list[str] = []
    for name in REVIEWABLE:
        p = topic_dir / name
        if p.exists():
            all_hits += lint_file(p)
    if all_hits:
        raise LintError(
            STAGE_ID,
            "final files violate hard lints:\n" + "\n".join(all_hits),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )

    files_text = "\n\n".join(
        f"=== {name} ===\n{(topic_dir / name).read_text(encoding='utf-8')}"
        for name in REVIEWABLE
        if (topic_dir / name).exists()
    )
    spec_text = json.dumps(blocks["blocks"], indent=1, ensure_ascii=False)
    manifest_text = json.dumps(render_out["manifest"], indent=2, ensure_ascii=False)
    facts_text = _facts_text(ground_truth)

    report = llm.call(
        STAGE_ID,
        [
            {"role": "system", "content": _system()},
            {
                "role": "user",
                "content": (
                    "BLOCK SPECS (what the page must implement):\n"
                    + spec_text
                    + "\n\nCITED FACTS (the ground truth this page must not "
                    "contradict):\n"
                    + facts_text
                    + "\n\nMANIFEST:\n"
                    + manifest_text
                    + "\n\nFINAL PAGE FILES:\n"
                    + files_text
                    + "\n\nDESIGN DOCTRINE + LESSON-PAGE EXAMPLE (the visual "
                    "language this page must follow):\n"
                    + design_context(cfg, with_examples=True)
                    + "\n\nTASK: Hunt for REAL defects in this generated page before it "
                    "is linked into the site: implementations that contradict the block "
                    "specs or the cited facts, broken answer keys, unusable interactive "
                    "elements. If the page is genuinely correct, return verdict=pass with "
                    "an empty issues array - do not invent problems to justify your role. "
                    "If you suspect an issue but cannot confirm it from the files above, "
                    "report it as minor with the message starting 'unverified:' - never "
                    "as fatal or major.\n"
                    "Checklist:\n"
                    "1. Every block spec is implemented correctly in the HTML/JS (quiz options "
                    "match, answer indices match, simulation controls match, diagram present). "
                    "The simulation's DRAWN behaviour (the draw loop) must be consistent with "
                    "its spec's description/default_behaviour and the CITED FACTS: a simulation "
                    "that draws physically wrong behaviour is a fatal issue.\n"
                    "2. Accessibility: interactive elements are keyboard reachable, have visible focus "
                    "and accessible names; feedback regions are aria-live.\n"
                    "3. Performance hygiene: no per-frame allocations beyond necessity, canvas ops are "
                    "batched, no synchronous layout reads in the draw loop.\n"
                    "4. Code quality: clear names, no dead code, no console.log left in.\n"
                    "5. Visual language: the page follows the DESIGN DOCTRINE above "
                    "(colour roles, diagram and simulation stroke rules). A clear "
                    "doctrine violation is a major issue; a violation that misleads "
                    "the learner about what moves or what is correct is fatal.\n"
                    "6. Frame adaptation (doctrine §10.2): the page must fit without horizontal "
                    "overflow and hold its 36 px ruled rhythm at ~360 px, ~768 px and ~1280 px "
                    "widths: diagrams scale through viewBox (no fixed width/height attributes), "
                    "text reflows, nothing depends on a laptop-only layout. A layout that "
                    "overflows or breaks on a phone frame is a major issue.\n"
                    'Return {"verdict": "pass"|"fail", "issues": [{"block_id" optional, '
                    '"severity": "fatal"|"major"|"minor", "message"}]}. Severity: fatal = a '
                    "block spec is implemented wrongly, an answer key is broken, or drawn "
                    "behaviour contradicts the CITED FACTS; major = a learner would be misled "
                    "or an interactive element is unusable; minor = style. verdict=fail only "
                    "if you report at least one fatal issue; major and minor issues alone do "
                    "not fail the page."
                ),
            },
        ],
        REVIEW_REPORT,
        "review_report",
        round_tag=round_tag,
    )

    rule_issues = [
        {"severity": "fatal", "message": issue}
        for issue in _static_review_findings(topic_dir)
    ]
    report.setdefault("issues", [])
    fatal_model = [i for i in report["issues"] if i["severity"] == "fatal"]
    if rule_issues or fatal_model:
        report["verdict"] = "fail"
        report["issues"] = rule_issues + report["issues"]
    run_ctx.save_stage_output(STAGE_ID, report)
    if round_tag:
        run_ctx.write_json(
            run_ctx.stage_dir(STAGE_ID) / f"report-{round_tag}.json", report
        )
    # Graph v2: a fail verdict is ROUTED to 10-reviewfix by the orchestrator
    # (the catcher paired with this gate); the report is the handoff.
    return report


def _facts_text(ground_truth: dict[str, Any]) -> str:
    """All claims + equations: the final page must not contradict any of them.
    03 checked the DRAFT against sources; 09 must be able to check the FINAL
    code (after 08-fixloop rewrote it) against the same facts."""
    lines = [
        f"- {c['id']}: {c['statement']} ["
        + ", ".join(f"{x['source_id']} {x['locator']}" for x in c["citations"])
        + "]"
        for c in ground_truth["claims"]
    ]
    for e in ground_truth.get("equations", []):
        lines.append(f"- {e['id']}: {e['expression']} ({e['description']})")
    return "\n".join(lines)


def _static_review_findings(topic_dir: Path) -> list[str]:
    findings = []
    html = (topic_dir / "index.html").read_text(encoding="utf-8")
    if "Content-Security-Policy" not in html:
        findings.append("index.html is missing the Content-Security-Policy meta tag")
    if 'lang="en"' not in html:
        findings.append("index.html is missing lang attribute")
    manifest_path = topic_dir / "manifest.json"
    if not manifest_path.exists():
        findings.append("manifest.json missing from the topic directory")
    else:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not data.get("sources"):
            findings.append("manifest has no sources listed (traceability broken)")
    return findings


def _system() -> str:
    return (
        "[ZIVON STAGE: 09-review] You are the Code Reviewer agent for the Zivon content "
        "factory. You are the last gate before a generated page is linked into the site.\n"
        "RULES:\n- Be strict about correctness and accessibility; be honest about uncertainty.\n"
        "- Output exactly ONE JSON object.\n"
    )
