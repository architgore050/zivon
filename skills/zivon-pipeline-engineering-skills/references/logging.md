# Logging

The factory emits **structured events** through `logging_manager.log_event`.
Progress lines printed to stdout are a human heartbeat; they are not telemetry.
This file is the pipeline-facing summary. The binding contracts are
`docs/specs/observability/logging-api.md`,
`docs/specs/observability/instrumentation-map.csv`, and
`docs/specs/observability/spec.md`; the deeper, cross-module treatment belongs
to the sibling evals/observability skill bundle if it is installed. Dated
**2026-11-14**.

## 1. The only public API

```python
from logging_manager import (
    log_event,
    bind_context,
    context_scope,
    current_context,
    delete_subject,
    LOG_SCHEMA_VERSION,
    Severity,
    ErrorClass,
)
```

`log_event(event, fields=None, *, severity=None, error_class=None,
latency_ms=None, run_id=None, session_id=None, turn_id=None, request_id=None,
stage=None)`.

Rules:

- **Only `log_event`.** No stdlib `logging`, no hand-built JSON lines, no SQL
  into `log_events`, no `print()` pretending to be an event.
- **Event names are contracts.** `<component>.<subject>.<action>`, lowercase
  snake case, one row per event in the instrumentation map.
- **Severity is declared once, in the map.** Do not pass `severity=` to
  override a row because the message "feels" worse.
- **Failure-shaped events carry a closed `ErrorClass`.** Never log a failure
  at `INFO`.
- **Duration events carry `latency_ms`.**
- **One event per attempt** in a retry loop, with `attempt` in `fields`; do not
  re-log duplicates.

Prints remain allowed for the live progress line
(`[06-render] ok in 12.3s ...`). That is the existing pattern and the thing an
operator watches in `kubectl logs`.

## 2. Naming and components

Component enum (closed): `factory`, `llm`, `llm_node`, `voice`, `translator`,
`frontend`, `dashboard`, `credit`, `log`.

Pipeline stages use `component=factory`; model-call client events inside any
consumer use `llm`; the isolated llm-manager node uses `llm_node`; translation
currently emits `factory` (a future translator service may use `translator`).

`stage` is a real stage id: `00-ingest`, `01-locate`, `02-generate`,
`03-check`, `04-repair`, `05-interactive`, `06-render`, `07-perf`,
`08-fixloop`, `09-review`, `10-reviewfix`, `10a-translate`, `10b-transcheck`,
`10c-transrepair`, `10d-transrender`, `11-link`, `12-narration`. A new stage
must be added to `STAGE_ORDER`, the instrumentation map, and
`testing/observability/test_events.py`.

## 3. Correlation: `run_id` is born once

`factory/stages.py::run_pipeline` binds `run_id` at the edge:

```python
bind_context(run_id=run_id)
```

- `run_id` comes from `make_run_id(chapter, class)`, `--run-id`, or
  `ZIVON_RUN_ID` (honored only when it agrees with the id being made).
- Every factory event, model call, and publish joins on that `run_id`.
- `request_id` is created per outbound model call
  (`context_scope(request_id=new_request_id())` in `factory/llm.py`); it joins
  `factory.call.*` and the node's events.
- Never thread ids through function arguments inside a process. Absence is
  honest: do not invent a `session_id` for a factory event.

Cross-process headers: the factory Job sends `X-Request-Id` and
`X-Zivon-Run-Id` to the llm-manager node. The node adds nothing to the
upstream OpenAI-format server.

## 4. Privacy and redaction

`logging_manager` redacts mechanically before any sink. Getting it wrong is a
review blocker.

- **Key denylist:** `transcript*`, `text`, `content`, `prompt`, `messages`,
  `response`, `completion`, `answer`, `page_html`, `code`, `patch`, `audio*`,
  `wav`, `pcm`, `speech*`, `utterance*`, `cookie`, `token`, `secret`, `key`,
  `authorization`.
- **Value scrubs:** emails, Indian phone numbers, Aadhaar-shaped numbers in
  context, `sk-…` / `ZIVON_…` keys, `Bearer …`, JWT-shaped strings, base64
  blobs > 512 chars.
- **Allowed aggregates:** `duration_ms`, `char_count`, `language_mix` (enum),
  `turn_count`, `partial_count`.
- **Use reference fields instead:** `block_id`, `topic`, `chapter`,
  `artifact_path`, `transcript_row_id`, `run_id`, `eval_run_id`.

Never put page content, prompts, answers, or audio bytes in `fields` "just for
debugging". The module scrubs it and emits `log.redaction_violation`; repeated
offences are a review finding.

## 5. Where events land

```text
log_event()
  ├─ stdout                                  always, one JSON line
  ├─ Postgres log_events                     when ZIVON_LOG_DSN is set
  └─ runs/logs/YYYYMMDD-<component>.jsonl    when the DSN is unset or DB down
```

A failed DB batch retries once, falls back to JSONL, and emits
`log.store_fallback`; recovery emits `log.store_recovered`. The JSONL file is
the sync source for the daily log-sync Job; do not rotate it yourself.
`ZIVON_LOG_LEVEL=DEBUG` is dev-only (in DEBUG, programmer errors such as an
unknown event raise).

## 6. Pipeline events

These rows exist in the instrumentation map; emit them through the owning
module and do not duplicate.

| Event | Emitter | Fields | Notes |
|---|---|---|---|
| `factory.run.started` | `factory/stages.py` | `chapter`, `class_level`, `fresh`, `resumed` | run edge |
| `factory.run.resumed` | `factory/stages.py` | `resumed_stages_count` | re-trigger reused stages |
| `factory.run.completed` | `factory/stages.py` | `stage_durations_present`, `blocks_published` | `latency_ms` = run wall time |
| `factory.run.failed` | `factory/stages.py` | `failed_stage`, `reason_code` | `error_class` default `repair_exhausted`; overrides for config/infra |
| `factory.stage.start` | `factory/artifacts.py::mark_stage` | none | one per stage transition |
| `factory.stage.ok` | `mark_stage` | `blocks`, `attempts` | `latency_ms` = stage ms |
| `factory.stage.fail` | `mark_stage` | `reason_code`, `attempt` | `error_class=gate_fail` default |
| `factory.call.started` | `factory/llm.py` | `call_intent`, `attempt` | `call_intent` enum |
| `factory.call.finished` | `factory/llm.py` | `first_token_s`, `chunks_received`, `finish_reason`, `usage_present` | `latency_ms` = call ms |
| `factory.call.rejected` | `factory/llm.py` + checks | `round`, `reason_code` | `validation_error` |
| `factory.call.transport_exhausted` | `factory/llm.py` | `attempts`, `last_status` | `transport_error` |
| `factory.repair.round` | `fixloop.py`, `reviewfix.py`, `stages.py` | `round`, `issues_count` | bounded catcher round (incl. `10c`) |
| `factory.repair.exhausted` | `fixloop.py`, `reviewfix.py`, `stages.py` | `plateau`, `cap_hit` | `repair_exhausted` |
| `factory.coverage.gap_fatal` | `factory/checks.py` | `missing_count` | `gate_fail` |
| `factory.perf.budget_fail` | `factory/perf.py` | `budget_name`, `measured_ms`, `limit_ms` | `gate_fail` |
| `factory.publish.ok` / `.fail` | `scripts/publish-frontend.sh` | `target`, `asset_count` / `reason_code` | publish path |

Rules for adding a row:

1. Add it to `docs/specs/observability/instrumentation-map.csv` with the fixed
   columns (`component,event,severity,correlation_ids,required_fields,
   latency_ms,error_class,privacy_class,emitter,notes`).
2. Emit it from the owning module with `log_event`.
3. Add the name to `testing/observability/test_events.py`'s emitted/reserved
   lists and update the map row-count assertion (a row add without this makes
   CI red).
4. Run the observability suite and `python3 scripts/check_specs.py`.
5. Put the event names in the PR and name the view/consumer, or say "audit
   only".

## 7. Eval telemetry

Use `evals/telemetry.emit_eval_event(evt_id, fields, ...)`, never `log_event`
directly. The canonical ids:

| EVT id | Dot event | Default severity |
|---|---|---|
| `EVT-EVAL-RUN-STARTED` | `factory.eval.run_started` | INFO |
| `EVT-EVAL-RUN-COMPLETED` | `factory.eval.run_completed` | INFO |
| `EVT-EVAL-REGRESSION-ALERT` | `factory.eval.regression_alert` | ERROR |
| `EVT-EVAL-HUMAN-EDIT-RECORDED` | `factory.eval.human_edit_recorded` | INFO |
| `EVT-EVAL-KID-SESSION-LOGGED` | `factory.eval.kid_session_logged` | INFO |

**Known gap (2026-11-14):** the instrumentation map has zero rows for these
events, and the shim's component is `evals`, outside the closed enum. Until
the map/component fix lands, these events produce `log.event_unknown` and land
with an inferred component. Do not add new cards while their events are
undeclared; fix this first (the companion contract recommends adding `evals`
to the enum and the five rows).

## 8. Debugging with the ledgers

- **"Is it alive?"** Read the live progress lines and the 60 s heartbeat
  (`still waiting on the model (Ns, N chunks received...)`). `0 chunks` means
  thinking; growing chunks means streaming. This is not failure.
- **"What did the model burn?"** `runs/<run_id>/calls_ledger.jsonl` and
  `run_report.json.model_call_stats`: attempts, rejected, transport failures,
  `thinking_s`, `max_completion_tokens`.
- **"What did the reviewers actually find?"**
  `runs/<run_id>/issues_ledger.jsonl` and `run_report.json.issues_found`:
  severity, category, block, unverified.
- **"What keeps recurring?"** `scripts/issue_report.py` aggregates across runs:
  per-stage call stats, issue counts by stage/severity/category, recurring
  block+category findings (the plateau signature).
- **"What happened on this call?"** `runs/<run_id>/<stage>/attempts/...`:
  `request.json`, `response.json`, `meta.json` (latency, tokens, finish reason,
  streaming evidence, outcome).

Do not diagnose from a screen scrollback when the artifact exists.

## 9. What "logged" means

A feature is logged only when all of these are true:

1. Every new event has a map row with the correct component, severity,
   correlation, required fields, and privacy class.
2. The code emits through `logging_manager.log_event` with correlation from
   context (no argument threading, no invented IDs).
3. Failure events carry a closed `ErrorClass`; duration events carry
   `latency_ms`.
4. The payload passes redaction (no denylisted key, no learner text, no
   secret).
5. `testing/observability/` passes, including the map-conformance test and the
   updated row count.
6. The event is observable in at least one sink in a normal run (stdout JSONL;
   file or Postgres), verified by a test or a local run.
7. The PR names the events added and the view/consumer, or says "audit only".

"It prints something" is not logged. "It has a log line in a test" is not
logged.

## 10. Anti-patterns

- `print()` or `logging.info()` as telemetry.
- An event name with no map row.
- Passing learner text, prompts, answers, or page HTML through `fields`.
- Inventing a `run_id`/`session_id` where the edge does not exist.
- Logging around a failure (swallow, then INFO).
- Overriding a map-declared severity because the message feels worse.
- Adding a row without updating the observability test's row count.
- Writing `logs/` JSONL or rotating it by hand.
