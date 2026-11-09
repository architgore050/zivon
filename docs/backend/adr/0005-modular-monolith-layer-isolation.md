# ADR-0005: Topology = modular monolith voice backend; Core content path fully independent
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session (layer independence is an inherited product rule)
- Driving NFRs / requirements: NFR-12 (Core availability independent of voice stack), NFR-13, maintainability (ref 01 §2), AGENTS.md module-separation list

## Context
AGENTS.md prescribes separated concerns (audio/session, Gnani clients, prompting, tutor logic,
anchoring, logging). The topology question: how many deployable services now, at 10-concurrent
demo scale, with a 3-day window to build the backend.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **One FastAPI Deployment (voice backend) + existing nginx Deployment (Core) + Postgres + CronJobs** | clean module seams inside one process (backend-spec §4.3); one image/CI job; failure domain matches the failure-mode table; Core survives every voice outage by construction (separate Deployment + PVC) | monolith CPU ceiling (headroom measured at 2× envelope) | minimal | — |
| Microservice split (audio-svc / llm-svc / tts-svc) | independent scaling | network hops inside the Gate-C budget; 3× images, 3× CI, service auth; nothing to scale independently at 10 concurrent | high | risks NFR-01; violates "modular monolith before any service split" (ref 01 §5) |
| Everything inside nginx (Lua) | fewer services | absurd for Python/Gnani SDKs | — | maintainability |

## Decision
Modular monolith `voice/` package → one Deployment + Service; GPU host is an external dependency
(not a cluster service in P0); sync/retention are CronJobs/Deployments with their own service
accounts (ref 05 §5). Core = existing nginx Deployment over `zivon-frontend` PVC — untouched.

## Consequences
Easier: single deploy/rollback path (NFR-27), single trace context, simple K8s story consistent
with `docs/deployment/`. Harder: module discipline must be enforced in code review (voice modules
must not import into content-serving paths — they physically can't: different Deployment).
Monitor: pod CPU p99, event-loop stall detector.

## Revisit trigger (measurable)
Pod CPU p99 > 80 % sustained at ≤ 10 concurrent, or Gate-C histograms show queueing (not stage)
delay → split the hot module (channel/audio) first, or add a replica (then ADR-0002 revisits).

## References
backend-spec §4.2/§4.3; AGENTS.md architecture guidelines; skill ref 01 §5.
