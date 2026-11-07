# Feature value filter - deciding what actually earns a place

Goal: separate features that add *learning value* from features that merely look
product-shaped. The output is a **decision log**, not a wish list.

## 1. Layer taxonomy (use these labels in every ID)

| Layer | Code | Meaning | Zivon examples |
|---|---|---|---|
| Core | `COR` | Teaching content and interaction. Already built; spec only the *surfaces* the frontend shows. | Lesson page, text blocks, worked example, check, reveal, diagram, simulation |
| Wrapper | `WRP` | Wraps every Core surface; works if the add-on is off. | Translation/language, text-to-speech |
| Add-on | `ADD` | Optional intelligence on top. | Voice tutor, personalization |
| Cross-cutting | `XCT` | Needed by all layers. | Consent, session, settings, accessibility, offline, error handling, onboarding |
| Ops | `OPS` | Not student-facing but frontend-displayed to staff. | Content release status, admin dashboard v0, usage/credit meter |

Feature IDs: `F-<LAYER>-<AREA>-<NN>`, e.g. `F-WRP-TTS-03`. IDs are never reused.

## 2. Generate broadly, then gate

Phase 3 produces a long list per layer using these prompts (each yields candidates):
- Walk the journey (arrive → choose topic → learn → doubt → check → leave → return) and ask at each step "what does the student see, hear, do, fear?"
- For each Core block type (`text`, `worked_example`, `check`, `reveal`, `diagram`, `simulation`) list what a *wrapper* and an *add-on* could do to it.
- For each wrapper/add-on list: entry, controls, states, settings, failure, privacy, cost, handoff to the other layers.
- Edge conditions: first visit, return visit, shared phone, no mic, no audio output, offline, quota exhausted, wrong language selected, noisy room, a sibling speaking.
- Adjacent products' features (PhET, Khan, Duolingo-style apps, voice assistants) - as prompts only; never copy engagement mechanics.

## 3. The gate - answer all eight in the decision log

| # | Question | Fail means |
|---|---|---|
| G1 | **Job & moment**: which job (JTBD) and which journey moment does it serve? | No user need → KILL |
| G2 | **Learning mechanism**: how does it cause understanding or remove a barrier to it? Cite a principle (`01`) with an evidence tag. | Decorative → KILL or DEFER |
| G3 | **Removal test**: if absent, does the student fail at the job, or merely have a less polished time? | Polish only → DEFER |
| G4 | **Layer independence**: does Core still work if this fails? | Violation → redesign or KILL |
| G5 | **Cost**: bandwidth, CPU on a low-end phone, tokens/credits (Prisma/Timbre/Evon are metered), operational burden, content-factory burden. | Unaffordable → MERGE into cheaper variant |
| G6 | **Risk**: child safety, privacy/consent, misinformation (wrong physics), cultural/language error, dark pattern. | Unmitigable → KILL; mitigable → attach mitigation |
| G7 | **Measurability**: which metric and event shows it works? | Unmeasurable → add a metric or DEFER |
| G8 | **Scope fit**: where does it sit on the repo's P0/P1/P2 ladder; does it collide with "explicitly out of scope"? | State the collision; propose, do not assume |

## 4. Decision outcomes

`KEEP` (becomes a feature card) · `MERGE into <ID>` (the same capability is cheaper inside another) · `DEFER (reason, revisit trigger)` · `KILL (reason)`.
Record **why** for every non-KEEP; the reasons are as valuable to the reader as the keeps.

Decision-log row:
`| cand-id | candidate | layer | job | mechanism + evidence tag | removal test | cost | risk | metric | outcome | reason |`

## 5. Kano pass on the survivors (assign each KEEP one class)

- **Must-be** (absence breaks trust): mic permission flow, language persistence, error recovery, pause/stop audio, consent.
- **Performance** (more is better): sim fidelity, answer correctness, latency.
- **Delighters** (unexpected value): tutor drives the sim step-by-step; "predict first" reveal. Keep few; each must pass G2.
- **Indifferent/Reverse**: gamification badges, leaderboards, streak guilt - likely reverse for children; default KILL unless evidence.

## 6. Questions the filter should force the author to answer for each layer

**Core surfaces**: What does the student see for each block type? How do they move through blocks (scroll, next, progress)? How does a check give feedback? How is a sim's state recoverable (reset)? What does the page do with JS disabled (the repo promises `<details>` works with zero JS)?

**Translation**: Which surfaces translate (chrome, text blocks, sim labels, diagram captions, check feedback, tutor speech, student input)? Translated at build-time or runtime, by whom, reviewed by whom? What is shown when a block lacks a translation? How are physics terms/symbols/units treated? Is "Hinglish" a language, a mode, or a style of explanation? Where is the choice remembered?

**TTS**: Which text is spoken (all, selected, sim narration, check feedback)? Pre-generated vs live? Controls (play, pause, speed, sentence-jump)? Highlight-follow? How are symbols, units, numerals pronounced? What happens when the tutor speaks - does page audio pause (audio focus)? Data-saver behaviour?

**Voice agent**: Entry/exit, push-to-talk vs hands-free, states, barge-in, transcript visibility, text fallback, anchoring chips, what the agent may *do* to the page (highlight, set a slider value, scroll), Socratic policy, hint ladder, limits, safety for minors, session end, credit exhaustion.

**Personalization**: What is personalized (language, pace, depth, examples, review order)? From what signals - explicit choice vs inference? Where stored, how long, who can see it? How does the student see and reset it? What is the *non-personalized default* and is it good? (Legal flag: see `06`.)

## 7. Anti-patterns to reject at the gate

Streaks/badges that pressure children · notification nags · infinite chat with no pedagogical goal · features whose only purpose is the demo · "AI" labelled features with no measurable learning effect · settings that merely export the designer's indecision to the student · a second way to do a thing that already has a good way.
