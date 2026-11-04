"""Vector retrieval over the source library (sentence-transformers, local).

The embedder is loaded once per process. Embeddings are cached on disk per
book; the cache key includes the model name and a hash of the chunk texts, so
any change to chunks or model invalidates it. No network calls happen at
embed time (the model is downloaded once by sentence-transformers on first
use, which requires HF connectivity or a pre-populated HF cache).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from .config import Config
from .textops import chunk_text


class Embedder(Protocol):
    def encode(self, texts: list[str]) -> np.ndarray: ...


_real_embedder: Any | None = None
_embedder_model_name: str | None = None


def get_embedder(cfg: Config):
    """Load the configured sentence-transformers model (process-wide singleton)."""
    global _real_embedder, _embedder_model_name
    name = cfg.retrieval["embedding_model"]
    if _real_embedder is None or _embedder_model_name != name:
        from sentence_transformers import SentenceTransformer  # deferred: heavy import

        _real_embedder = SentenceTransformer(name, device=cfg.retrieval["device"])
        _embedder_model_name = name
    return _real_embedder


class FixtureEmbedder:
    """Deterministic test double: hashing-based vectors. Used ONLY by tests; the
    pipeline always uses the configured sentence-transformers model."""

    def __init__(self, dim: int = 64):
        self.dim = dim

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, t in enumerate(texts):
            for token in t.lower().split():
                h = int(hashlib.sha256(token.encode()).hexdigest(), 16)
                out[i, h % self.dim] += 1.0
        norm = np.linalg.norm(out, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return out / norm


def chunks_for_book(
    cfg: Config, book_id: str, pages: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Chunk a book's pages (each {page:int, text:str}) into overlapping chunks.
    Chunking is per page, so every chunk carries an exact page citation."""
    chunk_chars = cfg.retrieval["chunk_chars"]
    overlap = cfg.retrieval["chunk_overlap"]
    chunks: list[dict[str, Any]] = []
    for p in pages:
        for i, text in enumerate(chunk_text(p["text"], chunk_chars, overlap)):
            chunks.append(
                {
                    "chunk_id": f"{book_id}#p{p['page']:04d}c{i:03d}",
                    "book_id": book_id,
                    "page_from": p["page"],
                    "page_to": p["page"],
                    "text": text,
                }
            )
    return chunks


def _cache_paths(cfg: Config, book_id: str) -> tuple[Path, Path]:
    emb_dir = cfg.repo_path(cfg.paths["text_cache"]) / "embeddings"
    return emb_dir / f"{book_id}.npy", emb_dir / f"{book_id}.meta.json"


def embed_chunks_cached(
    cfg: Config, book_id: str, chunks: list[dict[str, Any]]
) -> np.ndarray:
    """Embeddings for a book's chunks, cached under sources/cache/embeddings/."""
    emb_path, meta_path = _cache_paths(cfg, book_id)
    texts_hash = hashlib.sha256(
        json.dumps([c["text"] for c in chunks]).encode("utf-8")
    ).hexdigest()
    key = {
        "model": cfg.retrieval["embedding_model"],
        "texts_sha256": texts_hash,
        "count": len(chunks),
    }
    if emb_path.exists() and meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta == key:
            return np.load(emb_path)
    matrix = get_embedder(cfg).encode([c["text"] for c in chunks]).astype(np.float32)
    emb_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(emb_path, matrix)
    meta_path.write_text(json.dumps(key), encoding="utf-8")
    return matrix


def top_k_chunks(
    embedder: Embedder,
    query: str,
    chunks: list[dict[str, Any]],
    matrix: np.ndarray,
    k: int,
) -> list[dict[str, Any]]:
    """Cosine similarity search (vectors are L2-normalised, so dot == cosine)."""
    if not chunks:
        return []
    q = np.asarray(embedder.encode([query]), dtype=np.float32)
    q = q / (np.linalg.norm(q, axis=1, keepdims=True) + 1e-9)
    scores = matrix @ q[0]
    order = np.argsort(-scores)[:k]
    results = []
    for idx in order:
        item = dict(chunks[int(idx)])
        item["score"] = round(float(scores[int(idx)]), 4)
        results.append(item)
    return results
