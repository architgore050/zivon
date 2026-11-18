# Feature-decision addendum — personalized learning + interactive artifacts

Status: **decided, 2026-11-17 (founder direction), specified to build.** This
document extends [`docs/product/features.md`](../../product/features.md) without
editing it. The parent document remains authoritative for every feature it
already decided; where this addendum adds a feature, the rows here are the
decision record, and the implementation contract is [`spec.md`](spec.md).

Method: `skills/zivon-product-design-skills/skills/zivon-product-design/SKILL.md`
(value filter → decision log → feature card → screen/element/information →
traceability → self-review). The raw candidates and their KEEP / MERGE / DEFER /
KILL outcomes are in [`decision-log-addendum.csv`](decision-log-addendum.csv).

Hard boundaries inherited unchanged: Physics only (Class 9–12); children are the
users (private-by-default, no profiling, no dark patterns); low-end Android and
a noisy shared room are the base case; Core works with this feature off; no
verbatim CBSE content (`DEC-COMP-001`); no paywall/payment in this prototype.

---

## 1. What already exists vs what this feature adds

| Area | Exists on `main` (2026-11-17) | This feature adds |
|---|---|---|
| Accounts | `users`, `auth_identity`, `auth_session`; login/signup/Google; settings; delete/export (ADR-0029, F2) | Nothing to auth; consumes it. Adds one preferences column/table and one settings section. |
| App shell | `/app` SSR shell, guard, CSP, `ShellContext`, nav (F0C) | `/app/personalized`, `/app/personalized/{id}`; nav entry; PL pages under the same guard. |
| Lesson content | Generated pages + manifests + source packs; P1 block hooks; F4 lesson shell | RAG index over published lessons + source packs; citation chips in teaching turns. |
| Assessment bank | P2 pack + `question_bank` import (§4.19) | Bank-first diagnostic and check selection; generated items never enter the bank. |
| Tutor | Voice dock, Gemma prompt, 7-day transcript TTL, credit guard | Personal-instruction injection (shared block); optional saved lesson-doubt sessions (decision D-PL-09). |
| Progress | F3 progress events, chapter stats | Explicit per-concept mastery evidence from personalized sessions, emitted as progress events. |
| Visuals | Build-time factory block builders + lint + doctrine | Runtime artifact builder reusing the same prompts/doctrine/lint, with a sandboxed viewer. |
| Evals | `evals/` framework and cards `EV-*` | Cards `EV-PL-001…005` and their deterministic checkers/goldens. |

## 2. Tension deltas (what this feature changes, and what it does not)

| Tension | Parent decision | Delta here | Why it is safe |
|---|---|---|---|
| **T5** — no inferred profile | Persistent **inferred** profile KILLED; explicit + session-scoped only | A cross-session **explicit teaching record** is stored: the student's own answers, per-concept status, and the conversation. Adaptation stays inside a session; a later session only uses the record when the student chooses to continue it. | The record is visible, exportable, and deletable; it is evidence, not a hidden ability model. No cross-student comparison, no inferred trait, no difficulty prediction from behaviour. The kill of inferred profiling stands (`PL-C-015`). |
| **T6** — anonymous device profile | Device-scoped, no accounts | Superseded in practice by ADR-0029 (accounts). Personal instructions are **account-scoped**; device settings stay device-local. | Accounts are the founder-decided full-frontend identity; this feature adds no new identity concept. |
| **T9** — Socratic default | Socratic by default, direct explanation on request | Personalized learning is a **guided teach → check → adapt** loop, not free chat. Socratic questioning remains available in the lesson dock; the loop asks before telling inside each check. | The loop is explicit about what it is doing at every stage; the student can ask for a direct explanation at any time. |
| **T11** — no raw audio | No audio retention | Personalized learning is **text-first** in R1; no microphone is opened. Artifacts are generated HTML, not audio. | Nothing new to retain or leak; the consent gate is unchanged. |
| **T12** — anchor + provenance | Tutor answers carry provenance; page context is the universe | Every teaching turn carries **NCERT/lesson citations** and the UI shows them. A turn with no valid citation is marked ungrounded and says so. | The grounding law is the same; citations are now a visible contract, not only a dock chip. |
| **T1** — captions/transcript | Final tutor transcript visible; no full duplication | The teaching transcript **is** the interface (text-first). No TTS in R1, so no caption duplication question. | Read-aloud is deferred (`PL-C-013`); when it lands it follows T1/TTS rules. |

New product tensions resolved here:

| ID | Decision | Rejected alternative | Deciding principle | Falsification test |
|---|---|---|---|---|
| **PL-T1** | Text-first teaching in R1. Voice input/read-aloud deferred. | Voice-first personalized sessions | Latency + cost + the lesson dock already covers spoken doubts; a text loop is testable sooner (`J8`) | Kid testers ask for voice in the first session; if >30% do, revisit read-aloud first |
| **PL-T2** | **Bank-first** diagnostic/check items; generate only when the bank lacks a suitable item, and never write generated items into `question_bank`. | Generate every check | Reviewed bank items are cheaper, cited, and quality-gated; generated items are session evidence only | Generated-item share per session > 50% (bank coverage gap) |
| **PL-T3** | Personalized learning runs on **DeepSeek V4.1 Flash via the OpenCode API key**, separate from the Gemma voice tutor and the factory credentials. | Use the Gemma/Gemini tutor path; use the factory's key/config | Long structured teaching calls would contend with the 4 s voice SLO; the OpenCode subscription already carries this model; separate secrets keep blast radius small | p90 first-text > 20 s or quota burn > budget for 2 weeks → revisit routing (D-PL-06) |
| **PL-T4** | Artifacts are untrusted content in a sandboxed iframe (`allow-scripts`, **no** same-origin), strict CSP, no network/storage/forms/top-nav; dedicated artifact origin in production. | Render generated HTML in the page; `srcdoc` with same-origin | Generated code is untrusted by definition; sandboxing is the only control that survives a lint miss | Any artifact reaches parent DOM/storage/network in a red-team test → blocker, rollback |
| **PL-T5** | Saved sessions are retained **90 days from last activity** (recommended), hard-deleted after; no cold copy; export/delete anytime. | Keep forever; 7 days like voice transcripts | The loop needs continuity across sittings (`J5`); 90 days balances usefulness and minimization. Counsel reviews before scale-up | Retention job misses a row, or a student cannot find export/delete → blocker |

Parent **principle** P2 ("subtract first — no chat history screen") is bounded here, not
overturned: `J10` (continue exactly where I stopped) needs the session list, so the list
exists — with no search, no filters, and no second doubts store (`D-PL-09` is accepted:
one store; the lesson-dock merge is the follow-up PR).

## 3. Jobs and metrics added

| ID | Job statement | Type |
|---|---|---|
| **J8** | When I know a chapter is weak but not which concept, I want a short diagnostic and a guided path, so I stop wandering and start where the gap is. | functional |
| **J9** | When a concept is invisible, I want a visual built for exactly the confusion I described, so the explanation lands without me translating a textbook diagram. | functional + emotional |
| **J10** | When I come back, I want to continue exactly where I stopped — same concept, same difficulty — so I don't repeat what I already proved. | functional |

| ID | Metric | Definition | Source |
|---|---|---|---|
| **M8** | Diagnostic completion | sessions that finish the 3-question diagnostic / sessions that start it | `EVT-PL-02/03` |
| **M9** | Loop completion | sessions that reach `advance` at least once / sessions that reach `teach` | stage events |
| **M10** | Mastery evidence rate | concepts with `mastered` evidence / concepts taught | session state |
| **M11** | Citation coverage | teaching turns with ≥1 valid citation / teaching turns | `EV-PL-002` |
| **M12** | Cost per session | input+output tokens and artifact builds per completed session | `personalized_usage` |
| **M13** | Honest-quota rate | quota-blocked turns that end in the designed state (no 5xx, no silent drop) / quota-blocked turns | `EV-PL-005` |
| **M14** | Artifact success | artifacts `ready` / artifact builds started; fallback shown when failed | `personalized_artifact` |

## 4. Feature cards

Every card cites ≥1 job and ≥1 metric, states acceptance criteria, and points to
the screen/state contract in [`spec.md`](spec.md) §5–§7. Priorities are relative
to **W5.5**, not to the frozen R1 list.

### PL-F1 · Personal instructions (account-level)

| Field | Value |
|---|---|
| Layer | ADD (personalization), cross-cutting |
| Summary | A short, student-authored "how I like to learn" text saved to the account and injected into both the lesson tutor and personalized learning, below safety rules. |
| Priority | **P0** for W5.5 |
| Decision ref | `PL-C-002`; D-PL-04 |
| Job + moment | J1 · Asks; J8 · Starts |
| Value hypothesis | If a student can set tone/pace/language once, repeat correction turns drop and the tutor feels personal without profiling. |
| Metrics | M12 (prompt cost), `EVT-PL-01` (save), `EV-PL-004` (safety) |
| Principles | P7 honest personalization · P9 explicit-only · T5 |
| Evidence | [ASSUMPTION] value; [STRONG] minimization as a legal posture |
| Depends on / blocks | F2 settings; PL2 prompt assembly; PL4 settings UI |
| Layer independence | Instructions off/empty → both tutors behave exactly as today |

**Behaviour (EARS)**
1. When a signed-in student saves instructions, the system shall store one
   normalized text value (≤ 500 characters) on the account and apply it from the
   next tutor/teaching turn.
2. When either prompt is assembled, the system shall append the instructions as
   a **lower-priority, delimited preference block**, never as system/safety text.
3. When the student clears the field, the system shall delete the stored value
   and stop injecting it immediately.
4. If the text looks like an attempt to instruct the system or contains
   personal contact details, the system shall reject it with plain-language
   guidance and change nothing.
5. The system shall never solicit secrets, contact details, or identity data in
   the field's copy or examples.

**Acceptance criteria** — AC-1 a save round-trips and appears in the next voice
prompt (test). AC-2 an adversarial instruction cannot override safety or
grounding (`EV-PL-004`). AC-3 clear removes it from the prompt. AC-4 over-limit
and rejected states keep the previous value intact. AC-5 keyboard/screen-reader
complete; 44 px targets. AC-6 the field is absent for guests and in the 503
auth-down shell.

**States** default (empty) · saved · partial (auth down → field disabled with
reason) · error (save failed, retry) · offline (unsaved, explicit) ·
untranslated (English copy R1) · over-limit/rejected · consent-missing is n/a
(no voice opened by saving).

**Surfaces** `SCR-PL-04` (`/app/settings` section) · `EL-PL-04-001…007` ·
`API-PL-01…03` · `ENT-PL-Prefs` · `EVT-PL-01`.

### PL-F2 · Personalized learning hub

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | The login-required front door: pick a class/chapter/concept or describe the weakness in free text, start a session, or continue a saved one. |
| Priority | **P0** |
| Decision ref | `PL-C-001`, `PL-C-003`, `PL-C-004` |
| Job + moment | J8 · Arrives; J10 · Returns |
| Value hypothesis | If the hub asks one question ("what's confusing?") and offers the chapter picker, time-to-first-teach drops below 60 s for a student who knows the chapter. |
| Metrics | M8, M9; `EVT-PL-02` |
| Principles | P2 subtract first · P7 honest status · P8 no dead ends |
| Evidence | [ASSUMPTION] time-to-first-teach |
| Depends on / blocks | catalogue (`syllabus_chapter` / `/v1/catalog`), PL1 sessions API, PL2 index |
| Layer independence | With the model/index down, the hub still lists chapters and saved sessions and explains why a new session cannot start |

**Behaviour (EARS)**
1. When a signed-in student opens `/app/personalized`, the system shall show the
   chapter picker (class-grouped, only chapters with index coverage), a free-text
   weakness field (≤ 500 characters), and saved sessions.
2. When the student starts without a chapter, the system shall use the profile
   class and ask for a chapter or free-text weakness; it shall not guess.
3. When the index or model is unavailable, the hub shall show the honest
   unavailable state and keep history readable.
4. When a saved session exists, the hub shall show title, chapter, stage, and
   last-updated time with Continue / Export / Delete.

**Acceptance criteria** — AC-1 keyboard-only start in ≤ 3 focus stops. AC-2 no
chapter is offered without index coverage (no dead start). AC-3 guest → 303
`/login?next=/app/personalized`. AC-4 quota line is accurate to the last turn.
AC-5 empty history is honest, not a fake card.

**States** default · loading (SSR; no client spinner) · empty (no sessions,
chapter list available) · partial (some chapters source-only → badge) · error
(index/model down) · offline (cached list, new sessions disabled) · auth-required
(303) · quota-exhausted (start disabled, resume allowed) · consent-missing n/a ·
reduced-motion n/a · untranslated (English UI, content language noted).

**Surfaces** `SCR-PL-01` · `EL-PL-01-001…014` · `API-PL-04…09` ·
`ENT-PL-Session` · `EVT-PL-02`.

### PL-F3 · Teaching session (diagnose → teach → check → adapt → harder → mastery)

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | The loop itself: a 3-question diagnostic, one concept slice at a time, one check per slice, adaptation after a wrong answer, progressive difficulty to board-style, and a mastery summary. |
| Priority | **P0** |
| Decision ref | `PL-C-005`…`PL-C-008`, `PL-C-022`, `PL-C-024` |
| Job + moment | J1, J3, J8, J9 |
| Value hypothesis | If every teaching slice ends in a committed check and the next slice depends on it, the student's own answers — not the model's opinion — drive the path, and M10 becomes measurable. |
| Metrics | M9, M10, M11; `EVT-PL-03/04/05` |
| Principles | P5 predict-before-reveal/retrieval · P6 status · P7 honesty · P8 control |
| Evidence | [STRONG] retrieval practice; [MODERATE] worked-example/adaptation; [ASSUMPTION] slice length |
| Depends on / blocks | PL2 agent + RAG; P2 bank; PL1 persistence; PL4 UI |
| Layer independence | If the model fails mid-session, the transcript stays readable and the session is resumable; no check is ever auto-marked |

**Behaviour (EARS)**
1. When a session starts, the system shall run a diagnostic of at most 3
   bank-first questions covering the target concept and its direct
   prerequisites (or start at the chapter beginning if skipped).
2. When the diagnostic ends, the system shall choose the first concept by
   prerequisite order and gap evidence and enter `teach`.
3. When a teaching slice is delivered, the system shall ask exactly one check
   before teaching the next slice of the same concept.
4. When a check is wrong, the system shall re-teach the same concept with a
   different representation and ask a new check; after 3 failed checks it shall
   show a worked example, mark the concept `not_yet`, and offer to move on.
5. When a concept is `mastered` (L2 + L3 correct, at least one first-try), the
   system shall advance to the next concept; when every concept is taught or
   skipped, it shall raise difficulty through L3 and L4 (board-style).
6. When the session ends or reaches its cap, the system shall write a mastery
   summary with per-concept evidence and emit one progress event.

**Acceptance criteria** — AC-1 state transitions are deterministic and pass
`EV-PL-001` on 3 golden sessions. AC-2 no check appears before its teach slice.
AC-3 answer keys never reach the client before submission. AC-4 numeric scoring
uses the stated tolerance and unit rule. AC-5 every teaching turn has ≥1 valid
citation or says it is ungrounded. AC-6 the student can end at any point and the
summary is honest about coverage. AC-7 no generated item enters `question_bank`.

**States** default (teaching) · loading (streaming text with a live region) ·
empty (diagnostic not answered yet) · partial (artifact pending; citation
missing) · error (model/deadline → retry, transcript intact) · offline
(read-only transcript, new turns disabled) · auth-required (303) ·
quota-exhausted (turn blocked before spend; resume tomorrow) · reduced-motion
(static artifact frame) · untranslated (check item fallback in English, noted) ·
consent-missing n/a (no mic).

**Surfaces** `SCR-PL-02` · `EL-PL-02-001…030` · `API-PL-10…15` ·
`ENT-PL-Session/Message/Mastery` · `EVT-PL-03…07`.

### PL-F4 · Saved conversations, resume, history, export, delete

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | Every personalized session is a saved conversation with a title, chapter, stage, and timestamps; list, resume, export JSON, delete. Text and artifacts only; no audio. |
| Priority | **P0** |
| Decision ref | `PL-C-009`, `PL-C-010`, `PL-C-030`; merges `TUT-05` for the lesson dock per D-PL-09 (accepted, ADR-0030 — follow-up PR) |
| Job + moment | J5, J10 · Returns |
| Value hypothesis | If resume is one tap from the hub, repeat teaching drops and the product feels like a notebook, not a chat toy. |
| Metrics | M9; `EVT-PL-08/09` |
| Principles | P7 (visible memory) · P8 (control) · P9 (delete/export) |
| Depends on / blocks | PL1 tables; PL4 list/detail UI |
| Layer independence | History readable when the model is down; delete/export always work |

**Behaviour (EARS)**
1. When the first tutor turn completes, the system shall title the session from
   the chapter + concept (never from free text containing PII), ≤ 120 characters.
2. When a session is opened, the system shall load its last 50 turns and offer
   "load earlier" for the rest.
3. When the student exports, the system shall return JSON containing the
   session, its messages, mastery evidence, and artifact ids — no other user's
   data, no model prompts.
4. When the student deletes, the system shall hard-delete the session and its
   messages, and drop artifact references; shared cached artifacts remain until
   unreferenced and expired.

**Acceptance criteria** — AC-1 resume restores stage, difficulty, concept state,
and the last check. AC-2 export is valid JSON with a stable schema version.
AC-3 delete removes rows and the artifact reference (test). AC-4 titles contain
no free-text PII (test with a seeded email/phone). AC-5 list is owner-scoped
(IDOR test). AC-6 export includes the student's own preferences.

**States** default · loading · empty · partial (artifacts failed → id only) ·
error (DB down → honest panel) · offline (browser cache only) · auth-required
(303) · permission-denied (other user's id → 404) · reduced-motion n/a ·
untranslated (English UI) · quota-exhausted n/a (reading is free).

**Surfaces** `SCR-PL-01` history region, `SCR-PL-02` header · `EL-PL-01-010…014`,
`EL-PL-02-025…030` · `API-PL-04, 06…09, 15` · `ENT-PL-Session/Message`.

### PL-F5 · Interactive artifacts + sandboxed viewer

| Field | Value |
|---|---|
| Layer | ADD |
| Summary | When a visual would teach better than words, the agent requests a self-contained simulation or diagram; the server builds it with the factory's design/lint discipline, caches it by content hash, and shows it in a locked-down iframe with a text/diagram fallback. |
| Priority | **P0** (one artifact kind: simulation; diagram fallback) |
| Decision ref | `PL-C-011`, `PL-C-012`, `PL-C-019`, `PL-C-025` |
| Job + moment | J9 · Reads/visualizes |
| Value hypothesis | If the artifact answers the student's stated confusion, the next check's first-try rate rises versus a text-only turn (A/B at kid tests). |
| Metrics | M14; `EVT-PL-06/07`; `EV-PL-003` |
| Principles | P3 direct manipulation · P10 weak Android · PL-T4 sandbox |
| Evidence | [STRONG] simulations help; [ASSUMPTION] per-turn generation quality |
| Depends on / blocks | PL3 builder + sandbox; PL2 turn contract; PL4 viewer |
| Layer independence | Artifact failure never blocks the teaching turn; the text/diagram fallback is always present |

**Behaviour (EARS)**
1. When the decide call requests an artifact, the system shall validate the
   spec, build it within the artifact budget, lint and render-check it, and
   attach it to the turn as `pending → ready|failed`.
2. When ready, the client shall render it in an iframe with
   `sandbox="allow-scripts"` (no `allow-same-origin`), a strict CSP document,
   no network/storage/forms/top navigation, and a visible title + fallback.
3. When the build fails or exceeds its deadline, the turn shall show the
   diagram/text fallback and an honest one-line note; it shall not retry
   silently more than once.
4. When the artifact is off-screen or the student prefers reduced motion, the
   animation shall pause; a visible Play control resumes it.

**Acceptance criteria** — AC-1 lint rejects external URLs, eval/Function,
network APIs, storage APIs, forms, and top navigation; 5 seeded defects each
fail (`EV-PL-003`). AC-2 headless render: zero console errors, zero network
requests, no 360 px overflow, ≥24 fps under 4× throttle. AC-3 no artifact can
read the parent DOM, cookies, or localStorage (red-team test). AC-4 content-hash
cache hit costs zero model calls. AC-5 deletion of all referencing sessions
allows purge after the cache window.

**States** default (ready) · loading (pending card) · empty (agent decided no
artifact) · partial (failed → fallback) · error (viewer load timeout) · offline
(cached artifact HTML may render; build disabled) · permission-denied (artifact
not owned/not referenced → 404) · reduced-motion (static frame + Play) ·
untranslated (title/fallback in session language where available) ·
quota-exhausted (artifact budget spent → fallback, honest note) · consent-missing
n/a.

**Surfaces** `SCR-PL-03` artifact region · `EL-PL-03-001…012` ·
`API-PL-13/14` · `ENT-PL-Artifact`.

### PL-F6 · Free-tier quota, rate limits, caching, and cost guard

| Field | Value |
|---|---|
| Layer | XCT / OPS |
| Summary | Login-required free access with honest per-user and global quotas, rate limits, artifact caching, and a cost ledger. No plan, no payment, no entitlement. |
| Priority | **P0** |
| Decision ref | `PL-C-018`, `PL-C-028`; D-PL-01, D-PL-06 |
| Job + moment | J7 · Operates; J1 · Asks (during an outage) |
| Value hypothesis | If quotas fail honestly and caching works, a shared subscription survives real student testing without a paywall or a surprise cut-off. |
| Metrics | M12, M13; `EVT-PL-10`; `EV-PL-005` |
| Principles | P7 honest limits · P8 finish the turn · P10 designed degradation |
| Evidence | [STRONG] as an operational constraint; numbers [ASSUMPTION] |
| Depends on / blocks | guard-style counters; abuse limiter; PL1/PL2 |
| Layer independence | Quota exhaustion blocks only new teaching turns; reading, history, export, and the lesson pages stay up |

**Behaviour (EARS)**
1. When a turn starts, the system shall check the per-user and global counters
   atomically and reserve the turn before any model call.
2. When the per-user quota is exhausted, the system shall return
   `E-QUOTA-EXHAUSTED` with `reset_at` and keep history/resume/export working.
3. When the global quota/concurrency is exhausted, the system shall return 503
   with `Retry-After` and an honest message; it shall not silently degrade
   quality.
4. When a turn ends, the system shall write one usage row (tokens, latency,
   artifact build, outcome) and actualize the counters.
5. When an artifact request matches a cached content hash, the system shall
   reuse it and record a cache hit with zero model calls.

**Acceptance criteria** — AC-1 concurrent turn race never exceeds the cap
(atomic test). AC-2 reset is 00:00 IST and the UI shows the time. AC-3 429
carries `Retry-After`; 403 quota carries `reset_at`. AC-4 in-progress turns
finish. AC-5 cache hit produces no model call (test seam). AC-6 no
plan/subscription/payment/entitlement table exists (docs contract test).

**States** normal · warn (≤15% remaining, one quiet line) · per-user exhausted ·
global exhausted · rate-limited · cache-hit · model-down (degraded, not quota) ·
auth-required.

**Surfaces** `EL-PL-01-013`, `EL-PL-02-004/024`, `SCR-PL-05` quota line ·
`API-PL-15` usage · `ENT-PL-Usage/Quota` · `EVT-PL-10`.

## 5. Screens and regions

| Screen | Route | Regions |
|---|---|---|
| **SCR-PL-01** hub | `/app/personalized` | R1 header + quota · R2 chapter/concept picker · R3 weakness input · R4 start actions · R5 saved sessions |
| **SCR-PL-02** session | `/app/personalized/{session_id}` | R1 header (title/chapter/stage/quota/end) · R2 transcript · R3 check card · R4 artifact region · R5 composer/actions · R6 summary |
| **SCR-PL-03** artifact viewer | region inside SCR-PL-02 | R1 title/meta · R2 iframe stage · R3 controls (reload/expand/report) · R4 text fallback |
| **SCR-PL-04** settings section | `/app/settings` | R1 title/help · R2 textarea + counter · R3 save/clear · R4 status copy |
| **SCR-PL-05** quota strip | hub + session | remaining, reset time, warn/exhausted copy |

The full state matrix (all 11 canonical states plus `auth-required`, per screen/region) is
[`spec.md`](spec.md) §7.

## 6. UI element inventory (compact)

Only elements this feature adds; existing shell/settings elements keep their
`EL-*` ids from `docs/product/ui-element-inventory.csv`.

| Element | Screen.region | Type | Content source | Interaction / event | Notes |
|---|---|---|---|---|---|
| `EL-PL-01-001` | SCR-PL-01.R1 | heading | static copy | — | "Learn what's weak" |
| `EL-PL-01-002` | SCR-PL-01.R1 | quota line | `API-PL-15` | — | `EVT-PL-10` on render |
| `EL-PL-01-003` | SCR-PL-01.R2 | class tabs | catalogue | filter list | keyboard radiogroup |
| `EL-PL-01-004` | SCR-PL-01.R2 | chapter picker | `/v1/catalog` + index coverage | select | source-only badge |
| `EL-PL-01-005` | SCR-PL-01.R2 | concept picker | `concepts` | optional select | only for a chosen chapter |
| `EL-PL-01-006` | SCR-PL-01.R3 | textarea | student | max 500; counter | no PII solicitation |
| `EL-PL-01-007` | SCR-PL-01.R3 | helper/examples | static | insert example | examples not prefilled |
| `EL-PL-01-008` | SCR-PL-01.R4 | primary Start | — | `POST /sessions` | disabled on quota |
| `EL-PL-01-009` | SCR-PL-01.R4 | secondary "chapter start" | — | start at concept 1 | skip diagnostic |
| `EL-PL-01-010` | SCR-PL-01.R5 | session row | `personalized_session` | open | title/chapter/stage/date |
| `EL-PL-01-011` | SCR-PL-01.R5 | Continue | — | open session | one tap |
| `EL-PL-01-012` | SCR-PL-01.R5 | Delete | — | confirm → delete | confirm-then-do |
| `EL-PL-01-013` | SCR-PL-01.R5 | Export | — | download JSON | owner only |
| `EL-PL-01-014` | SCR-PL-01.R5 | empty state | static | start first session | honest |
| `EL-PL-02-001` | SCR-PL-02.R1 | title | session | — | chapter/concept title |
| `EL-PL-02-002` | SCR-PL-02.R1 | stage chip | session.stage | — | Diagnosing/Teaching/Checking/Deeper/Board/Mastery |
| `EL-PL-02-003` | SCR-PL-02.R1 | chapter link | catalogue | navigate | leaves session (saved) |
| `EL-PL-02-004` | SCR-PL-02.R1 | quota | API-PL-15 | — | warn/exhausted |
| `EL-PL-02-005` | SCR-PL-02.R1 | End session | — | confirm → summary | always available |
| `EL-PL-02-006` | SCR-PL-02.R2 | teaching card | turn payload | read | citation chips |
| `EL-PL-02-007` | SCR-PL-02.R2 | citation chip | turn citations | expand source line | `NCERT Ch. 4 p. 47` |
| `EL-PL-02-008` | SCR-PL-02.R2 | ungrounded note | turn flag | — | honest note |
| `EL-PL-02-009` | SCR-PL-02.R3 | check stem | check payload | read | Bricolage, no color-only |
| `EL-PL-02-010` | SCR-PL-02.R3 | option chips | check options | select one | radiogroup, keyboard |
| `EL-PL-02-011` | SCR-PL-02.R3 | numeric input | check payload | type | unit shown |
| `EL-PL-02-012` | SCR-PL-02.R3 | Check button | — | submit | 44 px |
| `EL-PL-02-013` | SCR-PL-02.R3 | feedback | answer result | — | shape + words |
| `EL-PL-02-014` | SCR-PL-02.R3 | "Why?" | explanation | disclosure | after submit only |
| `EL-PL-02-015` | SCR-PL-02.R3 | hint | hint payload | reveal (≤2) | logs hint rung |
| `EL-PL-02-016` | SCR-PL-02.R3 | skip concept | — | confirm | marks skipped |
| `EL-PL-02-017` | SCR-PL-02.R4 | artifact card | artifact | render iframe | see SCR-PL-03 |
| `EL-PL-02-018` | SCR-PL-02.R5 | reply textarea | student | optional free reply | "explain differently" |
| `EL-PL-02-019` | SCR-PL-02.R5 | "Explain directly" | — | direct mode for this slice | T9 |
| `EL-PL-02-020` | SCR-PL-02.R5 | "I'm stuck" | — | hint/worked example | max 2 hints |
| `EL-PL-02-021` | SCR-PL-02.R6 | mastery summary | session state | — | per concept + evidence counts |
| `EL-PL-02-022` | SCR-PL-02.R6 | next chapter CTA | catalogue | navigate | only when mastered |
| `EL-PL-02-023` | SCR-PL-02.R6 | resume later | — | back to hub | session saved |
| `EL-PL-02-024` | SCR-PL-02.R1 | connection chip | stream state | — | thinking/streaming/offline |
| `EL-PL-02-025` | SCR-PL-02.R2 | earlier turns | messages page | load earlier | cursor |
| `EL-PL-02-026` | SCR-PL-02.R2 | export | — | download | same as hub |
| `EL-PL-02-027` | SCR-PL-02.R2 | delete | — | confirm | same as hub |
| `EL-PL-02-028` | SCR-PL-02.R2 | personal-preferences note | prefs state | link settings | "using your learning preferences" |
| `EL-PL-02-029` | SCR-PL-02.R5 | quota-exhausted copy | API-PL-15 | — | reset time |
| `EL-PL-02-030` | SCR-PL-02.R1 | report problem | — | report flow | reuses F4 report path |
| `EL-PL-03-001` | SCR-PL-03.R1 | artifact title | artifact | — | kind + concept |
| `EL-PL-03-002` | SCR-PL-03.R2 | iframe stage | artifact | sandboxed render | fixed aspect, 8 rows max |
| `EL-PL-03-003` | SCR-PL-03.R2 | loading state | — | — | skeleton + text |
| `EL-PL-03-004` | SCR-PL-03.R2 | error state | — | retry once | then fallback |
| `EL-PL-03-005` | SCR-PL-03.R3 | reload | — | reload iframe | — |
| `EL-PL-03-006` | SCR-PL-03.R3 | expand | — | in-page expand | never new tab |
| `EL-PL-03-007` | SCR-PL-03.R3 | pause/play | — | postMessage | reduced motion default paused |
| `EL-PL-03-008` | SCR-PL-03.R3 | report artifact | — | report flow | category=artifact |
| `EL-PL-03-009` | SCR-PL-03.R4 | text fallback | turn text | — | always present |
| `EL-PL-03-010` | SCR-PL-03.R4 | diagram fallback | static SVG | — | from decide payload |
| `EL-PL-03-011` | SCR-PL-03.R1 | provenance | artifact | — | "generated for this session" |
| `EL-PL-03-012` | SCR-PL-03.R1 | sandbox note | static | — | "runs isolated; no network" |
| `EL-PL-04-001` | SCR-PL-04.R1 | section title | static | — | "How I like to learn" |
| `EL-PL-04-002` | SCR-PL-04.R1 | help + privacy line | static | — | no personal details |
| `EL-PL-04-003` | SCR-PL-04.R2 | textarea | prefs | max 500 | counter |
| `EL-PL-04-004` | SCR-PL-04.R2 | example chips | static | insert | three safe examples |
| `EL-PL-04-005` | SCR-PL-04.R3 | Save | — | PUT | CSRF |
| `EL-PL-04-006` | SCR-PL-04.R3 | Clear | — | DELETE + confirm | confirm-then-do |
| `EL-PL-04-007` | SCR-PL-04.R4 | status | save state | — | saved/rejected/error |

## 7. Traceability check (zero orphans)

- Every feature card cites a job, a metric, a decision row, at least one
  screen/element, an API, an entity, and an event.
- Every screen region has at least one element row; every element appears in
  exactly one screen region.
- Every API in [`data-and-api.md`](data-and-api.md) §4 is consumed by an
  element or a workstream; every table in §2 traces to an entity above.
- Every event in [`agent-and-rag.md`](agent-and-rag.md) §10 has a privacy class
  (`L1`/`L2`) and no free-text field.
- Every eval card in [`evals.md`](evals.md) maps to at least one acceptance
  criterion above.

## 8. Self-review findings (recorded)

| Check | Result |
|---|---|
| Value filter | 30 candidates; 15 KEEP, 1 MERGE, 4 DEFER, 10 KILL — all recorded in the CSV |
| Layer independence | Pass: with PL off, lessons, practice, tests, voice dock unchanged |
| All-states rule | Pass: 11 canonical states + `auth-required` per screen in `spec.md` §7 |
| Child-safety pass | Pass with one flag: stored session text is child free text → 90-day cap, no cold copy, no logs, export/delete, counsel review before scale-up (D-PL-05) |
| Doctrine | Pass with one open item: the session screen has no doctrine section yet; it uses §1–§9 base components. If the founder wants lesson devices, a DCR is required (D-PL-10) |
| No dark patterns | Pass: no streaks, no countdowns, no fake urgency; quota copy is factual; export/delete are not buried |
