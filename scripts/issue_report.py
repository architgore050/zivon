#!/usr/bin/env python3
"""Aggregate the factory's ledgers across runs: which failure classes recur?

The pipeline records two append-only JSONL ledgers per run (2026-11-08):
- calls_ledger.jsonl - every model attempt: answered / rejected(+reason) /
  transport-failure, with latency, time-to-first-content (thinking proxy)
  and token usage;
- issues_ledger.jsonl - every reviewer-found issue: stage, call, severity,
  category, block, unverified flag.

This script reads them across every run dir and answers the founder's
question - "what are the agents actually failing at?" - so prompting and
generation fixes can target the classes that keep recurring:

- per-stage call stats: attempts, rejections, transport failures, total
  thinking seconds, max completion tokens (a thinking-loop signature is
  huge thinking_s with finish_reason=length or repeated rejections);
- issue counts by stage / category / severity, confirmed vs unverified;
- recurring findings: the same (stage, call, block, category) across
  multiple catcher rounds - the plateau signature;
- per-run one-liners from run_report.json.

Run against the host mirror of the PVC run dirs (refresh first with
scripts/publish-artifacts.sh):

    python3 scripts/issue_report.py            # reads ./runs
    python3 scripts/issue_report.py --json     # machine-readable

Stdlib only; safe to run anywhere the mirror exists.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue  # torn append line: skip, never crash the report
        if isinstance(row, dict):
            rows.append(row)
    return rows


def aggregate(runs_dir: Path) -> dict[str, Any]:
    calls: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for run_dir in sorted(p for p in runs_dir.iterdir() if p.is_dir()):
        if (run_dir / "calls_ledger.jsonl").exists():
            calls.extend(_read_jsonl(run_dir / "calls_ledger.jsonl"))
        if (run_dir / "issues_ledger.jsonl").exists():
            issues.extend(_read_jsonl(run_dir / "issues_ledger.jsonl"))
        report = run_dir / "run_report.json"
        if report.exists():
            try:
                data = json.loads(report.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            runs.append(
                {
                    "run_id": data.get("run_id", run_dir.name),
                    "ok": data.get("ok"),
                    "duration_s": data.get("duration_s"),
                    "issues_found": data.get("issues_found", {}).get("total", 0),
                }
            )

    # Final state per attempt (answered can be followed by rejected).
    final: dict[tuple[str, str, int], dict[str, Any]] = {}
    for row in calls:
        key = (
            str(row.get("stage", "?")),
            str(row.get("round_tag") or ""),
            int(row.get("attempt") or 0),
        )
        prev = final.get(key)
        if prev is None or row.get("outcome") in ("rejected", "transport-failure"):
            final[key] = row

    per_stage: dict[str, dict[str, Any]] = {}
    for row in final.values():
        stage = str(row.get("stage", "?"))
        stats = per_stage.setdefault(
            stage,
            {
                "attempts": 0,
                "answered": 0,
                "rejected": 0,
                "transport_failures": 0,
                "thinking_s": 0.0,
                "max_completion_tokens": 0,
                "length_cuts": 0,
            },
        )
        stats["attempts"] += 1
        outcome = row.get("outcome")
        if outcome == "rejected":
            stats["rejected"] += 1
        elif outcome == "transport-failure":
            stats["transport_failures"] += 1
        elif outcome == "answered":
            stats["answered"] += 1
        first = row.get("first_token_s")
        if isinstance(first, (int, float)):
            stats["thinking_s"] = round(stats["thinking_s"] + first, 1)
        completion = row.get("completion_tokens")
        if isinstance(completion, (int, float)):
            stats["max_completion_tokens"] = max(
                stats["max_completion_tokens"], int(completion)
            )
        if row.get("finish_reason") == "length":
            stats["length_cuts"] += 1

    by_stage = Counter(str(i.get("stage", "?")) for i in issues)
    by_category = Counter(str(i.get("category") or "other") for i in issues)
    by_severity = Counter(str(i.get("severity", "?")) for i in issues)
    unverified = sum(1 for i in issues if i.get("unverified"))

    # Recurring findings: same (stage, call, block, category) across rounds.
    rounds_by_key: dict[tuple[str, str, str, str], set[str]] = {}
    for i in issues:
        key = (
            str(i.get("stage", "?")),
            str(i.get("call", "?")),
            str(i.get("block_id") or "(page level)"),
            str(i.get("category") or "other"),
        )
        rounds_by_key.setdefault(key, set()).add(str(i.get("round_tag") or "first"))
    recurring = sorted(
        (
            {
                "stage": k[0],
                "call": k[1],
                "block_id": k[2],
                "category": k[3],
                "rounds": len(v),
            }
            for k, v in rounds_by_key.items()
            if len(v) >= 2
        ),
        key=lambda r: -r["rounds"],
    )

    return {
        "runs": runs,
        "calls_total": len(final),
        "calls_by_stage": dict(sorted(per_stage.items())),
        "issues_total": len(issues),
        "issues_unverified": unverified,
        "issues_by_stage": dict(by_stage.most_common()),
        "issues_by_category": dict(by_category.most_common()),
        "issues_by_severity": dict(by_severity.most_common()),
        "recurring_findings": recurring,
    }


def _print_report(data: dict[str, Any]) -> None:
    print(f"runs analysed: {len(data['runs'])}")
    for run in data["runs"]:
        print(
            f"  {run['run_id']}: ok={run['ok']} duration={run['duration_s']}s "
            f"issues={run['issues_found']}"
        )

    print(f"\nmodel calls (final state per attempt): {data['calls_total']}")
    print(
        f"{'stage':<16} {'att':>4} {'ans':>4} {'rej':>4} {'t-fail':>6} {'thinking_s':>10} {'max_comp':>8} {'len-cut':>7}"
    )
    for stage, s in data["calls_by_stage"].items():
        print(
            f"{stage:<16} {s['attempts']:>4} {s['answered']:>4} {s['rejected']:>4} "
            f"{s['transport_failures']:>6} {s['thinking_s']:>10} "
            f"{s['max_completion_tokens']:>8} {s['length_cuts']:>7}"
        )

    print(
        f"\nissues found: {data['issues_total']} (unverified way-out: {data['issues_unverified']})"
    )
    print("  by stage:   ", data["issues_by_stage"])
    print("  by severity:", data["issues_by_severity"])
    print("  by category:", data["issues_by_category"])

    if data["recurring_findings"]:
        print("\nrecurring findings (same block+class across catcher rounds):")
        for r in data["recurring_findings"]:
            print(
                f"  {r['stage']}/{r['call']} block {r['block_id']} "
                f"[{r['category']}] in {r['rounds']} rounds"
            )
    else:
        print("\nno recurring findings across rounds.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "runs_dir", nargs="?", default="runs", help="mirror of run dirs"
    )
    parser.add_argument("--json", action="store_true", help="print raw JSON instead")
    args = parser.parse_args(argv)
    runs_dir = Path(args.runs_dir)
    if not runs_dir.is_dir():
        print(f"no runs dir at {runs_dir} (run scripts/publish-artifacts.sh first)")
        return 2
    data = aggregate(runs_dir)
    if args.json:
        print(json.dumps(data, indent=1, ensure_ascii=False))
    else:
        _print_report(data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
