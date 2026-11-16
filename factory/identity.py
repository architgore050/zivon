"""Stable content identity for generated artifacts (P1, 2026-11-15).

One deterministic place that answers "what is this content called?":

- ``chapter_id`` / ``lesson_id`` - the chapter owns exactly one lesson, so both
  ids are the same stable slug-derived key (``class-9-motion``). The page's
  directory slug, the manifest and every downstream product layer key off it.
- ``concept_id`` - the section-scoped concept key for a block or a section
  (``class-9-motion-sec-03``). It is a stable GROUPING key, not a claim that a
  curated syllabus concept exists: the concept graph and its curated ids are
  P2's ``concept-tag`` stage, which may re-map these keys. Until then this key
  is what every block carries so no block is an orphan.
- ``chapter_title`` repair - the "Grade" defect class. NCERT PDFs mix page
  furniture into the opener's text layer ("Grade 7", "Curiosity",
  "Chapter-04.indd 48"), and the pre-fix title picker published one live page
  with ``chapter.title = "Grade"``. A title that does not name a chapter is
  never published: it is repaired from the located line or the operator's
  query, and if neither is usable the renderer refuses loudly.

Nothing here calls a model, reads a clock, or stores state - the same inputs
always produce the same ids and the same ``content_hash``.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

SUBJECT = "physics"

# Words that describe the BOOK or the PAGE, never the chapter. A "title" that
# is only one of these (optionally followed by a number) is furniture.
_NON_TITLE_WORDS = frozenset(
    {
        "activity",
        "chapter",
        "class",
        "contents",
        "curiosity",
        "exploration",
        "exercise",
        "example",
        "grade",
        "index",
        "introduction",
        "part",
        "physics",
        "preface",
        "science",
        "summary",
        "textbook",
        "unit",
    }
)

# PDF print furniture that survives text extraction ("Chapter-04.indd 48").
_FURNITURE_RE = re.compile(
    r"(?i)^(?:chapter-?\d+\.indd|fig\.?\s*\d|table\s*\d|page\s*\d)"
)

_MAX_TITLE_WORDS = 14


def collapse_ws(text: Any) -> str:
    """Collapse every whitespace run to one space (PDF extraction inserts
    newlines mid-title)."""
    return " ".join(str(text or "").split())


def is_usable_chapter_title(title: Any) -> bool:
    """True when ``title`` names a chapter rather than a page-furniture line."""
    text = collapse_ws(title)
    if len(text) < 3 or not any(c.isalpha() for c in text):
        return False
    words = text.split()
    if len(words) > _MAX_TITLE_WORDS:
        return False
    if _FURNITURE_RE.match(text):
        return False
    if text.casefold() in _NON_TITLE_WORDS:
        return False
    # "Grade 7", "Class 9", "Science 134", "Chapter 4"
    if (
        len(words) == 2
        and words[0].casefold() in _NON_TITLE_WORDS
        and words[1].isdigit()
    ):
        return False
    # A bare number ("4", "134") is a page number.
    return not all(w.isdigit() for w in words)


def repair_chapter_title(
    title: Any,
    *,
    matched_line: Any = None,
    query: Any = None,
) -> str | None:
    """The chapter title to publish, or ``None`` when nothing usable is left.

    Precedence is the located chapter title, then the line the locator matched,
    then the operator's own query - the honest chain of what we actually know.
    A caller that gets ``None`` must fail loudly instead of publishing a
    placeholder: an invented title is worse than a failed render.
    """
    for candidate in (title, matched_line, query):
        if is_usable_chapter_title(candidate):
            return collapse_ws(candidate)
    return None


def chapter_id(class_level: int | str, slug: str) -> str:
    """``class-9-motion`` - the stable chapter/lesson key (see module docstring)."""
    return f"class-{class_level}-{slug}"


def lesson_id(class_level: int | str, slug: str) -> str:
    """A chapter owns exactly one lesson page, so the ids are the same value."""
    return chapter_id(class_level, slug)


def concept_id(chapter_key: str, section_id: str) -> str:
    """``class-9-motion-sec-03`` - the section-scoped concept key."""
    return f"{chapter_key}-{section_id}"


def canonical_json(payload: Any) -> str:
    """Stable serialisation for hashing (sorted keys, no whitespace drift)."""
    return json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    )


def content_hash(
    chapter_key: str,
    lesson: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> str:
    """Identity of the TEACHING CONTENT, independent of render-time chrome.

    Two renders of the same draft produce the same hash; any change to a
    lesson section, objective, glossary entry, block spec or citation changes
    it. Used to key caches (narration, i18n) and to prove a re-render shipped
    the same content.
    """
    payload = {
        "chapter_id": chapter_key,
        "lesson": lesson,
        "blocks": blocks,
    }
    digest = hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def pipeline_version() -> str:
    """The stage-contract version stamped into every manifest.

    Deferred import: ``factory/stages.py`` imports the renderer, so the version
    constant can only be read at call time. One source of truth - the constant
    stays in ``stages.py`` next to the stage graph it describes.
    """
    from .stages import PIPELINE_VERSION

    return PIPELINE_VERSION
