"""Observability & telemetry hooks for `evals/` (SP3 contract + fallback shim).

Codes against the `logging_manager` public API contract (`docs/specs/observability/logging-api.md`)
and emits the `EVT-EVAL-*` events and Prometheus metrics specified in
`docs/specs/evals/spec.md` §6.2.

When `EX3-OBS`'s `logging_manager` package is present in the environment, all
calls delegate directly to it; prior to Wave-E merge, the built-in SP3-compliant
shim formats JSON lines v1, enforces redaction, and writes to `evals_runs/logs/`.
"""

from __future__ import annotations

import contextvars
import enum
import json
import os
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LOG_SCHEMA_VERSION = 1


class Severity(str, enum.Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class ErrorClass(str, enum.Enum):
    transport_error = "transport_error"
    validation_error = "validation_error"
    gate_fail = "gate_fail"
    repair_exhausted = "repair_exhausted"
    infra_error = "infra_error"
    quota_error = "quota_error"
    auth_error = "auth_error"
    client_error = "client_error"
    privacy_violation = "privacy_violation"
    store_error = "store_error"


# Canonical event mapping between SP4 EVT-EVAL-* IDs and SP3 dot-namespaced events
EVAL_EVENT_MAP: dict[str, tuple[str, Severity]] = {
    "EVT-EVAL-RUN-STARTED": ("factory.eval.run_started", Severity.INFO),
    "EVT-EVAL-RUN-COMPLETED": ("factory.eval.run_completed", Severity.INFO),
    "EVT-EVAL-REGRESSION-ALERT": ("factory.eval.regression_alert", Severity.ERROR),
    "EVT-EVAL-HUMAN-EDIT-RECORDED": ("factory.eval.human_edit_recorded", Severity.INFO),
    "EVT-EVAL-KID-SESSION-LOGGED": ("factory.eval.kid_session_logged", Severity.INFO),
}

_CTX_VARS: contextvars.ContextVar[dict[str, str] | None] = contextvars.ContextVar(
    "zivon_eval_log_ctx",
    default=None,  # mutable {} default is unsafe (B039)
)

_DENYLIST_KEY_RE = re.compile(
    r"^(transcript.*|text|content|prompt|messages|response|completion|answer|"
    r"page_html|code|patch|audio.*|wav|pcm|speech.*|utterance.*|cookie|token|"
    r"secret|key|authorization)$",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+91[\s-]?)?[6-9]\d{9}\b")
_SECRET_VAL_RE = re.compile(r"\b(?:sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._-]+)\b")


def _redact_value(val: Any) -> Any:
    if isinstance(val, str):
        s = _EMAIL_RE.sub("[REDACTED:email]", val)
        s = _PHONE_RE.sub("[REDACTED:phone]", s)
        s = _SECRET_VAL_RE.sub("[REDACTED:secret]", s)
        return s
    if isinstance(val, list):
        return [_redact_value(x) for x in val]
    if isinstance(val, dict):
        return _redact_fields(val)
    return val


def _redact_fields(fields: dict[str, Any] | None) -> dict[str, Any]:
    if not fields:
        return {}
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if _DENYLIST_KEY_RE.match(str(k)):
            out[k] = "[REDACTED:key-denylist]"
        else:
            out[k] = _redact_value(v)
    return out


def bind_context(**kwargs: str | None) -> None:
    """Bind correlation IDs (`run_id`, `session_id`, `turn_id`, `request_id`)."""
    try:
        import logging_manager  # type: ignore[import-not-found]

        clean = {k: v for k, v in kwargs.items() if v is not None}
        logging_manager.bind_context(**clean)  # type: ignore[arg-type]
        return
    except ImportError:
        pass
    cur = dict(_CTX_VARS.get() or {})
    for k, v in kwargs.items():
        if v is not None:
            cur[k] = v
    _CTX_VARS.set(cur)


@contextmanager
def context_scope(**kwargs: str | None) -> Iterator[None]:
    """Task-local context override for correlation IDs."""
    try:
        import logging_manager  # type: ignore[import-not-found]

        clean = {k: v for k, v in kwargs.items() if v is not None}
        with logging_manager.context_scope(**clean):  # type: ignore[arg-type]
            yield
        return
    except ImportError:
        pass
    prev = dict(_CTX_VARS.get() or {})
    merged = dict(prev)
    for k, v in kwargs.items():
        if v is not None:
            merged[k] = v
    token = _CTX_VARS.set(merged)
    try:
        yield
    finally:
        _CTX_VARS.reset(token)


def current_context() -> dict[str, str]:
    """Return a read-only snapshot of active correlation IDs."""
    try:
        import logging_manager  # type: ignore[import-not-found]

        return dict(logging_manager.current_context())
    except ImportError:
        return dict(_CTX_VARS.get() or {})


def emit_eval_event(
    evt_id: str,
    fields: dict[str, Any] | None = None,
    *,
    severity: Severity | None = None,
    error_class: ErrorClass | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,
    stage: str | None = None,
    fallback_dir: Path | None = None,
) -> dict[str, Any]:
    """Emit an `EVT-EVAL-*` structured telemetry event via `logging_manager` or shim."""
    dot_event, default_sev = EVAL_EVENT_MAP.get(evt_id, (evt_id, Severity.INFO))
    eff_sev = severity or default_sev
    redacted = _redact_fields({"evt_id": evt_id, **(fields or {})})
    ctx = current_context()
    eff_run_id = run_id or ctx.get("run_id")

    try:
        import logging_manager  # type: ignore[import-not-found]

        logging_manager.log_event(
            dot_event,
            redacted,
            severity=logging_manager.Severity(eff_sev.value),
            error_class=(
                logging_manager.ErrorClass(error_class.value) if error_class else None
            ),
            latency_ms=latency_ms,
            run_id=eff_run_id,
            stage=stage,
        )
    except ImportError:
        pass

    now_iso = (
        datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    )
    record: dict[str, Any] = {
        "ts": now_iso,
        "schema_version": LOG_SCHEMA_VERSION,
        "severity": eff_sev.value,
        "event": dot_event,
        "evt_id": evt_id,
        "component": "factory",
        "env": os.environ.get("ZIVON_ENV", "dev"),
    }
    if eff_run_id:
        record["run_id"] = eff_run_id
    if stage:
        record["stage"] = stage
    if latency_ms is not None:
        record["latency_ms"] = max(0, int(latency_ms))
    if error_class is not None:
        record["error_class"] = error_class.value
    record["fields"] = redacted

    if fallback_dir is not None:
        logs_dir = fallback_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        day_str = datetime.now(UTC).strftime("%Y%m%d")
        log_file = logs_dir / f"{day_str}-evals.jsonl"
        with log_file.open("a", encoding="utf-8") as fh:
            fh.write(
                json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
            )

    return record


def format_prometheus_metrics(
    report_dict: dict[str, Any],
    human_edits: list[dict[str, Any]] | None = None,
) -> str:
    """Format the 6 Prometheus metrics from `docs/specs/evals/spec.md` §6.2."""
    lines: list[str] = [
        "# HELP zivon_eval_card_score Evaluation card score (0.0-1.0)",
        "# TYPE zivon_eval_card_score gauge",
    ]
    for card in report_dict.get("cards", []):
        cid = card["card_id"]
        stage = card["stage"]
        det = card.get("deterministic_score", 0.0)
        lines.append(
            f'zivon_eval_card_score{{card_id="{cid}",stage="{stage}",mode="deterministic"}} {det:.4f}'
        )
        judge = card.get("judge_score")
        if judge is not None:
            lines.append(
                f'zivon_eval_card_score{{card_id="{cid}",stage="{stage}",mode="judge"}} {judge:.4f}'
            )

    lines.extend(
        [
            "# HELP zivon_eval_reviewer_recall Reviewer calibration recall on planted defects",
            "# TYPE zivon_eval_reviewer_recall gauge",
            "# HELP zivon_eval_reviewer_specificity Reviewer specificity on clean goldens",
            "# TYPE zivon_eval_reviewer_specificity gauge",
        ]
    )
    for card in report_dict.get("cards", []):
        cid = card["card_id"]
        metrics = card.get("metrics") or {}
        if "fatal_recall" in metrics:
            lines.append(
                f'zivon_eval_reviewer_recall{{card_id="{cid}",severity="fatal"}} {float(metrics["fatal_recall"]):.4f}'
            )
        if "blocking_recall" in metrics:
            lines.append(
                f'zivon_eval_reviewer_recall{{card_id="{cid}",severity="blocking"}} {float(metrics["blocking_recall"]):.4f}'
            )
        if "clean_specificity" in metrics:
            lines.append(
                f'zivon_eval_reviewer_specificity{{card_id="{cid}"}} {float(metrics["clean_specificity"]):.4f}'
            )

    lines.extend(
        [
            "# HELP zivon_eval_human_edit_rate Human edit rate per generated topic",
            "# TYPE zivon_eval_human_edit_rate gauge",
        ]
    )
    for edit in human_edits or []:
        slug = edit.get("topic_slug", "unknown")
        cls_lv = edit.get("class_level", 0)
        rate = float(edit.get("human_edit_rate", 0.0))
        lines.append(
            f'zivon_eval_human_edit_rate{{topic_slug="{slug}",class_level="{cls_lv}"}} {rate:.4f}'
        )

    gate_b = report_dict.get("summary", {}).get("gate_b_comprehension_rate", 1.0)
    lines.extend(
        [
            "# HELP zivon_eval_gate_b_pass_rate Gate B kid comprehension cohort pass rate",
            "# TYPE zivon_eval_gate_b_pass_rate gauge",
            f'zivon_eval_gate_b_pass_rate{{round="current"}} {float(gate_b):.4f}',
            "# HELP zivon_eval_run_duration_seconds Duration of eval suite run in seconds",
            "# TYPE zivon_eval_run_duration_seconds gauge",
            f'zivon_eval_run_duration_seconds{{suite="{report_dict.get("suite", "smoke")}"}} {float(report_dict.get("duration_s", 0.0)):.2f}',
        ]
    )
    return "\n".join(lines) + "\n"
