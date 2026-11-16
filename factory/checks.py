"""Rule-based checks (stage 03-check, code side). Independent of the model reviewer.

These catch mechanically detectable failures: answer keys that do not match
their options, citations to claims that do not exist, phrases that break
self-containment, numbers that appear nowhere in the sources, and unsafe SVG.
They run regardless of what the model reviewer says; any fatal rule failure
fails the stage.
"""

from __future__ import annotations

import re
from typing import Any

from . import numeric
from .issue_categories import categorize

SELF_CONTAINMENT_PATTERNS = [
    (r"(?i)\bprevious chapter\b", "references a previous chapter"),
    (r"(?i)\bnext chapter\b", "references a next chapter"),
    (r"(?i)\bearlier chapter\b", "references an earlier chapter"),
    (r"(?i)\bthe textbook\b", "references 'the textbook'"),
    (r"(?i)\bthe ncert\b", "references 'the NCERT' (book), not this page"),
    (r"(?i)\byour teacher\b", "defers to an external person"),
    (r"(?i)\bexercise \d+", "references an external exercise number"),
    (
        r"(?i)\bas we (saw|learned|discussed)\b",
        "references prior context the reader may not have",
    ),
    (r"(?i)\bfig(ure)?\.?\s*\d+\.\d+", "references an external figure number"),
    (r"https?://", "contains a URL (pages must be self-contained)"),
]


def rule_answer_keys(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] != "check":
            continue
        spec = b["spec"]
        fmt = spec.get("format")
        if fmt == "mcq":
            options = spec.get("options")
            idx = spec.get("answer_index")
            if not isinstance(options, list) or len(options) < 2:
                issues.append(
                    _issue(b, "fatal", f"mcq has {options!r} options", "answer_key")
                )
                continue
            if not isinstance(idx, int) or not (0 <= idx < len(options)):
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f"answer_index {idx!r} out of range for {len(options)} options",
                        "answer_key",
                    )
                )
                continue
            answer = str(spec.get("answer", "")).strip()
            if answer and answer.strip() != str(options[idx]).strip():
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f"answer key mismatch: answer='{answer}' but options[{idx}]='{options[idx]}'",
                        "answer_key",
                    )
                )
        elif fmt == "numeric":
            answer = spec.get("answer")
            try:
                float(str(answer).strip())
            except (TypeError, ValueError):
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f"numeric answer {answer!r} is not a number - the answer "
                        'field must be the bare number only (e.g. "6"), with the '
                        "unit moved into the question",
                        "answer_key",
                    )
                )
        else:
            issues.append(
                _issue(b, "fatal", f"unknown check format {fmt!r}", "answer_key")
            )
    return issues


def rule_citations(
    blocks: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    source_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    """Citations must point at real claims and real sources, and every factual
    block (text / worked_example / check / reveal - the draft prompt's list)
    must carry at least one claim citation.

    Allowed source ids are DERIVED from the actual source pack (primary book +
    supplement chunk ids), not a hardcoded prefix list: a citation to a source
    that was never fetched is exactly the fabrication this rule must catch.
    """
    valid_claims = {c["id"] for c in ground_truth["claims"]}
    allowed_sources = {"ncert"}
    chapter = source_pack.get("chapter") or {}
    if chapter.get("book_id"):
        allowed_sources.add(chapter["book_id"])
    for s in source_pack.get("supplements", []):
        allowed_sources.add(s.get("source_id"))
        allowed_sources.add(s.get("book_id"))
    allowed_sources.discard(None)

    issues: list[dict[str, Any]] = []
    for b in blocks:
        citations = b.get("citations", [])
        if b["type"] in ("text", "worked_example", "check", "reveal") and not citations:
            issues.append(
                _issue(
                    b,
                    "fatal",
                    f"{b['type']} block carries no citations - every factual block "
                    "must cite at least one ground-truth claim",
                    "citations",
                )
            )
        for cit in citations:
            claim_id = cit.get("claim_id")
            if claim_id and claim_id not in valid_claims:
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f"cites unknown claim '{claim_id}'",
                        "citations",
                    )
                )
            source_id = cit.get("source_id")
            if source_id and source_id not in allowed_sources:
                # unknown provenance is suspicious but not necessarily wrong; major
                issues.append(
                    _issue(
                        b,
                        "major",
                        f"cites source_id '{source_id}' that is not in the source pack "
                        f"(allowed: {sorted(allowed_sources)})",
                        "citations",
                    )
                )
    return issues


def rule_self_containment(
    blocks: list[dict[str, Any]], lesson: dict[str, Any]
) -> list[dict[str, Any]]:
    texts = [p for s in lesson["sections"] for p in s["paragraphs"]]
    texts += [g["definition"] for g in lesson["glossary"]]
    for b in blocks:
        spec = b["spec"]
        for key in (
            "question",
            "explanation",
            "problem",
            "answer",
            "caption",
            "description",
            "title",
            "learning_goal",
            "default_behaviour",
        ):
            v = spec.get(key)
            if isinstance(v, str):
                texts.append(v)
        for k in ("paragraphs", "options"):
            texts += [x for x in spec.get(k, []) if isinstance(x, str)]
        for step in spec.get("steps", []):
            texts += [step.get("title", ""), step.get("detail", "")]
        for ctrl in spec.get("controls", []):
            texts.append(ctrl.get("label", ""))
    issues: list[dict[str, Any]] = []
    for text in texts:
        for pattern, why in SELF_CONTAINMENT_PATTERNS:
            m = re.search(pattern, text or "")
            if m:
                issues.append(
                    {
                        "block_id": None,
                        "severity": "major",
                        "rule": "self_containment",
                        "category": categorize("self_containment"),
                        "message": f"{why}: ...{m.group(0)}... in: {text[:120]!r}",
                    }
                )
    return issues


def _number_in_corpus(num: str, corpus: str) -> bool:
    """Boundary-aware numeral match.

    Plain substring matching is wrong: '5' would 'appear' in '15' or '1.5'.
    A match requires the numeral not to be glued to another digit on either
    side, and not to be the tail of a decimal on its left. '5' matches '5',
    '5.0' and '(5 m/s)' but never '15', '50' or '1.5'.
    """
    variants = {num, num.lstrip("0") or "0"}
    for variant in variants:
        if re.search(rf"(?<![\d.]){re.escape(variant)}(?!\d)", corpus):
            return True
    return False


def rule_numbers(
    blocks: list[dict[str, Any]],
    ground_truth: dict[str, Any],
    source_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    """Problem data is the harness guarantee; computed answers are the reviewer's.

    Every number in a worked_example PROBLEM or a check QUESTION must be traceable
    to the ground truth or the primary source text (string match on the numeral,
    ignoring formatting). This catches invented problem data - the page must teach
    and test the chapter's own problems, not invented lookalikes.

    Numbers in ANSWERS and options are deliberately NOT code-checked: textbook
    exercises are meant to be computed, and derivability cannot be verified by
    string match. The 03-check reviewer recomputes every worked_example and
    numeric check instead (a wrong computed answer is fatal there), and its
    verdict routes to the 04-repair catcher.
    """
    corpus = " ".join(
        [c["statement"] for c in ground_truth["claims"]]
        + [e["expression"] for e in ground_truth["equations"]]
        + [source_pack["ncert_text"]]
    )
    issues: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] not in ("worked_example", "check"):
            continue
        spec = b["spec"]
        problem = (
            spec.get("problem")
            if b["type"] == "worked_example"
            else spec.get("question")
        )
        for num in re.findall(r"\d+(?:\.\d+)?", str(problem or "")):
            if not _number_in_corpus(num, corpus):
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f"number {num} appears in the problem statement but nowhere in "
                        "the ground truth or the primary source - problem data must "
                        "come from the sources",
                        "numbers",
                    )
                )
    return issues


def rule_diagram_svg(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] != "diagram":
            continue
        svg = str(b["spec"].get("svg", ""))
        if not svg.strip().startswith("<svg"):
            issues.append(
                _issue(
                    b,
                    "fatal",
                    "diagram svg does not start with <svg>",
                    "diagram_svg",
                )
            )
        # xmlns declarations are namespace names, not fetched URLs - strip before scanning
        svg_no_ns = re.sub(r'\sxmlns(?::\w+)?\s*=\s*"[^"]*"', "", svg)
        for bad, why in [
            (r"<\s*script", "svg contains a <script> tag"),
            (r"<\s*style", "svg contains a <style> tag (use presentation attributes)"),
            (r"https?://", "svg references an external URL"),
            (r"<\s*(image|foreignObject|use)\b", "svg embeds external content"),
            (r"\son\w+\s*=", "svg has an inline event handler"),
        ]:
            if re.search(bad, svg_no_ns, re.IGNORECASE):
                issues.append(_issue(b, "fatal", why, "diagram_svg"))
    return issues


def rule_shapes(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Shape invariants the run's other rule checks silently depend on
    (founding rule: guarantees live in the harness, not in prompt prose). A
    nemotron-class model emitted `worked_example.steps` as one dict - Python's
    dict iteration then handed bare strings to every `step.get(...)` and the
    run died with an AttributeError instead of telling the model what was
    wrong. Shapes are therefore checked FIRST: run_all_rules short-circuits
    on them so the retry transcript lands the fix instruction."""
    issues: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] in ("worked_example", "reveal"):
            steps = b["spec"].get("steps")
            if not isinstance(steps, list) or not all(
                isinstance(s, dict) for s in steps
            ):
                issues.append(
                    _issue(
                        b,
                        "fatal",
                        f'{b["type"]} "steps" must be a list of '
                        '{"title","detail"} objects (a dict or string is not a '
                        "step sequence)",
                        "shape",
                    )
                )
    return issues


def rule_numeric_recompute(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Recompute worked-example and numeric-check answers (P4, 2026-11-15).

    The 03-check model reviewer already recomputes these; this rule is the
    harness guarantee behind that rubric. Only provable arithmetic is fatal or
    blocking; everything ambiguous (`sqrt`, scientific notation, symbolic
    algebra) is reported as `unverified:` minor and never blocks a page.
    """
    return list(numeric.recompute_blocks(blocks)["issues"])


def rule_glossary_coverage(
    lesson: dict[str, Any],
    blocks: list[dict[str, Any]],
    glossary_data: dict[str, Any],
    promised_locales: list[str],
) -> list[dict[str, Any]]:
    """Every glossary term the page actually uses must be translated in every
    locale the page promises (P4 gate; P2 owns authoring the entries).

    A term is "tagged" when its English form appears in the lesson or block
    text (same stem match the translator uses to build `glossary_subset`).
    A promised locale with no `native_term` for a tagged term is a publish
    failure: the page would silently fall back to English mid-sentence.
    """
    if not promised_locales:
        return []
    blob = _all_text(lesson, blocks).lower()
    issues: list[dict[str, Any]] = []
    for entry in glossary_data.get("terms", []):
        english = str(entry.get("english_term") or "").strip()
        if not english:
            continue
        stem = english.lower()[: max(4, len(english) - 2)]
        if stem not in blob and english.lower() not in blob:
            continue
        locales = entry.get("locales") or {}
        for locale in promised_locales:
            loc_map = locales.get(locale) or {}
            native = str(loc_map.get("native_term") or "").strip()
            gloss = str(loc_map.get("first_mention_gloss") or "").strip()
            if native and gloss:
                continue
            issues.append(
                _issue(
                    {"id": None},
                    "fatal",
                    f"glossary term '{english}' is used on the page but has no "
                    f"complete '{locale}' entry (native_term + first_mention_gloss) "
                    "in sources/glossary/physics_glossary.json",
                    "glossary_coverage",
                )
            )
    return issues


def _all_text(lesson: dict[str, Any], blocks: list[dict[str, Any]]) -> str:
    """Every learner-visible string the lesson and blocks carry."""
    texts: list[str] = [str(lesson.get("title") or "")]
    texts += [str(o) for o in lesson.get("objectives", [])]
    for section in lesson.get("sections", []):
        texts.append(str(section.get("title") or ""))
        texts += [str(p) for p in section.get("paragraphs", [])]
    texts += [
        f"{g.get('term', '')} {g.get('definition', '')}"
        for g in lesson.get("glossary", [])
    ]
    for b in blocks:
        spec = b.get("spec") or {}
        for value in spec.values():
            if isinstance(value, str):
                texts.append(value)
            elif isinstance(value, list):
                texts += [str(x) for x in value if isinstance(x, str)]
    return "\n".join(texts)


def run_all_rules(
    blocks: list[dict[str, Any]],
    lesson: dict[str, Any],
    ground_truth: dict[str, Any],
    source_pack: dict[str, Any],
) -> dict[str, Any]:
    shape_issues = rule_shapes(blocks)
    if any(i["severity"] == "fatal" for i in shape_issues):
        # Short-circuit: the later rules iterate steps the same way this run
        # died doing - the shape verdict IS the report for this round.
        return {
            "rule_issues": shape_issues,
            "fatal_count": len(shape_issues),
            "verdict": "fail",
        }
    numeric_report = numeric.recompute_blocks(blocks)
    issues = (
        shape_issues
        + rule_answer_keys(blocks)
        + rule_citations(blocks, ground_truth, source_pack)
        + rule_self_containment(blocks, lesson)
        + rule_numbers(blocks, ground_truth, source_pack)
        + rule_diagram_svg(blocks)
        + list(numeric_report["issues"])
    )
    fatal = [i for i in issues if i["severity"] == "fatal"]
    return {
        "rule_issues": issues,
        "fatal_count": len(fatal),
        "verdict": "fail" if fatal else "pass",
        # Coverage summary: how much of the numeric content the deterministic
        # rule could actually verify (checked/verified/unverifiable counts).
        "numeric_recompute": {
            "blocks": numeric_report["blocks"],
            "checked": numeric_report["checked"],
            "verified": numeric_report["verified"],
            "unverifiable": numeric_report["unverifiable"],
        },
    }


def _issue(
    block: dict[str, Any], severity: str, message: str, rule: str
) -> dict[str, Any]:
    return {
        "block_id": block.get("id"),
        "severity": severity,
        "rule": rule,
        "category": categorize(rule),
        "message": message,
    }
