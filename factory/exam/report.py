"""Deterministic gate report for exam/series artifacts.

Same shape as `factory.assessment.validators.gate_report` on purpose - the
admin coverage view (ADM-11) and the eval checkers read one report format - but
deliberately *not* imported from the assessment package: the two entrypoints are
independent (HANDSHAKE Q-1), and a shared dataclass would make an assessment
refactor break the exam pipeline for no product reason.

Severity scale is the repo's: `fatal` / `major` block, `minor` is recorded debt.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import jsonschema

SEVERITY_RANK = {"minor": 1, "major": 2, "fatal": 3}


@dataclass(frozen=True)
class Issue:
    """One gate finding. `rule` is the stable id the eval cards assert on."""

    rule: str
    severity: str
    message: str
    item_id: str | None = None
    paper_id: str | None = None
    chapter_id: str | None = None
    series_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }
        for key in ("item_id", "paper_id", "chapter_id", "series_id"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        return out


def schema_issue(prefix: str, exc: Exception, **kwargs: Any) -> Issue:
    """Wrap a jsonschema failure as one fatal, stable-rule finding."""
    if isinstance(exc, jsonschema.ValidationError):
        where = "/".join(str(part) for part in exc.absolute_path) or "<root>"
        message = f"{where}: {exc.message}"
    else:  # pragma: no cover - defensive
        message = str(exc)
    return Issue(rule=f"{prefix}.schema", severity="fatal", message=message, **kwargs)


def validate_schema(instance: Any, schema: dict[str, Any], name: str) -> None:
    """Raise the underlying jsonschema error; callers turn it into an Issue."""
    jsonschema.validate(instance=instance, schema=schema)
    _ = name  # kept for a readable call site


def gate_report(
    issues: Sequence[Issue], *, counts: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """The artifact every gated stage writes: verdict + stable findings."""
    blocking = [i for i in issues if i.severity in ("fatal", "major")]
    warnings = [i for i in issues if i.severity == "minor"]
    by_rule: dict[str, int] = {}
    for issue in issues:
        by_rule[issue.rule] = by_rule.get(issue.rule, 0) + 1
    return {
        "verdict": "fail" if blocking else "pass",
        "error_count": len(blocking),
        "warning_count": len(warnings),
        "issues": [i.to_dict() for i in issues],
        "rules": dict(sorted(by_rule.items())),
        "counts": dict(counts or {}),
    }


def blocking_issues(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        issue
        for issue in report.get("issues", [])
        if issue.get("severity") in ("fatal", "major")
    ]


def issues_for_reasons(report: Mapping[str, Any]) -> list[str]:
    """Human-readable one-line summaries for a gate failure message."""
    return [
        f"[{issue['severity']}] {issue['rule']}: {issue['message']}"
        for issue in blocking_issues(report)
    ]


def report_rules(report: Mapping[str, Any]) -> set[str]:
    """Every rule id that fired, blocking or not (eval assertions use this)."""
    return {str(issue.get("rule")) for issue in report.get("issues", [])}


def merge_reports(*reports: Mapping[str, Any]) -> dict[str, Any]:
    """Combine stage reports without losing the individual findings."""
    issues: list[dict[str, Any]] = []
    counts: dict[str, Any] = {}
    for report in reports:
        issues.extend(report.get("issues", []))
        counts.update(report.get("counts", {}))
    blocking = [i for i in issues if i.get("severity") in ("fatal", "major")]
    warnings = [i for i in issues if i.get("severity") == "minor"]
    by_rule: dict[str, int] = {}
    for issue in issues:
        by_rule[str(issue.get("rule"))] = by_rule.get(str(issue.get("rule")), 0) + 1
    return {
        "verdict": "fail" if blocking else "pass",
        "error_count": len(blocking),
        "warning_count": len(warnings),
        "issues": issues,
        "rules": dict(sorted(by_rule.items())),
        "counts": counts,
    }


def dumps(payload: Any) -> str:
    """Stable, human-readable JSON (the pack's file format)."""
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


__all__ = [
    "SEVERITY_RANK",
    "Issue",
    "blocking_issues",
    "dumps",
    "gate_report",
    "issues_for_reasons",
    "merge_reports",
    "report_rules",
    "schema_issue",
    "validate_schema",
]
