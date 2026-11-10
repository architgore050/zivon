"""Stage 10a-translate: build-time per-block lesson localization via Evon v3.3.

Translates one unit at a time (`b-00-meta`, `b-01`..`b-NN`) per target locale
through `factory/llm.py` (`LLMClient` -> `llm_manager`), with per-`(locale, unit_id)`
disk checkpointing under `runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json`
and two-tier Translation Memory (`sources/cache/tm/` + PostgreSQL Class C3).
Zero Gnani API credits are consumed (`ADR-0013`, `ADR-0015`, `ADR-0021`).
"""

from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jsonschema

from . import checks
from ._logging_shim import ErrorClass, Severity, context_scope, log_event
from .artifacts import RunContext
from .config import Config
from .errors import ConfigError, FactoryError, SchemaError
from .llm import LLMClient
from .schemas import (
    BLOCKS,
    LESSON,
    TRANSLATED_CHECK_MCQ_PAYLOAD,
    TRANSLATED_CHECK_NUMERIC_PAYLOAD,
    TRANSLATED_DIAGRAM_PAYLOAD,
    TRANSLATED_META_PAYLOAD,
    TRANSLATED_REVEAL_PAYLOAD,
    TRANSLATED_SIMULATION_PAYLOAD,
    TRANSLATED_TEXT_PAYLOAD,
    TRANSLATED_WORKED_EXAMPLE_PAYLOAD,
)

STAGE_ID = "10a-translate"

ET.register_namespace("", "http://www.w3.org/2000/svg")

LOCALE_METADATA: dict[str, dict[str, Any]] = {
    "en": {
        "code": "en",
        "autonym": "English",
        "english_name": "English (Source)",
        "script": "Latn",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": 0.0,
        "fallback_locale": None,
        "script_range": (0x0041, 0x007A),
        "script_rule": "Write clear Class 9-12 NCERT English.",
    },
    "hi": {
        "code": "hi",
        "autonym": "हिन्दी",
        "english_name": "Hindi",
        "script": "Deva",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": -1.5,
        "fallback_locale": "en",
        "script_range": (0x0900, 0x097F),
        "script_rule": (
            "Write natural Class 9-12 NCERT Hindi in Devanagari script. On the FIRST "
            "mention of a glossary Physics term in this unit, emit '<Hindi Term> "
            "(<English Term>)', e.g., 'वेग (velocity)'. On later mentions in the same "
            "unit, write '<Hindi Term>' alone. Keep Western Arabic numerals (0-9), SI "
            "units (m/s, m/s², m/s2, N, kg, J), and equations untouched. Never use "
            "Devanagari digits (०-९)."
        ),
    },
    "hi-Latn": {
        "code": "hi-Latn",
        "autonym": "Hinglish",
        "english_name": "Hinglish (Hindi in Latin script)",
        "script": "Latn",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": 0.0,
        "fallback_locale": "hi",
        "script_range": (0x0041, 0x007A),
        "script_rule": (
            "Write natural conversational Hinglish in Latin (Roman) script only — zero "
            "Devanagari characters ([\\u0900-\\u097F]). Keep technical Physics nouns in "
            "standard English spelling (velocity, acceleration, displacement, force, "
            "momentum), with Romanized Hindi gloss in parentheses on first definition "
            "where helpful (velocity (veg)), and write explanatory clauses in clear "
            "Roman Hindi (e.g., 'Yahan initial velocity u = 35 m/s hai'). Keep all "
            "numerals (0-9), SI units, and equations verbatim."
        ),
    },
    "ta": {
        "code": "ta",
        "autonym": "தமிழ்",
        "english_name": "Tamil",
        "script": "Taml",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0B80, 0x0BFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Tamil script "
            "(Taml). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "te": {
        "code": "te",
        "autonym": "తెలుగు",
        "english_name": "Telugu",
        "script": "Telu",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0C00, 0x0C7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Telugu script "
            "(Telu). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "mr": {
        "code": "mr",
        "autonym": "मराठी",
        "english_name": "Marathi",
        "script": "Deva",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.5,
        "fallback_locale": "en",
        "script_range": (0x0900, 0x097F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Marathi Devanagari "
            "script (Deva). On FIRST mention of a glossary Physics term in this unit, "
            "emit '<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), "
            "SI units, and equations character-for-character identical to the source."
        ),
    },
    "bn": {
        "code": "bn",
        "autonym": "বাংলা",
        "english_name": "Bengali",
        "script": "Beng",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0980, 0x09FF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Bengali script "
            "(Beng). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "gu": {
        "code": "gu",
        "autonym": "ગુજરાતી",
        "english_name": "Gujarati",
        "script": "Gujr",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0A80, 0x0AFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Gujarati script "
            "(Gujr). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "kn": {
        "code": "kn",
        "autonym": "ಕನ್ನಡ",
        "english_name": "Kannada",
        "script": "Knda",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0C80, 0x0CFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Kannada script "
            "(Knda). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "ml": {
        "code": "ml",
        "autonym": "മലയാളം",
        "english_name": "Malayalam",
        "script": "Mlym",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0D00, 0x0D7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Malayalam script "
            "(Mlym). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "pa": {
        "code": "pa",
        "autonym": "ਪੰਜਾਬੀ",
        "english_name": "Punjabi (Gurmukhi)",
        "script": "Guru",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0A00, 0x0A7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Gurmukhi script "
            "(Guru). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
}

_REGIONAL_DIGIT_RE = re.compile(
    r"[\u0966-\u096F\u0BE6-\u0BEF\u0C66-\u0C6F\u09E6-\u09EF"
    r"\u0AE6-\u0AEF\u0CE6-\u0CEF\u0D66-\u0D6F\u0A66-\u0A6F]"
)
_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_NUMERAL_RE = re.compile(r"\d+(?:\.\d+)?")
_PLACEHOLDER_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bTODO\b"), "TODO marker"),
    (re.compile(r"\bTBD\b"), "TBD marker"),
    (re.compile(r"\[\s*translate\s*\]", re.IGNORECASE), "[translate] placeholder"),
    (re.compile(r"<\s*translate\s*>", re.IGNORECASE), "<translate> placeholder"),
    (re.compile(r"\{\{|\}\}"), "mustache template braces {{ or }}"),
]
_TEMPLATE_VAR_RE = re.compile(r"\{[a-zA-Z0-9_]+\}")

_PURE_SYMBOL_CHARS_RE = re.compile(r"^[\d\s.,+\-−=×÷/()^₀-₉⁰-⁹a-zA-ZΔθωλμ°%]+$")
_SI_UNIT_WORDS = {
    "m",
    "s",
    "kg",
    "g",
    "n",
    "j",
    "w",
    "pa",
    "hz",
    "c",
    "v",
    "a",
    "ms",
    "cm",
    "mm",
    "km",
    "hr",
    "min",
    "sec",
    "rad",
    "deg",
    "mol",
    "cd",
    "wb",
    "t",
}


def is_pure_symbol_or_numeral(text: str) -> bool:
    """Return True if an SVG <text> string is a standalone math symbol, number,
    or quantity/unit token (e.g. 'F', '10 N', 'm₁', 'v (m/s)', 't (s)', '0')
    that must not be translated (CP-TRN-002 / block-contract.md §3.6)."""
    stripped = text.strip()
    if not stripped:
        return True
    if not _PURE_SYMBOL_CHARS_RE.match(stripped):
        return False
    # Extract alphabetic word tokens (ignoring subscripts/digits)
    words = re.findall(r"[A-Za-z]+", stripped)
    if not words:
        return True
    for w in words:
        low = w.lower()
        # Any 1-letter symbol (F, v, u, a, t, O, A, B) or known SI unit abbreviation
        # is a symbol/unit token; any longer word ('time', 'slope', 'weight') is prose.
        if len(w) == 1 or low in _SI_UNIT_WORDS:
            continue
        return False
    return True


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[1] if "}" in tag else tag


def extract_diagram_payload(block: dict[str, Any]) -> dict[str, Any]:
    """Extract caption, root svg_aria_label, and descriptive <text> strings
    from a diagram block without exposing raw SVG geometry to the model."""
    spec = block["spec"]
    svg_str = str(spec.get("svg", ""))
    try:
        root = ET.fromstring(svg_str)
    except ET.ParseError as exc:
        raise SchemaError(
            STAGE_ID,
            f"diagram block {block.get('id')} has invalid SVG XML: {exc}",
        ) from exc

    svg_aria_label = str(root.attrib.get("aria-label", ""))
    svg_texts: list[dict[str, Any]] = []
    idx = 0
    for elem in root.iter():
        if _local_tag(elem.tag) in ("text", "tspan"):
            raw = (elem.text or "").strip()
            if raw and not is_pure_symbol_or_numeral(raw):
                max_chars = max(int(len(raw) * 1.25), len(raw) + 6)
                svg_texts.append(
                    {
                        "id": f"t-{idx}",
                        "source": raw,
                        "max_chars": max_chars,
                    }
                )
                idx += 1
    return {
        "caption": str(spec.get("caption", "")),
        "svg_aria_label": svg_aria_label,
        "svg_texts": svg_texts,
    }


def reinject_diagram_svg(
    block_id: str,
    source_svg: str,
    translated_diagram_payload: dict[str, Any],
) -> str:
    """Re-inject translated <text> strings and aria-label into a clone of the
    English SVG DOM, tag localized <text> elements with data-i18n, and verify
    via factory/checks.py::rule_diagram_svg (block-contract.md §3.6)."""
    source_extracted = extract_diagram_payload(
        {"id": block_id, "type": "diagram", "spec": {"svg": source_svg, "caption": ""}}
    )
    expected_ids = [item["id"] for item in source_extracted["svg_texts"]]
    got_items = translated_diagram_payload.get("svg_texts", [])
    got_ids = [item.get("id") for item in got_items]
    if got_ids != expected_ids:
        raise ValueError(
            f"diagram {block_id} svg_texts id mismatch: expected {expected_ids}, got {got_ids}"
        )

    text_by_id: dict[str, str] = {}
    for src_item, tr_item in zip(source_extracted["svg_texts"], got_items, strict=True):
        tr_text = str(tr_item.get("text", "")).strip()
        if not tr_text:
            raise ValueError(f"diagram {block_id} svg_texts[{src_item['id']}] is empty")
        if "<" in tr_text or ">" in tr_text:
            raise ValueError(
                f"diagram {block_id} svg_texts[{src_item['id']}] contains forbidden '<' or '>'"
            )
        text_by_id[src_item["id"]] = tr_text

    aria_label = str(translated_diagram_payload.get("svg_aria_label", "")).strip()
    if "<" in aria_label or ">" in aria_label:
        raise ValueError(
            f"diagram {block_id} svg_aria_label contains forbidden '<' or '>'"
        )

    root = ET.fromstring(source_svg)
    if aria_label:
        root.set("aria-label", aria_label)

    idx = 0
    for elem in root.iter():
        if _local_tag(elem.tag) in ("text", "tspan"):
            raw = (elem.text or "").strip()
            if raw and not is_pure_symbol_or_numeral(raw):
                tid = f"t-{idx}"
                elem.text = text_by_id[tid]
                elem.set("data-i18n", f"{block_id}.svg_texts.{tid}")
                idx += 1

    serialized = ET.tostring(root, encoding="unicode")
    svg_issues = checks.rule_diagram_svg(
        [
            {
                "id": block_id,
                "type": "diagram",
                "spec": {"svg": serialized, "caption": ""},
            }
        ]
    )
    if svg_issues:
        raise ValueError(
            f"re-injected SVG for {block_id} failed rule_diagram_svg: "
            + "; ".join(i["message"] for i in svg_issues)
        )
    return serialized


def extract_sim_strings_from_js(page_js: str) -> dict[str, dict[str, str]]:
    """Extract ctx.t_str('key', 'English fallback') pairs per simulation block
    from page.js (CP-TRN-003). Returns {} when page.js has no t_str calls."""
    if not page_js.strip():
        return {}
    out: dict[str, dict[str, str]] = {}
    reg_re = re.compile(
        r"""ZivonSim\.register\(\s*["'](b-[0-9]{2})["']\s*,\s*\{""",
        re.MULTILINE,
    )
    t_str_re = re.compile(
        r"""\bctx\.t_str\(\s*["']([^"']+)["']\s*,\s*["']([^"']*)["']\s*\)"""
    )
    matches = list(reg_re.finditer(page_js))
    for i, m in enumerate(matches):
        bid = m.group(1)
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(page_js)
        segment = page_js[start:end]
        pairs: dict[str, str] = {}
        for tm in t_str_re.finditer(segment):
            pairs[tm.group(1)] = tm.group(2)
        if pairs:
            out[bid] = pairs
    return out


def extract_translatable_payload(
    unit_id: str,
    unit_type: str,
    block_or_meta: dict[str, Any],
    sim_strings: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Return ONLY the translatable fields for a unit (SP2-TRANS §3.1 & block-contract.md)."""
    if unit_id == "b-00-meta" or unit_type == "meta":
        return {
            "title": str(block_or_meta["title"]),
            "objectives": [str(o) for o in block_or_meta["objectives"]],
            "sections": [
                {
                    "id": str(s["id"]),
                    "title": str(s["title"]),
                    "paragraphs": [str(p) for p in s["paragraphs"]],
                }
                for s in block_or_meta["sections"]
            ],
            "glossary": [
                {"term": str(g["term"]), "definition": str(g["definition"])}
                for g in block_or_meta["glossary"]
            ],
            "sim_strings": copy.deepcopy(
                sim_strings
                if sim_strings is not None
                else block_or_meta.get("sim_strings", {})
            ),
        }

    spec = block_or_meta["spec"]
    if unit_type == "text":
        return {"paragraphs": [str(p) for p in spec["paragraphs"]]}
    if unit_type == "worked_example":
        return {
            "problem": str(spec["problem"]),
            "steps": [
                {"title": str(s["title"]), "detail": str(s["detail"])}
                for s in spec["steps"]
            ],
            "answer": str(spec["answer"]),
        }
    if unit_type == "check":
        fmt = spec.get("format")
        if fmt == "mcq":
            return {
                "question": str(spec["question"]),
                "options": [str(o) for o in spec["options"]],
                "explanation": str(spec["explanation"]),
                "expected_understanding": str(spec["expected_understanding"]),
            }
        if fmt == "numeric":
            return {
                "question": str(spec["question"]),
                "explanation": str(spec["explanation"]),
                "expected_understanding": str(spec["expected_understanding"]),
            }
        raise ConfigError(f"unknown check format {fmt!r} in block {unit_id}")
    if unit_type == "reveal":
        return {
            "title": str(spec["title"]),
            "steps": [
                {"title": str(s["title"]), "detail": str(s["detail"])}
                for s in spec["steps"]
            ],
        }
    if unit_type == "diagram":
        return extract_diagram_payload(block_or_meta)
    if unit_type == "simulation":
        return {
            "title": str(spec["title"]),
            "description": str(spec["description"]),
            "learning_goal": str(spec["learning_goal"]),
            "controls": [
                {"id": str(c["id"]), "label": str(c["label"])}
                for c in spec.get("controls", [])
            ],
            "default_behaviour": str(spec["default_behaviour"]),
        }
    raise ConfigError(f"unknown unit_type {unit_type!r} for unit {unit_id}")


def schema_for_unit(
    unit_id: str, unit_type: str, source_block_or_meta: dict[str, Any]
) -> tuple[dict[str, Any], str]:
    """Return (json_schema, schema_name) for a translatable unit."""
    if unit_id == "b-00-meta" or unit_type == "meta":
        return TRANSLATED_META_PAYLOAD, "translated_meta"
    if unit_type == "text":
        return TRANSLATED_TEXT_PAYLOAD, "translated_text"
    if unit_type == "worked_example":
        return TRANSLATED_WORKED_EXAMPLE_PAYLOAD, "translated_worked_example"
    if unit_type == "check":
        fmt = source_block_or_meta.get("spec", {}).get("format")
        if fmt == "mcq":
            return TRANSLATED_CHECK_MCQ_PAYLOAD, "translated_check_mcq"
        return TRANSLATED_CHECK_NUMERIC_PAYLOAD, "translated_check_numeric"
    if unit_type == "reveal":
        return TRANSLATED_REVEAL_PAYLOAD, "translated_reveal"
    if unit_type == "diagram":
        return TRANSLATED_DIAGRAM_PAYLOAD, "translated_diagram"
    if unit_type == "simulation":
        return TRANSLATED_SIMULATION_PAYLOAD, "translated_simulation"
    raise ConfigError(f"unknown unit_type {unit_type!r} for unit {unit_id}")


def reassemble_translated_unit(
    unit_id: str,
    unit_type: str,
    source_block_or_meta: dict[str, Any],
    translated_payload: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically merge translated strings into a deep copy of the
    verified English unit and validate against LESSON or BLOCKS schema."""
    if unit_id == "b-00-meta" or unit_type == "meta":
        meta_out = {
            "title": str(translated_payload["title"]),
            "objectives": [str(o) for o in translated_payload["objectives"]],
            "sections": [
                {
                    "id": str(src_sec["id"]),
                    "title": str(tr_sec["title"]),
                    "paragraphs": [str(p) for p in tr_sec["paragraphs"]],
                }
                for src_sec, tr_sec in zip(
                    source_block_or_meta["sections"],
                    translated_payload["sections"],
                    strict=True,
                )
            ],
            "glossary": [
                {"term": str(g["term"]), "definition": str(g["definition"])}
                for g in translated_payload["glossary"]
            ],
        }
        # Validate against LESSON schema (relaxing only minLength if Indic script is compact)
        jsonschema.Draft7Validator(
            {
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
        ).validate(meta_out)
        return meta_out

    block_out = copy.deepcopy(source_block_or_meta)
    spec_out = block_out["spec"]
    if unit_type == "text":
        spec_out["paragraphs"] = [str(p) for p in translated_payload["paragraphs"]]
    elif unit_type == "worked_example":
        spec_out["problem"] = str(translated_payload["problem"])
        spec_out["steps"] = [
            {"title": str(s["title"]), "detail": str(s["detail"])}
            for s in translated_payload["steps"]
        ]
        spec_out["answer"] = str(translated_payload["answer"])
    elif unit_type == "check":
        fmt = spec_out.get("format")
        if fmt == "mcq":
            options = [str(o) for o in translated_payload["options"]]
            answer_index = int(spec_out["answer_index"])
            spec_out["question"] = str(translated_payload["question"])
            spec_out["options"] = options
            # Deterministic answer-key lock (block-contract.md §3.4 Variant A)
            spec_out["answer"] = options[answer_index]
            spec_out["explanation"] = str(translated_payload["explanation"])
            spec_out["expected_understanding"] = str(
                translated_payload["expected_understanding"]
            )
        else:
            spec_out["question"] = str(translated_payload["question"])
            # Deterministic numeric answer lock (block-contract.md §3.4 Variant B)
            spec_out["answer"] = str(source_block_or_meta["spec"]["answer"])
            spec_out["explanation"] = str(translated_payload["explanation"])
            spec_out["expected_understanding"] = str(
                translated_payload["expected_understanding"]
            )
    elif unit_type == "reveal":
        spec_out["title"] = str(translated_payload["title"])
        spec_out["steps"] = [
            {"title": str(s["title"]), "detail": str(s["detail"])}
            for s in translated_payload["steps"]
        ]
    elif unit_type == "diagram":
        spec_out["caption"] = str(translated_payload["caption"])
        spec_out["svg"] = reinject_diagram_svg(
            unit_id,
            str(source_block_or_meta["spec"]["svg"]),
            translated_payload,
        )
    elif unit_type == "simulation":
        spec_out["title"] = str(translated_payload["title"])
        spec_out["description"] = str(translated_payload["description"])
        spec_out["learning_goal"] = str(translated_payload["learning_goal"])
        spec_out["default_behaviour"] = str(translated_payload["default_behaviour"])
        for orig_ctrl, tr_ctrl in zip(
            spec_out.get("controls", []),
            translated_payload.get("controls", []),
            strict=True,
        ):
            orig_ctrl["label"] = str(tr_ctrl["label"])

    block_item_schema = BLOCKS["properties"]["blocks"]["items"]
    jsonschema.Draft7Validator(block_item_schema).validate(block_out)
    return block_out


def _collect_strings(obj: Any) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, list):
        out: list[str] = []
        for x in obj:
            out.extend(_collect_strings(x))
        return out
    if isinstance(obj, dict):
        out = []
        for k, v in obj.items():
            if k == "id":
                continue
            out.extend(_collect_strings(v))
        return out
    return []


def check_unit_deterministic_invariants(
    locale: str,
    unit_id: str,
    unit_type: str,
    source_payload: dict[str, Any],
    translated_payload: dict[str, Any],
    source_block_or_meta: dict[str, Any] | None = None,
    glossary_subset: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Code-side extra_validator run inside llm_manager's validation retry loop
    (block-contract.md §3 & §5). Returns a list of human-readable problem strings."""
    del glossary_subset
    problems: list[str] = []

    all_tr_strings = _collect_strings(translated_payload)
    all_src_strings = _collect_strings(source_payload)
    src_joined = " ".join(all_src_strings)

    # 1. Regional digits check (R3)
    for text in all_tr_strings:
        m = _REGIONAL_DIGIT_RE.search(text)
        if m:
            problems.append(
                f"[R3 number_mismatch] unit {unit_id}: contains forbidden regional "
                f"digit {m.group(0)!r}; use Western Arabic numerals (0-9) only"
            )
            break

    # 2. Script purity check (R6)
    if locale == "hi-Latn":
        for text in all_tr_strings:
            m = _DEVANAGARI_RE.search(text)
            if m:
                problems.append(
                    f"[R6 script_violation] unit {unit_id}: hi-Latn (Hinglish) must use "
                    f"Latin script only, found Devanagari character {m.group(0)!r}"
                )
                break

    # 3. Placeholder leak check (R7)
    for text in all_tr_strings:
        for pat, desc in _PLACEHOLDER_PATTERNS:
            if pat.search(text) and not pat.search(src_joined):
                problems.append(
                    f"[R7 placeholder_leak] unit {unit_id}: contains untranslated {desc}"
                )
                break
        if text.rstrip().endswith("...") and not any(
            s.rstrip().endswith("...") for s in all_src_strings
        ):
            problems.append(
                f"[R7 placeholder_leak] unit {unit_id}: translated text ends with "
                "truncation ellipsis '...' not present in source"
            )
            break

    # 4. Per-unit structural and numeral invariants
    if unit_id == "b-00-meta" or unit_type == "meta":
        src_secs = source_payload.get("sections", [])
        tr_secs = translated_payload.get("sections", [])
        if len(tr_secs) != len(src_secs):
            problems.append(
                f"[R1 schema_integrity] b-00-meta: expected {len(src_secs)} sections, "
                f"got {len(tr_secs)}"
            )
        else:
            for s_sec, t_sec in zip(src_secs, tr_secs, strict=True):
                if t_sec.get("id") != s_sec.get("id"):
                    problems.append(
                        f"[R1 schema_integrity] b-00-meta: section id mismatch "
                        f"expected {s_sec.get('id')!r}, got {t_sec.get('id')!r}"
                    )
                if len(t_sec.get("paragraphs", [])) != len(s_sec.get("paragraphs", [])):
                    problems.append(
                        f"[R1 schema_integrity] b-00-meta section {s_sec.get('id')}: "
                        f"expected {len(s_sec.get('paragraphs', []))} paragraphs, "
                        f"got {len(t_sec.get('paragraphs', []))}"
                    )
        if len(translated_payload.get("objectives", [])) != len(
            source_payload.get("objectives", [])
        ):
            problems.append(
                f"[R1 schema_integrity] b-00-meta: expected "
                f"{len(source_payload.get('objectives', []))} objectives, got "
                f"{len(translated_payload.get('objectives', []))}"
            )
        if len(translated_payload.get("glossary", [])) != len(
            source_payload.get("glossary", [])
        ):
            problems.append(
                f"[R1 schema_integrity] b-00-meta: expected "
                f"{len(source_payload.get('glossary', []))} glossary items, got "
                f"{len(translated_payload.get('glossary', []))}"
            )
        # Verify sim_strings template placeholders ({0}, {val})
        src_sims = source_payload.get("sim_strings", {})
        tr_sims = translated_payload.get("sim_strings", {})
        for bid, key_map in src_sims.items():
            tr_map = tr_sims.get(bid, {})
            for k, src_val in key_map.items():
                if k not in tr_map:
                    problems.append(
                        f"[R7 placeholder_leak] b-00-meta sim_strings.{bid}.{k} missing"
                    )
                    continue
                src_vars = set(_TEMPLATE_VAR_RE.findall(str(src_val)))
                tr_vars = set(_TEMPLATE_VAR_RE.findall(str(tr_map[k])))
                if src_vars != tr_vars:
                    problems.append(
                        f"[R7 placeholder_leak] b-00-meta sim_strings.{bid}.{k} "
                        f"placeholder mismatch: expected {sorted(src_vars)}, got {sorted(tr_vars)}"
                    )

    elif unit_type == "text":
        if len(translated_payload.get("paragraphs", [])) != len(
            source_payload.get("paragraphs", [])
        ):
            problems.append(
                f"[R1 schema_integrity] unit {unit_id}: expected "
                f"{len(source_payload.get('paragraphs', []))} paragraphs, got "
                f"{len(translated_payload.get('paragraphs', []))}"
            )

    elif unit_type == "worked_example":
        if len(translated_payload.get("steps", [])) != len(
            source_payload.get("steps", [])
        ):
            problems.append(
                f"[R1 schema_integrity] unit {unit_id}: expected "
                f"{len(source_payload.get('steps', []))} steps, got "
                f"{len(translated_payload.get('steps', []))}"
            )
        src_prob_nums = Counter(
            _NUMERAL_RE.findall(str(source_payload.get("problem", "")))
        )
        tr_prob_nums = Counter(
            _NUMERAL_RE.findall(str(translated_payload.get("problem", "")))
        )
        if src_prob_nums != tr_prob_nums:
            problems.append(
                f"[R3 number_mismatch] unit {unit_id}: worked_example problem numerals "
                f"must match source 100% (expected {dict(src_prob_nums)}, got {dict(tr_prob_nums)})"
            )
        src_ans_nums = Counter(
            _NUMERAL_RE.findall(str(source_payload.get("answer", "")))
        )
        tr_ans_nums = Counter(
            _NUMERAL_RE.findall(str(translated_payload.get("answer", "")))
        )
        if src_ans_nums != tr_ans_nums:
            problems.append(
                f"[R3 number_mismatch] unit {unit_id}: worked_example answer numerals "
                f"must match source 100% (expected {dict(src_ans_nums)}, got {dict(tr_ans_nums)})"
            )

    elif unit_type == "check":
        src_q_nums = Counter(
            _NUMERAL_RE.findall(str(source_payload.get("question", "")))
        )
        tr_q_nums = Counter(
            _NUMERAL_RE.findall(str(translated_payload.get("question", "")))
        )
        if src_q_nums != tr_q_nums:
            problems.append(
                f"[R3 number_mismatch] unit {unit_id}: check question numerals must "
                f"match source 100% (expected {dict(src_q_nums)}, got {dict(tr_q_nums)})"
            )
        if "options" in source_payload:
            src_opts = source_payload["options"]
            tr_opts = translated_payload.get("options", [])
            if len(tr_opts) != len(src_opts):
                problems.append(
                    f"[R5 answer_key] unit {unit_id}: expected {len(src_opts)} MCQ "
                    f"options, got {len(tr_opts)}"
                )
            elif len({str(o).strip() for o in tr_opts}) != len(tr_opts):
                problems.append(
                    f"[R5 answer_key] unit {unit_id}: translated MCQ options must all be distinct"
                )
            elif source_block_or_meta is not None:
                ans_idx = int(source_block_or_meta["spec"]["answer_index"])
                src_opt_nums = Counter(_NUMERAL_RE.findall(str(src_opts[ans_idx])))
                tr_opt_nums = Counter(_NUMERAL_RE.findall(str(tr_opts[ans_idx])))
                if src_opt_nums != tr_opt_nums:
                    problems.append(
                        f"[R3 number_mismatch] unit {unit_id}: correct option[{ans_idx}] "
                        f"numerals must match source (expected {dict(src_opt_nums)}, "
                        f"got {dict(tr_opt_nums)})"
                    )

    elif unit_type == "reveal":
        if len(translated_payload.get("steps", [])) != len(
            source_payload.get("steps", [])
        ):
            problems.append(
                f"[R1 schema_integrity] unit {unit_id}: expected "
                f"{len(source_payload.get('steps', []))} steps, got "
                f"{len(translated_payload.get('steps', []))}"
            )

    elif unit_type == "diagram":
        src_texts = source_payload.get("svg_texts", [])
        tr_texts = translated_payload.get("svg_texts", [])
        if [x.get("id") for x in tr_texts] != [x.get("id") for x in src_texts]:
            problems.append(
                f"[R8 svg_integrity] unit {unit_id}: svg_texts ids must match "
                f"{[x.get('id') for x in src_texts]}"
            )
        else:
            for src_item, tr_item in zip(src_texts, tr_texts, strict=True):
                txt = str(tr_item.get("text", ""))
                max_c = int(src_item["max_chars"])
                if "<" in txt or ">" in txt:
                    problems.append(
                        f"[R8 svg_integrity] unit {unit_id}: svg_texts[{src_item['id']}] "
                        "contains forbidden '<' or '>'"
                    )
                if len(txt) > max_c:
                    problems.append(
                        f"[R9 length_budget] unit {unit_id}: svg_texts[{src_item['id']}] "
                        f"is {len(txt)} chars, max allowed is {max_c}"
                    )

    elif unit_type == "simulation":
        src_ctrls = source_payload.get("controls", [])
        tr_ctrls = translated_payload.get("controls", [])
        if [c.get("id") for c in tr_ctrls] != [c.get("id") for c in src_ctrls]:
            problems.append(
                f"[R1 schema_integrity] unit {unit_id}: simulation control ids must "
                f"match {[c.get('id') for c in src_ctrls]}"
            )
        for c in tr_ctrls:
            lbl = str(c.get("label", ""))
            if len(lbl) > 32:
                problems.append(
                    f"[R9 length_budget] unit {unit_id}: control {c.get('id')!r} label "
                    f"is {len(lbl)} chars (max 32)"
                )

    return problems


def load_glossary(cfg: Config) -> dict[str, Any]:
    path = cfg.repo_path(cfg.translation["glossary_path"])
    if not path.exists():
        return {"glossary_version": "1.0.0", "terms": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_ui_strings(cfg: Config) -> dict[str, dict[str, str]]:
    path = cfg.repo_path(cfg.translation["ui_strings_path"])
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("strings", {}))


def select_glossary_subset(
    glossary_data: dict[str, Any],
    locale: str,
    text_blob: str,
    chapter_glossary: list[dict[str, str]] | None = None,
) -> list[dict[str, Any]]:
    """Return the subset of canonical glossary terms whose English term appears
    (case-insensitive stem match) in `text_blob` (SP2-TRANS §2.3)."""
    lowered = text_blob.lower()
    matched: list[dict[str, Any]] = []
    seen_en: set[str] = set()
    for entry in glossary_data.get("terms", []):
        en_term = str(entry.get("english_term", "")).strip()
        if not en_term:
            continue
        stem = en_term.lower()[: max(4, len(en_term) - 2)]
        if stem in lowered or en_term.lower() in lowered:
            loc_map = entry.get("locales", {}).get(locale)
            if loc_map:
                matched.append(
                    {
                        "english_term": en_term,
                        "native_term": loc_map["native_term"],
                        "first_mention_gloss": loc_map["first_mention_gloss"],
                        "short_label": loc_map["short_label"],
                    }
                )
                seen_en.add(en_term.lower())
    if chapter_glossary:
        for g in chapter_glossary:
            t_name = str(g.get("term", "")).strip()
            if t_name and t_name.lower() not in seen_en and t_name.lower() in lowered:
                matched.append(
                    {
                        "english_term": t_name,
                        "native_term": t_name,
                        "first_mention_gloss": t_name,
                        "short_label": t_name,
                    }
                )
                seen_en.add(t_name.lower())
    return matched[:12]


def _unit_excerpt(unit_type: str, block_or_meta: dict[str, Any], max_chars: int) -> str:
    if unit_type == "meta":
        text = str(block_or_meta.get("title", ""))
    else:
        spec = block_or_meta.get("spec", {})
        text = str(
            (spec.get("paragraphs") or [""])[0]
            if unit_type == "text"
            else spec.get("problem")
            or spec.get("question")
            or spec.get("title")
            or spec.get("caption")
            or ""
        )
    text = text.strip().replace("\n", " ")
    return text[:max_chars]


def build_translate_messages(
    *,
    locale: str,
    chapter_title: str,
    class_level: int,
    unit_id: str,
    unit_type: str,
    source_payload: dict[str, Any],
    glossary_subset: list[dict[str, Any]],
    neighbour_ctx: dict[str, str],
    repair_feedback: list[str] | None = None,
) -> list[dict[str, str]]:
    """Construct the 2-message OpenAI chat-completions transcript per
    block-contract.md §2.1 & §2.2."""
    loc_meta = LOCALE_METADATA[locale]
    stage_marker = (
        "[ZIVON STAGE: 10-translate] [STAGE_ID: 10a-translate]"
        if not repair_feedback
        else "[ZIVON STAGE: 10-transrepair] [STAGE_ID: 10c-transrepair]"
    )
    system = (
        f"{stage_marker} You are the Physics Curriculum Translator (Evon v3.3) in "
        "the Zivon content factory.\n"
        "RULES:\n"
        "- Translate ONLY the human-readable strings in `source_payload` into the "
        "target locale while preserving exact Physics accuracy.\n"
        "- Keep ALL Western Arabic numerals (0-9), SI units (m/s, m/s², m/s2, kg, N, "
        "J, W, Pa, Hz), variable symbols, and equations character-for-character "
        "identical to the source.\n"
        "- Output Retrieve/JSON object ONLY matching the unit's response schema. "
        "No prose, no markdown fences.\n"
    )
    prompt_obj: dict[str, Any] = {
        "task": "translate_physics_unit"
        if not repair_feedback
        else "repair_translated_physics_unit",
        "target_locale": {
            "code": loc_meta["code"],
            "autonym": loc_meta["autonym"],
            "english_name": loc_meta["english_name"],
            "script": loc_meta["script"],
            "script_rule": loc_meta["script_rule"],
        },
        "topic_context": {
            "chapter_title": chapter_title,
            "class_level": class_level,
            "unit_id": unit_id,
            "unit_type": unit_type,
        },
        "glossary_subset": glossary_subset,
        "neighbour_context": neighbour_ctx,
    }
    if unit_type in ("worked_example", "check"):
        prob_text = str(
            source_payload.get("problem") or source_payload.get("question") or ""
        )
        prompt_obj["immutable_numbers_in_problem"] = _NUMERAL_RE.findall(prob_text)
    prompt_obj["source_payload"] = source_payload
    if repair_feedback:
        prompt_obj["repair_feedback"] = repair_feedback

    return [
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": json.dumps(prompt_obj, indent=2, ensure_ascii=False),
        },
    ]


def translate_single_unit(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    locale: str,
    unit_id: str,
    unit_type: str,
    source_block_or_meta: dict[str, Any],
    glossary_subset: list[dict[str, Any]],
    neighbour_ctx: dict[str, str],
    *,
    chapter_title: str = "",
    sim_strings: dict[str, dict[str, str]] | None = None,
    round_tag_prefix: str = "init",
    repair_feedback: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Translate a single unit via LLMClient -> llm_manager (block-contract.md §5).

    Returns (source_payload, translated_payload, reassembled_unit).
    """
    del run_ctx
    source_payload = extract_translatable_payload(
        unit_id, unit_type, source_block_or_meta, sim_strings=sim_strings
    )
    schema, schema_name = schema_for_unit(unit_id, unit_type, source_block_or_meta)
    class_level = cfg.learner.get("class_level") or 9
    messages = build_translate_messages(
        locale=locale,
        chapter_title=chapter_title
        or str(source_block_or_meta.get("title", "Physics")),
        class_level=int(class_level),
        unit_id=unit_id,
        unit_type=unit_type,
        source_payload=source_payload,
        glossary_subset=glossary_subset,
        neighbour_ctx=neighbour_ctx,
        repair_feedback=repair_feedback,
    )

    def validate_invariants(candidate: dict[str, Any]) -> list[str]:
        errs = check_unit_deterministic_invariants(
            locale=locale,
            unit_id=unit_id,
            unit_type=unit_type,
            source_payload=source_payload,
            translated_payload=candidate,
            source_block_or_meta=source_block_or_meta,
            glossary_subset=glossary_subset,
        )
        if not errs:
            try:
                reassemble_translated_unit(
                    unit_id, unit_type, source_block_or_meta, candidate
                )
            except Exception as exc:  # noqa: BLE001 — surface reassembly error to validation retry
                errs.append(f"[reassembly] {exc}")
        return errs

    round_tag = (
        f"{locale}/{unit_id}"
        if round_tag_prefix == "init"
        else f"{locale}/{unit_id}/{round_tag_prefix}"
    )
    stage_id = STAGE_ID if round_tag_prefix == "init" else "10c-transrepair"

    # Use a translator-scoped shallow copy of LLMClient with max_tokens=4096
    # set on LLMConfig (per block-contract.md §1.2 & llm_manager/README.md §Configuration).
    translator_llm = copy.copy(llm)
    translator_llm._llm_config = dataclasses.replace(llm._llm_config, max_tokens=4096)

    translated_payload = translator_llm.call(
        stage_id=stage_id,
        messages=messages,
        schema=schema,
        schema_name=schema_name,
        extra_validator=validate_invariants,
        round_tag=round_tag,
    )
    reassembled = reassemble_translated_unit(
        unit_id, unit_type, source_block_or_meta, translated_payload
    )
    return source_payload, translated_payload, reassembled


def compute_tm_keys(
    unit_id: str,
    translatable_payload: dict[str, Any],
    target_locale: str,
    glossary_version: str,
    prompt_version: str,
) -> tuple[str, str]:
    """Compute canonical (source_content_sha256, tm_key) per SP2-TRANS §3.1."""
    del unit_id
    normalized = unicodedata.normalize(
        "NFC",
        json.dumps(
            translatable_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    source_content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    composite = (
        f"{source_content_sha256}:{target_locale}:{glossary_version}:{prompt_version}"
    )
    tm_key = hashlib.sha256(composite.encode("utf-8")).hexdigest()
    return source_content_sha256, tm_key


def checkpoint_path(run_ctx: RunContext, locale: str, unit_id: str) -> Path:
    return run_ctx.stage_dir(STAGE_ID) / "blocks" / locale / f"{unit_id}.json"


def tm_cache_path(cfg: Config, locale: str, tm_key: str) -> Path:
    cache_root = cfg.repo_path(cfg.paths["text_cache"]) / "tm"
    return cache_root / locale / tm_key[:2] / f"{tm_key}.json"


def write_checkpoint_atomic(path: Path, envelope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp_path, path)


def load_checkpoint(
    run_ctx: RunContext, locale: str, unit_id: str, expected_tm_key: str
) -> dict[str, Any] | None:
    path = checkpoint_path(run_ctx, locale, unit_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("tm_key") != expected_tm_key:
        return None
    if "translated_payload" not in data or "reassembled_block" not in data:
        return None
    return data


def load_tm_entry(
    cfg: Config,
    locale: str,
    tm_key: str,
    source_content_sha256: str | None = None,
) -> dict[str, Any] | None:
    """Lookup a verified entry in Tier 1 PVC cache (or Tier 2 DB store when present)."""
    try:
        from . import tm_store  # type: ignore[attr-defined]

        store = tm_store.get_tm_store(cfg)
        return store.lookup(
            locale=locale,
            tm_key=tm_key,
            source_content_sha256=source_content_sha256,
        )
    except ImportError:
        path = tm_cache_path(cfg, locale, tm_key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict) or data.get("tm_key") != tm_key:
            return None
        if data.get("review_status") not in ("machine_verified", "human_approved"):
            return None
        return data


def glossary_sha256(cfg: Config) -> str:
    gpath = cfg.repo_path(cfg.translation["glossary_path"])
    if not gpath.exists():
        return "no-glossary"
    return hashlib.sha256(gpath.read_bytes()).hexdigest()[:16]


def build_checkpoint_envelope(
    *,
    unit_id: str,
    unit_type: str,
    locale: str,
    source_content_sha256: str,
    tm_key: str,
    glossary_version: str,
    prompt_version: str,
    model_id: str,
    source_payload: dict[str, Any],
    translated_payload: dict[str, Any],
    reassembled_block: dict[str, Any],
    translation_source: str = "machine",
    review_status: str = "draft",
) -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "unit_type": unit_type,
        "locale": locale,
        "source_content_sha256": source_content_sha256,
        "tm_key": tm_key,
        "glossary_version": glossary_version,
        "prompt_version": prompt_version,
        "model_id": model_id,
        "translation_source": translation_source,
        "review_status": review_status,
        "source_payload": source_payload,
        "translated_payload": translated_payload,
        "reassembled_block": reassembled_block,
        "created_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _read_page_js(run_ctx: RunContext, render_out: dict[str, Any] | None) -> str:
    if render_out and render_out.get("topic_dir"):
        js_path = Path(render_out["topic_dir"]) / "page.js"
        if js_path.exists():
            return js_path.read_text(encoding="utf-8")
    if (run_ctx.stage_dir("05-interactive") / "output.json").exists():
        interactive = run_ctx.load_stage_output("05-interactive")
        return "\n\n".join(
            out["files"].get("page.js", "")
            for out in interactive.values()
            if isinstance(out, dict) and out.get("files", {}).get("page.js")
        )
    return ""


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    render_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute 10a-translate across all configured target_locales (SP2-TRANS §1.2-1.3)."""
    del ground_truth
    glossary_data = load_glossary(cfg)
    glossary_version = str(glossary_data.get("glossary_version", "1.0.0"))
    prompt_version = str(cfg.translation["prompt_version"])
    max_neighbour = int(cfg.translation["max_chars_neighbour_context"]) // 2
    page_js = _read_page_js(run_ctx, render_out)
    extracted_sim_strings = extract_sim_strings_from_js(page_js)
    chapter_title = str(lesson.get("title", "Physics"))

    ordered_blocks: list[dict[str, Any]] = list(blocks["blocks"])
    worklist: list[tuple[str, str, dict[str, Any]]] = [
        ("b-00-meta", "meta", lesson),
        *[(str(b["id"]), str(b["type"]), b) for b in ordered_blocks],
    ]

    locales_out: dict[str, Any] = {}
    for locale in cfg.translation["target_locales"]:
        t_locale_start = time.monotonic()
        resumed_in_run = 0
        tm_hits = 0
        model_calls = 0
        translated_meta: dict[str, Any] = copy.deepcopy(lesson)
        translated_sim_strings: dict[str, dict[str, str]] = copy.deepcopy(
            extracted_sim_strings
        )
        translated_blocks_list: list[dict[str, Any]] = []
        unit_status: dict[str, str] = {}
        prev_translated_excerpt = ""

        for idx, (unit_id, unit_type, src_unit) in enumerate(worklist):
            next_excerpt = (
                _unit_excerpt(worklist[idx + 1][1], worklist[idx + 1][2], max_neighbour)
                if idx + 1 < len(worklist)
                else ""
            )
            neighbour_ctx = {
                "previous_unit_translated_excerpt": prev_translated_excerpt,
                "next_unit_source_excerpt": next_excerpt,
            }
            src_payload = extract_translatable_payload(
                unit_id,
                unit_type,
                src_unit,
                sim_strings=extracted_sim_strings if unit_id == "b-00-meta" else None,
            )
            source_sha, tm_key = compute_tm_keys(
                unit_id, src_payload, locale, glossary_version, prompt_version
            )

            # 1. Check In-Run Checkpoint (runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json)
            ckpt = load_checkpoint(run_ctx, locale, unit_id, tm_key)
            if ckpt is not None:
                resumed_in_run += 1
                unit_status[unit_id] = "resumed_in_run"
                reassembled = ckpt["reassembled_block"]
                tr_payload = ckpt["translated_payload"]
            else:
                # 2. Check Cross-Run Translation Memory (sources/cache/tm/ or DB)
                tm_entry = load_tm_entry(
                    cfg, locale, tm_key, source_content_sha256=source_sha
                )
                if tm_entry is not None:
                    tm_hits += 1
                    unit_status[unit_id] = "tm_hit"
                    tr_payload = tm_entry["translated_payload"]
                    reassembled = reassemble_translated_unit(
                        unit_id, unit_type, src_unit, tr_payload
                    )
                    envelope = build_checkpoint_envelope(
                        unit_id=unit_id,
                        unit_type=unit_type,
                        locale=locale,
                        source_content_sha256=source_sha,
                        tm_key=tm_key,
                        glossary_version=glossary_version,
                        prompt_version=prompt_version,
                        model_id=str(tm_entry.get("model_id", cfg.server["model"])),
                        source_payload=src_payload,
                        translated_payload=tr_payload,
                        reassembled_block=reassembled,
                        translation_source=str(
                            tm_entry.get("translation_source", "machine")
                        ),
                        review_status=str(
                            tm_entry.get("review_status", "machine_verified")
                        ),
                    )
                    write_checkpoint_atomic(
                        checkpoint_path(run_ctx, locale, unit_id), envelope
                    )
                else:
                    # 3. Call LLMClient -> llm_manager (1 unit per call)
                    text_blob = " ".join(_collect_strings(src_payload))
                    glossary_subset = select_glossary_subset(
                        glossary_data,
                        locale,
                        text_blob,
                        chapter_glossary=lesson.get("glossary"),
                    )
                    t_call = time.monotonic()
                    with context_scope(
                        request_id=f"{run_ctx.run_id}-{locale}-{unit_id}"
                    ):
                        try:
                            src_payload, tr_payload, reassembled = (
                                translate_single_unit(
                                    cfg,
                                    run_ctx,
                                    llm,
                                    locale,
                                    unit_id,
                                    unit_type,
                                    src_unit,
                                    glossary_subset,
                                    neighbour_ctx,
                                    chapter_title=chapter_title,
                                    sim_strings=extracted_sim_strings
                                    if unit_id == "b-00-meta"
                                    else None,
                                )
                            )
                            log_event(
                                "translator.translate.ok",
                                {"src_lang": "en", "tgt_lang": locale},
                                severity=Severity.INFO,
                                latency_ms=int((time.monotonic() - t_call) * 1000),
                                run_id=run_ctx.run_id,
                                stage=STAGE_ID,
                            )
                        except FactoryError as exc:
                            log_event(
                                "translator.translate.fail",
                                {
                                    "reason_code": type(exc).__name__,
                                    "attempts": cfg.server["max_attempts"],
                                },
                                severity=Severity.ERROR,
                                error_class=ErrorClass.transport_error,
                                run_id=run_ctx.run_id,
                                stage=STAGE_ID,
                            )
                            raise

                    model_calls += 1
                    unit_status[unit_id] = "translated"
                    envelope = build_checkpoint_envelope(
                        unit_id=unit_id,
                        unit_type=unit_type,
                        locale=locale,
                        source_content_sha256=source_sha,
                        tm_key=tm_key,
                        glossary_version=glossary_version,
                        prompt_version=prompt_version,
                        model_id=str(cfg.server["model"]),
                        source_payload=src_payload,
                        translated_payload=tr_payload,
                        reassembled_block=reassembled,
                        translation_source="machine",
                        review_status="draft",
                    )
                    write_checkpoint_atomic(
                        checkpoint_path(run_ctx, locale, unit_id), envelope
                    )

            if unit_id == "b-00-meta":
                translated_meta = reassembled
                translated_sim_strings = dict(tr_payload.get("sim_strings", {}))
            else:
                translated_blocks_list.append(reassembled)
            prev_translated_excerpt = _unit_excerpt(
                unit_type, reassembled, max_neighbour
            )

        # Aggregate token usage from calls_ledger for this locale
        prompt_tokens = 0
        completion_tokens = 0
        ledger_path = run_ctx.dir / "calls_ledger.jsonl"
        if ledger_path.exists():
            for line in ledger_path.read_text(encoding="utf-8").splitlines():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get("stage") == STAGE_ID and str(
                    row.get("round_tag") or ""
                ).startswith(f"{locale}/"):
                    prompt_tokens += int(row.get("prompt_tokens") or 0)
                    completion_tokens += int(row.get("completion_tokens") or 0)

        locales_out[locale] = {
            "meta": translated_meta,
            "blocks": {"blocks": translated_blocks_list},
            "sim_strings": translated_sim_strings,
            "unit_status": unit_status,
            "fallback_blocks": [],
            "stats": {
                "units_total": len(worklist),
                "resumed_in_run": resumed_in_run,
                "tm_hits": tm_hits,
                "model_calls": model_calls,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "latency_s": round(time.monotonic() - t_locale_start, 2),
                "gnani_credits_used": 0,
            },
        }

    return {"locales": locales_out}
