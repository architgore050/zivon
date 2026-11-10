# DPDP Guardian Deletion & Breach Response Runbook (`RB-10` / `RB-11` / `GAP-007`)

Operable procedure for executing right-to-erasure requests (`NEED-013`,
`DELETE /v1/data`) and handling suspected data incidents (`RB-11`).

---

## 1. Self-Service Device Wipe (`API-007` — Online Path)

A student or parent/guardian on the device can trigger immediate erasure from
the Privacy page (`EL-PRV-003`/`004`) with zero account creation:

1. Client requests a one-time challenge token:
   `GET /v1/data/challenge?device_pseudo_id=<uuid4>` -> `{device_pseudo_id, confirm_token}` (10-min TTL).
2. Client submits `DELETE /v1/data` with `{device_pseudo_id, confirm_token, scope: "device"}`.
3. `DeletionAndRetentionService.wipe_device()` executes the 8-step cascade
   (`backend/privacy.py`, `< 60 s` p95 `NFR-24`):
   - **Step 1**: Writes `deletion_request` tombstone (`status='in_progress'`) before deleting any row.
   - **Step 2**: Hard-deletes `voice_turn` (C6), `eval_kid_session` (C4/C10),
     `telemetry_event` (C10), `session` (C20), `consent_record` (C9),
     `problem_report` (C17), and `device` (C8 seam). Preserves `credit_ledger`
     (C11, no personal content) and `audit_log` (C13, staff/system evidence).
   - **Steps 3–4**: Marks any `object_catalog` rows with `subject_ref = device_pseudo_id`
     as `deleted` and enqueues cold-storage deletion in `outbox`.
   - **Steps 5–6**: Calls `delete_subject(session_id)` for every session of the
     device, purging `log_events` in Postgres and scrubbing any fallback JSONL
     files under `runs/logs/`, then emitting one L3 `privacy.subject_deleted`
     audit event (IDs only).
   - **Steps 7–8**: Stamps `deletion_request` `status='completed'` with deleted
     row counts (`{sessions, consents, events, turns, reports}`) and records an
     `audit_log` row (`action='deletion.complete'`).

---

## 2. Guardian-Assisted Out-of-Band Deletion Intake (`GAP-007`)

When a parent/guardian contacts the founder/ops team requesting erasure:

1. **Intake & Verification (No Account Created)**:
   - Obtain the `device_pseudo_id` (displayed on the Privacy page) or `session_id`
     from the guardian, or match `session.guardian_ref` if populated post-challenge
     (`ADR-0007` / `T6`). Never solicit new child PII during verification.
2. **Execution**:
   - Run the idempotent erasure pipeline inside the `core-backend` pod:
     ```bash
     kubectl exec -n zivon deploy/core-backend -- python -c "
     import os
     from db import DatabaseEngine
     from backend.privacy import DeletionAndRetentionService
     eng = DatabaseEngine.from_url(os.environ['ZIVON_DB_URL'])
     res = DeletionAndRetentionService(eng).wipe_device('<DEVICE_PSEUDO_ID>')
     print(res)
     "
     ```
3. **Tombstone & Backup Ageing Verification**:
   - Confirm `deletion_request.status = 'completed'` in `audit_log` (`GET /v1/admin/audit`).
   - Live hot tiers (`U1`/`U2`/`U3`) are purged immediately (`<= 7 d` SLA `NFR-24`);
     immutable encrypted backups (`C14`) age out within their rolling window and
     are guarded by `REDEL-01` (`python -m backend.sync redelete-restore`) on any
     restore (`docs/deployment/restore-drill.md`).
4. **SLA Clocks**:
   - Online wipe: `< 60 s` p95 (`NFR-24`).
   - Full live + cold pipeline: `<= 7 d` target (`NFR-24`); statutory DPDP
     response clock (`90 d` `[ASSUMPTION — counsel item Q-L2]`).

---

## 3. Automated Retention & TTL Enforcement (`GAP-005` / `k8s/53`)

Even without a deletion request, `k8s/53-sync-cronjobs.yaml` enforces data
minimization automatically:

| CronJob | Command | Enforces |
|---|---|---|
| `ttl-voice-turn` | `python -m backend.privacy ttl-voice-turn` | 7-day hard delete on `voice_turn` transcripts (`A-02`) |
| `ttl-coverage` | `python -m backend.privacy ttl-coverage` | 24-hour idle clear on `session.coverage` |
| `ttl-abuse-bucket` | `python -m backend.privacy ttl-abuse-bucket` | 72-hour rolling expiry on salted HMAC IP hashes (`A-12`) |
| `rollup-daily-stats` | `python -m backend.privacy rollup-daily-stats` | Nightly aggregate roll-up into `daily_stats` + 30-day `session` delete |
| `ttl-telemetry` | `python -m backend.privacy ttl-telemetry` | 90-day delete on `telemetry_event` and resolved `problem_report` |

---

## 4. Suspected Breach Notification Path (`RB-11`)

1. **Contain (`<= 15 min`, `RB-05`)**: Rotate compromised K8s Secrets (`zivon-voice-env`,
   `zivon-db-env`, `zivon-admin-secret`, `zivon-cold-*`) and rollout-restart
   `deployment/core-backend` (`gotcha 18`).
2. **Triage (`<= 1 h`)**: Inspect `audit_log` (`GET /v1/admin/audit`) and
   `log.redaction_violation` events. Note that raw child audio is never stored
   (`C7`, schema-enforced `audio_retained = false`) and cold child-adjacent
   archives are client-side envelope-encrypted (`A-13`).
3. **Notification (`<= 72 h` `[ASSUMPTION — counsel Q-L2]`)**: Escalate to
   legal counsel for DPDP Board notification and update the Privacy page notice
   version (`ZIVON_NOTICE_VERSION`) if required.
