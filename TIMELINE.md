# Build Timeline: Oct 29 → Nov 10, 2026

## Reality Snapshot

| Item | Value |
|---|---|
| Start | Thu 29 Oct 2026 (Day 0) |
| Hard deadline | **Tue 10 Nov 2026, 11:59 PM IST** — no extensions |
| Build time | ~12.5 days |
| Internal submission target | Everything public by **10 Nov, 12:00 PM IST** (12h safety buffer) |
| Working assumption | Solo builder + agent workforce, full-time crunch, weekends included |

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
| **A — Evon quality** | Day 1 EOD | Is Evon v3.3 strong enough as the tutor brain? | 10 Physics explanations + 5 Hinglish prompts scored on: factual correctness, step decomposition, misconception detection, code-mix naturalness | Switch runtime LLM to Gemma 4 (or latest). Prisma + Timbre stay regardless — challenge only requires ≥1 Gnani model, and we already use two. Goal remains all three. |
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

- **Gate A (Evon)**: run the eval rubric above. Record the decision in writing.
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
- **Admin dashboard v0**: sessions, usage, credit consumption, topic engagement.
- main → prod promotion pipeline with automated security checks.
- **Gate D**: sign the ship list (P0/P1/P2 below). Code features stop here.

**Done when**: dashboard shows real session data; security checklist complete; CI/CD green; ship list signed.

### Day 9 — Sat 7 Nov — Phase 4 frontend perfection pass

- Design system: type scale, color tokens, spacing, corner radii, component states. Polish the **exact screens the demo will show** first.
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
