"""Stage 10-review: the Code Reviewer agent, plus a final static pass.

The model reviews the final page (HTML + JS + CSS + manifest) against the repo
checklist: correctness against the block specs, safety (no eval, no external
calls - also enforced mechanically by lint), accessibility, and performance
hygiene. Fatal model findings or fatal lints stop the run here; nothing is
linked into frontend/ until this stage passes.
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


def run(cfg: Config, run_ctx: RunContext, llm: LLMClient,
        blocks: dict[str, Any], render_out: dict[str, Any]) -> dict[str, Any]:
    topic_dir = Path(render_out["topic_dir"])

    # Mechanical pass first: every shipped file must be lint-clean.
    all_hits: list[str] = []
    for name in REVIEWABLE:
        p = topic_dir / name
        if p.exists():
            all_hits += lint_file(p)
    if all_hits:
        raise LintError(STAGE_ID, "final files violate hard lints:\n" + "\n".join(all_hits),
                        artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)))

    files_text = "\n\n".join(
        f"=== {name} ===\n{(topic_dir / name).read_text(encoding='utf-8')}"
        for name in REVIEWABLE if (topic_dir / name).exists()
    )
    spec_text = json.dumps(blocks["blocks"], indent=1, ensure_ascii=False)
    manifest_text = json.dumps(render_out["manifest"], indent=2, ensure_ascii=False)

    report = llm.call(STAGE_ID, [
        {"role": "system", "content": _system()},
        {"role": "user", "content": (
            "BLOCK SPECS (what the page must implement):\n" + spec_text +
            "\n\nMANIFEST:\n" + manifest_text +
            "\n\nFINAL PAGE FILES:\n" + files_text +
            "\n\nTASK: Review this generated page before it is linked into the site.\n"
            "Checklist:\n"
            "1. Every block spec is implemented correctly in the HTML/JS (quiz options match, "
            "answer indices match, simulation controls match, diagram present).\n"
            "2. Accessibility: interactive elements are keyboard reachable, have visible focus "
            "and accessible names; feedback regions are aria-live.\n"
            "3. Performance hygiene: no per-frame allocations beyond necessity, canvas ops are "
            "batched, no synchronous layout reads in the draw loop.\n"
            "4. Code quality: clear names, no dead code, no console.log left in.\n"
            "Return {\"verdict\": \"pass\"|\"fail\", \"issues\": [{\"block_id\" optional, "
            "\"severity\": \"fatal\"|\"major\"|\"minor\", \"message\"}]}."
        )},
    ], REVIEW_REPORT, "review_report")

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
            "code review failed: " + "; ".join(i["message"][:160] for i in report["issues"]),
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
        )
    return report


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
