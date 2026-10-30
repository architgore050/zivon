# Project Idea: Voice-First Physics Tutor for Indian Learners

> **Note:** This project originally explored a Python coding tutor. The focus is now **academic Physics study (Class 9–12)** — confirmed as the product scope. This document has been rewritten to match. See `05-timeline.md` for the execution plan.

## One-line Summary

An interactive voice tutor that teaches **Physics (Class 9–12)** to Indian students in natural **code-mixed Hindi-English** (and optionally other Indian languages), combining pipeline-generated interactive content (animations, simulations, diagrams) with a spoken Hinglish tutor, using Gnani's Prisma + Timbre + Evon stack.

## Why This Idea Fits the Challenge

- **Voice-first** → plays to Prisma (STT) and Timbre (TTS) strengths
- **Code-mixed speech** is the natural way most Indian students speak about Physics
- Physics is a subject where **visual + spoken explanation beats text walls** — interactive simulations are a genuine learning multiplier, not decoration
- Highly practical and high-impact (board exams, foundation for engineering/medical careers)
- Easy to demo in 60 seconds
- Can target multiple award categories: Mixed Vibes, Real Deal, Main Character, Demo Day Drop, Jugaad Genius

## Target Users

- Class 9–12 students (CBSE/ICSE and state boards) more comfortable speaking Hindi/Hinglish than pure English
- Self-learners preparing for boards or foundation courses (JEE/NEET groundwork)
- Students in Tier-2 / Tier-3 cities who lack good offline tutors
- Kids learning a concept **ahead of their class** — a core validation target (see Gate B in `05-timeline.md`)

## Core Experience (MVP)

Student opens the live site → gets a curated, interactive Physics topic page (text + animation + interactive simulation + diagram) → can talk to the anchored voice tutor about anything on the page, in Hindi / English / Hinglish.

### Supported Interactions

1. **Concept explanation**
   "Reflection of light kaise hota hai? Ray diagram ke saath samjhao."
   Tutor explains simply in Hinglish, referencing what's on the student's screen.

2. **Interactive teaching**
   Tutor asks questions, waits for spoken answers, gives feedback, adjusts difficulty.

3. **Problem-solving help**
   Student reads or describes a numerical problem aloud; tutor walks through it step by step, spoken units and numbers handled naturally.

4. **Simulation-guided learning**
   Tutor directs the student to interact with the on-page simulation ("ab slider badhao aur angle kya hota hai dekho") — learning by doing, narrated.

5. **Practice + checks (lightweight)**
   Comprehension checks embedded in pages; tutor reviews spoken answers.

6. **Progress tracking (lightweight)**
   Remembers what the student has covered in the current session.

## The Content Factory (Phase 1 — the foundation)

Before any agent teaches, a multi-agent content pipeline must reliably produce pages kids actually learn from:

**Curator** (NCERT + public-domain sources, cited) → **Synthesizer** (learner-facing content with JSON blocks declaring required visuals) → **Visual Builder** (animations / interactive simulations / diagrams as self-contained HTML/JS) → **Performance Engineer** (low-end Android budgets) → **Comprehension & Fact Reviewer** (first-time-learner clarity, hallucination check against source) → **Code Reviewer**.

Validation loop: generate → test with 2–3 real kids → refine the skill → repeat until the pipeline scales to new topics **without supervision** (measured by human edit rate → zero).

## Technical Stack (Must Use Gnani)

- **Prisma v2.5** → Speech-to-Text (code-mixed + noisy audio is the primary mode, not an edge case)
- **Evon v3.3** → Reasoning + pedagogical responses (open-weight, self-hosted; fallback policy in `05-timeline.md` Gate A)
- **Timbre v2.5** → Natural Indian-accent TTS replies, including expressive tags (whisper, excitement, etc.)
- Backend: Python (FastAPI + WebSockets)
- Frontend: simple web UI with mic button; static content pages on the chosen domain
- Session memory: in-memory / lightweight for MVP

## Pedagogical Differentiator

Most tutors dump answers. Zivon should actively **teach**:

- Socratic questioning instead of answer-dumping
- Detecting common Physics misconceptions (force=motion confusion, "heavier things fall faster", etc.)
- Breaking concepts into small spoken steps synced with on-screen visuals
- Making the student speak the answer before revealing it
- Switching freely between Hindi and English based on the student's comfort

## Demo Script (60 seconds)

1. Student speaks in Hinglish: "Reflection of light kaise hota hai? Samjhao."
2. Tutor explains clearly in natural mixed voice while the on-page animation plays.
3. Tutor asks the student to drag a slider in the simulation and describe what changes.
4. Student answers (with hesitation / code-mixing); tutor gives feedback.
5. Tutor checks understanding with one follow-up question.
6. Show the GitHub + live link.

## Award Targeting

Primary:
- **Mixed Vibes** (code-mixed voice experience)
- **Real Deal** (education — real learning for real students)
- **Demo Day Drop** (clean 60s video)
- **Noise Canceller** (demo includes a deliberately noisy take)

Secondary:
- Main Character (if a strong regional language is added — P2 stretch)
- Jugaad Genius (kid-validated interactive content factory is the unusual, creative piece)

## Success Metrics for the Build

- Kids demonstrably learn from generated pages (Gate B evidence)
- Works reliably with noisy / code-mixed audio
- Feels like talking to a helpful senior rather than a chatbot
- Demo is understandable even without a technical background
- Deployed and shareable publicly before the deadline

## Next Immediate Steps

See `05-timeline.md` — Day 0 list (Kanban, repo process, domain, API keys + credit budget, Evon prep, kid testers, topic selection).
