"""Stage 00-ingest: fetch and index every book in sources/catalog.json.

Guarantees:
- Every downloaded file starts with the %PDF magic bytes and parses with
  pdfplumber (pdfminer engine, use_text_flow reading order - handles
  superscripts and layout far better than raw pypdf).
- The prelims of every auto-download book contains the catalog's class-evidence
  string; otherwise the stage fails loudly with the offending text quoted.
- Chapter PDFs are stored one file per chapter; text is cached per page.
- A 404 on a chapter of a chapters_verified=false book ends that book's list at
  the last good chapter and records `truncated_at` in the output (printed
  loudly). A 404 on a chapters_verified=true book is fatal - fix the catalog.
- Manual-download books must already exist at sources/pdfs/<id>/<filename>;
  otherwise the stage fails with exact placement instructions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pdfplumber
import requests

from .artifacts import RunContext
from .config import Config
from .errors import SourceError
from .textops import clean_pdf_text

STAGE_ID = "00-ingest"
PDF_MAGIC = b"%PDF-"


def run(cfg: Config, run_ctx: RunContext) -> dict[str, Any]:
    catalog = _load_catalog(cfg)
    out_books: list[dict[str, Any]] = []
    for book in catalog["books"]:
        if book.get("download") == "manual":
            out_books.append(_index_manual_book(cfg, book))
        else:
            out_books.append(_index_auto_book(cfg, run_ctx, book))
    return {"books": out_books}


# --------------------------------------------------------------------- catalog
def _load_catalog(cfg: Config) -> dict[str, Any]:
    path = cfg.repo_path(cfg.paths["catalog"])
    if not path.exists():
        raise SourceError(STAGE_ID, f"catalog not found at {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not data.get("books"):
        raise SourceError(STAGE_ID, f"catalog at {path} has no books")
    return data


def _book_dir(cfg: Config, book_id: str) -> Path:
    return cfg.repo_path(cfg.paths["pdf_cache"]) / book_id


def _cache_dir(cfg: Config, book_id: str) -> Path:
    return cfg.repo_path(cfg.paths["text_cache"]) / book_id


def _fetch(url: str, dest: Path) -> Path:
    """Download (or reuse cache) one PDF and validate it is really a PDF."""
    if dest.exists() and dest.stat().st_size > 0:
        _validate_pdf(dest, f"{dest} (cached)")
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    if url.startswith("file://"):
        src = Path(url[len("file://") :])
        if not src.exists():
            raise _NotFound(url)
        dest.write_bytes(src.read_bytes())
    else:
        try:
            resp = requests.get(
                url, timeout=120, headers={"User-Agent": "zivon-content-factory/0.1"}
            )
        except requests.RequestException as exc:
            raise SourceError(STAGE_ID, f"could not fetch {url}: {exc}") from exc
        if resp.status_code == 404:
            raise _NotFound(url)
        if resp.status_code != 200:
            raise SourceError(STAGE_ID, f"HTTP {resp.status_code} while fetching {url}")
        dest.write_bytes(resp.content)
    _validate_pdf(dest, url)
    return dest


class _NotFound(Exception):
    def __init__(self, url: str):
        self.url = url
        super().__init__(f"404 at {url}")


def _validate_pdf(path: Path, origin: str) -> None:
    head = path.read_bytes()[:5]
    if not head.startswith(PDF_MAGIC):
        raise SourceError(
            STAGE_ID,
            f"{origin} is not a PDF (starts with {head!r}). If this is an HTML error page, "
            "delete the cached file and check the URL.",
        )


def _extract_pages(
    pdf_path: Path, max_pages: int | None = None
) -> list[dict[str, Any]]:
    """Extract page text with pdfplumber.

    use_text_flow=True follows the content-stream order, which for born-digital
    textbooks (all catalog entries) IS the reading order: raised superscripts
    join their base line ("m s -2") instead of being smeared mid-word, and
    column furniture stays put. Scanned/image-only pages yield empty text and
    warn loudly per page."""
    try:
        pages_out: list[dict[str, Any]] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_list = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            for i, page in enumerate(page_list):
                try:
                    text = clean_pdf_text(page.extract_text(use_text_flow=True) or "")
                except Exception as exc:  # noqa: BLE001 — pdfminer can raise on weird pages; warning is loud, not silent
                    text = ""
                    print(
                        f"    [warn] page {i + 1} of {pdf_path.name}: text extraction failed ({exc})"
                    )
                pages_out.append({"page": i + 1, "text": text})
        return pages_out
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError(STAGE_ID, f"could not parse {pdf_path}: {exc}") from exc


def _save_pages(
    cfg: Config, book_id: str, stem: str, pages: list[dict[str, Any]]
) -> Path:
    out = _cache_dir(cfg, book_id) / f"{stem}.pages.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    return out


# ------------------------------------------------------------------ auto books
def _index_auto_book(
    cfg: Config, run_ctx: RunContext, book: dict[str, Any]
) -> dict[str, Any]:
    book_id = book["id"]
    print(f"[{STAGE_ID}] book {book_id}: {book['title']}")
    prelims_pdf = _fetch(book["prelims_url"], _book_dir(cfg, book_id) / "prelims.pdf")
    prelims_pages = _extract_pages(prelims_pdf, max_pages=6)
    _save_pages(cfg, book_id, "prelims", prelims_pages)

    evidence = [e for e in book.get("class_evidence", []) if e]
    if evidence:
        blob = "\n".join(p["text"] for p in prelims_pages).lower()
        if not any(e.lower() in blob for e in evidence):
            raise SourceError(
                STAGE_ID,
                f"book {book_id}: none of the class_evidence strings {evidence} appear in the "
                f"prelims text. First page says: {prelims_pages[0]['text'][:300]!r}. "
                "Fix the catalog entry or the class_evidence list.",
            )

    chapters: list[dict[str, Any]] = []
    truncated_at: int | None = None
    for n in book["chapter_numbers"]:
        url = book["chapter_url_template"].format(nn=f"{n:02d}")
        dest = _book_dir(cfg, book_id) / f"ch{n:02d}.pdf"
        try:
            _fetch(url, dest)
        except _NotFound as exc:
            if book.get("chapters_verified") is False:
                truncated_at = n
                print(
                    f"    [loud] book {book_id}: chapter {n} returned 404; the catalog marks this "
                    f"book's chapter list as unverified, so the list ends at chapter {n - 1}. "
                    "Recorded in the run output. If that is wrong, fix sources/catalog.json."
                )
                run_ctx.mark_stage(
                    STAGE_ID,
                    "running",
                    detail=f"{book_id}: chapter list truncated at {n - 1}",
                )
                break
            raise SourceError(
                STAGE_ID,
                f"book {book_id}: chapter {n} returned 404 at {url}, but the catalog marks this "
                "book chapters_verified=true. Fix sources/catalog.json.",
            ) from exc
        pages = _extract_pages(dest)
        _save_pages(cfg, book_id, f"ch{n:02d}", pages)
        chapters.append(
            {
                "n": n,
                "pdf": str(dest),
                "pages_count": len(pages),
                "title_detected": _detect_title(pages),
            }
        )

    return {
        "id": book_id,
        "class": book["class"],
        "subject": book["subject"],
        "title": book["title"],
        "is_ncert": book["is_ncert"],
        "license": book["license"],
        "prelims_pdf": str(prelims_pdf),
        "chapters": chapters,
        "truncated_at": truncated_at,
    }


def _detect_title(pages: list[dict[str, Any]]) -> str | None:
    """Best-effort chapter title from the first page: the first non-numeric,
    non-'chapter' line at the start of the chapter."""
    import re

    if not pages:
        return None
    lines = [ln.strip() for ln in pages[0]["text"].splitlines() if ln.strip()]
    for i, ln in enumerate(lines[:10]):
        if re.fullmatch(r"(?i)chapter\s*\d+", ln) and i + 1 < len(lines):
            return lines[i + 1]
        m = re.match(r"(?i)chapter\s*\d+\s+(.+)", ln)
        if m:
            return m.group(1).strip()
    return None


# --------------------------------------------------------------- manual books
def _index_manual_book(cfg: Config, book: dict[str, Any]) -> dict[str, Any]:
    book_id = book["id"]
    dest = _book_dir(cfg, book_id) / book["manual_filename"]
    if not dest.exists():
        raise SourceError(
            STAGE_ID,
            f"book {book_id} is a manual-download entry but the file is missing. "
            f"Download it from {book.get('manual_url')} and place it at: {dest}",
        )
    print(f"[{STAGE_ID}] book {book_id}: using manually placed {dest.name}")
    pages = _extract_pages(dest)
    _save_pages(cfg, book_id, dest.stem, pages)
    return {
        "id": book_id,
        "class": book["class"],
        "subject": book["subject"],
        "title": book["title"],
        "is_ncert": book["is_ncert"],
        "license": book["license"],
        "prelims_pdf": None,
        "chapters": [
            {
                "n": 1,
                "pdf": str(dest),
                "pages_count": len(pages),
                "title_detected": None,
            }
        ],
        "single_file": True,
        "truncated_at": None,
    }
