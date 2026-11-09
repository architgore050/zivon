# Secrets — runtime-only, by name

The registry AGENTS.md requires: every credential Zivon uses, the K8s Secret
object that carries it, who creates it, and who consumes it. **Values never
enter the repo, images, manifests, or workflows** — this file documents NAMES
and KEYS only. If you find a value anywhere else, that is a leak: rotate the
credential, then fix the leak (gitleaks + GitHub push protection are the
tripwires, and CI runs key-free so nothing can "need" a secret).

Owner: EX6-CICD (GAP-001). Objects marked "EX0/EX3 manifests" are created by
the owning agent's manifests (`envFrom` / `secretKeyRef`, env-only injection);
the FOUNDER creates the objects themselves and holds the values.

## The Secret objects

| Secret object | Keys (names only) | Created by | Consumed by |
|---|---|---|---|
| `zivon-factory-env` (exists) | `ZIVON_API_KEY` (OpenRouter key, shared by the node + factory) | founder | factory Job (`k8s/20`, `50`), llm-manager node (`k8s/16`), evals CronJob (`k8s/52`) |
| `zivon-voice-env` | `GNANI_PRISMA_API_KEY`, `GNANI_TIMBRE_API_KEY`, `ZIVON_VOICE_GEMINI_API_KEY`, `ZIVON_DB_URL`, `ZIVON_SESSION_TOKEN_KEY`, `ZIVON_IP_HASH_SALT` | founder (values); EX0 (manifest reference) | core-backend monolith incl. `voice/` (`k8s/25–28`) |
| `zivon-db-env` | `POSTGRES_PASSWORD` | founder (values); EX0 (manifest reference) | Postgres (`k8s/25`) + core-backend monolith |
| `zivon-cold-writer` | B2/R2 application key — upload+read only, **no delete** (storage-tiering §5) | founder (values); EX0 (manifest reference) | sync worker (`k8s/51/53` bundle) |
| `zivon-cold-deleter` | B2/R2 application key — delete-capable identity | founder (values); EX0 (manifest reference) | deletion pipeline jobs |
| `zivon-cold-restore` | B2/R2 application key — read-only restore identity | founder (values); EX0 (manifest reference) | restore/DRILL-01 jobs |
| `zivon-admin-auth` | `ZIVON_ADMIN_TOKEN` (single-admin bearer, ADR-0026) | founder (values); EX3 (manifest reference) | admin dashboard (`k8s/23–24`) |

Rules that hold across all of them (already enforced by the repo, restated so
nobody "fixes" around them):

- Manifests reference secrets via `envFrom.secretRef` / `valueFrom.secretKeyRef`
  (env injection) — never `env.value`, never `stringData` in a committed manifest,
  never compose defaults. kube-linter's `unsecrets` check is deliberately
  exempted in `.kube-linter.yaml` because env injection IS the intended pattern.
- `k8s/infra.env` is config values only — no secret keys, no placeholder values
  that invite real ones. `ZIVON_DB_URL` in `zivon-voice-env` is the one DSN-shaped
  entry and it is a Secret because the password is inside it.
- The three cold identities preserve the least-privilege split: the writer cannot
  delete, the deleter does not read data, the restorer only reads.
- CI never sees any of these (the merge gate + promotion gate run key-free;
  `docs/deployment/cicd.md` security posture table).

## Creating the objects (founder runbook — names/keys only, values stay in the terminal)

```bash
# exists already (factory + node + evals)
kubectl create secret generic zivon-factory-env -n zivon \
  --from-literal=ZIVON_API_KEY='<openrouter key>'

# core-backend monolith + voice (EX0 manifests reference it)
kubectl create secret generic zivon-voice-env -n zivon \
  --from-literal=GNANI_PRISMA_API_KEY='<gnani prisma key>' \
  --from-literal=GNANI_TIMBRE_API_KEY='<gnani timbre key>' \
  --from-literal=ZIVON_VOICE_GEMINI_API_KEY='<google ai studio key>' \
  --from-literal=ZIVON_DB_URL='postgresql://zivon:<db-password>@postgres.zivon.svc.cluster.local:5432/zivon' \
  --from-literal=ZIVON_SESSION_TOKEN_KEY='<128-bit hex>' \
  --from-literal=ZIVON_IP_HASH_SALT='<128-bit hex>'

# Postgres itself
kubectl create secret generic zivon-db-env -n zivon \
  --from-literal=POSTGRES_PASSWORD='<db-password>'

# cold provider identities (least-privilege split, storage-tiering §5)
kubectl create secret generic zivon-cold-writer -n zivon \
  --from-literal=B2_APPLICATION_KEY_ID='<key id>' \
  --from-literal=B2_APPLICATION_KEY='<write-only key>'
kubectl create secret generic zivon-cold-deleter -n zivon \
  --from-literal=B2_APPLICATION_KEY_ID='<key id>' \
  --from-literal=B2_APPLICATION_KEY='<deleter key>'
kubectl create secret generic zivon-cold-restore -n zivon \
  --from-literal=B2_APPLICATION_KEY_ID='<key id>' \
  --from-literal=B2_APPLICATION_KEY='<read-only key>'

# admin dashboard (ADR-0026)
kubectl create secret generic zivon-admin-auth -n zivon \
  --from-literal=ZIVON_ADMIN_TOKEN='<long random token>'
```

## Rotation (gotcha 18 — keys are read at pod start)

1. Create the new value into the SAME Secret key (`kubectl create secret generic
   ... --from-literal=... --dry-run=client -o yaml | kubectl apply -f -`).
2. Rollout-restart every consuming Deployment (`kubectl rollout restart deploy/<name> -n zivon`)
   — Jobs/CronJobs pick the new value up on their next run by themselves.
3. Delete the old upstream credential (Gnani dashboard / Google AI Studio / B2) only
   AFTER the restarted pods are healthy — the roll is then reversible.
4. Record the rotation date + the next due date in the deployment runbook row below.

| Credential | Rotation trigger | Suggested cadence |
|---|---|---|
| Gnani Prisma/Timbre keys | programme end / suspected leak | per challenge cycle |
| Google Gemini API key | per Google AI Studio guidance | 90 d |
| OpenRouter key (`ZIVON_API_KEY`) | suspected leak / key visible in a log | 90 d |
| `POSTGRES_PASSWORD` | with any DB restore drill | quarterly |
| `ZIVON_SESSION_TOKEN_KEY` / `ZIVON_IP_HASH_SALT` | leak only — rotating invalidates sessions / breaks abuse-counter continuity | on compromise |
| B2/R2 application keys | least-privilege re-review | 180 d |
| `ZIVON_ADMIN_TOKEN` | admin-adjacent incident | 90 d |

Revisit triggers: a new consuming service (add a row + its `envFrom`), a key
scope change (re-cut the B2 identities), or the P1 move to per-user admin
identity (ADR-0026 successor) — that one gets its own Secret row here.
