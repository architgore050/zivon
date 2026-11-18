#!/usr/bin/env python3
"""Build the personalized-learning RAG index (agent-and-rag.md §6.4; PL2).

Key-free and offline by construction: the only model-ish component is the
local embedder, and `--embedder fixture` (the default in CI/tests) produces a
fully deterministic index with no download and no network. A real deployment
build uses `--embedder fastembed` (the ONNX multilingual-e5-small per §6.4)
or an explicit sentence-transformers model id.

Corpus (§6.1):
- `syllabus`  sources/syllabus/syllabus.json (one chunk per concept);
- `glossary`  sources/glossary/physics_glossary.json (one chunk per term);
- `lesson`    published `frontend/courses/**/manifest.json` + the topic's
              `index.html` block text (tier `lesson`, honestly labelled);
- `ncert`     cached page text `sources/cache/**/*.pages.json` matched by the
              catalog's chapter URL stems (tier `source`). A chapter whose
              pages cache is absent is **skipped and recorded** in the
              manifest — never substituted or fabricated.

**Never indexed:** CBSE exam-paper content (`sources/exam/` — DEC-COMP-001),
user content, artifacts, logs.

Output: `<index-root>/<version>/{chunks.jsonl, embeddings.npy, manifest.json}`.
The version is content-addressed (first 16 hex of sha256 over the syllabus
digest, published manifests' content hashes, the P2 pack digest, the embedder
id, and the chunker version), so the same inputs rebuild as a no-op and
`--force` is only needed to overwrite an existing directory in place.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import numpy as np

from backend.personalized.rag import (
    Embedder,
    FixtureEmbedder,
    IndexError_,
    chunks_from_glossary,
    chunks_from_lesson,
    chunks_from_ncert_pages,
    chunks_from_syllabus,
    get_embedder,
    index_version,
)
from backend.personalized.rag import (
    build_index as write_index,
)

CATALOG_PATH = REPO_ROOT / "sources" / "catalog.json"
SYLLABUS_PATH = REPO_ROOT / "sources" / "syllabus" / "syllabus.json"
GLOSSARY_PATH = REPO_ROOT / "sources" / "glossary" / "physics_glossary.json"
COURSES_DIR = REPO_ROOT / "frontend" / "courses"
ASSESSMENT_DIR = REPO_ROOT / "sources" / "assessment"
EXAM_DIR = REPO_ROOT / "sources" / "exam"  # never read; named for the guard


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(65536), b""):
            digest.update(block)
    return digest.hexdigest()


def _pack_sha256() -> str:
    """Digest over the tracked P2 assessment packs (the bank's provenance)."""
    digest = hashlib.sha256()
    pack_dirs = sorted(p for p in ASSESSMENT_DIR.glob("packs/*") if p.is_dir())
    for pack_dir in pack_dirs:
        for path in sorted(pack_dir.glob("*.json")):
            digest.update(pack_dir.name.encode("utf-8"))
            digest.update(b"\x1f")
            digest.update(_sha256_file(path).encode("utf-8"))
            digest.update(b"\x1e")
    return digest.hexdigest()


def _ncert_pages_for_chapter(
    cache_root: Path, book: dict, chapter_no: int
) -> tuple[Path | None, list[dict]]:
    """Match a chapter's pages cache via the catalog's URL stem (§6.2).

    The catalog's `chapter_url_template` (`…/jesc1{nn}.pdf`) pins the local
    cache stem `jesc109.pages.json` under any directory of the cache root.
    Returns `(path, pages)` or `(None, [])` when the cache is absent — an
    honest gap the manifest records, never a guess.
    """
    if not cache_root.is_dir():
        return None, []
    template = str(book.get("chapter_url_template", ""))
    offset = int(book.get("chapter_url_offset", 0) or 0)
    if "{nn}" not in template or not template.endswith(".pdf"):
        return None, []
    nn = chapter_no - offset
    if nn < 1:
        return None, []
    stem = Path(template.replace("{nn}", f"{nn:02d}")).stem
    for path in sorted(cache_root.rglob(f"{stem}.pages.json")):
        try:
            pages = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if (
            isinstance(pages, list)
            and pages
            and all(isinstance(p, dict) and "page" in p and "text" in p for p in pages)
        ):
            return path, pages
    return None, []


def _lesson_chunks() -> list[dict]:
    """Published-lesson chunks from the repo's committed `frontend/courses/`."""
    chunks: list[dict] = []
    for manifest_path in sorted(COURSES_DIR.glob("*/*/manifest.json")):
        topic_dir = manifest_path.parent
        # Only the base (English) locale is indexed; translations share the
        # content and the base lesson is the reviewed wording (§6.1).
        if topic_dir.name in ("hi", "hi-Latn", "en"):
            continue
        course_id = topic_dir.name
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            print(f"skip unreadable manifest: {manifest_path}", file=sys.stderr)
            continue
        index_html = topic_dir / "index.html"
        if not index_html.is_file():
            continue
        chunks.extend(
            chunks_from_lesson(
                manifest,
                index_html.read_text(encoding="utf-8"),
                course_id=f"{topic_dir.parent.name}/{course_id}",
            )
        )
    return chunks


def gather_corpus(cache_root: Path) -> tuple[list[dict], dict]:
    """All indexed chunks + the `sources` provenance block for the manifest."""
    syllabus = json.loads(SYLLABUS_PATH.read_text(encoding="utf-8"))
    glossary = json.loads(GLOSSARY_PATH.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    chunks: list[dict] = []
    chunks.extend(chunks_from_syllabus(syllabus))
    chunks.extend(chunks_from_glossary(glossary))
    lesson_chunks = _lesson_chunks()
    chunks.extend(lesson_chunks)

    books_by_id = {str(b.get("id")): b for b in catalog.get("books", [])}
    ncert_files: dict[str, str] = {}
    ncert_missing: list[str] = []
    syllabus_chunks = [c for c in chunks if c["source_kind"] == "syllabus"]
    for cls in syllabus.get("classes", []):
        for chapter in cls.get("chapters", []):
            chapter_id = str(chapter.get("chapter_id", ""))
            book = books_by_id.get(str(chapter.get("book_id", "")))
            if book is None or not chapter.get("number"):
                continue
            path, pages = _ncert_pages_for_chapter(
                cache_root, book, int(chapter["number"])
            )
            concepts = [c for c in syllabus_chunks if c.get("chapter_id") == chapter_id]
            if path is None or not pages:
                ncert_missing.append(chapter_id)
                continue
            ncert_files[chapter_id] = _sha256_file(path)
            chunks.extend(
                chunks_from_ncert_pages(
                    pages,
                    book_id=str(chapter.get("book_id")),
                    book_title=str(book.get("title", chapter.get("book_id"))),
                    chapter_no=int(chapter["number"]),
                    chapter_id=chapter_id,
                    chapter_title=str(chapter.get("title", "")),
                    chapter_concepts=concepts,
                )
            )

    sources_meta = {
        "syllabus": {
            "path": "sources/syllabus/syllabus.json",
            "sha256": _sha256_file(SYLLABUS_PATH),
        },
        "glossary": {
            "path": "sources/glossary/physics_glossary.json",
            "sha256": _sha256_file(GLOSSARY_PATH),
        },
        "lesson_manifests": sorted(
            {str(c.get("content_hash")) for c in lesson_chunks if c.get("content_hash")}
        ),
        "ncert_pages_files": ncert_files,
        "ncert_missing_chapters": sorted(ncert_missing),
        "exam_paper_content_indexed": False,
    }
    return chunks, sources_meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--index-root",
        default=str(REPO_ROOT / "runs" / "personalized-index"),
        help="output root (default runs/personalized-index; gitignored, PVC-mounted)",
    )
    parser.add_argument(
        "--ncert-cache-dir",
        default=str(REPO_ROOT / "sources" / "cache"),
        help="NCERT pages-cache root (default sources/cache)",
    )
    parser.add_argument(
        "--embedder",
        default="fixture",
        help=(
            "'fixture' (deterministic hashing, tests/CI), 'fastembed' "
            "(the ONNX multilingual-e5-small per spec), or an explicit model id"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="overwrite an existing version directory in place",
    )
    args = parser.parse_args(argv)

    if EXAM_DIR.exists() and EXAM_DIR.is_dir():
        # The guard is structural: no code path below reads sources/exam/.
        pass

    chunks, sources_meta = gather_corpus(Path(args.ncert_cache_dir))
    syllabus_sha = sources_meta["syllabus"]["sha256"]
    pack_sha = _pack_sha256()

    embedder: Embedder
    if args.embedder == "fixture":
        embedder = FixtureEmbedder()
    elif args.embedder == "fastembed":
        embedder = get_embedder("intfloat/multilingual-e5-small")
    else:
        embedder = get_embedder(args.embedder)

    version = index_version(
        syllabus_sha256=syllabus_sha,
        manifest_content_hashes=frozenset(
            sources_meta["lesson_manifests"],
        ),
        pack_sha256=pack_sha,
        embedder_id=embedder.model_id,
        chunker_version="pl-rag-1",
    )

    out_dir = Path(args.index_root) / version
    if (out_dir / "manifest.json").is_file() and not args.force:
        print(f"index {version} already present: {out_dir}")
        print("up to date (use --force to rebuild in place)")
        return 0
    if args.force:
        import shutil

        shutil.rmtree(out_dir, ignore_errors=True)

    try:
        manifest = write_index(
            out_dir,
            chunks,
            embedder,
            version,
            sources_meta,
        )
    except IndexError_ as exc:
        print(f"index build refused: {exc}", file=sys.stderr)
        return 2

    print(f"index {version} written to {out_dir}")
    print(
        "chunks: "
        + ", ".join(f"{k}={v}" for k, v in manifest["counts_by_source_kind"].items())
    )
    if sources_meta["ncert_missing_chapters"]:
        print(
            "ncert cache missing for chapters (recorded in the manifest, "
            f"not substituted): {', '.join(sources_meta['ncert_missing_chapters'])}",
            file=sys.stderr,
        )
    dims = np.load(out_dir / "embeddings.npy").shape
    print(f"embeddings: {dims}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
