"""Fetch the openly-licensed Siyavula supplement PDFs into sources/pdfs/.

Downloads the Siyavula / FHSST "Everything Science" CAPS Physical Sciences
learner books (Grades 11 and 12) registered as manual-download entries in
``sources/catalog.json``. Both books are released under CC BY 3.0 (verified on
the siyavula.com reader pages on 2026-11-22; embedded videos/simulations from
external sources are excluded by the site's own licence note - this script
fetches the text-only learner PDFs, which the pipeline paraphrases and cites,
never redistributes: ``sources/pdfs/`` is gitignored).

Usage:

    python scripts/fetch_siyavula.py [repo_root]      # default: cwd

The script is data-driven from the catalog: it only downloads entries whose id
is in SIYAVULA_BOOKS below and whose ``download`` is ``manual``; the placement
path matches what ``factory/ingest.py`` expects for manual books
(``sources/pdfs/<book_id>/<manual_filename>``). Existing non-empty files are
kept (idempotent, like the NCERT prefetch). Every fetched file is checked for
the ``%PDF`` magic bytes and a minimum size before it is accepted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import requests

# book id -> direct learner-book PDF URL (from the siyavula.com reader pages,
# verified reachable 2026-11-22).
SIYAVULA_BOOKS: dict[str, str] = {
    "siyavula-physical-sciences-11": (
        "https://www.siyavula.com/downloads/books/science/"
        "Gr11_PhysicalSciences_Learner_Eng.pdf"
    ),
    "siyavula-physical-sciences-12": (
        "https://www.siyavula.com/downloads/books/science/"
        "Gr12_PhysicalSciences_Learner_Eng.pdf"
    ),
}

USER_AGENT = "zivon-factory/1.0 (content pipeline; CC-BY source ingest)"
MIN_BYTES = 1_000_000  # a real learner book is ~9 MB; reject truncations early


def fetch(repo: Path) -> int:
    catalog_path = repo / "sources" / "catalog.json"
    catalog = __import__("json").loads(catalog_path.read_text(encoding="utf-8"))
    books = {b["id"]: b for b in catalog["books"]}

    failures: list[str] = []
    for book_id, url in SIYAVULA_BOOKS.items():
        book = books.get(book_id)
        if book is None:
            failures.append(f"{book_id}: not registered in sources/catalog.json")
            continue
        if book.get("download") != "manual":
            failures.append(f"{book_id}: catalog entry is not download:manual")
            continue
        dest = repo / "sources" / "pdfs" / book_id / book["manual_filename"]
        if dest.exists() and dest.stat().st_size > MIN_BYTES:
            print(f"[fetch-siyavula] {book_id}: already cached at {dest}")
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"[fetch-siyavula] {book_id}: downloading {url}")
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=300)
        resp.raise_for_status()
        data = resp.content
        if not data.startswith(b"%PDF"):
            failures.append(f"{book_id}: response does not start with %PDF magic bytes")
            continue
        if len(data) < MIN_BYTES:
            failures.append(
                f"{book_id}: fetched {len(data)} bytes, below the {MIN_BYTES} sanity floor"
            )
            continue
        dest.write_bytes(data)
        print(f"[fetch-siyavula] {book_id}: wrote {len(data)} bytes -> {dest}")

    if failures:
        for line in failures:
            print(f"[fetch-siyavula] FAIL {line}", file=sys.stderr)
        return 1
    return 0


def main() -> int:
    repo = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    return fetch(repo)


if __name__ == "__main__":
    sys.exit(main())
