"""Shared hermetic seams for the PL2 agent/turn tests (data-and-api.md §6).

SQLite in memory (the real migration), a scripted fake `ModelClient`, a
static in-memory `BankSource`, and a tiny fixture RAG index built in a temp
dir with the deterministic `FixtureEmbedder`. No key, no network, no model.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from backend.personalized.agent import TurnUsage
from backend.personalized.rag import (
    FixtureEmbedder,
    RagIndex,
    build_index,
    index_version,
)
from backend.personalized.store import PersonalizedStore

CHAPTER = "class-10-light-reflection-and-refraction"
CONCEPT_A = f"{CHAPTER}-reflection-of-light"
CONCEPT_B = f"{CHAPTER}-spherical-mirrors"

_CONCEPT_ROWS = [
    (
        CONCEPT_A,
        "Reflection of light",
        "The two laws of reflection and the image formed by a plane mirror.",
        "[]",
        0,
    ),
    (
        CONCEPT_B,
        "Spherical mirrors",
        "Concave and convex mirrors, pole, centre and radius of curvature, principal focus and ray diagrams.",
        json.dumps([CONCEPT_A]),
        1,
    ),
]

_MCQ_ROW = (
    "q-mcq-1-en",
    "q-mcq-1",
    CONCEPT_A,
    "mcq",
    "easy",
    "A ray strikes a plane mirror with 30 degrees incidence. What is the angle of reflection?",
    '["30 degrees","60 degrees","15 degrees","90 degrees"]',
    '{"index": 0}',
)
_MCQ_MED = (
    "q-mcq-2-en",
    "q-mcq-2",
    CONCEPT_A,
    "mcq",
    "medium",
    "Which law does a periscope rely on?",
    '["First law","Second law","Neither","Both"]',
    '{"index": 1}',
)
_NUMERIC_ROW = (
    "q-num-1-en",
    "q-num-1",
    CONCEPT_B,
    "numeric",
    "hard",
    "The radius of curvature of a concave mirror is 32 cm. What is its focal length in cm?",
    "[]",
    '{"value": 16.0, "unit": "cm"}',
)
_EASY_FOR_B = (
    "q-mcq-3-en",
    "q-mcq-3",
    CONCEPT_B,
    "mcq",
    "easy",
    "Which mirror is used as a vehicle rear-view mirror?",
    '["Concave","Convex","Plane","Parabolic"]',
    '{"index": 1}',
)


class FakeModelClient:
    """Scripted `ModelClient`: streamed teach deltas + one decide JSON per
    turn. Records the prompts it was given so injection tests assert on the
    assembled payload."""

    model_id = "fake-teach-1"

    def __init__(
        self,
        *,
        teach_text: str = (
            "Light bounces off smooth surfaces. "
            "The angle of incidence equals the angle of reflection [S1].\n\n"
            "Key statement: equal angles about the normal.\n\n"
            "Now answer the check that follows."
        ),
        decide: dict[str, Any] | None = None,
        stream_error: Exception | None = None,
        decide_error: Exception | None = None,
    ) -> None:
        self.teach_text = teach_text
        self.decide_payload = decide or {
            "check": {
                "kind": "mcq",
                "question": "generated fallback check",
                "options": [{"id": "A", "text": "one"}, {"id": "B", "text": "two"}],
                "answer": "B",
                "explanation": "Because two.",
                "concept_id": CONCEPT_A,
                "level": 1,
                "misconception": None,
                "source": {"kind": "generated", "item_id": None},
            },
            "mastery_signal": {"concept_id": CONCEPT_A, "status": "getting_there"},
            "next_action": "ask_check",
            "citations": [{"excerpt_id": "S1", "locator": "p. 148"}],
            "ungrounded": False,
        }
        self.stream_error = stream_error
        self.decide_error = decide_error
        self.teach_prompts: list[list[dict[str, str]]] = []
        self.decide_prompts: list[list[dict[str, str]]] = []
        self._pending: list[TurnUsage] = []

    def stream(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> Iterator[str]:
        self.teach_prompts.append(messages)
        if self.stream_error is not None:
            raise self.stream_error
        for delta in (self.teach_text[:20], self.teach_text[20:]):
            if delta:
                yield delta
        self._pending.append(
            TurnUsage(
                stage="teach",
                model=self.model_id,
                input_tokens=100,
                output_tokens=40,
                latency_ms=50,
                first_token_ms=5,
            )
        )

    def complete_json(
        self, messages: list[dict[str, str]], *, session_id: str
    ) -> dict[str, Any]:
        self.decide_prompts.append(messages)
        if self.decide_error is not None:
            raise self.decide_error
        self._pending.append(
            TurnUsage(
                stage="decide",
                model=self.model_id,
                input_tokens=90,
                output_tokens=30,
                latency_ms=40,
            )
        )
        return self.decide_payload

    def drain_usage(self) -> list[TurnUsage]:
        rows = self._pending
        self._pending = []
        return rows


class StaticBank:
    """The `BankSource` seam over an in-memory row list."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows

    def candidates(
        self, concept_ids: list[str], level: int, *, limit: int = 6
    ) -> list[dict[str, Any]]:
        difficulty = {1: "easy", 2: "medium", 3: "hard"}.get(level, "hard")
        return [
            r
            for r in self.rows
            if r["concept_id"] in concept_ids and r["difficulty"] == difficulty
        ][:limit]

    def item(self, item_id: str) -> dict[str, Any] | None:
        for row in self.rows:
            if row["base_item_id"] == item_id:
                return row
        return None


def default_bank() -> StaticBank:
    rows = []
    for question_id, base_id, concept, kind, difficulty, prompt, options, answer in (
        _MCQ_ROW,
        _MCQ_MED,
        _NUMERIC_ROW,
        _EASY_FOR_B,
    ):
        rows.append(
            {
                "question_id": question_id,
                "base_item_id": base_id,
                "concept_id": concept,
                "type": kind,
                "difficulty": difficulty,
                "prompt": prompt,
                "options": json.loads(options),
                "answer": json.loads(answer),
                "explanation": "The bank's stored explanation.",
                "misconception": "Angle measured from the surface.",
            }
        )
    return StaticBank(rows)


def build_fixture_index(tmp_dir: Path) -> RagIndex:
    """A tiny deterministic index (fixture embedder) with one chunk per
    source kind, scoped to the two probe concepts."""
    chunks: list[dict[str, Any]] = [
        {
            "chunk_id": "ncert-science-10#p0148c001",
            "text": "The angle of incidence is equal to the angle of reflection. The image formed by a plane mirror is virtual and erect.",
            "source_kind": "ncert",
            "concept_ids": [CONCEPT_A],
            "label": "NCERT Class 10 Science, Ch. 10, p. 148",
            "locator": "p. 148",
            "book_id": "ncert-science-10",
            "chapter_no": 10,
            "page_from": 148,
            "page_to": 148,
        },
        {
            "chunk_id": f"lesson:{CHAPTER}:b-02",
            "text": "Spherical mirrors: a concave mirror converges light; the principal focus is where parallel rays meet.",
            "source_kind": "lesson",
            "concept_ids": [CONCEPT_B],
            "label": "Lesson: Light - Reflection and Refraction · Mirrors",
            "locator": "lesson block b-02",
            "course_id": CHAPTER,
            "block_id": "b-02",
            "block_type": "text",
            "lesson_title": "Light - Reflection and Refraction",
            "content_hash": "sha256:fixture",
        },
        {
            "chunk_id": "glossary:normal",
            "text": "Glossary term: normal. The perpendicular line to a mirror surface at the point of incidence.",
            "source_kind": "glossary",
            "concept_ids": [],
            "label": "Glossary: normal",
            "locator": "physics glossary",
        },
        {
            "chunk_id": f"syllabus:{CONCEPT_A}",
            "text": "Concept: Reflection of light. Chapter: Light. The two laws of reflection.",
            "source_kind": "syllabus",
            "concept_ids": [CONCEPT_A],
            "label": "Syllabus: Light · Reflection of light",
            "locator": "NCERT sections 10.1",
            "chapter_id": CHAPTER,
        },
    ]
    embedder = FixtureEmbedder()
    version = index_version(
        syllabus_sha256="fixture-syllabus",
        manifest_content_hashes=frozenset({"sha256:fixture"}),
        pack_sha256="fixture-pack",
        embedder_id=embedder.model_id,
        chunker_version="pl-rag-1",
    )
    out_dir = tmp_dir / "personalized-index" / version
    build_index(
        out_dir,
        chunks,
        embedder,
        version,
        {"fixture": True},
    )
    return RagIndex.load(out_dir)


class PersonalizedAgentSupport(unittest.TestCase):
    """DB + store + session seeding shared by the agent/turn tests."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        from db.engine import DatabaseEngine
        from db.migrate import upgrade_db

        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=False)
        upgrade_db(self.db)
        self.db.execute(
            "INSERT INTO users (user_id, email) VALUES ('u-1', 'asha@example.com')"
        )
        self.db.execute(
            "INSERT INTO users (user_id, email) VALUES ('u-2', 'other@example.com')"
        )
        self.db.execute(
            "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
            "VALUES (?, 10, 'physics', 10, 'light', 'Light - Reflection and Refraction')",
            (CHAPTER,),
        )
        for concept_id, title, description, prerequisites, order in _CONCEPT_ROWS:
            self.db.execute(
                "INSERT INTO concept (concept_id, chapter_id, slug, title_en, description, "
                "prerequisites, order_index) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    concept_id,
                    CHAPTER,
                    concept_id.rsplit("-", 1)[-1],
                    title,
                    description,
                    prerequisites,
                    order,
                ),
            )
        self.store = PersonalizedStore(self.db)
        self.session = self.store.create_session(
            user_id="u-1",
            chapter_id=CHAPTER,
            class_level=10,
            title="Light · Reflection of light",
            concept_ids=[CONCEPT_A, CONCEPT_B],
            weakness_text="I don't get why the image flips",
            skip_diagnostic=True,
        )
        self.session_id = self.session["session_id"]

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _force_diagnose(self) -> None:
        """Reset the probe session to the diagnose stage (column + state)."""
        import json as _json

        session = self.store.get_session("u-1", self.session_id)
        assert session is not None, "probe session must exist"
        state = _json.loads(_json.dumps(session["state"]))
        state["started_at_stage"] = "diagnose"
        self.db.execute(
            "UPDATE personalized_session SET stage = 'diagnose', state = ? WHERE session_id = ?",
            (_json.dumps(state), self.session_id),
        )

    def _open_check_id(self) -> str | None:
        from backend.personalized import state as _sm

        state = self.fresh_state()
        open_check = _sm.open_check(state)
        return str(open_check["check_id"]) if open_check else None

    def _run(self, agent, ctx) -> list:  # type: ignore[no-untyped-def]
        from backend.personalized.agent import PersonalizedAgent

        assert isinstance(agent, PersonalizedAgent)
        return list(agent.run_turn(ctx))

    def fresh_state(self) -> dict[str, Any]:
        session = self.store.get_session("u-1", self.session_id)
        assert session is not None
        return json.loads(json.dumps(session["state"]))
