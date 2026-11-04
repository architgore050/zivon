# Zivon

**A voice-first AI tutor Indian students can actually talk to.**

Built for the **Great Indian AI Internship Challenge** (Gnani AI) on Gnani's sovereign stack:

> Student speaks (Hindi / English / Hinglish) → **Prisma v2.5** listens → **Evon v3.3** reasons → **Timbre v2.5** speaks back.

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
  🎤 mic ─→ Prisma v2.5 ─→ Evon v3.3 ─→ Timbre v2.5 ─→ 🔊 tutor voice
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

- **Product runtime** runs on the Gnani stack (Prisma + Timbre; Evon as the intended reasoning brain).
- **Content factory** is build-time tooling (`pipeline.py` + `factory/`) that runs on any local OpenAI-format model — server wiring via environment variables, pipeline behaviour via `config.json` (see `.env.example`). Build-time models are a deliberate choice (see TIMELINE.md, guiding rule 4); the product runtime stays Gnani.

## Run the content factory

```bash
pip install -r requirements.txt
python -m playwright install chromium      # once, for the perf gate
# server settings come from the environment (never from files):
export ZIVON_BASE_URL=http://127.0.0.1:8080/v1     # your inference server (host loopback is fine HERE)
export ZIVON_MODEL=qwen3.8-flash-next-iq3_xxs      # exactly as GET /v1/models reports
python pipeline.py "Motion" --class 9
```

Run ids are deterministic per (chapter, class): re-running the same command **resumes** the previous attempt — completed stages load from `runs/` instead of re-calling the model; pass `--fresh` to wipe the attempt and generate clean.

Running the factory **in a container or on the cluster** instead? Those can never see a host's loopback — start the inference router (`docker compose up -d inference-router`) and use `ZIVON_BASE_URL=http://192.168.49.1:18080/v1` (see [`docs/deployment/kubernetes.md`](docs/deployment/kubernetes.md)).

Every run keeps full evidence (requests, responses, retries, reports) under `runs/`. Tests: `python -m unittest discover -s testing/content_factory/unit -t .` — see `testing/README.md` and `docs/content-factory/runbook.md`. The cluster also runs the full suite on a schedule (CronJob `test-suite`); trigger it on demand with `kubectl create job --from=cronjob/test-suite <name> -n zivon` — the standing "button" until the admin dashboard exists (see `docs/deployment/cicd.md`).

## Tech Stack

| Layer | Choice |
|---|---|
| STT | Gnani **Prisma v2.5** (streaming, code-mixed, noisy-audio strong) |
| LLM | Gnani **Evon v3.3** (open-weight, self-hosted) |
| TTS | Gnani **Timbre v2.5** (streaming, expressive tags) |
| Backend | Python — FastAPI + WebSockets |
| Frontend | Web UI with mic; static interactive pages (canvas/SVG) |
| Infra | Docker containers, Kubernetes, CI/CD, staging → prod |

## Running with Docker

The content factory ships as a container image (`Dockerfile` at the repo root):

```bash
docker build -t zivon-factory:0.3.7 .
docker run --rm zivon-factory:0.3.7                          # environment smoke test
docker compose run --rm factory python pipeline.py "Motion" --class 9   # full pipeline run
docker compose up web                                        # serve frontend/ on http://localhost:8081
```

- API keys are passed via environment variables (`ZIVON_API_KEY`) — never baked into the image.
- `runs/`, PDF/text caches, and the HuggingFace model cache are mounted as volumes, so containers stay disposable and caches survive between runs.
- `docker-compose.yml` is the local dev runner; Kubernetes manifests come with the deployment setup.

## Kubernetes (local cluster)

Manifests live in `k8s/` (numeric prefix = apply order); `k8s/infra.env` is the single source of truth for cluster config values (test cadence, inference server URL, model). Local cluster is minikube with the docker driver:

```bash
minikube start --driver=docker
minikube image load zivon-factory:0.3.7   # minikube has its own container store
scripts/apply-k8s.sh                      # ConfigMap + all manifests + rendered CronJob + startup test run
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

Merge gate (`.github/workflows/ci.yml`, required on every PR to `main`): ruff lint/format, mypy, Dockerfile lint (hadolint), image build + smoke test, image CVE scan (trivy), SBOM artifact, secret-leak scan (gitleaks), dependency audit (pip-audit), manifest checks (kubeconform + kube-linter). Code scanning (`.github/workflows/codeql.yml`) analyzes our Python code weekly and on every PR. Dependabot watches pip/docker/actions dependencies. All third-party actions are pinned to commit SHAs; `GITHUB_TOKEN` permissions are least-privilege.

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
| [`docs/deployment/`](docs/deployment/) | Docker, Kubernetes, and CI/CD setup; see the folder README for layout and status |
| [`docs/content-factory/`](docs/content-factory/) | Content factory: architecture, config reference, block schema, runbook, source catalog (public PDF sources for classes 6-12 — research + licensing + verification status) |
| [`docs/logs/`](docs/logs/) | Dated session logs (done / not done / next) |
| [`testing/`](testing/README.md) | Test sets: `content_factory/` (unit + end-to-end vs mock inference server + perf harness tool) and `frontend/` (site shell + behaviour in Chromium) |
| [`skills/content-creation/`](skills/content-creation/) | Agent skills for build-in-public posts; see the folder README for layout and rules |
| [`skills/prompting-and-agent-design/`](skills/prompting-and-agent-design/) | The prompting + agent-design skill behind the factory's stage prompts; see the folder README |

## Engineering Process

- `main` protected; `prod` branch for production; all changes via PR
- Every PR: CI + agentic code review before merge; `main` → `prod` promotion includes security checks
- Kanban maintained daily: public board at <https://trello.com/b/6ae259654bfcaa47ee720df7/zivon>
- Public build-in-public posts on X / LinkedIn throughout the build
- For those posts, use the skills in [`skills/content-creation/`](skills/content-creation/); **Kinocut MCP** (video) and **GIMP MCP** (images) are the decided editing tools. The folder README holds the layout and rules

## Built on Gnani's Models

Zivon is built entirely on Gnani AI's sovereign stack — **Prisma v2.5, Evon v3.3, and Timbre v2.5** — Indian models for Indian learners, for the **Great Indian AI Internship Challenge**.

`#GreatIndianAIInternshipChallenge` `#GnaniAI`

## License

TBD (MIT planned before repo goes public).
