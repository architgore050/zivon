# Cold Restore Drill Runbook (`RB-12` / `DRILL-01` / `GAP-004`)

Operable procedure for executing a timed cold-storage database and content
restore drill into an isolated scratch namespace (`zivon-drill`), verifying
`NFR-17` (`RPO <= 5 min`), `NFR-19` (`RTO <= 4 h`), and `REDEL-01`
(re-delete-on-restore tombstone enforcement).

- **Cadence**: One timed drill before Gate D / submission (`DRILL-01`, P0),
  then monthly (`RB-12`, P1).
- **Owners**: Founder + Ops (`EX0-BACKEND`).
- **Gate rule**: Failure of the drill blocks Phase 3 done, never the live demo
  (the drill executes strictly inside `zivon-drill`).

---

## 1. Preconditions

1. At least one verified base backup (`c14/base/...`) and nightly consent/tombstone
   snapshot (`c9/consent-snap/...`) exist in cold storage (`cold_verified_at IS NOT NULL`
   in `object_catalog`).
2. Read-only restore credentials (`zivon-cold-restore` Secret, `storage-tiering.md` §5)
   are available locally or mounted into the scratch namespace.

---

## 2. Step-by-Step Drill Procedure

### Step 1 — Quiesce or Snapshot Writers (Timestamp $T_0$)

Record start timestamp `T0=$(date -u +"%Y-%m-%dT%H:%M:%SZ")`:

```bash
# Trigger an immediate verified base backup + consent/tombstone snapshot
kubectl exec -n zivon deploy/core-backend -- python -m backend.sync base-backup
kubectl exec -n zivon deploy/core-backend -- python -m backend.sync sync-nightly
```

### Step 2 — Provision Scratch Namespace (`zivon-drill`) and Restore `zivon-db`

Create an isolated namespace so live `zivon` traffic is untouched:

```bash
kubectl create namespace zivon-drill --dry-run=client -o yaml | kubectl apply -f -
sed 's/namespace: zivon/namespace: zivon-drill/g' k8s/25-postgres.yaml | kubectl apply -f -
kubectl rollout status deployment/postgres -n zivon-drill
```

Fetch the latest verified base backup (`base/<YYYY-MM-DD>.zst.enc`) and replay WAL
segments up to `recovery_target_time`, then apply linear Alembic migrations:

```bash
sed 's/namespace: zivon/namespace: zivon-drill/g' k8s/28-backend-config.yaml | kubectl apply -f -
sed 's/namespace: zivon/namespace: zivon-drill/g' k8s/26-backend-migrate-job.yaml | kubectl apply -f -
kubectl wait --for=condition=complete job/backend-migrate -n zivon-drill --timeout=120s
```

### Step 3 — Enforce `REDEL-01` (Re-Delete Tombstoned Subjects Before Cutover)

**Mandatory (`storage-tiering.md` §6.1)**: Because immutable backups aged `<= 30 d`
may contain rows for devices that requested erasure after the backup was taken,
run `redelete-restore` **before** the restored instance accepts student traffic:

```bash
sed 's/namespace: zivon/namespace: zivon-drill/g' k8s/27-core-backend.yaml | kubectl apply -f -
kubectl rollout status deployment/core-backend -n zivon-drill
kubectl exec -n zivon-drill deploy/core-backend -- python -m backend.sync redelete-restore
```

Verify zero rows survive for any tombstoned `device_pseudo_id`:

```bash
kubectl exec -n zivon-drill deploy/core-backend -- python -c "
from db import DatabaseEngine
import os
eng = DatabaseEngine.from_url(os.environ.get('ZIVON_DB_URL', 'sqlite:///:memory:'))
hit = eng.fetchone('''
    SELECT COUNT(*) AS cnt FROM device
    WHERE device_pseudo_id IN (SELECT device_pseudo_id FROM deletion_request WHERE status = 'completed')
''')
assert int(hit['cnt']) == 0, 'REDEL-01 violation: tombstoned device resurrected!'
print('REDEL-01 verified: 0 resurrected rows')
"
```

### Step 4 — Smoke Test Restored Monolith (`/v1/health`, `voice_turn`, `guard_counter`)

```bash
kubectl exec -n zivon-drill deploy/core-backend -- python -m backend --smoke
```

Check `/v1/health` returns `status: "ok"`, `db: "ok"`, `schema_version: "0002"`,
and `guard_profile` + `guard_counter` rows are queryable.

### Step 5 — Tabletop Breach Walk-Through (`RB-11`) & Cleanup

1. Walk through `docs/deployment/deletion-runbook.md` §4 (`RB-11` suspected
   breach triage 1 h -> DPDP Board 72 h clock `[ASSUMPTION — counsel Q-L2]` ->
   credential rotation `RB-05` <= 15 min).
2. Record elapsed time $T_{\text{done}} - T_0$ (must be `<= 4 h` per `NFR-19`,
   target `~15 min` for P0 volume) and sign off in `docs/logs/`.
3. Tear down the scratch namespace:

```bash
kubectl delete namespace zivon-drill
```
