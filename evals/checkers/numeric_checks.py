"""Deterministic numeric/unit checks for `EV-SYN-003` (0 model calls).

Runs `factory.checks.rule_numeric_recompute` over the golden drafts and proves
two properties:

1. clean goldens carry no blocking numeric finding, and a planted arithmetic
   mutation IS caught (the rule is not vacuously green);
2. every finding the rule cannot prove is a `minor` starting with
   `unverified:` - the way-out contract that keeps unparsable maths from ever
   becoming a false blocker.

The checker never recomputes with a model and never calls the network.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from factory.checks import rule_numeric_recompute

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

CHECK_ID = "DET-SYN03-NUMERIC-RECOMPUTE"
WAY_OUT_ID = "DET-SYN03-WAY-OUT"

_CLEAN_FIXTURE = Path("evals/goldens/defects/03-check/SD-CHK-007.json")


def _topic_blocks(cfg: EvalConfig, topic_rel: str) -> list[dict[str, Any]]:
    """Blocks for a golden topic: its published i18n bundle, else the clean
    GT-01 fixture (documented: the class-9 golden has no i18n bundle)."""
    ref_path = cfg.repo_root / topic_rel / "artifact_ref.json"
    if ref_path.is_file():
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        published = ref.get("published_dir")
        if published:
            bundle = cfg.repo_root / published / "i18n" / "en.json"
            if bundle.is_file():
                return list(json.loads(bundle.read_text(encoding="utf-8"))["blocks"])
    fixture = cfg.repo_root / _CLEAN_FIXTURE
    if fixture.is_file():
        return list(
            json.loads(fixture.read_text(encoding="utf-8"))["inputs"]["blocks"][
                "blocks"
            ]
        )
    return []


def _blocking(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [i for i in issues if i.get("severity") in ("fatal", "major")]


def check_numeric_recompute(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN03-NUMERIC-RECOMPUTE`: clean goldens pass; planted error fails."""
    issues: list[IssueRecord] = []
    metrics = context.setdefault("metrics", {})
    topics = 0
    blocks = 0
    checked = 0
    verified = 0
    clean_blocks: list[dict[str, Any]] | None = None

    for topic_rel in card.golden_inputs.get("topics", []):
        topic_blocks = _topic_blocks(cfg, topic_rel)
        if not topic_blocks:
            continue
        topics += 1
        blocks += len(topic_blocks)
        if clean_blocks is None:
            clean_blocks = topic_blocks
        for block in topic_blocks:
            report = rule_numeric_recompute([block])
            if any(i.get("severity") in ("fatal", "major") for i in report):
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id=CHECK_ID,
                        block_id=block.get("id"),
                        category="numeric",
                        message=f"{topic_rel}: numeric gate flagged a clean block: "
                        + "; ".join(i["message"] for i in report),
                    )
                )
            checked += 1
            verified += 1 if not report else 0

    mutation_caught = False
    if clean_blocks:
        mutated = copy.deepcopy(clean_blocks)
        for block in mutated:
            if block.get("type") == "worked_example":
                # Plant an arithmetic contradiction the rule must catch:
                # 10 / 5 is 2, so a step asserting 3 is provably wrong.
                block["spec"].setdefault("steps", []).append(
                    {"title": "Planted", "detail": "a = 10 / 5 = 3 m/s2."}
                )
                break
        mutation_caught = bool(_blocking(rule_numeric_recompute(mutated)))
        if not mutation_caught:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id=CHECK_ID,
                    category="numeric",
                    message="planted arithmetic error was NOT caught by "
                    "factory.checks.rule_numeric_recompute (rule is vacuous)",
                )
            )

    metrics["numeric_topics"] = topics
    metrics["numeric_blocks"] = blocks
    metrics["numeric_checked"] = checked
    metrics["numeric_reported"] = checked - verified
    metrics["numeric_mutation_caught"] = mutation_caught
    return issues


def check_numeric_way_out(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """`DET-SYN03-WAY-OUT`: unprovable maths is `unverified:` minor, never blocking."""
    issues: list[IssueRecord] = []
    metrics = context.setdefault("metrics", {})
    unverified = 0
    minors = 0
    total = 0
    for topic_rel in card.golden_inputs.get("topics", []):
        for block in _topic_blocks(cfg, topic_rel):
            for finding in rule_numeric_recompute([block]):
                total += 1
                message = str(finding.get("message", ""))
                if message.startswith("unverified:"):
                    unverified += 1
                    if finding.get("severity") != "minor":
                        issues.append(
                            IssueRecord(
                                severity="fatal",
                                check_id=WAY_OUT_ID,
                                block_id=block.get("id"),
                                category="numeric",
                                message="`unverified:` finding must be minor, got "
                                f"{finding.get('severity')!r}",
                            )
                        )
                elif finding.get("severity") == "minor":
                    minors += 1
    metrics["numeric_findings_total"] = total
    metrics["numeric_unverified"] = unverified
    metrics["numeric_minor_reported"] = minors
    metrics["numeric_unverified_rate"] = round(unverified / total, 4) if total else 0.0
    return issues
