"""PL2 state-machine unit tests (agent-and-rag.md §2; DET-PL01-* contracts).

Pure-function tests over the machine: transitions, the five invariants, and
the deterministic scoring rules (§3.3). No model, no DB, no clock.
"""

from __future__ import annotations

import unittest

from backend.personalized import state as sm


def make_state(concepts: list[str] | None = None) -> dict:
    return sm.initial_state(concepts or ["c-1", "c-2", "c-3"])


class ScoringTest(unittest.TestCase):
    """§3.3 deterministic scoring, server-side."""

    def test_mcq_exact_option_only(self) -> None:
        check = {"kind": "mcq", "answer_key": "B"}
        self.assertTrue(sm.score_answer(check, "B").correct)
        self.assertTrue(sm.score_answer(check, " b ").correct)
        self.assertFalse(sm.score_answer(check, "A").correct)
        self.assertFalse(sm.score_answer(check, "AB").correct)

    def test_numeric_tolerance_rule(self) -> None:
        check = {"kind": "numeric", "answer_value": 16.0, "answer_unit": "cm"}
        self.assertTrue(sm.score_answer(check, "16").correct)
        self.assertTrue(sm.score_answer(check, "16.05").correct)  # within 1 %
        self.assertTrue(sm.score_answer(check, "1.6e1").correct)  # scientific
        self.assertFalse(sm.score_answer(check, "17").correct)
        self.assertFalse(sm.score_answer(check, "garbage").correct)

    def test_numeric_small_value_uses_absolute_floor(self) -> None:
        check = {"kind": "numeric", "answer_value": 0.5, "answer_unit": None}
        self.assertTrue(sm.score_answer(check, "0.505").correct)
        self.assertFalse(sm.score_answer(check, "0.52").correct)

    def test_wrong_unit_is_incorrect_with_unit_hint(self) -> None:
        check = {
            "kind": "numeric",
            "answer_value": 16.0,
            "answer_unit": "cm",
            "given_unit": "m",
        }
        result = sm.score_answer(check, "16")
        self.assertFalse(result.correct)
        self.assertTrue(result.unit_hint)

    def test_scientific_notation_normalized(self) -> None:
        check = {"kind": "numeric", "answer_value": 3200.0, "answer_unit": None}
        self.assertTrue(sm.score_answer(check, "3.2E3").correct)
        self.assertTrue(sm.score_answer(check, "3.2e3").correct)
        self.assertTrue(sm.score_answer(check, "3,200").correct)

    def test_blank_answer_is_not_an_attempt(self) -> None:
        check = {"kind": "mcq", "answer_key": "A"}
        with self.assertRaises(sm.BlankAnswer):
            sm.score_answer(check, "")
        with self.assertRaises(sm.BlankAnswer):
            sm.score_answer(check, None)
        with self.assertRaises(sm.BlankAnswer):
            sm.score_answer(check, "   ")


class InvariantTest(unittest.TestCase):
    """§2.3 invariants, asserted in code."""

    def test_no_check_before_teach_slice(self) -> None:
        state = make_state()
        with self.assertRaises(sm.StateError) as ctx:
            sm.set_open_check(
                state, check_id="chk-1", concept_id="c-1", level=1, kind="mcq"
            )
        self.assertEqual(ctx.exception.code, "E-CONFLICT")

    def test_diagnostic_check_is_pre_teach_by_design(self) -> None:
        state = make_state()
        sm.set_open_check(
            state,
            check_id="chk-d1",
            concept_id="c-1",
            level=1,
            kind="mcq",
            diagnostic=True,
        )
        self.assertIsNotNone(sm.open_check(state))

    def test_one_open_check_at_a_time(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        sm.set_open_check(
            state, check_id="chk-1", concept_id="c-1", level=1, kind="mcq"
        )
        with self.assertRaises(sm.StateError) as ctx:
            sm.set_open_check(
                state, check_id="chk-2", concept_id="c-1", level=1, kind="mcq"
            )
        self.assertEqual(ctx.exception.code, "E-PL-TURN-OPEN")

    def test_advance_never_revisits_taught_or_skipped(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        sm.skip_concept(state, "c-2")
        self.assertEqual(sm.next_concept(state), "c-3")
        sm.record_teach_slice(state, "c-3")
        self.assertIsNone(sm.next_concept(state))

    def test_harder_requires_coverage_gate(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        self.assertFalse(sm.coverage_complete(state))
        sm.record_teach_slice(state, "c-2")
        sm.skip_concept(state, "c-3")
        self.assertTrue(sm.coverage_complete(state))

    def test_mastery_requires_l2_and_l3_evidence(self) -> None:
        concept = {"attempts": 1, "levels_passed": [1], "skipped": False}
        self.assertEqual(sm.concept_mastery_status(concept), "getting_there")
        concept["levels_passed"] = [1, 2]
        self.assertEqual(sm.concept_mastery_status(concept), "getting_there")
        concept["levels_passed"] = [1, 2, 3]
        self.assertEqual(sm.concept_mastery_status(concept), "mastered")

    def test_skipped_is_never_mastered(self) -> None:
        concept = {
            "attempts": 4,
            "levels_passed": [1, 2, 3],
            "skipped": True,
        }
        self.assertEqual(sm.concept_mastery_status(concept), "skipped")

    def test_mastery_summary_excludes_skipped_from_mastered(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        sm.skip_concept(state, "c-2")
        for level in (1, 2, 3):
            sm.set_open_check(
                state,
                check_id=f"chk-{level}",
                concept_id="c-1",
                level=level,
                kind="mcq",
            )
            sm.record_check_result(state, correct=True)
        summary = {row["concept_id"]: row for row in sm.mastery_summary(state)}
        self.assertEqual(summary["c-1"]["status"], "mastered")
        self.assertEqual(summary["c-2"]["status"], "skipped")
        self.assertEqual(summary["c-3"]["status"], "not_yet")


class TransitionTest(unittest.TestCase):
    """The transition table rows the engine replays (§2.2)."""

    def test_three_failures_lead_to_worked_example(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        sm.set_open_check(
            state, check_id="chk-1", concept_id="c-1", level=1, kind="mcq"
        )
        for attempt in range(3):
            sm.record_check_result(state, correct=False)
            attempts = int(state["concepts"]["c-1"]["attempts"])
            sm.set_open_check(
                state,
                check_id=f"chk-{attempts + 1}",
                concept_id="c-1",
                level=1,
                kind="mcq",
            )
        sm.worked_example_fallback(state)
        concept = state["concepts"]["c-1"]
        self.assertEqual(concept["status"], "not_yet")
        self.assertEqual(concept["attempts"], 3)

    def test_levels_recorded_on_correct_answers(self) -> None:
        state = make_state()
        sm.record_teach_slice(state, "c-1")
        for level in (2, 3):
            sm.set_open_check(
                state,
                check_id=f"chk-{level}",
                concept_id="c-1",
                level=level,
                kind="mcq",
            )
            last = sm.record_check_result(state, correct=True)
            self.assertFalse(last["open"])
        self.assertEqual(state["concepts"]["c-1"]["levels_passed"], [2, 3])
        self.assertEqual(state["concepts"]["c-1"]["first_try_correct"], 1)

    def test_turn_cap(self) -> None:
        state = make_state()
        for _ in range(sm.MAX_TURNS):
            self.assertFalse(sm.turn_cap_reached(state))
            sm.bump_turn(state)
        self.assertTrue(sm.turn_cap_reached(state))

    def test_invalid_level_refused(self) -> None:
        state = make_state()
        with self.assertRaises(sm.StateError):
            sm.set_difficulty(state, 5)

    def test_state_from_session_forward_compatible(self) -> None:
        session = {"concept_ids": ["c-1"], "state": {"schema_version": 99}}
        state = sm.state_from_session(session)
        self.assertEqual(state["schema_version"], sm.STATE_SCHEMA_VERSION)
        self.assertIn("c-1", state["concepts"])

    def test_state_from_session_corrupt_state_resets(self) -> None:
        session = {"concept_ids": ["c-1"], "state": "not-a-dict"}
        state = sm.state_from_session(session)
        self.assertIn("c-1", state["concepts"])

    def test_diagnostic_over_length_refused(self) -> None:
        state = make_state()
        for i in range(4):
            sm.record_diagnostic(state, f"q-{i}", True)
            state["diagnostic"]["item_ids"].append(f"q-{i}")
        with self.assertRaises(sm.StateError):
            sm.finish_diagnostic(state)


if __name__ == "__main__":
    unittest.main()
