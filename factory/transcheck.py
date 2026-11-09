"""Stage 10b-transcheck: deterministic translation rules + calibrated LLM reviewer.

Combines 9 deterministic code checks (`R1`..`R9`) with 1 bounded Evon v3.3
Translation Reviewer call per locale via `llm_manager`. Any `fatal` or `major`
issue marks the locale `"fail"` and routes ONLY the flagged `(locale, block_id)`
units to `10c-transrepair` (`ADR-0021`, `ADR-0022`, `reviewer-rubric.md`).
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from collections import Counter
from typing import Any

import jsonschema

from . import checks, tm_store, translate
from .artifacts import RunContext
from .config import Config
from .ledger import issue_entry
from .llm import LLMClient
from .schemas import (
    BLOCKS,
    LESSON,
    TRANSLATION_REVIEW_CALL_REPORT,
)

STAGE_ID = "10b-transcheck"

_REGIONAL_DIGIT_RE = re.compile(
    r"[\u0966-\u096F\u0BE6-\u0BEF\u0C66-\u0C6F\u09E6-\u09EF"
    r"\u0AE6-\u0AEF\u0CE6-\u0CEF\u0D66-\u0D6F\u0A66-\u0A6F]"
)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_NUMERAL_RE = re.compile(r"\d+(?:\.\d+)?")
_TEMPLATE_VAR_RE = re.compile(r"\{[a-zA-Z0-9_]+\}")

_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTODO\b"), "TODO marker"),
    (re.compile(r"\bTBD\b"), "TBD marker"),
    (re.compile(r"\[\s*translate\s*\]", re.IGNORECASE), "[translate] placeholder"),
    (re.compile(r"<\s*translate\s*>", re.IGNORECASE), "<translate> placeholder"),
    (re.compile(r"\{\{|\}\}"), "mustache template braces {{ or }}"),
    (re.compile(r"(?<![A-Za-z0-9_])undefined(?![A-Za-z0-9_])"), "'undefined' leak"),
]

# Multi-character SI unit expressions checked by literal/token presence, and
# single-letter SI units checked when attached to numbers or parentheses.
_COMPOUND_SI_UNITS = ("m/s²", "m/s2", "m/s", "km/h", "kg", "Pa", "Hz", "Ω")
_SINGLE_LETTER_SI_RE = re.compile(
    r"(?:\b\d+(?:\.\d+)?\s*(N|J|W)\b|\(\s*(N|J|W)\s*\))"
)

_SVG_GEOMETRY_ATTRS = (
    "viewBox",
    "d",
    "x",
    "y",
    "x1",
    "y1",
    "x2",
    "y2",
    "cx",
    "cy",
    "r",
    "width",
    "height",
    "points",
    "transform",
    "stroke",
    "fill",
)


def _issue(
    block_id: str,
    severity: str,
    category: str,
    rule_id: str,
    message: str,
) -> dict[str, Any]:
    return {
        "block_id": block_id,
        "severity": severity,
        "category": category,
        "rule": rule_id,
        "message": message,
    }


def _block_strings(block: dict[str, Any]) -> list[str]:
    spec = block.get("spec", {})
    btype = block.get("type")
    if btype == "text":
        return [str(p) for p in spec.get("paragraphs", [])]
    if btype == "worked_example":
        out = [str(spec.get("problem", "")), str(spec.get("answer", ""))]
        for s in spec.get("steps", []):
            out.append(str(s.get("title", "")))
            out.append(str(s.get("detail", "")))
        return out
    if btype == "check":
        out = [
            str(spec.get("question", "")),
            str(spec.get("explanation", "")),
            str(spec.get("expected_understanding", "")),
        ]
        for o in spec.get("options", []):
            out.append(str(o))
        return out
    if btype == "reveal":
        out = [str(spec.get("title", ""))]
        for s in spec.get("steps", []):
            out.append(str(s.get("title", "")))
            out.append(str(s.get("detail", "")))
        return out
    if btype == "diagram":
        out = [str(spec.get("caption", ""))]
        try:
            payload = translate.extract_diagram_payload(block)
            if payload.get("svg_aria_label"):
                out.append(str(payload["svg_aria_label"]))
            for item in payload.get("svg_texts", []):
                out.append(str(item.get("source", "")))
        except Exception:  # noqa: BLE001 — SVG validity is checked by R8
            pass
        return out
    if btype == "simulation":
        out = [
            str(spec.get("title", "")),
            str(spec.get("description", "")),
            str(spec.get("learning_goal", "")),
            str(spec.get("default_behaviour", "")),
        ]
        for c in spec.get("controls", []):
            out.append(str(c.get("label", "")))
        return out
    return []


def _meta_strings(meta: dict[str, Any]) -> list[str]:
    out = [str(meta.get("title", ""))]
    out.extend(str(o) for o in meta.get("objectives", []))
    for sec in meta.get("sections", []):
        out.append(str(sec.get("title", "")))
        out.extend(str(p) for p in sec.get("paragraphs", []))
    for g in meta.get("glossary", []):
        out.append(str(g.get("term", "")))
        out.append(str(g.get("definition", "")))
    return out


# --------------------------------------------------- Layer 1: Rules R1..R9
def rule_trans_schema(
    en_lesson: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R1: Reassembled blocks validate against BLOCKS and meta validates against
    LESSON; block count, id sequence, and type sequence match English 1:1."""
    issues: list[dict[str, Any]] = []
    localized_lesson_schema = {
        **LESSON,
        "properties": {
            **LESSON["properties"],
            "objectives": {
                "type": "array",
                "minItems": 2,
                "items": {"type": "string", "minLength": 10},
            },
            "sections": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "required": ["id", "title", "paragraphs"],
                    "additionalProperties": False,
                    "properties": {
                        "id": {"type": "string", "pattern": "^sec-[0-9]{2}$"},
                        "title": {"type": "string", "minLength": 2},
                        "paragraphs": {
                            "type": "array",
                            "minItems": 1,
                            "items": {"type": "string", "minLength": 20},
                        },
                    },
                },
            },
            "glossary": {
                "type": "array",
                "minItems": 2,
                "items": {
                    "type": "object",
                    "required": ["term", "definition"],
                    "additionalProperties": False,
                    "properties": {
                        "term": {"type": "string", "minLength": 2},
                        "definition": {"type": "string", "minLength": 8},
                    },
                },
            },
        },
    }
    try:
        jsonschema.Draft7Validator(localized_lesson_schema).validate(tr_meta)
    except jsonschema.ValidationError as exc:
        issues.append(
            _issue(
                "b-00-meta",
                "fatal",
                "schema_integrity",
                "R1",
                f"b-00-meta failed LESSON schema validation: {exc.message[:180]}",
            )
        )

    if [s.get("id") for s in tr_meta.get("sections", [])] != [
        s.get("id") for s in en_lesson.get("sections", [])
    ]:
        issues.append(
            _issue(
                "b-00-meta",
                "fatal",
                "schema_integrity",
                "R1",
                "b-00-meta section id sequence does not match English lesson sections",
            )
        )

    try:
        jsonschema.Draft7Validator(BLOCKS).validate({"blocks": tr_blocks})
    except jsonschema.ValidationError as exc:
        issues.append(
            _issue(
                "b-01",
                "fatal",
                "schema_integrity",
                "R1",
                f"translated blocks failed BLOCKS schema validation: {exc.message[:180]}",
            )
        )

    if len(tr_blocks) != len(en_blocks):
        issues.append(
            _issue(
                "b-01",
                "fatal",
                "schema_integrity",
                "R1",
                f"block count mismatch: expected {len(en_blocks)}, got {len(tr_blocks)}",
            )
        )
        return issues

    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=True):
        bid = str(en_b.get("id", "b-01"))
        if tr_b.get("id") != en_b.get("id") or tr_b.get("type") != en_b.get("type"):
            issues.append(
                _issue(
                    bid,
                    "fatal",
                    "schema_integrity",
                    "R1",
                    f"block {bid} id/type mismatch: expected ({en_b.get('id')}, "
                    f"{en_b.get('type')}), got ({tr_b.get('id')}, {tr_b.get('type')})",
                )
            )
    return issues


def rule_trans_citations(
    en_blocks: list[dict[str, Any]],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R2: Every translated block preserves exact citations equality with English."""
    issues: list[dict[str, Any]] = []
    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        bid = str(en_b.get("id", "b-01"))
        if tr_b.get("citations") != en_b.get("citations"):
            issues.append(
                _issue(
                    bid,
                    "fatal",
                    "citation_loss",
                    "R2",
                    f"block {bid} citations altered or lost: expected "
                    f"{en_b.get('citations')}, got {tr_b.get('citations')}",
                )
            )
    return issues


def rule_trans_numbers(
    en_lesson: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R3: Zero regional Unicode digits anywhere, and 100% multiset preservation
    of Western Arabic numerals in worked_example problem/answer and check
    question/correct-option."""
    del en_lesson
    issues: list[dict[str, Any]] = []
    for text in _meta_strings(tr_meta):
        m = _REGIONAL_DIGIT_RE.search(text)
        if m:
            issues.append(
                _issue(
                    "b-00-meta",
                    "fatal",
                    "number_mismatch",
                    "R3",
                    f"b-00-meta contains forbidden regional digit {m.group(0)!r}",
                )
            )
            break

    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        bid = str(en_b.get("id", "b-01"))
        for text in _block_strings(tr_b):
            m = _REGIONAL_DIGIT_RE.search(text)
            if m:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "number_mismatch",
                        "R3",
                        f"block {bid} contains forbidden regional digit {m.group(0)!r}",
                    )
                )
                break

        btype = en_b.get("type")
        en_spec = en_b.get("spec", {})
        tr_spec = tr_b.get("spec", {})
        if btype == "worked_example":
            for field in ("problem", "answer"):
                en_nums = Counter(_NUMERAL_RE.findall(str(en_spec.get(field, ""))))
                tr_nums = Counter(_NUMERAL_RE.findall(str(tr_spec.get(field, ""))))
                if en_nums != tr_nums:
                    issues.append(
                        _issue(
                            bid,
                            "fatal",
                            "number_mismatch",
                            "R3",
                            f"block {bid} worked_example.{field} numerals mismatch: "
                            f"expected {dict(en_nums)}, got {dict(tr_nums)}",
                        )
                    )
        elif btype == "check":
            en_q = Counter(_NUMERAL_RE.findall(str(en_spec.get("question", ""))))
            tr_q = Counter(_NUMERAL_RE.findall(str(tr_spec.get("question", ""))))
            if en_q != tr_q:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "number_mismatch",
                        "R3",
                        f"block {bid} check.question numerals mismatch: "
                        f"expected {dict(en_q)}, got {dict(tr_q)}",
                    )
                )
            if en_spec.get("format") == "mcq":
                idx = en_spec.get("answer_index")
                en_opts = en_spec.get("options", [])
                tr_opts = tr_spec.get("options", [])
                if (
                    isinstance(idx, int)
                    and 0 <= idx < len(en_opts)
                    and idx < len(tr_opts)
                ):
                    en_onums = Counter(_NUMERAL_RE.findall(str(en_opts[idx])))
                    tr_onums = Counter(_NUMERAL_RE.findall(str(tr_opts[idx])))
                    if en_onums != tr_onums:
                        issues.append(
                            _issue(
                                bid,
                                "fatal",
                                "number_mismatch",
                                "R3",
                                f"block {bid} check.options[{idx}] numerals mismatch: "
                                f"expected {dict(en_onums)}, got {dict(tr_onums)}",
                            )
                        )
    return issues


def rule_trans_units_and_symbols(
    ground_truth: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R4: Every ground-truth equation and every SI unit token appearing in an
    English block is preserved in the translated block."""
    issues: list[dict[str, Any]] = []
    equations = [
        str(eq.get("expression", "")).strip()
        for eq in ground_truth.get("equations", [])
        if str(eq.get("expression", "")).strip()
    ]
    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        bid = str(en_b.get("id", "b-01"))
        en_text = " ".join(_block_strings(en_b))
        tr_text = " ".join(_block_strings(tr_b))

        for expr in equations:
            if expr in en_text and expr not in tr_text:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "unit_or_symbol",
                        "R4",
                        f"block {bid} dropped ground-truth equation {expr!r}",
                    )
                )

        for unit in _COMPOUND_SI_UNITS:
            pat = rf"(?<![A-Za-z]){re.escape(unit)}(?![A-Za-z])"
            if re.search(pat, en_text) and not re.search(pat, tr_text):
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "unit_or_symbol",
                        "R4",
                        f"block {bid} dropped SI unit {unit!r} present in source block",
                    )
                )

        for m in _SINGLE_LETTER_SI_RE.finditer(en_text):
            u_tok = m.group(1) or m.group(2)
            if u_tok and not re.search(rf"(?<![A-Za-z]){re.escape(u_tok)}(?![A-Za-z])", tr_text):
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "unit_or_symbol",
                        "R4",
                        f"block {bid} dropped SI unit {u_tok!r} present in source block",
                    )
                )
    return issues


def rule_trans_mcq_integrity(
    en_blocks: list[dict[str, Any]],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R5: For check blocks, format and answer_index match English; MCQ options
    match length and are distinct, and answer == options[answer_index]; numeric
    answer matches English verbatim."""
    issues: list[dict[str, Any]] = []
    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        if en_b.get("type") != "check":
            continue
        bid = str(en_b.get("id", "b-01"))
        en_spec = en_b.get("spec", {})
        tr_spec = tr_b.get("spec", {})
        fmt = en_spec.get("format")
        if tr_spec.get("format") != fmt:
            issues.append(
                _issue(
                    bid,
                    "fatal",
                    "answer_key",
                    "R5",
                    f"block {bid} check format changed from {fmt!r} to {tr_spec.get('format')!r}",
                )
            )
            continue
        if fmt == "mcq":
            en_idx = en_spec.get("answer_index")
            tr_idx = tr_spec.get("answer_index")
            en_opts = en_spec.get("options", [])
            tr_opts = tr_spec.get("options", [])
            if tr_idx != en_idx:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "answer_key",
                        "R5",
                        f"block {bid} answer_index changed from {en_idx!r} to {tr_idx!r}",
                    )
                )
            if not isinstance(tr_opts, list) or len(tr_opts) != len(en_opts):
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "answer_key",
                        "R5",
                        f"block {bid} MCQ option count mismatch: expected {len(en_opts)}, "
                        f"got {len(tr_opts) if isinstance(tr_opts, list) else tr_opts!r}",
                    )
                )
                continue
            stripped = [str(o).strip() for o in tr_opts]
            if any(not s for s in stripped) or len(set(stripped)) != len(stripped):
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "answer_key",
                        "R5",
                        f"block {bid} MCQ options must be non-empty and distinct: {tr_opts!r}",
                    )
                )
            if isinstance(tr_idx, int) and 0 <= tr_idx < len(tr_opts):
                if str(tr_spec.get("answer", "")).strip() != str(tr_opts[tr_idx]).strip():
                    issues.append(
                        _issue(
                            bid,
                            "fatal",
                            "answer_key",
                            "R5",
                            f"block {bid} MCQ answer {tr_spec.get('answer')!r} != "
                            f"options[{tr_idx}] {tr_opts[tr_idx]!r}",
                        )
                    )
        elif fmt == "numeric":
            if str(tr_spec.get("answer", "")).strip() != str(
                en_spec.get("answer", "")
            ).strip():
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "answer_key",
                        "R5",
                        f"block {bid} numeric answer changed from "
                        f"{en_spec.get('answer')!r} to {tr_spec.get('answer')!r}",
                    )
                )
    return issues


def _native_script_ratio(text: str, code_range: tuple[int, int]) -> tuple[int, int]:
    """Return (native_script_chars, total_alphabetic_chars) after stripping
    parenthetical English glosses `(velocity)` and math/SI expressions."""
    # Strip parenthetical ASCII glosses like '(velocity)' or '(distance-time graph)'
    cleaned = re.sub(r"\([A-Za-z0-9\s\-_.,/+=²³^]+\)", " ", text)
    # Strip common SI units and single-letter variables
    for unit in _COMPOUND_SI_UNITS:
        cleaned = cleaned.replace(unit, " ")
    lo, hi = code_range
    native_count = 0
    total_alpha = 0
    for ch in cleaned:
        cp = ord(ch)
        if lo <= cp <= hi:
            native_count += 1
            total_alpha += 1
        elif ch.isalpha():
            total_alpha += 1
    return native_count, total_alpha


def rule_trans_script_purity(
    locale: str,
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R6: For hi-Latn, zero Devanagari characters. For Indic native-script
    locales, native script characters must account for >= 40% of alphabetic
    characters in prose blocks."""
    issues: list[dict[str, Any]] = []
    if locale == "hi-Latn":
        for text in _meta_strings(tr_meta):
            m = _DEVANAGARI_RE.search(text)
            if m:
                issues.append(
                    _issue(
                        "b-00-meta",
                        "fatal",
                        "script_violation",
                        "R6",
                        f"b-00-meta in hi-Latn contains Devanagari char {m.group(0)!r}",
                    )
                )
                break
        for tr_b in tr_blocks:
            bid = str(tr_b.get("id", "b-01"))
            for text in _block_strings(tr_b):
                m = _DEVANAGARI_RE.search(text)
                if m:
                    issues.append(
                        _issue(
                            bid,
                            "fatal",
                            "script_violation",
                            "R6",
                            f"block {bid} in hi-Latn contains Devanagari char {m.group(0)!r}",
                        )
                    )
                    break
        return issues

    loc_meta = translate.LOCALE_METADATA.get(locale)
    if not loc_meta or loc_meta["script"] == "Latn":
        return issues

    script_range: tuple[int, int] = loc_meta["script_range"]
    for tr_b in tr_blocks:
        btype = tr_b.get("type")
        if btype not in ("text", "worked_example", "reveal", "check"):
            continue
        bid = str(tr_b.get("id", "b-01"))
        spec = tr_b.get("spec", {})
        if btype == "check":
            prose = str(spec.get("explanation", ""))
        else:
            prose = " ".join(_block_strings(tr_b))
        native_c, total_c = _native_script_ratio(prose, script_range)
        if total_c >= 10:
            ratio = native_c / total_c
            if ratio < 0.40:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "script_violation",
                        "R6",
                        f"block {bid} in locale {locale!r} has only {ratio:.0%} native "
                        f"script characters ({native_c}/{total_c}, minimum required 40%)",
                    )
                )
    return issues


def rule_trans_placeholders(
    en_lesson: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
    en_sim_strings: dict[str, dict[str, str]] | None = None,
    tr_sim_strings: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """R7: Zero untranslated placeholder/truncation artifacts and exact template
    placeholder preservation in sim_strings."""
    issues: list[dict[str, Any]] = []
    en_meta_joined = " ".join(_meta_strings(en_lesson))
    for text in _meta_strings(tr_meta):
        for pat, desc in _PLACEHOLDER_PATTERNS:
            if pat.search(text) and not pat.search(en_meta_joined):
                issues.append(
                    _issue(
                        "b-00-meta",
                        "fatal",
                        "placeholder_leak",
                        "R7",
                        f"b-00-meta contains {desc}: {text[:80]!r}",
                    )
                )
                break

    if en_sim_strings and tr_sim_strings is not None:
        for bid, key_map in en_sim_strings.items():
            tr_map = tr_sim_strings.get(bid, {})
            for k, src_val in key_map.items():
                if k not in tr_map:
                    issues.append(
                        _issue(
                            "b-00-meta",
                            "fatal",
                            "placeholder_leak",
                            "R7",
                            f"b-00-meta missing sim_strings.{bid}.{k}",
                        )
                    )
                    continue
                src_vars = set(_TEMPLATE_VAR_RE.findall(str(src_val)))
                tr_vars = set(_TEMPLATE_VAR_RE.findall(str(tr_map[k])))
                if src_vars != tr_vars:
                    issues.append(
                        _issue(
                            "b-00-meta",
                            "fatal",
                            "placeholder_leak",
                            "R7",
                            f"b-00-meta sim_strings.{bid}.{k} placeholder mismatch: "
                            f"expected {sorted(src_vars)}, got {sorted(tr_vars)}",
                        )
                    )

    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        bid = str(en_b.get("id", "b-01"))
        en_strs = _block_strings(en_b)
        en_joined = " ".join(en_strs)
        en_has_ellipsis = any(s.rstrip().endswith("...") for s in en_strs)
        for text in _block_strings(tr_b):
            for pat, desc in _PLACEHOLDER_PATTERNS:
                if pat.search(text) and not pat.search(en_joined):
                    issues.append(
                        _issue(
                            bid,
                            "fatal",
                            "placeholder_leak",
                            "R7",
                            f"block {bid} contains {desc}: {text[:80]!r}",
                        )
                    )
                    break
            if text.rstrip().endswith("...") and not en_has_ellipsis:
                issues.append(
                    _issue(
                        bid,
                        "fatal",
                        "placeholder_leak",
                        "R7",
                        f"block {bid} ends with truncation '...' not present in source",
                    )
                )
                break
    return issues


def _svg_geometry_signature(svg_str: str) -> list[tuple[str, dict[str, str]]]:
    root = ET.fromstring(svg_str)
    sig: list[tuple[str, dict[str, str]]] = []
    for elem in root.iter():
        tag = elem.tag.split("}", 1)[1] if "}" in elem.tag else elem.tag
        geom = {
            attr: elem.attrib[attr]
            for attr in _SVG_GEOMETRY_ATTRS
            if attr in elem.attrib
        }
        sig.append((tag, geom))
    return sig


def rule_trans_svg_safety(
    en_blocks: list[dict[str, Any]],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R8: Runs rule_diagram_svg and verifies that XML element tag sequence and
    all geometry attributes match the English SVG identically."""
    issues: list[dict[str, Any]] = []
    for raw_issue in checks.rule_diagram_svg(tr_blocks):
        issues.append(
            _issue(
                str(raw_issue.get("block_id") or "b-01"),
                "fatal",
                "svg_integrity",
                "R8",
                str(raw_issue["message"]),
            )
        )

    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        if en_b.get("type") != "diagram":
            continue
        bid = str(en_b.get("id", "b-01"))
        en_svg = str(en_b.get("spec", {}).get("svg", ""))
        tr_svg = str(tr_b.get("spec", {}).get("svg", ""))
        try:
            en_sig = _svg_geometry_signature(en_svg)
            tr_sig = _svg_geometry_signature(tr_svg)
        except ET.ParseError as exc:
            issues.append(
                _issue(
                    bid,
                    "fatal",
                    "svg_integrity",
                    "R8",
                    f"block {bid} has malformed SVG XML: {exc}",
                )
            )
            continue
        if en_sig != tr_sig:
            issues.append(
                _issue(
                    bid,
                    "fatal",
                    "svg_integrity",
                    "R8",
                    f"block {bid} SVG element tree or geometry attributes differ from English SVG",
                )
            )
    return issues


def rule_trans_length_budget(
    en_lesson: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """R9: Enforces ADR-0023 expansion budgets on simulation slider labels,
    diagram SVG text labels, and card titles."""
    issues: list[dict[str, Any]] = []
    en_title = str(en_lesson.get("title", ""))
    tr_title = str(tr_meta.get("title", ""))
    if len(tr_title) > int(len(en_title) * 1.35) + 10:
        issues.append(
            _issue(
                "b-00-meta",
                "minor",
                "length_budget",
                "R9",
                f"b-00-meta title length {len(tr_title)} exceeds 1.35x + 10 budget",
            )
        )

    for en_b, tr_b in zip(en_blocks, tr_blocks, strict=False):
        bid = str(en_b.get("id", "b-01"))
        btype = en_b.get("type")
        en_spec = en_b.get("spec", {})
        tr_spec = tr_b.get("spec", {})

        if btype == "simulation":
            for c in tr_spec.get("controls", []):
                lbl = str(c.get("label", ""))
                if len(lbl) > 40:
                    issues.append(
                        _issue(
                            bid,
                            "fatal",
                            "length_budget",
                            "R9",
                            f"block {bid} control {c.get('id')!r} label is {len(lbl)} "
                            "chars (> 40 fatal cap; max 32 chars)",
                        )
                    )
                elif len(lbl) > 32:
                    issues.append(
                        _issue(
                            bid,
                            "major",
                            "length_budget",
                            "R9",
                            f"block {bid} control {c.get('id')!r} label is {len(lbl)} "
                            "chars (exceeds 32-char slider budget)",
                        )
                    )
            en_st = str(en_spec.get("title", ""))
            tr_st = str(tr_spec.get("title", ""))
            if len(tr_st) > int(len(en_st) * 1.35) + 10:
                issues.append(
                    _issue(
                        bid,
                        "minor",
                        "length_budget",
                        "R9",
                        f"block {bid} simulation title exceeds 1.35x + 10 budget",
                    )
                )

        elif btype == "diagram":
            try:
                en_diag = translate.extract_diagram_payload(en_b)
                tr_root = ET.fromstring(str(tr_spec.get("svg", "")))
                tr_texts: list[str] = []
                for elem in tr_root.iter():
                    tag = elem.tag.split("}", 1)[1] if "}" in elem.tag else elem.tag
                    if tag in ("text", "tspan"):
                        raw = (elem.text or "").strip()
                        if raw and not translate.is_pure_symbol_or_numeral(raw):
                            tr_texts.append(raw)
                for src_item, tr_txt in zip(
                    en_diag.get("svg_texts", []), tr_texts, strict=False
                ):
                    max_c = int(src_item["max_chars"])
                    if len(tr_txt) > max_c:
                        issues.append(
                            _issue(
                                bid,
                                "major",
                                "length_budget",
                                "R9",
                                f"block {bid} SVG label {src_item['id']} is {len(tr_txt)} "
                                f"chars (exceeds max_chars={max_c})",
                            )
                        )
            except Exception:  # noqa: BLE001
                pass

        elif btype == "reveal":
            en_rt = str(en_spec.get("title", ""))
            tr_rt = str(tr_spec.get("title", ""))
            if len(tr_rt) > int(len(en_rt) * 1.35) + 10:
                issues.append(
                    _issue(
                        bid,
                        "minor",
                        "length_budget",
                        "R9",
                        f"block {bid} reveal title exceeds 1.35x + 10 budget",
                    )
                )
    return issues


def run_all_trans_rules(
    *,
    locale: str,
    ground_truth: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: list[dict[str, Any]],
    tr_meta: dict[str, Any],
    tr_blocks: list[dict[str, Any]],
    en_sim_strings: dict[str, dict[str, str]] | None = None,
    tr_sim_strings: dict[str, dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Run all 9 deterministic translation checks (R1..R9, reviewer-rubric.md §2)."""
    return (
        rule_trans_schema(en_lesson, en_blocks, tr_meta, tr_blocks)
        + rule_trans_citations(en_blocks, tr_blocks)
        + rule_trans_numbers(en_lesson, en_blocks, tr_meta, tr_blocks)
        + rule_trans_units_and_symbols(ground_truth, en_blocks, tr_blocks)
        + rule_trans_mcq_integrity(en_blocks, tr_blocks)
        + rule_trans_script_purity(locale, tr_meta, tr_blocks)
        + rule_trans_placeholders(
            en_lesson,
            en_blocks,
            tr_meta,
            tr_blocks,
            en_sim_strings=en_sim_strings,
            tr_sim_strings=tr_sim_strings,
        )
        + rule_trans_svg_safety(en_blocks, tr_blocks)
        + rule_trans_length_budget(en_lesson, en_blocks, tr_meta, tr_blocks)
    )


# --------------------------------------------------- Layer 2: LLM Reviewer
def build_reviewer_messages(
    *,
    locale: str,
    class_level: int,
    glossary_terms: list[dict[str, Any]],
    paired_units: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Build the calibrated Evon v3.3 reviewer prompt per reviewer-rubric.md §3.3."""
    loc_meta = translate.LOCALE_METADATA[locale]
    system = (
        "[ZIVON STAGE: 10-transcheck] [STAGE_ID: 10b-transcheck] "
        "You are the Physics Translation Reviewer for Zivon (Class 9-12 NCERT Physics).\n"
        "Your job is to verify that a localized lesson faithfully preserves the exact "
        "physics meaning, NCERT terminology, and learner clarity of the verified English "
        "source blocks.\n"
        "Output ONLY a single JSON object matching the schema."
    )
    user = (
        "=== TARGET LOCALE & POLICY ===\n"
        f"Locale: {locale} ({loc_meta['autonym']} / {loc_meta['english_name']}, "
        f"script: {loc_meta['script']})\n"
        f"Policy: {loc_meta['script_rule']}\n\n"
        "=== CHAPTER GLOSSARY (CANONICAL TERMS) ===\n"
        f"{json.dumps(glossary_terms, indent=2, ensure_ascii=False)}\n\n"
        f"=== SOURCE (ENGLISH) vs TRANSLATED ({locale}) UNITS ===\n"
        f"{json.dumps(paired_units, indent=2, ensure_ascii=False)}\n\n"
        "=== REVIEW GOAL & RUBRIC ===\n"
        "Inspect each unit pair (b-00-meta and b-01..b-NN) once in order.\n"
        f"Hunt for REAL physics translation errors. If the translation is faithful, "
        f"accurate, and clear for a Class {class_level} learner, return an empty issues "
        'array: {"issues": []}.\n\n'
        "Report an issue ONLY when you can cite the exact English text and the exact "
        "translated text:\n"
        '- "fatal": Distorts or inverts physics meaning (e.g. confuses speed/velocity '
        'or distance/displacement, drops a condition like "uniform" or "at rest", '
        "drops a negation, or makes the correct MCQ option physically wrong).\n"
        '- "major": Uses the wrong physics term instead of the Chapter Glossary term, '
        'omits the required first-mention bilingual gloss "<Native Term> (<English Term>)" '
        "on a core glossary term, leaves an English sentence untranslated, or "
        "hallucinates extra claims not in the English block.\n"
        '- "minor": Minor phrasing stiffness that does not mislead the learner. If you '
        'are uncertain about a regional nuance, prefix the message with "unverified:" '
        'and use severity "minor".\n\n'
        "Do NOT flag Western Arabic numerals (0-9), SI units (m/s, m/s², N, kg, J), "
        "or Latin variable symbols (v, u, a, t, F) — keeping those in standard "
        "international form is mandatory policy.\n\n"
        "Return ONLY a JSON object matching the schema:\n"
        '{"issues": [{"block_id": "b-03", "severity": "fatal"|"major"|"minor", '
        '"category": "physics_meaning"|"glossary_term"|"untranslated_leak"|'
        '"hallucinated_content"|"grade_register"|"awkward_phrasing", "message": "..."}]}'
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def normalize_reviewer_issues(
    raw_issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Apply the unverified: escape-hatch downgrade in code (reviewer-rubric.md §3.2):
    any issue whose message starts with 'unverified:' is downgraded to 'minor'."""
    normalized: list[dict[str, Any]] = []
    for item in raw_issues:
        msg = str(item.get("message", "")).strip()
        sev = str(item.get("severity", "minor"))
        if msg.lower().startswith("unverified:"):
            sev = "minor"
        normalized.append(
            {
                "block_id": str(item.get("block_id", "b-01")),
                "severity": sev,
                "category": str(item.get("category", "awkward_phrasing")),
                "message": msg,
            }
        )
    return normalized


def _promote_verified_units_to_tm(
    cfg: Config,
    run_ctx: RunContext,
    locale: str,
    blocking_unit_ids: set[str],
    all_unit_ids: list[str],
) -> None:
    """Write every unit with zero blocking issues in `10b-transcheck` into the
    persistent Translation Memory (ADR-0022 §2 & reviewer-rubric.md §4.1)."""
    store = tm_store.get_tm_store(cfg)
    for uid in all_unit_ids:
        if uid in blocking_unit_ids:
            continue
        ckpt_file = translate.checkpoint_path(run_ctx, locale, uid)
        if not ckpt_file.exists():
            continue
        try:
            envelope = json.loads(ckpt_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if envelope.get("review_status") != "human_approved":
            envelope["review_status"] = "machine_verified"
        translate.write_checkpoint_atomic(ckpt_file, envelope)
        store.store_verified_unit(envelope)


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    en_lesson: dict[str, Any],
    en_blocks: dict[str, Any],
    translate_out: dict[str, Any],
    round_tag: str | None = None,
    only_units_by_locale: dict[str, set[str]] | None = None,
) -> dict[str, Any]:
    """Execute 10b-transcheck (9 deterministic rules + calibrated LLM judge)."""
    glossary_data = translate.load_glossary(cfg)
    page_js = translate._read_page_js(run_ctx, None)
    en_sim_strings = translate.extract_sim_strings_from_js(page_js)
    en_blocks_list: list[dict[str, Any]] = list(en_blocks["blocks"])
    all_unit_ids = ["b-00-meta", *[str(b["id"]) for b in en_blocks_list]]
    class_level = int(cfg.learner.get("class_level") or 9)

    locales_report: dict[str, Any] = {}
    overall_fail = False
    ledger_lines: list[dict[str, Any]] = []

    for locale, loc_data in translate_out.get("locales", {}).items():
        tr_meta = loc_data["meta"]
        tr_blocks_list = loc_data["blocks"]["blocks"]
        tr_sim_strings = loc_data.get("sim_strings", {})
        unit_status = loc_data.get("unit_status", {})

        # 1. Layer 1: Deterministic code rules (R1..R9)
        rule_issues = run_all_trans_rules(
            locale=locale,
            ground_truth=ground_truth,
            en_lesson=en_lesson,
            en_blocks=en_blocks_list,
            tr_meta=tr_meta,
            tr_blocks=tr_blocks_list,
            en_sim_strings=en_sim_strings,
            tr_sim_strings=tr_sim_strings,
        )

        # 2. Layer 2: Calibrated Evon v3.3 LLM Reviewer (1 call per locale)
        target_units: set[str] | None = (
            only_units_by_locale.get(locale) if only_units_by_locale else None
        )
        # Include 1-block neighbour context around repaired units on re-check
        units_with_context: set[str] | None = None
        if target_units is not None:
            units_with_context = set(target_units)
            for idx, uid in enumerate(all_unit_ids):
                if uid in target_units:
                    if idx > 0:
                        units_with_context.add(all_unit_ids[idx - 1])
                    if idx + 1 < len(all_unit_ids):
                        units_with_context.add(all_unit_ids[idx + 1])

        paired_units: list[dict[str, Any]] = []
        all_candidates_tm_hits = True
        if units_with_context is None or "b-00-meta" in units_with_context:
            if unit_status.get("b-00-meta") != "tm_hit":
                all_candidates_tm_hits = False
            paired_units.append(
                {
                    "unit_id": "b-00-meta",
                    "unit_type": "meta",
                    "source": translate.extract_translatable_payload(
                        "b-00-meta", "meta", en_lesson, sim_strings=en_sim_strings
                    ),
                    "translated": translate.extract_translatable_payload(
                        "b-00-meta", "meta", tr_meta, sim_strings=tr_sim_strings
                    ),
                }
            )
        for en_b, tr_b in zip(en_blocks_list, tr_blocks_list, strict=False):
            bid = str(en_b["id"])
            if units_with_context is not None and bid not in units_with_context:
                continue
            if unit_status.get(bid) != "tm_hit":
                all_candidates_tm_hits = False
            btype = str(en_b["type"])
            paired_units.append(
                {
                    "unit_id": bid,
                    "unit_type": btype,
                    "source": translate.extract_translatable_payload(bid, btype, en_b),
                    "translated": translate.extract_translatable_payload(
                        bid, btype, tr_b
                    ),
                }
            )

        model_issues: list[dict[str, Any]] = []
        # Skip LLM reviewer call only if every single unit was a verified TM hit
        if paired_units and not all_candidates_tm_hits:
            glossary_terms = translate.select_glossary_subset(
                glossary_data,
                locale,
                json.dumps(en_lesson, ensure_ascii=False)
                + " "
                + json.dumps(en_blocks_list, ensure_ascii=False),
                chapter_glossary=en_lesson.get("glossary"),
            )
            r_tag = f"{round_tag}-{locale}" if round_tag else locale
            raw_report = llm.call(
                STAGE_ID,
                build_reviewer_messages(
                    locale=locale,
                    class_level=class_level,
                    glossary_terms=glossary_terms,
                    paired_units=paired_units,
                ),
                TRANSLATION_REVIEW_CALL_REPORT,
                "translation_review_call",
                round_tag=r_tag,
            )
            model_issues = normalize_reviewer_issues(raw_report.get("issues", []))
            if target_units is not None:
                # Filter model issues to the repaired units under inspection
                model_issues = [
                    i for i in model_issues if i.get("block_id") in target_units
                ]

        combined_issues = model_issues + rule_issues
        blocking = [
            i for i in combined_issues if i.get("severity") in ("fatal", "major")
        ]
        blocking_unit_ids = {str(i.get("block_id") or "") for i in blocking}

        # Promote all passing units to Translation Memory (ADR-0022 §2)
        _promote_verified_units_to_tm(
            cfg, run_ctx, locale, blocking_unit_ids, all_unit_ids
        )

        verdict = "fail" if blocking else "pass"
        if verdict == "fail":
            overall_fail = True

        locales_report[locale] = {
            "model_issues": model_issues,
            "rule_issues": rule_issues,
            "blocking_count": len(blocking),
            "verdict": verdict,
        }

        for i in model_issues:
            ledger_lines.append(
                issue_entry(STAGE_ID, f"reviewer-{locale}", round_tag, i)
            )
        for i in rule_issues:
            ledger_lines.append(
                issue_entry(STAGE_ID, f"rules-{locale}", round_tag, i)
            )

    if ledger_lines:
        run_ctx.append_ledger("issues_ledger", ledger_lines)

    return {
        "locales": locales_report,
        "verdict": "fail" if overall_fail else "pass",
    }
