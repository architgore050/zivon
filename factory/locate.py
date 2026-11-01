"""Stage 01-locate: find the requested chapter and build the cited source pack.

Two searches, per the founder's spec:
1. EXACT search in NCERT: every cached NCERT chapter file's opening pages are
   matched against the user's chapter name (normalised title equivalence).
   Ambiguity is a hard error that lists the candidates; `--class` resolves it.
2. VECTOR search over the other PDFs' index: sentence-transformers embeddings
   of overlapping chunks from every OTHER book (alternates first, then other
   NCERT books), ranked by cosine similarity to the chapter title + opening
   text.

The output source pack is what the synthesizer is allowed to know. Anything
not in it cannot enter the lesson - that is the traceability guarantee.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import retrieval as _retrieval  # module access so tests can swap the embedder
from .artifacts import RunContext
from .config import Config
from .errors import SourceError
from .textops import normalize_title, titles_equivalent

STAGE_ID = "01-locate"


def run(
    cfg: Config, run_ctx: RunContext, chapter: str, class_filter: int | None
) -> dict[str, Any]:
    books: list[dict[str, Any]] = run_ctx.load_stage_output("00-ingest")["books"]
    if class_filter is not None:
        books = [b for b in books if b["class"] == class_filter]
        if not books:
            raise SourceError(STAGE_ID, f"no catalog books for class {class_filter}")

    ncert_books = [b for b in books if b["is_ncert"]]
    other_books = [b for b in books if not b["is_ncert"]]
    if not ncert_books:
        raise SourceError(STAGE_ID, "no NCERT books available for the requested class")

    # ---- 1. exact chapter search in NCERT --------------------------------
    match = _match_ncert_chapter(cfg, chapter, ncert_books)

    pages = _load_pages(cfg, match)
    if not pages:
        raise SourceError(
            STAGE_ID, f"page cache missing for {match['file']}; re-run stage 00"
        )
    ncert_text = "\n\n".join(f"[page {p['page']}]\n{p['text']}" for p in pages)
    cap = cfg.limits["max_chars_ncert_to_model"]
    truncated = False
    if len(ncert_text) > cap:
        ncert_text = ncert_text[:cap].rsplit("\n\n", 1)[0]
        truncated = True

    # ---- 2. vector search over the other books ----------------------------
    embedder = _retrieval.get_embedder(cfg)
    supplements: list[dict[str, Any]] = []
    for book in other_books + [b for b in ncert_books if b["id"] != match["book_id"]]:
        for ch in book["chapters"]:
            ch_pages = _load_pages(cfg, ch)
            if not ch_pages:
                continue
            chunks = _retrieval.chunks_for_book(cfg, book["id"], ch_pages)
            if not chunks:
                continue
            matrix = _retrieval.embed_chunks_cached(cfg, book["id"], chunks)
            query = f"{match['title']}\n{ncert_text[:800]}"
            supplements.extend(
                _retrieval.top_k_chunks(
                    embedder, query, chunks, matrix, cfg.retrieval["top_k"]
                )
            )

    # Rank across books; alternates win near-ties; cap per book and total.
    supplements.sort(
        key=lambda h: (h["score"], not h["book_id"].startswith("ncert")), reverse=True
    )
    per_book_cap = max(2, cfg.retrieval["top_k"] // 2)
    capped: list[dict[str, Any]] = []
    per_book: dict[str, int] = {}
    total = 0
    for hit in supplements:
        if per_book.get(hit["book_id"], 0) >= per_book_cap:
            continue
        text = hit["text"][: cfg.limits["max_chars_supplement_each"]]
        if total + len(text) > cfg.limits["max_chars_supplement_total"]:
            break
        per_book[hit["book_id"]] = per_book.get(hit["book_id"], 0) + 1
        total += len(text)
        capped.append(
            {
                "source_id": hit["chunk_id"],
                "book_id": hit["book_id"],
                "book_title": _title_of(hit["book_id"], books),
                "page_from": hit.get("page_from"),
                "page_to": hit.get("page_to"),
                "score": hit["score"],
                "text": text,
            }
        )

    return {
        "query": chapter,
        "class_filter": class_filter,
        "chapter": {
            "title": match["title"],
            "book_id": match["book_id"],
            "book_title": match["book_title"],
            "class": match["class"],
            "file": match["file"],
            "pages": [pages[0]["page"], pages[-1]["page"]],
            "matched_line": match["matched_line"],
        },
        "ncert_text": ncert_text,
        "ncert_text_truncated": truncated,
        "supplements": capped,
    }


# ------------------------------------------------------------------ matching
def _pages_cache_path(cfg: Config, ch: dict[str, Any]) -> Path:
    pdf = Path(ch.get("pdf") or ch["file"])
    return (
        cfg.repo_path(cfg.paths["text_cache"])
        / pdf.parent.name
        / f"{pdf.stem}.pages.json"
    )


def _load_pages(cfg: Config, ch: dict[str, Any]) -> list[dict[str, Any]]:
    path = _pages_cache_path(cfg, ch)
    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _opening_lines(pages: list[dict[str, Any]]) -> list[str]:
    """Candidate title lines from the first three pages, including the
    'CHAPTER N' + next-line join that NCERT chapter openers use."""
    blob = "\n".join(p["text"] for p in pages[:3])
    lines = [raw.strip() for raw in blob.splitlines() if raw.strip()]
    joined: list[str] = list(lines)
    for i, s in enumerate(lines):
        if re.fullmatch(r"(?i)chapter\s*\d+", s) and i + 1 < len(lines):
            joined.append(f"{s} {lines[i + 1]}")
    return joined


def _match_ncert_chapter(
    cfg: Config, query: str, ncert_books: list[dict[str, Any]]
) -> dict[str, Any]:
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    for book in ncert_books:
        for ch in book["chapters"]:
            pages = _load_pages(cfg, ch)
            if not pages:
                continue
            found = None
            for line in _opening_lines(pages):
                if titles_equivalent(query, line):
                    found = line
                    break
            if found is None:
                nq = normalize_title(query)
                blob3 = normalize_title("\n".join(p["text"] for p in pages[:3]))
                if nq and nq in blob3:
                    found = ch.get("title_detected") or query
            if found is None:
                continue
            hit = {
                "title": ch.get("title_detected") or found,
                "matched_line": found,
                "book_id": book["id"],
                "book_title": book["title"],
                "class": book["class"],
                "file": ch["pdf"],
                "exact": normalize_title(query) == normalize_title(found),
            }
            (exact if hit["exact"] else partial).append(hit)

    if exact:
        if len(exact) == 1:
            return exact[0]
        raise SourceError(
            STAGE_ID,
            f"'{query}' exactly matches several NCERT chapters: "
            + ", ".join(
                f"{h['title']} ({h['book_title']}, class {h['class']})" for h in exact
            )
            + ". Re-run with --class <n> to disambiguate.",
        )
    if len(partial) == 1:
        return partial[0]
    if partial:
        raise SourceError(
            STAGE_ID,
            f"'{query}' matches several chapters: "
            + "; ".join(
                f"{h['title']} ({h['book_title']}, class {h['class']})" for h in partial
            )
            + ". Use a more exact chapter name or re-run with --class <n>.",
        )
    raise SourceError(
        STAGE_ID,
        f"'{query}' matches no NCERT chapter in the cached library. Check the spelling, "
        "or extend sources/catalog.json. Cached chapter titles: "
        + ", ".join(
            ch.get("title_detected") or f"ch{ch['n']:02d}"
            for b in ncert_books
            for ch in b["chapters"]
        ),
    )


def _title_of(book_id: str, books: list[dict[str, Any]]) -> str:
    for b in books:
        if b["id"] == book_id:
            return b["title"]
    return book_id
