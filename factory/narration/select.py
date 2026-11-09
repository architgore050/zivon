"""Speakable-block selection: which lesson content gets narrated, and as what
spoken form.

This module is the CODE form of the gap-register GAP-015 mini-spec (the
binding contract for EX8-NARRATION):

    text            -> full prose (every paragraph)
    animation/simulation -> spec.title + spec.description + readout strings
                       from page.js (never JS code)
    diagram         -> svg_texts only (never the SVG markup, never the caption
                       - captions are "on request only" per the features
                       states row; English v1 blocks carry no svg_texts, so
                       diagrams are simply not narrated until the translation
                       payload (CP-TRN-002) introduces them)
    check           -> question + options; answers are NEVER read aloud until
                       revealed (no answer / explanation / expected_understanding)
    metadata        -> b-00-meta: lesson title + objectives
    worked_example  -> problem + steps + answer (the features.md states row
                       lists worked_example as speakable; the full worked
                       solution IS the teaching content and is fully visible
                       on the page - the check rule about unrevealed answers
                       does not apply here)
    reveal          -> not speakable (progressive-disclosure content; the
                       mini-spec lists no speakable fields for it)

All other spec fields are excluded (GAP-015: "All other spec fields are
excluded") - notably simulation controls/labels and every citation.

Nothing in this module performs I/O or calls a model: pure selection over the
02-generate block payloads plus the 05-interactive readout strings.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

# The one expressive tag narration uses, and why (AGENTS.md 13-tag catalog,
# Timbre v3.0 only): a narrated physics paragraph does not laugh, whisper or
# shout, but a pause between paragraphs/steps/options is where a human reader
# would breathe. Tags bill as characters, so the budget (budget.py) counts
# the assembled spoken text INCLUDING tags.
PAUSE_TAG = "<pauses>"

# Unit pronunciation rules (features.md behaviour 5: "block text with
# unit-pronunciation rules", principle P7 "units spoken in full"). Ordered:
# longer patterns first so m/s2 is never eaten by m/s. SC-06 (the translation
# spec's spoken-form proposal) supersedes this table when it lands; until
# then this is the fallback the features card names.
_UNIT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bm/s2\b"), "metres per second squared"),
    (re.compile(r"m/s2"), "metres per second squared"),
    (re.compile(r"m/s\u00b2"), "metres per second squared"),
    (re.compile(r"\bm/s\b"), "metres per second"),
    (re.compile(r"\bkm/h\b"), "kilometres per hour"),
    (re.compile(r"\bkm/s\b"), "kilometres per second"),
    (re.compile(r"\bcm/s\b"), "centimetres per second"),
    (re.compile(r"\bkg/m3\b"), "kilograms per cubic metre"),
    (re.compile(r"kg/m\u00b3"), "kilograms per cubic metre"),
    (re.compile(r"\bN/kg\b"), "newtons per kilogram"),
    (re.compile(r"\u00b0C"), "degrees Celsius"),
    (re.compile(r"\u00b0F"), "degrees Fahrenheit"),
)

# page.js readout strings (CP-TRN-003 pattern): ctx.t_str("key", "fallback").
_T_STR_RE = re.compile(r'ctx\.t_str\(\s*"(?:[^"\\]|\\.)*"\s*,\s*"((?:[^"\\]|\\.)*)"')
# A readout that is a standalone math/unit token (F, 10 N, m/s, v (m/s)) is
# canvas chrome, not speakable prose - the same exclusion CP-TRN-002 applies
# to svg_texts. Speakable prose always carries an alphabetic run of >= 3
# characters (Latin or Devanagari); unit tokens never do.
_SPEAKABLE_RE = re.compile(r"[A-Za-z\u0900-\u097F]{3,}")


@dataclass(frozen=True)
class NarrationUnit:
    """One speakable unit: a block (or the lesson envelope) plus its spoken
    parts, in page order."""

    block_id: str  # "b-00-meta" or "b-01".."b-45"
    kind: str  # meta | text | worked_example | check | simulation | animation | diagram
    parts: tuple[str, ...]

    @property
    def chars(self) -> int:
        """Billable character estimate: the assembled spoken form, tags
        included (tags bill as characters per the verified Timbre v3.0
        catalog). The budget guard estimates from this."""
        return len(spoken_text(self))


def spoken_text(unit: NarrationUnit) -> str:
    """Assemble the unit's spoken form: unit-pronunciation rules applied per
    part, parts joined by the <pauses> tag.

    This is the features.md "spoken form (SC-06 when available; else block
    text with unit-pronunciation rules)" fallback path - SC-06 supersedes it
    once the translation spec's spoken-form schema lands.
    """
    cleaned = [_speak_part(part) for part in unit.parts]
    cleaned = [part for part in cleaned if part]
    return f" {PAUSE_TAG} ".join(cleaned)


def _speak_part(part: str) -> str:
    text = re.sub(r"\s+", " ", str(part)).strip()
    for pattern, spoken in _UNIT_RULES:
        text = pattern.sub(spoken, text)
    return text


def speakable_units(
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    interactive: dict[str, Any] | None = None,
) -> list[NarrationUnit]:
    """Ordered speakable units for one lesson: b-00-meta first (title +
    objectives), then every content block that has something speakable, in
    page order. Blocks with nothing speakable (diagrams without svg_texts,
    reveal blocks, empty prose) are simply absent - the availability flag
    for them is false by construction."""
    units: list[NarrationUnit] = []
    meta_parts = _meta_parts(lesson)
    if meta_parts:
        units.append(NarrationUnit("b-00-meta", "meta", tuple(meta_parts)))
    interactive = interactive or {}
    for block in blocks.get("blocks", []):
        parts = _block_parts(block, interactive.get(block.get("id"), {}))
        if parts:
            units.append(
                NarrationUnit(str(block["id"]), str(block["type"]), tuple(parts))
            )
    return units


def _meta_parts(lesson: dict[str, Any]) -> list[str]:
    """b-00-meta (GAP-015: metadata -> title + objectives)."""
    parts: list[str] = []
    title = str(lesson.get("title", "")).strip()
    if title:
        parts.append(title)
    for objective in lesson.get("objectives", []):
        text = str(objective).strip()
        if text:
            parts.append(text)
    return parts


def _block_parts(block: dict[str, Any], interactive_out: dict[str, Any]) -> list[str]:
    """GAP-015 per-type extraction. Returns [] when the block has nothing
    speakable."""
    btype, spec = block.get("type"), block.get("spec", {})
    if btype == "text":
        return [str(p).strip() for p in spec.get("paragraphs", []) if str(p).strip()]
    if btype == "worked_example":
        return _worked_example_parts(spec)
    if btype == "check":
        return _check_parts(spec)
    if btype in ("simulation", "animation"):
        return _simulation_parts(spec, interactive_out)
    if btype == "diagram":
        # svg_texts ONLY (the CP-TRN-002 payload shape: [{id, source}, ...]).
        # The caption and the SVG markup are never spoken.
        return [
            str(t.get("source", "")).strip()
            for t in spec.get("svg_texts", [])
            if str(t.get("source", "")).strip()
        ]
    # reveal and any future type: not speakable until GAP-015 says so.
    return []


def _worked_example_parts(spec: dict[str, Any]) -> list[str]:
    parts = ["Worked example"]
    problem = str(spec.get("problem", "")).strip()
    if problem:
        parts.append(problem)
    for step in spec.get("steps", []):
        title = str(step.get("title", "")).strip()
        detail = str(step.get("detail", "")).strip()
        if title:
            parts.append(title)
        if detail:
            parts.append(detail)
    answer = str(spec.get("answer", "")).strip()
    if answer:
        parts.append(f"The answer is: {answer}")
    return parts


def _check_parts(spec: dict[str, Any]) -> list[str]:
    """question + options; the answer, explanation and expected_understanding
    are excluded (nothing is read aloud until revealed - GAP-015)."""
    parts: list[str] = []
    question = str(spec.get("question", "")).strip()
    if question:
        parts.append(question)
    for option in spec.get("options", []):
        text = str(option).strip()
        if text:
            parts.append(text)
    return parts


def _simulation_parts(
    spec: dict[str, Any], interactive_out: dict[str, Any]
) -> list[str]:
    """title + description + page.js readout strings (never JS code). The
    readouts come from the 05-interactive output via the CP-TRN-003
    ctx.t_str("key", "fallback") pattern; pages that predate it simply have
    none (sim_strings defaults to {})."""
    parts: list[str] = []
    for field in ("title", "description"):
        text = str(spec.get(field, "")).strip()
        if text:
            parts.append(text)
    page_js = interactive_out.get("files", {}).get("page.js", "")
    for fallback in _T_STR_RE.findall(page_js):
        # Unescape the JSON string literal properly (\" \\ \n \uXXXX):
        # unicode_escape would mangle any non-ASCII fallback (Hindi readouts
        # would arrive as mojibake). A malformed escape skips the readout -
        # a corrupt canvas string never becomes narration.
        try:
            text = json.loads(f'"{fallback}"')
        except json.JSONDecodeError:
            continue
        text = text.strip()
        if text and _SPEAKABLE_RE.search(text):
            parts.append(text)
    return parts
