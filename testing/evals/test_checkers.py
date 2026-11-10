"""Unit tests for `evals/checkers/*` deterministic checkers."""

from __future__ import annotations

import unittest
from typing import Any

from evals.checkers import run_deterministic_check
from evals.checkers.visual_checks import check_security_defect_corpus
from evals.config import EvalConfig
from evals.models import load_all_cards


class TestDeterministicCheckers(unittest.TestCase):
    def setUp(self) -> None:
        self.cfg = EvalConfig.from_env({})
        self.cards = load_all_cards(self.cfg.cards_dir)

    def test_all_card_deterministic_checks_pass_on_shipped_goldens(self) -> None:
        total_executed = 0
        for card_id, card in self.cards.items():
            for chk in card.deterministic_checks:
                ctx: dict[str, object] = {}
                issues = run_deterministic_check(chk.entrypoint, self.cfg, card, ctx)
                blocking = [i for i in issues if i.severity in ("fatal", "major")]
                self.assertEqual(
                    blocking,
                    [],
                    f"{card_id} / {chk.id} reported unexpected blocking issues: {blocking}",
                )
                total_executed += 1
        self.assertEqual(total_executed, 24)

    def test_seeded_security_defects_sd_sec_001_to_005_all_caught(self) -> None:
        ctx: dict[str, Any] = {}
        issues = check_security_defect_corpus(self.cfg, self.cards["EV-REV-002"], ctx)
        self.assertEqual(issues, [])
        metrics = ctx.get("metrics") or {}
        self.assertEqual(metrics.get("security_catch_rate"), 1.0)


if __name__ == "__main__":
    unittest.main()
