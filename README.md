# Zivon

**A voice-first AI tutor Indian students can actually talk to.**

Built for the **Great Indian AI Internship Challenge** (Gnani AI) on Gnani's sovereign stack:

> Student speaks (Hindi / English / Hinglish) → **Prisma v2.5** listens → **Evon v3.3** reasons → **Timbre v2.5** speaks back.

**Focus:** academic Physics, Class 9–12 — taught through interactive animations, simulations, and diagrams, with a patient spoken Hinglish tutor anchored to every page.

---

## Status

🚧 **In active build.** Deadline: **10 November 2026, 11:59 PM IST**.

- Live demo: *coming soon* (link will be pinned here)
- Day-by-day build plan: [`05-timeline.md`](05-timeline.md)

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
- **Content factory** is build-time tooling that generates the static interactive pages.

## Tech Stack

| Layer | Choice |
|---|---|
| STT | Gnani **Prisma v2.5** (streaming, code-mixed, noisy-audio strong) |
| LLM | Gnani **Evon v3.3** (open-weight, self-hosted) |
| TTS | Gnani **Timbre v2.5** (streaming, expressive tags) |
| Backend | Python — FastAPI + WebSockets |
| Frontend | Web UI with mic; static interactive pages (canvas/SVG) |
| Infra | Static hosting + backend host, HTTPS/WSS, CI/CD, staging → prod |

## Repo Map

| Doc | Contents |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Instructions for coding agents working on this repo |
| [`01-gnani-challenge-brief.md`](01-gnani-challenge-brief.md) | Challenge brief |
| [`02-project-idea-physics-voice-tutor.md`](02-project-idea-physics-voice-tutor.md) | Product idea (Physics, confirmed scope) |
| [`03-naming-methodology.md`](03-naming-methodology.md) | Brand naming process → **Zivon** |
| [`04-all-about-gnani.md`](04-all-about-gnani.md) | Gnani context, strategy, and "what they need vs what we deliver" |
| [`05-timeline.md`](05-timeline.md) | Day-by-day build timeline, gates, risks, scope ladder |

## Engineering Process

- `main` protected; `prod` branch for production; all changes via PR
- Every PR: CI + agentic code review before merge; `main` → `prod` promotion includes security checks
- Kanban (GitHub Projects) maintained daily
- Public build-in-public posts on X / LinkedIn throughout the build

## Built on Gnani's Models

Zivon is built entirely on Gnani AI's sovereign stack — **Prisma v2.5, Evon v3.3, and Timbre v2.5** — Indian models for Indian learners, for the **Great Indian AI Internship Challenge**.

`#GreatIndianAIInternshipChallenge` `#GnaniAI`

## License

TBD (MIT planned before repo goes public).
