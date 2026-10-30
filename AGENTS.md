# AGENTS.md — Instructions for Coding Agents

You are implementing **Zivon**, a voice-first AI tutor for Indian learners.

This project is being built for the **Great Indian AI Internship Challenge** by Gnani AI. The judges care deeply about real working voice demos that use their models well, especially on code-mixed speech and noisy audio. Keep that perspective in mind in every decision.

**Subject scope (confirmed): academic Physics, Class 9–12.** Not Python, not general chat.

**Execution plan: `TIMELINE.md` (repo root).** Deadline 10 Nov 2026, 11:59 PM IST — hard. Respect the decision gates (A–D) and the P0/P1/P2 scope ladder defined there.

**Decision & research docs:** `docs/DECISIONS-and-RESEARCH/` — challenge brief (01), Gnani research (02), product idea (03), naming methodology (04). Read them before making product or positioning decisions.

---

## Project goal

Two coupled systems:

1. **Content factory (build-time):** multi-agent pipeline — Curator → Synthesizer (JSON visual specs) → Visual Builder → Performance Engineer → Comprehension & Fact Reviewer → Code Reviewer — that turns NCERT / public-domain Physics material into interactive learning pages (text + animations + interactive simulations + diagrams) that kids demonstrably learn from.
2. **Voice tutor (product runtime):** the conversation loop —
   1. Student speaks (Hindi / English / code-mixed)
   2. **Gnani Prisma** transcribes the speech
   3. **Gnani Evon** reasons and generates a tutor response (anchored to the page the student is on)
   4. **Gnani Timbre** speaks the response back, with expressive tags where appropriate

The tutor personality: patient, clear, encouraging, step-by-step, Socratic. Voice is the primary interface for doubts; interactive visuals are the primary interface for learning.

---

## Non-negotiable constraints

- **Prisma v2.5** (STT) and **Timbre v2.5** (TTS) are non-negotiable for the product's voice loop. No OpenAI/Deepgram/ElevenLabs replacements for these.
- **Evon v3.3** is the intended reasoning brain and the default. A fallback LLM (e.g. Gemma 4 or latest) is permitted **only** via Gate A in `TIMELINE.md` (a written Physics-reasoning eval decision), because the challenge requires at least one Gnani model and Prisma + Timbre already satisfy that. The goal and the public story remain the full three-model loop.
- The demo must work end-to-end with real voice input and output.
- Prefer simplicity and reliability over feature count. A solid 60-second demo beats a half-broken multi-feature app.
- Content sourcing: **NCERT (officially free) and public-domain sources only**, with citations in the source packs. No scraping copyrighted textbooks.

---

## Build order (mirrors `TIMELINE.md`)

1. **Phase 1 — Content factory + validation** (Days 1–4, iterating to Day 7)
   Get the fundamentals of teaching right before any agent touches a student. Validate with 2–3 real kid testers; measure pipeline reliability by human edit rate per generated topic. Static pages go live on the chosen domain.
2. **Phase 2 — Voice loop + agentic tutor** (Days 5–7)
   CLI voice loop first, then mic UI on the live pages with page-context anchoring. Recommended architecture: static curated content + on-demand anchored doubt tutor (hybrid), decided at the Day-5 architecture decision.
3. **Phase 3 — Minimum-credible production ops** (Day 8)
   Structured logging, telemetry, per-stage latency, error tracking, security hardening pass, admin dashboard v0.
4. **Phase 4 — Frontend perfection pass** (Day 9)
   Design system, demo-flow screens first, low-end-Android-first performance, accessibility.
5. **Phase 5 — Presentation** (Days 10–11)
   Demo script, commercial, deck, rehearsals, code freeze, buffer day.

Do not start Phase 3/4 perfection work before their scheduled days or before earlier gates pass.

---

## Architecture guidelines

### Product runtime

- Python backend owns the conversation loop.
- Real-time audio handling (WebSocket).
- LiveKit is a strong option because Gnani provides an official `livekit-plugins-gnani` plugin. Use it if it reduces complexity.
- If you do not use LiveKit, still keep the STT → LLM → TTS pipeline clean and modular.
- Separate concerns:
  - Audio / session management
  - Gnani API clients (Prisma, Timbre)
  - Evon inference / prompting (incl. expressive TTS tag emission)
  - Tutor personality and Physics subject logic
  - Page-context anchoring (what the student is reading/interacting with)
  - Usage / session logging (simple is fine)

### Content factory (build-time)

- Agents communicate via structured **JSON block specs**, not ad-hoc markup tags:
  `{ "type": "animation" | "simulation" | "diagram" | "text" | "check", "spec": {...} }`
- Generated visuals are self-contained HTML/JS (canvas/SVG), no heavy frameworks, and must pass a performance budget for low-end Android (page load < 2s, ~60fps animations).
- Every generated page passes the Comprehension & Fact Reviewer (against the cited source pack) and the Code Reviewer (no `eval`, no external calls, accessible) before it can go live.

### Key design principles

- Low latency matters. Stream everywhere. Target < ~4s end-of-speech → first spoken audio (Gate C).
- Treat code-mixed speech and imperfect audio as normal, not edge cases.
- Keep the tutor personality consistent: patient, clear, encouraging, step-by-step.
- Make it easy to swap or add subjects later (start with Physics).
- Log enough information to debug conversations (transcripts, latency, errors).

---

## Repo process (applies to every change, no exceptions)

- Branch model: protected `main`, `prod` for production, `feature/*` for work.
- Every change goes through a PR → CI (lint / typecheck / build / test) → agentic code review → merge to `main`.
- `main` → `prod` only via the promotion pipeline, which includes security checks.
- Kanban (GitHub Projects) is groomed daily; nothing gets worked on that isn't on the board.
- Docs (README, architecture notes) are updated in the same PR as the code they describe.
- Never commit secrets. Configuration lives in environment variables.

---

## Content creation skills

`skills/content-creation/` holds the agent skills for the build-in-public posts (LinkedIn and X writers, shared post theme rules, asset/edit briefs, and the Kinocut + GIMP editing lessons store). Read [`skills/content-creation/README.md`](skills/content-creation/README.md) before any post work — it is the source of truth for the folder's layout and rules; this file does not list individual files.

Non-negotiables: interview before drafting (Depth Gate), never fabricate facts, never post on the user's behalf without explicit approval, and **Kinocut MCP (video) and GIMP MCP (image editing) are the decided editing tools** — do not evaluate or propose other editing tools.

---

## Coding standards

- Prefer clear, readable Python.
- Use type hints.
- Keep configuration in environment variables (API keys, model names, sample rates, etc.).
- Never commit secrets.
- Write small, focused modules. Avoid giant files.
- Add basic logging from day one.
- When adding dependencies, prefer well-maintained packages and keep the set small.
- Document any non-obvious setup steps in the README.

---

## Gnani-specific notes

- Prisma and Timbre are accessed via Gnani's API (`api.vachana.ai` / dashboard).
- Evon is open-weight. You will need to run it yourself (or via a compatible inference server). Plan for this early — GPU hosting choice is a Day-0/1 task.
- Official LiveKit plugin exists: `livekit-plugins-gnani`. Prefer using it if you go the LiveKit route.
- Programme credits are limited (5,000 per registrant). Log usage daily, use text-only dev mode where possible, and **reserve ~40% of credits** for demo day and judge traffic.
- Timbre supports expressive tags (whisper, excitement, etc.) — confirm the exact tag set from Gnani docs before prompting Evon to emit them. Fine-tuning for tag emission is a stretch goal (P2), not the critical path.
- The models are strong on Indian languages and code-mixing — lean into that strength in demos and prompts.

---

## What to avoid

- Building complex multi-user systems, billing, or heavy analytics before the core loop works.
- Over-engineering authentication, databases, or frontend frameworks early.
- Replacing Prisma or Timbre. Replacing Evon only via Gate A, documented.
- Long, feature-heavy demos. Judges watch many submissions — clarity wins.
- Ignoring latency. A slow tutor feels broken even if the answers are good.
- Adding topics/features after the Day-8 feature freeze (Gate D).
- Any change that bypasses the PR → CI → review → main flow.

---

## Definition of done for the MVP

- Physics topic pages (≥6) generated by the content factory are live on the chosen domain and validated with kid testers.
- A student can open a page, speak a Physics doubt in natural or code-mixed speech, and hear a clear, context-aware spoken explanation.
- The full pipeline uses Prisma + Evon (or Gate A fallback) + Timbre.
- The experience works reasonably well with some background noise and mixed language, including on a low-end Android phone.
- There is a short, understandable demo video of the above.
- The README clearly states that the project is built on Gnani's models for the Great Indian AI Internship Challenge.

---

## When in doubt

Ask:
"Does this help us ship a reliable, impressive voice tutor demo that shows off Gnani's models on real Indian speech?"

If the answer is no, defer it.
