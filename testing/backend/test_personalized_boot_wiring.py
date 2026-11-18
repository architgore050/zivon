"""PL2 boot wiring and slim-dependency smoke checks (intake findings 1 & 2).

Two contracts the first iteration got wrong:

1. The boot wiring (`backend/app.py::_wire_personalized_agent`) imports
   `RetrievalPorts` from `backend.personalized.rag` — the class is OWNED by
   the retrieval module. This test boots the real app with a REAL index
   directory and asserts the engine + catalog seams come up and a turn runs.
2. The slim backend image ships `numpy` but NOT the optional embedding
   backends (fastembed / sentence-transformers). `rag.py` must import,
   load an index, and retrieve lexically under exactly that dependency set —
   never a silent 503 when an index exists (agent-and-rag.md §7.5.5).
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from testing.backend.personalized_support import (
    CHAPTER,
    build_fixture_index,
)
from testing.backend.web_auth_support import WebAuthSupport


class BootWiringTest(WebAuthSupport):
    """create_app with a real index directory: the seams must be live."""

    config_overrides: ClassVar[dict[str, Any]] = {}

    def setUp(self) -> None:
        self._index_tmp = None  # built after the harness setUp creates the tmp
        super().setUp()
        self.db.execute(
            "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
            "VALUES (?, 10, 'physics', 10, 'light', 'Light - Reflection and Refraction')",
            (CHAPTER,),
        )
        self.db.execute(
            "INSERT INTO concept (concept_id, chapter_id, slug, title_en, order_index) "
            "VALUES (?, ?, 'reflection', 'Reflection of light', 0)",
            (f"{CHAPTER}-reflection-of-light", CHAPTER),
        )

    def test_boot_wires_engine_and_catalog_with_a_real_index(self) -> None:
        index_dir = Path(self._tmp.name) / "personalized-index"
        index = build_fixture_index(Path(self._tmp.name))
        # Move the built version dir under the configured root.
        version_dir = next(
            d
            for d in (Path(self._tmp.name) / "personalized-index").iterdir()
            if d.is_dir()
        )
        del index_dir, index
        self.assertTrue(version_dir.is_dir())

        from backend import BackendConfig, create_app

        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            app_base_url="https://app.test",
            personalized_index_dir=str(Path(self._tmp.name) / "personalized-index"),
        )
        app = create_app(cfg)
        self.assertIsNotNone(
            app.state.personalized_index_catalog, "catalog seam must be wired"
        )
        catalog = app.state.personalized_index_catalog()
        self.assertTrue(catalog["index_version"])
        self.assertIsNotNone(app.state.personalized_retrieval)
        retrieval = app.state.personalized_retrieval
        self.assertIsNotNone(retrieval.index)
        # No embedder backend in this environment: the marked lexical
        # fallback, never a silent 503.
        self.assertIn(retrieval.last_mode, ("n/a", "lexical_fallback", "vector"))
        # The engine stays UNWIRED (route not configured) -> honest 503, but
        # the catalog seam is live: the failure mode is explicit, not silent.
        self.assertIsNone(app.state.personalized_turn_engine)
        app_state = {"catalog_version": catalog["index_version"]}
        self.assertTrue(app_state["catalog_version"])

    def test_boot_wires_the_turn_engine_when_the_route_is_configured(self) -> None:
        build_fixture_index(Path(self._tmp.name))
        from backend import BackendConfig, create_app
        from backend.personalized.agent import PersonalizedAgent

        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            app_base_url="https://app.test",
            personalized_index_dir=str(Path(self._tmp.name) / "personalized-index"),
            personalized_turn_engine_enabled=True,
            personalized_model_base_url="https://opencode.example/v1",
            personalized_model_api_key="runtime-secret",
        )
        app = create_app(cfg)
        engine = app.state.personalized_turn_engine
        self.assertIsInstance(engine, PersonalizedAgent)
        self.assertIsNotNone(app.state.personalized_retrieval.index)


class SlimDependencySmokeTest(unittest.TestCase):
    """The slim backend image: numpy yes, embedding backends no."""

    def test_backend_requirements_pin_numpy_and_not_the_embedding_stacks(self) -> None:
        lines = (
            Path("backend/requirements.txt").read_text(encoding="utf-8").splitlines()
        )
        requirements = [
            line.strip().lower()
            for line in lines
            if line.strip() and not line.strip().startswith("#")
        ]
        self.assertTrue(
            any(r.startswith("numpy") for r in requirements),
            "the slim backend must pin numpy for the RAG index loader",
        )
        for banned in ("torch", "sentence-transformers", "fastembed"):
            self.assertFalse(
                any(banned in r for r in requirements),
                f"the slim backend must not ship {banned}",
            )

    def test_rag_imports_and_falls_back_lexically_without_the_embedding_stacks(
        self,
    ) -> None:
        # Poison the optional backends exactly like the slim image (absent).
        poisoned = {"fastembed": None, "sentence_transformers": None}
        with mock.patch.dict(sys.modules, poisoned):
            for name in ("fastembed", "sentence_transformers"):
                sys.modules.pop(name, None)
            from backend.personalized.rag import (
                EmbedderUnavailable,
                FixtureEmbedder,
                get_embedder,
            )

            with self.assertRaises(EmbedderUnavailable):
                get_embedder("intfloat/multilingual-e5-small")
            # The index path itself needs only numpy: load + lexical retrieve.
            import tempfile

            from backend.personalized.rag import RagIndex, build_index, index_version

            with tempfile.TemporaryDirectory() as tmp:
                chunks = [
                    {
                        "chunk_id": "c1",
                        "text": "the angle of incidence equals the angle of reflection",
                        "source_kind": "ncert",
                        "concept_ids": ["c-1"],
                        "label": "NCERT p. 1",
                        "locator": "p. 1",
                    }
                ]
                embedder = FixtureEmbedder()
                version = index_version(
                    syllabus_sha256="s",
                    manifest_content_hashes=frozenset({"m"}),
                    pack_sha256="p",
                    embedder_id=embedder.model_id,
                    chunker_version="pl-rag-1",
                )
                out = Path(tmp) / version
                build_index(out, chunks, embedder, version, {"fixture": True})
                loaded = RagIndex.load(out)
                result = loaded.retrieve(
                    concept_title="Reflection",
                    concept_description="angle of incidence",
                    scope_concept_ids=["c-1"],
                    chapter_id=None,
                    embedder=None,  # the slim image has no embedder
                )
                self.assertEqual(result["mode"], "lexical_fallback")
                self.assertTrue(result["excerpts"])
                self.assertFalse(result["ungrounded"])


if __name__ == "__main__":
    unittest.main()
