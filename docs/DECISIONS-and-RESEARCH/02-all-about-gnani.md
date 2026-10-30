# All About Gnani — Challenge Context & Strategy

This document captures the full context of the **Great Indian AI Internship Challenge**, who Gnani AI is, what their models do, what they actually reward, and how our project (Zivon) is positioned to impress them.

---

## 1. Who is Gnani AI?

Gnani AI is a Bengaluru-based company building **sovereign speech and language AI for India**.

Key points:
- They train their own models on real Indian telephonic audio (noisy, code-mixed, multi-accent).
- Their stack is designed for Indian languages and real-world voice conditions from the start — not English models adapted later.
- They were selected under the government’s **IndiaAI Mission** (2025) to help build a voice foundation model for Indian languages.
- Their commercial offering is the **Artha** sovereign stack: Prisma + Timbre + Evon running on customer-controlled infrastructure.

They are not looking for research papers or pure model fine-tunes. They want **working voice applications** that solve real problems for Indian users.

---

## 2. The Challenge at a Glance

| Item | Detail |
|------|--------|
| **Official name** | Great Indian AI Internship Challenge |
| **Theme** | Build Sovereign AI for India |
| **Organiser** | Gnani AI |
| **Deadline** | 10 November 2026, 11:59 PM IST (no extensions) |
| **Eligibility** | Enrolled students in India, aged 18+, solo or team of two |
| **Cost** | Free to enter |
| **Credits** | 5,000 programme credits per registrant (for Prisma + Timbre APIs) |
| **Internships** | Up to **100** paid six-month internships |
| **Stipend** | Up to **₹1 lakh per month** per selected intern (individual offer decides the exact amount) |
| **Internship start** | 1 January 2027 |
| **Awards** | 10 categories × ₹50,000 = ₹5 lakh total |
| **Public demo required** | Yes — post on X and/or LinkedIn with both hashtags |

**Hashtags (mandatory for engagement tracking):**
- `#GreatIndianAIInternshipChallenge`
- `#GnaniAI`

---

## 3. The Three Models You Must Use

You must use **at least one** of Gnani’s models. Pure competing models or completely independent systems are not accepted.

| Model | Type | Key strengths | How we use it |
|-------|------|---------------|---------------|
| **Prisma v2.5** | Speech-to-Text | Trained on 14M+ hours of telephonic audio. Streams in <200 ms. Excellent on code-mixed speech (Hinglish, Tanglish, Benglish, etc.) and noisy real-world audio. 10+ Indian languages. | Core listener for the tutor. Handles imperfect mics, background noise, and mixed language naturally. |
| **Timbre v2.5** | Text-to-Speech | Natural Indian-language prosody. Correct handling of names, numerals, lakh/crore cadence. Streams over WebSocket / SSE. 10+ Indic languages. | The voice of the tutor. Makes explanations feel human and local. |
| **Evon v3.3** | Reasoning LLM (open-weight) | ~30B MoE parameters, 128K context, 11 Indian languages native. Apache 2.0. Not yet on the public API — request weights via Hugging Face and run yourself. | The brain of the tutor. Explains concepts, checks understanding, adapts difficulty. |

**Important note on Evon:** It is open-weight. You download and run it yourself (or use a compatible inference setup). Prisma and Timbre run through the Gnani API dashboard (app.gnani.ai) and consume the 5,000 programme credits.

**Fallback policy (our decision, not the challenge's):** Evon v3.3 is the intended brain and our default. If it fails the Day-1 quality gate (see `05-timeline.md`, Gate A — Physics reasoning eval), the runtime LLM may be swapped (e.g. Gemma 4 or latest). The challenge only requires **at least one** Gnani model, and Prisma + Timbre already satisfy that — but our goal and our story remain the full three-model sovereign loop.

Together these three form a complete voice agent pipeline: listen → reason → speak.

---

## 4. What Gnani Actually Cares About

From their own messaging and award categories:

1. **Practical, working demos** — not slides or notebooks.
2. **Code-mixed speech as a first-class feature** — not an afterthought.
3. **Robustness to noisy, real-world audio** (especially telephony-style conditions).
4. **India-first use cases** — students, farmers, kirana stores, rural citizens, small businesses, government schemes, education, etc.
5. **Sovereign AI narrative** — building on Indian models for Indian users.
6. **Clear 60-second demo video** that anyone can understand quickly.
7. **Public engagement** — posts on X/LinkedIn with the required hashtags are actively tracked for shortlisting.

They repeatedly emphasise:  
> “No fixed idea list. No single right project. We want to see what you choose to build when the tools are in your hands.”

---

## 5. Award Categories (₹50,000 each)

These reveal exactly what they value:

| Award | What it rewards |
|-------|-----------------|
| **Main Character** | Best build in a regional / low-resource Indian language |
| **Mixed Vibes** | Best code-mixed voice experience |
| **Real Deal** | Most useful real-world problem (farmers, kirana, rural health, education, etc.) |
| **Noise Canceller** | Best performance on messy telephone audio |
| **Jugaad Genius** | Most creative / unexpected use of the models |
| **Solo Ninja / Two-Person Army** | Best solo or team-of-two project |
| **Demo Day Drop** | Best 60-second demo video |
| **Crowd Favourite** | Highest public engagement on X + LinkedIn |
| **Small Town, Big Build** | Best entry from Tier-2 / Tier-3 city or college |

A project can (and should) aim at multiple categories at once.

---

## 6. Selection Reality

- **Internship shortlist** is driven heavily by **verified public engagement** + quality of the build.
- Awards are judged separately from the internship shortlist.
- You can win an award without getting an internship, and vice versa.
- Shortlisted candidates go through **individual interviews**.
- High-performing interns may later be considered for full-time roles (not guaranteed).

**Bottom line:** A strong technical build + a clear, shareable demo + visible public posts is the winning combination.

---

## 7. Our Project: Zivon

**One-line pitch:**  
A voice-first AI tutor that Indian students can actually talk to — in Hindi, English, or mixed — even on noisy connections.

**Why this fits Gnani perfectly:**

| Gnani priority | How Zivon addresses it |
|----------------|------------------------|
| Code-mixed speech | Primary interface is spoken Hinglish / mixed Indian languages |
| Noisy real-world audio | Designed for imperfect mics and real environments (Prisma’s strength) |
| India-first use case | Education — millions of students who are more comfortable speaking than typing |
| Working voice agent | Full loop: Prisma → Evon → Timbre |
| Clear demo | Easy 60-second flow: student asks a Physics question, tutor explains step-by-step in natural voice |
| Sovereign stack | Built entirely on Prisma + Timbre + Evon |

**MVP focus:**
- Physics (Class 9–12 concepts) as the first subject
- Patient, clear, encouraging tutor personality
- Real-time voice conversation
- Designed so new subjects can be added later

Execution plan: `05-timeline.md` (Day-by-day, with decision gates and a scope ladder).

**Name:** Zivon (blank-slate, no inherited meaning). Domain decision closes by Day 1 — see `03-naming-methodology.md` and `05-timeline.md`.

---

## 8. What They Need vs. What Zivon Delivers

The challenge sets a floor. We intend to clear it by a wide margin — and be explicit about the gap so the ambition is documented, not implied.

| The challenge's bar | The Zivon bar |
|---|---|
| Use **at least one** Gnani model | Full sovereign loop: **Prisma + Evon + Timbre** end-to-end, with a documented quality gate on Evon rather than blind faith |
| A working demo | A **kid-validated** learning product: content proven to teach real children (including topics a class above their level) before any agent touches a student |
| Some app or page | A **multi-agent content factory** that generates interactive animations, simulations, and diagrams at scale, with fact-checking and performance review built into the pipeline |
| Handles code-mixed speech | Code-mixed Hinglish as the **primary interface**, plus a deliberately noisy take filmed in the demo |
| 60-second demo video | Commercial-grade demo film + presentation deck, rehearsed end-to-end |
| GitHub repo + live link | Production-style repo: protected `main`, separate `prod`, PRs with CI + agentic code review, security checks on every promotion, maintained docs |
| Post on X/LinkedIn with hashtags | Daily build-in-public pipeline across the whole build window, both hashtags, nominated, professional growth tactics |
| Basic robustness | Telemetry, per-stage latency logging, error tracking, admin dashboard, analytics for product decisions |
| "Good enough" frontend | Deliberate UI/UX engineering pass: design system, low-end-Android-first performance, accessibility, telemetry-driven iteration |

**Honesty clause:** Netflix/Google-grade security and frontend perfection are the standard we *aim at*, time-boxed within 12 days. Where we don't reach it, the gap is documented and carried forward as a roadmap — not hidden. The demo's reliability always outranks polish.

---

## 9. Strategy to Impress Them

1. **Make the voice loop rock-solid first**  
   Prisma transcription quality + Timbre naturalness + Evon explanations that feel like a good tutor.

2. **Lean hard into code-mixing and noise**  
   Record demos with real Hinglish and some background noise. Show that it still works.

3. **Keep the demo under 60 seconds and obvious**  
   Student asks one clear Physics question → tutor answers step-by-step → student follows up → tutor checks understanding. No long setup.

4. **Post publicly early and often**  
   Progress posts + final demo with both required hashtags. Engagement is part of the selection signal.

5. **Tell the sovereign story**  
   In the README, demo description, and posts: “Built on Gnani’s Prisma, Timbre and Evon — Indian models for Indian learners.”

6. **Aim for multiple awards at once**  
   Mixed Vibes + Real Deal (education) + Noise Canceller + Demo Day Drop is a realistic multi-award shot.

---

## 10. Key Dates

| Milestone | Date |
|-----------|------|
| Contest start / registration open | 1 October 2026 |
| **Final submission deadline** | **10 November 2026, 11:59 PM IST** |
| Review + individual interviews | After close |
| Internships begin | 1 January 2027 |

As of late October 2026 we have roughly two weeks of focused build time left. Prioritise a reliable demo over extra features.

---

## 11. Official Links

- Challenge page: https://www.gnani.ai/internship
- Blog overview: https://www.gnani.ai/resources/blogs/great-indian-ai-internship-challenge-2026
- API / models: app.gnani.ai (Prisma + Timbre)  
- Evon weights: request via Hugging Face (open-weight)

---

**Remember the core brief they keep repeating:**

> Build something useful with Gnani AI’s models and APIs, show us how it works, and put your work in front of the team.

Zivon is our answer to that brief.