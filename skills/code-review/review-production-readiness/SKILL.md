---
name: review-production-readiness
description: Operability and release-safety lens for code review. Use when a change includes database migrations or schema changes, queries or indexes, network or third-party calls, background jobs and queues, caching, feature flags or config, logging/metrics/tracing, deploy/CI/infrastructure files, performance-sensitive paths, or new dependencies. Also use when the user asks "is this safe to ship", "can we roll this back", "what happens in production", "will this scale", "do we have enough observability", or wants a pre-deploy or launch review.
---

# Production Readiness Review

Code that is correct in a unit test can still fail in production: deployed alongside old versions, hit by 100× the data, starved by a slow dependency, or impossible to debug at 3 a.m. This lens asks: **if this ships today, how will we know it works, how does it fail, and how do we undo it?**

Findings use the shared format and severity scale from `code-review`. Skip sections the change doesn't touch.

## 1. Observability: can we tell it's broken?

- **Logs**: structured, with enough context to find the request/entity (IDs, correlation/trace ID), at the right level; errors logged once at the boundary with cause, not at every layer. No secrets or PII. Not so chatty that hot paths drown in noise or cost.
- **Metrics**: new behavior has the signals that matter: request rate, error rate, latency (RED), queue depth/age, saturation (USE), business outcome counters. Is there a way to tell "working" from "silently doing nothing"?
- **Tracing/propagation**: context passes through async boundaries, queues, and outbound calls.
- **Alerts and dashboards** exist or are updated for new failure modes; alerts are actionable and link to a runbook. A new critical path with no alert is a **major**.
- **Health checks** reflect real readiness, not just process liveness.

## 2. Failure modes and resilience

For every new external call (HTTP, DB, queue, cache, filesystem, another service), ask what happens when it is **slow, down, returns an error, or returns garbage**:

- **Timeouts** on every call; none means a hung dependency hangs us.
- **Retries** only for idempotent operations, with a cap, exponential backoff and jitter; no retry amplification across layers (retries × retries).
- **Circuit breakers, bulkheads, load shedding, backpressure** where a failing dependency could cascade. Unbounded queues and unbounded concurrency are deferred outages.
- **Graceful degradation**: can the feature fail without taking down the core path? Is the fallback correct (stale cache vs wrong data)?
- **Idempotency and deduplication** for anything delivered at-least-once (webhooks, queue consumers, scheduled jobs, client retries). Check for double-charge/double-send scenarios.
- **Ordering and concurrency**: duplicate workers, overlapping cron runs, leader election, locks with expiry.
- **Startup/shutdown**: graceful shutdown drains in-flight work; startup doesn't require every dependency to be perfectly healthy if it needn't; migrations don't run from many instances at once.

## 3. Data safety and migrations

Treat data changes as the highest-risk part of any release; they're usually the hardest to roll back.

- **Compatibility during deploy**: old and new code run side by side (rolling deploy, canary, rollback). Use **expand → migrate → contract**: add nullable/with-default columns or new tables first; dual-write/backfill; switch reads; remove old structures in a later release. A migration that only the new code can survive is a **blocker** unless deploy is atomic and downtime accepted.
- **Locking and duration**: does the DDL take long locks or rewrite a large table (adding a non-null column with default on old engines, adding an index without `CONCURRENTLY`, changing column types)? Estimate against production-sized data, not dev data.
- **Backfills**: batched, resumable, throttled, idempotent, and observable; not one giant transaction.
- **Reversibility**: is there a down-migration or a clear forward-fix plan? Destructive operations (drop, truncate, overwrite) require a backup/restore path and explicit confirmation of scope.
- **Constraints and indexes**: uniqueness and foreign keys enforced in the DB; indexes match new query patterns; no accidental sequential scans on large tables.
- **Privacy and retention**: new personal data has a purpose, retention/deletion path (including deletion requests), encryption where needed, and appropriate access controls.

## 4. Performance and capacity

Flag with reasoning, not vibes. Look for:
- N+1 queries, per-item network calls in loops, missing pagination/limits, unbounded result sets, large payloads, unnecessary serialization, repeated expensive work that could be cached or hoisted.
- Cache design: key includes everything that affects the value (tenant, user, locale); invalidation strategy exists; stampede protection on expensive keys; TTL chosen deliberately; no caching of authorized data under a shared key.
- Memory/CPU/connection use under load: pool sizes, file descriptors, thread/worker counts, queue consumers' concurrency.
- Cost: new paid API calls, LLM tokens, storage, egress. Per-user/per-request cost caps and quotas where a loop or hostile user could run up a bill.
- Is there evidence (benchmark, query plan, load test) for any claimed improvement or for risky paths?

## 5. Rollout and rollback

- **How does this reach users?** Feature flag, canary, gradual percentage, region-by-region, or all at once? High-risk or hard-to-reverse changes should be behind a flag with a safe default and a kill switch.
- **What is the rollback?** Redeploy previous version? Does that remain safe given data already written by the new version? Flag off? If rollback is impossible, say so and require stronger pre-checks.
- **Config and secrets**: new settings have safe defaults, validation at startup (fail fast on bad config), documentation, and are provisioned in every environment before deploy. Secrets come from the secret manager, not code or images.
- **Environment parity**: works in prod-like settings (TLS, proxies, read-only filesystems, different time zones, multiple instances), not only on a laptop.
- **Backward and forward compatibility** of APIs, events, and cached/serialized data across mixed-version fleets.

## 6. Build, deploy, and dependencies

- CI/CD changes: pinned actions/images, least-privilege tokens, no skipped checks, reproducible builds, artifacts verified between stages. (Security detail in `review-security`.)
- New dependencies: maintained, license-compatible, size/startup impact acceptable, version pinned, audit passes.
- Infra-as-code changes: plan reviewed, blast radius understood, no public exposure or wildcard permissions by accident, resources tagged/owned, quotas considered.
- Runbook/on-call updates when behavior, alerts, or failure handling change (see `review-docs-sync`).

## 7. Output

End with a short **Go/No-go readiness note**: what you verified, which risks remain and who owns them, the rollback story in one sentence, and the first signals to watch after deploy (specific metrics/logs/alerts and expected values).

## Severity guidance

| Situation | Typical level |
|---|---|
| Migration incompatible with the running version or that locks a hot table; irreversible data loss without backup; no timeout/limit on a critical-path external call; retry on non-idempotent payment/send | blocker–major |
| New critical path with no alerting or logs sufficient to debug; unbounded queue/concurrency; no rollback story for risky change; cache key missing tenant | major |
| Log noise, missing metric on non-critical feature, suboptimal index with small data, config lacking validation | minor |
| Style of log message wording | nit |
