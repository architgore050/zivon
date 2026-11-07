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

Hard boundaries respected throughout (never re-decided here): Gnani voice stack fixed
(Prisma v3.0 + Timbre v3.0 — latest versions, founder decision 2026-11-07; runtime LLM =
**Gemma 4 26B A4B** per the Gate A outcome recorded 2026-11-07, Evon v3.3 now the
post-challenge aspiration); Gate C latency
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

Each: **decision · rejected alternative · deciding principle · how we'll know it was wrong ·
flag** (ADR = systems-impacting, goes to Stage 2's ADR list; DCR = Doc Change Proposal to
the doctrine owner).

| ID | Decision | Rejected alternative | Deciding principle | Falsification test | Flag |
|---|---|---|---|---|---|
| **T1** | Narration + visuals with **short labels only** by default. The voice dock shows the **final tutor transcript by default** (it doubles as status + a11y caption surface); live partial transcript is opt-in P1; lesson text is never duplicated as full captions. Per-user memory of the toggle. | (a) audio-only (fails a11y + noisy room); (c) always full text+audio duplication (Mayer redundancy cost) | Mayer redundancy/modality [STRONG] balanced against WCAG captions-for-audio [STRONG] | Kid test: do testers glance at the transcript or ignore it? Learning outcome equal-or-better with captions off vs on (Gate-B style A/B) | none (copy rule) |
| **T2** | Language model: **UI languages = English / हिन्दी / Hinglish** (Hinglish in Roman script, house style: Devanagari for physics terms where natural, else English term kept). Hinglish is *also* the tutor's default speech style. Bar shows autonyms. v1 = 3 languages; bar chips wrap (doctrine §10.5) so ≥5 is a data change not a redesign. RTL out. **Revision 2026-11-07 (founder correction):** the product language set is **all Gnani-supported languages**, not just the three demo ones — verified against docs.gnani.ai today: Prisma v2.5/v3.0 STT = 10 languages (bn-IN, en-IN, gu-IN, hi-IN, kn-IN, ml-IN, mr-IN, pa-IN, ta-IN, te-IN; en-IN accepts EN-HI mixed audio); Timbre v2.5 = 42 voices, one preferred language each (incl. a dedicated **Hinglish voice Poorvi**, `hi-en`); Timbre v3.0 = 13 voices, **each speaking all 10 languages**; Evon v3.3 = 11 Indian languages native. EN / हिन्दी / Hinglish = **demo subset**, not the ceiling; the bar stays data-driven (wrap rule already handles ≥5). Page translation remains a **separate second-layer pipeline** (SC-01) — the factory produces English natively. **Model versions (founder decision 2026-11-07): Prisma v3.0 + Timbre v3.0 adopted** — `indic-auto` detection + polyglot voices are the mechanism this revision runs on. | Hinglish as tutor-style only (page stays English); single "Hindi" covering both scripts | J4 (read at thinking speed) + the challenge's code-mix story [STRONG] | Kid preference sessions (Gate-B rounds): which UI language do testers stay in? Label-length audit at 360 px | **ADR** (per-string language data model; STT language hints; TTS voice choice) |
| **T3** | **Push-to-talk default** (tap-to-start, tap-or-endpoint-to-stop). Hands-free VAD is a P2 opt-in. | Hands-free default (false triggers in noisy shared rooms; always-on mic for a child) | Noisy shared room is the base case (repo rule) + child privacy | EVT-010 voice_abandon + false-trigger rate in field logs; quiet-room vs noisy-room session comparison | **ADR** (WebSocket PTT message contract) |
| **T4** | Doctrine already names the Devanagari fallback stack (§10.3) — the gap is **verification**: LessonKit baseline alignment, canvas `fillText` font stack, and the row rhythm under Hindi strings are unproven. File **DCR-001**: doctrine gains a "Devanagari rendering verification" clause (no tofu, rules hold, canvas stack pinned) + the pipeline vendors Kalam/Nirmala-class faces. Never ship tofu. | Ship Hindi strings on the unverified stack; or drop Hindi from v1 | Doctrine owner decides doctrine; honesty + a11y [STRONG] | Device test: Hindi page at 360 px — zero tofu, rules under baselines after resize (perf-gate extension) | **DCR-001** |
| **T5** | **Explicit + session-scoped only.** Explicit settings (language, pace, Guide/Tell, data-saver) and session coverage memory. **Persistent inferred profile: KILLED** (not deferred) — behavioural profiling of children. Cross-session *explicit* progress deferred to post-challenge with counsel. | Guardian-consented persistent memory now; inferred difficulty model | DPDP Rules 2025 bar tracking/behavioural monitoring of children (Act §8 duty + Rules; **verified 2026-11-07**: children's-data provisions fall in the "remaining provisions" batch in force **13 May 2027** per the MeitY commencement notification G.S.R. 843(E) of 13 Nov 2025, via secondary sources; counsel still required) + repo hard rule P9 | Legal review outcome; if killed profiling later proves necessary, it returns only as a counsel-cleared, purpose-limited feature | **ADR** (data model must preclude profiling by default) |
| **T6** | **Anonymous device-scoped profile** (localStorage: language, settings, session pointers; pseudonymous session id server-side). Data model gives every table a nullable `guardian_ref` column so a guardian identity can attach later. No accounts, no auth — TIMELINE boundary respected. | Magic-link guardian identity now; per-lesson anonymous profiles | Scope fit (TIMELINE out-of-scope list) while still serving J5/J6 | Field signal: share of sessions from a new device wanting prior memory (measured via EVT-001 device-new rate) | **ADR** (identity model) |
| **T7** | Tutor may **highlight, scroll, and narrate** (visible, narrated, non-destructive). Tutor **setting** a sim value: P2, only with visible undo + spoken narration of the change. | Full page agency now | User control + honesty (P8/P7); conceptual model "the tutor points, I move" | Undo-usage rate; kid-test observation of confusion/annoyance when tutor moves a slider | **ADR** (tutor→page message types) |
| **T8** | **Build-time reviewed** translation and (later) narration for all lesson content via the factory (glossary + reviewer gate per language). **Runtime only for tutor speech.** No runtime page translation. | Runtime LLM translation per visit | Physics terminology correctness is a correctness risk not cosmetic [STRONG]; cost/latency | Per-language launch gate = reviewer approval rate ≥ threshold before a language ships; terminology complaint rate via report-a-problem | **ADR** + content-factory schema proposals SC-01/SC-02 (see handoff §7) |
| **T9** | **Socratic default**; one-tap "Explain directly" in the dock (P1); after 2 failed attempts on the same check the tutor *offers* direct explanation (never forces). | Mode buried in settings; always-direct; always-Socratic | P5 retrieval practice vs J1 exam-eve frustration [MODERATE] | Toggle usage rate; follow-up-question rate after direct explanations; M1 in A/B sessions | none |
| **T10** | **P0 is not expanded.** P0 here = TIMELINE ladder exactly (≥6 pages, voice doubt-tutor, demo artifacts, low-end Android). Everything else tagged P1 / P2 / post-challenge; this doc *is* the Gate-D ship list + post-challenge roadmap. Founder sign-off at Gate D: **SIGNED OFF as-is, 2026-11-07** — the 16-P0 list stands frozen. | Pulling language switching or dashboard into P0 | Gate D rule + demo safety first | Gate-D sign-off record; if P0 slips, cuts come from P1 first — never from the ladder | none (this doc's priority column is the artifact) |
| **T11** | **No raw audio retention, ever, in the product path**: audio is buffered transiently for STT and discarded; transcripts live in ephemeral server logs (TTL 7 days, flagged child-data) and the dock; pseudonymous aggregates only. Opt-in short-lived debug capture is post-challenge + counsel. | 30-day audio retention for quality debugging | P9 children-first privacy; DPDP minimization [STRONG as law] | Storage audit (zero audio objects); debugging pain measured — if transcript-only logs prove insufficient, revisit with counsel | **ADR** (voice pipeline buffer lifecycle) |
| **T12** | **Anchor + provenance**: the tutor answers about page context it can see; its dock transcript carries a provenance chip ("from: Simulation 2 / NCERT ch. 8"); persona is allowed and encouraged to say "I'm not sure — let's check the page"; report-a-problem path on every page. | Free-knowledge answers beyond the page | P7 honesty + wrong-physics-is-harm [STRONG as principle] | M3 rubric scores on answer correctness; provenance-chip click-through on reports; report rate per topic | **ADR** (context payload + provenance message design) |

Doc Change Proposals raised: **DCR-001** (T4, Devanagari verification clause) and
**DCR-002** (voice dock is a new lesson-page component the doctrine does not yet describe —
proposed §10.12: paper-card device, state visuals, earcon policy; full text in §7).

---

## 4. Feature cards (survivors)

21 cards. Every card cites ≥1 job + ≥1 metric, has EARS behaviour, acceptance criteria,
states, surfaces, backend needs. Screens/regions referenced: **SCR-HUB-01** (Courses hub);
**SCR-LES-01** (Lesson page) regions R1 header · R2 language bar · R3 text blocks ·
R4 diagram · R5 simulation card · R6 check card · R7 worked-example/reveal/glossary ·
R8 sources footer + report · R9 voice dock · R10 consent overlay · R11 settings sheet ·
R12 onboarding hints; **SCR-PRIV-01** (Privacy summary); **SCR-ADM-01** (Admin dashboard v0).

### F-COR-HUB-01 · Courses hub & topic navigation

| Field | Value |
|---|---|
| Layer | COR |
| Summary | The front door: a list of generated topic pages grouped by class, with an honest empty state. |
| Priority | **P0** (built today; grouping slice P1) — P0 ladder requires ≥6 live pages reachable |
| Kano | must-be |
| Decision-log ref | C-001 (C-002, C-003, C-032 merged) |
| Job + moment | J1 · Arrives |
| Value hypothesis | If the hub groups by class, a Class-9 student finds their chapter page without scrolling past other classes — shown by topic_open→first-interaction time. |
| Metrics / events | M6; EVT-017 (hub_view, topic_open) |
| Principles applied | P1 (navigation serves J1) · P2 (no search, no filters — list only) · P7 (empty state says why) |
| Evidence | [STRONG] built; grouping [ASSUMPTION] |
| Depends on / blocks | needs ≥1 factory run (NEED-001/002) |
| Layer-independence | fully static; works with every wrapper/add-on off; works offline after first visit (F-XCT-OFF-01) |

**Behaviour (EARS)**
1. When the hub loads, the system shall render one card per entry in `courses.js` (title, class, chapter, generated date), grouped under class headings when ≥2 classes exist.
2. When `courses.js` is missing or empty, the system shall show the built empty-state paragraph and no broken list.
3. If a card's target file is missing (stale catalogue), the link shall still render; the 404 page behaviour is the host's (state row).
4. While offline (SW cache hit), the hub shall render from cache with the offline chip (F-XCT-OFF-01).

**Acceptance criteria** — AC-1 Given a built site, When opened on 360 px, Then cards are single-column, touch targets ≥44 px, no horizontal overflow. AC-2 Given zero topics, When loaded, Then empty copy names the reason and what happens next. AC-3 Keyboard: each card is a link, focus ring visible. AC-4 Weak Android: hub load within perf gate (measured today). AC-5 Hindi chrome (P1 slice): grouping headings translated; untranslated → English. AC-6 Privacy: hub sets no cookies; only local flags.

**States** | default: grouped cards · loading: native (static HTML) · empty: built copy · partial: some classes have topics · error: 404 target (host page) · offline: cached render + chip · permission-denied: n/a (public) · reduced-motion: n/a (no motion) · untranslated: English + notice (P1) · quota-exhausted: n/a · consent-missing: n/a (voice consent is per voice use)

**Surfaces** SCR-HUB-01 · EL-HUB-001…008 · INF-001…008, INF-084 · NEED-001, NEED-002 · ENT?-PageMeta · EVT-017, EVT-001, EVT-016

**Backend needs** NEED-001 static delivery (exists); NEED-002 catalogue data (exists as `courses.js`; keep generated, never hand-edited).

**Entities** ENT?-PageMeta (course_id, class, title, chapter, generated_at, sources[], translation availability post-SC-01).

**Cost & risk** zero added bytes for P0; grouping ≤1 KB JS. Risk: stale catalogue after failed run — mitigated by publish staleness guard (already built).

**Open questions** — Q: card order newest-first or class-then-chapter? owner: frontend Day-9 · blocking: n.

### F-COR-LES-01 · Lesson reading surface

| Field | Value |
|---|---|
| Layer | COR |
| Summary | The generated chapter taught in full: objectives, typed text on ruled paper, one underlined statement to remember, worked examples, method reveals, glossary. |
| Priority | **P0** (built) |
| Kano | must-be |
| Decision-log ref | C-005 (C-007, C-013 merged; C-031 as state row) |
| Job + moment | J2 · Reads |
| Value hypothesis | If every chapter section is taught with a signaled key statement, ≥2/3 kids restate the concept (Gate B). |
| Metrics / events | M1; EVT-001, EVT-002 |
| Principles applied | P4 (one highlighted statement, no decoration) · P2 (single column until Day-9 grid) · P5 (taught-before-tested ordering enforced by factory) · P7 (JS-off: text still readable) |
| Evidence | [STRONG] Mayer signaling; built |
| Depends on / blocks | factory stages 02/06 (exists) |
| Layer-independence | fully readable with voice/TTS/translation off |

**Behaviour (EARS)**
1. When a lesson page loads, the system shall show header (title, course kicker, meta line, objectives) then blocks in authored order.
2. When a block is a highlighted statement, the system shall render it as its own paragraph with the generated pen underline (shell-owned).
3. When a worked example or reveal is present, its steps shall be native `<details>` (zero-JS openable).
4. If `zivon.js` fails to load, the system shall still render all text/diagrams; interactive cards shall show their static content (state row), never blank.

**Acceptance criteria** — AC-1 kid can read start-to-finish on 360 px without horizontal overflow (perf-gate overflow check exists). AC-2 Given reduced-motion, Then no animation anywhere (none exist today). AC-3 Screen reader: headings ordered, objectives list announced. AC-4 Weak Android: page within `weak-android` profile (measured per run). AC-5 Hindi (P1): body falls back per glyph per doctrine §10.3; no tofu (DCR-001 test). AC-6 Privacy: reading stores nothing server-side beyond EVT-001 aggregate.

**States** | default: full page · loading: static HTML paint (no spinner) · empty: n/a (factory never ships an empty page — hard error upstream) · partial: a block whose sim JS failed shows the on-canvas error painter; text intact · error: kit-missing guard (lesson-kit throws in example; shell logs) · offline: cached full page · permission-denied: n/a · reduced-motion: static · untranslated: English + notice (P1) · quota-exhausted: n/a · consent-missing: n/a

**Surfaces** SCR-LES-01.R1/R3/R7 · EL-LES-01-001…011, 032…036 · INF-009…013, 018, 019, 043…049 · NEED-001 · ENT?-PageMeta · EVT-001, EVT-002

**Backend needs** NEED-001 (exists). No new capability for P0.

**Entities** ENT?-PageMeta (manifest.json exists: chapter, sources, block_counts, generated_at).

**Cost & risk** built; fonts bundled locally (bytes fixed). Risk: overlong Hindi strings breaking row rhythm — DCR-001 test.

**Open questions** — Q: two-column grid Day-9 — pairing rule which blocks pair? owner: founder/frontend · blocking: n (Day-9).

### F-COR-DIA-01 · Diagrams

| Field | Value |
|---|---|
| Layer | COR |
| Summary | Clean SVG drawn on the paper with hand-annotated labels; every diagram speaks (aria-label) and can carry a long description. |
| Priority | **P0** (built; longdesc slice P1) |
| Kano | performance (more clarity → better learning) |
| Decision-log ref | C-014 (C-016 merged) |
| Job + moment | J2 · Reads |
| Value hypothesis | If diagrams pair words+pictures with annotated quantities, restatement quality (M1) rises vs text-only recall. |
| Metrics / events | M1; EVT-002 (diagram focus) |
| Principles applied | P4 (multimedia) · P7 (honest scale: arrow length ∝ magnitude, stated in caption) · P10 (fixed box scales via container query — built) |
| Evidence | [STRONG] Mayer multimedia |
| Depends on / blocks | factory 02 (SVG authored), 09-review (doctrine check) — exist |
| Layer-independence | static SVG; works with everything off |

**Behaviour (EARS)**
1. When a diagram renders, the system shall include an `aria-label` listing its labels (built today).
2. When P1 longdesc is present, the system shall offer it as a `<details>` "Describe this figure" under the caption.
3. If the SVG fails the frame-adaptation overflow gate, the run never ships the page (harness guarantee, exists).
4. When translated (P1), annotation labels swap language; quantity symbols (F, 10 N) never translate.

**Acceptance criteria** — AC-1 caption + figure readable at 360 px (perf gate). AC-2 Screen reader reads label list. AC-3 Colour-blind check: meaning carried by shape/words, not hue alone (doctrine enforces). AC-4 No external refs (lint enforces). AC-5 Hindi labels render with Caveat→Kalam stack, no tofu. AC-6 n/a privacy.

**States** | default: figure+caption · loading: inline (no wait) · empty: n/a · partial: longdesc absent → aria-label only · error: n/a (authored SVG) · offline: cached · reduced-motion: n/a (static) · untranslated: English labels + notice · others n/a

**Surfaces** SCR-LES-01.R4 · EL-LES-01-014…017 · INF-022…026 · NEED-001, NEED-016 (P1) · ENT?-PageMeta · EVT-002

**Backend needs** NEED-001; P1: NEED-016 for label strings (SC-01).

**Entities** ENT?-PageMeta. **Cost & risk** built; longdesc adds ≤2 KB/page. Risk: thin aria-labels — 09-review checklist item.

**Open questions** — Q: longdesc authored by factory or shell-generated from SVG labels? owner: content-factory · blocking: n.

### F-COR-SIM-01 · Interactive simulations

| Field | Value |
|---|---|
| Layer | COR |
| Summary | Taped paper cards the student operates: sliders with live values, a canvas that responds physically, a text mirror of every state, a reset. |
| Priority | **P0** (runtime + wiring built; state mirror P0 slice; reset + drag-alternative P1) |
| Kano | performance → delighter when direct-manipulation sims arrive |
| Decision-log ref | C-017 (C-018, C-022 merged; C-021 P1 slice) |
| Job + moment | J2 · Reads (MoT-2) |
| Value hypothesis | If students manipulate and immediately see physical consequence, conceptual gain roughly doubles (Hake) — shown by M6 + M1. |
| Metrics / events | M6; EVT-003 |
| Principles applied | P3 (start still — runtime honors; no autoplay) · P8 (reset) · P10 (rAF loop, 24 fps floor under 4× throttle) · P2 (≤3 control groups) |
| Evidence | [STRONG] Hake + PhET |
| Depends on / blocks | ZivonSim runtime (exists); SC-02 for units/state template |
| Layer-independence | sims are pure client-side; voice off, TTS off — fully work |

**Behaviour (EARS)**
1. When a sim loads, the system shall draw `default_behaviour` once and not animate autonomously (reduced-motion: static frame only).
2. When a control changes, the system shall update canvas + readout `<output>` + the aria-live state mirror within one frame.
3. If sim JS throws, the system shall paint the error on canvas (exists) and the state mirror shall say "This simulation stopped working."
4. When reset is pressed (P1), all controls return to `initial` values and the mirror announces it.
5. If a sim has a draggable object (P1, SC-07), the system shall also provide arrow-key nudge or +/- buttons (WCAG 2.2 drag alternative).

**Acceptance criteria** — AC-1 first interaction within 2 s of visibility on weak Android (EVT-003 time-to-first-interaction). AC-2 Keyboard: every slider operable; values announced. AC-3 Screen reader: state mirror updates politely (aria-live=polite, no flood). AC-4 Perf gate green (exists). AC-5 Hindi control labels within label budget (1–3 words, wrap allowed). AC-6 Privacy: sim state leaves the device only inside a voice turn (NEED-005) with consent given.

**States** | default: still, default_behaviour drawn · loading: canvas blank until JS (≤1 frame) · empty: n/a · partial: broken sim → loud on-canvas error + mirror text · error: same · offline: fully works (cached) · permission-denied: n/a · reduced-motion: static frame + step-free (P2 revisit C-019) · untranslated: English labels + notice · quota-exhausted: n/a · consent-missing: n/a (sims need no consent)

**Surfaces** SCR-LES-01.R5 · EL-LES-01-018…024 · INF-027…035 · NEED-001, NEED-005 (voice reads mirror) · ENT?-PageMeta · EVT-003

**Backend needs** NEED-001; SC-02 (`unit`, `readout_format`, `state_text_template`) so the mirror + TTS + tutor can read sim state honestly.

**Entities** ENT?-PageMeta. **Cost & risk** built; per-sim factory cost (one model call each). Risk: physically wrong sims — 09-review fact recheck (exists).

**Open questions** — Q: SC-02 adoption timing (blocks mirror quality)? owner: content-factory · blocking: **y** for P1 slices, n for P0 ship.

### F-COR-CHK-01 · Comprehension checks

| Field | Value |
|---|---|
| Layer | COR |
| Summary | MCQ and numeric self-tests: commit an answer, get kind specific feedback, open "Why?", retry freely — never scored on screen. |
| Priority | **P0** (built; per-option misconception feedback P1) |
| Kano | must-be (the product promises testing) |
| Decision-log ref | C-008 (C-012 merged) |
| Job + moment | J3 · Practices (MoT-3) |
| Value hypothesis | If feedback addresses the misconception behind the wrong choice, first-attempt pass rate on re-visits rises (M4). |
| Metrics / events | M4; EVT-004 |
| Principles applied | P5 (answer hidden until commit — built) · P8 (retry, no lock) · P9 (attempt data is telemetry only, never a displayed score) |
| Evidence | [STRONG] retrieval practice |
| Depends on / blocks | factory 02/03 (answer keys reviewed) — exist |
| Layer-independence | fully client-side; works with everything off |

**Behaviour (EARS)**
1. When options are selected and Check pressed, the system shall reveal correctness (shape + words, not hue) + one feedback sentence.
2. When "Why?" opened, the system shall show the explanation `<details>` (built).
3. If numeric format, the system shall parse the first number from the input (built) and compare to the answer key.
4. If P1 option_feedback exists, the system shall show the feedback tied to the chosen distractor.
5. While unanswered, the system shall show no answer hint (answer_index stays unrevealed in UI; DOM exposure accepted, see risk).

**Acceptance criteria** — AC-1 kid completes a check unaided (Gate-B observation). AC-2 Keyboard/screen reader: radiogroup semantics (doctrine §10.6 fix exists), feedback announced politely. AC-3 Retry: reselecting + Check again works, no lock. AC-4 Perf: check cards within page budget. AC-5 Hindi question/option strings (P1) keep units/symbols untranslated. AC-6 Privacy: EVT-004 carries block_id + option_index + attempt_n only — no child identity beyond pseudonymous session.

**States** | default: unanswered · loading: n/a · empty: n/a · partial: feedback shown, Why closed · error: numeric parse miss → "Enter a number like 5" · offline: fully works · permission-denied: n/a · reduced-motion: n/a · untranslated: English + notice (P1) · quota-exhausted: n/a · consent-missing: n/a

**Surfaces** SCR-LES-01.R6 · EL-LES-01-025…031 · INF-036…042 · NEED-001, NEED-010 · ENT?-PageMeta · EVT-004

**Backend needs** NEED-001; SC-03 (`option_feedback[]` per check) for P1 slice.

**Entities** ENT?-PageMeta. **Cost & risk** built. Risk: answer key in DOM (`data-answer-index`) — accepted for static MVP, flagged for post-challenge hardening.

**Open questions** — Q: SC-03 per-option feedback — factory prompt + reviewer burden acceptable? owner: content-factory · blocking: n (P1).

### F-COR-PROV-01 · Provenance & citations

| Field | Value |
|---|---|
| Layer | COR |
| Summary | Every page says where its content came from: NCERT/open sources with licenses, chapter pages, generation date — and students can report a problem. |
| Priority | **P0** (footer + manifest built; report button P1) |
| Kano | must-be (licensing + trust) |
| Decision-log ref | C-028 (C-030 merged; C-029 deferred) |
| Job + moment | J1 · Reads; J6 (guardian trust) |
| Value hypothesis | If provenance is visible, guardians trust the product and wrong-physics reports reach ops (EVT-014 volume). |
| Metrics / events | EVT-014; report-resolution SLA (ops metric) |
| Principles applied | P7 (honesty) · P1 (safety valve for T12) |
| Evidence | [STRONG] as principle |
| Depends on / blocks | report inbox in F-OPS-ADM-01 |
| Layer-independence | static text; report needs backend |

**Behaviour (EARS)**
1. When a lesson page renders, the footer shall name sources with licenses (built) and the manifest shall carry the same (exists).
2. When Report pressed (P1), the system shall submit page_id, block_id (from focus region), category (wrong physics / bad translation / broken sim / other), optional short text.
3. If the report endpoint is down, the button shall show "Could not send — try again" and keep the draft text.
4. The system shall never ask for name/contact on the report form (child-data rule).

**Acceptance criteria** — AC-1 sources visible without scrolling past 2 blocks on 360 px. AC-2 Keyboard operable form. AC-3 Report submission works offline? No — offline state disables with explanation. AC-4 Perf negligible. AC-5 Form labels translated (P1). AC-6 Privacy: reports carry no child identity beyond pseudonymous session; free-text flagged child-data-safe (no solicitation).

**States** | default: footer visible; report button quiet graphite · loading: n/a · empty: n/a · partial: report draft kept unsent · error: send failure copy · offline: disabled + reason · permission-denied: n/a · reduced-motion: n/a · untranslated: English + notice · quota-exhausted: n/a · consent-missing: n/a (report needs no consent; still pseudonymous)

**Surfaces** SCR-LES-01.R8 · EL-LES-01-037…041 · INF-050…055 · NEED-014 · ENT?-ProblemReport, ENT?-PageMeta · EVT-014

**Backend needs** NEED-014 report submission.

**Entities** ENT?-ProblemReport (page, block, category, text, status, ts; no PII). **Cost & risk** tiny. Risk: report spam → rate-limit (Stage 2).

**Open questions** — Q: per-block citation display (C-029) timing? owner: content-factory · blocking: n.

### F-WRP-LAN-01 · Page language switching (language bar)

| Field | Value |
|---|---|
| Layer | WRP |
| Summary | One bar at the top of a lesson switches every string on the page — English / हिन्दी / Hinglish — with honest flags for anything not yet translated. |
| Priority | **P1** (doctrine §10.5 Day-9 item; T10 keeps P0 intact) |
| Kano | performance (must-be once Hindi users exist) |
| Decision-log ref | C-034 (C-035…C-039, C-042…C-046 merged) |
| Job + moment | J4 · Reads (MoT-5) |
| Value hypothesis | If the whole page switches language, Hindi-first kids finish pages and pass checks at rates near English (M4 parity). |
| Metrics / events | EVT-011; M4 by language |
| Principles applied | P7 (MT flag + never silent mixing) · P2 (one control switches everything) · T2 decision |
| Evidence | [STRONG] mother-tongue comprehension; [ASSUMPTION] our string supply |
| Depends on / blocks | blocks on SC-01 (factory translations) for real Hindi content; bar UI itself independent |
| Layer-independence | Core fully works with this off; this feature never touches voice/TTS internals |

**Behaviour (EARS)**
1. When the bar is pressed, the system shall swap title, body, diagram labels, sim labels, check strings, feedback, chrome copy, and set `lang` on the document.
2. When a block lacks a translation for the chosen language, the system shall show English text plus a visible "not translated yet" marker — never silent mixing.
3. When translated content is machine-generated (factory MT pass), the system shall show a one-time "machine translated" flag on first use of that language (per page).
4. The system shall persist the choice per device (localStorage) and apply it on next page load.
5. The system shall never translate SI units, symbols, or equations; English physics term + gloss on first mention (glossary carries glosses).

**Acceptance criteria** — AC-1 switch completes < 200 ms client-side (string bundles preloaded lazily per language). AC-2 Keyboard: chips form a radiogroup (doctrine). AC-3 Longest-language audit: Hindi labels fit 1–3-word budget, chips wrap, no overflow at 360 px. AC-4 Offline: already-fetched language bundle works; unfetched → English + notice. AC-5 Untranslated fallback visible. AC-6 Privacy: language choice stored locally only; server sees it only as an aggregate EVT-011.

**States** | default: English (or remembered choice) · loading: bar visible, bundle fetch < 200 ms target · empty: n/a · partial: some blocks untranslated + markers · error: bundle fetch fail → stay current language + "couldn't load" chip · offline: cached bundle works; else English · permission-denied: n/a · reduced-motion: n/a · untranslated: the feature's own partial state · quota-exhausted: n/a · consent-missing: n/a

**Surfaces** SCR-LES-01.R2 · EL-LES-01-006…009 · INF-014…017 (chrome), translated variants of INF-018…048, INF-049, 087, 088 · NEED-016 · ENT?-LanguageBundle · EVT-011

**Backend needs** NEED-016 language bundle delivery: static JSON per (page, language), generated by factory (SC-01), fetched on first switch, cached by SW.

**Entities** ENT?-LanguageBundle (page_id, lang, strings keyed by block_id+field, mt_flag, reviewed_flag, version). **Cost & risk** ~10–30 KB per page-language; factory review cost per language (T8 gate). Risk: bad terminology → report path + reviewer gate.

**Open questions** — Q: Hinglish orthography house style sheet — **revised 2026-11-07 (founder)**: translation is a **separate second-layer pipeline** (SC-01, not yet built; factory produces English natively), so the per-language style sheet defers with that pipeline — it blocks only the pipeline's launch, not the demo. What the P0 voice loop needs now is Stage-2 prompt rules (reply in the student's language/mix; never-translate units/terms). Language set = all Gnani languages (10 STT languages verified 2026-11-07); EN/HI/Hinglish = demo subset. owner: founder + native reviewer (style sheet) / Stage 2 (voice rules).

### F-WRP-TTS-01 · Read-aloud of lesson content

| Field | Value |
|---|---|
| Layer | WRP |
| Summary | A speaker button on each text block reads that paragraph aloud in the page language (Timbre), with a stop control; audio focus yields to the mic. |
| Priority | **P1** |
| Kano | performance (accessibility multiplier) |
| Decision-log ref | C-050 (C-027, C-055 merged; C-051/052/053 deferred) |
| Job + moment | J4 · Reads |
| Value hypothesis | If low-literacy kids can hear paragraphs, page completion and M1 rise for them specifically. |
| Metrics / events | EVT-012; M7 (credit burn per page) |
| Principles applied | P4 (modality) · P7 (spoken form differs from on-screen: units spoken in full) · P10 (on-demand fetch only, no prefetch in data-saver) |
| Evidence | [STRONG] Mayer modality; [ASSUMPTION] credit cost model |
| Depends on / blocks | voice backend exists (Timbre client reused); NOT dependent on the tutor |
| Layer-independence | works with voice agent off; voice agent works with this off |

**Behaviour (EARS)**
1. When the speaker button is pressed, the system shall request block narration (NEED-017) and stream audio, showing progress on the button.
2. While read-aloud audio plays and the mic opens (F-ADD-VOI-01), the system shall pause read-aloud (audio focus).
3. If TTS fails or credits are exhausted, the system shall say "Read-aloud is unavailable right now" and the text stays fully usable.
4. When data-saver is on, the system shall not prefetch any audio and shall warn once per session that read-aloud uses data + credits.
5. The system shall speak the block's *spoken form* (SC-06 when available; else block text with unit-pronunciation rules), not raw markup.

**Acceptance criteria** — AC-1 first audio byte < 1.5 s p90 (separate from Gate C). AC-2 Stop control always visible while playing. AC-3 Screen reader unaffected (button announced; audio is not a live region). AC-4 Weak Android: no jank while streaming (perf gate). AC-5 Hindi text → Hindi voice (Timbre language param); untranslated block → read-aloud disabled with reason. AC-6 Privacy: read-aloud requests carry page/block ids only, never device identity beyond session pseudonym.

**States** | default: quiet button per block · loading: streaming indicator · empty: n/a · partial: some blocks speakable (text/worked_example/check stem) others not (diagram caption only on request) · error: TTS fail copy + retry · offline: previously played clips replay; new ones disabled + reason · permission-denied: audio autoplay blocked → user-initiated only (built-in constraint) · reduced-motion: n/a (audio not motion) · untranslated: disabled + reason · quota-exhausted: disabled + budget copy (F-XCT-OFF-01) · consent-missing: n/a (read-aloud is not voice input; no consent gate — flagged: uses third-party TTS, disclosed in privacy page)

**Surfaces** SCR-LES-01.R3/R7 (buttons) · EL-LES-01-012 · INF-020, 089 (labels/copy; spoken content = source blocks INF-018…048) · NEED-017, NEED-008, NEED-009 · ENT?-PageMeta · EVT-012, EVT-007

**Backend needs** NEED-017 block narration (page_id, block_id, lang → streamed audio, cached server-side per block+lang+version); reuses NEED-008 Timbre client; metered by NEED-009.

**Entities** ENT?-PageMeta. **Cost & risk** Timbre chars ≈ paragraph length × attempts; cache makes repeats free. Risk: credit burn — budget guard can disable read-aloud before it disables the tutor (priority order stated: tutor first).

**Open questions** — Q: pre-generated narration (C-051) adoption? owner: founder + factory · blocking: n.

### F-ADD-VOI-01 · Voice dock (mic entry + state machine + transcript)

| Field | Value |
|---|---|
| Layer | ADD (XCT states) |
| Summary | The paper-card dock on every lesson page: press to speak, see/hear every state (listening, thinking, speaking), interrupt with one tap, read what was said. |
| Priority | **P0** (the challenge core; live partial transcript slice P1) |
| Kano | must-be |
| Decision-log ref | C-056 (C-054, C-057, C-058, C-060, C-078, C-084, C-096 merged; C-081 P1 slice) |
| Job + moment | J1 · Asks (MoT-1, MoT-4) |
| Value hypothesis | If a kid can press, ask in Hinglish, and hear a reply in < 4 s, doubt-resolution sessions happen (M2, M3). |
| Metrics / events | M2, M3; EVT-005, EVT-006 |
| Principles applied | P6 (every state visible + audible) · P8 (barge-in) · P7 ("I'm an AI" line) · T1/T3 decisions |
| Evidence | [STRONG] repo mandate; state-machine practice [WEAK-MODERATE] |
| Depends on / blocks | NEED-003/004/006/007/008/009 (voice backend — to build); consent F-XCT-CON-01 gates first use |
| Layer-independence | the whole ADD layer is off-switchable: dock collapses to a quiet "tutor unavailable" state; Core untouched |

**Behaviour (EARS)**
1. When the mic button is pressed (push-to-talk), the system shall move dock → listening with an earcon + visual, and open the voice channel (NEED-004).
2. When end-of-speech is detected, the system shall show "thinking" within 300 ms and stream the reply: partial text may appear before audio; first audio target < 4 s (Gate C).
3. When the student taps the dock or speaks while the tutor is speaking, the system shall stop TTS within 300 ms and return to listening (barge-in).
4. When a turn completes, the dock shall show the final transcript + tutor text + provenance chip (F-ADD-VOI-02) — captions default per T1.
5. If mic permission is denied or mic is in use, the dock shall show the typed fallback (F-ADD-VOI-03) and never re-prompt more than once per session.
6. The dock shall show the one-time "I'm an AI" identity line on first open.

**Acceptance criteria** — AC-1 Gate C rehearsal: Hinglish doubt → first audio < 4 s on deployed site, measured by EVT-006 p90. AC-2 Every state has a visible + audible cue; screen reader announces state changes politely. AC-3 Barge-in works while speaker output is loud (mic picks up tutor voice — echo handling). AC-4 Weak Android: dock ≤ 60 KB JS loaded lazily on first mic tap (P10 lazy-load rule). AC-5 Hindi/Hinglish labels within budget; untranslated → English dock copy. AC-6 Consent (F-XCT-CON-01) precedes first listening; no audio retained (T11).

**States** (full machine) | idle: quiet chip "Ask a doubt" · requesting-permission: browser prompt + explainer line · ready: mic enabled · listening: pulsing ring + live level meter + earcon in · endpointing: "…got it" micro-state · thinking: animated pen-dot + "thinking" (≤300 ms) · speaking: waveform + tutor text streaming + Stop control · interrupted: instant return to listening · no-input (silence > 5 s): "I didn't hear anything — press and speak" · no-match: "I didn't catch that — say it again or type it" (→ F-ADD-VOI-03) · system-error: "The tutor hit a problem. Try again." + retry · offline: dock disabled + reason (Core intact) · quota-exhausted: "Voice is resting (daily limit). Type your doubt." (typed mode via NEED-004 text path) · mic-denied: fallback shown · mic-in-use: explanation + fallback · unsupported-browser: explanation + typed fallback · consent-missing: consent overlay (F-XCT-CON-01) shown first · reduced-motion: static state indicators · loading (channel open): "connecting" ≤ 1 s then error state

**Surfaces** SCR-LES-01.R9 · EL-LES-01-042…049, 051…053 · INF-056…068 · NEED-003, NEED-004, NEED-006, NEED-007, NEED-008, NEED-009, NEED-012 · ENT?-Session, ENT?-VoiceTurn · EVT-005, EVT-006, EVT-009, EVT-010, EVT-013

**Backend needs** see realtime section (handoff §3): PTT start/stop, audio frames up, partial/final transcript down, tutor text stream down, TTS audio chunks down, interrupt up, cancel down, latency meta down.

**Entities** ENT?-Session (pseudonymous), ENT?-VoiceTurn (transcript TTL 7 d server log, audio_retained=false). **Cost & risk** Prisma minutes + Timbre chars per turn (metered); battery: mic only while listening; echo/feedback loop in speaker→mic path (device testing). Risk: Gate C miss → Gate C fallback per TIMELINE (shorter replies, hybrid mode).

**Open questions** — Q: earcon set (3 sounds) authored where? owner: frontend Day-9 · blocking: n. Q: exact Timbre tag set — **resolved 2026-11-07 from docs.gnani.ai**: 13 tags, **Timbre v3.0 only** (v2.5 strips tags before synthesis). Replaced by: Q: Prisma/Timbre **model version v2.5 vs v3.0** (v3.0 adds `indic-auto` auto language detection + expressive tags) — owner: founder · blocking: **y** for expressive tags (C-069) and language-agnostic STT, n for plain voice on v2.5.

### F-ADD-VOI-02 · Page-context anchoring

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | The tutor knows what you're looking at: the block in view, the sim's current values, your last check result — and the dock shows what it's asking about. |
| Priority | **P0** (auto-anchor + chip); **P1** per-block "Ask about this" |
| Kano | delighter → must-be for answer quality |
| Decision-log ref | C-061 (C-062 merged; C-026 P1 slice) |
| Job + moment | J1 · Asks (MoT-1) |
| Value hypothesis | If answers reference the on-screen block/sim state, M3 context-appropriateness ≥ 80% on rubric. |
| Metrics / events | M3; EVT-005 (anchor_source field) |
| Principles applied | P7 (anchor chip = conceptual model: "sees this page, not the room") · T12 (answers stay anchored) |
| Evidence | [STRONG] hybrid-B+ architecture decision (TIMELINE Day 5) |
| Depends on / blocks | F-ADD-VOI-01; NEED-005 |
| Layer-independence | if context payload fails, tutor answers generically with a visible note — never blocks |

**Behaviour (EARS)**
1. When a voice turn starts, the client shall send the context snapshot: page_id, visible block ids + types + titles, sim control values + state mirror text, last check (block, correct/incorrect, option index), language, session coverage summary (F-ADD-MEM-01).
2. When the turn is answered, the dock shall show the anchor chip ("Asking about: <block title or 'the whole page'>").
3. When "Ask about this" is pressed on a block (P1), that block becomes the explicit anchor for the next turn.
4. If the snapshot is incomplete server-side, the tutor shall say what it cannot see and ask the student to describe it (honesty, never fake anchoring).

**Acceptance criteria** — AC-1 rubric-scored sample of 20 doubt turns: ≥80% reference the actual on-page state (M3). AC-2 Chip visible within 1 s of answer start. AC-3 Keyboard: ask-about-this button reachable per block. AC-4 Payload ≤ 4 KB per turn (cost). AC-5 Anchor chip label translated (P1). AC-6 Privacy: payload contains page state only — no camera, no room audio, no identity.

**States** | default: auto-anchor = block nearest viewport center · loading: n/a · empty: whole-page anchor when nothing focused · partial: missing sim values → tutor told "values unavailable" · error: payload fail → generic answer + visible note · offline: n/a (voice off) · permission-denied: n/a · reduced-motion: n/a · untranslated: chip label English fallback · quota-exhausted: n/a (typed mode carries the same payload) · consent-missing: n/a

**Surfaces** SCR-LES-01.R9 (chip) + per-block buttons (P1) · EL-LES-01-013, 050, 056 · INF-021, 064 · NEED-005, NEED-007 · ENT?-VoiceTurn · EVT-005

**Backend needs** NEED-005 context payload composition into the LLM prompt (Gemma 4 26B A4B per Gate A outcome 2026-11-07; Stage 2 designs the prompt assembly; product states the payload contract above).

**Entities** ENT?-VoiceTurn.anchor. **Cost & risk** prompt tokens per turn (Gemma 4 26B A4B self-hosted — no Gnani credit, GPU cost). Risk: wrong anchoring misleads → chip honesty + T12.

**Open questions** — Q: scroll-observer definition of "visible block" (≥50% area?) owner: frontend · blocking: n.

### F-ADD-VOI-03 · Voice error recovery & typed fallback

| Field | Value |
|---|---|
| Layer | ADD XCT |
| Summary | Every voice failure has a kind next step: re-ask in the student's language, "you can say…" help after 3 misses, or type the doubt — never a dead end. |
| Priority | **P0** |
| Kano | must-be (MoT-4 decides trust) |
| Decision-log ref | C-063 (C-064 merged) |
| Job + moment | J1 · Asks (MoT-4) |
| Value hypothesis | If failures always end in an action, voice-abandon rate (EVT-010) stays < 20% of voice sessions. |
| Metrics / events | M3; EVT-010, EVT-009 |
| Principles applied | P8 (no dead ends) · P7 (plain-language copy) · voice error taxonomy [WEAK-MODERATE] |
| Evidence | [WEAK-MODERATE] practitioner consensus; [ASSUMPTION] thresholds |
| Depends on / blocks | F-ADD-VOI-01 states |
| Layer-independence | typed fallback works over the same channel even when STT/TTS are down — this is the degraded-mode floor (F-XCT-OFF-01) |

**Behaviour (EARS)**
1. If a no-match occurs, the system shall re-ask in the student's language with one concrete example phrase ("You can say: 'reflection kaise hota hai?'").
2. After 3 consecutive failures (no-input/no-match), the system shall offer the typing input prominently and stop auto-listening.
3. When typed mode is active, the system shall keep the same anchoring + tutor + TTS reply path (voice output optional per setting).
4. If the system-error state occurs, retry shall preserve context (no lost conversation).
5. The typed input shall never require the mic.

**Acceptance criteria** — AC-1 scripted test: force no-match ×3 → help + typing offered, conversation continues. AC-2 Typing works keyboard-only + screen reader. AC-3 Copy exists in all 3 languages for every failure (copy keys). AC-4 Offline: typed mode also disabled → "come back when internet returns" + lesson intact. AC-5 Fallback input target ≥ 44 px. AC-6 Typed doubts carry same privacy class as voice (transcript logs TTL 7 d).

**States** inherits the failure rows of F-ADD-VOI-01's state table; adds: fallback-open (input + send), help-shown (example phrases), retrying (context preserved indicator).

**Surfaces** SCR-LES-01.R9 (fallback row) · EL-LES-01-052, 053 · INF-066…068 (failure copy keys) · NEED-004 (text path), NEED-007 · ENT?-VoiceTurn · EVT-005 (modality=typed), EVT-009, EVT-010

**Backend needs** NEED-004 text-turn message type (typed doubt → same pipeline minus STT); NEED-007 unchanged.

**Entities** ENT?-VoiceTurn (modality field). **Cost & risk** near-zero UI; typed mode saves credits during outages. Risk: over-eager help nags → help shown once per failure-type per session.

**Open questions** — Q: failure-count reset window (per session vs per 10 min)? owner: Stage 2 · blocking: n.

### F-ADD-VOI-04 · Tutor conversation & pedagogy

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | The tutor's mind: multi-turn, Socratic by default, mirrors the student's language, stays on-page physics, redirects off-topic gently, and speaks with Timbre's expressive tags. |
| Priority | **P0** (conversation, mirroring, safety, Socratic default); **P1** (Guide/Tell toggle, highlight-sync, expressive tags) |
| Kano | performance (quality is the product) |
| Decision-log ref | C-065 (C-066, C-067, C-068, C-069, C-071, C-077 merged; C-070 deferred) |
| Job + moment | J1 · Asks; J3 · Practices |
| Value hypothesis | If the tutor asks before telling and carries follow-ups, doubt-sessions average ≥ 3 turns with M1 improvement at kid tests. |
| Metrics / events | M1, M3; EVT-005 (turns, redirect_count, tag presence) |
| Principles applied | P5 (speak-the-answer) · P7 (uncertainty allowed) · T7 (highlight/suggest only) · T9 (Socratic default) |
| Evidence | [STRONG] pedagogy; [WEAK-MODERATE] conversation design; tags [WEAK] |
| Depends on / blocks | NEED-007 (LLM serving — **resolved 2026-11-07: Gemma 4 26B A4B**), NEED-008 (**resolved: Timbre v3.0 adopted — 13 tags available**) |
| Layer-independence | persona quality never blocks Core; a bad turn degrades to "let's look at the page together" |

**Behaviour (EARS)**
1. When a doubt is answered, the tutor shall reference the anchor (F-ADD-VOI-02) and stay within the page's physics universe (grounding law mirrors the factory's).
2. When the student answers a Socratic question wrongly, the tutor shall address the misconception and ask one narrower question before explaining.
3. After 2 failed attempts on the same check, the tutor shall offer a direct explanation (T9).
4. The tutor shall reply in the student's language mix (Hinglish default when input is Hinglish).
5. When input is off-topic or unsafe, the tutor shall redirect once gently to physics ("That's outside my page — back to the simulation?") and log the redirect (no punitive tone).
6. When expressive tags are enabled (P1), the LLM may emit Timbre tags per the confirmed Gnani tag set; unknown tags are stripped by the harness (never spoken literally).
7. The tutor may highlight/scroll to the referenced block (P1, narrated); it shall not change sim values (P2 later, T7).

**Acceptance criteria** — AC-1 rubric M3 ≥ 80% on 20-turn sample (context + pedagogy quality). AC-2 Socratic policy observable in transcripts: question-before-explain ratio ≥ 1:2 in doubt sessions. AC-3 Redirect policy: zero personal-data solicitation (audit). AC-4 Latency budget: reply text ≤ 3 sentences default (Gate C enabler). AC-5 Tags: unknown tags never reach Timbre (harness test). AC-6 Privacy: turn text logs TTL 7 d; EVT carries buckets not free text.

**States** | default: Socratic · guide-tell (P1 toggle: guide default, tell mode) · redirect-shown · uncertain-phrasing (persona line) · turn-limit (session length cap: soft nudge "want to continue on the page?" at 20 turns) · all failure states inherited from F-ADD-VOI-01/03 |

**Surfaces** SCR-LES-01.R9/R11 (toggle P1) · EL-LES-01-045, 056, 065 · INF-057, 058, 061, 068, 079 (persona copy keys, toggle labels) · NEED-004, NEED-005, NEED-007, NEED-008, NEED-011 · ENT?-VoiceTurn, ENT?-Session · EVT-005, EVT-006

**Backend needs** NEED-007 turn generation (persona + anchor payload + coverage summary + history window → streamed text with optional tags); NEED-011 coverage summary injection.

**Entities** ENT?-VoiceTurn (tutor_text, tags, redirect_flag, mode). **Cost & risk** Gemma 4 26B A4B tokens per turn (GPU, not Gnani credits); risk: wrong physics → T12 provenance + report path; risk: over-refusal annoyance → redirect tone tested at Gate-B round 2.

**Open questions** — both **resolved 2026-11-07 (founder)**: Gate A outcome = **Gemma 4 26B A4B** runtime LLM (recorded in TIMELINE.md Gate A row); Timbre tag set = 13 tags on **Timbre v3.0** (adopted same day). Remaining: tag-emission prompt quality for Gemma (harness strips unknown tags) — verify at Gate-C rehearsal.

### F-ADD-MEM-01 · Session memory

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | Within one sitting, the tutor knows what you read, simulated, and got right — and you can see and clear exactly what it remembers. |
| Priority | **P0** (session scope); **P1** memory view + clear |
| Kano | performance |
| Decision-log ref | C-072 (C-075 merged; C-073 deferred, C-074 killed) |
| Job + moment | J5 · Returns |
| Value hypothesis | If coverage is carried within a session, repeat-explanation rate drops (EVT-005 duplicate-topic count). |
| Metrics / events | M6; EVT-002, EVT-018 |
| Principles applied | P9 (session-scoped, no profiling) · P7 (memory view = honest personalization) · T5/T6 |
| Evidence | [ASSUMPTION] Day-7 plan item; value hypothesis ours |
| Depends on / blocks | NEED-011; memory view needs only local data |
| Layer-independence | memory off → tutor answers each turn fresh; Core untouched |

**Behaviour (EARS)**
1. When blocks are viewed/simulated/checks attempted, the client shall update the local coverage list and sync a compact summary to the session (NEED-011) at turn boundaries.
2. When a new voice turn arrives, the coverage summary shall be in the tutor's context ("student has covered: balanced forces ✓, net force sim ✓; not yet: action-reaction").
3. When the memory view is opened (P1), the system shall list covered items plainly and offer Clear (confirm-then-clear, local + server TTL note).
4. The system shall expire session memory at 24 h idle (server TTL) and on Clear.

**Acceptance criteria** — AC-1 tutor avoids re-explaining covered content in a scripted 5-turn session (rubric). AC-2 Memory view keyboard accessible; Clear requires confirmation. AC-3 Server TTL enforced (Stage 2 test). AC-4 Works offline locally; syncs on return. AC-5 View labels translated (P1). AC-6 Privacy: coverage list is the only memory; no scores, no ability inferences; child-data flagged (consent-bearing per F-XCT-CON-01).

**States** | default: silent accumulation · empty: fresh session · partial: offline → local only + "syncing later" · error: sync fail → local continues · permission-denied: n/a · quota-exhausted: n/a · consent-missing: local-only until consent given (server sync off) · others n/a |

**Surfaces** SCR-LES-01.R9/R11 (memory view entry P1) · EL-LES-01-054, 067 · INF-069, 070, 081 · NEED-011, NEED-013 · ENT?-Session · EVT-018

**Backend needs** NEED-011 session coverage store (session_id → covered blocks/checks, TTL 24 h); NEED-013 clear path.

**Entities** ENT?-Session.coverage. **Cost & risk** tiny storage. Risk: memory feels creepy if invisible → view + clear (P1) closes it.

**Open questions** — Q: does memory view ship P0-lite (list only, no clear)? owner: founder · blocking: n.

### F-XCT-CON-01 · Consent & privacy basics

| Field | Value |
|---|---|
| Layer | XCT |
| Summary | Before voice first runs: a one-page plain-language notice ("what we collect, what we never collect") with a guardian confirmation; plus a privacy page and a clear-my-data button. |
| Priority | **P0** (notice + local record); **P1** (privacy page + clear) |
| Kano | must-be |
| Decision-log ref | C-085 (C-086 merged; C-087 deferred to counsel) |
| Job + moment | J6 (guardian) · Asks |
| Value hypothesis | If the notice is honest and short, guardians allow voice use and the demo ships responsibly (completion of first voice session after notice ≥ 90%). |
| Metrics / events | EVT-013 |
| Principles applied | P9 (private-by-default) · P7 (plain copy, no dark patterns) · T5/T6/T11 |
| Evidence | [STRONG] as law-driven principle; DPDP children's-data provisions in force 13 May 2027 (remaining-provisions batch, G.S.R. 843(E); **verified 2026-11-07 via secondary sources; counsel required before scale-up**) |
| Depends on / blocks | gates F-ADD-VOI-01 first use; NEED-012 |
| Layer-independence | consent-missing blocks only the ADD layer (voice); Core fully usable — this is the isolation boundary made visible |

**Behaviour (EARS)**
1. Before the first voice session on a device, the system shall show the consent overlay: what voice use sends (speech → Gnani models → text kept 7 days → no raw audio), who it is not shown to, and a guardian-confirmation checkbox ("I am a parent/guardian or using this with one's OK").
2. If confirmation is declined, the system shall return to the lesson with voice disabled and a quiet "Ask with typing or read the page" state — never re-nag.
3. When confirmed, the system shall record (device_pseudo_id, consent_version, ts) locally + server-side (NEED-012) and enable the dock.
4. The privacy page (P1) shall list every data class with retention and a Clear-my-data action (local wipe + server delete request, NEED-013).
5. The notice shall be re-shown only when consent_version changes.

**Acceptance criteria** — AC-1 overlay readable in ≤ 30 s at 360 px (copy budget ≤ 120 words). AC-2 Keyboard + screen reader complete the flow. AC-3 Declining leaves the page fully usable (Core test). AC-4 Copy in 3 languages (P1 slice; English P0). AC-5 Clear action removes local storage + calls NEED-013 and shows confirmation. AC-6 Audit: no analytics fires EVT-005+ before consent; EVT-001/002 pre-consent are aggregate-safe (no child identity beyond pseudonym) — flagged for legal review.

**States** | default: not-yet-consented (voice chip quiet) · overlay-shown · confirmed · declined (voice disabled, no nag) · version-stale (re-show) · error: consent record save fail → voice stays off + retry · offline: local consent works; server sync later · untranslated: English P0 · others n/a |

**Surfaces** SCR-LES-01.R10, SCR-PRIV-01 · EL-LES-01-057…061, EL-PRV-001…005 · INF-072…076, 090…094 · NEED-012, NEED-013 · ENT?-ConsentRecord, ENT?-DeviceProfile · EVT-013, EVT-018

**Backend needs** NEED-012 consent store; NEED-013 deletion endpoint (device_pseudo_id scope; DPDP 90-day response posture post-challenge).

**Entities** ENT?-ConsentRecord (device_pseudo_id, version, guardian_flag, ts). **Cost & risk** tiny. Risk: self-declared consent ≠ VPC — **flagged for legal review** (C-087), acceptable for demo + founder-supervised kid sessions.

**Open questions** — Q: does the demo link show the overlay to judges? — **resolved 2026-11-07 (founder)**: **show it in both** the demo video (~2–3 s of screen time) and the live link (one Continue tap) — the consent flow is a demo asset, not friction. Demo-script note: overlay copy is English at P0; narrate it in Hinglish.

### F-XCT-OFF-01 · Offline & degraded modes

| Field | Value |
|---|---|
| Layer | XCT OPS |
| Summary | The ladder that keeps Zivon alive: full → static (voice off) → typed-only → offline-reading; and the credit-exhaustion floor that never surprises a student mid-doubt. |
| Priority | **P0** (ladder + over-budget states); **P1** (service worker) |
| Kano | must-be |
| Decision-log ref | C-089 (C-088 merged) |
| Job + moment | J1 · Asks; J2 · Arrives; J7 |
| Value hypothesis | If degradation is designed, a credit outage or flaky network never shows a broken UI — abandon rate during incidents < 30%. |
| Metrics / events | EVT-016, EVT-008; M7 |
| Principles applied | P10 (designed ladder) · P7 (warn before limits, never surprise cut-off) · P8 |
| Evidence | [STRONG] as constraint (repo base case) |
| Depends on / blocks | NEED-009 budget guard feeds quota-exhausted states |
| Layer-independence | this feature IS the independence proof: each rung turns one layer off while Core survives |

**Behaviour (EARS)**
1. When the network drops, the system shall show an offline chip, disable voice/read-aloud with reasons, and keep reading/simulating/checking working (cached pages via SW, P1; browser cache P0).
2. When the credit guard reports warn, the dock shall show "voice is limited today" before sessions start; when exhausted, voice switches to typed mode (NEED-004 text path) with plain copy — an in-progress turn is finished, never cut mid-answer.
3. When connectivity returns, the system shall silently re-enable layers and sync queued local data (memory, EVT batch).
4. The system shall never prefetch audio in data-saver or offline (F-XCT-SET-01).

**Acceptance criteria** — AC-1 airplane-mode test: previously visited page fully readable + sims operable (SW P1; cache P0). AC-2 Budget-exhaustion drill: typed mode answers a doubt end-to-end with zero Gnani credits (self-hosted LLM path). AC-3 Offline chip visible ≤ 1 s after connectivity loss. AC-4 No data loss: queued EVT/memory sync on return. AC-5 Copy in 3 languages (P1). AC-6 Privacy: queued local data respects consent state.

**States** this card defines the offline / quota-exhausted columns of the screen-state matrix (§5.3).

**Surfaces** SCR-LES-01.R9 + global chip, SCR-HUB-01 · EL-LES-01-070…072, EL-HUB-008 · INF-084…086 · NEED-009, NEED-004 · ENT?-Session · EVT-016, EVT-008

**Backend needs** NEED-009 guard state push (session flag voice_enabled / typed_only); NEED-004 typed path.

**Entities** ENT?-Session.flags. **Cost & risk** SW ~3 KB + version-rotation care (publish flow already rotates topics). Risk: stale SW serving old topic versions — cache versioning keyed to generated_at (Stage 2).

**Open questions** — Q: warn threshold (credits remaining %)? owner: founder (recommend warn at 15% of daily tranche) · blocking: **y** for guard tuning.

### F-XCT-A11Y-01 · Accessibility baseline

| Field | Value |
|---|---|
| Layer | XCT |
| Summary | The floor every screen must hold: keyboard everything, visible focus, 44–48 px targets, screen-reader mirrors, reduced motion, contrast (already doctrine-validated), captions for all audio. |
| Priority | **P0** (built baseline + sim mirror); **P1** (drag alternatives, longdesc, polish audit) |
| Kano | must-be |
| Decision-log ref | C-090, C-091, C-092 (C-096 state rows) |
| Job + moment | J2 · Reads; J3 · Practices |
| Value hypothesis | If the WCAG-2.2-AA floor holds on generated pages, kids with low vision / motor limits / screen readers can complete a lesson (task-completion test per release). |
| Metrics / events | a11y audit pass rate per topic (ops metric, not EVT) |
| Principles applied | P8 · P10 · doctrine §10.8 (contrast, focus, targets — already validated) |
| Evidence | [STRONG] WCAG 2.2 — **numbers verified 2026-11-07 against w3.org WCAG22 Understanding pages**: 2.1.1 keyboard; 2.5.7 Dragging Movements (Level AA, new in 2.2) single-pointer alternative; 2.5.8 Target Size Minimum 24×24 CSS px (AA) / 2.5.5 Target Size Enhanced 44×44 CSS px (AAA) — we design to 44–48 px for children |
| Depends on / blocks | factory lint/review (exists) + shell |
| Layer-independence | applies to every layer independently |

**Behaviour (EARS)**
1. Every control shall be keyboard operable with a visible 3 px pen-blue focus ring (doctrine, exists).
2. Every canvas shall carry a text mirror updated politely (F-COR-SIM-01).
3. If a sim offers drag (P1), the system shall also offer a single-pointer/keyboard alternative (WCAG 2.5.7).
4. All spoken output (read-aloud, tutor) shall have a text equivalent visible on request or by default (T1).
5. Reduced-motion shall zero all animation (runtime honors `prefers-reduced-motion`, exists).

**Acceptance criteria** — AC-1 axe-core scan of each published page: zero serious/critical (CI extension — proposed to factory test set). AC-2 Keyboard-only lesson walk-through by a human tester per release. AC-3 Screen-reader walk-through: sim mirror + check feedback announced. AC-4 Targets ≥ 44 px measured. AC-5 No colour-only meaning (doctrine enforces). AC-6 No timed interactions anywhere (C-097 kill enforced).

**States** reduced-motion column of the state matrix is defined here; all other columns per-screen in §5.3.

**Surfaces** all screens · EL rows carry a11y columns in `ui-element-inventory.csv` · NEED-001 (static) · EVT: audit results to EVT-009 class (operational).

**Backend needs** none beyond existing delivery; CI test-set extension proposed (handoff §7 note).

**Entities** n/a. **Cost & risk** audit time per topic. Risk: generated code varies in a11y quality — factory Code Reviewer already gates; axe in CI closes the gap.

**Open questions** — Q: axe-core in factory CI or perf-gate stage? owner: content-factory · blocking: n (P1).

### F-XCT-SET-01 · Student settings

| Field | Value |
|---|---|
| Layer | XCT |
| Summary | Four honest switches, all local: language (via bar), speech pace, Guide/Tell depth, data-saver — plus "what the tutor remembers → clear". |
| Priority | **P1** |
| Kano | performance |
| Decision-log ref | C-093 (settings shell for C-066 toggle, C-039 persistence) |
| Job + moment | J4 · Reads; J5 |
| Value hypothesis | If settings are explicit and few, students adapt the product without profiling (setting-change rate EVT-015 > 0 proves use). |
| Metrics / events | EVT-015 |
| Principles applied | P9 (explicit-only personalization, T5) · P2 (four settings, no menu tree) |
| Evidence | [ASSUMPTION] usage |
| Depends on / blocks | settings surfaces for LAN/TTS/VOI features |
| Layer-independence | settings off → defaults work; each setting maps 1:1 to a feature's default |

**Behaviour (EARS)**
1. Settings shall live in a sheet opened from the dock/page header: Language, Read-aloud pace (0.75×/1×/1.25×), Tutor depth (Guide me / Explain directly), Data-saver (on/off), Memory (view/clear).
2. All settings persist per device (localStorage); no server profile (T6).
3. Data-saver on shall disable audio prefetch and warn once per session before any streamed audio.
4. Changing Tutor depth mid-session shall apply from the next turn (no restart).

**Acceptance criteria** — AC-1 sheet keyboard/screen-reader operable. AC-2 Defaults are the good experience (settings never required). AC-3 Pace applies to read-aloud and tutor TTS. AC-4 Local-only storage audit. AC-5 Labels translated (P1). AC-6 Clear-memory action confirm-then-clear (shared with F-ADD-MEM-01).

**States** | default: all defaults · partial: a setting's feature unavailable (e.g. pace with TTS off) → control disabled + reason · offline: settings still work locally · others n/a |

**Surfaces** SCR-LES-01.R11 · EL-LES-01-055, 062…067 · INF-071, 077…081 · NEED-018 (local) · ENT?-DeviceProfile · EVT-015

**Backend needs** NEED-018 settings persistence: client-local primary; server mirror post-challenge only (out of P0/P1 build).

**Entities** ENT?-DeviceProfile (local). **Cost & risk** tiny. Risk: settings exporting indecision (anti-pattern) — capped at four switches.

**Open questions** — none blocking.

### F-XCT-ONB-01 · First-use onboarding (anti-onboarding)

| Field | Value |
|---|---|
| Layer | XCT |
| Summary | Two one-time hints, then silence: a single "press and speak" label on the fresh mic chip, and one calm "wiggle-me" phrase on a sim whose object isn't obviously grabbable — both vanish on first interaction. |
| Priority | **P1** |
| Kano | delighter (small) |
| Decision-log ref | C-094 |
| Job + moment | J1 · Asks; J2 · Reads |
| Value hypothesis | If first-session friction is two lines, time-to-first-interaction (sim and mic) drops (EVT-002/005 first-interaction timestamps). |
| Metrics / events | EVT-002, EVT-005 (first_interaction latency) |
| Principles applied | P3 (PhET wiggle-me rules) · P2 (no tour, no modal, no help center) |
| Evidence | [STRONG] PhET |
| Depends on / blocks | dock exists; sims exist |
| Layer-independence | hints are per-layer (mic hint only when voice on) |

**Behaviour (EARS)**
1. On first-ever visit (local flag), the mic chip shall carry the label "Press to ask" and the first sim card a one-line hint; both disappear permanently on first interaction anywhere.
2. The system shall show no tours, modals, or coach-mark sequences, ever.
3. Help text, if ever added, shall be request-only, ≤ 4 short lines, adjacent to the item.

**Acceptance criteria** — AC-1 hints never reappear after interaction. AC-2 Hints are plain text (screen-reader readable), not overlays. AC-3 Reduced-motion: wiggle-me is text-only (no animation). AC-4 Translated (P1). AC-5 Zero cost when off. AC-6 n/a privacy (local flag only).

**States** | default: fresh flags · hinted (first session only) · done (flags set) · others n/a |

**Surfaces** SCR-LES-01.R9/R5/R12 · EL-LES-01-068, 069 · INF-082, 083 · NEED-018 (local flags) · ENT?-DeviceProfile · EVT-002, EVT-005

**Backend needs** none (local flags).

**Entities** ENT?-DeviceProfile.flags. **Cost & risk** trivial. Risk: hint becomes nag → permanent disappearance rule.

**Open questions** — none blocking.

### F-OPS-ADM-01 · Admin dashboard v0

| Field | Value |
|---|---|
| Layer | OPS |
| Summary | The founder's cockpit: live sessions, credit burn, topic engagement, the three trigger buttons (tests / generate / watch-run), run status, and the report inbox. |
| Priority | **P1** (Day-8 ladder item; today it is the scripts — the dashboard wraps them) |
| Kano | must-be (operations) |
| Decision-log ref | C-100 (C-101, C-102, C-109 merged) |
| Job + moment | J7 |
| Value hypothesis | If the founder sees credit burn and engagement live, cut/fix decisions happen daily (decision-count/week ops metric). |
| Metrics / events | M6, M7; reads EVT aggregates |
| Principles applied | P7 (honest numbers) · P2 (five panels only) |
| Evidence | [STRONG] as plan (TIMELINE Day 8 + trigger-button semantics mandated) |
| Depends on / blocks | NEED-010 (data exists first), NEED-015; scripts are the sanctioned implementation behind buttons |
| Layer-independence | staff-facing; zero student impact |

**Behaviour (EARS)**
1. The dashboard shall show: sessions today (count + pseudonymous list), credit burn (Prisma min / Timbre chars / guard state), topic engagement (opens, sim interactions, check attempts per topic), factory run status (latest run per topic + stage durations from run evidence), and open problem reports.
2. The three buttons shall perform exactly the script semantics (TIMELINE table): clone test CronJob; render+apply factory Job template (manual-only, never scheduled); follow latest run logs by label lookup.
3. Access shall be admin-gated (cluster-side auth / Grafana-style gate; no student-facing accounts).
4. The report inbox shall allow status change (open → fixed → shipped-next-run).

**Acceptance criteria** — AC-1 buttons create the same Jobs the scripts do (parity test). AC-2 Dashboard unreachable without admin auth (security scan). AC-3 Data freshness ≤ 5 min for usage panels. AC-4 No child free-text on any panel (transcripts never shown; aggregates only). AC-5 Runs panel reads `status.json`/`run_report.json` evidence (exists). AC-6 Rate-limit + CSRF protection on trigger actions (Stage 2).

**States** | default: panels with data · loading: skeletons · empty: "no sessions yet" · partial: a panel's source down → panel error, others fine · error: auth fail → login · offline: n/a (staff tool) · permission-denied: 403 page · others n/a |

**Surfaces** SCR-ADM-01 (R1 sessions · R2 usage/credits · R3 engagement · R4 ops/runs · R5 reports) · EL-ADM-001…012 · INF-095…105 · NEED-010, NEED-015, NEED-009 · ENT?-TelemetryEvent, ENT?-CreditLedger, ENT?-RunStatus, ENT?-ProblemReport · EVT-007, EVT-008 (read side)

**Backend needs** NEED-015 admin API (query aggregates + trigger actions wrapping the three scripts); reads NEED-009/010 stores.

**Entities** as listed. **Cost & risk** one small FastAPI service + minimal UI. Risk: trigger actions = privileged endpoints → auth + audit log (Stage 2 security).

**Open questions** — Q: dashboard UI hand-rolled static + HTMX vs tiny React? owner: Stage 2 (recommend static, repo style) · blocking: n.

### F-OPS-MET-01 · Credit metering & budget guard

| Field | Value |
|---|---|
| Layer | OPS XCT |
| Summary | Counts every Gnani credit second/character live, protects the reserved 40% demo tranche, and flips sessions to typed mode before credits die — never mid-turn. |
| Priority | **P0** (backend guard); dashboard display slice in F-OPS-ADM-01 |
| Kano | must-be |
| Decision-log ref | C-103 (C-110 merged) |
| Job + moment | J7 · Asks |
| Value hypothesis | If the guard trips at warn→typed before exhaustion, demo-day credit failure probability ≈ 0 (drill-tested). |
| Metrics / events | M7; EVT-007, EVT-008 |
| Principles applied | P7 (warn before limits) · P10 (typed floor) · TIMELINE credit rules [STRONG as plan] |
| Evidence | [STRONG] as plan; thresholds [ASSUMPTION] |
| Depends on / blocks | voice usage (NEED-006/008 metering points); feeds F-XCT-OFF-01 states |
| Layer-independence | guard disables ADD/WRP audio layers; Core + typed tutor survive |

**Behaviour (EARS)**
1. Every Prisma stream-second and Timbre character shall be counted per session + global ledger at call time (NEED-009).
2. When global burn crosses warn threshold, new sessions get voice_enabled=true + a dock notice; when exhausted, new sessions get typed_only; in-progress turns complete.
3. The reserved tranche shall be a separate budget bucket: demo-day traffic draws from it only when the founder flips a mode flag.
4. The daily credit log (parallel-pipeline rule) shall be generated from the ledger automatically.

**Acceptance criteria** — AC-1 drill: burn to exhaustion in dev → typed mode engages cleanly, zero 500s, zero mid-turn cuts. AC-2 Ledger totals match Gnani dashboard within 2% (calibration check). AC-3 Counting adds < 5 ms per call. AC-4 Budget state visible in dashboard (F-OPS-ADM-01). AC-5 n/a localization. AC-6 Privacy: ledger holds counts only, never content.

**States** ok / warn / exhausted / reserved-mode — these drive the quota-exhausted column of the state matrix.

**Surfaces** SCR-ADM-01.R2; student-visible only via dock copy (F-ADD-VOI-01/03, F-XCT-OFF-01) · EL-ADM-003, 004; EL-LES-01-071, 072 · INF-085, 086, 097, 098 · NEED-009 · ENT?-CreditLedger · EVT-007, EVT-008

**Backend needs** NEED-009 metering + guard service (counters, thresholds, mode flag, per-session flag push at session bootstrap + mid-session on state change).

**Entities** ENT?-CreditLedger (model, units, ts, bucket). **Cost & risk** in-memory counters + periodic persist (Stage 2 chooses store). Risk: counter drift vs Gnani dashboard → daily reconciliation.

**Open questions** — Q: warn threshold + daily tranche size? owner: founder (Day-8 decision) · blocking: **y** for guard config, n for spec.

### F-OPS-TEL-01 · Product telemetry & latency tracking

| Field | Value |
|---|---|
| Layer | OPS XCT |
| Summary | The measurement spine: 18 pseudonymous events, per-stage voice latency, structured errors — enough to prove Gate C and M1–M7, never enough to profile a child. |
| Priority | **P0** |
| Kano | must-be (Gate C is unprovable without it) |
| Decision-log ref | C-104 (C-105 merged) |
| Job + moment | J7 |
| Value hypothesis | If EVT-006 latency p90 < 4 s is visible live, Gate C claims are defensible and regressions are caught same-day. |
| Metrics / events | M2, M3, M4, M6, M7; EVT-001…018 (catalogue in handoff §4) |
| Principles applied | P9 (privacy classes per event) · P6 (latency measured not felt) |
| Evidence | [STRONG] as plan |
| Depends on / blocks | event emission points across all features; ingestion endpoint |
| Layer-independence | telemetry failure must never break a user-facing feature (fire-and-forget + local queue) |

**Behaviour (EARS)**
1. The client shall batch events (≤ 5 s or 20 events) to the ingestion endpoint; failures queue locally (≤ 200 events) and retry with backoff.
2. The voice backend shall emit stage timestamps (end-of-speech, STT final, LLM first token, TTS first audio byte) per turn (EVT-006).
3. Error events shall carry component + error class + latency context — never free-text payloads.
4. Events fire only after consent state is known; pre-consent events limited to EVT-001/016/017 aggregate-safe set (flagged).
5. No event shall contain raw child free text (transcripts stay in server logs, TTL 7 d, not in EVT).

**Acceptance criteria** — AC-1 EVT-006 p90 < 4 s on deployed rehearsal (Gate C evidence). AC-2 Event schema validation rejects free-text fields (CI test). AC-3 Local queue survives reload (no loss of more than 200 events). AC-4 Ingestion adds < 50 ms to interaction path (async). AC-5 n/a localization. AC-6 Privacy audit: every EVT row has a privacy class (handoff §4 table is the audit artifact).

**States** | default: batching · degraded: ingestion down → local queue + drop-oldest · consent-missing: restricted set only · offline: queue |

**Surfaces** emission across all screens (no dedicated UI) · EL rows carry emits_event column · NEED-010 · ENT?-TelemetryEvent · EVT-001…018

**Backend needs** NEED-010 ingestion (batch POST, schema-validated, pseudonymous ids only; sink: structured logs → dashboard aggregates; Loki is P2 per deployment docs).

**Entities** ENT?-TelemetryEvent. **Cost & risk** tiny bandwidth. Risk: metric theater (vanity metrics) — catalogue is capped at 18 events tied to M1–M7.

**Open questions** — Q: aggregate store (Postgres vs logs+Grafana)? owner: Stage 2 · blocking: n for product, y for dashboard build.

---

## 5. Screens, elements, information

### 5.1 Screen list

| Screen | Name | Purpose | Regions | Features served |
|---|---|---|---|---|
| **SCR-HUB-01** | Courses hub | Front door; find and open a topic page | R1 header (kicker/title/sub) · R2 groups + course cards + empty state · R3 footer attribution · global offline chip | F-COR-HUB-01, F-XCT-OFF-01 |
| **SCR-LES-01** | Lesson page | The whole generated chapter + doubt tutor + wrappers | R1 header/meta · R2 language bar · R3 text blocks · R4 diagram · R5 simulation card · R6 check card · R7 worked-example/reveal/glossary · R8 sources footer + report · R9 voice dock · R10 consent overlay · R11 settings sheet · R12 onboarding hints · global chips | all student-facing cards |
| **SCR-PRIV-01** | Privacy summary | Guardian-facing: what is kept, for how long, how to erase | R1 title + back · R2 data-class table · R3 clear + confirmation | F-XCT-CON-01 |
| **SCR-ADM-01** | Admin dashboard v0 | Founder cockpit: sessions, credits, engagement, runs, reports, triggers | R1 sessions · R2 usage/credits · R3 engagement · R4 ops/runs + triggers · R5 reports · R0 auth gate | F-OPS-ADM-01, F-OPS-MET-01 |

### 5.2 Element inventory

`ui-element-inventory.csv` — **97 rows** (EL-LES-01-001…072, EL-HUB-001…008,
EL-PRV-001…005, EL-ADM-001…012). Every perceivable element on every screen has a row
with states, interaction, emitted event, API need, entity read, i18n rule, TTS rule,
a11y contract, perf budget, privacy class, priority. Walk-through test basis for §7.

### 5.3 Information inventory

`information-inventory.csv` — **105 rows** (INF-001…105). Every word/number/sound the UI
can show, with source, format, units/symbols rule, nullability + fallback, freshness,
localization rule, PII class, retention hint, visibility. Never-translate rule (units,
symbols, autonyms, source names) and child-data flags live here.

### 5.4 Screen-state matrix

Every region × the 11 required states. `n/a` always carries a reason.

| Screen / region | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| SCR-HUB-01 (whole) | grouped cards + attribution | static HTML paint (no spinner) | built empty copy (INF-007) | some class groups have topics, others absent | card target 404 → host page; hub intact | cached render + offline chip (EL-HUB-008) | n/a (public page) | n/a (no motion) | English chrome + INF-087 marker (P1) | n/a (hub costs no credits) | n/a (voice consent is per voice use) |
| SCR-LES-01.R1 header | kicker · title · meta · objectives | static paint | n/a (factory hard-errors on empty pages) | no objectives → section absent | n/a (static text) | cached full render | n/a | n/a | English + INF-087 | n/a | n/a |
| SCR-LES-01.R2 language bar | 3 chips, remembered selection | bundle fetch < 200 ms | n/a | HI/Hinglish chips disabled until bundle exists | bundle fetch fail → stay current language + "couldn't load" chip | cached bundle works; else English + reason | n/a | n/a | this IS the untranslated surface (INF-087/088) | n/a | n/a |
| SCR-LES-01.R3 text blocks | paragraphs + one highlighted statement | static paint | n/a | some blocks untranslated + markers | n/a (static text) | cached full text | n/a | n/a | English + INF-087 | text unaffected; read-aloud disabled (INF-089) | n/a (reading needs no consent) |
| SCR-LES-01.R4 diagram | figure + caption | inline SVG (no wait) | n/a | no longdesc → aria-label only | n/a (authored + gated upstream) | cached | n/a | n/a (static SVG) | English labels + marker; symbols fixed | n/a | n/a |
| SCR-LES-01.R5 simulation card | still; default_behaviour drawn once | canvas blank ≤ 1 frame until JS | n/a | broken sim → on-canvas painter + mirror text (INF-035) | same as partial; EVT-009 fires | fully works (pure client-side) | n/a | static frame; no rAF loop | English labels + marker; units never translated | n/a (sims cost no credits) | n/a (sims need no consent) |
| SCR-LES-01.R6 check card | unanswered | n/a | n/a | answered → feedback shown, Why closed | numeric parse miss → INF-042 copy | fully works | n/a | n/a | English + INF-087 | n/a | n/a |
| SCR-LES-01.R7 WE/reveal/glossary | details closed | n/a | n/a | some steps open | n/a (native `<details>`) | works | n/a | n/a | English + INF-087 | n/a | n/a |
| SCR-LES-01.R8 sources + report | footer visible; report button quiet | n/a | n/a | report draft kept unsent | send fail copy (INF-055) | report disabled + reason | n/a | n/a | English + INF-087 | n/a | n/a (report is pseudonymous, no consent gate) |
| SCR-LES-01.R9 voice dock | collapsed chip "Ask a doubt" | "connecting" ≤ 1 s → error if fail | transcript panel empty | partial transcript off by default; anchor = whole page | full failure machine (INF-068 copy → re-ask → help chips → typed fallback) | dock disabled + reason (INF-084); Core intact | mic denied → typed fallback shown, never re-prompted | static state indicators; earcons unchanged | English dock copy + marker | typed-only notice (INF-086); in-progress turn completes | consent overlay (R10) shown first |
| SCR-LES-01.R10 consent overlay | closed | n/a | n/a | n/a | consent save fail → voice stays off + retry | local consent works; server sync deferred | declined → voice off quietly, no re-nag | n/a | English P0 (P1: all 3) | n/a | this IS the consent-missing surface |
| SCR-LES-01.R11 settings sheet | closed | n/a | n/a | row for unavailable feature disabled + reason | n/a (local storage) | works locally | n/a | n/a | English + INF-087 | pace row still applies to typed mode | n/a (settings need no consent) |
| SCR-LES-01.R12 onboarding hints | hidden (flags set) | n/a | n/a | n/a | n/a | works (local flags) | n/a | text-only hints | English P0 | n/a | mic hint hidden (voice off) |
| SCR-LES-01 global chips | hidden | n/a | n/a | n/a | n/a | offline chip ≤ 1 s (INF-084) | n/a | n/a | English | warn (INF-085) / typed-only (INF-086) notices | n/a |
| SCR-PRIV-01 | data-class table + clear button | static paint | no consent record → INF-076 fallback copy | n/a | clear fail copy | local wipe works; server deletion deferred + reason | n/a | n/a | English P0 | n/a | shows "no consent record" state honestly |
| SCR-ADM-01 | five panels with data | skeletons | "no sessions yet" per panel | one panel's source down → panel error; others fine | auth fail → login / 403 | n/a (staff tool on cluster network) | 403 page | n/a | n/a (staff UI English) | guard badge shows exhausted | n/a (ops views are aggregates) |

---

## 6. Traceability summary

Full matrix: `traceability-matrix.csv` (21 rows, one per feature card).

- **Coverage (feature → everything):** every card cites ≥1 job (J1–J7), ≥2 principles
  (P1–P10), its screens/regions, its element + info ID ranges, its NEED/ENT?/EVT
  references, ≥1 metric (M1–M7 or a named ops metric), its priority, and its
  decision-log candidates.
- **Zero orphans (everything → feature), verified mechanically:** all 97 EL rows, all
  105 INF rows, all 18 NEEDs, all 10 ENT? entities, all 18 EVT events appear in at
  least one feature row; no ID referenced anywhere exists outside the inventories.
  F-XCT-A11Y-01 and F-OPS-TEL-01 bind to the *columns* of the inventories (a11y /
  emits_event) rather than listing IDs — that is their contract form.
- **Decision-log closure:** all 110 candidates resolve to KEEP (21 anchor cards +
  merged slices), MERGE (2 infra), DEFER (19, each with a revisit trigger), or KILL
  (16, each with a stated reason). No candidate is unaccounted.

---

## 7. Self-review + Doc Change Proposals

Self-review run 2026-11-07 against the skill's delivery checklist (`references/08`).
No silent ❌ below.

### 7.1 Checklist results

**A. Decision quality**
- ✅ Decision log: 110 candidates, KEEP 73 / MERGE 2 / DEFER 19 / KILL 16; all KILLs
  visible with reasons.
- ✅ Every KEEP row carries job, mechanism + evidence tag, removal test, cost, risk,
  metric (CSV-validated: no empty mandatory fields).
- ✅ Layer independence: each card has an explicit "Layer-independence" row; the
  degraded ladder (F-XCT-OFF-01) is the independence proof — consent-missing blocks
  only the ADD layer; voice/TTS failure never blocks Core reading/simulating/checking.
- ✅ T1–T12 all decided in §3 with rejected alternative + falsification test; no new
  tensions surfaced during card writing that are not covered by T1–T12.
- ✅ Priority tags on all 21 cards: **16 P0 / 5 P1 / 0 P2 / 0 post-challenge cards**
  (P2 and post-challenge items live as DEFER rows with revisit triggers). P0 matches
  the TIMELINE ladder exactly (T10 decision; **Gate-D sign-off recorded: founder
  signed off the 16-P0 ship list as-is, 2026-11-07**).

**B. Principles**
- ✅ 10-principle brief at §1, each with UI consequence + test.
- ✅ Nielsen pass done at card + state-matrix level (status visibility P6 rows, error
  recovery rows, user-control rows per screen). A dedicated per-screen heuristic
  audit-log is scheduled for the Day-9 frontend pass — owner: frontend; not a
  delivery blocker because every state already has designed copy + exit.
- ✅ Mayer pass: redundancy/modality decided (T1), signaling (highlighted statement,
  tutor highlight), segmenting (details-based reveals, WE steps), contiguity
  (highlight-sync P1), pre-training (glossary + first-mention gloss).
- ✅ PhET pass on the sim surface: start still (runtime rule), ≤3 control groups,
  1–3 word labels, help on request only (wiggle-me once), consistent representations
  (doctrine). Play/step/trace deferred deliberately (C-019/020) with triggers.
- ✅ Child-safety/privacy pass: consent gate (F-XCT-CON-01), zero audio retention
  (T11), no profiling (C-074 KILLED not deferred), no streaks/gamification (C-097/098/099
  KILLed), honest copy audit = every state-matrix cell has plain-language text.

**C. Granularity and traceability**
- ✅ Walk-through test (10 random perceivable things, each → EL row + INF row +
  feature): lesson title (EL-LES-01-002/INF-010/F-COR-LES-01) · sim slider readout
  (020/030/SIM-01) · earcon sound (045/058/VOI-01) · "Why?" explanation (031/041/CHK-01)
  · consent checkbox label (059/073/CON-01) · offline chip (070+HUB-008/084/OFF-01)
  · hub empty paragraph (HUB-006/007/HUB-01) · anchor chip text (050/064/VOI-02)
  · dashboard guard badge (ADM-004/098/MET-01) · wiggle-me hint (069/083/ONB-01).
- ✅ State matrix: 16 region rows × 11 state columns, zero blank cells (mechanically
  checked); every `n/a` carries a reason.
- ✅ Orphan checks green both directions (mechanical): 97 EL, 105 INF, 18 NEED,
  10 ENT?, 18 EVT — every ID referenced somewhere exists in an inventory, and every
  inventory row is claimed by ≥1 feature.
- ✅ Every INF row has source, format, units rule, nullability + fallback, freshness,
  localization rule, PII class, retention hint, visibility (CSV-validated).
- ✅ Every EL row has a11y role/name/keyboard + i18n rule; spoken elements name their
  spoken text (INF-057 state labels, INF-058 earcons, INF-060/061 transcript/reply).
- ✅ Sim trio: non-drag alternative (keyboard arrows built; SC-07 for future draggables
  per WCAG 2.5.7), text state mirror (EL-022, SC-02), reduced-motion behaviour
  (static frame, no rAF loop).

**D. Handoff**
- ✅ `backend-handoff.md` complete: 18 NEEDs, 10 ENT?, realtime contract, 18 EVT with
  privacy classes, volumes, retention/consent, SC-01…07 with costs, DCRs.
- ✅ Needs stated as capabilities + data shapes; endpoint paths shown are illustrative
  shapes, Stage 2 owns the actual API design.
- ✅ Schema proposals separated with build cost.
- ✅ DCR-001 / DCR-002 listed with affected doc + section.
- ✅ No contradictions with AGENTS.md / TIMELINE.md / design-doctrine.md /
  blocks-schema.md: Prisma/Timbre non-negotiable respected (versions updated to v3.0 by
  founder decision 2026-11-07; Gate A outcome recorded — Gemma 4 26B A4B runtime LLM);
  P0 ladder untouched (T10); doctrine followed, gaps raised as DCRs instead
  of silently diverging; factory Job/trigger-script semantics mirrored exactly in
  NEED-015.

**E. Honesty**
- ✅ Evidence tags on every card + decision row; behavioural claims without formal
  research are tagged [ASSUMPTION]/[WEAK-MODERATE] and each has a falsification test.
- ✅ Unknowns live in card "Open questions" rows + §7.3 below.

### 7.2 Perishable-fact verification record (done this session, 2026-11-07)

| Fact as quoted | Verified against | Result |
|---|---|---|
| WCAG 2.5.7 Dragging Movements, Level AA, single-pointer alternative required | w3.org WCAG22 Understanding page (fetched today) | ✅ as quoted |
| Target size: 24×24 CSS px minimum (2.5.8, AA); 44×44 CSS px (2.5.5 Enhanced, AAA) | w3.org WCAG22 Understanding page (fetched today) | ✅ as quoted; we design 44–48 px for children |
| DPDP: Act bars child tracking/behavioural monitoring/targeted advertising | Act §8 duty via secondary source (fetched today) | ✅ |
| DPDP children's-data provisions in force date | MeitY commencement notification G.S.R. 843(E) (13 Nov 2025) via secondary source (fetched today) | **corrected 14 May → 13 May 2027** in §3 T5, F-XCT-CON-01, handoff §6, decision-log C-087; counsel still required for VPC design |
| Gnani language coverage (founder correction 2026-11-07: product language set = all Gnani languages) | docs.gnani.ai supported-languages + available-voices pages (fetched today) | ✅ verified: Prisma v2.5/v3.0 STT = 10 languages (bn/en/gu/hi/kn/ml/mr/pa/ta/te, `*-IN`); Timbre v2.5 = 42 voices one-preferred-language-each (incl. Hinglish voice Poorvi `hi-en`); Timbre v3.0 = 13 voices × all 10 languages; supersedes the "10+" approximations in `02-all-about-gnani.md` |
| Timbre expressive tag set | docs.gnani.ai audio-tags page (fetched today) | **13 tags, Timbre v3.0 only; Timbre v2.5 strips tags before synthesis** (tags billable as characters) — AGENTS.md note corrected; feeds the open model-version decision below |
| Prisma v3.0 / Timbre v3.0 availability | gnani.ai homepage + docs.gnani.ai (fetched today) | ✅ available (`prisma-v3.0` / `timbre-v3.0` model values; official LiveKit plugin supports them; Prisma v3.0 adds `indic-auto` auto language detection) — **founder decision recorded 2026-11-07: v3.0 adopted for both** (AGENTS.md non-negotiable updated); credit-billing parity check on the Gnani dashboard + a Gate-C smoke test remain ops actions |

### 7.3 Blocking open questions (aggregated from cards)

1. ~~Hinglish orthography house-style sheet~~ — **revised 2026-11-07 (founder)**: page
   translation is a **separate second-layer pipeline** (SC-01, not yet built; the
   factory produces English natively), so its per-language style sheet defers with
   that pipeline. What the P0 voice loop needs now is Stage-2 prompt rules (reply in
   the student's language/mix; never-translate units/terms). Language set = **all
   Gnani languages** (10 STT languages verified); EN/HI/Hinglish = demo subset.
2. ~~Exact Timbre expressive tag set / Prisma-Timbre model version~~ — **resolved
   2026-11-07 (founder)**: **v3.0 adopted for both STT and TTS** (`indic-auto`
   detection; 13 expressive tags; 13 polyglot voices). Remaining ops actions:
   credit-billing parity check on the Gnani dashboard; 30-minute v3.0 smoke test
   before the Gate-C rehearsal.
3. ~~Gate A outcome (Evon v3.3 vs fallback)~~ — **resolved 2026-11-07 (founder)**:
   runtime LLM = **Gemma 4 26B A4B** (self-hosted, served via the existing
   OpenAI-format inference-router pattern; Evon v3.3 becomes the post-challenge
   aspiration). Recorded in the TIMELINE.md Gate A row; public story updated — the
   Gnani voice loop (Prisma v3.0 + Timbre v3.0) carries the ≥1-Gnani-model requirement.
4. ~~Does the demo link show the consent overlay to judges?~~ — **resolved 2026-11-07
   (founder)**: shown in both the demo video and the live link; consent flow treated
   as a demo asset.
5. Credit-guard warn threshold + daily tranche size — owner: founder (Day-8) — blocks
   guard config (F-OPS-MET-01).
6. SC-02 adoption timing — owner: content factory — blocks P1 sim-quality slices,
   not the P0 ship.

Non-blocking open questions stay on their cards.

### 7.4 Doc Change Proposals raised (full text in handoff §8)

- **DCR-001** — design-doctrine §10: Devanagari rendering verification clause (T4).
- **DCR-002** — design-doctrine §10.12: voice dock as a doctrine-covered component.

Both await the doctrine owner (founder). No doctrine text was changed by this doc.

---

## 8. Backend handoff (for the systems-design stage)

Full text: **`docs/product/backend-handoff.md`** (the 8-section Stage-2 input). Mirror
of its headline numbers:

- **18 capability needs** (NEED-001…018): 2 exist (static delivery, catalogue), 1 is
  the core new build (NEED-004 voice WebSocket channel — full message contract), 6
  wrap existing pieces (Prisma STT, Gemma 4 26B A4B LLM, Timbre TTS, credit guard, telemetry,
  admin API over the three sanctioned trigger scripts), the rest are small stores
  (session, consent, coverage, deletion, reports, bundles, narration cache).
- **10 entity proposals** (ENT?-Session, VoiceTurn, ConsentRecord, DeviceProfile,
  CreditLedger, TelemetryEvent, ProblemReport, PageMeta, RunStatus, LanguageBundle) —
  all preclude child profiling by construction (T5), all carry a nullable
  `guardian_ref` seam (T6).
- **1 realtime channel contract** (handoff §3): PTT messages, audio frames up
  (transient, never persisted — T11), partial/final transcript down, tutor text stream,
  TTS chunks, interrupt/barge-in ≤ 300 ms, guard-state push, typed path, backpressure
  rules, degraded rungs.
- **18 events** with privacy classes; transcripts never in events; consent-gated
  catalogue.
- **Volume hints:** < 150 KB per voice turn; ≤ 500 sessions/day, ≤ 10 concurrent voice
  sessions; per 20-turn session ≈ 5 min Prisma + ≈ 10 k Timbre chars.
- **Retention:** zero raw audio, transcripts 7 d, coverage 24 h, telemetry 90 d.
- **7 schema proposals** (SC-01…SC-07) + 1 test-set proposal (axe-core in factory CI).
- **2 Doc Change Proposals:** DCR-001 (Devanagari verification clause), DCR-002
  (doctrine §10.12 voice dock).
- **8 ADR flags** handed to Stage 2: T2, T3, T5, T6, T7, T8, T11, T12.
