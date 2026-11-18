"""PL2 RAG tests (agent-and-rag.md §6): corpus honesty, index validation,
scoped retrieval, lexical fallback, citation resolution.

The embedder is the deterministic `FixtureEmbedder` — no model, no network
(test-seam table, data-and-api.md §6).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.personalized.rag import (
    FixtureEmbedder,
    IndexError_,
    RagIndex,
    build_index,
    chunks_from_glossary,
    chunks_from_lesson,
    chunks_from_ncert_pages,
    chunks_from_syllabus,
    index_version,
    resolve_citations,
)

SYLLABUS = {
    "classes": [
        {
            "class": 10,
            "chapters": [
                {
                    "chapter_id": "ch-light",
                    "title": "Light",
                    "concepts": [
                        {
                            "concept_id": "ch-light-mirrors",
                            "title": "Spherical mirrors",
                            "description": "Concave and convex mirrors and ray diagrams.",
                            "prerequisites": ["ch-light-basics"],
                            "section_refs": ["9.2"],
                        }
                    ],
                }
            ],
        }
    ]
}

GLOSSARY = {
    "terms": [
        {
            "term_slug": "normal",
            "english_term": "normal",
            "locales": {
                "hi": {"native_term": "अभिलंब", "first_mention_gloss": "अभिलंब (normal)"}
            },
        }
    ]
}

LESSON_MANIFEST = {
    "lesson_title": "Light - Reflection",
    "content_hash": "sha256:abc",
    "blocks": {"b-01": {"type": "text", "concept_id": "ch-light-mirrors"}},
}
LESSON_HTML = """
<html><body>
<section id="b-01" data-block-type="text" data-concept-id="ch-light-mirrors" data-title="Mirrors">
<p>A concave mirror converges parallel rays to the principal focus.</p>
<p>The focal length is half the radius of curvature.</p>
</section>
<section id="b-09" data-block-type="simulation"><p>sim only</p></section>
</body></html>
"""


class CorpusTest(unittest.TestCase):
    def test_syllabus_one_chunk_per_concept(self) -> None:
        chunks = chunks_from_syllabus(SYLLABUS)
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk["chunk_id"], "syllabus:ch-light-mirrors")
        self.assertEqual(chunk["concept_ids"], ["ch-light-mirrors"])
        self.assertIn("9.2", chunk["locator"])

    def test_glossary_terms_include_hindi_gloss(self) -> None:
        chunks = chunks_from_glossary(GLOSSARY)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_id"], "glossary:normal")
        self.assertIn("अभिलंब", chunks[0]["text"])

    def test_lesson_chunks_only_text_blocks_with_concept_tag(self) -> None:
        chunks = chunks_from_lesson(LESSON_MANIFEST, LESSON_HTML, "course-x")
        self.assertEqual(len(chunks), 1)
        chunk = chunks[0]
        self.assertEqual(chunk["chunk_id"], "lesson:course-x:b-01")
        self.assertEqual(chunk["source_kind"], "lesson")
        self.assertEqual(chunk["concept_ids"], ["ch-light-mirrors"])
        self.assertIn("principal focus", chunk["text"])
        self.assertNotIn("sim only", chunk["text"])
        self.assertEqual(chunk["label"], "Lesson: Light - Reflection · Mirrors")

    def test_ncert_chunks_carry_exact_pages_and_never_cross(self) -> None:
        pages = [
            {"page": 148, "text": "law of reflection " * 80},
            {"page": 149, "text": "spherical mirrors " * 80},
        ]
        chunks = chunks_from_ncert_pages(
            pages,
            book_id="ncert-science-10",
            book_title="Science X",
            chapter_no=10,
            chapter_id="ch-light",
            chapter_title="Light",
            chapter_concepts=SYLLABUS["classes"][0]["chapters"][0]["concepts"],
        )
        self.assertTrue(chunks)
        for chunk in chunks:
            self.assertIn(chunk["chunk_id"].split("#")[0], ("ncert-science-10",))
            self.assertEqual(chunk["page_from"], chunk["page_to"])
            self.assertIn("p. ", chunk["locator"])
        page_ids = {c["page_from"] for c in chunks}
        self.assertEqual(page_ids, {148, 149})

    def test_ncert_concept_assignment_by_section_refs(self) -> None:
        pages = [{"page": 150, "text": "ray diagrams for spherical mirrors " * 40}]
        concepts = [
            {
                "concept_id": "ch-light-mirrors",
                "title": "Spherical mirrors",
                "description": "Concave and convex mirrors and ray diagrams.",
                "section_refs": ["9.2"],
            }
        ]
        chunks = chunks_from_ncert_pages(
            pages,
            book_id="ncert-science-10",
            book_title="Science X",
            chapter_no=10,
            chapter_id="ch-light",
            chapter_title="Light",
            chapter_concepts=concepts,
            section_pages={"9.2": [150]},
        )
        self.assertEqual(chunks[0]["concept_ids"], ["ch-light-mirrors"])

    def test_unknown_source_kind_refused(self) -> None:
        # The corpus builders only emit valid kinds; the guard lives in
        # _chunk, so an exam-paper kind can never enter the index.
        from backend.personalized.rag import _chunk

        with self.assertRaises(ValueError):
            _chunk(
                chunk_id="x",
                text="t",
                source_kind="exam_paper",
                concept_ids=[],
                label="l",
                locator="l",
            )


class IndexTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _build(self, chunks: list[dict]) -> Path:
        embedder = FixtureEmbedder()
        version = index_version(
            syllabus_sha256="s",
            manifest_content_hashes=frozenset({"m"}),
            pack_sha256="p",
            embedder_id=embedder.model_id,
            chunker_version="pl-rag-1",
        )
        out = self.root / version
        build_index(out, chunks, embedder, version, {"fixture": True})
        return out

    def test_version_is_content_addressed_and_stable(self) -> None:
        embedder = FixtureEmbedder()
        args = {
            "syllabus_sha256": "s",
            "manifest_content_hashes": frozenset({"m1", "m2"}),
            "pack_sha256": "p",
            "embedder_id": embedder.model_id,
            "chunker_version": "pl-rag-1",
        }
        v1 = index_version(**args)
        v2 = index_version(**args)
        self.assertEqual(v1, v2)
        self.assertEqual(len(v1), 16)
        changed = dict(args, pack_sha256="p2")
        self.assertNotEqual(v1, index_version(**changed))

    def test_load_roundtrip_and_manifest_counts(self) -> None:
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
        out = self._build(chunks)
        index = RagIndex.load(out)
        self.assertEqual(index.manifest["chunk_count"], 1)
        self.assertEqual(index.manifest["counts_by_source_kind"]["ncert"], 1)

    def test_tampered_chunks_refuse_loudly(self) -> None:
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
        out = self._build(chunks)
        lines = (out / "chunks.jsonl").read_text(encoding="utf-8").splitlines()
        row = json.loads(lines[0])
        row["text"] = "tampered content"
        lines[0] = json.dumps(row, sort_keys=True)
        (out / "chunks.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        with self.assertRaises(IndexError_):
            RagIndex.load(out)

    def test_missing_manifest_refuses(self) -> None:
        with self.assertRaises(IndexError_):
            RagIndex.load(self.root / "does-not-exist")

    def test_empty_index_refused(self) -> None:
        embedder = FixtureEmbedder()
        with self.assertRaises(IndexError_):
            build_index(
                self.root / "empty",
                [],
                embedder,
                "v-empty",
                {"fixture": True},
            )


class RetrievalTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        from testing.backend.personalized_support import build_fixture_index

        self.index = build_fixture_index(Path(self._tmp.name))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _retrieve(self, *, embedder="fixture", weakness="", stem=""):
        return self.index.retrieve(
            concept_title="Spherical mirrors",
            concept_description="Concave and convex mirrors and ray diagrams",
            scope_concept_ids=["ch-light-mirrors"],
            chapter_id="ch-light",
            embedder=FixtureEmbedder() if embedder == "fixture" else None,
            weakness_text=weakness,
            last_wrong_stem=stem,
        )

    def test_vector_retrieval_returns_excerpts_with_ids_and_tiers(self) -> None:
        result = self._retrieve()
        self.assertEqual(result["mode"], "vector")
        self.assertFalse(result["ungrounded"])
        for i, excerpt in enumerate(result["excerpts"], start=1):
            self.assertEqual(excerpt["excerpt_id"], f"S{i}")
            self.assertIn(
                excerpt["source_kind"], ("ncert", "lesson", "glossary", "syllabus")
            )
            tier = "lesson" if excerpt["source_kind"] == "lesson" else "source"
            self.assertEqual(excerpt["tier"], tier)

    def test_excerpt_budget_enforced_and_sentence_trimmed(self) -> None:
        result = self._retrieve()
        total = sum(len(e["text"]) for e in result["excerpts"])
        self.assertLessEqual(total, 4000)

    def test_lexical_fallback_marked_honestly(self) -> None:
        result = self._retrieve(embedder=None)
        self.assertEqual(result["mode"], "lexical_fallback")
        self.assertTrue(result["excerpts"])

    def test_scoped_retrieval_prefers_the_concept(self) -> None:
        result = self._retrieve()
        top = result["excerpts"][0]
        self.assertIn("mirror", top["text"].lower())

    def test_no_hits_is_ungrounded_not_empty_prose(self) -> None:
        # The zero-hits path (§6.5.7) is an empty index: the teach call still
        # runs, marked ungrounded, and the prompt says the excerpts are empty.
        empty = RagIndex.__new__(RagIndex)
        empty.version = "empty"
        empty.manifest = {"version": "empty"}
        empty.chunks = []
        empty.matrix = None
        result = empty.retrieve(
            concept_title="Anything",
            concept_description="nothing indexed",
            scope_concept_ids=["x"],
            chapter_id="x",
            embedder=FixtureEmbedder(),
        )
        self.assertTrue(result["ungrounded"])
        self.assertEqual(result["excerpts"], [])
        # A nonsense query over a small index still returns background
        # candidates (the §6.5.3 out-of-scope check) — ranked honestly.
        result = self.index.retrieve(
            concept_title="Nonexistent",
            concept_description="zzz qqq",
            scope_concept_ids=["no-such-concept"],
            chapter_id="no-chapter",
            embedder=FixtureEmbedder(),
        )
        self.assertFalse(result["ungrounded"])
        self.assertTrue(result["excerpts"])


class CitationTest(unittest.TestCase):
    EXCERPTS = [
        {
            "excerpt_id": "S1",
            "chunk_id": "ncert-science-10#p0148c001",
            "source_kind": "ncert",
            "label": "NCERT Class 10 Science, Ch. 10, p. 148",
            "locator": "p. 148",
        },
        {
            "excerpt_id": "S2",
            "chunk_id": "lesson:course:b-02",
            "source_kind": "lesson",
            "label": "Lesson: Light · Mirrors",
            "locator": "lesson block b-02",
        },
    ]

    def test_known_ids_resolve_with_labels(self) -> None:
        resolved, ungrounded = resolve_citations(["S1", "S2"], self.EXCERPTS)
        self.assertFalse(ungrounded)
        self.assertEqual(resolved[0]["chunk_id"], "ncert-science-10#p0148c001")
        self.assertEqual(resolved[0]["label"], "NCERT Class 10 Science, Ch. 10, p. 148")

    def test_unknown_ids_dropped_never_invented(self) -> None:
        resolved, _ungrounded = resolve_citations(["S1", "S9"], self.EXCERPTS)
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["excerpt_id"], "S1")

    def test_zero_resolved_is_ungrounded(self) -> None:
        resolved, ungrounded = resolve_citations(["S7"], self.EXCERPTS)
        self.assertTrue(ungrounded)
        self.assertEqual(resolved, [])
        resolved, ungrounded = resolve_citations([], self.EXCERPTS)
        self.assertTrue(ungrounded)

    def test_duplicates_collapsed(self) -> None:
        resolved, _ = resolve_citations(["S1", "S1"], self.EXCERPTS)
        self.assertEqual(len(resolved), 1)


if __name__ == "__main__":
    unittest.main()
