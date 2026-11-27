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
        # 31 was the baseline before the four P2 assessment checkers landed
        # (EV-ASM-001..004), then 35 before the four P3 exam/series checkers
        # (EV-EXM-001, EV-SER-001..003), both 2026-11-17, then 39 before the
        # seven W5.5 PL2 checkers (DET-PL01-SM/SCHEMA/SCORE + DET-PL02-CITATIONS/
        # PROVENANCE/SCOPE/FALLBACK) and eight EV-PL-003 artifact checkers
        # (W5.5 PL3), both 2026-11-18, then 54 before the six EV-PL-004
        # (NORMALIZE/PII/KEY/INJECT/PARITY/SAVE-PRIVACY) and twelve EV-PL-005
        # (QUOTA/RATE/CSRF/IDOR/ARTIFACT-REF/DELETE/EXPORT/LOGS/HEADERS/
        # NO-PAYWALL/NEXT/SECRETS) security checkers (W5.5 PL5, 2026-11-19),
        # then 73 before the concept-map gate checker DET-REV02-CONCEPT-MAP-GATE
        # (issue 118, 2026-11-27). The count is pinned so a checker silently
        # disappearing fails here.
        self.assertEqual(total_executed, 73)

    def test_seeded_security_defects_sd_sec_001_to_005_all_caught(self) -> None:
        ctx: dict[str, Any] = {}
        issues = check_security_defect_corpus(self.cfg, self.cards["EV-REV-002"], ctx)
        self.assertEqual(issues, [])
        metrics = ctx.get("metrics") or {}
        self.assertEqual(metrics.get("security_catch_rate"), 1.0)


if __name__ == "__main__":
    unittest.main()
