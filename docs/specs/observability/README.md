# Observability Specs (SP3-OBS)

Build-ready specification for Zivon-wide logging/observability and the admin dashboard v0 — the Wave-S1 docs deliverable that becomes the `logging_manager/` module. Every module that emits telemetry codes against [`logging-api.md`](logging-api.md); decisions live in ADRs 0017–0019 under `docs/backend/adr/`.

## Layout

| Doc | Contents |
|---|---|
| [`spec.md`](spec.md) | The system spec: module overview, correlation IDs, redaction/child-data rules, log levels, storage & lifecycle, error taxonomy, frontend event contract (EVT-Fxx), alerting minimum, assumptions index |
| [`logging-api.md`](logging-api.md) | **The contract other agents code against** — exact `log_event` signatures, context helpers, the versioned JSON line schema with example lines, sink behavior, redaction rules, error taxonomy values |
| [`instrumentation-map.csv`](instrumentation-map.csv) | One row per (component, event): severity, correlation IDs, required fields, latency measurement, error class, privacy class, emitter location |
| [`dashboard-spec.md`](dashboard-spec.md) | Admin dashboard v0: views, endpoints, auth (ADR-0026), k8s manifests 23–24, the two trigger buttons, data sources |
| [`open-questions.md`](open-questions.md) | Open items with stable IDs (OQ-n), owners, and what closes them |

## Related decisions (docs/backend/adr/)

- **ADR-0024** — stdlib JSON logging over OpenTelemetry (OTel deferred via reserved trace fields)
- **ADR-0025** — hot log store: day-partitioned Postgres `log_events`; PVC JSONL fallback; daily cold sync; retention per class
- **ADR-0026** — minimal admin auth: single-admin bearer Secret, HttpOnly session, fail-closed

## Rules for consumers (short version)

Import `logging_manager`, call `log_event(...)`, propagate correlation IDs per `spec.md` §3, never log transcripts/audio/learner free text (§4 — enforced in the module), never write the `log_events` table or hand-roll log JSON yourself, and add your `instrumentation-map.csv` rows in the same PR as your events. Challenges to ADR decisions go in your agent manifest, not silent overrides.

## Sanity checklist (docs-agent §4 tests)

The docs sanity pass for this folder (results recorded in the SP3-OBS manifest, re-runnable by the merge agent):

1. Every CSV in this folder parses as RFC-4180 with a consistent column count.
2. Every repo path referenced by any doc here exists (or is declared as a contract for a parallel agent in `open-questions.md`).
3. Every cross-reference resolves: `EVT-Fxx` rows ↔ `spec.md` §8 ↔ `instrumentation-map.csv`; `OQ-n` ↔ `open-questions.md`; ADR-0024/0018/0019 ↔ `docs/backend/adr/`.
