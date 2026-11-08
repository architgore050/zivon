"""Stage 09-review: the Code Reviewer agent - TWO bounded model calls + a final static pass.

The split (2026-11-08 founder decision, after repeated 09-review thinking
loops): one giant call asked a single model to hold block specs + cited facts
+ manifest + all page files + the design doctrine + its lesson example and
self-plan a whole review. Even with the bounded six-step procedure (same day,
earlier attempt) the call thought 24k-130k tokens before answering and the
09<->10 catcher loop plateaued on it. The task is now two smaller calls, each
carrying only the context its checks need:

- 09-review-facts  - the page's TRUTH: answer keys, contradictions of the
  CITED FACTS, simulations' DRAWN behaviour, HTML-vs-JS value inconsistencies.
  Context: block specs + cited facts + final files. No doctrine, no example.
- 09-review-design - the page's VISUAL USABILITY: doctrine compliance, frame
  law, usability/access, plus a general RENDERING SWEEP - judging what a
  learner would see (labels vs what is drawn, clipped text, broken canvases,
  animations contradicting captions), not just comparison against the doctrine
  example. Context: compact block inventory + final files + doctrine + example.
  No full specs, no facts list.

The verdict is computed by the HARNESS (fail iff any fatal issue - the rule
that used to be prompt prose is now code), and each call outputs issues only.
Every issue carries a category; all of them land in the run's
issues_ledger.jsonl for cross-run failure-class analysis (founder's logging
ask).

The manifest is no longer sent to the model: it is mechanical page metadata
(course/class/title/chapter/sources) whose traceability the static checks
below already enforce; both calls get a 3-line identity header instead.

Mechanical pass first: every shipped file must be lint-clean, and the static
findings below (CSP meta, lang attr, manifest traceability) are fatal by code.
Fatal model findings or fatal lints stop the run here; nothing is linked into
frontend/ until this stage passes.

Graph v2 unchanged: a fail verdict is ROUTED to 10-reviewfix (the paired
catcher) by the orchestrator - this stage returns the merged report instead of
raising, so the reviewers' findings reach the fixer instead of killing the
run. Mechanical lint hits still raise immediately (the shipped files
themselves are broken).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .design import design_context
from .errors import LintError
from .ledger import issue_entry
from .lint import lint_file
from .llm import LLMClient
from .schemas import REVIEW_CALL_REPORT

STAGE_ID = "09-review"

REVIEWABLE = ("index.html", "page.js", "page.css")

# The two bounded procedures. Each call commits to one pass, one check per
# item; the severity ladder is stated once per call; the honest way-out
# ('unverified:' minor) and the compact-output rule are shared law.
_FACTS_TASK = (
    "TASK: You are the fact checker - this page's TRUTH gate. Run the "
    "inspection procedure below EXACTLY ONCE, in this order. Commit to this "
    "procedure: one pass, one check per item, then the issues. Your entire "
    "visible output is the final JSON object.\n"
    "STEP 1 - Answer keys. For each quiz, check and worked_example block, "
    "in BLOCK SPECS order: is its stated answer physically correct, given "
    "the CITED FACTS and the numbers on the page? A wrong answer key is a "
    "fatal issue (category answer_key).\n"
    "STEP 2 - Facts sweep. Read CITED FACTS top to bottom. For each fact "
    "ask exactly one question: does any code or text on this page "
    "contradict it? The source pack is this page's whole universe, so a "
    "contradiction is fatal (category fact). The facts themselves are "
    "already verified - do not re-derive them.\n"
    "STEP 3 - Drawn behaviour. For each simulation block: is its DRAWN "
    "behaviour (the draw loop) consistent with the CITED FACTS and its "
    "spec's description/default_behaviour? Drawing physically wrong "
    "behaviour is a fatal issue (category drawn_behaviour).\n"
    "STEP 4 - Consistency sweep. Compare every quantity, answer and "
    "statement wherever it appears: index.html text vs page.js values vs "
    "visible labels. A page that displays one value while its code computes "
    "or rewrites another (e.g. HTML shows 49 s while the script mutates it "
    "to 37 s) is inconsistent - fatal when a learner would be misled "
    "(category inconsistency).\n"
    "STEP 5 - Report. Severity ladder: fatal = a wrong answer key, a "
    "contradiction of the CITED FACTS, physically wrong drawn behaviour, or "
    "a misleading inconsistency; major = a learner would be misled but the "
    "physics stays usable; minor = style or wording. If you suspect an issue "
    "but cannot confirm it from the files above, report it as minor with "
    "the message starting 'unverified:' - never as fatal or major. If the "
    "page's truth is genuinely correct, return an empty issues array - do "
    "not invent problems to justify your role.\n"
    'Return {"issues": [{"block_id": optional, "severity": '
    '"fatal"|"major"|"minor", "category": "answer_key"|"fact"|'
    '"drawn_behaviour"|"inconsistency", "message"}]} - keep every issue '
    "message under 40 words with one concrete pointer (a block id or a short "
    "quoted snippet)."
)

_DESIGN_TASK = (
    "TASK: You are the design and rendering reviewer - this page's VISUAL "
    "USABILITY gate. Run the inspection procedure below EXACTLY ONCE, in "
    "this order. Commit to this procedure: one pass, one check per item, "
    "then the issues. Your entire visible output is the final JSON object.\n"
    "STEP 1 - Visual language. The page follows the DESIGN DOCTRINE above "
    "(colour roles, diagram and simulation stroke rules), judged against it "
    "and the lesson-page example. A clear doctrine violation is a major "
    "issue (category visual_language); a violation that misleads the learner "
    "about what moves or what is correct is fatal.\n"
    "STEP 2 - Frame law (doctrine section 10.2). No horizontal overflow at "
    "~360 px, ~768 px and ~1280 px; diagrams scale through viewBox (no fixed "
    "width/height attributes); text reflows; nothing depends on a laptop-only "
    "layout. A layout that overflows or breaks on a phone frame is a major "
    "issue (category frame).\n"
    "STEP 3 - Usability and access. For each interactive element: keyboard "
    "reachable, visible focus, accessible name; feedback regions aria-live. "
    "An unusable interactive element is a major issue (category "
    "accessibility).\n"
    "STEP 4 - Rendering sweep. Now judge the page as a learner would, not "
    "against the doctrine: for each diagram, simulation and quiz, does what "
    "is DRAWN match its labels, caption, axis units and legend? Look for "
    "clipped or overlapping text, empty or broken canvases, animations that "
    "contradict their caption, charts that visually suggest the opposite of "
    "the text, diagrams that read as decoration rather than as the concept. "
    "Anything that would confuse or mislead a learner looking at the render "
    "is an issue (category rendering): fatal when it misleads about the "
    "physics, major when it merely confuses.\n"
    "STEP 5 - Report. Severity ladder: fatal = a learner would be taught "
    "wrong physics by what is drawn or laid out; major = confusing or "
    "unusable; minor = style. If you suspect an issue but cannot confirm it "
    "from the files above, report it as minor with the message starting "
    "'unverified:' - never as fatal or major. If the page is genuinely "
    "well-built, return an empty issues array - do not invent problems to "
    "justify your role.\n"
    'Return {"issues": [{"block_id": optional, "severity": '
    '"fatal"|"major"|"minor", "category": "visual_language"|"frame"|'
    '"accessibility"|"rendering", "message"}]} - keep every issue message '
    "under 40 words with one concrete pointer (a block id or a short quoted "
    "snippet)."
)


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
    facts_text = _facts_text(ground_truth)
    identity = _identity_header(render_out)

    # Attempt artifacts namespace per call: attempts/facts/attempt-NN,
    # attempts/design/attempt-NN (re-reviews: attempts/round-01-facts/...).
    facts_tag = f"{round_tag}-facts" if round_tag else "facts"
    design_tag = f"{round_tag}-design" if round_tag else "design"

    facts_report = llm.call(
        STAGE_ID,
        [
            {"role": "system", "content": _system("09-review-facts", "fact checker")},
            {
                "role": "user",
                "content": (
                    identity
                    + "\n\nBLOCK SPECS (what the page must implement):\n"
                    + spec_text
                    + "\n\nCITED FACTS (the ground truth this page must not "
                    "contradict):\n"
                    + facts_text
                    + "\n\nFINAL PAGE FILES:\n"
                    + files_text
                    + "\n\n"
                    + _FACTS_TASK
                ),
            },
        ],
        REVIEW_CALL_REPORT,
        "review_call",
        round_tag=facts_tag,
    )
    design_report = llm.call(
        STAGE_ID,
        [
            {
                "role": "system",
                "content": _system("09-review-design", "design and rendering reviewer"),
            },
            {
                "role": "user",
                "content": (
                    identity
                    + "\n\nBLOCK INVENTORY (what the page contains):\n"
                    + _block_inventory(blocks)
                    + "\n\nFINAL PAGE FILES:\n"
                    + files_text
                    + "\n\nDESIGN DOCTRINE + LESSON-PAGE EXAMPLE (the visual "
                    "language this page must follow):\n"
                    + design_context(cfg, with_examples=True)
                    + "\n\n"
                    + _DESIGN_TASK
                ),
            },
        ],
        REVIEW_CALL_REPORT,
        "review_call",
        round_tag=design_tag,
    )

    issues = list(facts_report["issues"]) + list(design_report["issues"])
    rule_issues = [
        {"severity": "fatal", "category": "other", "message": issue}
        for issue in _static_review_findings(topic_dir)
    ]
    # The verdict rule that used to be prompt prose is now harness code:
    # fail iff any fatal issue (static or model-found); majors are advisory.
    has_fatal = any(i["severity"] == "fatal" for i in issues)
    report = {
        "verdict": "fail" if rule_issues or has_fatal else "pass",
        "issues": rule_issues + issues,
    }
    run_ctx.save_stage_output(STAGE_ID, report)
    if round_tag:
        run_ctx.write_json(
            run_ctx.stage_dir(STAGE_ID) / f"report-{round_tag}.json", report
        )
    run_ctx.append_ledger(
        "issues_ledger",
        [issue_entry(STAGE_ID, "facts", round_tag, i) for i in facts_report["issues"]]
        + [
            issue_entry(STAGE_ID, "design", round_tag, i)
            for i in design_report["issues"]
        ]
        # Static findings are generation defects (missing CSP meta, broken
        # traceability) - they belong in the ledger too, tagged by their call.
        + [issue_entry(STAGE_ID, "static", round_tag, i) for i in rule_issues],
    )
    print(
        f"[{STAGE_ID}] facts call: {len(facts_report['issues'])} issue(s); "
        f"design call: {len(design_report['issues'])} issue(s); "
        f"merged verdict={report['verdict']}"
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


def _identity_header(render_out: dict[str, Any]) -> str:
    """3-line page identity instead of the full manifest dump (2026-11-08):
    the manifest is mechanical metadata; its traceability is enforced by the
    static checks. The model only needs to know what page it is reviewing."""
    manifest = render_out.get("manifest", {})
    chapter = manifest.get("chapter", {})
    return (
        f"PAGE UNDER REVIEW: {manifest.get('title', '?')} "
        f"(chapter: {chapter.get('title', '?')}, class {manifest.get('class', '?')})"
    )


def _block_inventory(blocks: dict[str, Any]) -> str:
    """One line per block (id, type, one-line goal) for the design call -
    it must know what the page contains, not re-read every full spec."""
    lines = []
    for b in blocks["blocks"]:
        spec = b.get("spec", {})
        summary = (
            spec.get("learning_goal")
            or spec.get("problem")
            or spec.get("question")
            or (spec.get("paragraphs") or [""])[0]
        )
        summary = str(summary).strip().replace("\n", " ")
        if len(summary) > 90:
            summary = summary[:89] + "…"
        lines.append(f"- {b['id']} [{b['type']}] {summary}")
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


def _system(tag: str, role: str) -> str:
    return (
        f"[ZIVON STAGE: {tag}] You are the {role} agent for the Zivon content "
        "factory's final review gate (09-review).\n"
        "RULES:\n- Be strict about correctness and accessibility; be honest "
        "about uncertainty.\n- Output exactly ONE JSON object.\n"
    )
