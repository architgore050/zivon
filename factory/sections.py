"""Deterministic block -> section ownership for a rendered lesson page.

The renderer wraps ``lesson.sections`` in ``<section class="zn-section">``
elements that own their blocks, and writes the same mapping into
``manifest.json`` so the product layers never re-parse HTML. Two sources feed
that mapping:

1. **Authored** - a block may name its section (``section_id``, additive block
   metadata). Fresh runs author it from the generation prompt, so this is the
   normal path and it is exactly as good as the model's own lesson plan.
2. **Derived** - older drafts (and any block the author left unattributed)
   carry no ``section_id``. The lesson prose in ``lesson.sections[].paragraphs``
   is the same prose the text blocks render, so a block's words identify the
   section it teaches. The match is scored by token containment and then made
   monotone: a page reads in order, so a block may only move FORWARD to a later
   section, never back. A block whose words match nothing inherits the section
   that is open where it sits (checks, examples and visuals follow the prose
   they exercise).

Every block gets a section id whenever the lesson has any sections, which is
what "a section owns exactly its blocks" needs. The resolution is pure: same
draft in, same mapping out - no model, no clock, no randomness.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

SECTION_ID_RE = re.compile(r"^sec-[0-9]{2}$")

# Containment floor for a derived match. Measured on the real run artifacts in
# runs/: true section prose scores 0.38-1.00, incidental word overlap 0.07-0.36.
# Raising this risks leaving real prose unattributed; lowering it lets a single
# shared word ("force") drag a block into the wrong section.
MIN_DERIVED_SCORE = 0.37

_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)
_STOPWORDS = frozenset(
    [
        "the",
        "a",
        "an",
        "and",
        "or",
        "but",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "with",
        "without",
        "from",
        "into",
        "onto",
        "over",
        "under",
        "for",
        "of",
        "to",
        "in",
        "on",
        "at",
        "by",
        "as",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "it",
        "its",
        "you",
        "your",
        "we",
        "our",
        "they",
        "their",
        "he",
        "she",
        "his",
        "her",
        "not",
        "no",
        "so",
        "such",
        "can",
        "may",
        "might",
        "will",
        "would",
        "should",
        "could",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "there",
        "here",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "when",
        "where",
        "why",
        "how",
        "all",
        "any",
        "each",
        "every",
        "more",
        "most",
        "other",
        "some",
        "only",
        "own",
        "same",
        "too",
        "very",
        "just",
        "also",
        "about",
        "after",
        "before",
        "between",
        "during",
        "through",
        "above",
        "below",
        "up",
        "down",
        "out",
        "off",
        "again",
        "further",
        "once",
        "both",
        "few",
        "many",
        "much",
        "one",
        "two",
        "three",
        "first",
    ]
)


@dataclass(frozen=True)
class SectionOwnership:
    """The block -> section map plus how it was obtained (for honest logs)."""

    by_block: dict[str, str]
    authored: int
    derived: int


def _tokens(text: Any) -> set[str]:
    words = {w.casefold() for w in _WORD_RE.findall(str(text or ""))}
    return {w for w in words if len(w) > 2 and w not in _STOPWORDS}


def _spec_text(block: dict[str, Any]) -> str:
    """Every human-readable string a block carries, for prose matching."""
    spec = block.get("spec") or {}
    parts: list[str] = []
    for key in ("paragraphs", "problem", "question", "title", "description"):
        value = spec.get(key)
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, list):
            parts.extend(str(v) for v in value)
    for key in ("steps", "options"):
        for item in spec.get(key) or []:
            if isinstance(item, dict):
                parts.extend(str(v) for v in item.values() if isinstance(v, str))
            else:
                parts.append(str(item))
    return " ".join(parts)


def _section_scores(
    block: dict[str, Any], section_tokens: list[set[str]]
) -> list[float]:
    block_tokens = _tokens(_spec_text(block))
    if not block_tokens:
        return [0.0] * len(section_tokens)
    return [
        (len(block_tokens & tokens) / len(tokens)) if tokens else 0.0
        for tokens in section_tokens
    ]


def resolve_sections(
    lesson: dict[str, Any], blocks: list[dict[str, Any]]
) -> SectionOwnership:
    """Assign every block to its lesson section (see module docstring)."""
    section_ids = [
        str(s["id"])
        for s in lesson.get("sections", [])
        if SECTION_ID_RE.match(str(s.get("id", "")))
    ]
    if not section_ids:
        return SectionOwnership(by_block={}, authored=0, derived=0)
    index_of = {sid: i for i, sid in enumerate(section_ids)}
    section_tokens = [
        _tokens(" ".join(str(p) for p in s.get("paragraphs", [])))
        for s in lesson.get("sections", [])
        if SECTION_ID_RE.match(str(s.get("id", "")))
    ]

    by_block: dict[str, str] = {}
    authored = derived = 0
    current = 0
    for block in blocks:
        block_id = str(block["id"])
        declared = str(block.get("section_id") or "")
        if declared in index_of:
            # Explicit authoring wins outright (issue #118, 2026-11-27): a
            # teaching block a repair round APPENDS with a declared section is
            # rendered and manifested under THAT section - the monotone rule
            # below exists for DERIVED assignments (prose matching must not
            # jump back), never to override the author's own declaration.
            by_block[block_id] = declared
            authored += 1
            current = max(current, index_of[declared])
            continue
        scores = _section_scores(block, section_tokens)
        target = max(range(len(scores)), key=lambda i: scores[i])
        score = scores[target]
        if score < MIN_DERIVED_SCORE:
            target, score = current, 0.0
        else:
            derived += 1
        # A page reads in order: forward only. A block that matches an EARLIER
        # section stays where the reader already is (clamped, still covered).
        current = max(target, current)
        by_block[block_id] = section_ids[current]
    return SectionOwnership(by_block=by_block, authored=authored, derived=derived)


def apply_metadata(
    blocks: list[dict[str, Any]],
    ownership: SectionOwnership,
    chapter_key: str,
) -> list[dict[str, Any]]:
    """Return copies of ``blocks`` carrying ``section_id`` + ``concept_id``.

    Additive block metadata (``docs/content-factory/blocks-schema.md``): the
    renderer never mutates the stage artifact it was handed.
    """
    enriched: list[dict[str, Any]] = []
    for block in blocks:
        out = dict(block)
        section = ownership.by_block.get(str(block["id"]))
        if section is not None:
            out["section_id"] = section
            out["concept_id"] = f"{chapter_key}-{section}"
        enriched.append(out)
    return enriched


def group_by_section(
    lesson: dict[str, Any], blocks: list[dict[str, Any]]
) -> list[tuple[str, list[dict[str, Any]]]]:
    """Ordered ``(section_id, blocks)`` groups, skipping empty sections."""
    order = [
        str(s["id"])
        for s in lesson.get("sections", [])
        if SECTION_ID_RE.match(str(s.get("id", "")))
    ]
    grouped: dict[str, list[dict[str, Any]]] = {sid: [] for sid in order}
    loose: list[dict[str, Any]] = []
    for block in blocks:
        section = str(block.get("section_id") or "")
        if section in grouped:
            grouped[section].append(block)
        else:
            loose.append(block)
    out = [(sid, grouped[sid]) for sid in order if grouped[sid]]
    # Defensive: never drop a block, even from a lesson whose sections the
    # schema rejected. The caller renders loose blocks without a wrapper.
    if loose:
        out.append(("", loose))
    return out
