# Practice hub, player, summary, and history (F5)

Status: implementation contract for the W4 F5 slice (landed 2026-11-17, branch
`feature/w4-f5-practice`, based on `main` @ `63ea560`). It describes code that
exists: `backend/practice/`, `backend/routes/practice.py`,
`web/practice_views.py`, `web/routes/practice.py`, the four practice templates,
`frontend/assets/practice.css`, and `frontend/assets/practice.js`.

Consumes: `docs/specs/frontend/web-shell.md` (route/guard/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base Field Notes only; no §10 lesson
device), `docs/content-factory/assessment.md` (the P2 pack contract),
`docs/backend/db-spec.md` §4.19 (`question_bank`, `practice_session`,
`practice_attempt`), REQUIREMENTS §9.4, §10.6–§10.8, §11.

Out of scope and owned elsewhere: speaking/explain-back (F6), tests/series (F7,
including the `/v1/practice/retry-mistakes` convenience endpoint listed in
REQUIREMENTS §9.4 — F5 creates retry sets through `POST /v1/practice/sessions`
with `mode=retry_mistakes`), SWOT (F8), admin (F10), the voice pipeline itself.

## 1. Routes and code paths

| Route | Surface | Code |
|---|---|---|
| `/app/practice` | SSR hub behind the F0C account guard; optional `?chapter=<id>` focus card | `web/routes/practice.py`, `web/templates/app/practice/hub.html` |
| `/app/practice/{session_id}` | SSR player, one question at a time | same router, `player.html` |
| `/app/practice/{session_id}/summary` | SSR score, accuracy, concepts, next actions | same router, `summary.html` |
| `/app/practice/history` | SSR session list | same router, `history.html` |
| `POST /app/practice/start` | HTML form → create a set → 303 player | same router |
| `POST /app/practice/{id}/answer` | HTML form → grade → 303 `?answered=<qid>` (the JavaScript-off Check path) | same router |
| `POST /app/practice/{id}/complete` | HTML form → close → 303 summary | same router |
| `POST /v1/practice/sessions` | JSON, 201 | `backend/routes/practice.py` |
| `GET /v1/practice/sessions/{id}` | JSON, 200 | same |
| `POST /v1/practice/sessions/{id}/answers` | JSON, 200 | same |
| `POST /v1/practice/sessions/{id}/complete` | JSON, 200 | same |
| `GET /v1/practice/history` | JSON, 200 | same |

The pages extend `base.html`, load `/assets/product.css`, `/assets/app.css`,
then `/assets/practice.css`; the player also loads `/assets/practice.js` with
`defer`. `web/nav.py` gains `Practice` between Dashboard and Progress. The pages
are `noindex`, `no-store`, and render no `zn-` lesson class and no
`zivon.css`.

Session creation and completion are **form posts** so the hub works without
JavaScript (no dead Start/Finish controls). The answer form is a real form too;
the island upgrades it to an inline check over the JSON endpoint. Both adapters
call the same `backend.practice` functions — there is no second selection or
grading path.

Auth is F0's `require_context`/`AuthService.verify_csrf`; the HTML forms use the
session-derived token through `csrf_field()`. The global `/v1/*` API family
rate limit applies (30 requests/min per IP hash by default): a 10-item drill is
a session POST, one GET, up to 10 answer POSTs, and a complete POST.

## 2. JSON contracts

### 2.1 `POST /v1/practice/sessions`

```json
{"mode": "chapter", "chapter_id": "class-9-describing-motion-around-us", "count": 10}
```

- `mode` ∈ `chapter | daily | weak_topic | retry_mistakes` (the DB enum).
- `chapter_id` is required for `chapter` and `weak_topic`, forbidden content-wise
  (ignored) for `daily`, and optional for `retry_mistakes` (accepted but not used
  by the UI).
- `count`: `chapter`/`weak_topic` 10–20 (default 10), `retry_mistakes` 1–10
  (default 10), `daily` rejects a count (fixed at 5).
- The **language is server-side**: the student's saved locale
  (`en-IN|hi-IN|hinglish`) maps to pack languages `en|hi|hi-Latn`. There is no
  client language field, so a caller cannot claim a language.
- Response `201`:

```json
{"schema_version": 1, "session": {
  "session_id": "…", "mode": "chapter", "chapter_id": "…",
  "question_ids": ["q-…-en", "…"], "question_count": 10,
  "config": {"language": "en", "requested_language": "en",
             "language_fallback": false},
  "score": null, "started_at": "…Z", "completed_at": null}}
```

Errors: `422 E-VALIDATION` (mode/chapter/count), `409 E-CONTENT-UNAVAILABLE`
(no servable bank for the chapter/class, no unresolved mistakes, no weak
concept), `401`/`403` for auth/CSRF.

### 2.2 `GET /v1/practice/sessions/{id}`

Returns session progress plus **the current question with the key withheld**:

```json
{"schema_version": 1,
 "session": {"…": "as above, without re-selection"},
 "question_count": 10, "answered_count": 1, "correct_count": 1,
 "index": 1,
 "question": {"question_id": "…", "chapter_id": "…", "concept_id": "…",
              "type": "mcq|numeric|assertion_reason", "difficulty": "easy",
              "marks": 1, "language": "en", "prompt": "…",
              "options": ["…"], "expected_time_ms": 47000,
              "answered": false, "feedback": null, "hint_available": false},
 "next_index": null, "complete_available": false, "completed": false,
 "questions_language": "en", "requested_language": "en",
 "language_fallback": false}
```

- The question shape is `Question.public()`. `answer`, `explanation`,
  `misconception`, and `source_ref` are **absent** until the student commits an
  answer.
- `index` is the first unanswered question, or the last question when all are
  answered (so the player can show its feedback and the Finish control).
- `?review` is not a query on the API; the HTML player passes
  `?answered=<question_id>` to the view builder, which renders that answered
  question (with feedback) instead of the next one.
- A completed session returns `question: null`, `completed: true`.
- `404 E-NOT-FOUND` for an unknown or another account's session (never a
  different student's row).

### 2.3 `POST /v1/practice/sessions/{id}/answers`

```json
{"question_id": "q-…-en", "answer": {"index": 2},
 "time_ms": 4200, "hints_used": 1}
```

- MCQ/assertion-reason answer: `{"index": n}`; numeric: `{"value": 15.0}`.
  The store grades from the key (`check_answer`); the route never accepts a
  `correct` flag.
- A malformed answer (missing, string where a number is required, an index out
  of range) is `422 E-VALIDATION`, **not** "wrong". A wrong key in the bank is
  `500 E-INTERNAL` (content fault).
- Response `200`:

```json
{"schema_version": 1,
 "attempt": {"attempt_id": "…", "question_id": "…", "answer": {"index": 2},
             "correct": false, "time_ms": 4200, "hints_used": 1,
             "attempt_no": 2, "created_at": "…Z"},
 "feedback": {"question_id": "…", "concept_id": "…", "correct": false,
              "answer": {"index": 0}, "explanation": "…",
              "misconception": "…", "unit": null},
 "answered_count": 1, "correct_count": 0, "question_count": 10,
 "next_index": 1, "complete_available": false}
```

- The attempt is append-only. A retry increments `attempt_no`; the set's
  accuracy uses the **latest** attempt, and the **first** attempt is what feeds
  F3's progress event (see §4).
- `409 E-CONFLICT` after the set is completed; `422` for a question outside the
  set; `404` for an unknown/foreign session.

### 2.4 `POST /v1/practice/sessions/{id}/complete`

Idempotent. Scores by latest-attempt question accuracy
(`round(100 · correct / answered, 2)`, `0.0` when nothing was answered) and
returns the full summary:

```json
{"schema_version": 1,
 "session": {"…": "score and completed_at set"},
 "summary": {"answered_count": 8, "question_count": 10, "unanswered_count": 2,
             "correct_count": 6, "accuracy_pct": 75.0, "score": 75.0,
             "first_attempt_answered": 8, "first_attempt_correct": 5,
             "first_attempt_accuracy_pct": 62.5,
             "time_ms": 312000, "hints_used": 3,
             "concepts": [{"concept_id": "…", "answered": 3, "correct": 2,
                           "accuracy_pct": 66.7}]}}
```

`time_ms` and `hints_used` are summed over **all** attempts (time actually
spent, including retries). Unanswered questions are counted as unanswered, not
wrong.

### 2.5 `GET /v1/practice/history`

`{"schema_version": 1, "items": [<session public shape>], "count": n}`, newest
first, bounded at 20 by the store. Owner-scoped.

## 3. Selection policy (`backend/practice/service.py`)

| Mode | Candidate set | Order | Default / bounds |
|---|---|---|---|
| `chapter` | servable `question_bank` rows for the chapter and served language | difficulty interleave easy → medium → hard, id-sorted inside a tier | 10 / 10–20 |
| `daily` | class-level rows, round-robin one per chapter a pass | store round-robin | 5 fixed |
| `weak_topic` | concepts whose **latest** attempt is wrong in that chapter | same interleave | 10 / 10–20 |
| `retry_mistakes` | questions whose **latest** attempt is wrong, newest first, deduplicated | newest miss first | 10 / 1–10 |

- A chapter with fewer than the requested count serves what it has; a chapter
  with zero servable rows is an honest `E-CONTENT-UNAVAILABLE`, never an empty
  session.
- "Missed" means unresolved: a question answered wrong once and later right does
  not return. Weak concepts are counted from those unresolved latest attempts.
- **Language:** the saved language first. If the bank has no rows in it, the set
  is served in English and the session config records
  `language_fallback: true` + `requested_language`; the hub, player, and summary
  say so. No silent fallback and no empty set.
- Selection is deterministic for the same bank. There is no shuffle, no
  adaptive difficulty, and no timer; those are not part of this slice.

## 4. Progress integration (F3)

On the **first** committed attempt for a question, `backend.practice` writes one
`practice_answer` `progress_event` with
`{correct, hints_used, time_ms}` and the question's chapter/concept ids. Retries
do not write (guess-until-right must not inflate accuracy). The write is
derivative: if it fails, a `practice.answer.progress_sync_failed` WARNING is
emitted and the answer response still succeeds — the committed attempt is the
primary record and is rebuildable.

The event payload is an allowlist with no answer text, key, prompt, or child
identity. This is what moves a chapter from **Learning** to **Practising** on
`/app/progress`.

## 5. Hints

The P2 pack has **no hint field**. The honest state is `hint_available: false`
and a "Need a nudge?" control that says *"No authored hint for this question
yet"* and offers a generic, non-answer-revealing study nudge (read what is given
and what is asked, then choose the relationship that connects them). Opening it
sets `hints_used = 1` on the next attempt, so the summary can say a hint was
used. No content is fabricated and no hint pretends to be authored.

## 6. "Ask the tutor" hand-off

After feedback the player/summary offers **"Ask the tutor on this chapter"**,
which links to the chapter's published lesson page (`catalogue.json` →
`lesson_url`). That page owns the real voice dock (F4/§10.12). When a chapter has
no published lesson, the copy says so and no dead link is rendered. Practice has
no second tutor pipeline, no fake chat, and no invented model call.

## 7. Pages

### Hub (`/app/practice`)

Page head; optional **From the lesson** focus card when `?chapter=` is present
(the F4 lesson-shell hand-off); **Daily 5** with its honest reason when it is
unavailable (no class set / no class bank); **Chapter drill** list of chapters
that actually have a bank (title from the catalogue, count, English-only marker
when relevant, Start form); **Weak topics** from unresolved misses; **Retry
mistakes** with its count; aside with **Recent sets** and **How this works**
(hints, retries, first-attempt progress, no timer, tutor hand-off, language).

### Player (`/app/practice/{id}`)

One question: `Question N of M`, native `<progress>`, question type/difficulty/
marks/expected time, the prompt as the fieldset legend, radios
(MCQ/assertion-reason) or a text input with `inputmode="decimal"` (numeric),
Check, "Need a nudge?", a polite `aria-live` feedback panel, the explanation in
an open "Why?" disclosure, the common mix-up, the tutor hand-off, Next question
or Finish set. A `?answered=<qid>` request renders the answered question's
feedback (the no-JS post-answer redirect). A completed set redirects to the
summary. An answered question can be retried before moving on; each retry is an
appended attempt.

### Summary (`/app/practice/{id}/summary`)

Score, answered/question count, accuracy (latest attempts), first-attempt
accuracy, time on task, hints, per-concept correct/total, unanswered note, then
Retry mistakes (when unresolved misses exist), next chapter (catalogue order),
back to the lesson/practice/history. Open sets say they are still open and offer
Continue. Tests are named as a future release, never linked as a dead control.

### History (`/app/practice/history`)

Newest-first list: mode, chapter title (or "Practice set"), day, question count,
score for finished sets or "still open", and the player/summary link.
Empty state points at the hub.

## 8. States

| State | Hub | Player | Summary | History |
|---|---|---|---|---|
| default | modes + recent | one question | score + concepts + next | session list |
| loading | n/a (SSR completes before bytes) | n/a | n/a | n/a |
| empty | no bank: honest "No chapter has an imported practice bank yet"; no start form | n/a (a session always has questions) | zero answered: "Nothing was answered in this set" | "No practice sets yet" |
| partial | Daily 5 unavailable reason; English-only chapter marker; no weak/retry yet | unanswered set, last question answered but set not closed | open set: "This set is still open"; unanswered count | open sets say "still open" |
| error | panel `notice--error` + retry, no invented modes | panel error + retry | panel error + retry | panel error + retry |
| offline | browser offline page (practice needs the server; no local pack in this slice) | same | same | same |
| permission-denied | guest → 303 `/login?next=` | same | same | same |
| reduced-motion | no animation; native controls | no animation; native progress | no animation | no animation |
| untranslated | English UI copy + saved-language note; question language is stated/fallback-marked | same | same | same |
| over-credit-budget | n/a — no voice control on practice | n/a | n/a | n/a |
| consent-missing | n/a — practice does not open the mic | n/a | n/a | n/a |

Failure-first details: a malformed numeric answer is `422` and the no-JS path
re-renders the same question with the entered value and "Enter a number like 15
or 0.5 before checking"; the island does the same inline. A stale CSRF token is a
branded `403` page. A closed set is `409` and the UI explains it. An unknown or
foreign session is a branded HTML `404`, never the JSON envelope.

## 9. Accessibility, mobile, privacy

- One `main`, one `h1` per page; every section `aria-labelledby`; native
  `<fieldset>/<legend>` for the options and `<progress>` for progress; feedback
  is `role="status" aria-live="polite"` and receives focus after an inline
  check; the answer error is `role="alert"`.
- Keyboard only: radios select with Space; Check and Next are native buttons or
  links; the hint disclosure is a native button with `aria-expanded`; no drag, no
  custom widgets, no autoplay.
- 360 px: the hub grid stacks to one column, chapter/weak/history rows stack,
  options and numeric input are full width, every button is ≥ 44 px, inputs are
  48 px. `testing/frontend/test_practice_layout.py` asserts no horizontal
  overflow and a clean console.
- Meaning is never colour alone: the feedback says "Correct." / "Not quite."
  and names the chosen and correct answers; the correct/incorrect border colour
  is reinforcement only.
- No email, user id, session id, cookie, or raw answer key in HTML before a
  commit. The API never returns `user_id`. Answers are stored as committed data
  (`practice_attempt`) and are not free text. There is no public profile, share
  link, leaderboard, or parent view. Account deletion cascades through the
  `users` foreign keys (F0 tables).
- No inline script/style/handlers; the island reads the CSRF meta token, talks
  only to same-origin `/v1/practice/*`, and builds feedback with DOM nodes and
  `textContent` (no `innerHTML`).

## 10. Logging

| Event | When | Fields (no content) |
|---|---|---|
| `practice.session.created` | set created (JSON or HTML) | `mode`, `question_count`, `chapter_id`, `language`, `language_fallback` |
| `practice.answer.recorded` | answer committed | `correct`, `attempt_no`, `time_ms`, `hints_used`, `answered_count`, `question_count` |
| `practice.session.completed` | set closed | `answered`, `question_count`, `unanswered`, `score` |
| `practice.answer.progress_sync_failed` | F3 event write failed | `reason_code` (`store_error`) |

All four resolve to rows in
`docs/specs/observability/instrumentation-map.csv` (component `practice`,
privacy `L2`, `request_id` correlation). The answer value, key, explanation,
prompt, and child identity never enter `fields`.

## 11. Tests

| Suite | Command | Covers |
|---|---|---|
| API | `python -m unittest discover -s testing/backend -t .` (`test_practice_api.py`) | auth/CSRF, validation bounds, empty-bank 409, creation, **answer withholding**, MCQ/numeric/assertion-reason grading, numeric parse errors, retries + first-attempt progress, complete/summary/idempotency/history, tenant isolation, Daily 5/weak/retry selection, language fallback, no PII/answer text in logs or responses |
| Pages | `testing/backend/test_practice_pages.py` | guest 303, nav entry, hub modes/empty states, focus card, one-question player with no key, no-JS Check path, numeric parse re-render, CSRF 403, completed redirect, summary/history, branded 404, no §10 device/inline code |
| Layout + island | `testing/frontend/test_practice_layout.py` | 360 px overflow, stacked grid, touch targets, keyboard radios, live region, feedback/next state, summary layout, the island's same-origin CSRF answer call (stubbed) |

All key-free, offline, deterministic; no model or voice call exists on this path.

## 12. Known debt / next

- **Stale cross-workstream copy.** F3's dashboard still says "five practice
  questions … not live yet" and F4's lesson end-CTA still shows Practice as
  "coming soon"; both are their owners' templates. The `Practice` nav entry and
  `/app/practice` are live now, so those two copy blocks are the next small
  follow-up (F3/F4), not an F5 edit.
- **Concept vocabulary.** The P2 import writes `question_bank` but not
  `syllabus_chapter`/`concept`; practice concept ids are semantic slugs while the
  published catalogue uses `…-sec-NN`. The summary therefore humanizes the
  concept id (a derived, honest label) instead of inventing a title, and no
  practice link deep-links a specific lesson section. Reconciling the vocabularies
  is P1/P2/P5 debt already recorded in `dashboard-progress.md`.
- **Chapter titles for un-catalogued chapters** (e.g. Class 10 Light until P5
  publishes it) fall back to the humanized chapter id; the same rule applies.
- **Hints** remain unavailable until the assessment pack grows an authored hint
  field and a gate for it.
- **No local/offline practice pack.** The player needs the server; offline is the
  browser's page. The REQUIREMENTS offline note ("practice itself works offline
  once loaded") is not met by this slice and is not claimed in the UI.
- **No timer, no adaptive order, no per-question randomisation.** Deliberate:
  deterministic selection is testable, and a timer is a test-mode feature (F7).
- **Rate limit.** A full 20-item drill is ~23 API requests; the 30/min per-IP
  family limit could bite a very fast tapper behind a shared IP. It is env-
  configurable (`rate_limit_api_per_min`) and not a product limit; watch it in
  the demo window.
- **Scoring semantics** are per-question latest-attempt accuracy. F7 (tests) may
  need marks/negative marking; that policy stays F7's and must not be added here.
