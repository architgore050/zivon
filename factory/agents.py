"""Prompt builders and runner functions for the model stages.

Graph v2 (2026-11-03): the reasoning layer is ONE giant call (02-generate:
Curator + Synthesizer + Instructional Designer), the review gates stay
separate (03-check, 09-review), and every gate failure is routed to its own
catcher (04-repair, 08-fixloop, 10-reviewfix) - the pipeline never re-runs
upstream stages on a downstream failure.

Every system prompt starts with a stable marker `[ZIVON STAGE: <id>]` so run
artifacts and the test mock can identify stages mechanically.

Global prompt law (mirrors repo rules):
- English only.
- Never invent facts, numbers, page numbers or citations; if the sources do
  not answer something, say so in the designated field instead of guessing.
- Output exactly one JSON object; no prose, no markdown fences.
"""

from __future__ import annotations

from typing import Any

from . import checks
from .artifacts import RunContext
from .config import Config
from .design import design_context, palette_text
from .llm import LLMClient
from .schemas import CHECK_REPORT, GENERATED, REPAIR

GLOBAL_RULES = (
    "RULES:\n"
    "- Use only the information in the provided source material. Never invent facts, "
    "numbers, page numbers, or citations.\n"
    "- Your knowledge of Physics does NOT count: if a concept is not explained in the "
    "source material, this page must not teach it, test it, or mention it - even if it "
    "is standard Physics. The source material is the whole universe of this page.\n"
    "- Write in simple English suited to an Indian school student.\n"
    "- If you are unsure about something, record it in the designated field rather than guessing.\n"
    "- Output exactly ONE JSON object and nothing else. No markdown, no commentary.\n"
)


def _system(stage_id: str, role: str) -> str:
    return f"[ZIVON STAGE: {stage_id}] You are the {role} in the Zivon content factory.\n{GLOBAL_RULES}"


def _pack_text(cfg: Config, source_pack: dict[str, Any]) -> str:
    ch = source_pack["chapter"]
    parts = [
        (
            f"PRIMARY SOURCE: {ch['book_title']} (NCERT, class {ch['class']}), "
            f"chapter '{ch['title']}', pages {ch['pages'][0]}-{ch['pages'][1]}. Text follows:"
        ),
        source_pack["ncert_text"],
    ]
    budget = cfg.limits["max_chars_supplement_total"]
    used = 0
    for s in source_pack["supplements"]:
        header = f"\n[SOURCE {s['source_id']} | {s['book_title']} | pages {s['page_from']}-{s['page_to']}]"
        text = s["text"]
        if used + len(text) > budget:
            break
        used += len(text)
        parts.append(header)
        parts.append(text)
    return "\n\n".join(parts)


# ------------------------------------------------------------ 02-generate
def run_generate(
    cfg: Config, run_ctx: RunContext, llm: LLMClient, source_pack: dict[str, Any]
) -> dict[str, Any]:
    """The one giant generation call: ground truth + lesson + blocks in a
    single JSON object. Replaces 02-synth + 03-explain + 04-draft (graph v1),
    so the reasoning layer pays ONE thinking cycle, not three."""
    ch = source_pack["chapter"]
    user = (
        f"GOAL: build the COMPLETE study page for chapter '{ch['title']}' from "
        f"{ch['book_title']} (class {ch['class']}). Your entire universe of facts "
        "is the SOURCE MATERIAL below. Success means: a student of this class "
        "who has never seen the topic can learn the WHOLE chapter from this page "
        "alone - correctly, patiently, and well enough to face every problem the "
        "chapter sets. A wrong or invented fact here becomes an exam answer, so "
        "every factual statement must be traceable to the sources.\n\n"
        "COVERAGE CONTRACT (the page fails without it): the chapter is the unit "
        "of teaching - a page that teaches only part of the chapter is a FAILED "
        "page even if everything it does teach is correct. Before drafting, take "
        "an inventory of the chapter: its titled sections, its in-text questions "
        "(Pause and Ponder, Think as a Scientist), its worked examples, and its "
        "end-of-chapter exercises. Then map every item: chapter section -> a "
        "lesson section; in-text question or conceptual exercise -> a check "
        "block; worked example or multi-step numerical problem -> a "
        "worked_example block; a derivation or method the source walks through "
        "-> a reveal block. Nothing from the inventory may be dropped. If a "
        "problem is unreadable in the source text (garbled figure data), replace "
        "it with an equivalent problem that the source's own method solves - "
        "never silently skip it.\n\n"
        "SOURCE MATERIAL:\n\n"
        + _pack_text(cfg, source_pack)
        + "\n\nDESIGN DOCTRINE (the visual rules this page must follow; the "
        "diagrams you spec must obey its diagram rules):\n"
        + design_context(cfg, with_examples=False)
        + "\n\nPALETTE (exact values from the page stylesheet; use these for "
        "diagram fill/stroke, invent nothing):\n"
        + palette_text(cfg)
        + "\n\nDELIVERABLE: ONE JSON object with exactly three layers - "
        '"ground_truth", "lesson", "blocks".\n\n'
        'LAYER 1 "ground_truth" - the page\'s fact base, synthesized from the '
        "sources above.\n"
        '- "topic": short topic name\n'
        '- "summary": 3-6 sentence overview\n'
        '- "claims": 12-40 factual claims; each {"id": "claim-01", "statement": "...", '
        '"citations": [{"source_id": "<id from the [SOURCE ...] headers, or \\"ncert\\" for the primary source>", '
        '"locator": "page 123" or "section name"}]}. One testable fact per claim, quotable from '
        "a single passage. Prioritise what a student needs to solve the chapter's problems: "
        "definitions, laws, standard values, units. Copy numbers, units and their forms exactly "
        "as written in the sources - do not convert units or compute new values.\n"
        '- "key_terms": [{"term", "definition", "citations"}] - at least 4\n'
        '- "equations": [{"id": "eq-01", "expression": "plain text like v = u + a*t", "description", "citations"}] '
        "(empty array if none)\n"
        '- "misconceptions": [{"id": "mis-01", "wrong_belief", "correction", "citations"}] - '
        "Physics chapters almost always contain misconceptions the source addresses or "
        "corrects; search for them before returning an empty array\n"
        '- "uncertain": list of questions the sources do NOT answer clearly. If a fact you '
        "wanted to state has no clear passage behind it, record that question here instead of "
        "stating the fact. Use [] only if you are certain everything "
        "needed is covered.\n"
        'Use source_id "ncert" for the primary NCERT chapter text.\n\n'
        "LAYER 2 - lesson: edit the ground truth into a SELF-CONTAINED lesson that explains "
        f"everything slowly and properly for a first-time learner in class {cfg.learner['class_level']}.\n"
        "Write as a patient tutor speaking directly to the student ('you'): clear, "
        "encouraging, step by step. Quality bar:\n"
        "- TEACHING ORDER: start from an everyday observation the student recognises, then "
        "define, then formalise with symbols and equations.\n"
        "- INDEPENDENT OF OUTSIDE SOURCES: the reader has only this page - remove every "
        "context-specific reference ('previous chapter', 'the textbook', 'Figure 7.3', "
        "'as we saw', exercise numbers, page numbers).\n"
        "- Define every technical term the first time it appears.\n"
        "- One idea per paragraph; 3-5 sentences per paragraph; short sentences.\n"
        "- Do not add facts that are not in the ground truth; keep numbers and units exactly "
        "as they appear in it.\n"
        '- "title": lesson title\n'
        '- "objectives": 2-4 sentences, each "After this lesson you can ..."\n'
        '- "sections": one per chapter topic - every titled section of the chapter '
        'gets its own lesson section (typically 5-10) - of {"id": "sec-01", "title", "paragraphs": ["...", ...]} in teaching order\n'
        '- "glossary": [{"term", "definition"}] - at least 3, plain-English definitions\n\n'
        "LAYER 3 - blocks: lay the lesson out as an ordered block sequence for the study "
        "page. Valid claim ids for citations come from layer 1.\n"
        "Block types and spec shapes:\n"
        '- text: {"paragraphs": ["..."]} - carry the lesson prose in reading order\n'
        '- worked_example: {"problem": "...", "steps": [{"title", "detail"}], "answer": "..."} '
        "- every worked example and every multi-step numerical problem in the source "
        "becomes one. The numbers in the PROBLEM must appear VERBATIM in the source; "
        "the answer is then COMPUTED from those numbers using only equations and "
        "methods the source itself states, with every step shown. Never put a figure "
        "into the problem that the source does not give.\n"
        '- check: {"question", "format": "mcq"|"numeric", "options": ["A","B","C","D"], '
        '"answer_index": 0-3 (mcq), "answer": "text" (numeric), "explanation", '
        '"expected_understanding"} - every in-text question and conceptual exercise from '
        "your inventory becomes a check, and every lesson section gets at least one; "
        "single-step numerical exercises may become numeric checks. "
        "answer_index must point at the correct option; one option may address a listed misconception\n"
        '- reveal: {"title", "steps": [{"title", "detail"}]} - a step-by-step derivation or method\n'
        '- diagram: {"svg": "<svg ...>...</svg> string using only viewBox, rect, circle, line, '
        'path, text, polygon with fill/stroke presentation attributes", "caption"} - label '
        "everything in ink; use PALETTE values for fill/stroke; doctrine v1.3 diagram "
        "language: geometry is CLEAN - straight lines, true circles and arcs, every "
        "rectangle with one consistent corner style (three round corners and one right "
        "angle on the same box is a defect); NO wobble on shapes; the only hand-drawn "
        "element allowed is an annotation arrow pointing at a part (a slightly wobbly "
        "<path>); no <style>, no <script>, no external refs; use viewBox and NO fixed "
        "width/height attributes so the shell scales the diagram at any screen width\n"
        '- simulation: {"title", "description", "learning_goal", "controls": [{"id", "label", '
        '"min", "max", "step", "initial"}], "default_behaviour": "what it shows before any input"} '
        "- only if the topic clearly benefits; 1-3 controls; a simulation with zero controls is "
        "an animation\n"
        "Order: text sections interleaved with checks and visuals the way a good teacher would "
        "pace the lesson. First block must be text; last block must be a check.\n"
        "Frame law (doctrine §10.2): the page is read on phones (~360 px), tablets and laptops. "
        "Write for reflow: keep sentences and list items short enough to wrap cleanly, keep "
        "diagram viewBoxes wide-friendly, and never assume a fixed pixel layout - the shell "
        "owns layout and keeps every block on the 36 px ruled grid at every width.\n"
        "Cite claims in every text, worked_example, check and reveal block (a factual block "
        "without citations is rejected): "
        '"citations": [{"claim_id": "claim-01"}].\n'
        "Grounding law for the WHOLE page: every factual statement in every layer must be "
        "traceable to the SOURCE MATERIAL above. Do not build any block or check around a "
        "concept the chapter does not itself explain, even if you know that concept is "
        "standard Physics.\n\n"
        "Example of the required SHAPE (content is from an unrelated chapter - never reuse "
        'it):\n{"ground_truth": {"topic": "...", "summary": "...", "claims": [{"id": '
        '"claim-07", "statement": "The SI unit of mass is the kilogram.", "citations": '
        '[{"source_id": "ncert", "locator": "page 12"}]}], "key_terms": [], "equations": [], '
        '"misconceptions": [], "uncertain": []}, '
        '"lesson": {"title": "...", "objectives": ["After this lesson you can ..."], '
        '"sections": [{"id": "sec-01", "title": "...", "paragraphs": ["..."]}], '
        '"glossary": [{"term": "...", "definition": "..."}]}, '
        '"blocks": [{"id": "b-01", "type": "text", "spec": {"paragraphs": ["..."]}, '
        '"citations": [{"claim_id": "claim-01"}]}, '
        '{"id": "b-02", "type": "check", "spec": {"question": "...", "format": "mcq", '
        '"options": ["2 m/s", "4 m/s", "6 m/s", "8 m/s"], "answer_index": 1, '
        '"explanation": "...", "expected_understanding": "..."}, '
        '"citations": [{"claim_id": "claim-02"}]}, '
        '{"id": "b-03", "type": "simulation", "spec": {"title": "...", "description": "...", '
        '"learning_goal": "...", "controls": [{"id": "speed", "label": "Speed (m/s)", '
        '"min": 0, "max": 20, "step": 1, "initial": 5}], "default_behaviour": "..."}, '
        '"citations": [{"claim_id": "claim-03"}]}]}'
        "\n\nBefore you answer: reread the SOURCE MATERIAL against your draft - "
        "every number, unit and concept in the page must survive that reread, and "
        "every item of your chapter inventory must appear in the page. "
        "Return only the JSON object."
    )

    def rule_feedback(parsed: dict[str, Any]) -> list[str]:
        """Code-side rule checks AT GENERATION TIME: the model sees its own fatal
        or major rule violations in the retry transcript and fixes them, instead
        of the run dying at 03-check."""
        report = checks.run_all_rules(
            parsed.get("blocks", {}).get("blocks", []),
            parsed.get("lesson") or {},
            parsed.get("ground_truth") or {},
            source_pack,
        )
        return [
            f"[{i['rule']}] block {i['block_id']}: {i['message']}"
            for i in report["rule_issues"]
            if i["severity"] in ("fatal", "major")
        ]

    return llm.call(
        "02-generate",
        [
            {
                "role": "system",
                "content": _system(
                    "02-generate",
                    "Curator + Synthesizer + Instructional Designer (the generation agent)",
                ),
            },
            {"role": "user", "content": user},
        ],
        GENERATED,
        "generated page",
        extra_validator=rule_feedback,
    )


def _gt_text(gt: dict[str, Any]) -> str:
    lines = [f"TOPIC: {gt['topic']}", f"SUMMARY: {gt['summary']}", "CLAIMS:"]
    for c in gt["claims"]:
        loc = ", ".join(f"{x['source_id']} {x['locator']}" for x in c["citations"])
        lines.append(f"- {c['id']}: {c['statement']} [{loc}]")
    lines.append(
        "KEY TERMS: "
        + "; ".join(f"{t['term']}: {t['definition']}" for t in gt["key_terms"])
    )
    if gt["equations"]:
        lines.append(
            "EQUATIONS: "
            + "; ".join(
                f"{e['id']}: {e['expression']} ({e['description']})"
                for e in gt["equations"]
            )
        )
    if gt["misconceptions"]:
        lines.append(
            "MISCONCEPTIONS: "
            + "; ".join(
                f"{m['id']}: WRONG '{m['wrong_belief']}' CORRECT '{m['correction']}'"
                for m in gt["misconceptions"]
            )
        )
    if gt["uncertain"]:
        lines.append(
            "UNCERTAIN (do not resolve by inventing): " + "; ".join(gt["uncertain"])
        )
    return "\n".join(lines)


def _lesson_text(lesson: dict[str, Any]) -> str:
    lines = [f"TITLE: {lesson['title']}", "OBJECTIVES:"]
    lines += [f"- {o}" for o in lesson["objectives"]]
    for s in lesson["sections"]:
        lines.append(f"SECTION {s['id']}: {s['title']}")
        lines += [p for p in s["paragraphs"]]
    lines.append(
        "GLOSSARY: "
        + "; ".join(f"{g['term']}: {g['definition']}" for g in lesson["glossary"])
    )
    return "\n".join(lines)


def _blocks_text(blocks: dict[str, Any]) -> str:
    import json as _json

    return _json.dumps(blocks["blocks"], indent=1, ensure_ascii=False)


# --------------------------------------------------------------- 03-check
def run_check(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    source_pack: dict[str, Any],
    ground_truth: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    round_tag: str | None = None,
) -> dict[str, Any]:
    user = (
        "SOURCE MATERIAL (the only allowed facts):\n\n"
        + _pack_text(cfg, source_pack)
        + "\n\nGROUND TRUTH:\n\n"
        + _gt_text(ground_truth)
        + "\n\nTHE LESSON THE PAGE TEACHES (what the student has already been "
        "taught by the time they reach each check):\n\n"
        + _lesson_text(lesson)
        + "\n\nDRAFT BLOCKS TO REVIEW:\n\n"
        + _blocks_text(blocks)
        + "\n\nTASK: You are the Comprehension & Fact Reviewer. Hunt for REAL "
        "errors: invented numbers, unit mismatches, answers that do not match the "
        "question, concepts smuggled in from outside the chapter, and whole-chapter "
        "gaps. Do not invent problems to justify your role - if the draft is "
        "faithful to the sources AND covers the chapter, "
        "return verdict=pass with an empty issues array. Review every block:\n"
        "1. Is each factual statement correct per the source material? Quote the source in your issue.\n"
        "2. Is every check's correct answer actually correct?\n"
        "3. Is the language and depth right for a class "
        f"{cfg.learner['class_level']} first-time learner (not above, not below)?\n"
        "4. Does anything read as if it depends on material outside this page?\n"
        "5. For every check block: does the page teach the expected_understanding before "
        "asking for it? A check that asks something the page never taught is major.\n"
        "6. RECOMPUTE every worked_example and numeric check yourself from its "
        "problem data, using only the equations and methods the source itself "
        "states. A wrong computed answer or wrong arithmetic step is fatal.\n"
        "7. COVERAGE: compare the page against the chapter's own structure - its "
        "titled sections, in-text questions, worked examples and end-of-chapter "
        "exercises. Every one of them must appear on the page - taught, tested or "
        "worked. Report every omission, quoting the chapter item that is missing.\n"
        "Severity ladder (apply it exactly):\n"
        "- fatal: a statement CONTRADICTS the source material, a check's answer key "
        "or a worked_example's computed answer is wrong, or the page omits a chapter "
        "section, worked example or exercise that the SOURCE MATERIAL itself teaches. "
        "You must quote the source passage (or the omitted chapter item) that proves it.\n"
        "- major: a block teaches, tests, or relies on a Physics concept that the SOURCE "
        "MATERIAL never explains (a smuggled-in concept), or a learner would otherwise be "
        "misled about what moves or what is correct.\n"
        "- minor: everything else - style, wording, and common-knowledge definitions that "
        "the source does not spell out (e.g. 'SI means the standard system of units'). "
        "Minor issues are advisory and must never fail the page.\n"
        "If you suspect a problem but cannot verify it against the source material, report "
        "it as minor with the message starting 'unverified:' - never as fatal or major.\n"
        'Return a JSON object: {"verdict": "pass"|"fail", "issues": '
        '[{"block_id": "b-01" or omit, "severity": "fatal"|"major"|"minor", '
        '"message": "..."}]}. verdict=fail if and only if you report at least one fatal '
        "issue. An empty issues array means pass.\n\n"
        'Example issue (SHAPE only - never reuse it): {"block_id": "b-05", "severity": "fatal", "message": '
        '"The block states the SI unit of speed is km/h; the source states the SI unit of '
        'speed is m/s [ncert page 12]."}'
    )
    return llm.call(
        "03-check",
        [
            {
                "role": "system",
                "content": _system("03-check", "Comprehension & Fact Reviewer agent"),
            },
            {"role": "user", "content": user},
        ],
        CHECK_REPORT,
        "check_report",
        round_tag=round_tag,
    )


# -------------------------------------------------------------- 04-repair
def run_repair(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    source_pack: dict[str, Any],
    ground_truth: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    issues: list[dict[str, Any]],
    round_tag: str,
) -> dict[str, Any]:
    """The content catcher: fixes ONLY the flagged blocks, grounded in the
    source pack. The reviewer's verdict is the input - the catcher that caught
    the issue routes it here instead of re-running the whole pipeline."""
    claim_ids = ", ".join(c["id"] for c in ground_truth["claims"])
    issue_lines = "\n".join(
        f"- [{i['severity']}] block {i.get('block_id', '(page level)')}: {i['message']}"
        for i in issues
    )
    user = (
        "SOURCE MATERIAL (the only allowed facts):\n\n"
        + _pack_text(cfg, source_pack)
        + "\n\nGROUND TRUTH:\n\n"
        + _gt_text(ground_truth)
        + "\n\nCURRENT BLOCKS:\n\n"
        + _blocks_text(blocks)
        + "\n\nDESIGN DOCTRINE (visual rules the fixed blocks must obey):\n"
        + design_context(cfg, with_examples=False)
        + "\n\nPALETTE (exact values; invent nothing):\n"
        + palette_text(cfg)
        + f"\n\nREVIEWER FINDINGS TO FIX (valid claim ids: {claim_ids}):\n{issue_lines}\n\n"
        "TASK: You are the Content Repair agent. The Fact Reviewer flagged the issues "
        "above. Fix ONLY the flagged blocks; leave every other block exactly as it is.\n"
        "For each flagged block return its COMPLETE replacement (same id, same type "
        "unless the fix requires a different type). Rules:\n"
        "- A 'smuggled concept' fix: rewrite the block so it teaches/tests ONLY what "
        "the SOURCE MATERIAL covers. If the block cannot be fixed that way, OMIT it "
        "from your output entirely (it will be removed from the page).\n"
        "- A wrong-number or wrong-answer fix: problem data must use values that "
        "appear VERBATIM in the source material or ground truth; a computed answer "
        "must be recomputed from those values using only the source's own equations.\n"
        "- A coverage-omission fix: ADD the missing teaching or testing as NEW "
        "blocks with new ids continuing the sequence (e.g. b-16, b-17...). New "
        "blocks are appended at the end of the page: order them teach-then-test "
        "and make your LAST added block a check. Ground every new fact in the "
        "SOURCE MATERIAL and cite claim ids.\n"
        "- Keep the page coherent: the first block stays text and the last stays a check.\n"
        "- Every replacement block that states facts must cite claim ids.\n"
        'Return {"analysis": "what you changed and why each fix is grounded", '
        '"blocks": [complete replacement blocks...]}. Only replacement blocks - not '
        "the whole page.\n\n"
        "Example of the required SHAPE (content from an unrelated chapter - never "
        'reuse it):\n{"analysis": "b-05 tested mass/force, which this chapter never '
        'defines; rewrote it as a speed comparison grounded in claim-03.", '
        '"blocks": [{"id": "b-05", "type": "check", "spec": {"question": "...", '
        '"format": "mcq", "options": ["..."], "answer_index": 0, "explanation": '
        '"...", "expected_understanding": "..."}, "citations": [{"claim_id": '
        '"claim-03"}]}]}'
    )

    def rule_feedback(parsed: dict[str, Any]) -> list[str]:
        merged = merge_blocks(blocks, parsed.get("blocks", []))
        report = checks.run_all_rules(
            merged["blocks"], lesson, ground_truth, source_pack
        )
        return [
            f"[{i['rule']}] block {i['block_id']}: {i['message']}"
            for i in report["rule_issues"]
            if i["severity"] in ("fatal", "major")
        ]

    return llm.call(
        "04-repair",
        [
            {
                "role": "system",
                "content": _system(
                    "04-repair", "Content Repair agent (fixers of the Synthesizer)"
                ),
            },
            {"role": "user", "content": user},
        ],
        REPAIR,
        "repair plan",
        round_tag=round_tag,
        extra_validator=rule_feedback,
    )


def merge_blocks(
    current: dict[str, Any], replacements: list[dict[str, Any]]
) -> dict[str, Any]:
    """Apply repair replacements by id: replace in place, append new ids,
    remove flagged blocks the repair chose to omit (omission is signalled by
    the caller via `removed_ids`)."""
    by_id = {b["id"]: b for b in replacements}
    merged = [by_id.pop(b["id"], b) for b in current["blocks"]]
    existing = {b["id"] for b in merged}
    merged.extend(b for b in replacements if b["id"] not in existing)
    return {"blocks": merged}


def remove_blocks(current: dict[str, Any], removed_ids: set[str]) -> dict[str, Any]:
    return {"blocks": [b for b in current["blocks"] if b["id"] not in removed_ids]}
