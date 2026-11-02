"""Stage 10-review: the Code Reviewer agent, plus a final static pass.

The model reviews the final page (HTML + JS + CSS + manifest) against the repo
checklist: correctness against the block specs AND against the cited ground
truth (the sim's drawn behaviour included - 09-fixloop may have rewritten the
code after 05-check saw the draft), safety (no eval, no external calls - also
enforced mechanically by lint), accessibility, and performance hygiene. Fatal
model findings or fatal lints stop the run here; nothing is linked into
frontend/ until this stage passes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .errors import LintError
from .lint import lint_file
from .llm import LLMClient
from .schemas import REVIEW_REPORT

STAGE_ID = "10-review"

REVIEWABLE = ("index.html", "page.js", "page.css")


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    blocks: dict[str, Any],
    render_out: dict[str, Any],
    ground_truth: dict[str, Any],
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
                    + "\n\nTASK: Review this generated page before it is linked into the "
                    "site. Assume the page contains at least one defect; your job is to find "
                    "it.\n"
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
    if report["verdict"] == "fail":
        from .errors import StageError

        raise StageError(
            STAGE_ID,
            "code review failed: "
            + "; ".join(i["message"][:160] for i in report["issues"]),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    return report


def _facts_text(ground_truth: dict[str, Any]) -> str:
    """All claims + equations: the final page must not contradict any of them.
    05 checked the DRAFT against sources; 10 must be able to check the FINAL
    code (after 09-fixloop rewrote it) against the same facts."""
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
        "[ZIVON STAGE: 10-review] You are the Code Reviewer agent for the Zivon content "
        "factory. You are the last gate before a generated page is linked into the site.\n"
        "RULES:\n- Be strict about correctness and accessibility; be honest about uncertainty.\n"
        "- Output exactly ONE JSON object.\n"
    )
