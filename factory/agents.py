"""Prompt builders and runner functions for the model stages (02-05).

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
from .llm import LLMClient
from .schemas import BLOCKS, CHECK_REPORT, GROUND_TRUTH, LESSON

GLOBAL_RULES = (
    "RULES:\n"
    "- Use only the information in the provided source material. Never invent facts, "
    "numbers, page numbers, or citations.\n"
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


# ------------------------------------------------------------- 02-synth
def run_synth(
    cfg: Config, run_ctx: RunContext, llm: LLMClient, source_pack: dict[str, Any]
) -> dict[str, Any]:
    ch = source_pack["chapter"]
    user = (
        f"TOPIC: chapter '{ch['title']}' from {ch['book_title']} (class {ch['class']}).\n\n"
        "SOURCE MATERIAL:\n\n"
        + _pack_text(cfg, source_pack)
        + "\n\nTASK: Synthesize ONE ground truth for this chapter from the sources above.\n"
        "Return a JSON object with exactly these keys:\n"
        '- "topic": short topic name\n'
        '- "summary": 3-6 sentence overview\n'
        '- "claims": 8-20 factual claims; each {"id": "claim-01", "statement": "...", '
        '"citations": [{"source_id": "<id from the [SOURCE ...] headers, or "ncert" for the primary source>", '
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
        "stating the fact. Never leave this out; use [] only if you are certain everything "
        "needed is covered.\n"
        'Use source_id "ncert" for the primary NCERT chapter text.\n\n'
        "Example of the required SHAPE (content is from an unrelated chapter - never reuse "
        'it):\n{"id": "claim-07", "statement": "The SI unit of mass is the kilogram.", '
        '"citations": [{"source_id": "ncert", "locator": "page 12"}]}'
    )
    return llm.call(
        "02-synth",
        [
            {
                "role": "system",
                "content": _system(
                    "02-synth",
                    "Ground-Truth Synthesizer (Curator + Synthesizer agents)",
                ),
            },
            {"role": "user", "content": user},
        ],
        GROUND_TRUTH,
        "ground_truth",
    )


# ------------------------------------------------------------ 03-explain
def run_explain(
    cfg: Config, run_ctx: RunContext, llm: LLMClient, ground_truth: dict[str, Any]
) -> dict[str, Any]:
    user = (
        "GROUND TRUTH (verified facts with citations):\n\n"
        + _gt_text(ground_truth)
        + "\n\nTASK: Edit this into a SELF-CONTAINED lesson that explains everything slowly and "
        "properly for a first-time learner in class "
        f"{cfg.learner['class_level']}.\n"
        "Write as a patient tutor speaking directly to the student ('you'): clear, "
        "encouraging, step by step.\n"
        "Hard requirements:\n"
        "- TEACHING ORDER: start from an everyday observation the student recognises, then "
        "define, then formalise with symbols and equations.\n"
        "- INDEPENDENT OF OUTSIDE SOURCES: the reader has only this page. Remove every "
        "context-specific reference: 'previous chapter', 'the textbook', 'Figure 7.3', "
        "'as we saw', exercise numbers, page numbers. Do not refer to any external material.\n"
        "- Define every technical term the first time it appears.\n"
        "- One idea per paragraph; 3-5 sentences per paragraph; short sentences.\n"
        "- Do not add facts that are not in the ground truth; keep numbers and units exactly "
        "as they appear in it.\n"
        "Return a JSON object with exactly these keys:\n"
        '- "title": lesson title\n'
        '- "objectives": 2-4 sentences, each "After this lesson you can ..."\n'
        '- "sections": 3-6 of {"id": "sec-01", "title", "paragraphs": ["...", ...]} in teaching order\n'
        '- "glossary": [{"term", "definition"}] - at least 3, plain-English definitions\n'
    )
    return llm.call(
        "03-explain",
        [
            {
                "role": "system",
                "content": _system("03-explain", "Lesson Editor (Synthesizer agent)"),
            },
            {"role": "user", "content": user},
        ],
        LESSON,
        "lesson",
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


# -------------------------------------------------------------- 04-draft
def run_draft(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    lesson: dict[str, Any],
    ground_truth: dict[str, Any],
    source_pack: dict[str, Any],
) -> dict[str, Any]:
    claim_ids = ", ".join(c["id"] for c in ground_truth["claims"])
    user = (
        "LESSON (approved prose):\n\n"
        + _lesson_text(lesson)
        + "\n\nGROUND TRUTH (facts, equations, misconceptions):\n\n"
        + _gt_text(ground_truth)
        + f"\n\nTASK: Lay this out as an ordered block sequence for the study page. "
        f"Valid claim ids for citations: {claim_ids}.\n"
        "Block types and spec shapes:\n"
        '- text: {"paragraphs": ["..."]} - carry the lesson prose in reading order\n'
        '- worked_example: {"problem": "...", "steps": [{"title", "detail"}], "answer": "..."} '
        "- only if the ground truth has equations or a numeric relation; every number in the "
        "answer must appear VERBATIM in the ground truth or the source text - do not "
        "compute new figures\n"
        '- check: {"question", "format": "mcq"|"numeric", "options": ["A","B","C","D"], '
        '"answer_index": 0-3 (mcq), "answer": "text" (numeric), "explanation", '
        '"expected_understanding"} - include at least 3 checks spread through the page; '
        "answer_index must point at the correct option; one option may address a listed misconception\n"
        '- reveal: {"title", "steps": [{"title", "detail"}]} - a step-by-step derivation or method\n'
        '- diagram: {"svg": "<svg ...>...</svg> string using only viewBox, rect, circle, line, '
        'path, text, polygon with fill/stroke presentation attributes", "caption"} - label '
        "everything in ink; no <style>, no <script>, no external refs\n"
        '- simulation: {"title", "description", "learning_goal", "controls": [{"id", "label", '
        '"min", "max", "step", "initial"}], "default_behaviour": "what it shows before any input"} '
        "- only if the topic clearly benefits; 1-3 controls; a simulation with zero controls is "
        "an animation\n"
        "Order: text sections interleaved with checks and visuals the way a good teacher would "
        "pace the lesson. First block must be text; last block must be a check.\n"
        "Cite claims in every text, worked_example, check and reveal block (a factual block "
        "without citations is rejected): "
        '"citations": [{"claim_id": "claim-01"}].\n'
        'Return {"blocks": [...]}.\n\n'
        "Example of the required SHAPE (content from an unrelated chapter - never reuse "
        'it):\n{"blocks": [{"id": "b-01", "type": "text", "spec": {"paragraphs": ["..."]}, '
        '"citations": [{"claim_id": "claim-01"}]}, '
        '{"id": "b-02", "type": "check", "spec": {"question": "...", "format": "mcq", '
        '"options": ["2 m/s", "4 m/s", "6 m/s", "8 m/s"], "answer_index": 1, '
        '"explanation": "...", "expected_understanding": "..."}, '
        '"citations": [{"claim_id": "claim-02"}]}, '
        '{"id": "b-03", "type": "simulation", "spec": {"title": "...", "description": "...", '
        '"learning_goal": "...", "controls": [{"id": "speed", "label": "Speed (m/s)", '
        '"min": 0, "max": 20, "step": 1, "initial": 5}], "default_behaviour": "..."}, '
        '"citations": [{"claim_id": "claim-03"}]}]}'
    )

    def rule_feedback(parsed: dict[str, Any]) -> list[str]:
        """Code-side rule checks AT DRAFT TIME: the model sees its own fatal or
        major rule violations in the retry transcript and fixes them, instead
        of the run dying at 05-check."""
        report = checks.run_all_rules(
            parsed.get("blocks", []), lesson, ground_truth, source_pack
        )
        return [
            f"[{i['rule']}] block {i['block_id']}: {i['message']}"
            for i in report["rule_issues"]
            if i["severity"] in ("fatal", "major")
        ]

    return llm.call(
        "04-draft",
        [
            {
                "role": "system",
                "content": _system(
                    "04-draft", "Instructional Designer (Synthesizer agent)"
                ),
            },
            {"role": "user", "content": user},
        ],
        BLOCKS,
        "blocks",
        extra_validator=rule_feedback,
    )


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


# --------------------------------------------------------------- 05-check
def run_check(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    source_pack: dict[str, Any],
    ground_truth: dict[str, Any],
    blocks: dict[str, Any],
) -> dict[str, Any]:
    user = (
        "SOURCE MATERIAL (the only allowed facts):\n\n"
        + _pack_text(cfg, source_pack)
        + "\n\nGROUND TRUTH:\n\n"
        + _gt_text(ground_truth)
        + "\n\nDRAFT BLOCKS TO REVIEW:\n\n"
        + _blocks_text(blocks)
        + "\n\nTASK: You are the Comprehension & Fact Reviewer. Assume the draft contains at "
        "least one error: hunt for invented numbers, unit mismatches, and answers that do not "
        "match the question. Review every block:\n"
        "1. Is each factual statement correct per the source material? Quote the source in your issue.\n"
        "2. Is every check's correct answer actually correct?\n"
        "3. Is the language and depth right for a class "
        f"{cfg.learner['class_level']} first-time learner (not above, not below)?\n"
        "4. Does anything read as if it depends on material outside this page?\n"
        "5. For every check block: does the page teach the expected_understanding before "
        "asking for it? A check that asks something the page never taught is major.\n"
        "If you suspect a problem but cannot verify it against the source material, report "
        "it as minor with the message starting 'unverified:' - never as fatal or major.\n"
        'Return a JSON object: {"verdict": "pass"|"fail", "issues": '
        '[{"block_id": "b-01" or omit, "severity": "fatal"|"major"|"minor", '
        '"message": "..."}]}. Severity: fatal = a statement contradicts the sources or an '
        "answer key is wrong; major = a learner would be misled or confused; minor = style or "
        "wording. verdict=fail if any fatal issue. An empty issues array means pass.\n\n"
        'Example issue (SHAPE only - never reuse it): {"block_id": "b-05", "severity": "fatal", "message": '
        '"The block states the SI unit of speed is km/h; the source states the SI unit of '
        'speed is m/s [ncert page 12]."}'
    )
    return llm.call(
        "05-check",
        [
            {
                "role": "system",
                "content": _system("05-check", "Comprehension & Fact Reviewer agent"),
            },
            {"role": "user", "content": user},
        ],
        CHECK_REPORT,
        "check_report",
    )


def _blocks_text(blocks: dict[str, Any]) -> str:
    import json as _json

    return _json.dumps(blocks["blocks"], indent=1, ensure_ascii=False)
