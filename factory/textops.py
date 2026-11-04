"""Text utilities shared by ingest/locate: chunking, normalisation, matching."""

from __future__ import annotations

import re


def normalize_title(text: str) -> str:
    """Normalise a chapter title for exact matching: lowercase, alphanumeric only."""
    return re.sub(r"[^a-z0-9]+", "", text.lower())


def titles_equivalent(a: str, b: str) -> bool:
    """Exact-match rule for chapter titles after normalisation. The user's
    chapter name must be contained in the document's title or equal it, so
    'Motion' matches 'Motion' and 'Motion and Measuring' style variants still
    require an explicit substring hit."""
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return False
    return na == nb or na in nb


def clean_pdf_text(text: str) -> str:
    """Normalise whitespace, decode symbol-font runs, and drop page furniture
    that breaks matching.

    Symbol fonts: NCERT cover/section pages use custom-encoded fonts whose glyphs
    arrive as private-use codepoints U+F0XX where XX is the ASCII code
    (e.g. \\uf050\\uf041\\uf052\\uf054 = "PART"; caught live on the physics-11
    prelims, 2026-11-02). Printable-range runs are decoded back to ASCII so
    matching and class-evidence checks see real text; remaining private-use
    glyphs (non-ASCII dingbats) are dropped as noise."""
    text = re.sub("[\uf020-\uf07e]", lambda m: chr(ord(m.group()) - 0xF000), text)
    text = re.sub("[\uf000-\uf01f\uf07f-\uf0ff]", "", text)
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    """Fixed-size character chunks with overlap. Deterministic, no semantics."""
    if chunk_chars <= overlap:
        raise ValueError("chunk_chars must be greater than overlap")
    text = text.strip()
    if not text:
        return []
    chunks: list[str] = []
    start = 0
    step = chunk_chars - overlap
    while start < len(text):
        end = min(start + chunk_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start += step
    return chunks
