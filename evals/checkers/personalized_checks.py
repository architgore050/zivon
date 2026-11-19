"""Deterministic checkers for the PL cards `EV-PL-001`/`EV-PL-002`/`EV-PL-003`.

Zero model calls, zero network, zero secrets (the deterministic-first funnel,
`docs/specs/personalized-learning/evals.md`). The state-machine checker
REPLAYS the golden transcripts through the real machine
(`backend/personalized/state.py`) — the same functions the runtime uses — so
an eval cannot drift from the code it claims to measure. Scoring rules are
reused verbatim via `state.score_answer`; citation resolution via
`rag.resolve_citations`. The artifact checkers (PL3) reuse the production
lint/spec/cache rules (`backend/personalized/artifacts.py`) instead of
re-implementing them; the two browser-backed checks run the real headless
render gate when Chromium is available and record an honest SKIP otherwise.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from backend.personalized import state as sm
from backend.personalized.artifact_prompt import build_user_message
from backend.personalized.artifact_sandbox import (
    RenderGateUnavailable,
    run_render_gate,
    run_sandbox_escape_test,
)
from backend.personalized.artifacts import (
    ARTIFACT_META_CSP,
    MAX_HTML_BYTES,
    ArtifactBuildError,
    ArtifactSpecError,
    compute_artifact_id,
    ensure_no_student_text,
    lint_artifact_html,
    normalize_fallback,
    validate_artifact_spec,
)
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


GOLDENS_REL = "evals/goldens/personalized/artifacts"

# The seeded-defect corpus (README in the goldens dir): name -> expected rule.
EXPECTED_DEFECT_RULES: dict[str, str] = {
    "external-fetch": "LINT_NETWORK_FETCH",
    "eval": "LINT_EVAL",
    "localstorage": "LINT_STORAGE",
    "form": "LINT_FORM",
    "topnav-link": "LINT_ANCHOR",
    "oversized": "LINT_SIZE",
    "missing-label": "LINT_LABEL_MISSING",
}

# The fixed claim universe the spec fixtures cite against (README).
SPEC_CLAIM_UNIVERSE = {f"c-{i:02d}" for i in range(1, 9)}

# DET-PL03-NO-STUDENT: the synthetic session free text the artifact path must
# never see (spec.md: the weakness and the personal instructions).
NO_STUDENT_CANARY = (
    "PII_CANARY_7f3a my weakness is that I mix up the image with the object"
)
NO_STUDENT_INSTRUCTIONS = "PII_CANARY_9d2e always mention my school name"


def _golden_dir(cfg: EvalConfig) -> Path:
    return cfg.repo_root / GOLDENS_REL


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_artifact_lint_defects(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-LINT`: the golden passes; every seeded defect fails with its
    expected rule."""
    issues: list[IssueRecord] = []
    golden_dir = _golden_dir(cfg)
    golden_path = golden_dir / "good-concave-mirror.html"
    if not golden_path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-LINT"] = (
            "golden artifact missing"
        )
        return issues
    golden_hits = lint_artifact_html(_read(golden_path))
    for hit in golden_hits:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-LINT",
                category="artifact_lint",
                message=f"golden artifact must pass the hard lint: {hit}",
            )
        )
    for name, expected_rule in EXPECTED_DEFECT_RULES.items():
        defect_path = golden_dir / "defects" / f"{name}.html"
        if not defect_path.is_file():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-LINT",
                    category="artifact_lint",
                    message=f"seeded defect {name}.html is missing from the corpus",
                )
            )
            continue
        hits = lint_artifact_html(_read(defect_path))
        rules = {h.split("[")[-1].rstrip("]") for h in hits}
        if expected_rule not in rules:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-LINT",
                    category="artifact_lint",
                    message=f"seeded defect {name}.html did not fail with "
                    f"{expected_rule}; got {sorted(rules) or 'no hits'}",
                )
            )
    return issues


def check_artifact_doc_contract(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-DOC`: the golden carries the meta CSP, the canvas a11y pair,
    label/for pairs, the reduced-motion branch, one h1, and no external URL;
    it stays inside the size/DOM budgets."""
    issues: list[IssueRecord] = []
    golden_path = _golden_dir(cfg) / "good-concave-mirror.html"
    if not golden_path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-DOC"] = (
            "golden artifact missing"
        )
        return issues
    html = _read(golden_path)
    meta_csp = ""
    import re as _re

    for match in _re.finditer(
        r"""<meta[^>]*http-equiv=["']Content-Security-Policy["'][^>]*>""",
        html,
        _re.IGNORECASE,
    ):
        # The CSP value quotes 'none'/'unsafe-inline' internally, so capture
        # by the outer quote style: try double-quoted first, then single.
        content = _re.search(r'content="([^"]+)"', match.group(0), _re.IGNORECASE)
        if not content:
            content = _re.search(r"content='([^']+)'", match.group(0), _re.IGNORECASE)
        if content:
            meta_csp = content.group(1)
    checks: list[tuple[bool, str]] = [
        (
            meta_csp == ARTIFACT_META_CSP,
            "the document must carry the §4 meta CSP byte-exact",
        ),
        (
            'role="img"' in html and "aria-label=" in html and "<canvas" in html,
            "the canvas must carry role=img + an aria-label",
        ),
        ("<h1" in html, "exactly one h1 is required"),
        (
            "prefers-reduced-motion" in html,
            "the reduced-motion branch (static frame + Play) is required",
        ),
        ('aria-live="polite"' in html, "the text mirror must be aria-live=polite"),
        ("<label" in html and "for=" in html, "every control needs a label/for pair"),
        ("matchMedia" in html, "reduced motion is detected via matchMedia"),
        ("addEventListener" in html, "handlers must use addEventListener (no on*=)"),
    ]
    for ok, why in checks:
        if not ok:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-DOC",
                    category="artifact_a11y",
                    message=f"golden artifact contract: {why}",
                )
            )
    if len(html.encode("utf-8")) > MAX_HTML_BYTES:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-DOC",
                category="artifact_size",
                message="golden artifact exceeds the 120 KB budget",
            )
        )
    return issues


def check_artifact_spec_validation(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-SPEC`: valid sim + diagram validate; too-many-controls and
    unknown-claim-ids behave per contract (reject / drop + weak_grounding)."""
    issues: list[IssueRecord] = []
    specs_dir = _golden_dir(cfg) / "specs"
    expected = {
        "valid-simulation.json": ("ok", "simulation"),
        "valid-diagram.json": ("ok", "diagram"),
        "too-many-controls.json": ("reject", None),
        "unknown-claim-ids.json": ("weak", None),
    }
    for name, (outcome, kind) in expected.items():
        path = specs_dir / name
        if not path.is_file():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-SPEC",
                    category="artifact_spec",
                    message=f"spec fixture {name} is missing",
                )
            )
            continue
        raw = json.loads(_read(path))
        try:
            spec, weak_grounding = validate_artifact_spec(
                raw, available_claim_ids=SPEC_CLAIM_UNIVERSE
            )
        except ArtifactSpecError:
            if outcome == "reject":
                continue
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-SPEC",
                    category="artifact_spec",
                    message=f"{name} was rejected but should validate",
                )
            )
            continue
        if outcome == "reject":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-SPEC",
                    category="artifact_spec",
                    message=f"{name} validated but must be rejected",
                )
            )
            continue
        if kind is not None and spec["kind"] != kind:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-SPEC",
                    category="artifact_spec",
                    message=f"{name}: unexpected kind {spec['kind']}",
                )
            )
        if outcome == "weak" and not weak_grounding:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-SPEC",
                    category="artifact_spec",
                    message=f"{name}: dropped unknown claims must mark weak_grounding",
                )
            )
    return issues


def check_artifact_cache_identity(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-CACHE`: same spec → same id; `why` excluded; a doctrine/
    prompt/lint change yields a new id."""
    issues: list[IssueRecord] = []
    path = _golden_dir(cfg) / "specs" / "valid-simulation.json"
    if not path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-CACHE"] = (
            "spec fixture missing"
        )
        return issues
    spec = json.loads(_read(path))
    spec.pop("why", None)
    id_a, hash_a = compute_artifact_id(spec, doctrine_hash="doctrine-a")
    id_b, hash_b = compute_artifact_id(spec, doctrine_hash="doctrine-a")
    if (id_a, hash_a) != (id_b, hash_b):
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-CACHE",
                category="artifact_cache",
                message="the same spec must produce the same content id",
            )
        )
    id_c, _ = compute_artifact_id(spec, doctrine_hash="doctrine-b")
    if id_c == id_a:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-CACHE",
                category="artifact_cache",
                message="a doctrine hash change must invalidate the cache id",
            )
        )
    spec_with_why = dict(spec)
    spec_with_why["why"] = "totally different misconception label"
    id_d, _ = compute_artifact_id(spec_with_why, doctrine_hash="doctrine-a")
    if id_d != id_a:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-CACHE",
                category="artifact_cache",
                message="the why label must be excluded from the content id",
            )
        )
    return issues


def check_artifact_no_student_text(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-NO-STUDENT`: the canary weakness/instructions never reach the
    builder prompt, the stored spec, or the document (T-PL-17)."""
    issues: list[IssueRecord] = []
    spec_path = _golden_dir(cfg) / "specs" / "valid-simulation.json"
    if not spec_path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-NO-STUDENT"] = (
            "spec fixture missing"
        )
        return issues
    spec = json.loads(_read(spec_path))

    # The structural guard: a spec quoting the student is a hard rejection.
    quoting = dict(spec)
    quoting["title"] = f"{spec['title']} — {NO_STUDENT_CANARY}"
    try:
        ensure_no_student_text(quoting, [NO_STUDENT_CANARY, NO_STUDENT_INSTRUCTIONS])
    except ArtifactSpecError:
        pass
    else:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-NO-STUDENT",
                category="artifact_privacy",
                message="a spec quoting the session's weakness must be rejected",
            )
        )

    # The build prompt for the clean spec carries no canary either way.
    from backend.personalized.artifact_prompt import ArtifactDesignContext

    design = ArtifactDesignContext(
        doctrine_block="", palette_block="", doctrine_hash="h"
    )
    prompt = build_user_message(spec, [], design)
    for canary in (NO_STUDENT_CANARY, NO_STUDENT_INSTRUCTIONS):
        if canary in prompt:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-NO-STUDENT",
                    category="artifact_privacy",
                    message="the builder prompt must never contain session free text",
                )
            )

    # The clean spec passes the guard (the guard must not over-reject).
    try:
        ensure_no_student_text(spec, [NO_STUDENT_CANARY, NO_STUDENT_INSTRUCTIONS])
    except ArtifactSpecError as exc:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-NO-STUDENT",
                category="artifact_privacy",
                message=f"the clean spec must pass the no-student-text guard: {exc.problems}",
            )
        )
    return issues


def check_artifact_fallback_payload(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-FALLBACK`: the stored fallback is always honest — a diagram
    fallback that is not provably safe downgrades to text, and a build
    failure carries the fallback for the turn (§8)."""
    issues: list[IssueRecord] = []
    safe = {
        "kind": "diagram",
        "svg": "<svg viewBox='0 0 10 10'><circle cx='5' cy='5' r='4'/></svg>",
    }
    unsafe = {"kind": "diagram", "svg": "<svg><script>alert(1)</script></svg>"}
    text_only = {"kind": "text"}
    if normalize_fallback(safe).get("kind") != "diagram":
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-FALLBACK",
                category="artifact_fallback",
                message="a safe diagram fallback must survive normalization",
            )
        )
    if normalize_fallback(unsafe).get("kind") != "text":
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-FALLBACK",
                category="artifact_fallback",
                message="an unsafe fallback SVG must downgrade to the text fallback",
            )
        )
    if normalize_fallback(text_only).get("kind") != "text":
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-FALLBACK",
                category="artifact_fallback",
                message="a text fallback must pass through",
            )
        )
    try:
        raise ArtifactBuildError(
            "lint", "forced", extra={"fallback": normalize_fallback(safe)}
        )
    except ArtifactBuildError as exc:
        if exc.extra.get("fallback", {}).get("kind") != "diagram":
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PL03-FALLBACK",
                    category="artifact_fallback",
                    message="a forced build failure must carry the fallback payload",
                )
            )
    return issues


def check_artifact_render_gate(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-RENDER`: the golden in headless Chromium with network aborted —
    zero console errors, zero network attempts, no navigation, no 360 px
    overflow, `ready` ≤ 5 s, fps floor. SKIPPED (never passed) when Chromium
    is unavailable."""
    issues: list[IssueRecord] = []
    golden_path = _golden_dir(cfg) / "good-concave-mirror.html"
    if not golden_path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-RENDER"] = (
            "golden artifact missing"
        )
        return issues
    try:
        report = run_render_gate(_read(golden_path))
    except RenderGateUnavailable as exc:
        context.setdefault("skipped_checks", {})["DET-PL03-RENDER"] = str(exc)
        return issues
    context["render_report"] = {
        "render_ms": report.render_ms,
        "ready_ms": report.ready_ms,
        "dom_nodes": report.dom_nodes,
        "median_fps": report.median_fps,
        "network_attempts": report.network_attempts,
    }
    for failure in report.failures:
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-RENDER",
                category="artifact_render",
                message=f"render gate: {failure}",
            )
        )
    return issues


def check_artifact_sandbox_redteam(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-PL03-SANDBOX`: the red-team artifact runs inside a real sandboxed
    iframe (opaque origin) and cannot read the parent, navigate the top,
    open a popup, or navigate itself. SKIPPED when Chromium is unavailable."""
    issues: list[IssueRecord] = []
    golden_dir = _golden_dir(cfg)
    redteam_path = golden_dir / "redteam.html"
    if not redteam_path.is_file():
        context.setdefault("skipped_checks", {})["DET-PL03-SANDBOX"] = (
            "red-team artifact missing"
        )
        return issues
    try:
        report = run_sandbox_escape_test(_read(redteam_path))
    except RenderGateUnavailable as exc:
        context.setdefault("skipped_checks", {})["DET-PL03-SANDBOX"] = str(exc)
        return issues
    for failure in report.get("failures", []):
        issues.append(
            IssueRecord(
                severity="fatal",
                check_id="DET-PL03-SANDBOX",
                category="artifact_sandbox",
                message=f"sandbox escape: {failure}",
            )
        )
    return issues
