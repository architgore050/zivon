# logging_manager — the exact contract

Sources: `docs/specs/observability/logging-api.md`, `spec.md`, `logging_manager/` at `main`
@ `57147bb`, and `tmp/agent-handshake/LOGGING-EVALS-CONTRACT.md` Part A. Verified 2026-11-14.
If this file and the spec disagree, the spec wins; record the drift in the PR.

## 1. Public surface (frozen)

```python
from logging_manager import (
    log_event,  # the only emission point
    bind_context,  # set correlation ids at an edge
    context_scope,  # scoped, async-safe override
    current_context,  # read-only snapshot (tests/debug)
    delete_subject,  # DPDP erasure for one pseudonymous session
    LOG_SCHEMA_VERSION,  # 1
    Severity,  # DEBUG | INFO | WARNING | ERROR | CRITICAL
    ErrorClass,  # closed failure taxonomy
)
```

Do not import private modules from consumer code. Instrumentation owners (the factory
adapter, the llm-manager node, the dashboard) may import `logging_manager.context` helpers
(`correlation_headers`, `new_request_id`, `bind_from_headers`); that is not part of the
consumer surface.

`__all__` is pinned by `testing/observability/test_events.py::ContractSurfaceTests`; adding a
public symbol is a contract change, not a convenience.

## 2. `log_event()` signature

```python
log_event(
    event: str,
    fields: dict[str, Any] | None = None,
    *,
    severity: Severity | None = None,   # default: derived from the map
    error_class: ErrorClass | None = None,
    latency_ms: int | None = None,
    run_id: str | None = None,          # omitted -> context
    session_id: str | None = None,      # omitted -> context
    turn_id: str | None = None,         # omitted -> context
    request_id: str | None = None,      # omitted -> context
    stage: str | None = None,
) -> None
```

Implementation facts that matter:

- It never raises on the delivery path; sink failures degrade loudly to the fallback. The only
  exceptions are programmer errors **in dev mode** (`ZIVON_LOG_LEVEL=DEBUG`): unknown event
  name, unknown `error_class`, negative `latency_ms`.
- Severity is looked up from the map unless you pass `severity=`. Do not override because the
  message "feels" worse; the map declares it once.
- Component is the map row's `component`, else inferred from the emitting module, else `log`.
  An undeclared event is delivered anyway and emits `log.event_unknown` (WARNING); CI
  map-lint makes that red.
- `fields` is redacted before serialization. Supplying a denylisted key or a secret-shaped
  value produces `log.redaction_violation` and a review-blocking finding.
- `bind_context(run_id=...)` is the normal way to supply correlation. Passing an ID explicitly
  is for the edge that owns it (and for tests) — not for threading it through the call stack.

## 3. Event naming

`<component>.<subject>.<action>` — dot-namespaced, lower snake case. The name is the contract;
one row per name in `docs/specs/observability/instrumentation-map.csv`.

| Component (closed enum) | Used by |
|---|---|
| `factory` | pipeline stages, orchestration, perf, publish |
| `llm` | model-call client events emitted by `llm_manager` itself (`events._infer_component`); today the factory's calls are declared as `factory.call.*`, so no `llm.*` row exists (2026-11-14) |
| `llm_node` | the isolated llm-manager service (`node.*` events) |
| `voice` | voice backend |
| `translator` | translation stages in `factory/translate.py` (`translator.translate.ok` / `.fail`) |
| `frontend` | browser events validated/re-emitted by the ingest endpoint |
| `dashboard` | admin dashboard |
| `credit` | credit guard / ledger |
| `log` | `logging_manager`'s own events |

The map currently declares one row outside this enum (`privacy.subject_deleted`, component
`privacy`); per-event the map wins, and the enum is the fallback vocabulary. A new component
is a `logging-api.md` §8 spec change, never a call-site string.

`stage` is a real factory stage id only: `00-ingest`, `01-locate`, `02-generate`, `03-check`,
`04-repair`, `05-interactive`, `06-render`, `07-perf`, `08-fixloop`, `09-review`,
`10-reviewfix`, `10a-translate`, `10b-transcheck`, `10c-transrepair`, `10d-transrender`,
`11-link`, `12-narration`. A new stage must be in `STAGE_ORDER` **and** the map.

## 4. Severity and error class

| Severity | Meaning | Example |
|---|---|---|
| `DEBUG` | developer-only; filtered at emit unless `ZIVON_LOG_LEVEL=DEBUG` | context dumps |
| `INFO` | normal lifecycle progress | `factory.stage.ok` |
| `WARNING` | recovered degradation, or a security/privacy audit hit | `log.store_fallback`, `log.redaction_violation` |
| `ERROR` | a gate/stage/request failed; a catcher may still recover | `factory.stage.fail` |
| `CRITICAL` | system-level: store down and fallback failed, auth lockout, guard refusal | `credit.guard_blocked` |

Failure-shaped events carry `error_class` from this closed enum:

`transport_error`, `validation_error`, `gate_fail`, `repair_exhausted`, `infra_error`,
`quota_error`, `auth_error`, `client_error`, `privacy_violation`, `store_error`.

Adding a class is a spec change (`spec.md` §7). Never log a failure at `INFO` with no class.

## 5. Correlation IDs

| ID | Born at | Joins |
|---|---|---|
| `run_id` | `factory/stages.py::run_pipeline` (`make_run_id`, `--run-id`, or `ZIVON_RUN_ID`) | every factory event, model call, publish |
| `session_id` | voice session start (UUID4) | every voice event, frontend `mic_press` |
| `turn_id` | voice turn handler (UUID4) | every per-turn event |
| `request_id` | every HTTP/WS entry (UUID4); `context_scope` per outbound model call | `factory.call.*`, `node.call.*`, response header |
| `client_session_id` | browser session (UUID4, stored client-side) | frontend events only |

Discipline:

- Exactly one `bind_context` per edge. Never pass IDs through function arguments inside a
  process.
- Cross-process IDs ride headers: `X-Request-Id`, `X-Zivon-Run-Id`, `X-Zivon-Session-Id`.
  Validate shape; generate if absent or malformed.
- `context_scope(request_id=new_request_id())` around an outbound model call is the existing
  pattern (`factory/llm.py`); reuse it.
- Absence is honest. Do not invent a `session_id` for a build-time pipeline event.

## 6. Redaction and privacy

Applied mechanically inside `log_event`, before any sink.

**Key denylist** (case-insensitive; exact keys plus prefixes marked `*`):

`transcript*`, `text`, `content`, `prompt`, `messages`, `response`, `completion`, `answer`,
`page_html`, `code`, `patch`, `audio*`, `wav`, `pcm`, `speech*`, `utterance*`, `cookie`,
`token`, `secret`, `key`, `authorization`.

A denylisted key becomes `[REDACTED:key-denylist]`.

**Sanctioned reference fields** (checked before the denylist):
`transcript_row_id`, `artifact_path`, `block_id`, `topic`, `chapter`.

**Value scrubs** (replace with `[REDACTED:<kind>]`): emails, Indian phone numbers,
Aadhaar-shaped numbers with context words, `sk-…` / `ZIVON_…` keys, `Bearer …`, JWTs, base64
blobs longer than 512 characters.

**Shape guard:** a value must be a scalar or a flat list of scalars. A dict, tuple, set, or
nested list cannot be redacted reliably, so the whole value becomes `[REDACTED:shape]`.

**Allowed learner-shaped aggregates:** `duration_ms`, `char_count`, `language_mix` (enum),
`turn_count`, `partial_count`. Numbers and enums, never the child's words.

Every redaction action emits `log.redaction_violation` (WARNING, `privacy_violation`) with
`{event_ref, key, kind}` only, deduplicated per call site (first + every 100th). A nonempty
violation stream on the dashboard is a call-site bug, not noise. Recorded drift: the map row
and `sink.py` say `event_ref`; the spec prose (`logging-api.md` §6, `spec.md` §4.4) still says
`event`. The map row is authoritative here; do not rename the field at a call site.

## 7. Sinks

```
log_event()
  ├─ stdout                                  always (one JSON line; pod logs stay greppable)
  ├─ Postgres `log_events`                   when ZIVON_LOG_DSN is set; batched 1 s / 64 events
  └─ runs/logs/YYYYMMDD-<component>.jsonl    when the DSN is unset or the DB is down
```

- A failed DB batch retries once, then falls back for the batch and emits `log.store_fallback`
  (WARNING, `store_error`). Recovery emits `log.store_recovered`.
- `ZIVON_RUNS_DIR` changes the JSONL base directory (useful for a key-free local demo so the
  repo's `runs/` stays clean).
- Never write or rotate the JSONL file yourself; it is the daily log-sync source.
- `ZIVON_LOG_LEVEL=DEBUG` is dev-only and must never appear in cluster manifests.

## 8. Frontend path

The browser does not call `log_event`. It emits `EVT-F01..F12` through `window.ZivonEvents`
(`frontend/assets/zivon.js`) to `POST /api/v1/events`; the backend validates the catalogue,
persists the telemetry row, and the ingest contract says accepted events are re-emitted through
`log_event` with `component=frontend` and a server `ts` (`logging-api.md` §10).

Verified implementation note (2026-11-14): `backend/routes/student.py::_ingest_events_impl`
validates and persists to `telemetry_event`; it emits `voice.events.ingest_rejected` on
rejection. Treat the per-event `log_event` re-emit as the documented target, and verify the
current path before relying on `log_events` for a brand-new frontend event.

Frontend rules:

- Reuse an existing `EVT-Fxx` if it can express the interaction. A new frontend event needs a
  map row with `component=frontend`, `client_session_id`, and an `EVT-Fxx` id.
- No free text, no stack traces, no page content; `error_kind` is an enum.
- The page must keep working if the beacon fails: buffer or drop, never break the turn.

## 9. Deletion (DPDP)

`delete_subject(session_id)` removes every hot-store row for that pseudonymous session and
rewrites the fallback JSONL files, then writes one L3 `privacy.subject_deleted` event with IDs
only. It is the 24-hour guardian-deletion path; transcripts live in their own DB rows with a
7-day TTL, and raw audio is never referenced from logs. Do not build a second deletion path.

## 10. Verified gotchas

- `events.component_for` prefers the map row over the emitting module. Passing a component is
  not an API option; fix the row or the module.
- `logging_manager` degrades to "no map" when the CSV is not on disk (a bare import outside an
  image): validation is disabled and every event is delivered. Tests that need map behaviour
  must run from the repo root or set `ZIVON_INSTRUMENTATION_MAP`.
- The map row count is pinned by a test (`73` on 2026-11-14). Adding a row without updating it
  turns CI red.
- `privacy.subject_deleted` is mapped with a component outside the closed enum; that is a
  known precedent, not a licence for new components.
- Eval telemetry (`evals/telemetry.py`) currently lands with component `log` and emits
  `log.event_unknown` because the five `factory.eval.*` names have no map rows. This is the
  open P-GAP-14 fix; see `eval-store-and-dashboard.md`.

## 11. Anti-patterns (fail review)

- `print()` / `logging.getLogger()` / hand-built JSON lines / SQL into `log_events`.
- An event name with no map row, or a row whose emitter does not exist.
- Learner text, prompts, answers, page HTML, audio bytes, or secrets in `fields`.
- Inventing `run_id` / `session_id` / `turn_id` where no edge exists.
- Logging around a failure (swallow → `INFO`); failures carry `ErrorClass`.
- Overriding `severity=` to make a map row "feel" right.
- A new component name without a `logging-api.md` §8 spec change.
- A test that asserts a string was passed rather than that the event resolves and serializes.
