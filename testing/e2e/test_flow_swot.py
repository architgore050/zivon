"""Flow 8 (§17.1): SWOT quadrants — evidence in, honest placement out.

Evidence is seeded only through real code paths (the practice answer writer,
the device-merge event batch). Fewer than three rated chapters must produce
the honest "not enough data" state, never a fabricated grid.
"""

from __future__ import annotations

from .support import MOTION, E2EFlow


class SwotQuadrantTests(E2EFlow):
    """The 2x2 grid from merged/practice evidence."""

    def seed_practice_answers(self, chapter: str, *, correct: bool) -> None:
        """Three scored items through the merge island's real event contract.

        The event store pattern-checks ids and records the chapter rollup;
        no bank rows are required for the SWOT aggregates."""
        for index in range(1, 4):
            self.merge_events(
                [
                    {
                        "kind": "practice_answer",
                        "chapter_id": chapter,
                        "question_id": f"seed-{chapter}-{index}",
                        "payload": {"correct": correct, "source": "merge"},
                    }
                ]
            )

    def test_fewer_than_three_rated_chapters_is_honest(self) -> None:
        self.seed_practice_answers(MOTION, correct=True)
        payload = self.client.get("/v1/swot").json()
        self.assertFalse(payload["enough_data"], payload.get("notice", ""))
        page = self.page("/app/swot")
        self.assertIn("Not enough data yet", page)
        how = self.page("/app/swot/how")
        self.assertIn("No medians yet", how)
