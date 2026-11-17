"""SWOT computation rules (F8) — pure, hermetic unit coverage.

No database, no HTTP: every test builds a `SwotInput` directly and asserts
the deterministic contract — the 21-day half-life weights, the median split
and the four quadrants, the <3-chapters unrated rule, exam weight as
priority (never a fifth quadrant), the dormant absolute mode, the 14-day
trend, and the all-student time prior (AI prior + EWMA with the outlier
cap, no all-history recompute).
"""

from __future__ import annotations

import datetime
import unittest

from backend.progress import CatalogueSnapshot, ChapterMeta, EventRow
from backend.swot import SwotInput, SwotModeError, build_swot, resolve_mode, rules
from backend.swot.stats import (
    ABSOLUTE_COVERAGE_HIGH_PCT,
    ABSOLUTE_PERFORMANCE_HIGH_PCT,
    ENOUGH_DATA_MIN_CHAPTERS,
    HALF_LIFE_DAYS,
    PRIOR_EWMA_ALPHA,
    PRIOR_MIN_OBSERVATIONS,
    PRIOR_OUTLIER_CAP_FACTOR,
    _effective_prior,
    _weight,
)

NOW = datetime.datetime(2026, 11, 17, 6, 0, 0, tzinfo=datetime.UTC)
CHAPTER_A = "class-9-ch-a"
CHAPTER_B = "class-9-ch-b"
CHAPTER_C = "class-9-ch-c"


def chapter(
    chapter_id: str,
    *,
    class_level: int = 9,
    chapter_no: int = 1,
    title: str = "A chapter",
) -> ChapterMeta:
    return ChapterMeta(
        chapter_id=chapter_id,
        class_level=class_level,
        chapter_no=chapter_no,
        slug=chapter_id,
        title=title,
        lesson_url=f"/courses/class-{class_level}-physics/{chapter_id}/",
    )


def snapshot(*chapters: ChapterMeta) -> CatalogueSnapshot:
    return CatalogueSnapshot(
        classes=((9, tuple(chapters)),),
        chapters={meta.chapter_id: meta for meta in chapters},
        source="fixture",
    )


def days_ago(days: float) -> datetime.datetime:
    return NOW - datetime.timedelta(days=days)


def answer(chapter_id: str, correct: bool, *, days: float = 0) -> EventRow:
    """A practice_answer row as the F3 store returns it (first attempt only)."""
    return EventRow(
        event_id=f"{chapter_id}-{int(correct)}-{days}",
        kind="practice_answer",
        chapter_id=chapter_id,
        concept_id=None,
        question_id=f"{chapter_id}-q",
        payload={"correct": correct, "hints_used": 0, "time_ms": 30000},
        created_at=days_ago(days),
    )


def lesson(
    chapter_id: str, *, blocks_seen: int, blocks_total: int, days: float = 1
) -> EventRow:
    return EventRow(
        event_id=f"{chapter_id}-lesson-{days}",
        kind="lesson_block_view",
        chapter_id=chapter_id,
        concept_id=None,
        question_id=None,
        payload={
            "section_id": "sec-01",
            "blocks_seen": blocks_seen,
            "blocks_total": blocks_total,
        },
        created_at=days_ago(days),
    )


def progress(chapter_id: str, *, seen: int, total: int) -> dict[str, object]:
    return {
        "chapter_id": chapter_id,
        "status": "in_progress",
        "blocks_seen": seen,
        "blocks_total": total,
    }


def make_input(
    chapters: tuple[ChapterMeta, ...],
    events: list[EventRow],
    *,
    speaking: list[dict[str, object]] | None = None,
    lesson_progress: list[dict[str, object]] | None = None,
    question_counts: dict[str, int] | None = None,
    attempted: dict[str, set[str]] | None = None,
    priors: dict[str, int] | None = None,
    exam_weights: dict[str, float] | None = None,
    mode: str = "relative",
) -> SwotInput:
    return SwotInput(
        events=events,
        speaking=speaking or [],
        lesson_progress=lesson_progress or [],
        question_counts=question_counts or {},
        attempted=attempted or {},
        priors=priors or {},
        exam_weights=exam_weights or {},
        catalogue=snapshot(*chapters),
        mode=mode,
        now=NOW,
    )


def all_cards(payload: dict) -> list[dict]:
    return (
        payload["unrated"]
        + payload["quadrants"]["strength"]
        + payload["quadrants"]["weakness"]
        + payload["quadrants"]["opportunity"]
        + payload["quadrants"]["threat"]
    )


class ModeTests(unittest.TestCase):
    def test_default_and_invalid_modes(self) -> None:
        self.assertEqual(resolve_mode(None), "relative")
        self.assertEqual(resolve_mode("RELATIVE "), "relative")
        self.assertEqual(resolve_mode("absolute"), "absolute")
        with self.assertRaises(SwotModeError):
            resolve_mode("median")
        with self.assertRaises(SwotModeError):
            resolve_mode("../absolute")


class WeightTests(unittest.TestCase):
    def test_half_life_21_days(self) -> None:
        # At exactly one half-life the weight is 0.5; at two, 0.25.
        self.assertAlmostEqual(_weight(NOW, days_ago(HALF_LIFE_DAYS)), 0.5, places=9)
        self.assertAlmostEqual(
            _weight(NOW, days_ago(2 * HALF_LIFE_DAYS)), 0.25, places=9
        )
        self.assertEqual(_weight(NOW, NOW), 1.0)

    def test_future_observation_is_clamped_to_one(self) -> None:
        self.assertEqual(_weight(NOW, NOW + datetime.timedelta(days=1)), 1.0)


class MedianSplitTests(unittest.TestCase):
    def test_three_chapters_split_into_three_quadrants(self) -> None:
        chapters = (
            chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),
            chapter(CHAPTER_B, chapter_no=2, title="Chapter B"),
            chapter(CHAPTER_C, chapter_no=3, title="Chapter C"),
        )
        events: list[EventRow] = []
        # A: 6/6 correct, coverage 6/9 (66.7%) -> above both medians.
        events += [answer(CHAPTER_A, True, days=1) for _ in range(6)]
        # B: 0/6 correct, coverage 5/9 (55.6%) -> below perf, above coverage.
        events += [answer(CHAPTER_B, False, days=2) for _ in range(6)]
        events.append(lesson(CHAPTER_B, blocks_seen=5, blocks_total=9, days=2))
        # C: 4/4 correct, coverage 3/9 (33.3%) -> above perf, below coverage.
        events += [answer(CHAPTER_C, True, days=3) for _ in range(4)]
        events.append(lesson(CHAPTER_C, blocks_seen=3, blocks_total=9, days=3))
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[
                    progress(CHAPTER_A, seen=6, total=9),
                    progress(CHAPTER_B, seen=5, total=9),
                    progress(CHAPTER_C, seen=3, total=9),
                ],
            )
        )
        self.assertTrue(payload["enough_data"])
        self.assertEqual(payload["medians"]["performance_pct"], 100.0)
        self.assertAlmostEqual(payload["medians"]["coverage_pct"], 55.6, places=1)
        self.assertEqual(
            [card["chapter_id"] for card in payload["quadrants"]["strength"]],
            [CHAPTER_A],
        )
        self.assertEqual(
            [card["chapter_id"] for card in payload["quadrants"]["weakness"]],
            [CHAPTER_B],
        )
        self.assertEqual(
            [card["chapter_id"] for card in payload["quadrants"]["opportunity"]],
            [CHAPTER_C],
        )
        self.assertEqual(payload["quadrants"]["threat"], [])
        # The snapshot exposes one card per quadrant for the dashboard.
        self.assertEqual(payload["snapshot"]["strength"]["chapter_id"], CHAPTER_A)

    def test_fewer_than_three_rated_chapters_makes_no_claim(self) -> None:
        chapters = (
            chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),
            chapter(CHAPTER_B, chapter_no=2, title="Chapter B"),
        )
        events = [answer(CHAPTER_A, True) for _ in range(4)]
        events += [answer(CHAPTER_B, False) for _ in range(4)]
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[
                    progress(CHAPTER_A, seen=6, total=9),
                    progress(CHAPTER_B, seen=5, total=9),
                ],
            )
        )
        # Both chapters are individually rated, but two is below the
        # three-chapter minimum, so no placement claim is made at all.
        self.assertFalse(payload["enough_data"])
        self.assertIsNone(payload["medians"])
        self.assertEqual(payload["rated_chapter_count"], 0)
        for name in ("strength", "weakness", "opportunity", "threat"):
            self.assertEqual(payload["quadrants"][name], [])
        self.assertEqual(len(payload["unrated"]), 2)
        self.assertIn(
            "at least 3 rated chapters", payload["unrated"][0]["unrated_reason"]
        )

    def test_lesson_only_chapter_is_unrated_not_forced_into_a_box(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        payload = build_swot(
            data=make_input(
                chapters,
                [lesson(CHAPTER_A, blocks_seen=2, blocks_total=9)],
                lesson_progress=[progress(CHAPTER_A, seen=2, total=9)],
            )
        )
        self.assertFalse(payload["enough_data"])
        self.assertEqual(len(payload["unrated"]), 1)
        self.assertEqual(payload["quadrants"]["strength"], [])

    def test_empty_account_is_new_with_honest_empty_state(self) -> None:
        payload = build_swot(data=make_input((chapter(CHAPTER_A),), []))
        self.assertTrue(payload["is_new"])
        self.assertFalse(payload["enough_data"])
        self.assertEqual(len(payload["unrated"]), 1)
        self.assertEqual(
            payload["unrated"][0]["unrated_reason"],
            "No scored practice, test, or explain-back evidence yet.",
        )

    def test_question_bank_gives_coverage_and_attempt_rate(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        events = [answer(CHAPTER_A, True) for _ in range(4)]
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                question_counts={CHAPTER_A: 10},
                attempted={CHAPTER_A: {f"{CHAPTER_A}-q"}},
            )
        )
        card = all_cards(payload)[0]
        self.assertEqual(card["metrics"]["attempt_rate_pct"], 10.0)
        self.assertEqual(card["metrics"]["coverage_pct"], 10.0)


class TrendTests(unittest.TestCase):
    def _payload(self, events: list[EventRow]) -> dict:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        return build_swot(
            data=make_input(
                chapters, events, lesson_progress=[progress(CHAPTER_A, seen=6, total=9)]
            )
        )

    def test_improving_trend_over_the_14_day_window(self) -> None:
        events = [answer(CHAPTER_A, False, days=20) for _ in range(4)]
        events += [answer(CHAPTER_A, True, days=5) for _ in range(4)]
        card = all_cards(self._payload(events))[0]
        self.assertEqual(card["metrics"]["trend"], "up")

    def test_slipping_trend_crosses_the_minus_threshold(self) -> None:
        events = [answer(CHAPTER_A, True, days=20) for _ in range(4)]
        events += [answer(CHAPTER_A, False, days=5) for _ in range(4)]
        card = all_cards(self._payload(events))[0]
        self.assertEqual(card["metrics"]["trend"], "down")

    def test_no_trend_without_a_baseline(self) -> None:
        events = [answer(CHAPTER_A, True, days=2) for _ in range(4)]
        card = all_cards(self._payload(events))[0]
        self.assertIsNone(card["metrics"]["trend"])

    def test_no_trend_with_too_few_recent_items(self) -> None:
        events = [answer(CHAPTER_A, False, days=20) for _ in range(4)]
        events += [answer(CHAPTER_A, True, days=5) for _ in range(2)]
        card = all_cards(self._payload(events))[0]
        self.assertIsNone(card["metrics"]["trend"])


class ExamWeightTests(unittest.TestCase):
    def test_exam_weight_reorders_inside_a_quadrant_and_marks_imp(self) -> None:
        chapters = (
            chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),
            chapter(CHAPTER_B, chapter_no=2, title="Chapter B"),
            chapter(CHAPTER_C, chapter_no=3, title="Chapter C"),
        )
        events: list[EventRow] = []
        # Absolute mode: all three sit below the fixed 75% accuracy bar and
        # above the 60% coverage bar, so all three land in Weakness with
        # different results — the reorder inside the box is observable.
        for chapter_id, wrong in ((CHAPTER_A, 3), (CHAPTER_B, 4), (CHAPTER_C, 2)):
            events += [answer(chapter_id, False) for _ in range(wrong)]
            events.append(answer(chapter_id, True))
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[
                    progress(CHAPTER_A, seen=7, total=9),
                    progress(CHAPTER_B, seen=7, total=9),
                    progress(CHAPTER_C, seen=7, total=9),
                ],
                exam_weights={CHAPTER_C: 1.5, CHAPTER_A: 0.5},
                mode="absolute",
            )
        )
        weak = payload["quadrants"]["weakness"]
        # Order inside the box: IMP chapter first, then heavier exam weight
        # (A's 0.5 beats B's none), then the lowest results.
        self.assertEqual(
            [card["chapter_id"] for card in weak],
            [CHAPTER_C, CHAPTER_A, CHAPTER_B],
        )
        self.assertTrue(weak[0]["exam_priority"])
        self.assertFalse(weak[1]["exam_priority"])
        # Exam weight is priority, never a fifth quadrant.
        self.assertNotIn("exam", payload["quadrants"])

    def test_null_exam_weight_is_no_priority(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        events = [answer(CHAPTER_A, True) for _ in range(4)]
        payload = build_swot(
            data=make_input(
                chapters, events, lesson_progress=[progress(CHAPTER_A, seen=6, total=9)]
            )
        )
        card = all_cards(payload)[0]
        self.assertFalse(card["exam_priority"])
        self.assertIsNone(card["exam_weight"])
        self.assertNotIn("IMP", " ".join(card["evidence"]))


class AbsoluteModeTests(unittest.TestCase):
    def test_absolute_mode_places_against_fixed_thresholds(self) -> None:
        chapters = (
            chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),
            chapter(CHAPTER_B, chapter_no=2, title="Chapter B"),
        )
        events: list[EventRow] = []
        # A: 100% accuracy, 80% coverage -> absolute strength.
        events += [answer(CHAPTER_A, True) for _ in range(4)]
        events.append(lesson(CHAPTER_A, blocks_seen=8, blocks_total=10))
        # B: 20% accuracy, 70% coverage -> absolute weakness.
        events += [answer(CHAPTER_B, False) for _ in range(4)]
        events.append(lesson(CHAPTER_B, blocks_seen=7, blocks_total=10))
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[
                    progress(CHAPTER_A, seen=8, total=10),
                    progress(CHAPTER_B, seen=7, total=10),
                ],
                mode="absolute",
            )
        )
        self.assertEqual(payload["mode"], "absolute")
        self.assertIsNone(payload["medians"])
        self.assertEqual(
            [card["chapter_id"] for card in payload["quadrants"]["strength"]],
            [CHAPTER_A],
        )
        self.assertEqual(
            [card["chapter_id"] for card in payload["quadrants"]["weakness"]],
            [CHAPTER_B],
        )

    def test_absolute_thresholds_are_the_documented_placeholders(self) -> None:
        published = rules("absolute")
        self.assertEqual(
            published["absolute_performance_high_pct"], ABSOLUTE_PERFORMANCE_HIGH_PCT
        )
        self.assertEqual(
            published["absolute_coverage_high_pct"], ABSOLUTE_COVERAGE_HIGH_PCT
        )
        # Dormant by default: the shipped mode never claims absolute.
        self.assertEqual(rules("relative")["mode"], "relative")

    def test_absolute_mode_needs_no_three_chapter_minimum(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        events = [answer(CHAPTER_A, True) for _ in range(4)]
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[progress(CHAPTER_A, seen=8, total=9)],
                mode="absolute",
            )
        )
        # In absolute mode one strong chapter is a strength, not a pending split.
        self.assertEqual(payload["quadrants"]["strength"][0]["chapter_id"], CHAPTER_A)


class SpeakingTests(unittest.TestCase):
    def test_speaking_attempts_count_and_feed_the_speaking_score(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        events = [answer(CHAPTER_A, True) for _ in range(2)]
        speaking = [
            {"chapter_id": CHAPTER_A, "score": 90.0, "created_at": days_ago(1)},
            {"chapter_id": CHAPTER_A, "score": 70.0, "created_at": days_ago(1)},
        ]
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                speaking=speaking,
                lesson_progress=[progress(CHAPTER_A, seen=6, total=9)],
            )
        )
        card = all_cards(payload)[0]
        self.assertEqual(card["metrics"]["scored_items"], 4)
        self.assertEqual(card["metrics"]["speaking_score_pct"], 80.0)


class TimePriorTests(unittest.TestCase):
    def test_ai_prior_stands_until_enough_observations(self) -> None:
        self.assertEqual(_effective_prior(ai_prior=60000, observations=[]), 60000.0)
        few = _effective_prior(
            ai_prior=60000,
            observations=[
                (days_ago(1), 30000) for _ in range(PRIOR_MIN_OBSERVATIONS - 1)
            ],
        )
        self.assertEqual(few, 60000.0)

    def test_ewma_refines_the_prior_after_enough_observations(self) -> None:
        observations = [(days_ago(9 - i), 60000) for i in range(PRIOR_MIN_OBSERVATIONS)]
        self.assertEqual(
            _effective_prior(ai_prior=120000, observations=observations), 60000.0
        )
        # One capped outlier cannot move it past 3x the prior.
        observations.append((days_ago(0), 10_000_000))
        capped = _effective_prior(ai_prior=120000, observations=observations)
        assert capped is not None
        cap = int(120000 * PRIOR_OUTLIER_CAP_FACTOR)
        expected = (1 - PRIOR_EWMA_ALPHA) * 60000 + PRIOR_EWMA_ALPHA * min(
            10_000_000, cap
        )
        self.assertAlmostEqual(capped, expected, places=6)
        self.assertLessEqual(capped, cap)

    def test_no_prior_and_no_observations_is_no_ratio(self) -> None:
        self.assertIsNone(_effective_prior(ai_prior=None, observations=[]))

    def test_time_ratio_surfaces_pace_evidence_when_slow(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        # Own time 180 s vs prior 60 s -> ratio 3.0, capped outlier far away.
        events = [
            EventRow(
                event_id=f"slow-{i}",
                kind="practice_answer",
                chapter_id=CHAPTER_A,
                concept_id=None,
                question_id=f"q-{i}",
                payload={"correct": True, "hints_used": 0, "time_ms": 180000},
                created_at=days_ago(1),
            )
            for i in range(4)
        ]
        payload = build_swot(
            data=make_input(
                chapters,
                events,
                lesson_progress=[progress(CHAPTER_A, seen=6, total=9)],
                priors={CHAPTER_A: 60000},
            )
        )
        card = all_cards(payload)[0]
        self.assertEqual(card["metrics"]["time_ratio"], 3.0)
        self.assertTrue(any("exam-pace risk" in line for line in card["evidence"]))


class EvidenceTests(unittest.TestCase):
    def test_card_carries_two_bullets_one_action_and_a_live_url(self) -> None:
        chapters = (chapter(CHAPTER_A, chapter_no=1, title="Chapter A"),)
        events = [answer(CHAPTER_A, True) for _ in range(4)]
        payload = build_swot(
            data=make_input(
                chapters, events, lesson_progress=[progress(CHAPTER_A, seen=6, total=9)]
            )
        )
        card = all_cards(payload)[0]
        self.assertGreaterEqual(len(card["evidence"]), 2)
        self.assertLessEqual(len(card["evidence"]), 3)
        self.assertTrue(card["next_action"]["text"])
        self.assertTrue(card["next_action"]["url"].startswith("/app/"))
        self.assertIn("67%", card["evidence"][1])

    def test_rules_publish_every_constant_the_copy_renders(self) -> None:
        published = rules("relative")
        for key in (
            "version",
            "formula_version",
            "mode",
            "half_life_days",
            "trend_window_days",
            "rated_min_items",
            "enough_data_min_chapters",
            "exam_weight_imp_min",
        ):
            self.assertIn(key, published)
        self.assertEqual(
            published["enough_data_min_chapters"], ENOUGH_DATA_MIN_CHAPTERS
        )


if __name__ == "__main__":
    unittest.main()
