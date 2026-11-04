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
- Hosts whose published TLS chain is broken (ncert.nic.in serves its leaf without
  the Let's Encrypt intermediate) are verified against pinned chain bundles in
  sources/certs/<host>.pem; fetches are polite (spaced) and retried with backoff
  because textbook sites throttle bursty clients.
- Extracted page text is cached per PDF and reused across runs (on the cluster the
  sources PVC makes the cache durable), so a run that dies partway resumes instead
  of re-extracting finished books.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

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


_FETCH_ATTEMPTS = 3
_MIN_FETCH_GAP_S = (
    1.5  # politeness: bursty clients get throttled/reset (seen 2026-11-02)
)
_last_fetch_at = 0.0


def _cert_bundle_for(cfg: Config, url: str) -> str | bool:
    """Pinned chain bundle for hosts with a broken published chain.

    ncert.nic.in serves its Let's Encrypt leaf without the YE1 intermediate, so
    stock verifiers fail. sources/certs/ncert.nic.in.pem carries the missing
    intermediates/roots (regeneration notes inside the file). Hosts without a
    bundle keep the system CA store (True)."""
    host = urlparse(url).hostname or ""
    certs_dir = Path(cfg.paths["catalog"]).parent / "certs"
    bundle = cfg.repo_path(str(certs_dir / f"{host}.pem"))
    return str(bundle) if bundle.exists() else True


def _get(url: str, cfg: Config) -> requests.Response:
    """One polite, retried GET. Raises SourceError after _FETCH_ATTEMPTS failures."""
    global _last_fetch_at
    verify = _cert_bundle_for(cfg, url)
    last_exc: Exception | None = None
    for attempt in range(1, _FETCH_ATTEMPTS + 1):
        gap = _MIN_FETCH_GAP_S - (time.monotonic() - _last_fetch_at)
        if gap > 0:
            time.sleep(gap)
        _last_fetch_at = time.monotonic()
        try:
            return requests.get(
                url,
                timeout=120,
                headers={"User-Agent": "zivon-content-factory/0.1"},
                verify=verify,
            )
        except requests.RequestException as exc:
            last_exc = exc
            print(
                f"    [warn] fetch attempt {attempt}/{_FETCH_ATTEMPTS} failed for {url}: {exc}"
            )
            if attempt < _FETCH_ATTEMPTS:
                time.sleep(5 * attempt)  # backoff: 5s, 10s
    raise SourceError(
        STAGE_ID, f"could not fetch {url} after {_FETCH_ATTEMPTS} attempts: {last_exc}"
    ) from last_exc


def _fetch(cfg: Config, url: str, dest: Path) -> Path:
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
        resp = _get(url, cfg)
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


def _render_table(table: Any) -> str | None:
    """Render a detected ruled table as explicit rows:

        [table]
        Quantity | Symbol | Unit
        Speed | v | m s-1

    Returns None for candidates too thin to be a real table (a single-row
    candidate is almost always a false positive from figure rules), in which
    case the region stays part of the flow text."""
    lines: list[str] = []
    for row in table.extract():
        cells = [(c or "").replace("\n", " ").strip() for c in row]
        if any(cells):
            lines.append(" | ".join(cells))
    if len(lines) < 2:
        return None
    return "[table]\n" + "\n".join(lines)


def _extract_pages(
    pdf_path: Path, max_pages: int | None = None
) -> list[dict[str, Any]]:
    """Extract page text with pdfplumber.

    use_text_flow=True follows the content-stream order, which for born-digital
    textbooks (all catalog entries) IS the reading order: raised superscripts
    join their base line ("m s -2") instead of being smeared mid-word, and
    column furniture stays put. Ruled tables are detected, removed from the
    flow text (outside_bbox), and re-appended as explicit "[table]" row blocks
    so the Synthesizer sees cell structure, not a flattened jumble.
    Scanned/image-only pages yield empty text and warn loudly per page."""
    try:
        pages_out: list[dict[str, Any]] = []
        with pdfplumber.open(str(pdf_path)) as pdf:
            page_list = pdf.pages if max_pages is None else pdf.pages[:max_pages]
            for i, page in enumerate(page_list):
                try:
                    text_page = page
                    table_blocks: list[str] = []
                    for candidate in page.find_tables():
                        block = _render_table(candidate)
                        if block is None:
                            continue  # false positive: keep its region in the flow text
                        table_blocks.append(block)
                        text_page = text_page.outside_bbox(candidate.bbox)
                    text = clean_pdf_text(
                        text_page.extract_text(use_text_flow=True) or ""
                    )
                    if table_blocks:
                        text = (text + "\n\n" if text else "") + "\n\n".join(
                            table_blocks
                        )
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


def _cached_pages(cfg: Config, book_id: str, stem: str) -> list[dict[str, Any]] | None:
    """Return previously extracted page text for this PDF, or None if absent/unusable.

    This is what makes a run resumable: on the cluster the text cache lives on the
    sources PVC, so a run that dies partway (deadline, OOM) does not re-extract
    books it already finished."""
    path = _cache_dir(cfg, book_id) / f"{stem}.pages.json"
    if not path.exists():
        return None
    try:
        pages = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        print(f"    [warn] text cache {path} unreadable ({exc}); re-extracting")
        return None
    if not isinstance(pages, list) or not all(
        isinstance(p, dict) and "page" in p and "text" in p for p in pages
    ):
        print(f"    [warn] text cache {path} malformed; re-extracting")
        return None
    print(f"    [cache] {book_id}/{stem}: reusing {len(pages)} extracted pages")
    return pages


# ------------------------------------------------------------------ auto books
def _index_auto_book(
    cfg: Config, run_ctx: RunContext, book: dict[str, Any]
) -> dict[str, Any]:
    book_id = book["id"]
    print(f"[{STAGE_ID}] book {book_id}: {book['title']}")
    prelims_pdf = _fetch(
        cfg, book["prelims_url"], _book_dir(cfg, book_id) / "prelims.pdf"
    )
    prelims_pages = _cached_pages(cfg, book_id, "prelims")
    if prelims_pages is None:
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
                "If the quoted text looks garbled (symbol-font glyphs), the cached prelims text is "
                f"stale: delete {_cache_dir(cfg, book_id) / 'prelims.pages.json'} and re-run. "
                "Otherwise fix the catalog entry or the class_evidence list.",
            )

    chapters: list[dict[str, Any]] = []
    truncated_at: int | None = None
    for n in book["chapter_numbers"]:
        url = book["chapter_url_template"].format(nn=f"{n:02d}")
        dest = _book_dir(cfg, book_id) / f"ch{n:02d}.pdf"
        try:
            _fetch(cfg, url, dest)
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
        pages = _cached_pages(cfg, book_id, f"ch{n:02d}")
        if pages is None:
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
    pages = _cached_pages(cfg, book_id, dest.stem)
    if pages is None:
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
