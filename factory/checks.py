"""Rule-based checks (stage 05, code side). Independent of the model reviewer.

These catch mechanically detectable failures: answer keys that do not match
their options, citations to claims that do not exist, phrases that break
self-containment, numbers that appear nowhere in the sources, and unsafe SVG.
They run regardless of what the model reviewer says; any fatal rule failure
fails the stage.
"""

from __future__ import annotations

import re
from typing import Any

SELF_CONTAINMENT_PATTERNS = [
    (r"(?i)\bprevious chapter\b", "references a previous chapter"),
    (r"(?i)\bnext chapter\b", "references a next chapter"),
    (r"(?i)\bearlier chapter\b", "references an earlier chapter"),
    (r"(?i)\bthe textbook\b", "references 'the textbook'"),
    (r"(?i)\bthe ncert\b", "references 'the NCERT' (book), not this page"),
    (r"(?i)\byour teacher\b", "defers to an external person"),
    (r"(?i)\bexercise \d+", "references an external exercise number"),
    (r"(?i)\bas we (saw|learned|discussed)\b", "references prior context the reader may not have"),
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
                issues.append(_issue(b, "fatal", f"mcq has {options!r} options"))
                continue
            if not isinstance(idx, int) or not (0 <= idx < len(options)):
                issues.append(_issue(b, "fatal", f"answer_index {idx!r} out of range for {len(options)} options"))
                continue
            answer = str(spec.get("answer", "")).strip()
            if answer and answer.strip() != str(options[idx]).strip():
                issues.append(_issue(
                    b, "fatal",
                    f"answer key mismatch: answer='{answer}' but options[{idx}]='{options[idx]}'",
                ))
        elif fmt == "numeric":
            answer = spec.get("answer")
            try:
                float(str(answer).strip())
            except (TypeError, ValueError):
                issues.append(_issue(b, "fatal", f"numeric answer {answer!r} is not a number"))
        else:
            issues.append(_issue(b, "fatal", f"unknown check format {fmt!r}"))
    return issues


def rule_citations(blocks: list[dict[str, Any]], ground_truth: dict[str, Any]) -> list[dict[str, Any]]:
    valid_claims = {c["id"] for c in ground_truth["claims"]}
    valid_terms = {t["term"] for t in ground_truth["key_terms"]}
    issues: list[dict[str, Any]] = []
    for b in blocks:
        for cit in b.get("citations", []):
            claim_id = cit.get("claim_id")
            if claim_id and claim_id not in valid_claims:
                issues.append(_issue(b, "fatal", f"cites unknown claim '{claim_id}'"))
            source_id = cit.get("source_id")
            if source_id and source_id != "ncert" and not source_id.startswith(("ncert", "openstax", "siyavula")):
                # unknown provenance is suspicious but not necessarily wrong; major
                issues.append(_issue(b, "major", f"cites source_id '{source_id}' that is not in the source pack naming scheme"))
            _ = valid_terms  # term-level citations allowed but not required
    return issues


def rule_self_containment(blocks: list[dict[str, Any]], lesson: dict[str, Any]) -> list[dict[str, Any]]:
    texts = [p for s in lesson["sections"] for p in s["paragraphs"]]
    texts += [g["definition"] for g in lesson["glossary"]]
    for b in blocks:
        spec = b["spec"]
        for key in ("question", "explanation", "problem", "answer", "caption", "description", "title", "learning_goal", "default_behaviour"):
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
                issues.append({
                    "block_id": None, "severity": "major", "rule": "self_containment",
                    "message": f"{why}: ...{m.group(0)}... in: {text[:120]!r}",
                })
    return issues


def rule_numbers(blocks: list[dict[str, Any]], ground_truth: dict[str, Any], source_pack: dict[str, Any]) -> list[dict[str, Any]]:
    """Every number used in a worked_example answer or a check answer must be
    traceable to the ground truth or the primary source text (string match on
    the numeral, ignoring formatting). Guards against invented answers."""
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
        candidates = []
        if b["type"] == "worked_example":
            candidates.append(str(spec.get("answer", "")))
        else:
            candidates.append(str(spec.get("answer", "")))
        for text in candidates:
            for num in re.findall(r"\d+(?:\.\d+)?", text or ""):
                bare = num.lstrip("0") or "0"
                if bare not in corpus and num not in corpus:
                    issues.append(_issue(
                        b, "fatal",
                        f"number {num} appears in the answer but nowhere in the ground truth "
                        "or the primary source - possible invented figure",
                    ))
    return issues


def rule_diagram_svg(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for b in blocks:
        if b["type"] != "diagram":
            continue
        svg = str(b["spec"].get("svg", ""))
        if not svg.strip().startswith("<svg"):
            issues.append(_issue(b, "fatal", "diagram svg does not start with <svg>"))
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
                issues.append(_issue(b, "fatal", why))
    return issues


def run_all_rules(blocks: list[dict[str, Any]], lesson: dict[str, Any],
                  ground_truth: dict[str, Any], source_pack: dict[str, Any]) -> dict[str, Any]:
    issues = (
        rule_answer_keys(blocks)
        + rule_citations(blocks, ground_truth)
        + rule_self_containment(blocks, lesson)
        + rule_numbers(blocks, ground_truth, source_pack)
        + rule_diagram_svg(blocks)
    )
    fatal = [i for i in issues if i["severity"] == "fatal"]
    return {
        "rule_issues": issues,
        "fatal_count": len(fatal),
        "verdict": "fail" if fatal else "pass",
    }


def _issue(block: dict[str, Any], severity: str, message: str) -> dict[str, Any]:
    return {"block_id": block.get("id"), "severity": severity, "rule": "auto", "message": message}
