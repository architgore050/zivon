# Zivon

**A voice-first AI tutor Indian students can actually talk to.**

**Status: post-challenge startup track (since 2026-11-15).** Zivon began as a
**Great Indian AI Internship Challenge** entry; it is now a startup build with no external
deadline. The current milestone is a **working prototype for product-market-fit testing** —
Class 9/10 Physics content complete, live lessons in English/Hindi/Hinglish, and the full
consumer frontend. Milestone, wave order, and the definition of done live in
[`TIMELINE.md`](TIMELINE.md) and [`AGENTS.md`](AGENTS.md).

The voice loop (current stack by choice, revisable by founder decision — see "Current stack" in
[`AGENTS.md`](AGENTS.md)):

> Student speaks (Hindi / English / Hinglish) → **Prisma v3.0** listens → **Gemma 4 26B A4B**
> (via the Gemini API) reasons → **Timbre v3.0** speaks back.

Build-time content generation runs on **DeepSeek V4.1 Flash** through the OpenCode API;
translation uses **Gnani Evon**.

**Focus:** academic Physics, Class 9–12 — taught through interactive animations, simulations, and diagrams, with a patient spoken Hinglish tutor anchored to every page.

---

## Status

🚧 **In active build — startup track, no external deadline.** Current milestone: the working
prototype for product-market-fit testing. Wave order and exit gates: [`TIMELINE.md`](TIMELINE.md);
the definition of done: [`AGENTS.md`](AGENTS.md).

- **Challenge-demo link (historical):** <https://advertisers-sunshine-rendered-sheet.trycloudflare.com>
  — a demo-grade Cloudflare quick tunnel used for the challenge submission, run as the user
  service `zivon-tunnel`. It may be offline now; a durable deployment is tracked in `TIMELINE.md`.
- **Scope source:** the frozen full-frontend plan (2026-11-13) is workspace-local
  (`tmp/full-frontend/FEATURE-MAP.md` + `REQUIREMENTS.md`, gitignored and deliberately not
  committed). Its committed restatement is [`docs/product/`](docs/product/) +
  [`docs/specs/frontend/`](docs/specs/frontend/) + `skills/zivon-frontend-product-skills/`.
- **Compliance:** exam-paper use is gated by the `docs/compliance/` memo (C0, 2026-11-15) —
  nothing is ingested, reproduced, or published before it lands.

**Honest status of the voice loop (challenge demo, 2026-11-10).** The full loop has been run
live on the public URL: Prisma v3.0 transcribes a Hinglish doubt, the reasoning model answers, and
Timbre v3.0 returns the tutor's speech — measured **2.98 s** from end-of-speech to first
audio, inside the 4 s Gate C bar, with the answer audio captured. The in-page voice dock
(**design-doctrine §10.12**, DCR-002 closed) does the full press-and-hold loop: permission on
first press, `MediaStreamSource` -> `ScriptProcessorNode` capture, 16 kHz mono PCM16 LE
frames on the `ws-contract §3` wire format, `audio.end` on release, and the track stopped
with the processor; Web Audio API PCM16 48 kHz downlink playback; per-block read-aloud
(**§10.13**, rendered when `manifest.json` carries narration assets, with working
loading/error/offline states); one-time consent gate (**§10.14**, first-visit bottom sheet)
+ `/privacy/` summary (`SCR-PRIV-01`, same-origin CSP scoped to that page, honest
wipe-failure copy); provenance report form (`POST /v1/reports`), credit/offline notices,
consent-gated `ZivonEvents` telemetry (`POST /api/v1/events`, flushed on pagehide and queue
pressure), and locale availability chips (`F-WRP-LAN-01`, English enabled; other locales
disabled with honest title until a `pipeline.py --locales` content run lands) are shipped
via the content-first shell injection kit (`ZivonShell.mount()`).

**Recorded model deviation.** Gate A selected **Gemma 4 26B A4B** as the runtime brain.
Measured on the Gemini API on 2026-11-10, it thinks for ~20 s before its first content
token and rejects `thinking_budget`/`thinking_level`, so it cannot meet a real-time voice
turn today. The challenge demo therefore ran **`gemini-2.5-flash` with thinking disabled** via
deployment config; Gemma 4 remains the code default and a one-env-var switch. This is a
documented deviation, not a silent swap (`docs/specs/voice-agent/open-questions.md` OQ-04).

**Data handling, stated plainly.** Audio is not retained by Zivon; transcripts are
short-lived (7-day TTL). Gnani-side audio retention for Prisma/Timbre is **not yet
confirmed** (counsel question Q-V1), and the device pseudonym is created before an explicit
consent gesture (DPDP review pending). Cold backup is **simulated** — RPO is the last base
backup, not a continuously replicated store.

---

## What It Does

1. A multi-agent **content factory** curates official NCERT / public-domain material and synthesizes it into interactive learning pages — each page pairs clear text with generated **animations, interactive simulations, and diagrams**, reviewed for factual accuracy and first-time-learner clarity.
2. Students (validated with real kid testers) learn from these pages on the live site.
3. On any page, the student can press the mic and ask a doubt **out loud, in Hinglish**. The tutor knows what's on the screen, explains step by step, narrates interactions with the simulation, asks Socratic follow-up questions, and answers in natural Indian-accented voice with expressive prosody.
4. A staff-only **admin cockpit** (`/admin/*`, ADR-0026 token auth) runs the operation: factory-run/test trigger buttons, credit burn, voice latency, errors, publish status, and the F10 product panels — content coverage, question-bank health, series/blueprint status, content-quality debt, users delete/export support, the report inbox, feature flags, and eval results — aggregate-only, no student free text or PII on any panel (`docs/specs/frontend/admin.md`).

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

- **Voice loop (current stack by choice):** Gnani **Prisma** + **Timbre** for speech I/O, **Gemma 4 26B A4B** (Gemini API) for reasoning. **Translation (build-time):** Gnani **Evon**. **Content generation (build-time):** **DeepSeek V4.1 Flash** via the OpenCode API. `AGENTS.md` carries the routing table and the rule that a change is a recorded founder decision.
- **Content factory** is build-time tooling (`pipeline.py` + `factory/`) that runs on any OpenAI-format model endpoint — all model calls go through the standalone **`llm_manager/`** module (streaming transport, honest inactivity timeouts, a per-call wall-clock deadline), which also ships as an isolated **llm-manager node** (own image + K8s Deployment/Service) that every consumer talks to. Server wiring via environment variables, pipeline behaviour via `config.json` (see `.env.example`). The build-time path and the tutor path are deliberately separate: the factory talks to the OpenCode/DeepSeek endpoint through `llm_manager`, the tutor talks to the Gemini API, and neither shares the other's credentials.

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

Practice items and speak-back rubrics are a **separate** entrypoint (they never run inside a lesson run):

```bash
python -m factory.assessment --list-chapters
python -m factory.assessment --chapter class-9-describing-motion-around-us \
    --chapter class-10-light-reflection-and-refraction
```

The default `--generator seed` is key-free (tracked curated banks); live generation uses the same `llm_manager` endpoint with `--generator llm`. Contract: [`docs/content-factory/assessment.md`](docs/content-factory/assessment.md).

Every run keeps full evidence (requests, responses, retries, reports) under `runs/` (assessment runs under `runs/assessment/`). Tests: `python -m unittest discover -s testing/content_factory/unit -t .` and `python -m unittest discover -s testing/content_factory/assessment -t .` — see `testing/README.md` and `docs/content-factory/runbook.md`. The cluster also runs the full suite on a schedule (CronJob `test-suite`); trigger it on demand with `kubectl create job --from=cronjob/test-suite <name> -n zivon` — the standing "button" until the admin dashboard exists (see `docs/deployment/cicd.md`).

## Tech Stack

| Layer | Choice |
|---|---|
| STT | Gnani **Prisma v3.0** (streaming, code-mixed, noisy-audio strong) |
| Tutor LLM | **Gemma 4 26B A4B** via the Gemini API (current choice; a recorded deployment may run another model) |
| TTS | Gnani **Timbre v3.0** (streaming, expressive tags) |
| Content generation (build-time) | **DeepSeek V4.1 Flash** via the OpenCode API, through `llm_manager` |
| Translation (build-time) | Gnani **Evon** |
| Backend | Python — FastAPI + WebSockets |
| Frontend | Web UI with mic; static interactive pages (canvas/SVG) |
| Infra | Docker containers, Kubernetes, CI/CD, staging → prod |

## Running with Docker

The content factory ships as a container image (`Dockerfile` at the repo root):

```bash
docker build -t zivon-factory:0.3.17 .
docker build -f Dockerfile.llm-manager -t zivon-llm-manager:0.1.0 .   # the model-call node (slim, no torch)
docker build -f Dockerfile.dashboard -t zivon-dashboard:0.1.0 .       # the admin dashboard (slim + kubectl)
docker build -f Dockerfile.backend -t zivon-backend:0.1.0 .           # core backend monolith (FastAPI + DB + guard)
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
docker compose --profile dev-stack run --rm evals-runner  # deterministic eval smoke (profile-gated; backend+postgres run non-profiled: `docker compose up -d backend`); the dashboard keeps its own `docker compose up -d dashboard` (:8082)
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
scripts/trigger-evals.sh                  # manual evaluation & reviewer-calibration run
scripts/trigger-factory-run.sh "Motion" 9 # one generation run (same topic+class RESUMES; add --fresh to force clean generation)
scripts/logs-factory-run.sh               # follow the latest run's logs (no job name needed)
scripts/publish-frontend.sh               # mirror courses/ + catalogue.json + courses.js into frontend/, run the P5 integrity gates, regenerate sitemap.xml/robots.txt
scripts/publish-frontend.sh --dry-run --source-dir <tree>   # validate a staging tree without touching frontend/
python3 -m factory.catalogue check --frontend-dir frontend --strict   # catalogue/version/locale/hook/SEO smoke
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
| [`TIMELINE.md`](TIMELINE.md) | Startup-track status, milestone + wave order; the preserved challenge timeline, gates, risks, and scope ladder; the live infra TODO and dated execution log |
| [`docs/DECISIONS-and-RESEARCH/01-gnani-challenge-brief.md`](docs/DECISIONS-and-RESEARCH/01-gnani-challenge-brief.md) | Challenge brief |
| [`docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md`](docs/DECISIONS-and-RESEARCH/02-all-about-gnani.md) | Gnani context, strategy, and "what they need vs what we deliver" |
| [`docs/DECISIONS-and-RESEARCH/03-project-idea-physics-voice-tutor.md`](docs/DECISIONS-and-RESEARCH/03-project-idea-physics-voice-tutor.md) | Product idea (Physics, confirmed scope) |
| [`docs/DECISIONS-and-RESEARCH/04-product-naming-methodology.md`](docs/DECISIONS-and-RESEARCH/04-product-naming-methodology.md) | Brand naming process → **Zivon** |
| [`docs/deployment/`](docs/deployment/) | Docker, Kubernetes, and CI/CD setup; see the folder README for layout and status — incl. the secrets registry (`secrets.md`) and the Wave-E reserved manifest numbering map |
| [`docs/content-factory/`](docs/content-factory/) | Content factory: architecture, config reference, block schema, runbook, source catalog (public PDF sources for classes 6-12 — research + licensing + verification status), and the separate assessment pipeline ([`assessment.md`](docs/content-factory/assessment.md): practice items, speaking rubrics, concept tagging, time priors, export pack) |
| [`docs/product/`](docs/product/) | Features document: decided feature list + decision log, feature cards, screen/element/information inventories, traceability matrix, backend handoff for the systems-design stage |
| Full-frontend plan (frozen 2026-11-13) | Workspace-local `tmp/full-frontend/FEATURE-MAP.md` + `REQUIREMENTS.md` — gitignored and deliberately not committed: locked product decisions, R1/R1.5/R2 scope, routes, screens, states, workstreams. Committed restatement: `docs/product/`, `docs/specs/frontend/`, `skills/zivon-frontend-product-skills/` |
| `docs/compliance/` (C0, 2026-11-15) | Compliance research memo for exam-paper use — copyright/CBSE terms, educational-use boundaries, the exact user-facing notice copy, and counsel-review flags. Lands with the C0 agent; nothing past-paper is ingested, reproduced, or published before it |
| [`docs/backend/`](docs/backend/) | Stage-2 systems specs (2026-11-07): backend spec (APIs, voice WebSocket contract, guard), database spec (Postgres schema), storage-tiering spec (cache / hot DB / cold provider), capacity & cost model, 16 ADRs |
| [`docs/logs/`](docs/logs/) | Dated session logs (done / not done / next) |
| [`testing/`](testing/README.md) | Test sets: `content_factory/` (unit + assessment-pipeline suite + end-to-end vs mock inference server + perf harness tool), `translation/` (10a..10d localization + TM + reviewer rules), `frontend/` (site shell, behaviour, voice-client state machine and low-end-Android perf budgets in Chromium), `observability/` (the logging_manager contract harness + dashboard tests, including the F10 admin-panel contract suite), `evals/` (unit + calibration tests for the evaluation framework), `backend/` (REST/admin contracts, credit guard concurrency, consent/wipe cascade, TTL, HMAC abuse, Alembic migrations), and `voice/` (voice-loop units on mocked Prisma/brain/Timbre seams — no network, no keys) |
| `evals/` | Evaluation & reviewer-calibration framework: 16 Eval Cards (`evals/cards/EV-*.yaml`, including the four `EV-ASM-*` assessment cards), 4 Golden Topics + 2 assessment goldens, 19 reviewer-calibration Seeded Defects + 6 assessment defects, deterministic checkers, `llm_manager` judges (`ADR-0028`), dual-write store (`ADR-0027`), and CLI (`python -m evals`) |
| [`skills/content-creation/`](skills/content-creation/) | Agent skills for build-in-public posts; see the folder README for layout and rules |
| [`skills/prompting-and-agent-design/`](skills/prompting-and-agent-design/) | The prompting + agent-design skill behind the factory's stage prompts; see the folder README |
| [`skills/code-review/`](skills/code-review/) | Code-review skill suite (entry point + seven lenses) used for the agentic review step; see the folder README |
| [`skills/zivon-product-design-skills/`](skills/zivon-product-design-skills/) | Feature-decision + granular-spec method (original skill + vendored PM skills); see the folder README |
| [`skills/zivon-systems-design-skills/`](skills/zivon-systems-design-skills/) | Backend/DB/storage-tiering spec method (original skill + vendored engineering skills); see the folder README |
| [`skills/zivon-frontend-product-skills/`](skills/zivon-frontend-product-skills/) | Full-frontend implementation entry point: public/static pages, generated lessons, SSR app/auth/admin, 11-state matrix, a11y/perf/SEO, and the founder visual-verdict protocol; `skills/zivon-frontend-skills/` stays the SEO reference |
| [`skills/skill-creation/`](skills/skill-creation/) | Find/evaluate/adapt/write/test/maintain skills for any domain: tested discovery toolkit, dated source catalog, rubric, security/licensing review, and a stdlib bundle validator |
| [`skills/zivon-pipeline-engineering-skills/`](skills/zivon-pipeline-engineering-skills/) | Content-factory engineering skill: stage contracts `00`–`12`, artifacts/resume, gate/catcher design, schemas, rendering/publishing, quality/evals, and logging; see the folder README |
| [`skills/zivon-evals-and-observability-skills/`](skills/zivon-evals-and-observability-skills/) | Logging + evaluation entry point: events and the instrumentation map, eval cards/checkers/goldens/judges, dual-write store, curation front, and the review bar; see the folder README |
| [`docs/specs/voice-agent/`](docs/specs/voice-agent/README.md) | Voice-tutor agent architecture spec (wave S1): pipeline, WebSocket contract, latency budget vs Gate C, ADRs 0017–0020, open questions |
| `voice/` | The vocal tutor runtime package (built by EX1-VOICE per the spec): Prisma STT → Gemma brain (Gemini API) → sentence chunker → Timbre TTS, streamed end-to-end; mounts into the core backend via `voice.mount_voice(app)`; tests in `testing/voice/` |
| [`docs/specs/translation/`](docs/specs/translation/) | Build-time translation pipeline spec, per-block contracts, reviewer rubric, and translation ADRs (`0021`–`0023`); see the folder README |
| [`docs/specs/observability/`](docs/specs/observability/) | System specs: observability (`logging_manager` API contract, instrumentation map, admin dashboard v0) with ADRs `0024`–`0026` under `docs/backend/adr/`; the implementation lives in `logging_manager/` + `dashboard/`, ops in [`docs/deployment/observability.md`](docs/deployment/observability.md); the F10 admin panels' route/state/privacy contract is [`docs/specs/frontend/admin.md`](docs/specs/frontend/admin.md) |
| [`docs/specs/evals/`](docs/specs/evals/) | Evaluation framework spec (`evals/` package, test-to-eval migration map, stage & E2E eval cards, golden sets, regression tracking) |
| [`docs/backend/adr/`](docs/backend/adr/) | Backend and evaluation Architecture Decision Records (ADRs) |
| [`docs/specs/frontend/`](docs/specs/frontend/) | Frontend implementation spec (wave S1): component inventory, state matrix, WS client contract, perf-budget tests, SEO plan |
| [`docs/specs/personalized-learning/`](docs/specs/personalized-learning/README.md) | Personalized learning + interactive artifacts (W5.5, 2026-11-17): login-required teach → check → adapt loop, account-level personal instructions, saved conversations, sandboxed generated artifacts, free-tier quotas, threat model, `EV-PL-001…005`, PL1–PL5 workstreams, open founder decisions, and the feature addendum that extends `docs/product/features.md` |
| [`docs/specs/gaps/`](docs/specs/gaps/) | Gap register + Wave-E assignment (SP6) |

## Engineering Process

- `main` protected; `prod` branch for production; all changes via PR
- Every PR: CI + agentic code review before merge; `main` → `prod` promotion includes security checks
- Kanban maintained daily: public board at <https://trello.com/b/6ae259654bfcaa47ee720df7/zivon>
- Public build-in-public posts on X / LinkedIn throughout the build
- For those posts, use the skills in [`skills/content-creation/`](skills/content-creation/); **Kinocut MCP** (video) and **GIMP MCP** (images) are the decided editing tools. The folder README holds the layout and rules

## Voice Stack and History

Zivon's voice loop runs on Gnani's stack — **Prisma v3.0** (STT) and **Timbre v3.0** (TTS) —
plus **Gemma 4 26B A4B** for reasoning. Gnani is the current vendor **by choice**: its models
are strong on Indian languages and code-mixed speech, not because a challenge rule requires
them. Translation uses Gnani Evon; build-time content generation uses DeepSeek V4.1 Flash.
See "Current stack" in [`AGENTS.md`](AGENTS.md) for the routing table and the change rule.

**History.** Zivon was built for the **Great Indian AI Internship Challenge** by Gnani AI
(`#GreatIndianAIInternshipChallenge` `#GnaniAI`). That track closed on 2026-11-15; the plan,
decision gates, and build-in-public posts are preserved as written in
[`TIMELINE.md`](TIMELINE.md), [`docs/logs/`](docs/logs/), and
[`docs/DECISIONS-and-RESEARCH/`](docs/DECISIONS-and-RESEARCH/).

## License

TBD (MIT planned before repo goes public).
