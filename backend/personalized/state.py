"""The teaching state machine (agent-and-rag.md §2; PL2).

Pure functions over the session's `state` JSON (§2.4) — no model import, no
DB access, no clock. The harness owns every transition: the model's advisory
`next_action`/`mastery_signal` are logged, never obeyed (§4.4).

Invariants asserted here (each covered by `DET-PL01-*` / unit tests):

1. No `check` exists for a concept before a `teach`/`adapt` slice for that
   concept in the same session.
2. Exactly one check is open at a time; a new turn cannot start while one is
   open (`E-PL-TURN-OPEN`).
3. A check's answer key never leaves the server (this module only scores).
4. `advance` never selects a concept whose prerequisites have no teach slice,
   unless the student explicitly chose "start here".
5. `harder` never runs before the coverage gate (every target concept taught
   or skipped).
6. `mastery` never reports `mastered` without L2+L3 evidence; `skipped` is
   never counted as mastered.
7. A turn is idempotent by `(session_id, client_turn_id)` — the store owns the
   uniqueness; this module is deterministic so a replay computes the same
   result.

Scoring rules (§3.3, deterministic, server-side):

- MCQ: exact option id, no partial credit.
- Numeric: `abs(given - expected) <= max(0.01, 0.005 * abs(expected))`; a
  wrong unit is incorrect with a unit hint; scientific notation normalized.
- Missing/blank: not an attempt — the caller raises `BlankAnswer`.
- Free text is never scored (PL-C-014): it becomes a follow-up teaching
  request.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Final

STATE_SCHEMA_VERSION: Final[int] = 1

STAGES: Final[tuple[str, ...]] = (
    "diagnose",
    "teach",
    "check",
    "adapt",
    "worked_example",
    "advance",
    "harder",
    "board",
    "mastery",
    "done",
)

LEVELS: Final[tuple[int, ...]] = (1, 2, 3, 4)
LEVEL_DIFFICULTY: Final[dict[int, str]] = {1: "easy", 2: "medium", 3: "hard"}
# Level 4 is board-style: generated in the board-exam style, never official
# CBSE questions (§4.1; DEC-COMP-001 stays in force).
BOARD_LEVEL: Final[int] = 4

MAX_TURNS: Final[int] = 60
MAX_ATTEMPTS_PER_CONCEPT: Final[int] = 3
# `mastered` requires L2 AND L3 evidence (EV-PL-001 DET-PL01-SM); level 1
# alone is `getting_there`.
MASTERED_EVIDENCE_LEVELS: Final[frozenset[int]] = frozenset({2, 3})

CHECK_KINDS: Final[tuple[str, ...]] = ("mcq", "numeric")


class StateError(ValueError):
    """A transition the machine refuses (the turn router maps it to 4xx)."""

    def __init__(self, reason: str, code: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.code = code


class BlankAnswer(StateError):
    """A missing/blank answer is not an attempt; the turn waits (§3.3)."""

    def __init__(self) -> None:
        super().__init__("blank_answer", "E-VALIDATION")


@dataclass(frozen=True)
class ScoreResult:
    """The deterministic verdict for one submitted answer (§3.3)."""

    correct: bool
    kind: str
    unit_hint: bool = False
    expected_display: str | None = None


def initial_state(
    concept_ids: list[str], *, skip_diagnostic: bool = False
) -> dict[str, Any]:
    """The §2.4 state object for a fresh session."""
    concepts: dict[str, Any] = {}
    for order, concept_id in enumerate(concept_ids):
        concepts[concept_id] = {
            "order": order,
            "status": "not_started",
            "attempts": 0,
            "first_try_correct": 0,
            "levels_passed": [],
            "last_check_id": None,
            "taught_slices": 0,
            "adapt_variants": 0,
            "skipped": False,
        }
    return {
        "schema_version": STATE_SCHEMA_VERSION,
        "current_concept_id": concept_ids[0] if concept_ids else None,
        "difficulty_level": 1,
        "diagnostic": {"item_ids": [], "answers": {}, "verdict": {}},
        "concepts": concepts,
        "coverage": {
            "taught": [],
            "skipped": [],
            "remaining": list(concept_ids),
        },
        "turn_count": 0,
        "last_check": None,
        "started_at_stage": "teach" if skip_diagnostic else "diagnose",
    }


def state_from_session(session: dict[str, Any]) -> dict[str, Any]:
    """Read the persisted state with a forward-compatible default (§2.4).

    An older `schema_version` (or a missing/ corrupt `state`) is read as a
    fresh state for the session's concept list — never a crash. A newer
    version than this build understands is also reset: writing it back would
    silently downgrade the machine's memory.
    """
    raw = session.get("state")
    if isinstance(raw, dict) and raw.get("schema_version") == STATE_SCHEMA_VERSION:
        return raw
    return initial_state(list(session.get("concept_ids") or []))


# --- deterministic scoring (§3.3) ---------------------------------------------


_SCI_NOTATION_RE = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*[eE×xX*]\s*(-?\d+)\s*$")
_ALLOWED_ANSWER_RE = re.compile(r"^[0-9eE+\-.,\s×xX*]+$")


def _normalize_number(raw: str) -> float | None:
    """Parse a numeric answer: plain decimal, comma decimal, or scientific.

    Returns None when the text is not a number (which for a numeric check is
    simply an incorrect answer, not a crash).
    """
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace(",", "").replace(" ", "")
    match = _SCI_NOTATION_RE.match(text)
    if match:
        try:
            return float(match.group(1)) * math.pow(10.0, float(match.group(2)))
        except (ValueError, OverflowError):
            return None
    if not _ALLOWED_ANSWER_RE.match(text) or text in ("+", "-", ".", ""):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def score_answer(check: dict[str, Any], answer: Any) -> ScoreResult:
    """Score one submitted answer against the stored key (server-side only).

    `check` is the open check with its server-side key (`answer_key` /
    `answer_index`); `answer` is the raw client value. Blank answers raise
    `BlankAnswer` — they are not attempts (§3.3).
    """
    kind = str(check.get("kind", ""))
    if answer is None or (isinstance(answer, str) and not answer.strip()):
        raise BlankAnswer()
    if kind == "mcq":
        expected = str(check.get("answer_key", ""))
        given = str(answer).strip().upper()
        return ScoreResult(
            correct=given == expected.upper(),
            kind=kind,
            expected_display=expected,
        )
    if kind == "numeric":
        expected_value = float(check.get("answer_value", 0.0))
        expected_unit = check.get("answer_unit")
        given_unit = check.get("given_unit")
        # A wrong unit is incorrect with a unit hint (§3.3), even when the
        # number matches.
        if expected_unit and given_unit and str(given_unit) != str(expected_unit):
            return ScoreResult(
                correct=False,
                kind=kind,
                unit_hint=True,
                expected_display=f"{_display_number(expected_value)} {expected_unit}",
            )
        given_value = _normalize_number(str(answer))
        tolerance = max(0.01, 0.005 * abs(expected_value))
        correct = given_value is not None and abs(given_value - expected_value) <= (
            tolerance + 1e-12
        )
        return ScoreResult(
            correct=correct,
            kind=kind,
            expected_display=_display_number(expected_value),
        )
    raise StateError(f"unsupported_check_kind:{kind}", "E-VALIDATION")


def _display_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


# --- state mutations -----------------------------------------------------------


def _concept_state(state: dict[str, Any], concept_id: str | None) -> dict[str, Any]:
    concepts = state.setdefault("concepts", {})
    if concept_id and concept_id not in concepts:
        concepts[concept_id] = {
            "order": len(concepts),
            "status": "not_started",
            "attempts": 0,
            "first_try_correct": 0,
            "levels_passed": [],
            "last_check_id": None,
            "taught_slices": 0,
            "adapt_variants": 0,
            "skipped": False,
        }
    return concepts[concept_id] if concept_id else {}


def record_diagnostic(state: dict[str, Any], item_key: str, correct: bool) -> None:
    """Record one diagnostic answer (§2.4 `diagnostic.answers`).

    `item_key` is the armed item's id (the bank's `base_item_id`); the armed
    item list itself lives in `item_ids` and is maintained by the arming
    phase."""
    diagnostic = state.setdefault(
        "diagnostic", {"item_ids": [], "answers": {}, "verdict": {}}
    )
    diagnostic["answers"][item_key] = bool(correct)


def finish_diagnostic(state: dict[str, Any]) -> None:
    """Diagnostic done → `teach` (transition table row 1; ≤ 3 items guard)."""
    diagnostic = state.get("diagnostic", {})
    if len(diagnostic.get("item_ids", [])) > 3:
        raise StateError("diagnostic_over_length", "E-VALIDATION")
    state["started_at_stage"] = "teach"


def record_teach_slice(state: dict[str, Any], concept_id: str) -> None:
    """A teach/adapt slice persisted: unlocks the concept's first check."""
    concept = _concept_state(state, concept_id)
    concept["taught_slices"] = int(concept.get("taught_slices", 0)) + 1
    if concept.get("status") != "not_yet":
        # A worked-example fallback slice must not resurrect the concept:
        # the not_yet verdict stands until the next concept (§2.1).
        concept["status"] = "practising"
    coverage = state.setdefault(
        "coverage", {"taught": [], "skipped": [], "remaining": []}
    )
    if concept_id not in coverage["taught"]:
        coverage["taught"].append(concept_id)
    if concept_id in coverage.get("remaining", []):
        coverage["remaining"].remove(concept_id)


def record_adapt_variant(state: dict[str, Any], concept_id: str) -> None:
    """An adapt variant persisted: counts toward the representation change."""
    concept = _concept_state(state, concept_id)
    concept["adapt_variants"] = int(concept.get("adapt_variants", 0)) + 1


def skip_concept(state: dict[str, Any], concept_id: str) -> None:
    """Explicit skip: never counted as mastered (invariant 6)."""
    concept = _concept_state(state, concept_id)
    concept["skipped"] = True
    concept["status"] = "skipped"
    coverage = state.setdefault(
        "coverage", {"taught": [], "skipped": [], "remaining": []}
    )
    if concept_id not in coverage["skipped"]:
        coverage["skipped"].append(concept_id)
    if concept_id in coverage.get("remaining", []):
        coverage["remaining"].remove(concept_id)


def open_check(state: dict[str, Any]) -> dict[str, Any] | None:
    """The one open check, or None (invariant 2)."""
    last = state.get("last_check")
    if isinstance(last, dict) and last.get("open"):
        return last
    return None


def set_open_check(
    state: dict[str, Any],
    *,
    check_id: str,
    concept_id: str,
    level: int,
    kind: str,
    diagnostic: bool = False,
) -> None:
    """Arm the open check (the key itself lives in the message row, not here).

    Guards: the concept must have a teach/adapt slice in this session
    (invariant 1) — **except for diagnostic items**, which are pre-teach by
    design (§4.5) and are marked `diagnostic=True`; and no other check may be
    open (invariant 2).
    """
    concept = _concept_state(state, concept_id)
    if not diagnostic and int(concept.get("taught_slices", 0)) < 1:
        raise StateError("check_before_teach", "E-CONFLICT")
    if open_check(state) is not None:
        raise StateError("turn_open", "E-PL-TURN-OPEN")
    state["last_check"] = {
        "check_id": check_id,
        "concept_id": concept_id,
        "level": int(level),
        "kind": str(kind),
        "open": True,
        "attempt_no": 0,
        "correct": None,
        "diagnostic": bool(diagnostic),
    }


def record_check_result(state: dict[str, Any], *, correct: bool) -> dict[str, Any]:
    """Close the open check with the deterministic verdict and update evidence."""
    last = open_check(state)
    if last is None:
        raise StateError("no_open_check", "E-CONFLICT")
    concept = _concept_state(state, last["concept_id"])
    concept["attempts"] = int(concept.get("attempts", 0)) + 1
    attempt_no = int(concept["attempts"])
    last["open"] = False
    last["correct"] = bool(correct)
    last["attempt_no"] = attempt_no
    if correct:
        level = int(last["level"])
        passed = concept.setdefault("levels_passed", [])
        if level not in passed:
            passed.append(level)
        if attempt_no == 1:
            concept["first_try_correct"] = int(concept.get("first_try_correct", 0)) + 1
        concept["status"] = "practising"
    return last


def concept_mastery_status(concept: dict[str, Any]) -> str:
    """The honest status rule (invariant 6): `mastered` needs L2+L3 evidence.

    `skipped` is never mastered; a worked-example fallback is `not_yet`.
    """
    if concept.get("skipped"):
        return "skipped"
    if concept.get("status") == "not_yet":
        # The worked-example fallback verdict (§2.1) stands: three failed
        # checks, the full solution shown — not_yet until a later session.
        return "not_yet"
    passed = set(concept.get("levels_passed", []))
    if MASTERED_EVIDENCE_LEVELS.issubset(passed):
        return "mastered"
    if passed or int(concept.get("attempts", 0)) > 0:
        return "getting_there"
    return "not_yet"


def worked_example_fallback(state: dict[str, Any]) -> None:
    """After 3 failed checks: concept marked `not_yet`, example shown (§2.1)."""
    last = state.get("last_check")
    concept_id = last["concept_id"] if isinstance(last, dict) else None
    if not concept_id:
        raise StateError("no_open_check", "E-CONFLICT")
    concept = _concept_state(state, concept_id)
    concept["status"] = "not_yet"


def coverage_complete(state: dict[str, Any]) -> bool:
    """Every target concept taught or skipped (the coverage gate)."""
    coverage = state.get("coverage", {})
    return not coverage.get("remaining", [])


def concept_has_l3_evidence(state: dict[str, Any], concept_id: str) -> bool:
    concepts = state.get("concepts", {})
    concept = concepts.get(concept_id, {})
    return 3 in concept.get("levels_passed", [])


def next_concept(state: dict[str, Any]) -> str | None:
    """The next untaught, unskipped concept in order (invariant 4).

    Prerequisites with no teach slice cannot be advanced past: the first
    remaining concept in order IS the prerequisite-respecting choice because
    the chapter's concept order follows the syllabus prerequisites.
    """
    concepts = state.get("concepts", {})
    ordered = sorted(
        (c for c in concepts.values() if isinstance(c, dict)),
        key=lambda c: int(c.get("order", 0)),
    )
    order_to_id = {
        int(c.get("order", 0)): cid
        for cid, c in concepts.items()
        if isinstance(c, dict)
    }
    for concept in ordered:
        cid = order_to_id[int(concept.get("order", 0))]
        if (
            int(concept.get("taught_slices", 0)) == 0
            and not concept.get("skipped")
            and cid in state.get("coverage", {}).get("remaining", [])
        ):
            return cid
    return None


def bump_turn(state: dict[str, Any]) -> int:
    """One more turn; returns the new count (cap 60 → the caller goes to
    `mastery`)."""
    state["turn_count"] = int(state.get("turn_count", 0)) + 1
    return int(state["turn_count"])


def turn_cap_reached(state: dict[str, Any]) -> bool:
    return int(state.get("turn_count", 0)) >= MAX_TURNS


def set_difficulty(state: dict[str, Any], level: int) -> None:
    if level not in LEVELS:
        raise StateError("invalid_level", "E-VALIDATION")
    state["difficulty_level"] = int(level)


def difficulty_level(state: dict[str, Any]) -> int:
    return int(state.get("difficulty_level", 1))


def mastery_summary(state: dict[str, Any]) -> list[dict[str, Any]]:
    """The honest end-of-session mastery report (invariant 6; §4.7 export)."""
    concepts = state.get("concepts", {})
    summary: list[dict[str, Any]] = []
    for concept_id, concept in sorted(
        concepts.items(), key=lambda kv: int(kv[1].get("order", 0))
    ):
        summary.append(
            {
                "concept_id": concept_id,
                "status": concept_mastery_status(concept),
                "attempts": int(concept.get("attempts", 0)),
                "first_try_correct": int(concept.get("first_try_correct", 0)),
                "levels_passed": sorted(concept.get("levels_passed", [])),
                "skipped": bool(concept.get("skipped")),
            }
        )
    return summary


def normalized_state(state: dict[str, Any]) -> dict[str, Any]:
    """The state as persisted: schema version pinned, JSON-clean."""
    state["schema_version"] = STATE_SCHEMA_VERSION
    return state
