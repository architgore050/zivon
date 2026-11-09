---
artifact: adr
version: "1.0"
created: 2026-11-09
status: Accepted
---

# ADR-0017: Structured stdlib logging (JSON lines) over OpenTelemetry for Zivon-wide observability

## Status

Accepted

**Date:** 2026-11-09
**Deciders:** SP3-OBS spec agent (founder directive, Wave S1); ratified by ADR review per `docs/backend/adr/` process

## Context

Day-8 (`TIMELINE.md`, Phase 3) calls for minimum-credible telemetry: structured logging, per-stage latency, error tracking, and an admin dashboard v0. Every module that lands from Wave S1 onward — `factory/`, `llm_manager/` node, the voice backend, the translator, the admin dashboard — must emit events through one shared contract (`logging_manager/`, specified in `docs/specs/observability/logging-api.md`). The open question this ADR settles: **what observability standard that contract implements.**

Three candidates:

1. **Python stdlib `logging` + one JSON line formatter** behind the `logging_manager.log_event()` API.
2. **OpenTelemetry (OTel)** — SDK + Collector Deployment, traces + metrics + logs signal, semantic conventions, vendor-neutral exporters.
3. **Hybrid** — stdlib JSON logging now, OTel traces layered later.

Forces at play:

- **Scale is small and bounded.** Computed from the repo's own parameters (`scripts` equivalent math, parameters from `TIMELINE.md` and `k8s/infra.env`): normal-day volume ≈ **2,650 events/day** (factory 430, scheduled test suite 720, voice 960, frontend 500, ops 40); demo-day judge-traffic spike ≈ **15,790 events/day**. Average rate 0.2 events/s, burst peak ≈ 4 events/s. This is 3–4 orders of magnitude below the scale where a dedicated telemetry pipeline earns its operating cost.
- **The hard cross-service latency problem is already instrumented.** Gate C (end-of-speech → first spoken audio < ~4 s) is a 3-hop path, and `llm_manager` already returns `first_token_s`, `chunks_received`, `latency`, and `finish_reason` per call (see `llm_manager/README.md`); the factory already writes per-stage `elapsed_s`, `stage_durations_s`, bracket logs with 60 s heartbeats, and `calls_ledger.jsonl` / `issues_ledger.jsonl` (0.3.1 / 2026-11-08 observability layer). What Day-8 needs is a **unified event contract and a store**, not a new tracing substrate.
- **Crunch economics.** The build window ends 10 Nov 2026. OTel integration at minimum costs: Collector Deployment + Service + ConfigMap (new manifests, CI job, kube-linter surface), SDK wiring in every consumer, a trace backend to receive/visualize (Jaeger/Tempo — another Deployment + PVC), and 1–2 engineer-days of integration plus ongoing collector maintenance — inside a phase that must also ship the dashboard, credit guard, and security pass. The learning-curve and failure-mode surface lands exactly on the demo-critical path.
- **Grafana stack is already decided** (`docs/deployment/README.md`, Decisions locked): Prometheus + Grafana via `kube-prometheus-stack` for infra metrics, Loki is P2. OTel would add a *third, parallel* telemetry path for marginal gain.
- **No external observability vendor is in scope** (secrets/egress discipline, cost, DPDP posture — children's data must not flow to a third-party SaaS).
- **DPDP / A-02 constraint** (backend-spec): transcripts are DB rows with 7-day TTL; structured logs carry **no transcripts, no raw-audio references**. A redaction guarantee must live *in the logging module* (harness, not prose — `skills/prompting-and-agent-design/` principle). That guarantee is independent of the transport decision, and stdlib logging keeps it auditable in one small file.

**[ASSUMPTION]** Event-volume parameters above (sessions/day, events/turn) are founder-plan estimates; even a 10× error leaves the conclusion unchanged (a 30k events/day peak is still trivially served by one Postgres table).

## Decision

We will implement observability on **Python stdlib `logging` emitting versioned JSON lines** through the shared `logging_manager/` module (`log_event()` + context propagation + PII denylist enforcement), stored per ADR-0018. Concretely:

- One JSON line schema (`schema_version` field), one correlation-ID discipline (`run_id` / `session_id` / `turn_id` / `request_id`), one severity policy — specified in `docs/specs/observability/spec.md` and `logging-api.md`.
- Latency telemetry is **event-based, not span-based**: each component emits explicit timing events (e.g. `voice.turn.e2e_latency`, `factory.stage.ok` with `elapsed_ms`, `node.call.finished` with `first_token_s`); percentiles are computed by the dashboard from stored events.
- OTel is **rejected for v0 and deferred, not banned**: the event schema reserves `trace_id`/`span_id` passthrough fields, so if post-challenge scale or a multi-service debugging need ever justifies OTel, existing events map onto it without a schema break.

## Consequences

### Positive

- Day-8 buildable: zero new infra; `logging_manager` is a pure-Python dependency-free module every agent can import immediately (EX1/EX2/EX4/EX5 requirement).
- The redaction/PII denylist guarantee sits in one small, unit-tested file — auditable by the review lenses without tracing expertise.
- Existing factory + llm_manager telemetry (ledgers, meta.json fields, observer hooks) maps onto the contract 1:1 — `factory/llm.py` and the node's observer hooks become `log_event` call sites, no rework of what already works.
- Dashboard queries (percentiles, error feed, run status) are plain SQL over the hot store — no trace-backend query layer.

### Negative

- No distributed trace waterfall for cross-service debugging; a multi-hop voice failure is reconstructed by joining `request_id`/`turn_id` events by hand. Accepted: the hop count is 3 and each hop already emits explicit timing events.
- If OTel is adopted later, historical events lack span structure (mitigated by the reserved `trace_id` field).

### Neutral

- Prometheus + Grafana remains the infra (CPU/RAM/pod) monitoring plane; Zivon business/telemetry events are this contract's plane. The two meet in the dashboard, which links Grafana for infra drill-down.
- `schema_version` bumping follows semver-style rules in `logging-api.md`.

### Model Choice

| Consequence | This decision |
|-------------|---------------|
| **Build, buy, or prompt** | Build (stdlib + one module). Buy (OTel vendor/backend) ruled out by cost + DPDP egress; full OTel self-host ruled out by crunch economics at 3–4 orders of magnitude below justifying scale |
| **What is now coupled to it** | The JSON line schema (`schema_version: 1`), event-name taxonomy, and correlation-ID rules in `logging-api.md`; every module's call sites |
| **Operating cost accepted** | One Postgres table + a daily cold-sync Job (ADR-0018); ~50 MB/day hot at demo-day peak |
| **Reversal cost** | Low-moderate: call sites stay (they call `log_event`); only the sink/formatter layer changes. Reserved `trace_id`/`span_id` fields avoid a schema migration |
| **What would reopen this** | Sustained > ~1M events/day, ≥3 concurrent long-lived services with opaque cross-service failures, or a post-challenge requirement for vendor-grade APM — whichever arrives first with evidence |

## Alternatives Considered

### OpenTelemetry (full SDK + Collector + trace backend)

Rejected for v0: new infra (Collector, Jaeger/Tempo, manifests, CI, kube-linter surface) and 1–2 integration days land on the demo-critical path, while measured volume (≤ 15.8k events/day) and the existing per-hop timing telemetry give traces nothing to find that events do not already carry. Deferred via the reserved trace fields, not foreclosed.

### Hybrid (stdlib now + OTel traces later in the same window)

Rejected: "later" inside a 12.5-day build never arrives before the deadline; a half-wired hybrid is the worst of both (two telemetry vocabularies, one review surface). The event schema's reserved fields achieve the same forward path for zero present cost.

### Log to files only (stdout → k8s logs), no structured store

Rejected: the dashboard v0 requires SQL-able queries (percentiles, error feed, credit counters, run status joins); scraping pod stdout back into a queryable store re-invents ADR-0018 badly. stdout JSON lines remain the **fallback sink** (PVC JSONL) for components that cannot reach Postgres — same schema, daily sync into the hot store.

## References

- `docs/specs/observability/spec.md` (log levels, redaction, correlation rules)
- `docs/specs/observability/logging-api.md` (the exact contract)
- ADR-0018 (hot log store + lifecycle), ADR-0019 (dashboard admin auth)
- ADR-0004 (cold provider), ADR-0006 (sync mechanism) — cold-tier interface only
- ADR-0007 / ADR-0011 (identity model, pseudonymous IDs) — correlation-ID privacy classes
- ADR-0015 (credit counters) — `credit.*` event family
- `llm_manager/README.md` (observer hooks, per-call telemetry fields)
- `docs/deployment/README.md` (Prometheus + Grafana decision, Loki P2)
- `TIMELINE.md` Day-8 (minimum-credible telemetry + admin dashboard v0)
