# ADR-0006: Sync mechanism = transactional outbox + worker + WAL archiver + nightly CronJobs (no message broker)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session
- Driving NFRs / requirements: NFR-18 (publish gate), NFR-17 (WAL lag), storage-tiering §3 SYNC-01…06

## Context
Six sync rules (artifact uploads, WAL shipping, snapshots, partition archival, run evidence,
optional logs) must move data hot→cold with verification-before-delete semantics. Question: what
carries the jobs.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Outbox table + sync-worker + Postgres archive_command + CronJobs** | outbox row commits atomically with the catalogue row (no lost jobs); idempotent content-addressed keys; retry/backoff in one place; CronJobs are the repo's existing pattern (test-suite CronJob precedent); archive_command is Postgres-native | worker is one more small Deployment (P1); polling not push | small | — |
| Message broker (NATS/Kafka/Redis streams) | push semantics, fan-out | new stateful infra for a producer-consumer pair that lives in the same DB transaction domain; durability story for jobs becomes worse than the outbox (broker loss = job loss) | medium-high | NFR-18 (job durability), simplicity rule |
| Pure cron (no outbox) | simplest | P0 form is exactly this for the publish gate (synchronous upload+verify step) — but a crashed publish mid-upload leaves no resume record | lowest | acceptable only for P0's low volume; not the target |

## Decision
Target: outbox + worker (db-spec §4.12, storage-tiering §3). P0: publish-time synchronous
upload+verify (gate semantics preserved) + nightly CronJobs + archive_command. No broker, ever,
unless the revisit trigger fires.

## Consequences
Easier: job state is queryable SQL (backlog-age alert is a SELECT); replays are idempotent.
Harder: polling loop tuning; outbox pruning (30 d). Monitor: backlog age > 15 min alert,
WAL lag, snapshot miss ×2.

## Revisit trigger (measurable)
> 10 k outbox jobs/hour sustained, or a second consumer of the same events (e.g. analytics fan-out)
appears → re-evaluate a broker or Postgres LISTEN/NOTIFY.

## References
storage-tiering §3; sync-policy.csv; skill ref 02 §3.1; k8s/50-test-cronjob.yaml (CronJob precedent).
