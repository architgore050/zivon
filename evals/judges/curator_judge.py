"""Curator LLM Judge (`EV-CUR-001` — `evals/judges/curator_judge.py`).

Verifies claim-to-passage quote fidelity and checks that `ground_truth` claims
and equations introduce zero smuggled concepts outside the source pack.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from factory.agents import GLOBAL_RULES, _gt_text, _pack_text
from factory.config import load_config
from factory.schemas import CHECK_REPORT

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord
from .base import JudgeClient, JudgeOutcome, verify_source_quote


def evaluate_curator_ground_truth(
    cfg: EvalConfig,
    card: EvalCard,
    judge_client: JudgeClient,
    context: dict[str, Any],
) -> JudgeOutcome:
    """Invoke the Curator quote-fidelity and concept-smuggling judge via `llm_manager`."""
    sample_path = cfg.goldens_dir / "defects" / "03-check" / "SD-CHK-007.json"
    sample = json.loads(sample_path.read_text(encoding="utf-8"))
    pack = context.get("source_pack") or sample["inputs"]["source_pack"]
    gt = context.get("ground_truth") or sample["inputs"]["ground_truth"]

    env_patch = {
        "ZIVON_BASE_URL": cfg.judge_base_url or "http://127.0.0.1:8080/v1",
        "ZIVON_MODEL": cfg.judge_model if cfg.judge_model != "unconfigured" else "eval-judge",
    }
    with mock.patch.dict("os.environ", env_patch):
        fcfg = load_config(cfg.repo_root / "config.json")
    prompt = (
        "SOURCE MATERIAL (the only allowed facts):\n\n"
        + _pack_text(fcfg, pack)
        + "\n\nGROUND TRUTH TO VERIFY:\n\n"
        + _gt_text(gt)
        + "\n\nTASK: Verify every claim-NN and eq-NN against the SOURCE MATERIAL.\n"
        "Severity ladder:\n"
        "- fatal: a claim or equation contradicts the cited source passage, or cites a passage "
        "that does not support it. Quote the exact source text.\n"
        "- major: a claim smuggles in a Physics concept from outside the source pack.\n"
        "- minor: wording/formatting or unverifiable suspicion starting 'unverified:'.\n"
        'Return {"verdict": "pass"|"fail", "issues": [{"block_id": "claim-01", '
        '"severity": "fatal"|"major"|"minor", "message": "..."}]}.'
    )
    messages = [
        {
            "role": "system",
            "content": f"[ZIVON STAGE: 03-check] You are the Curator Fact Judge.\n{GLOBAL_RULES}",
        },
        {"role": "user", "content": prompt},
    ]
    report, _lat, _think, _comp, _fin = judge_client.call_json(
        "curator_judge",
        messages,
        CHECK_REPORT,
        "check_report",
    )

    corpus = pack.get("ncert_text", "")
    issues: list[IssueRecord] = []
    for raw_i in report.get("issues", []):
        sev = raw_i["severity"]
        msg = raw_i["message"]
        if sev == "fatal" and not verify_source_quote(msg, corpus):
            # Demote unquoted fatal to minor unverified per ADR-0028 quote-grounding law
            sev = "minor"
            if not msg.startswith("unverified:"):
                msg = f"unverified: {msg}"
        issues.append(
            IssueRecord(
                severity=sev,
                block_id=raw_i.get("block_id"),
                category="fact",
                message=msg,
                unverified=msg.startswith("unverified:"),
            )
        )

    fatals = sum(1 for i in issues if i.severity == "fatal")
    majors = sum(1 for i in issues if i.severity == "major")
    verdict = "fail" if fatals > 0 or majors > card.thresholds.get("major_issues_max", 0) else "pass"
    score = 1.0 if verdict == "pass" else 0.0
    return JudgeOutcome(
        score=score,
        verdict=verdict,
        issues=issues,
        metrics={"claim_quote_precision": 1.0 if fatals == 0 else 0.0},
        stats=judge_client.stats,
    )
