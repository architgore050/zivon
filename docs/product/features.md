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

Each: **decision · rejected alternative · deciding principle · how we'll know it was wrong ·
flag** (ADR = systems-impacting, goes to Stage 2's ADR list; DCR = Doc Change Proposal to
the doctrine owner).

| ID | Decision | Rejected alternative | Deciding principle | Falsification test | Flag |
|---|---|---|---|---|---|
| **T1** | Narration + visuals with **short labels only** by default. The voice dock shows the **final tutor transcript by default** (it doubles as status + a11y caption surface); live partial transcript is opt-in P1; lesson text is never duplicated as full captions. Per-user memory of the toggle. | (a) audio-only (fails a11y + noisy room); (c) always full text+audio duplication (Mayer redundancy cost) | Mayer redundancy/modality [STRONG] balanced against WCAG captions-for-audio [STRONG] | Kid test: do testers glance at the transcript or ignore it? Learning outcome equal-or-better with captions off vs on (Gate-B style A/B) | none (copy rule) |
| **T2** | Language model: **UI languages = English / हिन्दी / Hinglish** (Hinglish in Roman script, house style: Devanagari for physics terms where natural, else English term kept). Hinglish is *also* the tutor's default speech style. Bar shows autonyms. v1 = 3 languages; bar chips wrap (doctrine §10.5) so ≥5 is a data change not a redesign. RTL out. | Hinglish as tutor-style only (page stays English); single "Hindi" covering both scripts | J4 (read at thinking speed) + the challenge's code-mix story [STRONG] | Kid preference sessions (Gate-B rounds): which UI language do testers stay in? Label-length audit at 360 px | **ADR** (per-string language data model; STT language hints; TTS voice choice) |
| **T3** | **Push-to-talk default** (tap-to-start, tap-or-endpoint-to-stop). Hands-free VAD is a P2 opt-in. | Hands-free default (false triggers in noisy shared rooms; always-on mic for a child) | Noisy shared room is the base case (repo rule) + child privacy | EVT-010 voice_abandon + false-trigger rate in field logs; quiet-room vs noisy-room session comparison | **ADR** (WebSocket PTT message contract) |
| **T4** | Doctrine already names the Devanagari fallback stack (§10.3) — the gap is **verification**: LessonKit baseline alignment, canvas `fillText` font stack, and the row rhythm under Hindi strings are unproven. File **DCR-001**: doctrine gains a "Devanagari rendering verification" clause (no tofu, rules hold, canvas stack pinned) + the pipeline vendors Kalam/Nirmala-class faces. Never ship tofu. | Ship Hindi strings on the unverified stack; or drop Hindi from v1 | Doctrine owner decides doctrine; honesty + a11y [STRONG] | Device test: Hindi page at 360 px — zero tofu, rules under baselines after resize (perf-gate extension) | **DCR-001** |
| **T5** | **Explicit + session-scoped only.** Explicit settings (language, pace, Guide/Tell, data-saver) and session coverage memory. **Persistent inferred profile: KILLED** (not deferred) — behavioural profiling of children. Cross-session *explicit* progress deferred to post-challenge with counsel. | Guardian-consented persistent memory now; inferred difficulty model | DPDP Rules 2025 bar tracking/behavioural monitoring of children (secondary sources; substantive children's duties ~14 May 2027 — **re-verified 2026-11-07 against repo reference `06`, counsel still required**) + repo hard rule P9 | Legal review outcome; if killed profiling later proves necessary, it returns only as a counsel-cleared, purpose-limited feature | **ADR** (data model must preclude profiling by default) |
| **T6** | **Anonymous device-scoped profile** (localStorage: language, settings, session pointers; pseudonymous session id server-side). Data model gives every table a nullable `guardian_ref` column so a guardian identity can attach later. No accounts, no auth — TIMELINE boundary respected. | Magic-link guardian identity now; per-lesson anonymous profiles | Scope fit (TIMELINE out-of-scope list) while still serving J5/J6 | Field signal: share of sessions from a new device wanting prior memory (measured via EVT-001 device-new rate) | **ADR** (identity model) |
| **T7** | Tutor may **highlight, scroll, and narrate** (visible, narrated, non-destructive). Tutor **setting** a sim value: P2, only with visible undo + spoken narration of the change. | Full page agency now | User control + honesty (P8/P7); conceptual model "the tutor points, I move" | Undo-usage rate; kid-test observation of confusion/annoyance when tutor moves a slider | **ADR** (tutor→page message types) |
| **T8** | **Build-time reviewed** translation and (later) narration for all lesson content via the factory (glossary + reviewer gate per language). **Runtime only for tutor speech.** No runtime page translation. | Runtime LLM translation per visit | Physics terminology correctness is a correctness risk not cosmetic [STRONG]; cost/latency | Per-language launch gate = reviewer approval rate ≥ threshold before a language ships; terminology complaint rate via report-a-problem | **ADR** + content-factory schema proposals SC-01/SC-02 (see handoff §7) |
| **T9** | **Socratic default**; one-tap "Explain directly" in the dock (P1); after 2 failed attempts on the same check the tutor *offers* direct explanation (never forces). | Mode buried in settings; always-direct; always-Socratic | P5 retrieval practice vs J1 exam-eve frustration [MODERATE] | Toggle usage rate; follow-up-question rate after direct explanations; M1 in A/B sessions | none |
| **T10** | **P0 is not expanded.** P0 here = TIMELINE ladder exactly (≥6 pages, voice doubt-tutor, demo artifacts, low-end Android). Everything else tagged P1 / P2 / post-challenge; this doc *is* the Gate-D ship list + post-challenge roadmap. Founder sign-off at Gate D (today). | Pulling language switching or dashboard into P0 | Gate D rule + demo safety first | Gate-D sign-off record; if P0 slips, cuts come from P1 first — never from the ladder | none (this doc's priority column is the artifact) |
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

**Surfaces** SCR-HUB-01 · EL-HUB-001…006 · INF-001…006, INF-070…072 · NEED-001, NEED-002 · ENT?-PageMeta · EVT-017, EVT-001, EVT-016

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

**Surfaces** SCR-LES-01.R1/R3/R7 · EL-LES-01-001…010, 040…046 · INF-010…026 · NEED-001 · ENT?-PageMeta · EVT-001, EVT-002

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

**Surfaces** SCR-LES-01.R4 · EL-LES-01-020…023 · INF-027…030 · NEED-001, NEED-016 (P1) · ENT?-PageMeta · EVT-002

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

**Surfaces** SCR-LES-01.R5 · EL-LES-01-024…031 · INF-031…038 · NEED-001, NEED-005 (voice reads mirror) · ENT?-PageMeta · EVT-003

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

**Surfaces** SCR-LES-01.R6 · EL-LES-01-032…039 · INF-039…046 · NEED-001, NEED-010 · ENT?-PageMeta · EVT-004

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

**Surfaces** SCR-LES-01.R8 · EL-LES-01-047…049 · INF-047…049 · NEED-014 · ENT?-ProblemReport, ENT?-PageMeta · EVT-014

**Backend needs** NEED-014 report submission.

**Entities** ENT?-ProblemReport (page, block, category, text, status, ts; no PII). **Cost & risk** tiny. Risk: report spam → rate-limit (Stage 2).

**Open questions** — Q: per-block citation display (C-029) timing? owner: content-factory · blocking: n.

<!-- CARDS-BATCH-2 -->

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
