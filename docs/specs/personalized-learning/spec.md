# Product flow — personal instructions, personalized learning, saved conversations, artifacts

Status: **implemented (the PL4 frontend landed 2026-11-19; the landed
frontend contract and state matrix are
[`docs/specs/frontend/personalized.md`](../frontend/personalized.md)).**
Read [`agent-and-rag.md`](agent-and-rag.md) for the teaching brain,
[`interactive-artifacts.md`](interactive-artifacts.md) for the artifact
pipeline, and [`data-and-api.md`](data-and-api.md) for the exact contracts.

The binding product rule: this is a **free, login-required prototype** for real
student testing. There is no paywall, plan, trial, or payment. Quotas and rate
limits are fairness/cost controls, not entitlements. Every limit is explained in
plain language before it blocks a student.

---

## 1. Personal instructions (account-level)

### 1.1 What it is

One short text field — "How I like to learn" — stored on the account, editable
and clearable in `/app/settings`, and injected into:

1. the lesson-page voice tutor (`/voice/ws`, signed-in sessions), and
2. personalized learning (`/app/personalized`).

It is a **preference**, not a system instruction. It can shape tone, language
mix, pacing, and the kind of examples used. It can never change safety rules,
grounding, privacy, scoring, or the spoken contract.

### 1.2 Field contract

| Property | Value |
|---|---|
| Storage | `user_preferences.personal_instructions` (one row per user; see data-and-api §2.1) |
| Max length | **500 characters** after normalization (Unicode NFC, trimmed) |
| Line shape | up to 5 lines; newlines preserved as separators, repeated blank lines collapsed |
| Allowed | "explain step by step", "use Hinglish", "give a worked example first", "keep answers short", "I like diagrams" |
| Not allowed | personal contact details, addresses, school names, passwords/keys, and clear jailbreak phrases ("ignore previous instructions", "you are now…", "reveal the system prompt"). A physics phrase like "the system of equations" is allowed — the phrase list is narrow, never a bare "system" token |
| Normalization | NFC; strip control chars (except newline); collapse >2 blank lines; strip a leading `system:` / `assistant:` / `user:` / `REF:` marker per line |
| Validation result | `200 saved` · `422 rejected` (with the reason and the previous value untouched) |
| Precedence | safety/system rules > grounding > spoken/format contract > **personal instructions** > session state |
| Application | next tutor turn / next teaching turn; no restart needed |
| Clear | `DELETE` removes the value immediately; both prompts stop including it on the next turn |
| Export | included in `/v1/me/export` and in the session export as `preferences` |
| Deletion | hard-deleted with the account; no cold copy; never logged |

### 1.3 UX (settings section `SCR-PL-04`)

```
How I like to learn
Tell Zivon how to explain things. This is saved to your account and used in
lessons and personalized learning. Don't include personal details.

[ Explain step by step. Use Hinglish. Give a worked example before practice. ]
                                                              123 / 500

[ Save ]   [ Clear ]

What this can't do: change safety rules, make Zivon ignore the lesson, or ask
you for personal information.
```

- Save is disabled while unchanged or over the limit; the counter turns
  pencil-red only when over 500.
- Clear is confirm-then-do ("Clear your learning preferences? Lessons will use
  the default style.").
- Example chips insert text at the cursor; they never auto-save.
- The field is absent for guests (the whole settings page is guarded) and
  disabled with a reason in the 503 auth-down shell.
- A status line is `role="status"`: "Saved. Zivon will use this from your next
  question." / "That looks like a personal detail. Try describing how you like
  to learn instead."
- Saving emits `EVT-PL-01` with `{action: save|clear, length_bucket}` only — no
  text.

### 1.4 Prompt injection posture (summary)

The instructions are **untrusted student data**. They ride in a separately
delimited block labelled "student-authored preference, lower priority than the
rules above", never concatenated into the safety prompt. The full contract and
the adversarial tests are in [`agent-and-rag.md`](agent-and-rag.md) §7 and
[`security-privacy.md`](security-privacy.md) §4.1.

### 1.5 Honest personalization

The lesson dock and the session header show one quiet line when preferences are
active: "Using your learning preferences · Edit". It links to settings. This is
the visible counterpart of the stored field (P7/P9); personalization is never
silent.

---

## 2. Personalized learning

### 2.1 Entry and login

- Route: `/app/personalized` (hub) and `/app/personalized/{session_id}`
  (session). A guest gets `303 /login?next=/app/personalized`.
- Login is required because sessions, mastery evidence, and preferences are
  account-scoped. The lesson pages and the voice dock stay guest-first
  (D-PL-11: the correction is read as this feature, not the whole product).
- The hub is server-rendered; the live turn stream is a small same-origin JS
  island (no SPA).

### 2.2 Start a session

The student chooses **one** of:

1. **Chapter** (class-grouped picker) and optionally a concept; or
2. **Free-text weakness** — up to 500 characters ("I don't get why the area
   under a v-t graph is displacement"); or
3. **"Start from the chapter beginning"** — skips the diagnostic and starts at
   the first concept.

The server resolves the input to a chapter + concept set:

- Explicit chapter/concept wins.
- A free-text weakness is mapped to the chapter's concepts by the decide call
  (lexical + embedding retrieval over concept titles/descriptions); the chosen
  concept is shown as a chip ("Starting with: Velocity-time graphs") and the
  student can ask for a different one in the first turn (a `message` action
  re-maps it) or restart from the hub. The chapter itself is resolved
  deterministically at create time (never guessed).
- No class/chapter is guessed silently. If the profile class is unset, the hub
  asks for it in the picker.

Only chapters with **index coverage** are offered. Coverage has two honest
tiers:

| Tier | Meaning | Badge |
|---|---|---|
| `lesson` | A published lesson page exists; teaching can quote reviewed page wording plus the source pack | none |
| `source` | No published lesson yet; teaching uses NCERT source-pack text only | "source only" |

A chapter with neither is not listed; a direct URL returns
`E-CONTENT-UNAVAILABLE` with the catalogue link.

### 2.3 Diagnostic (max 3 questions)

- Purpose: find the entry concept and difficulty; not a test, no score shown as
  a grade.
- Items are **bank-first** (`question_bank`: same chapter/concept, difficulty
  1–2, active, session language; exclude items already used in this session).
  If the bank cannot supply 3, one model call generates the missing item(s);
  generated items stay in the session payload and are **never written to
  `question_bank`** (`PL-T2`, `PL-C-022`).
- Coverage: the target concept and up to two direct prerequisites, in
  prerequisite order.
- Interaction: one question per card; "Not sure" is a valid answer (counts as a
  gap, no shame copy); no timer; no score.
- Result (internal): per concept `known` / `gap` / `unknown`; entry concept =
  first `gap` in prerequisite order, else the explicit concept, else the first
  concept.
- Skip: "Start from the beginning" is always available. Skipping sets the entry
  concept to the first concept and difficulty L1.
- Completion emits `EVT-PL-02` with counts only.

### 2.4 The teaching loop

The student-visible rhythm is: **a little teaching → one check → feedback →
adapt or move on**. The full state machine is
[`agent-and-rag.md`](agent-and-rag.md) §2; this section is the product view.

| Stage | What the student sees | Exit |
|---|---|---|
| **Diagnose** | 1–3 short questions, "Not sure" allowed | all answered or skipped |
| **Teach** | one concept slice: ≤ 4 short paragraphs, one key statement, optional worked example, optional artifact; citation chips under the slice | Check pressed |
| **Check** | exactly one MCQ or numeric question; options have no answer key; unit shown for numeric; no timer | answer submitted |
| **Feedback** | correct/incorrect in shape + words; one-sentence why; "Why?" disclosure with the full explanation; hint available before submitting (≤ 2) | continue |
| **Adapt** | after a wrong answer: the same concept re-taught with a **different representation** (analogy, diagram, worked example), then a new check | correct → advance; 3 fails → worked example + `not_yet` + offer to move on |
| **Advance** | the next concept in prerequisite order, difficulty reset to L1–L2 for that concept | all concepts taught/skipped |
| **Harder** | difficulty rises one level (L1→L2→L3) on the current concept or a mixed set; each level has its own check | L3 passed |
| **Board** | L4 items: multi-step numericals / 3–5 mark "board-style" questions with step-mark-style answers; copy says **board-style**, never "official CBSE" | at least one L4 attempted or the student ends |
| **Mastery** | per-concept summary: mastered / practising / not yet / skipped, evidence counts, coverage; next-chapter CTA when the chapter is mastered | end |
| **Done** | summary stays; session is resumable only if it was ended before the cap | — |

**Teaching slice contract (product view):**

- ≤ 4 paragraphs, each ≤ 70 words; one key statement; no markdown/LaTeX in the
  visible text (formulas are plain text).
- Every slice carries ≥ 1 citation chip, or the turn says "no page reference
  found" (ungrounded) and the student sees an honest note.
- The language follows the student's UI/typing language (EN / HI / Hinglish);
  physics terms stay English on first mention with a Hindi gloss where the
  glossary has one.
- The slice never introduces a claim the retrieved sources do not support; the
  grounding law is the same as the lesson tutor's (T12).

**Check contract (product view):**

- Exactly one check per teach slice; the check must be answerable from the slice.
- MCQ: 2–4 options, one correct; options are chips in a radiogroup; selected
  state is visible by fill, not only colour.
- Numeric: a plain number input + unit label; tolerance
  `max(0.01, 0.005 × |expected|)`; a unit mismatch is incorrect with a unit
  hint, not a silent pass.
- The correct answer and explanation never enter the client payload before
  submission; scoring is deterministic on the server.
- A wrong answer never shames; it produces the misconception-targeted sentence
  when the bank item has one, otherwise a neutral "not yet — let's look again".

**Difficulty levels:**

| Level | Kind | Example |
|---|---|---|
| L1 | recall / definition | "Which quantity does the slope of a v-t graph give?" |
| L2 | single-step application | "A body speeds up from 2 to 8 m/s in 3 s. Find a." |
| L3 | multi-step numerical | "A train decelerates uniformly over 200 m…" |
| L4 | board-style 3–5 mark | multi-part: calculate + explain + graph/Justify |

L4 items carry a `board_style: true` flag and the notice copy in §9. They are
generated or bank items labelled as Zivon practice, never as CBSE questions.

### 2.5 Mastery evidence (explicit, visible, deletable)

Per concept, the server stores only what the student did:

- `attempts`, `first_try_correct`, `last_correct`, `levels_attempted`,
  `levels_passed`, `status`, `last_check_id`.

Status rules (deterministic):

| Status | Rule |
|---|---|
| `not_started` | no teach slice delivered |
| `learning` | taught, no correct check yet |
| `practising` | ≥ 1 correct at L1 or L2 |
| `mastered` | ≥ 1 correct at L2 **and** ≥ 1 correct at L3, with at least one of those first-try |
| `board_ready` | `mastered` **and** ≥ 1 correct at L4 |
| `skipped` | student skipped the concept (visible; not counted as mastered) |

No hidden ability score, no cross-student comparison, no model-inferred trait.
The summary shows the counts that produced the status. The same evidence is
emitted as a progress event so F3/SWOT can read it without a second store.

### 2.6 Session length and limits

- **Coverage means the selected chapter.** "Full coverage" is every concept in
  the chosen chapter taught or explicitly skipped; it is not a claim that every
  syllabus chapter is available (that is the index-coverage rule, D-PL-02).
- Soft nudge at **40 turns**: "You've done a lot — you can stop here and
  continue later." Not a modal, one line.
- Hard cap at **60 turns** per session; the session ends with the mastery
  summary. Resuming after the hard cap starts a new session linked to the old
  one (`parent_session_id`, display-only — no state or mastery carries over),
  shown as "continue from your last session".
- Daily/per-minute limits are §5; an in-progress turn always finishes.
- The student can end at any time; End is not buried and does not require a
  confirmation dialog (it is reversible by resuming).

### 2.7 Resume and history

- The hub lists sessions ordered by `last_turn_at desc`, with title, chapter,
  stage chip, and a relative date.
- Continue loads the session at the exact stage, concept, and difficulty; the
  last check is shown with its result, not re-asked.
- The session loads the last 50 messages; "Load earlier" pages backwards.
- A session left idle for **90 days** is auto-deleted (D-PL-05) with a warning
  in the list at 83 days ("deletes in 7 days · export it").
- Delete is hard and immediate after confirm; export is a JSON download.

---

## 3. Saved conversations (the chat model)

There is **one** saved-conversation store for personalized learning:
`personalized_session` + `personalized_message`. A "chat" is a session whose
`mode='chat'` (free-form follow-ups inside a teaching session) or a
`mode='learning'` session viewed as a transcript. Titles, chapter/topic,
timestamps, resume, delete, and export are the same operations.

- No raw audio, ever (T11). The only media is generated artifact HTML.
- Text and artifact references only; a deleted artifact leaves a text fallback.
- The lesson-page voice dock's own doubt history (`TUT-05`) is **not** created
  by this feature. D-PL-09 is accepted (`ADR-0030`, 2026-11-18): it merges into
  the same store (`origin='lesson_dock'`) because two chat stores would confuse
  delete/export; the merge is a follow-up PR, so until it lands this feature
  owns only the personalized store.
- Search is deferred (`PL-C-026`); the list is short and ordered.
- The transcript is private to the owner; no share links, no public profile, no
  parent/teacher view (`PL-C-016/017`).

---

## 4. Interactive artifacts (product view)

Full contract: [`interactive-artifacts.md`](interactive-artifacts.md).

- The agent may request **one** artifact per teaching slice when a visual would
  teach better than words: a simulation (sliders/canvas) or a diagram (static
  SVG). It is a request, not a guarantee.
- The artifact is built **after** the teaching text starts streaming, so the
  student reads while it builds. It appears as a card with a title and a
  "building a visual…" state, then renders in a sandboxed iframe.
- Failed/timed-out build → the turn keeps the text and a diagram/text fallback
  with a one-line note ("The visual didn't build. Here's the diagram instead.").
- The viewer has: title, kind + concept, reload, in-page expand, pause/play
  (reduced motion starts paused), report, and a provenance line ("generated for
  this session from NCERT Ch. 4").
- No "open in new tab" (the sandbox story dies at top-level navigation;
  `PL-C-025`). Expand is an in-page overlay.
- Artifacts are content-addressed and shared across sessions when identical
  (the spec is public content, never the student's weakness text).

---

## 5. Free prototype: login, quotas, caching, cost

### 5.1 Login

- Personalized learning, preferences, history, export, and delete require a
  session cookie. The lesson pages, catalogue, practice, tests, and the voice
  dock keep their existing guest behaviour.
- Login is the only gate. There is no plan check, no trial timer, no paywall,
  no "upgrade" CTA anywhere in this feature.

### 5.2 Quotas (recommended defaults — D-PL-01)

| Scope | Limit | Reset |
|---|---|---|
| Per user, teaching turns | 40 / day | 00:00 IST |
| Per user, new sessions | 5 / day | 00:00 IST |
| Per user, turn rate | 6 / minute | rolling |
| Per user, concurrent turns | 2 | rolling |
| Per user, artifact builds | 12 / day, 4 / session | 00:00 IST |
| Unverified-email accounts | 20 turns / day (recommended, D-PL-08) | 00:00 IST |
| Per IP, personalized requests | 20 / minute | rolling |
| Global, teaching turns | 1,500 / day | 00:00 IST |
| Global, concurrent model calls | 8 | rolling |
| Global, artifact builds | 300 / day | 00:00 IST |

- Diagnostics count as turns, one per answered question (up to 3); starting
  with a diagnostic therefore costs up to 3 of the daily turns. Reading history,
  resume, export, and delete are **not** metered.
- A **warn** line appears at ≤ 15% remaining ("3 turns left today · resets
  00:00 IST"). The line is factual, not urgent.
- The quota is checked and reserved **before** any model call, then actualized
  at turn end. A failed turn returns its reservation.
- Per-user exhausted → `403 E-QUOTA-EXHAUSTED` + `reset_at`; the transcript,
  resume, export, and delete still work.
- Global exhausted or all 8 slots busy → `503 E-QUOTA-EXHAUSTED` (or
  `E-SERVICE-UNAVAILABLE` for a model outage) + `Retry-After`; copy says
  "Zivon is at its daily limit. Your work is saved; try again after 00:00 IST."
- Rate limit → `429 E-RATE-LIMIT` + `Retry-After`; copy names the wait in
  seconds, not a vague "later".
- No dark patterns: no countdown timers, no fake scarcity, no "streak lost"
  message, no upsell.

### 5.3 Caching

| Cache | Key | Benefit | Invalidation |
|---|---|---|---|
| Artifact | `sha256(spec + prompt_version + doctrine_version + schema_version)` | identical visuals cost zero model calls | version bump or manual purge |
| RAG retrieval | `sha256(chapter + concept set + query + index_version)` | repeated questions reuse the same chunks | index version |
| Static teaching assets | lesson/manifest content hash | no re-indexing on every boot | content publish |
| Never cached | teaching prose, checks, mastery, personal instructions | personalization must be honest | — |

### 5.4 Cost and observability

- Every model call writes one `personalized_usage` row: model, input/output
  tokens, latency, stage, cache hit, artifact build, outcome. No free text.
- Daily totals by user and global; admin sees cost per session (M12), artifact
  success (M14), and quota blocks (M13).
- The model route has a **kill switch** (`ZIVON_PERSONALIZED_ENABLED=false`)
  that turns the feature into a read-only history view with an honest notice.
  It does not affect lessons, practice, or the voice dock.

---

## 6. Screens

### 6.1 `SCR-PL-01` — personalized hub (`/app/personalized`)

Layout (base Field Notes §1–§9; no §10 lesson devices):

```
Learn what's weak                                      [ 37 turns left today ]
Pick a chapter, or tell Zivon what's confusing. It teaches a little, checks,
and adjusts.

Class:  [9] [10] [11] [12]
Chapter: [ Light – Reflection and Refraction        v ]   (source only)
Concept: [ Spherical mirrors                         v ]   (optional)

What's confusing? (optional)
[ I don't get why the image in a concave mirror flips                ] 54/500
[ Start ]   [ Start from the chapter beginning ]

Your sessions
┌ Light – Reflection and Refraction · Spherical mirrors ─ Checking · 2 h ago ┐
│ Continue   Export   Delete                                                 │
└────────────────────────────────────────────────────────────────────────────┘
```

- The chapter picker is a native `<select>` (keyboard + screen reader) on
  mobile; class tabs are a radiogroup. No search in R1 (fewer than 25 chapters
  per class).
- Start validates: chapter or weakness required; weakness ≤ 500 chars; quota
  available.
- Empty history: "No sessions yet. Start with the chapter you're studying."
- Source-only badge is text, not colour alone.

### 6.2 `SCR-PL-02` — session (`/app/personalized/{id}`)

```
Light – Reflection and Refraction · Spherical mirrors     [ Checking ]  [End]
Using your learning preferences · Edit                       37 turns left

  Teacher card 1 (paper card)
  A concave mirror curves inward. Parallel rays meet at the focus…
  [NCERT Class 10 Science, Ch. 9, p. 148]  [lesson: Ray diagrams]

  Check 1 of this idea
  Where does a parallel ray reflect in a concave mirror?
  ( ) Through the centre of curvature
  ( ) Through the principal focus        [ Check ]
  ...

  Visual (artifact card)
  [ sandboxed simulation: move the object, see the image ]
  [Reload] [Expand] [Pause] [Report]   generated for this session

  [ Explain directly ] [ I'm stuck ] [ Ask something else…        ] [Send]
```

- The transcript is a vertical list of cards; stage changes are small meta
  lines ("Now practising: mirror formula").
- Streaming text appears in the live card; an `aria-live="polite"` region
  announces "Zivon is writing" then the first sentence, not every token.
- The check card is disabled while a turn is streaming (one thing at a time).
- End session confirms once and shows the summary; resuming is always possible.

### 6.3 `SCR-PL-03` — artifact viewer (region)

- Card title + kind; iframe in a fixed-aspect box (max 8 rows tall at desktop,
  5 on phones) with `sandbox="allow-scripts"`, `referrerpolicy="no-referrer"`,
  `allow=""`, and a strict CSP document.
- Controls: Reload, Expand (in-page overlay), Pause/Play, Report.
- Fallback: the turn's text + a static diagram (if the decide payload included
  one) are always in the DOM; the viewer failure state never leaves an empty
  box.
- A sandbox note is visible once per session in the card meta: "Runs isolated —
  no network, no access to your account."

### 6.4 `SCR-PL-04` — settings section

See §1.3.

### 6.5 `SCR-PL-05` — quota strip

A single line in the hub and session header: remaining turns, reset time, and
the warn/exhausted copy. It is part of the page, not a toast; it never overlays
content. On the session page it is next to the stage chip.

---

## 7. States (all 11, per screen)

The canonical vocabulary is the frontend 11-state rule
(`skills/zivon-frontend-product-skills/`): default, loading, empty, partial, error, offline,
permission-denied, reduced-motion, untranslated, quota-exhausted, consent-missing. Each
table adds `auth-required` (the `/app` guard's 303) as a separate row so the guard state is
never confused with a permission denial. Legend: `n/a (reason)` is a valid cell. Copy is
English at R1; translation follows the UI-translation workstream.

### 7.1 `SCR-PL-01` hub

| State | What the student sees |
|---|---|
| default | chapter picker + weakness field + saved sessions + quota line |
| loading | n/a — SSR completes before bytes; a slow DB is the panel error |
| empty | "No sessions yet" + the start form (not a fake card) |
| partial | some chapters source-only → badge; no chapter → "No chapter with content yet" + catalogue link |
| error | "Personalized learning is unavailable right now" + retry; history still listed if readable |
| offline | browser offline page for navigation; a cached page shows "You're offline — saved sessions need a connection" |
| auth-required | `303 /login?next=/app/personalized` |
| permission-denied | n/a (a valid session owns its own list); another user's id never appears here |
| reduced-motion | no animation; no change needed |
| untranslated | English UI; the saved language is shown in the shell, not silently applied |
| quota-exhausted | Start disabled with "You've used today's turns. Your sessions are safe; resets 00:00 IST." Resume/export/delete still enabled |
| consent-missing | n/a — no microphone or voice is opened by this screen |

### 7.2 `SCR-PL-02` session

| State | What the student sees |
|---|---|
| default | transcript, current check, composer, quota, stage chip |
| loading | streaming card with a live region ("Zivon is writing…"), check card disabled |
| empty | diagnostic not answered yet: one question card + "Not sure" + skip |
| partial | artifact pending ("building a visual…"), citation missing ("no page reference found"), earlier turns not loaded ("Load earlier") |
| error | "That answer didn't come through" + Retry; the turn is not persisted as complete; quota returned |
| offline | transcript readable from the page; composer disabled with "Reconnect to continue"; no queued turns |
| auth-required | `303 /login?next=/app/personalized/{id}` |
| permission-denied | other user's session → 404 page (never 403 that confirms existence) |
| reduced-motion | artifacts start paused on a static frame; streaming text still appears |
| untranslated | check item not in the session language → English item + "This question is in English" note; teaching text stays in the chosen language |
| quota-exhausted | turn blocked before spend: "You've used today's turns. This session is saved." + resume tomorrow; in-progress turn finishes |
| consent-missing | n/a (no mic); voice consent is a lesson-dock concern |

### 7.3 `SCR-PL-03` artifact viewer

| State | What the student sees |
|---|---|
| default | ready artifact, title, controls, provenance |
| loading | skeleton + "building a visual…" (the teaching text is already readable) |
| empty | no artifact requested: nothing rendered (no empty card) |
| partial | failed build → text + static diagram fallback + one-line note |
| error | iframe load timeout → "The visual didn't load" + fallback + Reload |
| offline | cached artifact HTML may render; a new build is disabled with a reason |
| permission-denied | artifact id not referenced by this user → 404 |
| reduced-motion | paused static frame + Play |
| untranslated | title/fallback in the session language where available; else English + note |
| quota-exhausted | artifact budget spent → fallback + "Visuals are paused for today" |
| consent-missing | n/a |

### 7.4 `SCR-PL-04` settings section

| State | What the student sees |
|---|---|
| default | empty or saved text, counter, Save/Clear |
| loading | n/a (SSR) |
| empty | "No preferences yet — the default style is already good." |
| partial | auth down → the field is disabled with a reason (503 shell) |
| error | save failed → previous value stays, `role="alert"` retry |
| offline | unsaved changes stay on screen; "Not saved — reconnect" |
| auth-required | guest → `303 /login?next=/app/settings` |
| permission-denied | n/a — the field is the caller's own account; it is absent for guests |
| reduced-motion | n/a (no animation) |
| untranslated | English copy; the field's text is the student's own language |
| quota-exhausted | n/a (preferences are not metered) |
| consent-missing | n/a |

---

## 8. Failure modes and recovery

| # | Failure | Detection | Student sees | Recovery | Spend |
|---|---|---|---|---|---|
| PL-F1 | Model unavailable / 5xx | `llm_manager` typed error | "Zivon can't think right now" + Retry; transcript intact | retry turn; quota returned | none |
| PL-F2 | First teaching text > 10 s | stream first-event deadline | "Taking longer than usual…" then either text or honest failure | one retry with a shorter prompt; then error | one call |
| PL-F3 | Stream dies mid-sentence | inactivity timeout | partial text stays + "answer cut short" + Retry | retry the turn (idempotent) | partial call logged |
| PL-F4 | Decide call fails after text | JSON/validation error | teaching text stays; check card replaced by "Ask me to continue" | retry decide only | one call |
| PL-F5 | Artifact build fails | lint/render/deadline | text + diagram fallback + note | no silent retry after one attempt | build logged |
| PL-F6 | RAG index missing/stale | boot/load check | "Content index is unavailable" for new sessions; history works | operator rebuild; `E-CONTENT-UNAVAILABLE` | none |
| PL-F7 | Quota exhausted | pre-call counter | honest state + reset time | tomorrow or global reset | none |
| PL-F8 | DB write fails at turn end | transaction error | "Your answer was scored but not saved" + Retry save | idempotent save by `client_turn_id` | call already spent; logged |
| PL-F9 | Auth session expires mid-session | 401 | 303 to login with `next` back to the session | re-login; session resumes | none |
| PL-F10 | Artifact viewer crash (browser) | iframe `onerror`/timeout | fallback + Reload | reload once | none |

Every failure ends in a next action. No dead ends, no silent truncation, no
"something went wrong" without a path.

---

## 9. Notices and copy rules

Personalized learning is **not** an exam surface and does not reproduce any
CBSE paper. It still must not imply affiliation:

- Hub footer line (all sessions): "Practice questions are AI-generated in the
  board-exam style. They are not official CBSE questions."
- L4 board-style item meta: "Board-style practice · generated by Zivon".
- If a generated item is used, the check card carries "AI-generated practice"
  in its meta line.
- No "exact", "actual", "official", "approved", or "affiliated" wording
  (`DEC-COMP-002`).
- Citations show the real source: `NCERT Class 10 Science, Ch. 9, p. 148`
  (book + chapter + page), or the lesson page title. Unknown/missing citation →
  the ungrounded note, never a fabricated source.
- The privacy page (`/app/settings/privacy`) gains a row for personalized
  sessions: what is stored, 90-day retention, export, delete.

Copy keys live with the implementation (`INF-PL-*` in the PL4 PR); the strings
above are normative for tone and claims, not final microcopy.

---

## 10. Accessibility, performance, language

- WCAG 2.2 AA floor: keyboard everything, visible focus, 44–48 px targets,
  one `<h1>`, landmarks, `aria-live="polite"` for streamed text (first sentence
  + completion, not every token), `role="status"` for save/quota, shape+words
  for correct/incorrect, no colour-only meaning.
- Artifacts: canvas has `role="img"` + an `aria-label` or a `.sr-only`
  description; sliders are native inputs with labels; reduced motion starts
  paused; no keyboard trap inside the iframe (the iframe is focusable and
  Escape returns to the card).
- Performance: the session page is SSR + one small island; first-party JS ≤
  150 KB gzip soft budget; no long task > 200 ms on the interaction path; the
  artifact box is a whole number of rows and never causes layout shift.
- Language: teaching text follows the student's chosen language (EN / HI /
  Hinglish) with English physics terms; checks prefer the same language from the
  bank, fall back to English with a note; UI chrome is English at R1 and
  translated with the UI workstream. No silent mixing.

---

## 11. Out of scope / traceability

- No payments/plans (founder correction 2026-11-17).
- No voice in personalized sessions (R1), no parent/teacher view, no sharing,
  no search, no inferred profile, no tools/browsing, no verbatim CBSE items.
- Feature cards: [`feature-addendum.md`](feature-addendum.md) `PL-F1…F6`.
- Decisions: [`decisions.md`](decisions.md) `D-PL-01…11`.
- Tables/APIs: [`data-and-api.md`](data-and-api.md).
- Threats/tests: [`security-privacy.md`](security-privacy.md).
- Evals: [`evals.md`](evals.md) `EV-PL-001…005`.
- Work split: [`workstreams.md`](workstreams.md) `PL1…PL5`.
