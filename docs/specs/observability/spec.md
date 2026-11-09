# Zivon Observability Spec — logging_manager + admin dashboard v0

**Agent:** SP3-OBS (Wave S1, docs-only spec) · **Date:** 2026-11-09 · **Status:** build-ready spec, patches target `feature/backend-db-storage-spec`

This folder is the build-ready specification for **industry-standard logging/observability across the whole Zivon system** and the **admin dashboard v0**. Its center of gravity is `logging_manager/` — the module every other agent's code must use for emitting events. This document is the system spec (what and why, decisions with numbers); the exact public API other agents code against is [`logging-api.md`](logging-api.md), the per-component event inventory is [`instrumentation-map.csv`](instrumentation-map.csv), and the dashboard is specified in [`dashboard-spec.md`](dashboard-spec.md). Open items are tracked in [`open-questions.md`](open-questions.md) with stable IDs (OQ-n).

## 0. How to consume this spec (EX1/EX2/EX4/EX5 agents start here)

1. **Emitting events:** import `logging_manager`, call `log_event(...)` exactly as specified in [`logging-api.md`](logging-api.md). Never print telemetry from library code (`llm_manager` isolation rules apply to `logging_manager` consumers too: prints are for the operator console, events are for the store). Never hand-roll JSON log lines, never write to the `log_events` table directly, never call the inference server from logging code.
2. **Correlation IDs:** create/propagate per §3 below. If your component has no ID in its hands, pass `run_id=None`-style absent fields — absence is honest, fabricating IDs is not.
3. **What you may never put in an event:** transcripts, learner free text, raw audio or references to raw audio, prompts, model responses, page content (§4 redaction — enforced in the module, violations are loud).
4. **Your rows in the map:** [`instrumentation-map.csv`](instrumentation-map.csv) lists every event your component emits, with severity, fields, and privacy class. Add rows there (same PR as your code) when you add events.
5. **Decisions already made for you:** stdlib JSON logging over OpenTelemetry (ADR-0017), Postgres hot store with PVC JSONL fallback (ADR-0018), single-admin dashboard auth (ADR-0019). Challenge via a manifest/challenge note, never by silently overriding.

## 1. Scope and non-goals

**In scope (this spec):** the `logging_manager/` module contract; the JSON line schema and its versioning; correlation-ID rules across factory, llm-manager node, voice backend, translator, and frontend; log-level policy; PII/child-data redaction enforced in code; log storage, tiering, retention, sync and deletion; the instrumentation map (every component's events, latency timings, error taxonomy); the admin dashboard v0 (views, auth, k8s shape, trigger buttons); the minimum alerting set; the frontend event contract.

**Non-goals (this window):** distributed tracing (deferred, ADR-0017), Loki log aggregation (P2, per `docs/deployment/README.md`), per-user admin identity (post-challenge, ADR-0019), email/Telegram paging (P1 — the v0 channel is the dashboard banner + alert events), infra metrics (Prometheus/Grafana owns CPU/RAM/pod telemetry — locked decision; this spec owns product-level events), full analytics (P2).

The system has two telemetry planes by deliberate design. The **infra plane** (Prometheus + Grafana, `kube-prometheus-stack`) watches pods, nodes, and load, with Grafana's own auth as its gate. The **product plane** (this spec: `log_events` store + dashboard v0) watches Zivon-shaped things: factory runs, voice turns, credits, errors, publishes. They meet in the dashboard, which links out to Grafana for infra drill-down; neither re-implements the other.

## 2. The logging_manager module (overview)

`logging_manager/` is a new top-level Python package, sibling to `llm_manager/`, with the same isolation discipline: it imports nothing from `factory/`, `llm_manager/`, or the voice backend; it does no model calls and no hand-rolled HTTP; it prints nothing. Public surface (exact signatures in [`logging-api.md`](logging-api.md)):

- `log_event(event, fields, *, severity=..., run_id=None, session_id=None, turn_id=None, request_id=None, stage=None, latency_ms=None, error_class=None)` — the single emission point for every component.
- Context helpers: `bind_context(...)`, `context_scope(...)`, `current_context()` — Python `contextvars`-based, so async voice handlers and threaded factory stages each carry their correlation IDs without threading them through every call.
- Sinks: Postgres `log_events` (day-partitioned, ADR-0018) when `ZIVON_LOG_DSN` is set; otherwise JSONL files under the PVC (`runs/logs/YYYYMMDD-<component>.jsonl`), byte-identical schema, with a loud `log.store_fallback` event on degradation. stdout is always written too (one JSON line per event) — `kubectl logs` stays human-useful and the factory's existing label-resolved log follower keeps working.
- Redaction: `redact.py` applies the §4 denylist/regexes to every event before any sink; violations become `log.redaction_violation` events carrying only the offending key name and event name, never the payload.
- Deletion: `delete_subject(session_id)` implements the guardian-deletion path (ADR-0018 §4).

Module-level tests are part of the deliverable when the module lands (`testing/logging_manager/`): redaction guarantees, schema shape, fallback switching, context propagation. The module ships with `LOG_SCHEMA_VERSION = 1` and `requirements.txt` limited to the DB driver — the JSON path needs nothing outside the stdlib.

## 3. Correlation IDs — who creates them, how they propagate

Every event carries zero or more correlation IDs. The four IDs and their owners:

| ID | Created by | Format | Scope | Propagates to |
|---|---|---|---|---|
| `run_id` | `factory/stages.py::make_run_id` (exists today: `<slugified-chapter>[-c<class>]`, deterministic per chapter+class; `--run-id` overrides for parallel attempts) | slug | one factory run, all 12 stages + catcher rounds | every `factory.*` event; model-call events via `factory/llm.py`; `llm_node.*` events via the `X-Zivon-Run-Id` request header; dashboard run views |
| `session_id` | voice backend, at voice-session start (UUID4); pseudonymous per ADR-0011/ADR-0007 — no name, no device id, no IP in the ID | UUID4 | one voice conversation | every `voice.*` + `credit.*` event; dashboard voice views; translator calls via `X-Zivon-Session-Id` |
| `turn_id` | voice backend, per user-turn (UUID4) | UUID4 | one STT→LLM→TTS turn | `voice.turn.*` events; page-context anchoring logs; `request_id` of the turn's HTTP legs |
| `request_id` | the receiving service at every HTTP/WS edge (voice backend, dashboard, llm-manager node): accept an inbound `X-Request-Id` from a same-cluster caller, else generate UUID4; always return it in the `X-Request-Id` response header | UUID4 | one request/response exchange | service logs; upstream calls (node forwards it); frontend-visible for bug reports |

Propagation mechanics: within a process, IDs live in `logging_manager`'s context vars — `bind_context()` at the edge (pipeline start, session start, request start), helpers read them so component code never passes IDs explicitly unless crossing a process boundary. Across processes, IDs ride HTTP headers: factory → node carries `X-Zivon-Run-Id` + `X-Request-Id`; the node echoes both in its own events; the frontend sends `client_session_id` + `request_id` inside event payloads to `POST /api/v1/events`. Across language/transport (browser): the frontend generates `client_session_id` (sessionStorage UUID) and per-event `request_id`.

The factory Job also passes `run_id` as an env var (`ZIVON_RUN_ID`) into the Job pod so pod-level scripts (`scripts/logs-factory-run.sh`) and the dashboard's run-status view can join pod logs to events without name guessing.

Frontend client events additionally carry `client_session_id` (pseudonymous, sessionStorage-lifetime) and, when the mic tutor is active on the page, the current `session_id`/`turn_id` so engagement rows join to voice rows. See §8 for the privacy class of each.

## 4. Redaction and child-data rules (guarantees in the harness, not in prose)

A-02 (backend spec): transcripts are DB rows with a 7-day TTL; **structured logs carry no transcripts**. ADR-0011/ADR-0007: learner identity is pseudonymous. This spec turns those into mechanical guarantees inside `logging_manager/redact.py`:

1. **Key denylist (hard-fail):** any field whose name matches the denylist is replaced by `[REDACTED:key-denylist]` before serialization: `transcript*`, `text`, `content`, `prompt`, `messages`, `response`, `completion`, `answer`, `page_html`, `code`, `patch`, `audio*`, `wav`, `pcm`, `speech*`, `utterance*`, `cookie`, `token`, `secret`, `key`, `authorization`. To log a reference instead of content, use the sanctioned reference fields: `transcript_row_id` (the A-02 DB row), `artifact_path` (runs/ evidence paths — build-time, no child data), `block_id`, `topic`, `chapter`.
2. **Value regexes (scrub in place):** email addresses, Indian phone numbers (+91 / 10-digit), Aadhaar-shaped 12-digit numbers (with context words), `sk-`/`ZIVON_`-prefixed API keys, `Bearer …` headers, JWT-shaped strings, base64 blobs > 512 chars (audio smuggle guard) → `[REDACTED:<kind>]`.
3. **Learner-shaped aggregates are allowed:** `duration_ms`, `char_count`, `language_mix` (e.g. `hi-en`), `turn_count`, `partial_count` — numbers and enums, never words the child said.
4. **Violation event:** a redaction action emits `log.redaction_violation` (WARNING, L3 audit class) with fields `{event, key, kind}` — enough to fix the call site, never the payload. Repeated violations from one call site are deduplicated per process (first + every 100th logged) so a chatty bug cannot flood the store.
5. **Tests are the guarantee:** `testing/logging_manager/test_redaction.py` pins every rule above (denylist hit, regex hit, reference-field allow, violation-event shape); the module's suite runs in CI with the repo's tests. A PR that weakens these tests fails review by the tests lens — same policy as the repo's other harness guarantees.

Note on an apparent conflict: `AGENTS.md` says "log enough information to debug conversations (transcripts, latency, errors)". A-02 supersedes the transcript word here: conversation debugging happens by joining `session_id`/`turn_id` events to the transcript DB rows (7-day TTL) — logs carry the IDs and the timings, never the words. This is recorded in `open-questions.md` (OQ-6) so the AGENTS.md line can be amended by its owner.

## 5. Log levels policy

| Level | Meaning | Examples | Dashboard treatment |
|---|---|---|---|
| `DEBUG` | Developer-only detail; requires `ZIVON_LOG_LEVEL=DEBUG` (default `INFO`), never set in cluster manifests | context dumps at edges | not stored (filtered at emit; costs nothing) |
| `INFO` | Normal lifecycle progress | `factory.stage.ok`, `voice.turn.e2e_latency`, `dashboard.action_triggered` | feeds views (runs, percentiles, publish) |
| `WARNING` | Recovered degradation, honest but survived | `log.store_fallback`, `node.call.transport_retry`, `log.redaction_violation` | error feed (yellow) |
| `ERROR` | A gate/stage/request failed; a catcher may still recover | `factory.stage.fail`, `voice.turn.error`, `credit.guard_blocked` | error feed (red), SLO inputs |
| `CRITICAL` | System-level: store unreachable AND fallback failed, auth lockout, alert condition | `alert.credit_tranche_exhausted`, `dashboard.auth_lockout` | banner + alert §9 |

Rules: severity is a property of the event name (declared once in [`instrumentation-map.csv`](instrumentation-map.csv) per event; `log_event` derives it from the map, explicit `severity=` overrides only for the ERROR/CRITICAL boundary between "caught" and "fatal"). No `print()` from library code — the factory's operator-console prints remain console-only and are not events. `ZIVON_LOG_LEVEL` joins `k8s/infra.env` as a line-edit when the module lands (config via env, never manifests).

## 6. Storage, tiering, retention, sync, deletion (summary)

Full decision in ADR-0018. Summary with the numbers this spec commits to:

- **Hot:** `log_events` in the backend's Postgres (SSD), `PARTITION BY RANGE (ts)` per day, indexes per ADR-0018's DDL. Demo-day peak ≈ 50 MB/day; 7-day hot window ≈ 0.35 GB — SSD-trivial.
- **Fallback:** PVC JSONL (`runs/logs/`), same schema, loud `log.store_fallback` on switch; the daily sync ingests it.
- **Cold:** daily `log-sync` CronJob exports the previous UTC day's partition(s) + fallback JSONL as NDJSON to the cold provider (ADR-0004) via ADR-0006's batch mechanism; row-count + checksum verified **before** the sweeper may drop the hot partition (retain-until-synced). Trigger: daily 03:30 IST + 200 MB file cap. **[ASSUMPTION]** trigger cadence/size align with `sync-policy.csv`; reconcile at merge (OQ-2).
- **Retention per class:** L1 system/diagnostic 7 d hot / 90 d cold; L2 usage/telemetry 7 d / 90 d; L3 security/audit 30 d / 365 d; credit counters 7 d / 365 d. Deletion = partition drop by the sweeper.
- **Deletion paths:** (a) TTL above; (b) guardian deletion — `logging_manager.delete_subject(session_id)` removes every row for the subject's pseudonymous session IDs (hot + fallback file + cold export manifests) within 24 h of the guardian request, writing one L3 `privacy.subject_deleted` event (IDs only). Transcripts live only in A-02 rows with their own 7-day TTL; raw audio is never referenced from logs by §4, so no other deletion path exists by construction.

## 7. Error taxonomy

Every failure-shaped event carries `error_class` from this fixed enum (column in the map; the dashboard's error feed groups by it):

| error_class | Meaning | Default severity | Example events |
|---|---|---|---|
| `transport_error` | Network/transport to an upstream (model server, Gnani APIs) failed or exhausted retries | ERROR | `node.call.transport_exhausted`, `voice.stt.upstream_error` |
| `validation_error` | Model output rejected by schema/contract rounds | WARNING (retryable) / ERROR (exhausted) | `factory.call.rejected` |
| `gate_fail` | A review/perf gate produced a failing verdict | WARNING (catcher engaged) | `factory.stage.fail` at 03-check/09-review |
| `repair_exhausted` | A catcher loop hit plateau or cap without passing | ERROR | `factory.repair.exhausted` |
| `infra_error` | Cluster/storage/process failures (PVC, DNS, node reboot, OOM) | ERROR/CRITICAL | `factory.stage.fail` at 00-ingest on DNS |
| `quota_error` | Credit/quota guard fired | CRITICAL | `credit.guard_blocked`, `alert.credit_tranche_exhausted` |
| `auth_error` | Admin auth failure/lockout | WARNING / CRITICAL (lockout) | `dashboard.auth_failure` |
| `client_error` | Malformed/mis-sent frontend events | WARNING (sampled) | `voice.events.ingest_rejected` |
| `privacy_violation` | Redaction denylist hit — always investigated | WARNING (L3 audit) | `log.redaction_violation` |
| `store_error` | Hot store write failed | ERROR (+ fallback) | `log.store_fallback` |

The taxonomy is closed: adding a class is a spec change (row here + map column note), not a call-site string.

## 8. Instrumentation map and the frontend event contract

The complete per-component inventory (events, severities, fields, latency measurements, privacy classes, emitter locations) is [`instrumentation-map.csv`](instrumentation-map.csv) — one row per (component, event), covering factory stages 00-ingest…11-link, the llm-manager node and client, the voice backend per-hop path, the translator, frontend client events, credit counters, dashboard audit events, and `logging_manager`'s own events. Components add rows in the same PR as their code.

**Frontend event contract (EVT-Fxx):** the browser-originated events are named `frontend.<action>` with stable catalogue IDs `EVT-F01`…`EVT-F12` in the map. Exact names/properties (all fields pseudonymous or content-id references; privacy class P2 per data-classification conventions — no free text, no transcripts, no audio):

| EVT ID | Event | Required properties | Transport |
|---|---|---|---|
| EVT-F01 | `frontend.page_view` | `topic`, `chapter`, `class_level`, `client_session_id`, `ts` | sendBeacon |
| EVT-F02 | `frontend.section_view` | `topic`, `section_id`, dwell bucket enum (`<5s`,`5-30s`,`>30s`) | sendBeacon |
| EVT-F03 | `frontend.sim_open` | `topic`, `block_id` | sendBeacon |
| EVT-F04 | `frontend.sim_interact` | `topic`, `block_id`, `variable`, interaction count (int) | sendBeacon (batched 1/5s) |
| EVT-F05 | `frontend.check_answered` | `topic`, `block_id`, `correct` (bool), attempts (int) | sendBeacon |
| EVT-F06 | `frontend.mic_press` | `topic`, `session_id?`, `client_session_id` | sendBeacon |
| EVT-F07 | `frontend.voice_turn_done` | `topic`, `session_id`, `turn_id`, `e2e_ms` bucket | sendBeacon |
| EVT-F08 | `frontend.error` | `topic`, `error_kind` enum (`js`,`mic_permission`,`network`,`voice`), no stack contents | fetch keepalive |
| EVT-F09 | `frontend.language_bar_use` | `topic`, `lang_selected` enum | sendBeacon |
| EVT-F10 | `frontend.session_end` | `client_session_id`, duration bucket, turn count | sendBeacon (pagehide) |
| EVT-F11 | `frontend.publish_view` | `topic`, source (`pvc`/`snapshot`) — publish-status view aid | sendBeacon |
| EVT-F12 | `frontend.heartbeat` | `client_session_id` — session liveness, 60 s | sendBeacon |

Transport: `navigator.sendBeacon()` to `POST /api/v1/events` (batched `{events: [...]}`, ≤ 32 events or 16 KB per beacon; the voice backend ingests and re-emits through `logging_manager` with component=`frontend`), fallback `fetch(..., {keepalive: true})`; events do **not** ride the voice WebSocket (that channel is audio/control only). Ingest validation is strict: unknown event names and out-of-enum fields are rejected (`voice.events.ingest_rejected`, `client_error`, sampled 1/10) so the catalogue stays exact.

**CSP carve-out (coordinated change F-1):** generated lesson pages ship `connect-src 'none'` (locked posture, `docs/deployment/README.md`). The telemetry beacon targets the **same origin** (`/api/v1/events`), which requires the generated-page CSP template to become `connect-src 'self'` — a one-line change in the factory's CSP emission plus `factory/lint.py`'s external-URL sweep stays as-is (it blocks absolute/protocol-relative refs; a relative same-origin beacon is unaffected). Until that carve-out ships (factory agent, integration note in the manifest), the shell buffers EVT-Fxx in `sessionStorage` (≤ 50 events, FIFO) and drains on the next page that can send; with the carve-out, buffering becomes unnecessary. The strict-CSP intent (no external egress) is unchanged — this is same-origin only, and the change is flagged for founder sign-off (OQ-5).

## 9. Alerting minimum (what pages the founder)

The v0 alerting set is deliberately small: **the channel is the dashboard banner + `alert.*` CRITICAL events**; email/Telegram is P1 (post-freeze). Alerts fire on SLO breaches, deduplicate (one open alert per key until the condition clears), and always carry the query that proved them:

| Alert | Condition (SLO) | Source events | Severity |
|---|---|---|---|
| `alert.pipeline_run_failed` | A factory run reaches terminal FAILED (catchers exhausted, transport dead, or `backoffLimit: 0` trip) | `factory.run.failed` | CRITICAL |
| `alert.voice_p95_breach` | Trailing-24 h voice `turn.e2e_latency` p95 > **4000 ms** (Gate C budget) | `voice.turn.e2e_latency` | CRITICAL |
| `alert.credit_tranche_exhausted` | Burn budget exhausted: cumulative credit use crosses **3,000** of 5,000 (the 40% = 2,000 demo reserve must stay intact per `TIMELINE.md`) | `credit.counter_update` (ADR-0015) | CRITICAL |

Gate C hop budget (measured per hop, budget-checked by the dashboard): end-of-speech → STT final ≤ 600 ms; → LLM first token ≤ 900 ms; → TTS first audio ≤ 1,800 ms; transport/hop overhead ≤ 300 ms; total 3,600 ms + 400 ms headroom = the 4,000 ms Gate C bar. A p95 breach names the slowest hop in the alert fields (`slowest_hop`), so the fix (shorter replies vs pre-warm vs streaming tighter) is evidence-backed — exactly the Gate C "if it fails" ladder in `TIMELINE.md`.

## 10. Dashboard v0 and admin auth (summary)

Full specification in [`dashboard-spec.md`](dashboard-spec.md); decisions in ADR-0019 (auth) and ADR-0018 (data sources). Summary: a small FastAPI app + static UI (no JS framework), k8s manifests **23** (Deployment) and **24** (ClusterIP Service) — the numbers reserved in the mission brief; admin-only via the single-secret flow of ADR-0019; views = factory runs status (resume/fail/repair-catcher), test-suite results, voice latency percentiles, credit usage vs tranche/cap (normal vs demo profile), error feed, publish status; the two trigger scripts' exact semantics exposed as the two admin buttons. The dashboard reads core-backend's admin surface contract rather than inventing a parallel one — the reconciliation item is OQ-3 because §6.3 was not present on this base.

## 11. Assumptions index

All `[ASSUMPTION]` tags carried in the ADRs and this spec, collected: session/event-volume parameters (§2 of ADR-0017 — founder-plan estimates, conclusion insensitive at 10×); cold provider = S3-compatible via ADR-0004/0006 with daily+size sync triggers (ADR-0018 — reconcile with `sync-policy.csv`, OQ-2); two shared-admin principals (ADR-0019); DB driver choice follows the backend agent (ADR-0018 §5); §6.3 admin-surface reconciliation (OQ-3); CSP carve-out pending founder sign-off (OQ-5). Items that are **not** assumptions: every number in §6/§9 (computed from repo parameters — `scripts/sp3-obs` scale math), the retention table (this spec's decision), the EVT-Fxx catalogue (this spec's contract).
