# Build Timeline: Oct 29 → Nov 10, 2026

## Reality Snapshot

| Item | Value |
|---|---|
| Start | Thu 29 Oct 2026 (Day 0) |
| Hard deadline | **Tue 10 Nov 2026, 11:59 PM IST** — no extensions |
| Build time | ~12.5 days |
| Internal submission target | Everything public by **10 Nov, 12:00 PM IST** (12h safety buffer) |
| Working assumption | Team of 2 (founder + teammate) + agent workforce, full-time crunch, weekends included |

This is an ambitious plan compressed into 12 days. The timeline is built so that **the demo is never at risk**: every phase has a gate, every "Netflix-level" ambition is time-boxed to a minimum credible version, and there is an explicit scope ladder (P0 / P1 / P2) so cuts happen deliberately, not by panic on Day 11.

---

## Guiding Rules

1. **Demo safety first.** A working 60-second demo beats a half-broken feature set. No phase is allowed to jeopardize Day 10–12 submission work.
2. **Gates, not vibes.** Each phase ends with a measurable acceptance test. If a gate fails, we fix or cut — decided at the gate, not later.
3. **Content is the product; voice is the interface.** Phase 1 proves the teaching fundamentals before any agent touches a student.
4. **Build-time vs runtime models.** The content factory (build-time tooling) may use any model/agent. The **product runtime** must run on the Gnani stack (Prisma + Timbre, Evon as the intended brain). This distinction matters for challenge compliance.
5. **Time-box the perfection phases.** Phases 3 and 4 are "minimum credible Netflix-level" passes within the window. The full vision is the post-challenge roadmap, and the README/deck will say so honestly.
6. **Everything flows through the parallel pipeline** (PR → CI → agentic review → main → prod) from Day 0. No exceptions, even during crunch.

---

## Phase → Day Map

| Phase | Core days | Continues / iterates |
|---|---|---|
| Phase 1 — Content factory + kid validation + static pages live | Days 1–4 | Days 5–7 (v2, more topics) |
| Phase 2 — Voice loop + agentic tutor | Days 5–7 | Day 8 polish |
| Phase 3 — Telemetry, logging, security, analytics (minimum credible) | Day 8 | Hygiene from Day 0 via CI/CD |
| Phase 4 — Frontend perfection pass | Day 9 | Day 10 morning polish |
| Phase 5 — Commercial + presentation | Days 10–11 | Day 12 posting |
| Submission | Day 12 | — |
| Parallel pipeline | Every day | — |

---

## Decision Gates

| Gate | When | Question | Pass bar | If it fails |
|---|---|---|---|---|
| **A — Evon quality** | Day 1 EOD → slipped to Day 2 → **rescheduled 1 Nov (founder decision): runs when voice agent work starts (Day 5), not before** — an eval before the brain is needed is a wasted eval; method corrected 31 Oct, see `posts/2026-10-30-day-1.md` | Is Evon v3.3 strong enough as the tutor brain? | Compare **published benchmark data** for Evon vs Gemma 4. Public data proves Evon's competence → Evon is the brain. Public data not enough to prove competence → adopt Gemma 4 as the runtime LLM without spending time or credits testing Evon. | Switch runtime LLM to Gemma 4 (or latest). Prisma + Timbre stay regardless — challenge only requires ≥1 Gnani model, and we already use two. Goal remains all three. |
| **B — Kid comprehension** | Day 4 EOD | Do kids actually learn from generated pages? | ≥2 of 3 kids restate the concept in their own words + answer 2 follow-ups; at least one handles a topic one class above their level | Do NOT proceed to voice-on-content integration. Fix the content skill first; voice loop core can still proceed in parallel. |
| **C — Voice latency** | Day 6 EOD | Is the voice loop fast enough to feel human? | < ~4s from end-of-speech to first spoken audio, streaming end-to-end | Reduce tutor reply length, pre-warm models, tighten streaming; if still failing, demo uses the hybrid mode (static content + on-demand tutor) with shorter replies. |
| **D — Feature freeze** | Day 8 EOD | What ships? | Explicit P0/P1/P2 list signed off | Anything not on the list is cut, documented, and moved to post-challenge roadmap. |

---

## Day-by-Day Plan

### Day 0 — Thu 29 Oct — Foundations

- **Kanban**: GitHub Projects board — Backlog / Doing / Review / Done / Blocked, swim lanes per phase. Groomed every morning (15 min).
- **Repo process**: real `.gitignore`, branch model (`main` protected, `prod` for production, `feature/*` branches), PR template, CI skeleton (lint / typecheck / build / test on every PR), agentic code-review workflow set up.
- **Domain decision (from doc 03)**: final call on Zivon vs backups. Purchase + DNS + social handles. Hosting accounts: static (Cloudflare Pages / Vercel) + backend (Fly.io / Render / VPS).
- **Gnani setup**: dashboard API keys, read credit pricing, estimate cost per STT minute / TTS character, set a usage budget, **reserve ~40% of the 5,000 credits** for demo day + judge usage on the live link.
- **Evon prep starts**: request/download weights, read the technical report, price GPU options (RunPod / Modal / HF / local quantized).
- **Line up kid testers**: 2–3 kids identified (family/neighbors), parental consent sorted, recording permission (doubles as demo footage).
- **Pick 3 test topics**: one at kid level, one at their class, one above — e.g. Class 9 *Motion* (NCERT Ch. 8), Class 10 *Light: Reflection*, Class 11 *Kinematics*.
- **Social post #1**: "Build starts today" with both hashtags.

**Done when**: repo + board + domain + keys live; topic list fixed; kids confirmed.

### Day 1 — Fri 30 Oct — Gate A + content factory design

- **Gate A (Evon)**: compare published benchmark data for Evon vs Gemma 4 (method corrected 31 Oct — see the
  Gate A row above). Record the decision in writing.
- **Content factory design**: freeze the agent roles and handoff contract:
  1. **Curator** — pulls official NCERT text + public-domain references; outputs a cited source pack. *(Licensing rule: NCERT and public-domain only; no scraping copyrighted textbooks.)*
  2. **Synthesizer** — turns the source pack into learner-facing content with structured JSON blocks declaring what visuals the next agent must build:
     ```json
     { "blocks": [
       { "type": "text", "content": "..." },
       { "type": "animation", "spec": { "behavior": "...", "learning_goal": "..." } },
       { "type": "simulation", "spec": { "interaction": "...", "variables": ["..."] } },
       { "type": "diagram", "spec": { "elements": ["..."] } },
       { "type": "check", "question": "...", "expected_understanding": "..." }
     ]}
     ```
     (JSON blocks instead of `<|tag|>` markup — parseable, reviewable, no delimiter collisions.)
  3. **Visual Builder** — implements animation / simulation / diagram blocks as self-contained HTML/JS (canvas/SVG), no heavy frameworks.
  4. **Performance Engineer** — audits generated code against a performance budget (low-end Android target).
  5. **Comprehension & Fact Reviewer** — checks against the source pack: first-time-learner clarity, hallucination detection, age-appropriate language.
  6. **Code Reviewer** — correctness, safety (no `eval`, no external calls), style, accessibility.
- Build **Curator + Synthesizer**; fully synthesize topic #1.

**Done when**: Gate A decision recorded; schema frozen; one topic fully synthesized with citations.

### Day 2 — Sat 31 Oct — Content factory v1, end-to-end

- Build **Visual Builder** + **Comprehension/Fact Reviewer**.
- Generate the **first complete page** (topic #1) end-to-end: ≥1 animation + ≥1 interactive simulation + ≥1 diagram + comprehension checks.
- Measure the key pipeline metric: **human edit rate** — how many manual edits the page needed. Target trends to zero.

**Done when**: one page goes source → published-quality HTML with zero (or near-zero) manual code edits.

### Day 3 — Sun 1 Nov — Pipeline reliability + staging deploy

- Add **Performance Engineer** + **Code Reviewer** agents to the pipeline.
- Generate topics #2 and #3 **unattended**; log edit rate per topic.
- Device test matrix: low-end Android + mid-range laptop. Budgets: page load < 2s, animations ~60fps, no jank on 4GB-RAM phone.
- **Staging deploy** on the domain (preview subdomain).

**Done when**: 3 pages generated; pipeline reliability measured; staging live.

### Day 4 — Mon 2 Nov — Gate B: kid test round 1 + pages go live

- **Kid sessions** (2–3 kids, consented, recorded): kid explores a page alone; success = restates the concept in their own words + answers 2 follow-up questions. Then test one topic a class above their level.
- Iterate the agents/skills on what you observed — this is the "fundamentals of teaching" gate. This is where the self-improvement loop lives: generate → observe kid → refine prompts/skills → regenerate.
- **Static pages go live on prod** under the chosen domain.

**Done when**: Gate B passed (≥2/3 kids); prod pages live.

### Day 5 — Tue 3 Nov — Voice loop core + Phase 2 architecture decision

- **Gate A runs first** (rescheduled 1 Nov): compare published benchmark data for Evon vs Gemma 4 and record the
  brain decision before building the loop.
- **Voice loop core (CLI first)**: mic → Prisma (streaming STT) → Evon (or Gate A fallback) → Timbre (streaming TTS) → speaker. Log latency per stage from the first run.
- **Phase 2 decision** (record the choice):
  - *Option A — full agent teaches everything*, screen shows only visuals. Maximum personalization, impressive — but token-expensive per learner, latency risk, harder to guarantee pedagogical quality, demo-fragile.
  - *Option B — static curated content + on-demand doubt tutor.* Cheap, reliable, scalable; content quality is guaranteed by the pipeline's own reviewers.
  - **Recommended: hybrid B+.** Static core everywhere; an anchored voice tutor on every page that knows what the student is currently reading, answers doubts in Hinglish, and asks Socratic follow-ups. Keeps the "personalized learning" story while protecting credits and demo reliability.
- Read the **Timbre expressive tag docs** — confirm the exact tag set (whisper, excitement, etc.) the model accepts.

**Done when**: end-to-end voice conversation works in CLI; per-stage latency logged; architecture decision recorded.

### Day 6 — Wed 4 Nov — Voice in the product + expressive TTS

- Web UI: mic button on the live pages; **tutor anchored to the current page/topic** (context-aware answers).
- Interruption/barge-in handling, silence handling, partial-transcript recovery.
- **Prompt-level expressive tag emission** for Timbre (the LLM outputs the tags directly). Fine-tuning is explicitly deferred to P2 — impressive, but off the critical path.
- HTTPS/WSS secure context (required for browser mic access).

**Done when**: Gate C — from a live page, a student asks a doubt in Hinglish and gets a spoken, context-aware answer in < ~4s to first audio.

### Day 7 — Thu 5 Nov — Kid test round 2 + content factory v2

- Kid sessions with voice + pages; iterate the tutor personality prompt (patient, encouraging, step-by-step, Socratic).
- Feed kid feedback back into the content factory; **batch-generate 3–5 more topics** with the zero-manual-edit target.
- Lightweight session memory: current topic + what the student has already covered.

**Done when**: Gate B re-passed with voice; ≥6 topics live; pipeline generates a new topic unattended.

### Day 8 — Fri 6 Nov — Phase 3 minimum credible + Gate D (feature freeze)

- Structured logging (transcripts, per-stage latency, errors), telemetry events, error tracking.
- Security hardening pass: rate limiting, input validation, headers/CSP, secrets audit, dependency scan. Time-boxed red-team mini pass against an OWASP Top-10 checklist.
- **Admin dashboard v0**: sessions, usage, credit consumption, topic engagement. Wire in the two admin trigger buttons per the "Admin trigger commands" table in the Infra & Deployment TODO (tests-now + generate-topic; the scripts stay as the implementation behind the buttons).
- **Cluster monitoring dashboard**: Prometheus + Grafana (`kube-prometheus-stack` Helm chart) — CPU/RAM per pod/node, which workloads/images are running, load; Grafana's own auth is the admin gate. Interim tools in use until then: `kubectl top` (metrics-server) + `docker stats`. Decision locked in `docs/deployment/README.md`; do not build before Day 8.
- main → prod promotion pipeline with automated security checks.
- **Gate D**: sign the ship list (P0/P1/P2 below). Code features stop here.

**Done when**: dashboard shows real session data; cluster monitoring live in Grafana (pods/nodes/resources); security checklist complete; CI/CD green; ship list signed.

### Day 9 — Sat 7 Nov — Phase 4 frontend perfection pass

- Design system: type scale, color tokens, spacing, corner radii, component states. Polish the **exact screens the demo will show** first. Note (2026-11-04): the §10 lesson shell was pulled forward and ported into `zivon.css`/`zivon.js` + `render.py` (hand-stroke SVG pass) — Day 9 keeps the remaining §10 items (two-column page grid, language bar) plus polish.
- Mobile-first responsiveness (primary device: low-end Android), micro-interactions, Devanagari rendering, contrast/accessibility basics.
- Frontend telemetry events (engagement per topic/visual) flowing into the dashboard.

**Done when**: demo-flow screens meet the design bar; telemetry events landing in the dashboard.

### Day 10 — Sun 8 Nov — Phase 5: commercial + deck + rehearsal + code freeze

- Lock the 60-second demo script; shoot and edit the commercial; build the presentation deck.
- Full end-to-end rehearsal, **including a deliberately noisy-audio take** (this is a selling point — film it).
- Load-test the live link.
- **Code freeze** after rehearsal: fixes only.

**Done when**: demo video v1 exists; deck v1 exists; rehearsal passes.

### Day 11 — Mon 9 Nov — Buffer day (non-negotiable)

- Fix everything the rehearsal exposed; re-record the demo if needed.
- README + docs final pass; schedule the final social announcement.
- Submission checklist dry run; verify reserved credits are intact.

**Done when**: checklist 100% green except the actual posting.

### Day 12 — Tue 10 Nov — Submission day

- By **12:00 PM IST**: GitHub public + pinned, live link verified from multiple devices (including a low-end Android), video posted on X **and** LinkedIn with `#GreatIndianAIInternshipChallenge` `#GnaniAI`, posts nominated, final post live.
- Evening stays free for verification and incident response. Do not submit at 11:58 PM.

---

## Parallel Pipeline (every single day, non-negotiable)

- **Social**: ≥1 post on X and/or LinkedIn daily — build-in-public: generated animations, kid-test clips (consented), latency numbers, even failures. Both hashtags, nominated. Professional growth tactics: consistent posting time, reply engagement, clip-first format, thread breakdowns.
- **Kanban**: morning grooming; nothing worked on that isn't on the board.
- **Code flow**: every change via PR → CI → agentic code review → `main`; `main` → `prod` only through the promotion pipeline with security checks.
- **Docs**: README + architecture notes updated in the same PR as the code they describe.
- **Credits**: usage logged daily against the budget.

---

## Infra & Deployment TODO (centralized — the only task list; no separate TODO files live in `docs/`)

Open — work top-down:

- 🔄 **FIRST GENERATION (most important)** — progress 2026-11-03, blocker by blocker: NCERT broken TLS chain fixed (pinned bundle `sources/certs/ncert.nic.in.pem` + polite retried fetches, 0.2.3); OOM at 4 Gi → 8 Gi + reusable text cache (0.2.4); NCERT symbol-font prelims (`U+F0XX` private-use glyphs) decoded in `clean_pdf_text` + stale cached text purged (0.2.5); the two manual-download supplements seeded onto the `zivon-sources` PVC via a helper pod (OpenStax HS Physics 57 MB, Siyavula Gr-10 9.5 MB — both CC BY); 02-synth truncation + read timeouts fixed (0.2.8: model-call limits made effectively non-binding — `ZIVON_MAX_TOKENS=65536` + `ZIVON_TIMEOUT_S=3600` in `k8s/infra.env`, per-stage caps removed; qwen's 5–10k thinking tokens count against `max_tokens`, single-slot local server at worst-case ~20 tok/s; the server clamps completion to remaining context and the Job's 2 h deadline is the backstop). All 11 catalog books ingested and cached. **Run `factory-run-motion-005728` reached 05-check for the first time** (warm ingest 11 s; 02-synth→05-check ≈ 40 min for 4 LLM calls ≈ 10 min each): the fact reviewer rejected the draft — mass/force claims not in the Motion chapter pack (they belong to Ch 9; model priors leaked beyond the cited source). Reviewer worked correctly; the gap is that a late-stage content failure re-runs the whole pipeline (no draft-repair loop). Measured class-9 chapter sizes 19k–62k chars → `max_chars_ncert_to_model` raised 60k → 120k so no chapter is ever truncated (0.2.9); run logs are now label-resolved (`scripts/logs-factory-run.sh`, no job-name guessing). Next: decision made and LANDED (2026-11-03, **graph v2**, pipeline version 3, image 0.3.0): reasoning layer consolidated into ONE giant `02-generate` call carrying the grounding law (the source pack is the page's whole universe; model priors "do NOT count") with the rule checks inside its retry loop; `03-check` recalibrated (honest framing + fixed severity ladder: fatal must quote the source, major = a concept smuggled in from outside the chapter, minor = advisory); catcher routing bounded in-run — `03→04-repair` (≤ `repair.content_rounds`, regenerates flagged blocks only), `09→10-reviewfix` (≤ `repair.code_rounds`), `07→08-fixloop` — a gate failure NEVER re-derives upstream stages (founder rule); runs RESUMABLE via deterministic run id + fingerprint guard + `--fresh`; factory Job `backoffLimit: 0`; `runs/` moved to the `zivon-sources` PVC (subPath `runs`). 198 unit + 7 integration tests green (resume, fingerprint guard, catcher routing covered). Progress 2026-11-04 (image **0.3.1**): the first graph-v2 attempt on 0.3.0 ran but was undiagnosable - the single-slot server legitimately spends 10-50 min on a giant `02-generate` call and nothing printed while it blocked; fixed with an observability layer (stage progress prints + per-stage `elapsed_s` + `stage_durations_s` in the run report; every model call bracketed with start/finish + token counts + a 60 s heartbeat while in flight; rejected attempts print the exact violation being fed back) - silence-vs-thinking is now readable straight from `scripts/logs-factory-run.sh`. The stage prompts were re-evaluated and fixed against the new `skills/prompting-and-agent-design/` skill: `02-generate` is goal-first (goal + success test + "why" motivation, deliverables not execution plans, de-duplicated constraints), `03-check` now receives the LESSON text so "taught before tested" is verifiable, `09-review` lost its "assume at least one defect" framing (honest hunt + `unverified:` minor way-out). Founder decision: the perf gate's load/FCP budgets are LOOSENED (2.0→6.0 s, 1.2→3.5 s) until first real 07-perf measurements exist - RAM/fps/throttle/pin stay founder spec, re-tighten at Phase 4. Cluster Jobs set `HF_HUB_OFFLINE=1` (embedder cached on `zivon-hf-cache` PVC: no HF Hub round-trip at boot). Image 0.3.1 built; kubeconform + kube-linter clean; cluster re-applied: factory-smoke Complete, in-cluster startup suite green (203 unit + 9 frontend + 7 integration), site 200. 203 unit + 9 frontend + 7 integration green locally and in-image. **Next action is the founder's trigger: `scripts/trigger-factory-run.sh "Motion" 9`** (re-triggering "Motion" 9 RESUMES from the `zivon-sources` PVC warm caches in seconds; add `--fresh` to force clean generation; watch via `scripts/logs-factory-run.sh`) - optional cluster tidy-up: `kubectl delete job factory-run-motion-005728 -n zivon`. Success = a generated Physics page appears on http://192.168.49.2:30080.
- ⬜ Branch protection on `main` + required checks (checklist in `docs/deployment/cicd.md`: quality, docker, frontend-image, secrets, deps, manifests, tests, CodeQL).
- ⬜ Publish pipeline: merge → build → push images to `ghcr.io/architgore050/zivon-*`.
- ⬜ Deploy pipeline + hosting decision: real cluster choice, public domain, TLS. (2026-11-04: the HTTPS posture is LOCKED — edge TLS only; pages are already host-agnostic by harness guarantee; the mic-demo secure-context constraint is recorded in `docs/deployment/README.md` Decisions locked. The hosting choice itself stays deliberately open for the hosting stage.)
- ⬜ Voice backend image (FastAPI/WebSockets) + Deployment + Service — Days 5–7 (Phase 2).
- ⬜ Cluster monitoring dashboard (Prometheus + Grafana, admin-authed) — Day 8, per the Day-8 plan and P1 above.
- ⬜ Cleanup stale images: `docker rmi zivon-factory:0.2.0 zivon-factory:0.2.1` + `minikube image rm` the same.

Done (2026-11-05):

- ✅ **Typed page, handwritten accents + frame adaptation** (founder design batch #2 of 4 Nov, factory image **0.3.5** + frontend image **0.1.2**): founder ruling retired handwriting from body text and hand-wobble from visuals ("only the annotations, underlines and titles get handwritten"); doctrine **v1.3** rewrote §10 around that — strict 36 px block rhythm (card padding + border = exactly one ruled row), measured baseline alignment re-fit on load/font-load/resize, a new **Frame adaptation** rule (360 px → laptop, no fixed pixel widths, no horizontal overflow, rules stay under baselines through every resize), clean-geometry law (straight lines, true circles/arcs, one consistent corner style per page), hand-stroke generator surviving **for annotation arrows only**; then compressed twice (prose only, all rules + pinned phrases kept) to 21,820 chars. Shell retyped (`zivon.css`/`zivon.js`: Courier Prime 17/36 body on the rules, Caveat only on titles/labels, sim canvas in a fixed 288 px wrap); `handify_svg` retired from `render.py` (diagrams render verbatim as authored — the guarantee moved to prompts + reviewer + harness: 02-generate clean-geometry diagram language + **Frame law**, 05-interactive 480×320 canvas buffer + clean geometry, 09-review checklist item 6, perf-harness overflow gate failing pages > 2 px past the viewport); both lesson examples converted to v1.3 (live example retyped + true SVG arcs + ARIA radio fix; candidate 2 same treatment, still awaiting founder swap approval); `max_chars_design_context` 64000 → 68000 (measured swap composition 65,821; verified against the inference server's `n_ctx = 262144`). 209 unit + 10 frontend + 7 integration green locally and in-cluster; kubeconform + kube-linter clean; frontend PVC re-seeded per gotcha 14 (host dir survived PV deletion — wiped manually; seeded shell byte-identical); site 200 serving the v1.3 shell. Next: founder views both examples → candidate swap decision → founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` on 0.3.6 → deferred visual tiny-details pass.
- ✅ **Merge gate green + factory image 0.3.6** (2026-11-05): branch pushed; **PR #1** opened (`feature/content-factory-pipeline` → `main`, 91 commits) — the repo's first CI run: 6/8 green on the first try, 2 gate bugs caught and fixed (closes the branch-push item). (1) `frontend-image` smoke curled the bare image — the shell is staged at `/opt/zivon-shell` and the served html root is a volume/PVC in production, so `/` served nginx's default page; CI now stands in for the cluster path: tmpfs root (`uid=101` = the fsGroup stand-in) seeded after the healthz wait with the same `cp -rn` glob copy the seed-shell initContainer uses (gotcha 6). (2) hadolint (threshold `info`) flagged the factory Dockerfile: torch unpinned (DL3013) → pinned `torch==2.15.0+cpu` (the exact wheel 0.3.5 installed; also pinned in the `tests` job so CI tests run the wheel the image ships); `USER app` (DL3066) → `useradd --uid 1000` + `USER 1000` (gotcha 1's fix now lives in the image). Image **0.3.6** built + smoke-tested (26 imports, `pipeline --help`, uid 1000), `minikube image load`, stack re-applied: factory-smoke Complete, in-cluster startup suite green (209 unit + 10 frontend + 7 integration), site 200; kubeconform 9/9 + kube-linter clean. `cicd.md` job table corrected (seven jobs — `tests` was missing). Session log: `docs/logs/2026-11-05-merge-gate-green-and-0-3-6.md`.

Done (2026-11-04):

- ✅ **Run observability layer** (factory, 0.3.1): every stage transition prints a live progress line; measured `elapsed_s` per stage in `status.json`; `stage_durations_s` + `started_at`/`completed_at` in `run_report.json`; every model call bracketed (`model call started` / `finished in Xs (tokens...)`) with a 60 s heartbeat while blocked and visible rejected-retry lines; `attempt meta.json` carries latency, token usage, sampling and payload sizes. A long thinking call is now visibly alive instead of looking hung (the 2026-11-04 stall diagnosis).
- ✅ **New `skills/prompting-and-agent-design/`** (SKILL.md + dated `references/`): current-era prompting + agent-graph rules (goal-first prompts, contracts over coercion, harness-guaranteed guarantees, calibrated reviewer rubrics, errors-as-context, honest reviewer framing) + authoring loop + anti-pattern list; AGENTS.md + README docs map point to it.
- ✅ **Prompts reworked per that skill**: `02-generate` goal-first with motivation + de-duped contracts + end-positioned reread; `03-check` gains the LESSON in its context (verifiable "taught before tested"); `09-review` framing honest + `unverified:` way-out; retry-feedback turns say fix precisely the reported problem and keep valid parts unchanged.
- ✅ **Perf budgets loosened** (founder): `weak-android` load 2.0→6.0 s, FCP 1.2→3.5 s, until first real generated pages are measured; RAM 750 MB / 24 fps / 4x throttle / 2 cores stay founder spec; re-tighten at Phase 4 (architecture.md § Performance budgets).
- ✅ **`HF_HUB_OFFLINE=1`** on the factory Job + test CronJob (embedder on `zivon-hf-cache` PVC). Image 0.3.1 built + cluster re-applied: factory-smoke Complete, in-cluster startup suite green (203 unit + 9 frontend + 7 integration), kubeconform + kube-linter clean, site 200.
- ✅ **Model-call caps removed entirely** (founder decision, 2026-11-04, image 0.3.2): no `max_tokens` is sent on any request; `ZIVON_MAX_TOKENS` retired from config defaults, `infra.env`, the ConfigMap and the docs; the 0.2.8 "huge but non-binding cap" story is superseded - Qwen thinks a lot and then gets things right (measured: 49,750 completion tokens, mostly thinking, on one review call). Backstops now: the server's own context, `ZIVON_TIMEOUT_S`, and the Job's `activeDeadlineSeconds`.
- ✅ **Frontend publish flow** (`scripts/publish-frontend.sh`, founder-run): mirrors the cluster-built `courses/` + `courses.js` from the `zivon-frontend` PVC into the repo's `frontend/` folder - the permanent, standalone-deployable snapshot; the shell stays repo-owned; a re-publish wholesale-replaces a topic's previous version ("delete the previous one when creating the next") with old versions living in git history; pages still never baked into images. First publish brought the live Motion page into the repo. The frontend test set now holds published snapshots to the same contracts (10 tests: catalogue entries resolve ↔ published directories listed; no-external-refs scan covers published files; the empty-state contract moved to synthetic data).
- ✅ **HTTPS posture verified + locked** (hosting-stage prep — no code change was needed): the generated site is already HTTPS-ready by construction. `factory/lint.py` hard-lints absolute AND protocol-relative URLs in every generated-code path (enforced inside 05/06/08/09/10), every page carries the strict CSP (`default-src 'none'`, `'self'` for style/script/img/font, `connect-src 'none'`), the frontend test set re-checks published snapshots in CI — and the Motion page proved clean end-to-end. TLS therefore terminates at the edge at whatever host the hosting stage picks; mic demos need HTTPS or localhost (secure context). Recorded in `docs/deployment/README.md` (Decisions locked) + `docs/deployment/kubernetes.md`.
- ✅ **Design-doctrine enforcement + §10 lesson-shell port** (founder batch, factory image **0.3.3** + frontend image **0.1.1**): (1) doctrine §10.1 gained the founder's **hand-drawn by default** rule — every visual element on a lesson page belongs to the notebook world; the typed layer and palette-token-styled native controls are the only exceptions; (2) factory example context narrowed to the lesson-page example only (`doctrine_examples` → `design-doctrine-lesson*.html`) — the post/brand main example no longer reaches the model, its single-file demo style was bleeding into generated pages; (3) founder rule wired in: everybody who reviews, writes or fixes page code gets the live doctrine + lesson-page example + palette — 09-review gained the example, and 08-fixloop + 10-reviewfix (previously design-blind) gained both with "fix toward the reference, never restyle while repairing" framing; 02-generate/03-check stay doctrine-text-only (they never touch HTML). (4) The Phase-4 §10 shell port was **pulled forward**: `zivon.css` now implements the lesson-page look for topic pages only (36 px ruled rhythm, Caveat 30/36 handwritten body at 46 ch, taped paper cards — torn-end tape, rotation on the tape only — for sim/quiz/reveal, worked examples written on the paper instead of carded, uncarded 288 px diagrams, ✓/✗ feedback carried by shape + words not hue), scoped `:not(.zn-home)` so the landing shell is untouched; `render.py` gained the deterministic **`handify_svg`** pass (port of the example's hand-stroke generator — seeded by block id, byte-identical re-renders, idempotent) rewriting straight `<line>`/`<polyline>`/M-L `<path>` primitives in model diagrams into hand strokes — the guarantee now lives in the harness, not in prompt prose; `zivon.js` gained the example's `fit()` baseline-alignment port (lesson pages sit their text on the ruled lines; the landing never aligns). Verified: 206 unit + 10 frontend + 7 integration green, in-cluster startup suite green on 0.3.3 (`test-startup-180819` Complete), kube gates clean, frontend PVC re-seeded with the new shell (md5-identical to repo) + Motion page restored, site 200 at http://192.168.49.2:30080 serving the §10 CSS. Gotcha 14 recorded (shell updates need a frontend PVC re-seed — including minikube's claim-directory reuse + Released-PV cleanup). Remaining Day-9 §10 items: two-column page grid + language bar. Next: founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` — the regenerated page is the test of this whole batch.
- ✅ **Coverage contract + example framing + example lesson page 2** (founder follow-up batch, factory image **0.3.4**): diagnosed why the regenerated Motion page "taught only the basics" — ingestion was **complete** (`ncert_text_truncated: False`, all 22 pages / 57.5k chars incl. all 16 exercises; the truncation hypothesis rejected — the model saw the whole chapter). Root causes: (1) `02-generate`'s prompt implicitly capped the page (3–6 sections, 8–20 claims, "at least 3" checks, worked_example told the model "do not compute new figures" → every NCERT numerical was impossible → all exercises skipped); (2) `rule_numbers` in `factory/checks.py` fatal-flagged any answer numeral not verbatim in the source — computed answers were structurally illegal; (3) `03-check`/`09-review` rubrics had no coverage dimension (the thin page passed both gates clean); (4) the 14.6 KB simple trilingual example bled into 05/08/09/10 with no styling-only framing. Fixes: `02-generate` gained the **COVERAGE CONTRACT** (inventory the chapter's titled sections, in-text questions, worked examples and end-of-chapter exercises; map every item to a block — nothing may be dropped; claims 12–40; every titled chapter section gets its own lesson section; worked_example = problem statement VERBATIM + answer COMPUTED from those numbers); `03-check` gained **RECOMPUTE** (recompute every worked_example and numeric check — a wrong computed answer is fatal) + **COVERAGE** (omitting a chapter section, worked example or exercise is fatal); `04-repair` can now **ADD blocks** for coverage omissions (new ids appended at the end, teach-then-test, last added block a check); `rule_numbers` rewritten — only problem/question-STATEMENT numerals are code-checked (invented-problem guard), answer/option numerals are the reviewer's recompute territory by design; `design.py` labels the example block **"VISUAL STYLING REFERENCE ONLY"** before the example bodies (styling + completeness only; never reuse or imitate their content; coverage is dictated by the SOURCE MATERIAL); `max_chars_design_context` 48000 → 64000. **Example lesson page 2 hand-built** from the real NCERT class-9 ch 6 "How Forces Affect Motion" (2025 ed): `docs/frontend/candidates/design-doctrine-lesson-example-2.html` — all 7 titled sections, 11 checks (Pause & Ponder + Revise exercises), 11 worked examples (Ex 6.1–6.8, snake boat, 4 exercise numericals with computed answers), 3 sims, 4 to-scale diagrams, 1 reveal, misconceptions panel, glossary, At a Glance; English-only content + static language-bar markup; deliberately lives OUTSIDE the `doctrine_examples` glob until the founder approves it (approval = move it into `docs/frontend/`; composed context 63,368 < 64,000 ✓). 211 unit + 10 frontend + 7 integration green. Next: founder reviews the candidate → approves or amends → founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` on 0.3.4.

Done (2026-11-02):

- ✅ Frontend live at **http://192.168.49.2:30080** (NodePort 30080, no manual command; caught + fixed a busybox `cp` seeding bug).
- ✅ Test CronJob (cadence rendered from `TEST_CRON_SCHEDULE` in `k8s/infra.env` — the config value) + manual trigger + startup run on every `scripts/apply-k8s.sh`; it caught a read-only-filesystem test bug → fixed → image 0.2.2.
- ✅ Real pipeline Job pattern live: `k8s/20-factory-run-job.yaml` + dev inference router (`docker/inference-router.Dockerfile`) bridging the host's loopback-only model server to containers/cluster.
- ✅ Factory runs are now a **topic-agnostic Job template + script trigger** (nothing topic/server/model-specific hardcoded in manifests); cluster config consolidated into `k8s/infra.env` + `zivon-factory-config` ConfigMap; generation is manual-only, never scheduled.

### Admin trigger commands (button stand-ins — wire THESE into the Day-8 dashboard)

Until the Day-8 admin dashboard exists, these are the sanctioned admin controls. When the dashboard is built, its buttons must perform exactly these semantics (keep the scripts as the implementation behind the buttons):

| Dashboard button (Day 8) | Command today (the stand-in) | What it does |
|---|---|---|
| **Run tests now** | `scripts/trigger-tests.sh` | `kubectl create job test-manual-<HHMMSS> --from=cronjob/test-suite -n zivon` — clones the CronJob's jobTemplate. The suite also runs on the `TEST_CRON_SCHEDULE` cadence AND once on every `scripts/apply-k8s.sh` (startup coverage; keep this behavior on dashboard deploys). |
| **Generate a topic** | `scripts/trigger-factory-run.sh "<chapter>" [class 6-12]` | Renders the `k8s/20` Job template (name → `factory-run-<slug>-<HHMMSS>`, injects chapter + optional `--class`) and applies it. Generation is **manual-only by design** — the factory Job must never be scheduled; only tests are. |
| **Watch the latest run** | `scripts/logs-factory-run.sh` | Resolves the newest factory run by the `task=factory-run` label (no generated job name/timestamp needed) and follows its logs; `--status` / `--list` for quick checks. The dashboard's run-log viewer must use the same label-based lookup. |

Constraints carried forward: cron granularity is minutes (sub-minute loops = runner Deployment + sleep, P2); test suites never ship in production images (the factory image carries them only because the perf harness is a runtime tool import); secrets runtime-only, never in manifests or CI.

---

## Implied Work (brain-dump didn't say it, the plan does)

- Domain purchase, DNS, SSL, hosting; **HTTPS/WSS required** for browser mic access.
- Credit budgeting: cost model for STT minutes / TTS characters, usage caps, reserved tranche for demo day + judge traffic on the live link.
- Evon hosting: GPU rental cost + cold-start/warm strategy, or local quantized fallback.
- **Content licensing**: NCERT (officially free) + public-domain sources only; attribution in the source pack; no copyrighted textbook scraping.
- Kid testing logistics: parental consent, recording permission, session protocol, measurable success criteria (used at Gates B).
- Device/perf matrix: low-end Android is the primary target for Indian students; explicit performance budgets.
- Accessibility: Devanagari font rendering, contrast, readable type sizes.
- Privacy: minors in testing → data minimization, anonymized telemetry, DPDP basics.
- Demo-failure contingency: pre-recorded fallback video + offline demo mode, rehearsed.
- Judge-traffic load/uptime on submission week.
- Submission mechanics: public repo, live link, video, hashtags, nominations, timing buffer.
- Recording setup for the commercial: capturing the voice loop working live (mic picking up speaker) convincingly.

---

## Risk Register

| Risk | Mitigation |
|---|---|
| Evon not strong enough for tutoring | Gate A Day 1; fallback LLM allowed (Prisma + Timbre still satisfy the ≥1-model rule); goal stays all three |
| GPU cost / cold-start latency for Evon | Quantized local run or rented GPU with warm instance; cache common explanations |
| Credit exhaustion mid-build | Daily usage log, dev-mode text-only testing (mock TTS during dev), reserved 40% tranche |
| Kid testers flake | Line up backups Day 0; sessions are 20 minutes each |
| Voice latency too high | Stream everywhere, shorter tutor replies, pre-warm; Gate C forces the decision early |
| Scope creep | Gate D freeze + scope ladder below |
| Demo-day failure | Pre-recorded fallback video, rehearsed script, Day 11 buffer, noon submission target |

---

## Scope Ladder

**P0 — must ship (the submission):**
- ≥6 Physics topic pages live on the domain, generated by the pipeline
- Voice doubt-tutor on the pages (Prisma → Evon/fallback → Timbre)
- 60-second demo video + public repo + live link + hashtag posts
- Works on low-end Android with code-mixed speech

**P1 — should ship:**
- Expressive Timbre tags via prompting
- Kid-test evidence shown in the demo
- Admin dashboard v0 + telemetry
- Cluster monitoring dashboard (Prometheus + Grafana, admin-authed)
- Full CI/CD + branch protection + agentic review
- 10+ topics

**P2 — stretch, only if ahead of schedule:**
- Fine-tuning Evon for expressive tag emission
- Full red-team agent pass
- Deep analytics
- A second language (Tamil/Telugu) for the Main Character award
- Full-agent teaching mode (Option A)

**Explicitly out of scope:** mobile app, accounts/billing, full course platform, code execution sandbox, multi-user auth.

---

## Definition of Submission-Ready (checklist, Day 11 dry run)

- [ ] Live link works on: laptop, mid-range Android, low-end Android
- [ ] Voice loop answers a Hinglish doubt in < 4s on the deployed site
- [ ] Repo public, pinned, README states the Gnani stack and challenge
- [ ] Demo video ≤ 60s, intelligible to a non-technical viewer
- [ ] Posts live on X and LinkedIn, both hashtags, nominated
- [ ] Reserved credits intact
- [ ] Fallback video ready in case the live link degrades
