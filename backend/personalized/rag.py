"""Personalized-learning RAG: corpus, index, scoped retrieval, citations.

Contract: `docs/specs/personalized-learning/agent-and-rag.md` §6. The index is
a build-time artifact (`scripts/build_personalized_index.py` →
`runs/personalized-index/<version>/{chunks.jsonl, embeddings.npy,
manifest.json}`); retrieval per turn is local, deterministic apart from the
query embedding, and never a model call.

Corpus rules (§6.1) — enforced here, not remembered:

- `ncert`  cached NCERT chapter text (`sources/cache/**/*.pages.json`,
           `[{page, text}, ...]`), per-page chunked exactly like
           `factory/retrieval.chunks_for_book` (1200 chars / 120 overlap), so
           a chunk never crosses a page and every chunk carries an exact
           `page_from/page_to`. **Tier `source`, honestly labelled as the
           textbook.**
- `lesson` published lesson manifests + `index.html` block text, one chunk per
           text-bearing block with its `block_id` and concept tag. **Tier
           `lesson`, labelled as the reviewed lesson** — never presented as
           the textbook.
- `glossary` one chunk per term; terminology consistency, never a factual
           source on its own.
- `syllabus` one chunk per concept description; scope and prerequisite order,
           never teaching prose.

**Never indexed:** CBSE exam-paper text (`DEC-COMP-001` — `sources/exam/`
holds metadata only and this module never reads it), user content, personal
instructions, artifacts, logs.

Retrieval (§6.5): scope = chapter + current concept + direct prerequisites;
query = concept title + description + weakness (≤ 500) + last wrong stem
(≤ 200); cosine top-24 in scope + top-8 out of scope; rerank keeps 8 with a
lexical overlap score and the source-kind prior (`lesson > ncert > syllabus >
glossary`); budget ≤ 4,000 excerpt characters trimmed at sentence boundaries;
`S1…S8` ids stable within the turn. Embedder unavailable → lexical-only
retrieval, honestly marked `lexical_fallback` (§6.5.8).

Citations (§6.6): the teach call may only cite `S1…S8` from its own prompt;
the server resolves each id against the retrieved set, drops unknown ids, and
builds every human label itself — never from model text.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Final, Protocol

import numpy as np

CHUNKER_VERSION: Final[str] = "pl-rag-1"
CHUNK_CHARS: Final[int] = 1200
CHUNK_OVERLAP: Final[int] = 120
SOURCE_KINDS: Final[tuple[str, ...]] = ("ncert", "lesson", "glossary", "syllabus")
# The rerank prior (§6.5.4): the reviewed lesson ranks first, the grounding
# textbook second, scope/terminology helpers last.
SOURCE_KIND_PRIOR: Final[dict[str, float]] = {
    "lesson": 0.30,
    "ncert": 0.20,
    "syllabus": 0.10,
    "glossary": 0.05,
}
MAX_CONCEPTS_PER_CHUNK: Final[int] = 3
TOP_K_IN_SCOPE: Final[int] = 24
TOP_K_OUT_SCOPE: Final[int] = 8
FINAL_K: Final[int] = 8
EXCERPT_BUDGET_CHARS: Final[int] = 4000
MAX_WEAKNESS_QUERY_CHARS: Final[int] = 500
MAX_WRONG_STEM_QUERY_CHARS: Final[int] = 200

_TOKEN_RE = re.compile(r"[a-z0-9]{2,}")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?।])\s+")


@dataclass
class RetrievalPorts:
    """Everything retrieval needs at runtime; `None` index ⇒ the honest
    `E-CONTENT-UNAVAILABLE`. Owned here (the retrieval module), consumed by
    the agent and the boot wiring."""

    index: RagIndex | None = None
    embedder: Embedder | None = None
    last_mode: str = "n/a"
    last_ungrounded: bool = False


class IndexError_(RuntimeError):
    """The index on disk is missing, stale, or does not match its manifest."""


class EmbedderUnavailable(RuntimeError):
    """No embedding backend is importable; callers fall back to lexical."""


class Embedder(Protocol):
    """The query-embedding seam (§6.6 tests fake it with `FixtureEmbedder`)."""

    def encode(self, texts: list[str]) -> np.ndarray: ...

    @property
    def model_id(self) -> str: ...


class FixtureEmbedder:
    """Deterministic hashing vectors (same scheme as `factory.retrieval`).

    Test-only double: the same token→bucket histogram, L2-normalized, so a
    fixture index and its queries share one vector space with no model
    download and no network. Never used by the production build script.
    """

    def __init__(self, dim: int = 64) -> None:
        self.dim = dim

    @property
    def model_id(self) -> str:
        return f"fixture-hashing-{self.dim}"

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for token in set(_TOKEN_RE.findall(text.lower())):
                digest = int(hashlib.sha256(token.encode("utf-8")).hexdigest(), 16)
                out[i, digest % self.dim] += 1.0
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return out / norms


def get_embedder(model_id: str) -> Embedder:
    """Load a real embedding backend (fastembed ONNX, then sentence-transformers).

    Deferred imports: the backend package is only needed when an index is
    built or a vector query is encoded. No backend importable raises
    `EmbedderUnavailable` and the caller falls back to lexical retrieval
    (§7.5.5).
    """
    try:
        from fastembed import TextEmbedding  # type: ignore[import-not-found]

        model = TextEmbedding(model_name=model_id)

        class _FastembedEmbedder:
            def encode(self, texts: list[str]) -> np.ndarray:
                return np.asarray(list(model.embed(texts)), dtype=np.float32)

            @property
            def model_id(self) -> str:
                return model_id

        return _FastembedEmbedder()
    except ImportError:
        pass
    except Exception as exc:  # pragma: no cover - backend load failure shape
        raise EmbedderUnavailable(
            f"fastembed unavailable: {type(exc).__name__}"
        ) from exc
    try:
        from sentence_transformers import SentenceTransformer  # type: ignore

        st_model = SentenceTransformer(model_id)

        class _STEmbedder:
            def encode(self, texts: list[str]) -> np.ndarray:
                return np.asarray(
                    st_model.encode(texts, normalize_embeddings=True), dtype=np.float32
                )

            @property
            def model_id(self) -> str:
                return model_id

        return _STEmbedder()
    except ImportError as exc:
        raise EmbedderUnavailable(
            "no embedding backend installed (fastembed or sentence-transformers)"
        ) from exc


# --- shared text helpers --------------------------------------------------------


def _tokens(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def chunk_text(text: str, chunk_chars: int, overlap: int) -> list[str]:
    """Fixed-size character chunks with overlap — the factory's exact contract
    (`factory/textops.py::chunk_text`), re-implemented here so the backend
    never imports the factory."""
    if chunk_chars <= overlap:
        raise ValueError("chunk_chars must be greater than overlap")
    cleaned = text.strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    step = chunk_chars - overlap
    while start < len(cleaned):
        end = min(start + chunk_chars, len(cleaned))
        chunks.append(cleaned[start:end])
        if end == len(cleaned):
            break
        start += step
    return chunks


def _trim_to_sentence(text: str, budget: int) -> str:
    """Trim at a sentence boundary, never mid-sentence (§6.5.5)."""
    if len(text) <= budget:
        return text
    cut = text[:budget]
    positions = [m.end() for m in _SENTENCE_END_RE.finditer(cut)]
    if positions:
        return cut[: positions[-1]].rstrip()
    # No sentence end inside the budget: back off to the last word boundary.
    last_space = cut.rfind(" ")
    return (cut[:last_space] if last_space > 0 else cut).rstrip()


# --- corpus builders -------------------------------------------------------------


def _chunk(
    *,
    chunk_id: str,
    text: str,
    source_kind: str,
    concept_ids: list[str],
    label: str,
    locator: str,
    **extra: Any,
) -> dict[str, Any]:
    if source_kind not in SOURCE_KINDS:
        raise ValueError(f"unknown source kind {source_kind!r}")
    concepts = list(dict.fromkeys(concept_ids))[:MAX_CONCEPTS_PER_CHUNK]
    chunk: dict[str, Any] = {
        "chunk_id": chunk_id,
        "text": text,
        "source_kind": source_kind,
        "concept_ids": concepts,
        "label": label,
        "locator": locator,
    }
    chunk.update(extra)
    return chunk


def chunks_from_syllabus(syllabus: dict[str, Any]) -> list[dict[str, Any]]:
    """One chunk per concept description (scope + order, never prose)."""
    chunks: list[dict[str, Any]] = []
    for cls in syllabus.get("classes", []):
        class_level = cls.get("class")
        for chapter in cls.get("chapters", []):
            chapter_id = str(chapter.get("chapter_id", ""))
            chapter_title = str(chapter.get("title", ""))
            for concept in chapter.get("concepts", []):
                concept_id = str(concept.get("concept_id", ""))
                description = str(concept.get("description", "")).strip()
                if not concept_id or not description:
                    continue
                title = str(concept.get("title", ""))
                section_refs = ", ".join(
                    str(ref) for ref in concept.get("section_refs", [])
                )
                text = (
                    f"Concept: {title}. Chapter: {chapter_title} "
                    f"(Class {class_level}). {description}"
                )
                chunks.append(
                    _chunk(
                        chunk_id=f"syllabus:{concept_id}",
                        text=text,
                        source_kind="syllabus",
                        concept_ids=[concept_id],
                        label=f"Syllabus: {chapter_title} · {title}",
                        locator=f"NCERT sections {section_refs}"
                        if section_refs
                        else "",
                        class_level=class_level,
                        chapter_id=chapter_id,
                        prerequisites=list(concept.get("prerequisites", [])),
                        title=title,
                    )
                )
    return chunks


def chunks_from_glossary(glossary: dict[str, Any]) -> list[dict[str, Any]]:
    """One chunk per term (EN + HI gloss)."""
    chunks: list[dict[str, Any]] = []
    for term in glossary.get("terms", []):
        name = str(term.get("english_term", "") or term.get("term", "")).strip()
        if not name:
            continue
        meaning = str(term.get("meaning_en", "") or term.get("en", "")).strip()
        hi_locale = (term.get("locales") or {}).get("hi") or {}
        hi = str(hi_locale.get("native_term", "") or term.get("hi", "")).strip()
        first_mention = str(hi_locale.get("first_mention_gloss", "")).strip()
        text = f"Glossary term: {name}. {meaning}"
        if first_mention:
            text += f" First-mention gloss: {first_mention}"
        elif hi:
            text += f" Hindi: {hi}"
        chunks.append(
            _chunk(
                chunk_id=(
                    "glossary:"
                    + str(
                        term.get("term_slug")
                        or re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
                    )
                ),
                text=text,
                source_kind="glossary",
                concept_ids=[],
                label=f"Glossary: {name}",
                locator="physics glossary",
            )
        )
    return chunks


class _SectionTextParser(HTMLParser):
    """Extract per-block text from a published lesson `index.html`.

    Published pages mark blocks as `<section id="b-XX" data-block-type=…`
    (data-and-api corpus table; the render contract). Paragraph text inside
    each section is the block's teaching prose.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: dict[str, dict[str, Any]] = {}
        self._current: str | None = None
        self._parts: list[str] = []
        self._block_type = ""
        self._concept_id = ""
        self._section_title = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = {k: (v or "") for k, v in attrs}
        block_id = attr_map.get("id", "")
        if tag == "section" and re.fullmatch(r"b-\d+", block_id or ""):
            self._current = block_id
            self._parts = []
            self._block_type = attr_map.get("data-block-type", "")
            self._concept_id = attr_map.get("data-concept-id", "")
            self._section_title = attr_map.get("data-title", "") or attr_map.get(
                "aria-label", ""
            )

    def handle_endtag(self, tag: str) -> None:
        if tag == "section" and self._current is not None:
            text = " ".join(part.strip() for part in self._parts if part.strip())
            if text:
                self.blocks[self._current] = {
                    "block_id": self._current,
                    "text": text,
                    "block_type": self._block_type,
                    "concept_id": self._concept_id,
                    "title": self._section_title,
                }
            self._current = None
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._current is not None:
            self._parts.append(data)


_TEXT_BLOCK_TYPES = frozenset({"text", "check", "worked_example", "reveal"})


def chunks_from_lesson(
    manifest: dict[str, Any], index_html: str, course_id: str
) -> list[dict[str, Any]]:
    """One chunk per text-bearing published block (tier `lesson`, §6.1).

    The chunk id carries the block id (`lesson:<course>:<block>`); the concept
    tag comes from the page's `data-concept-id`, falling back to the manifest
    block entry. The manifest's `content_hash` rides on the chunk so the
    index version changes when the lesson changes (§6.4).
    """
    parser = _SectionTextParser()
    parser.feed(index_html)
    blocks_manifest = manifest.get("blocks", {})
    lesson_title = str(manifest.get("lesson_title") or manifest.get("title", ""))
    chunks: list[dict[str, Any]] = []
    content_hash = str(manifest.get("content_hash", ""))
    for block_id in sorted(parser.blocks):
        block = parser.blocks[block_id]
        block_type = block["block_type"] or str(
            (blocks_manifest.get(block_id) or {}).get("type", "")
        )
        if block_type and block_type not in _TEXT_BLOCK_TYPES:
            continue
        concept_id = block["concept_id"] or str(
            (blocks_manifest.get(block_id) or {}).get("concept_id", "")
        )
        text = block["text"].strip()
        if len(text) < 40:
            continue
        heading = block["title"]
        label = f"Lesson: {lesson_title}"
        if heading:
            label += f" · {heading}"
        chunks.append(
            _chunk(
                chunk_id=f"lesson:{course_id}:{block_id}",
                text=text,
                source_kind="lesson",
                concept_ids=[concept_id] if concept_id else [],
                label=label,
                locator=f"lesson block {block_id}",
                course_id=course_id,
                block_id=block_id,
                block_type=block_type or "text",
                lesson_title=lesson_title,
                content_hash=content_hash,
            )
        )
    return chunks


def _concept_by_section_refs(
    concepts: list[dict[str, Any]], section_refs: list[str]
) -> list[str]:
    matched: list[str] = []
    for concept in concepts:
        refs = {str(r) for r in concept.get("section_refs", [])}
        if refs & set(section_refs):
            matched.append(str(concept.get("concept_id", "")))
    return [c for c in matched if c]


def _concept_by_lexical_overlap(text: str, concepts: list[dict[str, Any]]) -> list[str]:
    """Deterministic concept assignment when the syllabus has no section ref
    (§6.3): highest token overlap with the concept description, stored and
    auditable."""
    text_tokens = set(_tokens(text))
    scored: list[tuple[int, str]] = []
    for concept in concepts:
        description = (
            str(concept.get("description", "")) + " " + str(concept.get("title", ""))
        )
        overlap = len(text_tokens & set(_tokens(description)))
        if overlap:
            scored.append((overlap, str(concept.get("concept_id", ""))))
    scored.sort(reverse=True)
    return [cid for _, cid in scored[:MAX_CONCEPTS_PER_CHUNK] if cid]


def chunks_from_ncert_pages(
    pages: list[dict[str, Any]],
    *,
    book_id: str,
    book_title: str,
    chapter_no: int,
    chapter_id: str,
    chapter_title: str,
    chapter_concepts: list[dict[str, Any]],
    section_pages: dict[str, list[int]] | None = None,
) -> list[dict[str, Any]]:
    """Per-page textbook chunks (tier `source`; §6.2).

    `section_pages` maps a syllabus section ref ("9.2.1") to the pages it
    spans (`{"9.2.1": [148, 149]}`); when the caller cannot supply it, concept
    assignment falls back to lexical overlap with the concept descriptions
    (§6.3, deterministic and stored).
    """
    del chapter_id  # part of the locator via book/chapter metadata
    chunks: list[dict[str, Any]] = []
    for page in pages:
        page_no = int(page["page"])
        text = str(page["text"]).strip()
        if not text:
            continue
        for i, piece in enumerate(chunk_text(text, CHUNK_CHARS, CHUNK_OVERLAP)):
            section_refs = [
                ref
                for ref, spanned_pages in (section_pages or {}).items()
                if page_no in spanned_pages
            ]
            concept_ids = (
                _concept_by_section_refs(chapter_concepts, section_refs)
                if section_refs
                else _concept_by_lexical_overlap(piece, chapter_concepts)
            )
            chunks.append(
                _chunk(
                    chunk_id=f"{book_id}#p{page_no:04d}c{i:03d}",
                    text=piece,
                    source_kind="ncert",
                    concept_ids=concept_ids,
                    label=f"{book_title}, Ch. {chapter_no}, p. {page_no}",
                    locator=f"p. {page_no}",
                    book_id=book_id,
                    chapter_no=chapter_no,
                    page_from=page_no,
                    page_to=page_no,
                )
            )
    return chunks


# --- index build / load -------------------------------------------------------------


def sha256_jsonl(rows: list[dict[str, Any]]) -> str:
    payload = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def index_version(
    *,
    syllabus_sha256: str,
    manifest_content_hashes: frozenset[str],
    pack_sha256: str,
    embedder_id: str,
    chunker_version: str,
) -> str:
    """First 16 hex of sha256 over the version inputs (§6.4)."""
    digest = hashlib.sha256()
    for part in (
        syllabus_sha256,
        "\x00".join(sorted(manifest_content_hashes)),
        pack_sha256,
        embedder_id,
        chunker_version,
    ):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x1f")
    return digest.hexdigest()[:16]


def build_index(
    out_dir: Path,
    chunks: list[dict[str, Any]],
    embedder: Embedder,
    version: str,
    sources: dict[str, Any],
) -> dict[str, Any]:
    """Write `chunks.jsonl`, `embeddings.npy`, `manifest.json` (§6.4).

    Idempotent by content: the same corpus + embedder yields the same version
    directory, so a rebuild is a no-op unless the corpus changed.
    """
    if not chunks:
        raise IndexError_("refusing to build an empty index")
    out_dir.mkdir(parents=True, exist_ok=True)
    texts = [str(c["text"]) for c in chunks]
    matrix = np.asarray(embedder.encode(texts), dtype=np.float32)
    if matrix.shape[0] != len(chunks):
        raise IndexError_("embedder returned the wrong number of vectors")
    (out_dir / "chunks.jsonl").write_text(
        "\n".join(json.dumps(chunk, sort_keys=True) for chunk in chunks) + "\n",
        encoding="utf-8",
    )
    np.save(out_dir / "embeddings.npy", matrix)
    manifest = {
        "schema_version": 1,
        "version": version,
        "embedder_id": embedder.model_id,
        "chunker_version": CHUNKER_VERSION,
        "chunk_chars": CHUNK_CHARS,
        "chunk_overlap": CHUNK_OVERLAP,
        "dim": int(matrix.shape[1]),
        "chunk_count": len(chunks),
        "chunks_sha256": sha256_jsonl(chunks),
        "counts_by_source_kind": {
            kind: sum(1 for c in chunks if c["source_kind"] == kind)
            for kind in SOURCE_KINDS
        },
        "sources": sources,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


class RagIndex:
    """The loaded index: validated manifest + chunks + vectors (§6.4).

    A missing/mismatched manifest refuses to load loudly (`IndexError_`) —
    never a silently stale retrieval.
    """

    def __init__(
        self,
        version: str,
        manifest: dict[str, Any],
        chunks: list[dict[str, Any]],
        matrix: np.ndarray | None,
    ) -> None:
        self.version = version
        self.manifest = manifest
        self.chunks = chunks
        self.matrix = matrix

    @classmethod
    def load(cls, index_dir: Path) -> RagIndex:
        manifest_path = index_dir / "manifest.json"
        chunks_path = index_dir / "chunks.jsonl"
        embeddings_path = index_dir / "embeddings.npy"
        if not manifest_path.is_file():
            raise IndexError_(f"index manifest missing under {index_dir}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not chunks_path.is_file() or not embeddings_path.is_file():
            raise IndexError_(f"index artifacts missing under {index_dir}")
        chunks = [
            json.loads(line)
            for line in chunks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if len(chunks) != int(manifest.get("chunk_count", -1)):
            raise IndexError_(
                "manifest chunk_count does not match chunks.jsonl "
                f"({manifest.get('chunk_count')} != {len(chunks)})"
            )
        digest = sha256_jsonl(chunks)
        if digest != manifest.get("chunks_sha256"):
            raise IndexError_("chunks.jsonl does not match the manifest hash")
        matrix = np.load(embeddings_path)
        if matrix.shape[0] != len(chunks):
            raise IndexError_("embeddings.npy does not match the chunk count")
        if int(manifest.get("dim", 0)) != int(matrix.shape[1]):
            raise IndexError_("embeddings dim does not match the manifest")
        return cls(str(manifest["version"]), manifest, chunks, matrix)

    # --- catalog (API-PL-04) ------------------------------------------------

    def chapters(self) -> dict[str, dict[str, Any]]:
        """chapter_id → {class_level, concepts, chunk counts, coverage tier}."""
        out: dict[str, dict[str, Any]] = {}
        for chunk in self.chunks:
            chapter_id = chunk.get("chapter_id")
            if not chapter_id:
                continue
            entry = out.setdefault(
                str(chapter_id),
                {
                    "chapter_id": str(chapter_id),
                    "class_level": chunk.get("class_level"),
                    "concepts": set(),
                    "source_kinds": {},
                    "chunk_count": 0,
                },
            )
            entry["chunk_count"] = int(entry["chunk_count"]) + 1
            entry["concepts"].update(chunk.get("concept_ids", []))
            kind = str(chunk["source_kind"])
            entry["source_kinds"][kind] = int(entry["source_kinds"].get(kind, 0)) + 1
        for entry in out.values():
            entry["concepts"] = sorted(entry["concepts"])
            entry["tier"] = (
                "lesson+source"
                if entry["source_kinds"].get("ncert")
                else ("lesson" if entry["source_kinds"].get("lesson") else "source")
            )
        return out

    def catalog(self) -> dict[str, Any]:
        """The API-PL-04 payload: chapters with index coverage + tier."""
        return {
            "index_version": self.version,
            "chapters": sorted(self.chapters().values(), key=lambda c: c["chapter_id"]),
        }

    def has_chapter(self, chapter_id: str) -> bool:
        return chapter_id in self.chapters()

    # --- retrieval (§6.5) -----------------------------------------------------

    def _scope_mask(
        self, scope_concepts: set[str], chapter_id: str | None
    ) -> np.ndarray:
        chapter_of_chunk = np.array(
            [
                1.0
                if (chapter_id and chunk.get("chapter_id") == chapter_id)
                or chunk["source_kind"] in ("glossary",)
                else 0.0
                for chunk in self.chunks
            ],
            dtype=bool,
        )
        if not scope_concepts:
            return chapter_of_chunk
        concept_mask = np.array(
            [
                bool(scope_concepts & set(chunk.get("concept_ids", [])))
                for chunk in self.chunks
            ],
            dtype=bool,
        )
        return chapter_of_chunk | concept_mask

    def retrieve(
        self,
        *,
        concept_title: str,
        concept_description: str,
        scope_concept_ids: list[str],
        chapter_id: str | None,
        embedder: Embedder | None = None,
        weakness_text: str = "",
        last_wrong_stem: str = "",
    ) -> dict[str, Any]:
        """Scoped retrieval for one turn (§6.5); local, no model call.

        Returns `{"excerpts": [{excerpt_id, chunk_id, text, source_kind,
        locator, label, concept_ids, tier}], "mode": "vector"|
        "lexical_fallback", "ungrounded": bool}`. Zero hits → `ungrounded`
        with an empty excerpt list: the teach call still runs, and the prompt
        says the excerpts are empty so the model gives generic method only
        and never invents a citation (§6.5.7).
        """
        weakness_part = f" {weakness_text[:MAX_WEAKNESS_QUERY_CHARS]}".rstrip()
        stem_part = f" {last_wrong_stem[:MAX_WRONG_STEM_QUERY_CHARS]}".rstrip()
        query = (
            f"{concept_title}. {concept_description}{weakness_part}{stem_part}".strip()
        )
        query_tokens = set(_tokens(query))
        if not self.chunks:
            return {"excerpts": [], "mode": "vector", "ungrounded": True}
        scope_set = set(scope_concept_ids)
        in_scope = self._scope_mask(scope_set, chapter_id)
        in_idx = np.flatnonzero(in_scope)
        out_idx = np.flatnonzero(~in_scope)

        mode = "vector"
        if embedder is not None:
            q = np.asarray(embedder.encode([query]), dtype=np.float32)
            q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-9)
            scores = self.matrix @ q[0]
            cosine = scores
        else:
            mode = "lexical_fallback"
            cosine = np.zeros(len(self.chunks), dtype=np.float32)

        def _pick(candidates: np.ndarray, k: int) -> list[int]:
            if candidates.size == 0:
                return []
            if embedder is None:
                # Lexical-only: token-overlap score over the whole candidate set.
                scored = sorted(
                    (
                        (float(self._lexical_score(int(i), query_tokens)), int(i))
                        for i in candidates
                    ),
                    reverse=True,
                )[:k]
                return [i for _, i in scored]
            order = candidates[np.argsort(-cosine[candidates])][:k]
            return [int(i) for i in order]

        picked = _pick(in_idx, TOP_K_IN_SCOPE)
        # Out-of-scope background check for prerequisite gaps (§6.5.3): they
        # compete in the rerank and only survive if they genuinely outscore.
        picked += [i for i in _pick(out_idx, TOP_K_OUT_SCOPE) if i not in picked]

        reranked = sorted(
            picked,
            key=lambda i: (
                -(
                    float(cosine[i])
                    + self._lexical_score(i, query_tokens)
                    + SOURCE_KIND_PRIOR.get(str(self.chunks[i]["source_kind"]), 0.0)
                )
            ),
        )[:FINAL_K]

        excerpts: list[dict[str, Any]] = []
        used = 0
        for i in reranked:
            chunk = self.chunks[i]
            text = str(chunk["text"])
            remaining = EXCERPT_BUDGET_CHARS - used
            if remaining <= 0:
                break
            trimmed = _trim_to_sentence(text, remaining)
            if not trimmed:
                continue
            used += len(trimmed)
            excerpts.append(
                {
                    "excerpt_id": f"S{len(excerpts) + 1}",
                    "chunk_id": str(chunk["chunk_id"]),
                    "text": trimmed,
                    "source_kind": str(chunk["source_kind"]),
                    "locator": str(chunk.get("locator", "")),
                    "label": str(chunk["label"]),
                    "concept_ids": list(chunk.get("concept_ids", [])),
                    "tier": "lesson" if chunk["source_kind"] == "lesson" else "source",
                }
            )
        return {
            "excerpts": excerpts,
            "mode": mode,
            "ungrounded": not excerpts,
        }

    def _lexical_score(self, idx: int, query_tokens: set[str]) -> float:
        """BM25-style token overlap (F1 between query and chunk tokens)."""
        chunk_tokens = set(_tokens(str(self.chunks[idx]["text"])))
        if not query_tokens or not chunk_tokens:
            return 0.0
        overlap = len(query_tokens & chunk_tokens)
        return 2.0 * overlap / (len(query_tokens) + len(chunk_tokens))


# --- citation resolution (§6.6) -------------------------------------------------


def resolve_citations(
    citation_ids: list[str], excerpts: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], bool]:
    """Resolve the model's `S#` ids against the retrieved set.

    Unknown ids are dropped (never invented); a teaching turn with zero
    resolved citations is `ungrounded` and the UI says so. Returns
    `(citations, ungrounded)`; each citation carries the chunk identity so
    the payload keeps its `rag_index_version` provenance (§6.6).
    """
    by_id = {str(e["excerpt_id"]): e for e in excerpts}
    seen: set[str] = set()
    resolved: list[dict[str, Any]] = []
    for raw_id in citation_ids or []:
        excerpt_id = str(raw_id).strip()
        if excerpt_id not in by_id or excerpt_id in seen:
            continue
        seen.add(excerpt_id)
        excerpt = by_id[excerpt_id]
        resolved.append(
            {
                "excerpt_id": excerpt_id,
                "chunk_id": excerpt["chunk_id"],
                "source_kind": excerpt["source_kind"],
                "label": excerpt["label"],
                "locator": excerpt["locator"],
            }
        )
    return resolved, not resolved
