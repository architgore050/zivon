# Kubernetes — running Zivon on a cluster

## Object model (what maps to what)

| K8s object | Semantics | Zivon mapping |
|---|---|---|
| Pod | Smallest unit: 1+ containers sharing network/volumes | any running container |
| **Job** | Run a pod **to completion**, retry per `backoffLimit`, then done | **content factory** (batch pipeline) ✅ |
| **Deployment + Service** | Keep N replicas running forever; stable internal address | **frontend (nginx)** ✅, voice backend (Phase 2) |
| Namespace | Name isolation | `zivon` |
| Secret / ConfigMap | Runtime config & credentials | `ZIVON_API_KEY` at runtime — never in manifests |

Core idea: K8s is declarative. You write desired state in YAML; controllers reconcile reality toward it forever. The daily loop is `apply → observe events → diagnose → fix → recreate`.

## Our manifests (`k8s/`, numeric prefix = apply order)

- `00-namespace.yaml` — the `zivon` namespace.
- `10-factory-smoke-job.yaml` — the K8s twin of `docker run --rm zivon-factory:0.3.3`:
  - `Job` + `restartPolicy: Never` + `backoffLimit: 2` = batch semantics (fresh pod per retry; a failing Job ends `Failed` — CI-detectable).
  - No `command:` — the pod inherits the image's CMD (smoke test). Pipeline runs override it (see next file).
  - `securityContext: runAsNonRoot: true` + `runAsUser: 1000` — see gotcha below.
  - `resources.requests` (scheduler placement) / `limits` (hard ceiling; torch import alone needs several hundred MB → 2 Gi limit). QoS class is `Burstable`, which decides eviction priority under node pressure.
  - `automountServiceAccountToken: false` — the factory needs no K8s API access; pods get no cluster credentials.
- `20-factory-run-job.yaml` — the content factory run Job **TEMPLATE** (a manual admin tool, never automatic, never applied raw). It carries placeholders: the Job name `factory-run-template` and `"__CHAPTER__"` in the pipeline command. The only sanctioned trigger is `scripts/trigger-factory-run.sh "<chapter>" [class] [--fresh]`, which renders the name and chapter per run (`factory-run-<chapter>-<timestamp>`) — the Job is topic-agnostic: the topic is a runtime input, nothing topic-specific is baked into any manifest. `backoffLimit: 0`: a Job-level whole-pod retry is never sanctioned — a gate failure is fixed IN-run by its catcher (04/08/10), and an infra kill is recovered by re-running the trigger script, which RESUMES from completed stages (pipeline run ids are deterministic per chapter+class). Server URL + model come from the `zivon-factory-config` ConfigMap (values from `k8s/infra.env`), NOT from this file. The `secretKeyRef` for the API key is `optional: true` — keyless local servers need no Secret; hosted servers: create it. Mounts: `runs/` on the `zivon-sources` PVC (subPath `runs` — evidence persists and resume survives pod death), `frontend/` + `sources/` on PVCs (15/13). Hard cap 2 h — a cold-cache first run politely fetches + extracts the whole catalog, and the sources PVC makes that progress resumable.
- `12-hf-cache-pvc.yaml` — the `zivon-hf-cache` PVC: the HuggingFace embedder cache (~90 MB) shared by the run Job and the test CronJob, so the model downloads once per cluster, not once per run (`HF_HOME` is baked into the factory image).
- `13-sources-pvc.yaml` — the `zivon-sources` PVC: the textbook PDF + extracted-text cache (`sources/pdfs`, `sources/cache`) shared across pipeline runs. The first run downloads the catalog once; later runs reuse it (ingest never re-fetches a valid cached PDF). A cold run that dies partway is resumable.
- `15-frontend-pvc.yaml` — the `zivon-frontend` PVC: the shared site volume. The run Job writes generated pages onto it (11-link publishes into `/app/frontend`); the frontend Deployment serves it. Truth model: the PVC is the LIVE workspace; the repo's `frontend/` is the PERMANENT deploy snapshot (publish bridge below). Apply order note: the PVC (15) must exist before the Job (20) that mounts it.
- `30-frontend-deployment.yaml` — nginx Deployment serving the site. A no-clobber `initContainer` (`cp -rn /opt/zivon-shell/* ...` — glob form; see gotcha 6) seeds the hand-maintained shell (landing page + assets, baked at `/opt/zivon-shell` in the image) into an empty PVC, so the landing page exists before the first pipeline run and generated content is never overwritten. Non-root (UID 101), capabilities dropped, read-only root fs with writable mounts for nginx's pid/cache/log dirs, probes, resource ceilings. Because the seed is no-clobber, updating the shell on an existing PVC requires the re-seed procedure (gotcha 14).
- `40-frontend-service.yaml` — NodePort `80 → 8080`, fixed `nodePort: 30080`. Stable host URL with no manual command: **http://192.168.49.2:30080** (minikube's fixed node IP). `minikube service frontend -n zivon` is the convenience opener. On a real cluster only the Service `type` changes (ingress/LB decision, TIMELINE.md infra TODO). The nodePort stays a concrete integer in the manifest: kubeconform strict needs an int, so it cannot be a `${...}` placeholder.
- `50-test-cronjob.yaml` — the scheduled full test suite (unit + frontend + integration) using the factory image with a command override. THE ONLY AUTOMATIC workload in the stack. Its `schedule:` is a `${TEST_CRON_SCHEDULE}` placeholder rendered from `k8s/infra.env` by `scripts/apply-k8s.sh` — do not apply this file raw, and do not hardcode a cadence anywhere else (gotcha 7). Manual trigger: `scripts/trigger-tests.sh`.
- `infra.env` — NOT a manifest: the single source of truth for cluster config values (`TEST_CRON_SCHEDULE`, `ZIVON_BASE_URL`, `ZIVON_MODEL`, `ZIVON_TIMEOUT_S` — the timeout deliberately huge; NO completion caps are sent at all as of 2026-11-04, see `docs/content-factory/config-reference.md`), consumed by `scripts/apply-k8s.sh` (rendered into the CronJob + the `zivon-factory-config` ConfigMap). Secrets never belong here — API keys exist only as the runtime K8s Secret `zivon-factory-env`. Image tags deliberately stay pinned in the manifests (they are code versions, bumped with the code — gotcha 9).

## Cluster scripts (`scripts/`) — the apply flow and the admin "buttons"

- `scripts/apply-k8s.sh` — applies the whole stack from `k8s/infra.env`: namespace → `zivon-factory-config` ConfigMap (server URL + model) → manifests in dependency order (smoke Job deleted + re-applied so it re-runs as a post-apply health check; **20 deliberately NOT applied**) → the test CronJob rendered with `TEST_CRON_SCHEDULE` → **one immediate full test run** (`scripts/trigger-tests.sh startup`; the CronJob's first tick can be up to a full interval away, so startup coverage is explicit).
- `scripts/trigger-tests.sh [suffix]` — the test-suite "button": `kubectl create job test-<suffix>-<HHMMSS> --from=cronjob/test-suite -n zivon`.
- `scripts/trigger-factory-run.sh "<chapter>" [class 6-12] [--fresh]` — the content factory "button": renders the 20 template (name + chapter + optional `--class` / `--fresh`) and applies it. Generation is manual-trigger only, by design: the factory NEVER runs on a schedule. A re-trigger of the same topic+class RESUMES the previous attempt; `--fresh` forces clean generation.
- `scripts/logs-factory-run.sh [--status|--list]` — watches the **latest** generation run without knowing its generated name: every run Job carries label `task=factory-run` (20 template), so the script resolves the newest one by label and follows its logs. Output visibility never depends on a timestamp.
- `scripts/publish-frontend.sh` — the publish bridge PVC → repo (founder-run; manual discipline like the factory trigger): pulls `courses/` + `courses.js` from the site root on the `zivon-frontend` PVC and replaces them wholesale under the repo's `frontend/`; the hand-maintained shell (`index.html`, `assets/`) is never overwritten from the cluster. Commit after publishing — git history IS the version rotation (the next publish replaces a topic's previous version, which survives in history). Standalone deploy after publishing: `docker run --rm -p 8081:8080 -v "$PWD/frontend:/usr/share/nginx/html" zivon-frontend:0.1.1` — no factory, no cluster.
- Both trigger scripts are the documented stand-ins for the Day-8 admin dashboard buttons (see `TIMELINE.md`).

## Pipeline Run Job pattern (`20-factory-run-job.yaml` + trigger script)

The pattern every topic run follows — a topic-agnostic template + a manual trigger:

- **Template placeholders** — the manifest carries `factory-run-template` (name) and `"__CHAPTER__"` (pipeline command). `scripts/trigger-factory-run.sh "<chapter>" [class] [--fresh]` renders them per run: name becomes `factory-run-<chapter-slug>-<HHMMSS>`, the command becomes `python pipeline.py "<chapter>" [--class N] [--fresh]`. Nothing topic-specific lives in any manifest; the Job is just a factory run. The Job name is unique per trigger, but the pipeline's own run id inside is deterministic per (chapter, class) — that is what resume keys on.
- **Config via ConfigMap** — `ZIVON_BASE_URL` + `ZIVON_MODEL` come from `zivon-factory-config` (`envFrom`), whose values live in `k8s/infra.env`. Missing server config is a hard config error by design (the pipeline fails loudly until configured). The router itself must be up (`docker compose up -d inference-router`).
- **Secret for the key** — `ZIVON_API_KEY` via `secretKeyRef`, created imperatively (`kubectl create secret generic zivon-factory-env -n zivon --from-literal=...`). Never in a manifest, never in git. kube-linter's `unsecrets` check is exempted in `.kube-linter.yaml` with a documented reason: the manifest only *references* the Secret; the factory reads the key directly from the `ZIVON_API_KEY` env var (all server settings are env-only — see `docs/content-factory/config-reference.md`).
- **`activeDeadlineSeconds: 7200`** — a hung pipeline run dies; Jobs must not run forever. 2 h because a cold-cache first run politely fetches + extracts the whole catalog.
- **Output split** — `runs/` is the `zivon-sources` PVC (subPath `runs`) = PERSISTENT evidence and resumable stage artifacts: a re-triggered run reuses completed stages instead of re-deriving them, and failed-run evidence survives for `kubectl cp zivon/<pod> runs -c factory` inspection. `frontend/` is the `zivon-frontend` PVC: published pages land on the site the frontend Deployment serves, surviving the Job. Publish flow (2026-11-04): `scripts/publish-frontend.sh` bridges the generated output from the PVC into the repo's `frontend/` — the committed, permanent, standalone-deployable snapshot, held to the same contracts by `testing/frontend/test_shell.py` (catalogue entries resolve ↔ published directories listed; zero external refs in published files). `sources/` (PDFs + extracted text) is the `zivon-sources` PVC (13): the catalog is fetched once, every later run reuses it.
- **Manual-only by design** — the factory NEVER runs on a schedule. Only the test suite (50) is scheduled.

## Dev inference router (`docker/inference-router.Dockerfile`)

The dev machine's OpenAI-format inference server binds **127.0.0.1 only** — and no container can ever reach a host's loopback (see gotcha 8). The server stays untouched; instead a tiny router bridges the gap:

- An `alpine` + `socat` container with `network_mode: host` — inside it, `127.0.0.1` IS the host loopback where the server lives.
- It listens on **`192.168.49.1:18080`** — minikube's host-side bridge gateway IP, deliberately NOT `0.0.0.0` (the server chose loopback-only privacy; the router re-exposes it only to the cluster, not the LAN).
- Every connection is forwarded to `127.0.0.1:8080`. The factory treats `http://192.168.49.1:18080/v1` as a normal OpenAI-format server — zero code changes.
- Start: `docker compose up -d inference-router` (`restart: unless-stopped`). Verified from the host AND from inside a cluster pod (`/v1/models` answers through the router).
- Dev tool only: not a product image, not in CI, not deployed to real clusters.

## Local cluster: minikube (docker driver)

Single-node cluster running as a Docker container on the dev machine. Setup (one-time):

```bash
curl -LO https://storage.googleapis.com/minikube/releases/latest/minikube-linux-amd64
sudo install minikube-linux-amd64 /usr/local/bin/minikube
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
sudo install kubectl /usr/local/bin/kubectl

minikube start --driver=docker
minikube addons enable dashboard      # cluster UI (the CronJob/Job "Recreate" action)
minikube addons enable metrics-server # makes kubectl top nodes/pods work
minikube image load zivon-factory:0.3.3   # see gotcha 2
minikube image load zivon-frontend:0.1.1  # frontend hosting (see gotcha 2)
# Apply the whole stack from k8s/infra.env (ConfigMap + manifests + rendered
# CronJob schedule) and run the full test suite once on startup:
scripts/apply-k8s.sh
# → open http://192.168.49.2:30080 (no extra command needed)
# The two admin "buttons" (Day-8 dashboard stand-ins, documented in TIMELINE.md):
scripts/trigger-tests.sh                    # full test suite, on demand
scripts/trigger-factory-run.sh "Motion" 9   # one generation run (chapter + class)
kubectl logs -f job/<name> -n zivon         # watch either one
kubectl get jobs,pods,deploy,svc,cronjob,pvc -n zivon
kubectl logs job/factory-smoke -n zivon
kubectl describe pod -n zivon -l app=zivon-factory   # the Events section is the debugging gold
```

## Gotchas already paid for (learn from them)

1. **`runAsNonRoot` needs a numeric UID.** With only `USER app` in the image, kubelets refuse: *"image has non-numeric user (app), cannot verify user is non-root"* → `CreateContainerConfigError`. Fix: `runAsUser: 1000` in the manifest (or numeric `USER` in the image). kube-linter in CI now catches this class of mistake pre-cluster.
2. **minikube has its own image store.** Local images must be injected with `minikube image load` or pods sit in `ImagePullBackOff`. Once CI publishes to `ghcr.io`, clusters pull from the registry and this disappears.
3. **Jobs are immutable.** Editing a Job manifest requires `kubectl delete job ... && kubectl apply` — never apply-over.
4. **Group permissions after `usermod -aG docker`** only apply to new login sessions; GNOME terminals inherit the stale systemd user manager until reboot.
5. **Reused tags mean stale images.** The cluster keeps whatever bytes were loaded under a tag. New code → new tag (`0.2.0` → `0.2.1` after the pdfplumber fix) → `minikube image load` again → delete + re-apply the Job. Never re-tag different content the same version.
6. **busybox `cp` silently no-ops on a `/.` source.** The seed initContainer used `cp -rn /opt/zivon-shell/. <dest>/` — on Alpine (busybox) that exits 0 and copies *nothing*; GNU `cp` on your laptop would have worked. Symptom: nginx up, `/healthz` 200, but `/` → 403 (empty root, no index). Fix: glob form `cp -rn /opt/zivon-shell/* <dest>/`. Related lesson: **initContainers only run at pod start** — after fixing the manifest, `kubectl delete pod` (or a template change) is what re-runs the seed. CI image smokes don't catch this class: it's cluster-path behavior, verified on-cluster.
7. **Cron granularity is minutes, not seconds.** K8s CronJob `schedule:` is cron syntax (min hour day month weekday); "every x seconds" is not expressible. The cadence is the config value `TEST_CRON_SCHEDULE` in `k8s/infra.env`, rendered into the CronJob by `scripts/apply-k8s.sh` — the manifest carries only the placeholder, so there is exactly one place to change it. Smallest sane unit is every few minutes. If sub-minute test loops are ever needed, the pattern is a runner Deployment with a sleep loop — deliberately not built (P2).
8. **A host's `127.0.0.1` is invisible to every container.** Containers reach the host only through bridge gateway IPs (`172.17.0.1`, `192.168.49.1`), never loopback — so a server bound to `127.0.0.1` is unreachable from Docker and cluster pods. Fix without touching the server: the inference router (section above) or rebind the server to `0.0.0.0`. Also: pointing containers at the host's LAN IP fails too when the listen socket is loopback-only.
9. **Cluster runs run IMAGES, not your working tree.** A test fix in the repo does nothing in-cluster until a new tag is built + `minikube image load`ed + manifests bumped (0.2.1 → 0.2.2 for the read-only-safe test fix). The CronJob failing twice on the stale `tmp-bad.json` test, then going green on 0.2.2, is this loop in action.
10. **`ncert.nic.in` has a broken published TLS chain AND flaky connections.** It serves its Let's Encrypt leaf (issuer `CN = YE1`) WITHOUT the intermediate → stock verifiers fail with `unable to get local issuer certificate`; connections also get randomly reset mid-handshake, especially after a burst of requests (our first run hammered it for 58 min and got throttled). Fixed in `factory/ingest.py` (image 0.2.3): (a) pinned chain bundles per host at `sources/certs/<host>.pem` — `ncert.nic.in.pem` carries YE1 + Root YE + ISRG Root X1/X2 (regeneration notes inside the file; `Root YE` is cross-signed by Root X2, so the bundle needs X2 too); (b) fetches are polite (≥1.5 s apart) and retried 3× with backoff. Two lessons: name the bundle exactly `<host>.pem` (the code's lookup convention — `ncert-chain.pem` silently fell back to the system store), and treat textbook-site flakiness as normal.
11. **pdfplumber peaks hard on real textbooks.** The run Job was OOMKilled twice at the 4 Gi container limit during 00-ingest on full NCERT PDFs (the node has 32 Gi — the limit, not the cluster, was the wall). Fixed in 0.2.4: limit raised to 8 Gi, and the extracted-text cache is now actually read back (`_cached_pages`) — before this, `pages.json` was written but never reused, so every retry re-extracted the whole catalog and died at the same book. A durable cache only pays off if both halves (PDFs AND text) are reused.
12. **kube-linter forbids `ttlSecondsAfterFinished` on CronJob-managed Jobs.** For standalone Jobs (10, 20) kube-linter *requires* ttl; inside a CronJob `jobTemplate` the same check flips and errors — ttl conflicts with `successfulJobsHistoryLimit`/`failedJobsHistoryLimit`, which are the CronJob-native cleanup. The CronJob carried a ttl from its introduction until the local re-run of the CI gates caught it. Rule of thumb: cleanup via ttl in standalone Jobs, via history limits in CronJobs. (Also caught locally: `source`-ing a config file sets shell-local vars — `envsubst` in a child process only sees **exported** ones, so `apply-k8s.sh` exports the infra.env values.)
13. **A bad extracted-text cache poisons later runs until purged.** `_save_pages` runs before the class-evidence check, so when NCERT's physics-11 prelims arrived garbled (symbol-font glyphs, see `docs/content-factory/architecture.md` 00-ingest), the garbled `prelims.pages.json` was cached on the sources PVC and every re-run would reuse it and die identically. Fix sequence (done 2026-11-02): decode symbol fonts in `clean_pdf_text` (0.2.5), purge the stale file via a one-shot busybox pod mounting the PVC (`rm /peek/cache/<book>/prelims.pages.json`), re-run — the PDF itself stays cached, only the text is re-extracted. The ingest error message now names this exact purge step when evidence text looks garbled.
14. **A shell update never propagates into a seeded `zivon-frontend` PVC - and a naive "delete + recreate the PVC" does NOT wipe the data on minikube.** The seed initContainer is no-clobber (`cp -rn`): once a PVC has a shell, a newer frontend image does not refresh it. Symptom (2026-11-04): the §10 shell shipped in `zivon-frontend:0.1.1` but the live site still served the old CSS. The trap on top of the trap: minikube's hostpath provisioner names the backing directory after the CLAIM (`/tmp/hostpath-provisioner/<ns>/<claim>`), so deleting the PVC and re-applying `15` binds the new PV to the SAME directory - old shell and old pages survive, and the no-clobber seed no-ops. Full re-seed procedure (verified 2026-11-04): (1) delete the frontend Deployment, wait for its pod to be gone; (2) delete the PVC - if it hangs Terminating on the `pvc-protection` finalizer, a stale pod (often phase `Unknown` after a minikube restart) is the blocker: force-delete it, and if it still hangs patch the finalizer off (`kubectl patch pvc ... -p '{"metadata":{"finalizers":null}}'`); (3) `kubectl get pv` and DELETE the `Released` leftovers - the provisioner's `Delete` reclaim is what actually wipes the host directory (skipping this orphans the old PV and keeps the data alive); (4) verify the directory is gone (`docker exec minikube ls /tmp/hostpath-provisioner/zivon/`); (5) re-apply `15` + `30` - the new image seeds the new shell - and verify byte-identity (`md5sum` the seeded `zivon.css`/`zivon.js`/`index.html` against the repo); (6) restore published pages from the repo snapshot (`kubectl cp frontend/courses zivon/<frontend-pod>:/usr/share/nginx/html/courses`, same for `courses.js`) or simply re-run the factory if the pages are being regenerated anyway. Related: pipeline perf stages measure the shell copied from the container's mounted `frontend/`, so re-seed BEFORE a generation run that must evaluate the new look.

## Hosting decision (partially closed)

Closed by the frontend objects (15/30/40): generated pages persist on a PVC, nginx serves them as a Deployment + Service, and locally the NodePort gives a stable URL (http://192.168.49.2:30080) with `docker compose up web` serving the same site on :8080 (LAN-reachable for kid testing).

Still open (hosting stage): **which real cluster** runs this (managed Kubernetes vs a small VM host running k3s), and the **public domain** piece (ingress vs load balancer, TLS, DNS — the local NodePort is a dev convenience, not the public answer). The deploy pipeline waits on those.

What is NOT open (HTTPS posture, locked 2026-11-04): TLS terminates at the **edge** — the app and cluster serve plain HTTP behind it and never implement TLS themselves. Generated pages are already host-agnostic: the relative-URL guarantee lives in the harness (factory lint + page CSP, re-checked on published snapshots in CI) — see `docs/deployment/README.md`, Decisions locked. The NodePort site stays dev-only.
