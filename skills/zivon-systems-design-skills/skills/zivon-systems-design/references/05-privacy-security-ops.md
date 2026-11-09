# Privacy, security and operations

## 1. Privacy by design for minors (engineering view; legal conclusions need counsel)

Context (secondary sources, see `06-zivon-systems-constraints.md` and `sources-and-evidence.md`): India's DPDP Rules 2025 require verifiable consent of a parent/guardian for under-18 users, restrict tracking/behavioural monitoring/targeted advertising directed at children (narrow purpose-based exemptions), set breach-notification and rights-response clocks, and phase in most duties about 18 months after notification (≈ May 2027). Design so that compliance is a configuration of the system, not a rewrite.

Engineering controls:
- **Data map first**: the classification table *is* the record of processing. Every class has purpose, legal basis placeholder, retention, recipients (Gnani models, hosting, cold provider = processors/sub-processors - list them).
- **Minimize**: no raw audio by default; transcripts only where a feature needs them; truncate `sim_state`; no device fingerprinting; no third-party analytics SDKs.
- **Pseudonymize**: events and sessions reference a random `device_profile_id`; any mapping to a guardian identity lives in a separate, tightly-scoped table/store.
- **Consent as data**: `consent_record` gates features at the API layer (middleware checks scope) - not just in the UI.
- **Deletion pipeline** (subject_ref → find all copies): DB rows → derived tables → SSD files → cold objects (delete or crypto-erase) → caches/CDN purge → search of logs (should be empty of PII) → record completion in the audit log; backups age out within a documented window and a re-delete list is applied on restore. Target far inside the legal response clock.
- **Access control**: least-privilege roles for services; humans have no standing access to child data; break-glass access is logged and reviewed.
- **Cross-border and processors**: record where each sub-processor stores/processes data (Gnani, GPU host, cold provider); get counsel's view on transfer rules before choosing regions.
- **Breach readiness**: detection → triage → notify path with owners and the 72-hour board-notification clock (verify) rehearsed in a runbook.

## 2. Security essentials (use vendored `secure-code-guardian` as a checklist)
Secrets via env/K8s Secrets only (repo rule); no keys in images/manifests/CI; TLS everywhere; admin surfaces authenticated and separated from student paths; rate limits and abuse controls on the WebSocket and write endpoints; input validation at the edge; strict CSP for generated lesson code; dependency and image scanning already in CI (repo) - extend to new services; encrypt data at rest on SSD volumes and in cold (client-side for personal data); rotate credentials; separate credentials for archival writers vs deleters (see `02` §4); restore-credentials held offline.
Threat prompts (STRIDE-style, brief): spoofed device/guardian; tampered lesson bundle (hash + signature check at publish); repudiated consent (append-only ledger); information disclosure via logs/object keys; DoS via audio floods or credit exhaustion; privilege escalation from admin UI; supply-chain (third-party SDKs, models); prompt injection via page content or transcripts.

## 3. Observability and SLOs (use vendored `sre-engineer`)
- **Golden signals per service** + per-stage voice latency histograms; trace id propagated client → WS → STT → LLM → TTS; structured JSON logs with no PII or transcripts; error budgets for the voice path; synthetic probes for content and voice.
- **Product-health dashboards** derived from `EVT-…` (aggregate, pseudonymous): sessions, turns/resolved doubt, first-attempt check correctness, fallback rates (text-only, no-translation), credit burn per minute, p95 first-audio latency.
- **Ops metrics specific to this design**: outbox backlog age, cold-verification lag, SSD usage and eviction rate, WAL archive lag, scrub drift count, last successful restore drill, deletion SLA.
- **Alerting**: page only on user-visible or data-loss risks (voice first-audio p95 breach, outbox stuck, WAL lag, SSD > 90 %); everything else is a ticket.
- Align with the repo's Day-8 plan (structured logging, telemetry, per-stage latency, error tracking, admin dashboard v0) and K8s monitoring (Prometheus/Grafana, admin-authed) rather than inventing a parallel stack.

## 4. Runbooks to write (one page each)
SSD full · SSD/node loss and restore · cold provider outage · credential leak · corrupted cold object · bad content publish and rollback (switch `live_pointer` to previous version) · Gnani credit exhaustion · voice latency regression · deletion request · breach response · monthly restore drill.

## 5. Deployment alignment
Voice backend = Deployment + Service (repo); content factory = Job (manual-trigger only); frontend = nginx Deployment serving a volume; PVCs: existing `zivon-sources`, `zivon-frontend`; add volumes only with a data-class justification; every new image follows the Dockerfile pattern (slim base, deps-before-code, non-root) and gets a CI job and manifests; document changes in `docs/deployment/` in the same PR. Cold-sync workers are separate Deployments/CronJobs with their own service accounts and credentials.
