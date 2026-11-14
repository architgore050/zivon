"""Deterministic checker template for a Zivon eval card.

Copy to `evals/checkers/<area>.py`, rename the function, and point the card's
`deterministic_checks[].entrypoint` at `<module>:<function>`.

Contract (evals/checkers/__init__.py):

    check_<name>(cfg: EvalConfig, card: EvalCard, context: dict[str, Any])
        -> list[IssueRecord]

- 0 model calls, 0 network, 0 secrets. A pure function of artifacts + goldens.
- Reuse the factory rule instead of re-implementing it; name it in the card's
  `reuses_factory_rule`.
- Never raise for a data problem: return a `fatal` IssueRecord naming the path.
- If there is no data to grade, record the reason in
  `context["skipped_checks"][CHECK_ID]` and return `[]`. A skip is honest; a
  fabricated pass is how a broken pipeline reports 1.0.
"""

from __future__ import annotations

import json
from typing import Any

from evals.config import EvalConfig
from evals.models import EvalCard, IssueRecord

CHECK_ID = "DET-SYN03-GOLDEN-REGISTERED"


def check_golden_registration(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """Every topic the card names must exist with its three golden files.

    This is a real, cheap invariant: a card that points at a missing or
    malformed golden is not evaluating anything. Replace it with the
    failure-mode-specific check your card owns.
    """
    issues: list[IssueRecord] = []
    topics = [str(topic) for topic in (card.golden_inputs.get("topics") or [])]
    if not topics:
        context.setdefault("skipped_checks", {})[CHECK_ID] = (
            "card declares no golden topics"
        )
        return issues

    required_files = ("expected.json", "source_pack_meta.json", "artifact_ref.json")
    for rel in topics:
        topic_dir = (cfg.repo_root / rel).resolve()
        if not topic_dir.is_dir():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    message=f"golden topic directory is missing: {rel}",
                )
            )
            continue
        for name in required_files:
            if not (topic_dir / name).is_file():
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        message=f"golden topic {rel} is missing {name}",
                    )
                )
                continue
        expected_path = topic_dir / "expected.json"
        if not expected_path.is_file():
            continue
        try:
            expected = json.loads(expected_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    message=f"{rel}/expected.json does not parse: {exc}",
                )
            )
            continue
        bounds = expected.get("structure_bounds")
        if not isinstance(bounds, dict):
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    message=f"{rel}/expected.json has no structure_bounds object",
                )
            )
            continue
        low = bounds.get("blocks_min")
        high = bounds.get("blocks_max")
        if not isinstance(low, int) or not isinstance(high, int) or low > high:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    message=(
                        f"{rel}/expected.json structure_bounds blocks_min/blocks_max "
                        f"are incoherent: {low!r}..{high!r}"
                    ),
                )
            )
    return issues
