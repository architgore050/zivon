# ADR-0002: Session state = in-process memory + Postgres rows (no Redis in P0)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session
- Driving NFRs / requirements: NFR-09/13; handoff §3 (resume semantics); repo rule "session memory: in-memory/lightweight for MVP"

## Context
Live session state (C5: current turn, anchor, partials, flags) is ephemeral and lost-on-crash is
acceptable (client resumes with context). Durable session facts (C20) belong in the DB. The voice
backend runs 1 replica at demo scale (NFR-13).

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Memory (U1) + Postgres (U2)** | zero extra infra; crash = reconnect + re-bootstrap (already the designed behaviour); durable rows already exist for resume | state dies with pod (accepted); no cross-pod sharing | none | — |
| Redis / valkey | cross-pod session sharing, TTL primitives | new stateful service + credentials + failure domain for a class explicitly marked "lost-on-crash acceptable" | medium | violates "add a cache or queue only when an NFR demands it" (ref 01 §5) |
| DB-only session state (JSONB hot rows) | one store | write amplification per audio turn; silly | low | NFR-14 hot-path cost |

## Decision
Memory for C5, Postgres for C20/C6 boundaries. Resume = API-009 revalidate + 60 s final-message
replay window held in the pod's memory.

## Consequences
Easier: nothing to operate beyond the pod; crash behaviour is already tested by the failure-mode
table. Harder: a pod restart drops ≤ 1 in-flight turn (student sees system-error + retry).
Monitor: pod restart count; if > 1/day investigate before adding any store.

## Revisit trigger (measurable)
2nd voice replica deployed (load test > 10 concurrent sustained) OR resume-failure rate > 1 % of
sessions → evaluate Redis (then it joins U1 with its own data-class row).

## References
backend-spec §3/§7.1; handoff §3; skill ref 03 §2 (key-value = session state only).
