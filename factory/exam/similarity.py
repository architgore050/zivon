"""The generated-item similarity gate (`cbse-exam-content.md` §7.4).

`DEC-COMP-006` requires generated items to be source-blind and similarity-gated:
normalise, compute 8-word shingles, block when any generated item shares an
8-gram with a stored source item or when shingle Jaccard against the nearest
source item exceeds 0.20.

In `blueprint_only` mode there is no stored source text at all, so the corpus is
empty and the gate is **vacuously clear**. That is recorded honestly: the
similarity record carries `corpus_size: 0` and `verdict: "vacuously_clear"`, and
the publish manifest reports `source_corpus_items: 0`. The gate exists and is
exercised by tests against a synthetic corpus; it is not a claim that a real
comparison happened. The thresholds are a copying-prevention control, not legal
clearance (stated in the decision log and repeated in `docs/content-factory/
exam.md`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

_WORD_RE = re.compile(r"[a-z\u0900-\u097f0-9#]+")
_SPACE_RE = re.compile(r"\s+")
_DIGIT_RE = re.compile(r"\d")


def normalize(text: str) -> str:
    """Lowercase, punctuation-free, whitespace-collapsed, digits mapped to `#`."""
    lowered = _DIGIT_RE.sub("#", str(text).lower())
    words = _WORD_RE.findall(lowered)
    return _SPACE_RE.sub(" ", " ".join(words)).strip()


def shingles(text: str, n: int = 8) -> set[tuple[str, ...]]:
    words = normalize(text).split()
    if len(words) < n:
        return {tuple(words)} if words else set()
    return {tuple(words[i : i + n]) for i in range(len(words) - n + 1)}


def jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 0.0
    union = left | right
    return len(left & right) / len(union)


def check_text(
    text: str,
    corpus: Sequence[Mapping[str, Any]],
    *,
    ngram: int = 8,
    max_overlap: float = 0.2,
    checked_at: str,
) -> dict[str, Any]:
    """Compare one item's text against a source corpus and return its record.

    `corpus` entries are `{"item_id": str, "text": str}`. An empty corpus is a
    vacuous check, never a silent pass: the verdict says so.
    """
    item_shingles = shingles(text, ngram)
    if not corpus:
        return {
            "ngram": ngram,
            "corpus_size": 0,
            "max_ngram_overlap": 0.0,
            "max_jaccard": 0.0,
            "nearest_source_item_id": None,
            "shared_ngram": False,
            "checked_at": checked_at,
            "verdict": "vacuously_clear",
        }
    worst_overlap = 0.0
    worst_jaccard = 0.0
    nearest: str | None = None
    shared_any = False
    for entry in corpus:
        source_shingles = shingles(str(entry.get("text") or ""), ngram)
        if not source_shingles:
            continue
        shared = item_shingles & source_shingles
        if shared:
            shared_any = True
        overlap = len(shared) / max(1, len(item_shingles))
        score = jaccard(item_shingles, source_shingles)
        if score > worst_jaccard or (
            score == worst_jaccard and overlap > worst_overlap
        ):
            worst_jaccard = score
            worst_overlap = overlap
            nearest = str(entry.get("item_id"))
    blocked = shared_any or worst_jaccard > max_overlap
    return {
        "ngram": ngram,
        "corpus_size": len(corpus),
        "max_ngram_overlap": round(worst_overlap, 4),
        "max_jaccard": round(worst_jaccard, 4),
        "nearest_source_item_id": nearest,
        "shared_ngram": shared_any,
        "checked_at": checked_at,
        "verdict": "blocked" if blocked else "clear",
    }


__all__ = ["check_text", "jaccard", "normalize", "shingles"]
