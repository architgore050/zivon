"""Stage 01-locate: find the requested chapter and build the cited source pack.

Two searches, per the founder's spec:
1. EXACT search in NCERT: every cached NCERT chapter file's opening pages are
   matched against the user's chapter name (normalised title equivalence on
   TITLE CANDIDATES only - body prose can never claim an exact hit; a
   body-phrase-only match is a demoted partial, reported loudly).
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
            "matched_via": match["matched_via"],
            "number": match.get("number"),
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


_CHAPTER_LINE = re.compile(r"(?i)^chapter\s+(?:\d+|[a-z]+)\s*$")
_CHAPTER_INLINE = re.compile(r"(?i)^chapter\s+(?:\d+|[a-z]+)\s+(.+)$")


def _looks_like_title(s: str) -> bool:
    """A line that could BE a chapter title, not prose about one. NCERT prints
    chapter titles in display caps; body sentences are long and mixed-case.
    Without this filter a Newton's-first-law sentence ('...continues in uniform
    motion in a straight line unless compelled...') matches a chapter query -
    the 2026-11-05 contamination where 'Motion in a Straight Line' (class 11)
    silently pulled the LAWS OF MOTION chapter."""
    words = s.split()
    if not (1 <= len(words) <= 8) or len(s) > 70:
        return False
    if s.endswith((".", ",", ";", ":")):
        return False
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return False
    return sum(c.isupper() for c in letters) >= len(letters) * 0.7


def _title_candidates(pages: list[dict[str, Any]]) -> list[str]:
    """Title-shaped lines from a chapter's opening pages: the line after a
    'CHAPTER N' line (NCERT prints chapter numbers as words - 'CHAPTER TWO'),
    an inline 'CHAPTER N Title', and standalone title-shaped lines - the clean
    title the opener's contents block prints, e.g. 'MOTION IN A STRAIGHT LINE
    15'. Display-type fragments ('M', 'OTION IN A') may appear here; they are
    harmless because a corrupted fragment can never contain the full query."""
    blob = "\n".join(p["text"] for p in pages[:3])
    lines = [raw.strip() for raw in blob.splitlines() if raw.strip()]
    out: list[str] = []
    for i, s in enumerate(lines):
        m = _CHAPTER_INLINE.match(s)
        if m:
            out.append(m.group(1).strip())
        elif _CHAPTER_LINE.match(s) and i + 1 < len(lines):
            out.append(lines[i + 1])
    out.extend(s for s in lines if _looks_like_title(s))
    return out


def _clean_title(line: str) -> str:
    """Drop the trailing book-page number NCERT opener/contents lines carry
    ('MOTION IN A STRAIGHT LINE 15' -> 'MOTION IN A STRAIGHT LINE')."""
    return re.sub(r"\s+\d{1,4}$", "", line).strip()


def _match_ncert_chapter(
    cfg: Config, query: str, ncert_books: list[dict[str, Any]]
) -> dict[str, Any]:
    """Chapter matching contract (rewritten 2026-11-05 after the founder's
    contamination incident): EXACT means a TITLE CANDIDATE (a title-shaped line
    from the chapter opener, never body prose) is title-equivalent to the query.
    A phrase that only appears in a chapter's BODY prose is a demoted PARTIAL -
    it can win only when no title matches anywhere, and it is reported loudly
    with its evidence so the operator can confirm. The old code let a body
    sentence fabricate an exact hit (found = query -> always 'exact'), which
    beat the real title match and silently built the wrong chapter's page."""
    exact: list[dict[str, Any]] = []
    partial: list[dict[str, Any]] = []
    nq = normalize_title(query)
    for book in ncert_books:
        for ch in book["chapters"]:
            pages = _load_pages(cfg, ch)
            if not pages:
                continue
            hit_line = next(
                (c for c in _title_candidates(pages) if titles_equivalent(query, c)),
                None,
            )
            if hit_line is not None:
                exact.append(
                    _chapter_hit(
                        book, ch, _clean_title(hit_line), hit_line, "title_line"
                    )
                )
                continue
            if nq and nq in normalize_title("\n".join(p["text"] for p in pages)):
                cands = _title_candidates(pages)
                title = ch.get("title_detected") or (
                    _clean_title(cands[0]) if cands else f"chapter {ch['n']}"
                )
                partial.append(_chapter_hit(book, ch, title, None, "body_phrase"))

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
        hit = partial[0]
        print(
            f"    [loud] {STAGE_ID}: no chapter TITLE matches '{query}'; the phrase "
            f"appears in the BODY of '{hit['title']}' ({hit['book_title']}, class "
            f"{hit['class']}) - verify this is the chapter you meant, or re-run with "
            "an exact chapter title."
        )
        return hit
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
            _library_title(cfg, ch) for b in ncert_books for ch in b["chapters"]
        ),
    )


def _chapter_hit(
    book: dict[str, Any],
    ch: dict[str, Any],
    title: str,
    matched_line: str | None,
    via: str,
) -> dict[str, Any]:
    # NCERT numbers chapters continuously across parts of a class (Part I
    # ends at 7, Part II starts at 8 - founder confirmed 2026-11-09), and
    # ingest's chapter records carry that global number as "n". Carry it
    # through so the manifest/courses index can order by real chapter
    # number; non-NCERT chapters have no reliable number and sort last.
    return {
        "title": title,
        "matched_line": matched_line,
        "matched_via": via,
        "book_id": book["id"],
        "book_title": book["title"],
        "class": book["class"],
        "file": ch["pdf"],
        "number": ch.get("n") if book.get("is_ncert") else None,
    }


def _library_title(cfg: Config, ch: dict[str, Any]) -> str:
    """Best display name for a chapter in error messages."""
    pages = _load_pages(cfg, ch)
    cands = _title_candidates(pages) if pages else []
    return ch.get("title_detected") or (
        _clean_title(cands[0]) if cands else f"ch{ch['n']:02d}"
    )


def _title_of(book_id: str, books: list[dict[str, Any]]) -> str:
    for b in books:
        if b["id"] == book_id:
            return b["title"]
    return book_id
