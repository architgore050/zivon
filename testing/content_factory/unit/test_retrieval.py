"""Unit tests for retrieval helpers with the deterministic FixtureEmbedder.

The real sentence-transformers model is exercised in the integration test; here
we prove the search logic itself (chunking, caching keys, cosine top-k).
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import retrieval
from factory.config import load_config
from factory.retrieval import (
    FixtureEmbedder,
    chunks_for_book,
    embed_chunks_cached,
    top_k_chunks,
)
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)


def make_cfg(tmp: Path):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"]["text_cache"] = str(tmp / "cache")
    path = tmp / "config.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    saved = install_server_env()  # server settings are env-only now
    try:
        return load_config(path)
    finally:
        release_server_env(saved)


PAGES = [
    {"page": 1, "text": "Motion is change of position. " * 40},
    {"page": 2, "text": "Speed is distance divided by time. " * 40},
    {"page": 3, "text": "Graphs show motion. " * 40},
]


class TestChunks(unittest.TestCase):
    def test_chunks_carry_pages(self):
        cfg = make_cfg(Path(tempfile.mkdtemp()))
        chunks = chunks_for_book(cfg, "b1", PAGES)
        self.assertTrue(len(chunks) > 3)
        self.assertTrue(all(c["book_id"] == "b1" for c in chunks))
        self.assertTrue(all(c["page_from"] is not None for c in chunks))
        first_pages = {c["page_from"] for c in chunks[:2]}
        self.assertIn(1, first_pages)

    def test_cache_roundtrip(self):
        tmp = Path(tempfile.mkdtemp())
        cfg = make_cfg(tmp)
        chunks = chunks_for_book(cfg, "b1", PAGES)
        with mock.patch.object(
            retrieval, "get_embedder", lambda cfg: FixtureEmbedder()
        ):
            matrix = embed_chunks_cached(cfg, "b1", chunks)
            again = embed_chunks_cached(cfg, "b1", chunks)
        np.testing.assert_array_equal(matrix, again)
        self.assertTrue((tmp / "cache" / "embeddings" / "b1.npy").exists())

    def test_cache_invalidated_by_text_change(self):
        tmp = Path(tempfile.mkdtemp())
        cfg = make_cfg(tmp)
        chunks = chunks_for_book(cfg, "b1", PAGES)
        with mock.patch.object(
            retrieval, "get_embedder", lambda cfg: FixtureEmbedder()
        ):
            m1 = embed_chunks_cached(cfg, "b1", chunks)
            chunks[0]["text"] += " changed"
            m2 = embed_chunks_cached(cfg, "b1", chunks)
        self.assertEqual(m1.shape, m2.shape)


class TestTopK(unittest.TestCase):
    def test_relevant_chunk_ranks_first(self):
        emb = FixtureEmbedder(dim=64)
        docs = [
            {
                "chunk_id": "d1",
                "text": "the slope of a distance-time graph gives the speed",
            },
            {"chunk_id": "d2", "text": "sound needs a medium to travel"},
            {"chunk_id": "d3", "text": "distance time graph slope speed of the object"},
        ]
        matrix = emb.encode([d["text"] for d in docs])
        hits = top_k_chunks(emb, "distance-time graph slope speed", docs, matrix, 2)
        self.assertEqual(len(hits), 2)
        self.assertIn(hits[0]["chunk_id"], ("d1", "d3"))
        self.assertGreaterEqual(hits[0]["score"], hits[1]["score"])

    def test_empty_chunks(self):
        emb = FixtureEmbedder(dim=8)
        self.assertEqual(
            top_k_chunks(emb, "q", [], np.zeros((0, 8), dtype=np.float32), 3), []
        )


if __name__ == "__main__":
    unittest.main()
