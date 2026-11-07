# Repo facts and constraints that bind the systems design

Snapshot from the repo at 7 Nov 2026 (`architgore050/zivon`). Re-read the source docs; they may have moved. Do not contradict; propose changes explicitly.

## Fixed decisions
- **Backend language/framework**: Python, FastAPI + WebSockets; typed; small modules; config via env vars; basic logging from day one (`AGENTS.md`).
- **Voice loop**: Gnani Prisma v2.5 (STT) and Timbre v2.5 (TTS) are non-negotiable; Evon v3.3 is the intended brain, a fallback LLM only via Gate A. LiveKit (`livekit-plugins-gnani`) is an allowed option if it reduces complexity.
- **Architecture**: hybrid - static curated content + on-demand anchored doubt tutor (Day-5 decision, recommended in `TIMELINE.md`).
- **Infra**: Docker + Kubernetes + GitHub Actions + GHCR; local minikube; voice backend = Deployment + Service; content factory = manual-trigger Job; frontend = nginx Deployment over a PVC; TLS terminates at the edge only (locked 2026-11-04); hosting provider still open.
- **Existing volumes**: PVC `zivon-sources` (content-factory `runs/`, caches; subPath `runs`), PVC `zivon-frontend` (generated site, served by nginx), `hf-cache` PVC. `scripts/publish-frontend.sh` mirrors the generated site into the repo's `frontend/` (git history = version rotation).
- **Secrets**: runtime-only (env/K8s Secrets); never in images, manifests, workflows; CI is key-free.
- **Branching/CI**: PR → CI → agentic review → merge; `main` → `prod` via promotion pipeline.
- **Content constraints**: lesson pages are generated, self-contained HTML/JS/SVG; no `eval`, no external calls, accessible; block schema v1 frozen (`docs/content-factory/blocks-schema.md`).
- **Credits**: Gnani programme credits are limited (5,000 per registrant); log usage daily; reserve ~40 % for demo day/judge traffic.
- **Monitoring (decided, Phase 3)**: Prometheus + Grafana (`kube-prometheus-stack`), admin-authed; Loki = P2.

## Things that are NOT in the repo yet (so the design must propose them)
No database, no object storage, no cold storage, no accounts/identity, no consent system, no event pipeline, no voice backend image. The repo says "avoid over-engineering authentication, databases... early" and "session memory: in-memory/lightweight for MVP", and lists "accounts/billing, multi-user auth" as explicitly out of scope. The user has now asked for a backend spec, a DB spec and a cold-storage separation: deliver the **target architecture with a phased path** and say clearly what P0 actually needs versus what is post-challenge.

## Time context
Challenge deadline: **10 Nov 2026, 11:59 PM IST** (internal target: public by 12:00 PM that day). Feature freeze (Gate D) was Day 8. These specs are therefore primarily the **post-challenge production roadmap** unless the founder states otherwise; mark each element P0/P1/P2/post-challenge and keep P0 identical to the repo's ladder.

## Legal/regulatory context to carry (secondary sources; not legal advice)
DPDP Act 2023 + DPDP Rules 2025 (notified mid-Nov 2025): verifiable guardian consent for under-18s; no tracking/behavioural monitoring/targeted ads directed at children (narrow purpose-based exemptions); breach notice to the Board within 72 h; response windows for rights requests; most duties from ≈ 14 May 2027. Whether Zivon qualifies for any exemption is a legal question. Cross-border transfer rules and any restricted-country list: verify. These shape retention, tiering regions and the sub-processor list.

## Naming and layout suggestions (follow the repo style)
Backend code under a new top-level package (e.g. `voice/` or `backend/`), separate from `factory/`; docs under `docs/` with the map in `AGENTS.md` kept current (add `docs/backend/` and `docs/data/` if introduced - update the AGENTS.md layout in the same PR); ADRs in `docs/decisions/`.
