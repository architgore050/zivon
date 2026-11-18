"""Deterministic checkers for the PL cards `EV-PL-001`/`EV-PL-002`.

Zero model calls, zero network, zero secrets (the deterministic-first funnel,
`docs/specs/personalized-learning/evals.md`). The state-machine checker
REPLAYS the golden transcripts through the real machine
(`backend/personalized/state.py`) — the same functions the runtime uses — so
an eval cannot drift from the code it claims to measure. Scoring rules are
reused verbatim via `state.score_answer`; citation resolution via
`rag.resolve_citations`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.personalized import state as sm
from backend.personalized.rag import FixtureEmbedder, RagIndex, resolve_citations

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

CHECK_SM = "DET-PL01-SM"
CHECK_SCHEMA = "DET-PL01-SCHEMA"
CHECK_SCORE = "DET-PL01-SCORE"
CHECK_CITATIONS = "DET-PL02-CITATIONS"
CHECK_PROVENANCE = "DET-PL02-PROVENANCE"
CHECK_SCOPE = "DET-PL02-SCOPE"
CHECK_FALLBACK = "DET-PL02-FALLBACK"

_GOLDEN_SESSIONS = (
    "evals/goldens/personalized/sessions/class-10-light-weakness/correct-first.json",
    "evals/goldens/personalized/sessions/class-10-light-weakness/wrong-then-adapt.json",
    "evals/goldens/personalized/sessions/class-10-light-weakness/skip-all.json",
    "evals/goldens/personalized/sessions/class-9-motion-diagnostic/diagnostic-first.json",
)
# The state-machine walk replays the teach→check→adapt→worked-example and the
# skip/coverage transcripts; the diagnostic transcript's d-1 arming rides the
# schema/citation checks below (known gap: its walk is not replayed by SM).
_SM_SESSIONS = tuple(_GOLDEN_SESSIONS[:3])
_GOLDEN_INDEX_GLOB = "evals/goldens/personalized/rag-index/*"


def _issue(check_id: str, severity: str, message: str) -> IssueRecord:
    return IssueRecord(severity=severity, message=message, check_id=check_id)


def _load_transcript(cfg: EvalConfig, rel: str) -> dict[str, Any]:
    return json.loads((cfg.repo_root / rel).read_text(encoding="utf-8"))


# --- EV-PL-001 ------------------------------------------------------------------


def check_state_machine(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL01-SM: replay the transcripts through the real state machine.

    The goldens record the machine-replayable walk (teach slices, armed
    checks with their server-side keys, scored answers, skips, the
    diagnostic close-out) plus the honest mastery summary; the replay must
    reproduce both.
    """
    issues: list[IssueRecord] = []
    for rel in _SM_SESSIONS:
        transcript = _load_transcript(cfg, rel)
        name = Path(rel).stem
        concepts = sorted({row["concept_id"] for row in transcript["mastery_summary"]})
        state = sm.initial_state(concepts)
        keys = transcript.get("check_keys", {})
        concept_of_check: dict[str, str] = {}
        open_check_id: str | None = None
        try:
            for turn in transcript["turns"]:
                payload = turn.get("payload") or {}
                label = f"{name}:{turn['client_turn_id']}"
                if payload.get("skipped"):
                    sm.skip_concept(state, str(payload["skipped"]))
                    continue
                if payload.get("diagnostic") is not None:
                    for item_key, correct in payload["diagnostic"]["answers"].items():
                        sm.record_diagnostic(state, item_key, bool(correct))
                    sm.finish_diagnostic(state)
                    continue
                check = payload.get("check") or {}
                key = keys.get(str(check.get("check_id", ""))) or turn.get("answer_key")
                if check and key is not None:
                    cid = str(check["check_id"])
                    concept_id = str(check["concept_id"])
                    # The teach/adapt slice precedes the check it arms.
                    if (
                        int(
                            state["concepts"]
                            .get(concept_id, {})
                            .get("taught_slices", 0)
                        )
                        == 0
                    ):
                        sm.record_teach_slice(state, concept_id)
                    try:
                        sm.set_open_check(
                            state,
                            check_id=cid,
                            concept_id=concept_id,
                            level=int(check["level"]),
                            kind=str(check["kind"]),
                            diagnostic=str(state.get("started_at_stage")) == "diagnose",
                        )
                    except sm.StateError as exc:
                        issues.append(
                            _issue(CHECK_SM, "fatal", f"{label}: arming refused: {exc}")
                        )
                        break
                    if open_check_id is not None and open_check_id != cid:
                        issues.append(
                            _issue(
                                CHECK_SM,
                                "fatal",
                                f"{label}: a second check armed while {open_check_id} is open",
                            )
                        )
                    open_check_id = cid
                    concept_of_check[cid] = concept_id
                    continue
                if turn.get("role") == "student" and "correct" in payload:
                    if open_check_id is None:
                        issues.append(
                            _issue(
                                CHECK_SM,
                                "fatal",
                                f"{label}: scored an answer with no open check",
                            )
                        )
                        break
                    sm.record_check_result(state, correct=bool(payload["correct"]))
                    sm.bump_turn(state)
                    open_check_id = None
                    continue
                if payload.get("stage") == "worked_example":
                    sm.worked_example_fallback(state)
                    continue
                if payload.get("stage") in ("teach", "adapt") and payload.get(
                    "mastery"
                ):
                    sm.record_teach_slice(
                        state, str(payload["mastery"].get("concept_id", concepts[0]))
                    )
            if sm.turn_cap_reached(state):
                issues.append(_issue(CHECK_SM, "fatal", f"{name}: turn cap exceeded"))
            if open_check_id is not None and not any(
                t.get("payload", {}).get("stage") == "worked_example"
                for t in transcript["turns"]
            ):
                issues.append(
                    _issue(
                        CHECK_SM, "fatal", f"{name}: the walk ends with an open check"
                    )
                )
            for row in transcript["mastery_summary"]:
                concept = state["concepts"].get(row["concept_id"])
                if concept is None:
                    issues.append(
                        _issue(
                            CHECK_SM,
                            "fatal",
                            f"{name}: unknown concept {row['concept_id']}",
                        )
                    )
                    continue
                status = sm.concept_mastery_status(concept)
                if status != row["status"]:
                    issues.append(
                        _issue(
                            CHECK_SM,
                            "fatal",
                            f"{name}: {row['concept_id']} status {status} != golden {row['status']}",
                        )
                    )
                if row["status"] == "mastered" and not set(row["levels_passed"]) >= {
                    2,
                    3,
                }:
                    issues.append(
                        _issue(
                            CHECK_SM,
                            "fatal",
                            f"{name}: mastered without L2+L3 evidence",
                        )
                    )
                if row["status"] == "mastered" and row.get("skipped"):
                    issues.append(
                        _issue(
                            CHECK_SM, "fatal", f"{name}: skipped counted as mastered"
                        )
                    )
        except (KeyError, ValueError, sm.StateError) as exc:
            issues.append(_issue(CHECK_SM, "fatal", f"{name}: replay crashed: {exc}"))
    return issues


def check_turn_schema(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL01-SCHEMA: the assembled-turn shape; no answer key in payloads."""
    issues: list[IssueRecord] = []
    for rel in _GOLDEN_SESSIONS:
        transcript = _load_transcript(cfg, rel)
        name = Path(rel).stem
        for turn in transcript["turns"]:
            payload = turn.get("payload") or {}
            if not payload or turn.get("role") != "tutor" or "teaching" not in payload:
                continue
            label = f"{name}:{turn['client_turn_id']}"
            if payload.get("schema_version") != 1:
                issues.append(
                    _issue(CHECK_SCHEMA, "fatal", f"{label}: schema_version missing")
                )
            if "ungrounded" not in payload:
                issues.append(
                    _issue(CHECK_SCHEMA, "fatal", f"{label}: ungrounded flag missing")
                )
            if "rag_index_version" not in payload:
                issues.append(
                    _issue(CHECK_SCHEMA, "fatal", f"{label}: rag_index_version missing")
                )
            if payload.get("prompt_version") != "pl-1":
                issues.append(
                    _issue(CHECK_SCHEMA, "fatal", f"{label}: prompt_version != pl-1")
                )
            blob = json.dumps(payload)
            if '"answer"' in blob or "answer_key" in blob:
                issues.append(
                    _issue(
                        CHECK_SCHEMA,
                        "fatal",
                        f"{label}: an answer key leaked into a payload",
                    )
                )
    return issues


def check_scoring_rules(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL01-SCORE: the §3.3 scoring rules, exercised through the real scorer."""
    issues: list[IssueRecord] = []
    cases: list[tuple[dict[str, Any], object, bool]] = [
        ({"kind": "mcq", "answer_key": "B"}, "B", True),
        ({"kind": "mcq", "answer_key": "B"}, "b", True),
        ({"kind": "mcq", "answer_key": "B"}, "A", False),
        ({"kind": "numeric", "answer_value": 16.0, "answer_unit": "cm"}, "16", True),
        ({"kind": "numeric", "answer_value": 16.0, "answer_unit": "cm"}, "1.6e1", True),
        ({"kind": "numeric", "answer_value": 16.0, "answer_unit": "cm"}, "17", False),
        (
            {
                "kind": "numeric",
                "answer_value": 16.0,
                "answer_unit": "cm",
                "given_unit": "m",
            },
            "16",
            False,
        ),
    ]
    for check, answer, expected in cases:
        result = sm.score_answer(dict(check), answer)
        if result.correct != expected:
            issues.append(
                _issue(
                    CHECK_SCORE,
                    "fatal",
                    f"scoring {check} <- {answer!r}: expected {expected}, got {result.correct}",
                )
            )
    if not issues:
        for transcript_rel in _GOLDEN_SESSIONS:
            transcript = _load_transcript(cfg, transcript_rel)
            for turn in transcript["turns"]:
                key = turn.get("answer_key")
                if key is None:
                    continue
                payload = turn["payload"]
                answer = str(turn["text"])
                if not answer.strip():
                    continue
                result = sm.score_answer(
                    {
                        "kind": key["kind"],
                        "answer_key": key.get("option"),
                        "answer_value": key.get("value"),
                        "answer_unit": key.get("unit"),
                    },
                    answer,
                )
                if result.correct is not bool(payload.get("correct", result.correct)):
                    issues.append(
                        _issue(
                            CHECK_SCORE,
                            "fatal",
                            f"{transcript_rel}: golden answer disagrees with the scorer",
                        )
                    )
    return issues


# --- EV-PL-002 ------------------------------------------------------------------


def _golden_index(cfg: EvalConfig) -> RagIndex | None:
    root = cfg.repo_root / "evals/goldens/personalized/rag-index"
    for version_dir in sorted(root.iterdir()):
        if version_dir.is_dir():
            return RagIndex.load(version_dir)
    return None


def check_citations(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL02-CITATIONS: every citation resolves; labels are server-built."""
    issues: list[IssueRecord] = []
    index = _golden_index(cfg)
    if index is None:
        return [_issue(CHECK_CITATIONS, "fatal", "golden rag-index missing")]
    chunks_by_id = {c["chunk_id"]: c for c in index.chunks}
    for rel in _GOLDEN_SESSIONS:
        transcript = _load_transcript(cfg, rel)
        name = Path(rel).stem
        for turn in transcript["turns"]:
            payload = turn.get("payload") or {}
            if "teaching" not in payload:
                continue
            citations = payload.get("citations") or []
            if not citations:
                if not payload.get("ungrounded", False):
                    issues.append(
                        _issue(
                            CHECK_CITATIONS,
                            "fatal",
                            f"{name}:{turn['client_turn_id']}: zero citations but ungrounded=false",
                        )
                    )
                continue
            for citation in citations:
                chunk = chunks_by_id.get(str(citation.get("chunk_id")))
                if chunk is None:
                    issues.append(
                        _issue(
                            CHECK_CITATIONS,
                            "fatal",
                            f"{name}:{turn['client_turn_id']}: citation to a chunk not in the index",
                        )
                    )
                    continue
                if str(citation.get("label")) != str(chunk.get("label")):
                    issues.append(
                        _issue(
                            CHECK_CITATIONS,
                            "fatal",
                            f"{name}:{turn['client_turn_id']}: label mismatch for {chunk['chunk_id']}",
                        )
                    )
    # resolve_citations behaviour on the fixture excerpts.
    excerpts = [
        {
            "excerpt_id": "S1",
            "chunk_id": "ncert-science-10#p0148c001",
            "source_kind": "ncert",
            "label": "NCERT Class 10 Science, Ch. 10, p. 148",
            "locator": "p. 148",
        },
    ]
    resolved, ungrounded = resolve_citations(["S1", "S9"], excerpts)
    if ungrounded or len(resolved) != 1:
        issues.append(
            _issue(
                CHECK_CITATIONS,
                "fatal",
                "resolve_citations dropped a known id or kept an unknown one",
            )
        )
    resolved, ungrounded = resolve_citations(["S9"], excerpts)
    if not ungrounded:
        issues.append(
            _issue(
                CHECK_CITATIONS, "fatal", "unknown-only citations must be ungrounded"
            )
        )
    return issues


def check_provenance(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL02-PROVENANCE: manifest hashes, honest page spans, no exam text."""
    issues: list[IssueRecord] = []
    index = _golden_index(cfg)
    if index is None:
        return [_issue(CHECK_PROVENANCE, "fatal", "golden rag-index missing")]
    if index.manifest.get("chunks_sha256") is None:
        issues.append(_issue(CHECK_PROVENANCE, "fatal", "manifest has no chunks hash"))
    for chunk in index.chunks:
        kind = chunk["source_kind"]
        if kind not in ("ncert", "lesson", "glossary", "syllabus"):
            issues.append(
                _issue(
                    CHECK_PROVENANCE,
                    "fatal",
                    f"{chunk['chunk_id']}: unknown source kind {kind}",
                )
            )
        if kind == "ncert" and (
            chunk.get("page_from") != chunk.get("page_to")
            or int(chunk.get("page_from", 0)) < 1
        ):
            issues.append(
                _issue(
                    CHECK_PROVENANCE,
                    "fatal",
                    f"{chunk['chunk_id']}: page span not exact",
                )
            )
        if kind == "lesson" and not str(chunk.get("chunk_id", "")).startswith(
            "lesson:"
        ):
            issues.append(
                _issue(CHECK_PROVENANCE, "fatal", "lesson tier chunk id malformed")
            )
    text_blob = " ".join(str(c["text"]) for c in index.chunks).lower()
    for banned in ("cbse", "previous year paper", "sample paper"):
        if banned in text_blob:
            issues.append(
                _issue(
                    CHECK_PROVENANCE,
                    "fatal",
                    f"index contains exam-paper phrasing: {banned}",
                )
            )
    return issues


def check_retrieval_scope(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL02-SCOPE: scoped retrieval honors the budget and stable ids."""
    issues: list[IssueRecord] = []
    index = _golden_index(cfg)
    if index is None:
        return [_issue(CHECK_SCOPE, "fatal", "golden rag-index missing")]
    chapter = "class-10-light-reflection-and-refraction"
    concept = f"{chapter}-spherical-mirrors"
    result = index.retrieve(
        concept_title="Spherical mirrors",
        concept_description="Concave and convex mirrors and ray diagrams",
        scope_concept_ids=[concept],
        chapter_id=chapter,
        embedder=FixtureEmbedder(),
    )
    total = 0
    for i, excerpt in enumerate(result["excerpts"], start=1):
        if excerpt["excerpt_id"] != f"S{i}":
            issues.append(
                _issue(
                    CHECK_SCOPE,
                    "fatal",
                    f"excerpt id unstable: {excerpt['excerpt_id']}",
                )
            )
        total += len(excerpt["text"])
        concepts = set(excerpt.get("concept_ids") or [])
        chunk = next(c for c in index.chunks if c["chunk_id"] == excerpt["chunk_id"])
        if (
            concepts
            and concept not in concepts
            and chunk.get("chapter_id") not in (chapter, None)
        ):
            issues.append(
                _issue(
                    CHECK_SCOPE,
                    "fatal",
                    f"{excerpt['chunk_id']} outside the queried scope",
                )
            )
    if total > 4000:
        issues.append(
            _issue(CHECK_SCOPE, "fatal", f"excerpt budget exceeded: {total} chars")
        )
    if result["ungrounded"]:
        issues.append(
            _issue(
                CHECK_SCOPE, "fatal", "scoped retrieval over the fixture found nothing"
            )
        )
    return issues


def check_lexical_fallback(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """DET-PL02-FALLBACK: embedder-off retrieval is honest and marked."""
    issues: list[IssueRecord] = []
    index = _golden_index(cfg)
    if index is None:
        return [_issue(CHECK_FALLBACK, "fatal", "golden rag-index missing")]
    result = index.retrieve(
        concept_title="Spherical mirrors",
        concept_description="mirrors",
        scope_concept_ids=[
            "class-10-light-reflection-and-refraction-spherical-mirrors"
        ],
        chapter_id="class-10-light-reflection-and-refraction",
        embedder=None,
    )
    if result["mode"] != "lexical_fallback":
        issues.append(
            _issue(
                CHECK_FALLBACK,
                "fatal",
                f"mode {result['mode']} is not the marked fallback",
            )
        )
    if not result["excerpts"]:
        issues.append(
            _issue(CHECK_FALLBACK, "fatal", "lexical fallback returned no excerpts")
        )
    empty = RagIndex.__new__(RagIndex)
    empty.version = "empty"
    empty.manifest = {}
    empty.chunks = []
    empty.matrix = None
    result = empty.retrieve(
        concept_title="x",
        concept_description="y",
        scope_concept_ids=["z"],
        chapter_id="z",
        embedder=FixtureEmbedder(),
    )
    if not result["ungrounded"] or result["excerpts"]:
        issues.append(
            _issue(CHECK_FALLBACK, "fatal", "an empty index must be ungrounded")
        )
    return issues
