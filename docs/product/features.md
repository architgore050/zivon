# Zivon — Features Document (implementation-granular)

Status: **v1, 2026-11-07** (Day 8 — Gate D feature-freeze day). Method:
`skills/zivon-product-design-skills/skills/zivon-product-design/SKILL.md` 9-phase pipeline.
This doc decides which features earn their place, records every cut, and specifies every
survivor to feature → screen → element → information → backend need so a frontend and
backend team can build from it without asking the author anything. Its final section is the
handoff for the systems-design stage (Stage 2).

Companion machine-readable files (same folder): `decision-log.csv`,
`ui-element-inventory.csv`, `information-inventory.csv`, `traceability-matrix.csv`,
`backend-handoff.md`.

Hard boundaries respected throughout (never re-decided here): Gnani stack fixed
(Prisma v2.5 / Evon v3.3 / Timbre v2.5, Gate A fallback only as documented); Gate C latency
< ~4 s end-of-speech → first spoken audio; low-end Android + low bandwidth + noisy room is
the base case; children are the users (private-by-default, DPDP); P0/P1/P2 ladder and
"explicitly out of scope" list from `TIMELINE.md` (Gate D: P0 here is identical to the repo
ladder — this doc doubles as the post-challenge roadmap); visual style owned by
`docs/frontend/design-doctrine.md` v1.5 (a feature needing a doctrine change files a DCR,
never overrides); **layer independence**: Core (read / simulate / check) fully works with
translation, TTS, voice agent and personalization all switched off.

Evidence tags: `[STRONG]` replicated/large-sample research · `[MODERATE]` credible but
narrower · `[WEAK]` practitioner consensus · `[ASSUMPTION]` ours — must be tested.

---

## 0. What already exists vs. what must be built (verified from the repo, 2026-11-07)

The core is not a plan — it is largely built. This table is the ground truth the rest of
the doc builds on.

| Area | Exists today (verified) | Gap to build |
|---|---|---|
| Content factory | `pipeline.py` + `factory/` full graph v2 (00-ingest → 11-link), resumable runs, progress-aware catchers, perf gate (Chromium `weak-android` profile), hard linter (no eval/external URLs), CSP baked into pages, doctrine flow into model stages. Image 0.3.10 | None for the product loop; schema-change proposals only (see backend handoff §7) |
| Generated lesson pages | 1 published page in `frontend/courses/class-9-physics/how-forces-affect-motion/` (index.html + page.js + page.css + manifest.json): objectives, text, 2 diagrams (aria-labelled SVG), 4 MCQ checks (radio + Check + aria-live feedback + "Why?" details), 1 simulation (2 sliders + 480×320 canvas), 1 reveal (`<details>`), 1 worked example, glossary, sources footer | ≥6 topics live (P0), 10+ (P1); numeric-check rendering exists in schema; language variants of page strings |
| Site shell | `frontend/index.html` Courses hub (course list from generated `courses.js`, empty state, attribution footer); `assets/zivon.css` (doctrine tokens), `assets/zivon.js` (quiz wiring, ZivonSim runtime with reduced-motion + on-canvas error painter, LessonKit ruled-line alignment, pen-underline) | Two-column page grid + language bar (doctrine §10.5, Day-9 item); no search/filter on hub |
| Voice loop | **Nothing in the repo.** CLI loop + FastAPI/WebSocket backend are Phase-2 items not yet on this branch | Entire voice runtime: STT/LLM/TTS clients, session mgmt, page-context anchoring, mic UI, interruption handling |
| Voice UI on pages | Absent | Mic button, tutor state surface, transcript/caption surface, consent gate |
| Personalization / session memory | Absent (factory takes no learner data; "lightweight session memory" is a Day-7 plan item) | Session-scoped topic/coverage memory (P0-minimal) |
| Telemetry / admin | Factory-side run evidence (`status.json`, `run_report.json`, attempt meta) + k8s scripts as admin stand-ins; no product telemetry, no dashboard | Frontend EVT catalogue → endpoint; admin dashboard v0 (sessions/usage/credits/engagement + the 3 trigger buttons); Prometheus+Grafana (P1) |
| Consent / child safety | Absent | Consent surface + privacy defaults + deletion path |
| Offline / degraded | Pages work offline once loaded (no external calls by CSP); no service worker, no offline hub | Degraded-mode ladder (see F-13) |
| Infra | k8s manifests (Job/CronJob/Deployment/Service/PVCs), CI merge gate green, CodeQL/trivy clean | Voice backend image + Deployment + Service; publish/deploy pipelines |

---

## 1. Design principles applied (brief)

Ten principles govern every decision below. Each names a concrete UI consequence and a test
(Phase-1 exit test). Sources: `references/01-principles-catalog.md`.

| # | Principle (source) | Rule for Zivon | Where you'll see it | How we test it | Evidence |
|---|---|---|---|---|---|
| P1 | Useful (Rams) | A feature exists only if it moves a named learner toward understanding or removes friction to it; delight that doesn't serve learning is cut | Every row of `decision-log.csv` names the job it serves | Decision-log audit: a KEEP row without a job+metric is a defect | WEAK-STRONG (craft doctrine) |
| P2 | As little design as possible (Rams #10) | Subtract first: fewer screens, controls, words; every surviving component must survive the removal test ("what breaks if this is removed?") | Max 3 control groups × ~3 controls per sim; hub has no search; no chat history screen | Removal test recorded per KEEP row in the decision log | WEAK (craft doctrine) |
| P3 | Start still + direct manipulation (PhET) | Sims load static in the simplest view; the key object is grabbable/draggable or the slider is the affordance; no motion on load; play/step controls only where physics needs them and then prominent + consistent | Every `zn-sim` block; ZivonSim runtime | First-time kid acts correctly with zero help text (Gate-B style observation) | STRONG (PhET think-alouds) |
| P4 | Coherence + signaling + modality (Mayer) | No decorative animation, music, or "fun" effects; narration + visual beats narration + visual + identical on-screen text — tutor speech gets captions on request, not by default; the object the tutor talks about is highlighted in sync | Tutor dock (caption toggle), sim highlight hook | Page-load audit: zero unrequested audio/motion; captions off by default | STRONG |
| P5 | Predict-before-reveal (Hake PER + retrieval practice) | Checks require a committed answer before feedback; the tutor asks the student to say the answer before explaining; misconception-targeted distractors where the source supports them | `zn-check` blocks (feedback hidden until Check), tutor Socratic loop | Check UI never shows the answer before submission; kid restates concept in own words (Gate B) | STRONG |
| P6 | Visibility of system status, latency as UX (Nielsen + voice practice) | Mic state (idle / listening / thinking / speaking / error) is always visible **and** audible; "thinking" feedback within ~300 ms; Gate C (< ~4 s to first audio) is a UX promise, not just an SLO | Voice dock states, earcons, per-stage latency logs | State matrix has no blank voice state; measured EVT-006 latency p90 < 4 s on deployed site | STRONG (heuristic) / ASSUMPTION (our numbers) |
| P7 | Honest design + a stated conceptual model (Rams, Norman) | Every limitation has visible plain-language copy: machine translation flagged, tutor uncertainty spoken ("I'm not sure" allowed by persona), credit exhaustion explained, "the tutor sees this page, not the room" stated once | Language bar MT flag, tutor copy keys, over-credit-budget state | Copy audit: every state in the state matrix has plain-language text, no euphemisms | WEAK (honesty cues) / STRONG (law-driven disclosures) |
| P8 | User control + graceful error recovery (Nielsen, voice design) | Barge-in always works; sim reset; check skip; after ~3 speech failures offer re-ask + typing fallback; no dead ends; destructive clear is confirm-then-do | Voice dock, sim card reset, fallback chip row | Walk every error row of the state matrix: each ends in a next action, never a dead end | STRONG |
| P9 | Children-first privacy (DPDP + ethics) | Private-by-default: no accounts, no raw audio retained, session memory local-first, no streaks/ranks/engagement mechanics, anything tracking a child is flagged for legal review; personalization is visible + clearable | Consent gate, memory view, EVT privacy classes | Every EVT row carries a privacy class; zero child-profiling features survive the filter unflagged | STRONG (law; re-verify dates) |
| P10 | Low-end Android is the base case (repo constraint) | Every feature must pass the `weak-android` perf profile or specify its degraded form; the degraded ladder is designed, not discovered: full → static → text-only | Perf gate, offline/degraded states, voice degraded mode | Perf harness green per page; degraded copy exists for every feature at each rung | ASSUMPTION (budgets) / STRONG (repo rule) |

---

## 2. Users, jobs, moments (condensed)

Personas per `foundation-persona`, jobs per `define-jtbd-canvas`, journey per
`discover-journey-map` (vendored mechanics; decisions are ours). Research basis: the repo's
own kid-tester program (Gate B, 2–3 consented testers), NCERT-scope product definition
(`docs/DECISIONS-and-RESEARCH/03`), and practitioner voice-UX guidance. No formal user
research exists yet — every behavioural claim below is tagged accordingly and gets a test.

### 2.1 Personas

| Persona | Who | Defining situation (not demographics) | Device / context |
|---|---|---|---|
| **Student** (primary) | Class 9–12 Indian learner, CBSE/ICSE/state board, comfortable explaining things in Hinglish more than in written English; self-studying after class, no access to a good doubt tutor | Stuck on a chapter concept at 8 pm; phone is the family device; shared/noisy room; data-conscious | Low-end Android (4 GB class), Chrome-class browser, 4G/weak Wi-Fi — **base case** [ASSUMPTION, Gate-B testers partially confirm] |
| **Guardian** (secondary, buyer-of-trust) | Parent who lets a minor use a learning site and who appears in the demo story | Decides whether the product is safe enough for their child; reads the privacy/attribution copy | Same device, often laptop |
| **Content-ops admin** (operator = founder today) | Runs generation, tests, watches usage/credits | Needs one-button controls and a live picture of sessions, credit burn, topic engagement | Desktop + cluster |

### 2.2 Jobs to be done (job IDs are cited by every feature card)

| Job | Statement (when → I want → so I can) | Type |
|---|---|---|
| **J1** | When I am stuck on a Physics concept in my textbook, I want to ask out loud in my own words (Hinglish ok) and get a clear, step-by-step answer about *what I'm looking at*, so I can keep studying without waiting for a tutor. | functional + emotional ("a senior helps me, not a bot") |
| **J2** | When a concept is invisible (force, ray, field), I want to touch and change a visual model and immediately see what changes, so I build the intuition exams quietly demand. | functional |
| **J3** | When I think I understand something, I want to test myself — including saying the answer out loud — so I can be sure before the exam. | functional |
| **J4** | When English-only text slows my thinking, I want the whole page in my language (Hindi / Hinglish), so I read at thinking speed and still learn the exam-standard English terms. | functional |
| **J5** | When I keep studying across sittings, I want the tutor to remember what I already covered this session, so I don't re-learn the same thing. | functional |
| **J6** | When my child studies on this site, I want to know what is collected (ideally nothing personal) and how to erase it, so I can allow it without worry. | emotional / social (guardian) |
| **J7** | When I run the product, I want one-button test/generate controls plus a live view of sessions, usage and credit burn, so quality and cost stay under control. | operational (admin) |

### 2.3 Journey (student, cyclical) and moments of truth

| # | Stage | Goal | Entry trigger | Exit criterion |
|---|---|---|---|---|
| 1 | **Arrives** | find a page for the chapter I'm studying | link (post / share / hub) | a topic page opens < ~6 s on weak Android |
| 2 | **Reads & simulates** | build the visual model | page open | sim manipulated + at least one highlighted statement read |
| 3 | **Asks** | clear a doubt | press mic, speak Hinglish | context-aware spoken answer, first audio < ~4 s |
| 4 | **Practices** | prove understanding to myself | check blocks / tutor's spoken follow-up | committed answer → feedback; ≥1 spoken answer |
| 5 | **Returns** | continue later | re-open site | session memory resumes coverage (or clean start) |

| MoT | Moment | Continue-vs-abandon risk | Feature that must win it |
|---|---|---|---|
| MoT-1 | First doubt spoken → answer | answer generic / slow / wrong-context → "bot, useless" | F-05 anchored voice tutor |
| MoT-2 | First slider drag | nothing visibly physical changes → sim is decoration | F-02 simulations |
| MoT-3 | Check answered wrong | shaming or bare ✗ → shame-abandon | F-03 checks with teaching feedback |
| MoT-4 | Mic fails (noise / permission / no-match) | dead end → voice feature distrusted forever | F-06 voice error recovery + typing fallback |
| MoT-5 | Language switch | half-translated page or hidden machine-translation → trust loss | F-04 page language switching (honest MT flag) |

Emotional curve (hypothesis, confidence low — Gate-B sessions are the validation):
Arrives = cautious curiosity · Reads = engaged (sim) · Asks = vulnerable (speaking a doubt is
brave) → must feel safe · Practices = tense → relieved (feedback teaches) · Returns =
"this helped" only if MoT-1/3/4 all passed. [ASSUMPTION]

### 2.4 Product metrics (every feature card cites ≥1)

| Metric | Definition | Gate link |
|---|---|---|
| M1 **Restatement rate** | kid restates concept in own words + answers 2 follow-ups | Gate B |
| M2 **Voice latency p90** | end-of-speech → first spoken audio, deployed site | Gate C (< ~4 s) |
| M3 **Doubt success rate** | spoken doubts answered context-appropriately (rubric-scored) | demo rehearsal + EVT sampling |
| M4 **Check engagement** | attempts per page / checks shown; first-attempt pass rate | telemetry EVT-004 |
| M5 **Edit rate** | manual edits per generated topic (pipeline reliability) | already measured by factory |
| M6 **Session depth** | blocks interacted with per session; sim interactions per page | EVT-002/003 |
| M7 **Credit burn** | Prisma minutes + Timbre chars per session vs budget | EVT-007/008, admin dashboard |

---

## 3. Tension decisions (T1–T12)

<!-- PHASE-4 CONTENT -->

---

## 4. Feature cards (survivors)

<!-- PHASE-5 CONTENT -->

---

## 5. Screens, elements, information

<!-- PHASE-6 CONTENT -->

---

## 6. Traceability summary

<!-- PHASE-7 CONTENT -->

---

## 7. Self-review + Doc Change Proposals

<!-- PHASE-8 CONTENT -->

---

## 8. Backend handoff (for the systems-design stage)

<!-- PHASE-7 CONTENT — mirrored in backend-handoff.md -->
