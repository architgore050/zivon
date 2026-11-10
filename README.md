# Zivon

**A voice-first AI tutor Indian students can actually talk to.**

Built for the **Great Indian AI Internship Challenge** (Gnani AI) on Gnani's sovereign stack:

> Student speaks (Hindi / English / Hinglish) → **Prisma v3.0** listens → **Gemma 4 26B A4B** (via Gemini API) reasons → **Timbre v3.0** speaks back.

**Focus:** academic Physics, Class 9–12 — taught through interactive animations, simulations, and diagrams, with a patient spoken Hinglish tutor anchored to every page.

---

## Status

🚧 **In active build.** Deadline: **10 November 2026, 11:59 PM IST**.

- Live demo: *coming soon* (link will be pinned here)
- Day-by-day build plan: [`TIMELINE.md`](TIMELINE.md)

---

## What It Does

1. A multi-agent **content factory** curates official NCERT / public-domain material and synthesizes it into interactive learning pages — each page pairs clear text with generated **animations, interactive simulations, and diagrams**, reviewed for factual accuracy and first-time-learner clarity.
2. Students (validated with real kid testers) learn from these pages on the live site.
3. On any page, the student can press the mic and ask a doubt **out loud, in Hinglish**. The tutor knows what's on the screen, explains step by step, narrates interactions with the simulation, asks Socratic follow-up questions, and answers in natural Indian-accented voice with expressive prosody.

## Architecture

```
        ┌─────────────────────────── PRODUCT RUNTIME ───────────────────────────┐
        │                                                                       │
  🎤 mic ─→ Prisma v3.0 ─→ Gemma 4 26B A4B ─→ Timbre v3.0 ─→ 🔊 tutor voice
              (STT)         (reasoning)     (TTS + expressive tags)
                    ▲                              │
                    └──── page context (topic,     │
                          what the student is      │
                          reading/interacting with)┘

        ┌─────────────────────────── CONTENT FACTORY (build-time) ──────────────┐
        │  Curator → Synthesizer (JSON visual specs) → Visual Builder           │
        │  → Performance Engineer → Comprehension & Fact Reviewer → Code Review │
        └───────────────────────────────────────────────────────────────────────┘
```

- **Product runtime** runs on the Gnani stack (Prisma + Timbre + Gemma 4 reasoning (Evon = post-challenge aspiration)).
- **Content factory** is build-time tooling (`pipeline.py` + `factory/`) that runs on any local OpenAI-format model — all model calls go through the standalone **`llm_manager/`** module (streaming transport, honest inactivity timeouts, a per-call wall-clock deadline), which also ships as an isolated **llm-manager node** (own image + K8s Deployment/Service) that every consumer talks to. Server wiring via environment variables, pipeline behaviour via `config.json` (see `.env.example`). Build-time models are a deliberate choice (see TIMELINE.md, guiding rule 4); the product runtime stays Gnani.

## Run the content factory

```bash
pip install -r requirements.txt
python -m playwright install chromium      # once, for the perf gate
# server settings come from the environment (never from files):
export ZIVON_BASE_URL=http://127.0.0.1:8080/v1     # your inference server (host loopback is fine HERE)
export ZIVON_MODEL=qwen3.8-flash-next-iq3_xxs      # exactly as GET /v1/models reports
python pipeline.py "Motion" --class 9
python pipeline.py "Motion" --class 9 --locales hi,hi-Latn   # optional: build Hindi + Hinglish localized routes
```

Model calls are streaming by default: `ZIVON_TIMEOUT_S` bounds INACTIVITY between chunks (a dead server is caught honestly) and `ZIVON_CALL_DEADLINE_S` is a total per-call wall-clock cap that aborts a runaway generation mid-stream. Locally you can also run the model path through the isolated **llm-manager node** (`docker compose up -d llm-manager`, then `ZIVON_BASE_URL=http://127.0.0.1:18090/v1`) — the same service the cluster runs at `http://llm-manager.zivon.svc.cluster.local/v1`.

Read-aloud narration (stage 12) is **opt-in** build-time TTS: `export
ZIVON_NARRATION_ENABLED=true` before a run (or
`python pipeline.py "Motion" --class 9 --stages 11-link,12-narration` on a
finished topic). Without a Timbre endpoint it produces silent mock assets
(credited `mode: "mock"` in the manifests, zero credits); with
`ZIVON_TIMBRE_BASE_URL`/`ZIVON_TIMBRE_API_KEY` it pre-generates real audio
with Gnani Timbre v3.0 under the A-15 credit tranche (refuse-before-exceed;
see `docs/content-factory/runbook.md`, "Narration builds"). ffmpeg must be
on PATH for the Opus encode.

Run ids are deterministic per (chapter, class): re-running the same command **resumes** the previous attempt — completed stages load from `runs/` instead of re-calling the model; pass `--fresh` to wipe the attempt and generate clean.

Running the factory **in a container or on the cluster** instead? Those can never see a host's loopback — start the inference router (`docker compose up -d inference-router`) AND the llm-manager node (`docker compose up -d llm-manager`), then point the factory at the node: in compose set `ZIVON_BASE_URL=http://llm-manager:8000/v1` **and** `ZIVON_NODE_UPSTREAM_URL=<server address>` (the node's own upstream — one variable for both would make the node call itself), plus `ZIVON_MAX_ATTEMPTS=1` on the factory side (the node owns transport retries). In the cluster the ConfigMaps already encode this split (factory → llm-manager Service → router). See [`docs/deployment/kubernetes.md`](docs/deployment/kubernetes.md).

Every run keeps full evidence (requests, responses, retries, reports) under `runs/`. Tests: `python -m unittest discover -s testing/content_factory/unit -t .` — see `testing/README.md` and `docs/content-factory/runbook.md`. The cluster also runs the full suite on a schedule (CronJob `test-suite`); trigger it on demand with `kubectl create job --from=cronjob/test-suite <name> -n zivon` — the standing "button" until the admin dashboard exists (see `docs/deployment/cicd.md`).

## Tech Stack

| Layer | Choice |
|---|---|
| STT | Gnani **Prisma v3.0** (streaming, code-mixed, noisy-audio strong) |
| LLM | Gnani **Gemma 4 26B A4B** via Google Gemini API (Evon v3.3 post-challenge aspiration) |
| TTS | Gnani **Timbre v3.0** (streaming, expressive tags) |
| Backend | Python — FastAPI + WebSockets |
| Frontend | Web UI with mic; static interactive pages (canvas/SVG) |
| Infra | Docker containers, Kubernetes, CI/CD, staging → prod |

## Running with Docker

The content factory ships as a container image (`Dockerfile` at the repo root):

```bash
docker build -t zivon-factory:0.3.17 .
docker build -f Dockerfile.llm-manager -t zivon-llm-manager:0.1.0 .   # the model-call node (slim, no torch)
docker build -f Dockerfile.dashboard -t zivon-dashboard:0.1.0 .       # the admin dashboard (slim + kubectl)
docker run --rm zivon-factory:0.3.17                          # environment smoke test
docker compose up -d llm-manager                              # the isolated model-access node (factory -> node -> server)
docker compose run --rm factory python pipeline.py "Motion" --class 9   # full pipeline run
docker compose up web                                        # serve frontend/ on http://localhost:8081
ZIVON_ADMIN_TOKEN=<secret> docker compose up -d dashboard    # admin dashboard v0 on http://127.0.0.1:8082
```

- API keys are passed via environment variables (`ZIVON_API_KEY`) — never baked into the image.
- `runs/`, PDF/text caches, and the HuggingFace model cache are mounted as volumes, so containers stay disposable and caches survive between runs.
- `docker-compose.yml` is the local dev runner; Kubernetes manifests come with the deployment setup.

**Dev stack for the incoming Wave-E services** (opt-in profile — the default `compose up` commands above behave exactly as before):

```bash
docker compose --profile dev-stack up -d    # dev Postgres (:5433) + evals runner; the dashboard keeps its own `docker compose up -d dashboard` (:8082)
docker compose --profile backend up -d      # db + core-backend (:8090) — needs EX0's Dockerfile.backend
docker compose run --rm evals-runner        # deterministic eval smoke (no model calls)
```

These boot key-free by design (config-only env, throwaway dev DB credentials) and error only when a service's Dockerfile has not landed yet — see [`docs/deployment/cicd.md`](docs/deployment/cicd.md) § Path guards.

## Kubernetes (local cluster)

Manifests live in `k8s/` (numeric prefix = apply order); `k8s/infra.env` is the single source of truth for cluster config values (test cadence, inference server URL, model). Local cluster is minikube with the docker driver:

```bash
minikube start --driver=docker
minikube image load zivon-factory:0.3.17   # minikube has its own container store
minikube image load zivon-llm-manager:0.1.0   # the model-call node
scripts/apply-k8s.sh                      # ConfigMaps + all manifests + rendered CronJob + startup test run
kubectl get jobs,pods,deploy,svc,cronjob,pvc -n zivon
kubectl logs job/factory-smoke -n zivon   # expect: smoke test passed
# the site, live with no extra command: http://192.168.49.2:30080
scripts/trigger-tests.sh                  # manual full test run (the "button")
scripts/trigger-factory-run.sh "Motion" 9 # one generation run (same topic+class RESUMES; add --fresh to force clean generation)
scripts/logs-factory-run.sh               # follow the latest run's logs (no job name needed)
scripts/publish-frontend.sh               # mirror the cluster-built site (courses/ + courses.js) into frontend/ - the versioned deploy snapshot
```

- The content factory runs as a **Job** (batch, runs to completion) and is **manual-trigger only** — generation never runs on a schedule. Only the test suite is scheduled (cadence from `TEST_CRON_SCHEDULE` in `k8s/infra.env`). The voice backend will run as a **Deployment + Service** when it exists.
- `k8s/20-factory-run-job.yaml` is a topic-agnostic TEMPLATE (placeholders for name + chapter); `scripts/trigger-factory-run.sh` is the only sanctioned way to start a run. Re-triggering the same topic+class RESUMES the previous attempt — the Job's `backoffLimit: 0` means a whole-pipeline re-run is never sanctioned.
- API keys reach pods via Secrets/env at runtime — never written in manifests.

## CI/CD (GitHub Actions)

Merge gate (`.github/workflows/ci.yml`, required on every PR to `main`): ruff lint/format, mypy, Dockerfile lint (hadolint), image build + smoke test, image CVE scan (trivy), SBOM artifact, secret-leak scan (gitleaks), dependency audit (pip-audit), manifest checks (kubeconform + kube-linter), and the test suites — plus the path-guarded Wave-E gates (core-backend image, dashboard image, Alembic upgrade-from-empty, evals deterministic smoke) that stay green until each service lands, and a Postgres 16 service container the backend suites and migrations run against. Code scanning (`.github/workflows/codeql.yml`) analyzes our Python code weekly and on every PR. **Promotion** (`.github/workflows/promotion.yml`): `main` → `prod` only through it — security gate (gitleaks, pip-audit, manifests, CodeQL, build + trivy of every shipping image), then the founder approves by merging the promotion PR. Dependabot watches pip/docker/actions dependencies. All third-party actions are pinned to commit SHAs; `GITHUB_TOKEN` permissions are least-privilege; CI runs key-free.

Branch protection on `main` (Settings → Branches): require PR + these checks green before merge — configured once in the repo UI.

## Repo Map

| Doc | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Instructions for coding agents working on this repo |
| [`TIMELINE.md`](TIMELINE.md) | Day-by-day build timeline, gates, risks, scope ladder |
| [`docs/DECISIONS-and-RESEARCH/01-gnani-challenge-brief.md`](docs/DECISIONS-and-RESEARCH/01-gnani-challenge-brief.md) | Challenge brief |
| [`docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md`](docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md) | Gnani context, strategy, and "what they need vs what we deliver" |
| [`docs/DECISIONS-and-RESEARCH/03-project-idea-physics-voice-tutor.md`](docs/DECISIONS-and-RESEARCH/03-project-idea-physics-voice-tutor.md) | Product idea (Physics, confirmed scope) |
| [`docs/DECISIONS-and-RESEARCH/04-product-naming-methodology.md`](docs/DECISIONS-and-RESEARCH/04-product-naming-methodology.md) | Brand naming process → **Zivon** |
| [`docs/deployment/`](docs/deployment/) | Docker, Kubernetes, and CI/CD setup; see the folder README for layout and status — incl. the secrets registry (`secrets.md`) and the Wave-E reserved manifest numbering map |
| [`docs/content-factory/`](docs/content-factory/) | Content factory: architecture, config reference, block schema, runbook, source catalog (public PDF sources for classes 6-12 — research + licensing + verification status) |
| [`docs/product/`](docs/product/) | Features document: decided feature list + decision log, feature cards, screen/element/information inventories, traceability matrix, backend handoff for the systems-design stage |
| [`docs/backend/`](docs/backend/) | Stage-2 systems specs (2026-11-07): backend spec (APIs, voice WebSocket contract, guard), database spec (Postgres schema), storage-tiering spec (cache / hot DB / cold provider), capacity & cost model, 16 ADRs |
| [`docs/logs/`](docs/logs/) | Dated session logs (done / not done / next) |
| [`testing/`](testing/README.md) | Test sets: `content_factory/` (unit + end-to-end vs mock inference server + perf harness tool), `translation/` (10a..10d localization + TM + reviewer rules), `frontend/` (site shell + behaviour in Chromium) and `observability/` (the logging_manager contract harness + dashboard tests) |
| [`skills/content-creation/`](skills/content-creation/) | Agent skills for build-in-public posts; see the folder README for layout and rules |
| [`skills/prompting-and-agent-design/`](skills/prompting-and-agent-design/) | The prompting + agent-design skill behind the factory's stage prompts; see the folder README |
| [`skills/code-review/`](skills/code-review/) | Code-review skill suite (entry point + six lenses) used for the agentic review step; see the folder README |
| [`skills/zivon-product-design-skills/`](skills/zivon-product-design-skills/) | Feature-decision + granular-spec method (original skill + vendored PM skills); see the folder README |
| [`skills/zivon-systems-design-skills/`](skills/zivon-systems-design-skills/) | Backend/DB/storage-tiering spec method (original skill + vendored engineering skills); see the folder README |
| [`docs/specs/voice-agent/`](docs/specs/voice-agent/README.md) | Voice-tutor agent architecture spec (wave S1): pipeline, WebSocket contract, latency budget vs Gate C, ADRs 0017–0020, open questions |
| [`docs/specs/translation/`](docs/specs/translation/) | Build-time translation pipeline spec, per-block contracts, reviewer rubric, and translation ADRs (`0021`–`0023`); see the folder README |
| [`docs/specs/observability/`](docs/specs/observability/) | System specs: observability (`logging_manager` API contract, instrumentation map, admin dashboard v0) with ADRs `0024`–`0026` under `docs/backend/adr/`; the implementation lives in `logging_manager/` + `dashboard/`, ops in [`docs/deployment/observability.md`](docs/deployment/observability.md) |
| [`docs/specs/evals/`](docs/specs/evals/) | Evaluation framework spec (`evals/` package, test-to-eval migration map, stage & E2E eval cards, golden sets, regression tracking) |
| [`docs/backend/adr/`](docs/backend/adr/) | Backend and evaluation Architecture Decision Records (ADRs) |
| [`docs/specs/frontend/`](docs/specs/frontend/) | Frontend implementation spec (wave S1): component inventory, state matrix, WS client contract, perf-budget tests, SEO plan |
| [`docs/specs/gaps/`](docs/specs/gaps/) | Gap register + Wave-E assignment (SP6) |

## Engineering Process

- `main` protected; `prod` branch for production; all changes via PR
- Every PR: CI + agentic code review before merge; `main` → `prod` promotion includes security checks
- Kanban maintained daily: public board at <https://trello.com/b/6ae259654bfcaa47ee720df7/zivon>
- Public build-in-public posts on X / LinkedIn throughout the build
- For those posts, use the skills in [`skills/content-creation/`](skills/content-creation/); **Kinocut MCP** (video) and **GIMP MCP** (images) are the decided editing tools. The folder README holds the layout and rules

## Built on Gnani's Models

Zivon is built entirely on Gnani AI's sovereign stack — **Prisma v3.0, Gemma 4 26B A4B, and Timbre v3.0** — Indian models for Indian learners, for the **Great Indian AI Internship Challenge**.

`#GreatIndianAIInternshipChallenge` `#GnaniAI`

## License

TBD (MIT planned before repo goes public).
