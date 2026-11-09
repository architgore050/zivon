# logging_manager — API contract (SP3-OBS)

**This is the contract every module codes against.** The system decisions (why stdlib JSON logging, why Postgres, why this auth) live in ADR-0017/0018/0019 and [`spec.md`](spec.md). This document pins the exact surface: signatures, the JSON line schema, sinks, header propagation, and the closed vocabularies. If your code needs something not expressible through this surface, open an OQ in [`open-questions.md`](open-questions.md) — do not work around the module.

## 1. Package layout

```
logging_manager/
  __init__.py        # public surface only (re-exports below)
  events.py          # LOG_SCHEMA_VERSION, Severity enum, event-name validation
  context.py         # contextvars helpers
  redact.py          # denylist + value regexes (spec §4)
  sink.py            # Postgres sink, JSONL fallback sink, stdout line writer
  store.py           # DDL + sweeper/sync SQL helpers (delete_subject lives here)
  requirements.txt   # DB driver only (JSON path is stdlib-only)
```

Public surface (everything else is private; importing privates fails review):

```python
from logging_manager import (
    log_event, bind_context, context_scope, current_context,
    delete_subject, LOG_SCHEMA_VERSION, Severity, ErrorClass,
)
```

## 2. `log_event()` — the single emission point

```python
def log_event(
    event: str,                        # required, dot.namespaced, must exist in instrumentation-map.csv
    fields: dict[str, Any] | None = None,   # redacted payload (§6)
    *,
    severity: Severity | None = None,  # default: derived from the map (map = declared once per event)
    error_class: ErrorClass | None = None,  # required for failure-shaped events (closed enum, §8)
    latency_ms: int | None = None,     # when the event measures a duration
    run_id: str | None = None,         # omitted -> taken from context vars
    session_id: str | None = None,     # omitted -> taken from context vars
    turn_id: str | None = None,        # omitted -> taken from context vars
    request_id: str | None = None,     # omitted -> taken from context vars
    stage: str | None = None,          # factory stage id ("00-ingest".."11-link")
) -> None
```

Rules:

- `log_event` never raises: sink failures degrade per §5 (loudly), so telemetry cannot break the caller's path. The ONLY exceptions are programmer errors raised in dev mode (`ZIVON_LOG_LEVEL=DEBUG`): unknown event name, unknown `error_class`, `latency_ms` negative.
- Unknown event name → a `log.event_unknown` WARNING is emitted (naming the offender) and the event is still delivered with component inferred from the package emitting it; CI's map-lint makes this red, not just yellow.
- **Idempotency at the caller:** call sites log an event when the thing happens; they never "re-log on retry" duplicates (retry loops log one event per attempt with `attempt` in fields).

## 3. Context helpers (correlation without plumbing)

```python
bind_context(run_id=..., session_id=..., turn_id=..., request_id=...)  # set at edges
with context_scope(request_id=new_id):     # scoped override (async-safe, task-local)
    ...
current_context() -> dict[str, str]        # read-only snapshot (tests, debugging)
```

- Implementation: `contextvars.ContextVar` — safe for the voice backend's asyncio handlers and the factory's threaded stages; a child task/tasklet inherits, a new pipeline stage binds fresh.
- **Edge discipline:** exactly one `bind_context` per edge — `pipeline.main()` (`run_id`), voice session start (`session_id`), turn handler (`turn_id`), every HTTP/WS request entry (`request_id` per §7). Components never pass IDs through function arguments unless crossing a process boundary.

## 4. JSON line schema v1 (the wire format, everywhere identical)

`LOG_SCHEMA_VERSION = 1`. One event = one JSON object = one line (UTF-8, `json.dumps(..., separators=(",", ":"), ensure_ascii=False)`), field order fixed as below. Emitting code never builds this line by hand.

```json
{"ts":"2026-11-09T09:41:07.412Z","schema_version":1,"severity":"INFO","event":"factory.stage.ok","component":"factory","env":"cluster","run_id":"motion-c9","stage":"03-check","latency_ms":51230,"fields":{"elapsed_s":51.2,"blocks":14}}
{"ts":"2026-11-09T09:41:08.100Z","schema_version":1,"severity":"ERROR","event":"node.call.transport_exhausted","component":"llm_node","env":"cluster","run_id":"motion-c9","request_id":"8f14e45f...","error_class":"transport_error","fields":{"attempts":3,"last_status":502}}
{"ts":"2026-11-09T09:41:09.735Z","schema_version":1,"severity":"INFO","event":"voice.turn.e2e_latency","component":"voice","env":"cluster","session_id":"0d0c8b2e-...","turn_id":"4b1f0a...","request_id":"91d2c...","latency_ms":3410,"fields":{"stt_final_ms":540,"llm_first_token_ms":880,"tts_first_audio_ms":1740,"slowest_hop":"tts_first_audio"}}
```

Field table (types are enforced at serialization; `null`/absent means "not applicable", never `""` or `0`):

| Field | Type | Presence | Notes |
|---|---|---|---|
| `ts` | ISO-8601 UTC, ms precision | always | event time, not emit time (backfilled events allowed only inside the emitting process) |
| `schema_version` | int | always | `1` today; bump rules §9 |
| `severity` | enum | always | `DEBUG\|INFO\|WARNING\|ERROR\|CRITICAL` (stdlib names) |
| `event` | string | always | dot.namespaced `<component>.<subject>.<action>`; the name IS the contract — map row must exist |
| `component` | enum | always | `factory\|llm\|llm_node\|voice\|translator\|frontend\|dashboard\|credit\|log` (`log` = this module's own events) |
| `env` | enum | always | `dev\|cluster\|prod` from `ZIVON_ENV` (default `dev`) |
| `run_id` | string | when set | factory's existing `make_run_id` value (adopted verbatim) |
| `session_id` | string (UUID4) | when set | pseudonymous voice session (ADR-0011) |
| `turn_id` | string (UUID4) | when set | one user turn |
| `request_id` | string (UUID4) | when set | one HTTP/WS exchange |
| `client_session_id` | string (UUID4) | frontend events only | browser-session pseudonymous id |
| `stage` | string | factory events | `00-ingest` … `11-link` |
| `latency_ms` | int ≥ 0 | timing events | the map marks which events carry it |
| `error_class` | enum | failure-shaped | §8 closed enum |
| `fields` | object | always (may be `{}`) | REDACTED payload (§6); values: str/int/float/bool/null or flat arrays of scalars, depth ≤ 2 |
| `trace_id` / `span_id` | string | reserved | ADR-0017 OTel path; do not populate yet |

## 5. Sinks (ADR-0018 behavior, exact)

- **Postgres (primary):** when `ZIVON_LOG_DSN` is set — batched inserts (flush every 1 s or 64 events, whichever first; batch failure retries once, then falls back for the batch and emits `log.store_fallback`). Writes go ONLY through this sink: no module writes `log_events` by hand.
- **JSONL fallback:** when the DSN is unset, or the DB is unreachable — append to `runs/logs/YYYYMMDD-<component>.jsonl` on the factory/sources PVC. First switch emits `log.store_fallback` (WARNING, `store_error`); recovery back to Postgres emits `log.store_recovered` (INFO). The fallback file IS a sync source for the daily `log-sync` Job.
- **stdout:** every event is ALSO written as one JSON line to stdout (pod logs stay greppable; `scripts/logs-factory-run.sh` keeps working).
- **DEBUG filtering:** `ZIVON_LOG_LEVEL=INFO` (default) filters DEBUG events at emit — they cost nothing in cluster; `ZIVON_LOG_LEVEL=DEBUG` is a dev-only setting (never set in manifests).

## 6. Redaction (mechanical, before any sink)

Applied inside `log_event` to `fields` (and to any string embedded in a structured value) — the rules and the guarantee live in [`spec.md`](spec.md) §4 and are pinned by `testing/logging_manager/test_redaction.py` when the module lands:

- **Key denylist** (hard-replace with `[REDACTED:key-denylist]`): `transcript*`, `text`, `content`, `prompt`, `messages`, `response`, `completion`, `answer`, `page_html`, `code`, `patch`, `audio*`, `wav`, `pcm`, `speech*`, `utterance*`, `cookie`, `token`, `secret`, `key`, `authorization` (case-insensitive, `*` = any suffix). Use the sanctioned reference fields instead: `transcript_row_id`, `artifact_path`, `block_id`, `topic`, `chapter`.
- **Value regexes** (scrub in place → `[REDACTED:<kind>]`): emails; Indian phone numbers (+91, 10-digit); Aadhaar-shaped numbers (with context words); `sk-…` / `ZIVON_…` API keys; `Bearer …`; JWT-shaped (`eyJ…`); base64 blobs > 512 chars (audio smuggle guard).
- **Allowed learner-shaped aggregates:** `duration_ms`, `char_count`, `language_mix` (enum), `turn_count`, `partial_count` — numbers and enums only.
- Every redaction action emits `log.redaction_violation` (WARNING, `privacy_violation`, L3 audit) with `{event, key, kind}` only; per-call-site dedup (first + every 100th) prevents flood.

## 7. Cross-process propagation (headers)

| Caller → Callee | Headers |
|---|---|
| voice backend / dashboard → llm-manager node | `X-Request-Id` (edge id), `X-Zivon-Session-Id` (voice only), `X-Zivon-Run-Id` (none — node calls are run-scoped from the factory) |
| factory Job → llm-manager node | `X-Request-Id`, `X-Zivon-Run-Id` |
| llm-manager node → upstream model server | none added (upstream is OpenAI-format; no header contract there) |
| browser → voice backend | `POST /api/v1/events` body (§ below); voice WS payloads carry `session_id`/`turn_id` in the control frames |
| any service → caller | `X-Request-Id` response header (always returned — the frontend shows it in error toasts for bug reports) |

Header receiving rule: accept an inbound `X-Request-Id` only from same-cluster callers (validate UUID shape; if absent or malformed, generate). `X-Zivon-*` ids are validated the same way. The node's model-mismatch guard and OpenAI-format relay behavior are unchanged (llm_manager keeps its own isolation; it gains an observer hook → `log_event` adapter, nothing more).

## 8. Closed vocabularies

- **Severity:** `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` (§5 of [`spec.md`](spec.md) for the policy).
- **ErrorClass:** `transport_error`, `validation_error`, `gate_fail`, `repair_exhausted`, `infra_error`, `quota_error`, `auth_error`, `client_error`, `privacy_violation`, `store_error` (meanings in `spec.md` §7; closed — additions are spec changes).
- **Component:** `factory`, `llm` (model-call client events inside any consumer), `llm_node`, `voice`, `translator`, `frontend`, `dashboard`, `credit`, `log`.

## 9. Schema versioning

`LOG_SCHEMA_VERSION = 1`. Additive, optional fields may land without a bump (list them in the map's notes column). Any of: removing/renaming a field, changing a type, tightening an enum, changing severity of an existing event → bump to `2`, keep the writer emitting `schema_version: 2` only after the reader (dashboard) and sweeper accept both — one release of overlap, then retire `1`. The `log_events` table is schema-agnostic (JSONB `fields`), so bumps never require a migration.

## 10. Event ingest endpoint (`POST /api/v1/events`)

Owned by the voice backend (runtime API); contract here so frontend and dashboard agents build against it:

- Body: `{"events": [ {event object per §4, client-produced subset}, ... ]}` — ≤ 32 events / 16 KB per request; `Content-Type: application/json`.
- Server-side: validate against the EVT-Fxx rows of `instrumentation-map.csv` (unknown name / out-of-enum field / oversized → `422` with per-event reasons and a `voice.events.ingest_rejected` WARNING, `client_error`, sampled 1/10); accepted events are re-emitted through `log_event(component="frontend", ...)` so they land in the same store with server `ts` (client `ts` kept in `fields.client_ts`).
- Auth: none for EVT-Fxx (pseudonymous, no PII — ADR-0019 scope is admin routes); rate-limited per IP (60 beacons/min, then drop silently — a dropped beacon must never break the page). CSP: same-origin only (spec §8, carve-out F-1).

## 11. Anti-patterns (fail review)

- Hand-building JSON log lines, `print()` from library code, writing `log_events` SQL outside the module.
- Passing learner text through `fields` "just for debugging" — that is the `privacy_violation` case, and the module will scrub it and flag the call site.
- Inventing correlation IDs where the spec says absence is honest.
- Emitting an event with no row in `instrumentation-map.csv` (map-lint is CI).
- Logging *around* a failure (swallowing then logging INFO) — failures carry `error_class`, severities per §8 of `spec.md`.

## 12. Tests that ship with the module

`testing/logging_manager/`: redaction rules (every denylist key pattern + regex kind + reference-field allow + violation-event shape); schema shape (field types, order-insensitivity of `fields`, ms-precision `ts`); context propagation (async + threaded); sink fallback switching + recovery (DSN unset / DB down / recovery), batch flush timing; `delete_subject` removes hot rows + fallback lines and writes the audit event; map-lint helper (every emitted name resolves to a CSV row). CI mirrors the repo's existing paths (`factory/`, `testing/` + this package) — the module lands with its tests in the same PR.
