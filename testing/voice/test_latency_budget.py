"""Latency-budget contract test (spec.md §13 / latency-budget.md).

Parses ``docs/specs/voice-agent/latency-budget.csv`` and fails the build if
the Gate C budget drifts: the P0 warm-path sum stays ≤ 4,000 ms, every row
keeps an owner + a measure method, and the P1 hands-free substitution (L0 →
L0h) still lands under the bar.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from typing import ClassVar

BUDGET_CSV = Path("docs/specs/voice-agent/latency-budget.csv")
GATE_C_MS = 4000


def _load_rows() -> list[dict[str, str]]:
    with BUDGET_CSV.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


class LatencyBudgetTest(unittest.TestCase):
    rows: ClassVar[list[dict[str, str]]] = []

    @classmethod
    def setUpClass(cls) -> None:
        if not BUDGET_CSV.exists():  # run from repo root, per testing/README.md
            raise unittest.SkipTest("run from the repo root (docs/ path)")
        cls.rows = _load_rows()

    def _sum(self, hops: list[str]) -> int:
        by_id = {r["hop"]: int(r["budget_ms"]) for r in self.rows}
        return sum(by_id[h] for h in hops)

    def test_every_row_has_owner_and_measure_method(self) -> None:
        for row in self.rows:
            self.assertTrue(row["owner"].strip(), f"{row['hop']} lost its owner")
            self.assertTrue(
                row["measure_method"].strip(), f"{row['hop']} lost its measure method"
            )
            self.assertGreater(int(row["budget_ms"]), 0, f"{row['hop']} has no budget")

    def test_p0_warm_path_sum_under_gate_c(self) -> None:
        warm = self._sum(["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"])
        self.assertLessEqual(warm, GATE_C_MS, "P0 warm path breached the Gate C bar")

    def test_p1_hands_free_substitution_stays_under_gate_c(self) -> None:
        hands_free = self._sum(["L0h", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"])
        self.assertLessEqual(hands_free, GATE_C_MS)

    def test_budget_headroom_documented_matches_csv(self) -> None:
        # latency-budget.md pins the warm sum at 1,955 ms — keep the CSV honest
        # against the doc so a silent budget change cannot slip past review.
        warm = self._sum(["L0", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"])
        self.assertEqual(warm, 1955)

    def test_all_lat_ids_present(self) -> None:
        ids = {r["hop"] for r in self.rows}
        self.assertTrue(
            {"L0", "L0h", "L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"} <= ids
        )


if __name__ == "__main__":
    unittest.main()
