"""Ledger entry builders (2026-11-08, founder's logging ask).

The gate stages (03-check, 09-review's two calls) append every issue they
receive to the run's issues_ledger.jsonl via RunContext.append_ledger. This
module is the single shape definition for those lines, so cross-run analysis
(scripts/issue_report.py) can group by stage / severity / category and name
the failure classes that prompting and generation should target.

`unverified` is split out because the reviewer's honest way-out ("I suspect
but cannot confirm") must not be counted as a confirmed defect when judging
how often real problems appear.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from .issue_categories import issue_category


def issue_entry(
    stage: str,
    call: str,
    round_tag: str | None,
    issue: dict[str, Any],
    default_category: str = "other",
) -> dict[str, Any]:
    """One issues_ledger line from a reviewer issue dict.

    stage: pipeline stage id (e.g. "09-review"); call: which reviewer call
    produced it ("facts" / "design" / "check"); round_tag: the catcher round
    ("round-01") or None for the first pass.

    The category is derived deterministically from the issue itself: a model
    category is kept verbatim, a code rule id maps through
    `factory.issue_categories`, and only an issue with neither falls back to
    the stage default. `rule` is carried so cross-run reports can group by the
    exact rule that fired (P4, 2026-11-15).
    """
    message = str(issue.get("message", ""))
    return {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "stage": stage,
        "call": call,
        "round_tag": round_tag,
        "block_id": issue.get("block_id"),
        "severity": issue.get("severity", "?"),
        "category": issue_category(issue, default_category),
        "rule": issue.get("rule") or issue.get("check_id") or None,
        "message": message,
        "unverified": message.startswith("unverified:"),
    }
