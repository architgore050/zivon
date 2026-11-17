# Tests, the exam-paper player, and the six series (F7)

Status: implementation contract for the W4 F7 slice (landed 2026-11-17, branch
`feature/w4-f7-tests`, based on `main` @ `811e775`). It describes code that
exists: `backend/test_engine/`, `backend/routes/tests.py`, `web/test_views.py`,
`web/routes/tests.py`, the seven test templates, `frontend/assets/tests.css`,
and `frontend/assets/tests.js`.

Consumes: `docs/specs/frontend/web-shell.md` (route/guard/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base Field Notes only; no §10 lesson
device), `docs/backend/db-spec.md` §4.19 (`test_series`, `test`,
`test_question`, `test_attempt`, `test_attempt_answer`, `question_bank`),
`docs/content-factory/exam.md` (P3 series definitions and the volume gate),
`docs/compliance/` (`DEC-COMP-001`, notice `N-01`), REQUIREMENTS §9.6,
§10.11–§10.16, §12.

Out of scope and owned elsewhere: the P3 series pack import (P3/admin), the
question bank and its provenance (`question_bank`), practice (F5), speaking
(F6), SWOT (F8), admin (F10), the voice pipeline itself.

## 1. Routes and code paths

| Route | Surface | Code |
|---|---|---|
| `/app/tests` | SSR hub: chapter tests, presets, series shortcuts, recent attempts | `web/routes/tests.py`, `web/test_views.py`, `app/tests/hub.html` |
| `/app/tests/new` | SSR builder; prefilled by `?count=&minutes=&chapter=` | `app/tests/new.html` |
| `POST /app/tests/start` | HTML form → create a custom/chapter/retry paper and start it → 303 player | same router |
| `/app/tests/history` | SSR history with `?status=&kind=` filters | `app/tests/history.html` |
| `/app/tests/{attempt_id}` | SSR exam-paper player; `?q=<question_id>` selects a palette entry | `app/tests/player.html` |
| `POST /app/tests/{attempt_id}/answer` | HTML form → save answer / mark for review → 303 player | same router |
| `GET /app/tests/{attempt_id}/submit` | SSR submit confirmation | `app/tests/submit.html` |
| `POST /app/tests/{attempt_id}/submit` | Grade once → 303 review | same router |
| `/app/tests/{attempt_id}/review` | SSR graded review | `app/tests/review.html` |
| `/app/series` | SSR six-series catalogue | `app/tests/series.html` |
| `/app/series/{slug}` | SSR series detail and papers | `app/tests/series_detail.html` |
| `POST /app/series/{slug}/start` | Start/resume a paper that belongs to that series | same router |
| `GET /v1/series` | JSON catalogue | `backend/routes/tests.py` |
| `GET /v1/series/{slug}` | JSON series detail | same |
| `POST /v1/tests/custom` | JSON builder, 201 | same |
| `POST /v1/tests/chapter` | JSON chapter test, 201 | same |
| `POST /v1/tests/retry` | JSON retry paper, 201 | same |
| `POST /v1/tests/{test_id}/attempts` | Start/resume, 201 | same |
| `GET /v1/tests/attempts/{attempt_id}` | player state, key withheld | same |
| `PATCH /v1/tests/attempts/{attempt_id}/answers` | autosave one answer/flag | same |
| `POST /v1/tests/attempts/{attempt_id}/submit` | grade + review | same |
| `GET /v1/tests/attempts/{attempt_id}/review` | review, 409 before submit | same |
| `GET /v1/tests/history` | history with filters | same |

The pages extend `base.html`, load `/assets/product.css`, `/assets/app.css`,
then `/assets/tests.css`; the player also loads `/assets/tests.js` with `defer`.
`web/nav.py` gains `Tests` between Dashboard and Progress. Every page is
`noindex`, `no-store`, and renders no `zn-` lesson class and no `zivon.css`.

Auth is F0's guard (`require_account` on GET, `resolve_auth_session` on POST)
and `AuthService.verify_csrf`; the JSON API keeps its `X-CSRF-Token` header
contract. The global `/v1/*` rate-limit family applies. There is no second
grading or session path.

## 2. Test creation

### 2.1 Builder (`POST /v1/tests/custom`, `/app/tests/new`)

| Field | Bounds | Default |
|---|---|---|
| `chapter_ids` | 1–4 chapter ids, each ≤ 120 chars, no `/` | required |
| `count` | 5–30 | 10 |
| `difficulty` | `mixed \| easy \| medium \| hard` | `mixed` |
| `duration_s` | 300–3600 | `max(300, questions × 90)` |

- A custom test is a `test` row owned by the student (`user_id`, `series_id`
  NULL, `status='draft'`), plus one `test_question` row per question in a single
  transaction (`create_test_with_questions`). It is not a published series
  paper.
- Selection is **deterministic for the same bank**: per chapter, eligible
  questions are ordered easy → medium → hard (id-sorted inside a tier), then
  round-robin across the chosen chapters so one chapter cannot fill the paper.
  Only `reviewed`/`published` rows serve.
- The paper keeps what exists. A chapter with a thin bank yields fewer questions
  than asked; fewer than three servable questions is the honest
  `E-CONTENT-UNAVAILABLE` ("not enough imported questions"), never a one-item
  test. The builder states this.
- The **language is server-side**: the student's saved locale maps to a pack
  language (`en|hi|hi-Latn`). If the requested language has fewer than three
  servable rows, the paper is drawn in English and `structure` records
  `language_fallback: true` + `requested_language`; the page says so. No mixed-
  language paper.
- Titles are generated server-side ("Custom test", "Chapter test", "Retry
  mistakes"); there is no student free-text field. The paper's `structure`
  records `source`, `difficulty`, `question_count`, `chapters`,
  `requested_language`, `language_fallback`.

### 2.2 Chapter test (`POST /v1/tests/chapter`, hub form)

Derived from one chapter's bank with `mixed` difficulty, up to 10 questions,
duration `max(300, questions × 90)`. A chapter with no bank never shows a Start
form in the hub.

### 2.3 Retry mistakes (`POST /v1/tests/retry`, review/history form)

- Draws questions whose **latest submitted answer** is wrong, newest miss first,
  deduplicated, at most 10, scoped to the student's class and language (English
  fallback when the requested language has no rows).
- A wrong answer that was later answered right does not return. Autosaved but
  unsubmitted answers never count.
- No unresolved misses is `E-CONTENT-UNAVAILABLE`; the page says "No unresolved
  test mistake yet", never a dead button.

### 2.4 Language and compliance filter

- Every selected question must have `source_type = 'generated'`. Rows with
  `past_paper` / `sample_paper` / `curated_pyq` are excluded at selection, and
  an attempt that somehow contains one refuses to open
  (`E-TEST-CONTENT-MODE`, HTML 409 with the reason). A published paper under a
  draft/retired series is not startable, and the verbatim Exact PYQ series
  stays dark even if a row was published by mistake. This is the runtime
  belt-and-braces for `DEC-COMP-001`; the import gate is still the primary
  control.

## 3. Player, clock, autosave, submit

### 3.1 Attempt lifecycle

- `POST /v1/tests/{test_id}/attempts` starts a paper or resumes the student's
  one live attempt on it. The DB's partial unique index
  (`test_attempt(test_id, user_id) WHERE status='in_progress'`) owns the
  guarantee; a double-start returns the same `attempt_id` (`resumed: true`).
- `test_attempt.status` ∈ `in_progress | submitted | expired | abandoned`. The
  product uses `in_progress` and `submitted`; the other two are schema states
  without a route.

### 3.2 Clock

- The deadline is **server-derived**: `started_at + test.duration_s`. The page
  renders the ISO deadline and the remaining seconds; `tests.js` only displays
  it. A reload, a second tab, or a stopped browser timer cannot extend it.
- An expired attempt refuses autosave (`409 E-CONFLICT`, internal code
  `E-TEST-EXPIRED`) and the player renders the submit-only state.
- A late submit is still graded and records the real `time_spent_s`; the paper
  is never silently discarded. With JavaScript on, the timer submits at zero;
  with JavaScript off, the student submits from the "Time is up" panel.

### 3.3 Autosave and mark-for-review

- `PATCH /v1/tests/attempts/{id}/answers` upserts one answer or flag. The store
  never writes `correct`/`marks_awarded` here; a flag-only save keeps an
  existing answer.
- The HTML form is the real path (Save answer / Mark for review buttons,
  followed by a 303 back to `?q=<question_id>`). `tests.js` enhances it:
  radio change, numeric input (900 ms debounce), and flag change issue the same
  PATCH with the session CSRF token; the `aria-live="polite"` save line says
  "Saving…", "Saved", or "Not saved — press Save answer". A failure is never
  hidden.
- The palette shows every question with an explicit state (Answered,
  Answered + marked, Marked for review, Not answered) and a text legend; the
  current item carries `aria-current="true"`. No status is colour-only.
- The numeric field uses `inputmode="decimal"`; a malformed value is a fixable
  re-render, not a wrong answer.

### 3.4 Submit

- `GET /app/tests/{id}/submit` is the confirmation: answered / unanswered /
  marked counts, the unanswered question numbers, and the time left. It reads
  no key.
- `POST /app/tests/{id}/submit` grades once (`submit_test_attempt`) and returns
  303 to the review. A second submit returns the stored result; the route is
  idempotent.
- Grading is **server-side from `question_bank`**: MCQ/assertion-reason by
  option index, numeric by value within the authored tolerance. A correct
  answer earns the paper's marks; a wrong or missing answer earns zero. There
  is no negative marking. The score is
  `round(100 × earned / possible, 2)`.
- On submit, one `test_submit` progress event per chapter feeds F3's recent
  activity/progress map (counts and score only; no answer text). A failed rollup
  logs `test.attempt.progress_sync_failed` and never un-submits the paper.

## 4. Review

- Withheld before submit: the API returns `409 E-CONFLICT`, the HTML review
  redirects to the player. The key enters the response only after the attempt is
  `submitted`.
- The review shows: score %, marks earned/possible, accuracy, answered right/
  wrong, unanswered, marked, time; a concept breakdown and a chapter breakdown
  (answered / total / accuracy); every question with the student's answer, the
  key, the explanation, the misconception, the source note, and an honest
  "Ask the tutor on this chapter" link when the lesson is published (else the
  reason it cannot open).
- Every question is labelled Correct / Incorrect / Not answered in words plus a
  marker shape. A missing explanation is a visible content gap, not a silent
  blank.
- The page offers Retry mistakes (every question whose latest answer was wrong)
  and links back to the hub, history, and practice.

## 5. History

`GET /app/tests/history` and `GET /v1/tests/history` list the owner's attempts,
newest first, bounded at 50. Filters: status (`in_progress`, `submitted`) and
kind (`chapter`, `custom`, `series`, `retry`); an unknown filter value is
ignored, never a 500. An in-progress row resumes; a submitted row opens the
review with its score. The page also offers Retry mistakes when unresolved
misses exist.

## 6. The six series

### 6.1 Catalogue and truthfulness

The definitions mirror `factory/series/__init__.py` (P3's build-time source of
truth) in `backend/test_engine/series.py`, because the backend image does not
ship `factory/`. `testing/backend/test_web_tests.py` asserts label, purpose,
language policy, notice id, and approved minimum stay identical to
`factory.series`.

| Slug | Kind | Purpose | Languages | Notice |
|---|---|---|---|---|
| `ai-lesson` | `ai_lesson` | Chapter tests / mixed practice from lesson concepts | EN + HI + Hinglish | N-01 |
| `pyq-pattern` | `pyq_pattern` | Recurring paper shapes, close to the pattern | EN + HI | N-01 |
| `exact-pyq` | `exact_pyq` | Curated past-year items with attribution | EN + HI | N-03 (dark) |
| `board-practice` | `board_practice` | Full-paper rehearsal | EN + HI | N-01 |
| `challenge` | `challenge` | Harder short sets | EN + HI + Hinglish | N-01 |
| `loop` | `loop` | High-frequency pattern drills | EN + HI + Hinglish | N-01 |

The URL slug is the catalogue slug; a DB row is matched by `kind`, so a
pack's own slug cannot create a second catalogue entry. One published
`test_series` row per kind is the P3 pack shape.

Status is derived, never asserted:

- `live` — a published `test_series` row for the student's class and at least
  one published `test` in it; papers list with Start/Resume.
- `pending` — no published row, or a published row with no papers. The page
  says "content pending" and names the approved minimum from
  `factory.series.MINIMUM_VOLUME` (e.g. "questions per chapter 20, chapter tests
  per chapter 1, mixed tests 2"). It shows no fake paper.
- `disabled` — `exact_pyq` under `DEC-COMP-001` until a clearance record exists.
  The page says the series is dark and why; no past-paper text is rendered.
- `not_open` — class 9/11 (the approved series volume is Class 10 and 12);
  chapter and custom tests still work.
- `choose_class` — the student's class is not set; the page points to Settings.

`/app/series` is one page and renders **one** N-01 notice; each detail page
renders its own N-01 at the end of the intro and again in the footer band, per
`docs/compliance/notices.md` "Rendering rules". The resolved English text is
`n01_notice(class_num)`; a test extracts the N-01 block from the compliance doc
and compares byte-for-byte. Hindi notice copy waits for the UI-translation
workstream (the rest of the shell is English-only; known debt below).

### 6.2 Copy rules

- Generated exam-pattern series use the approved blurbs: "Built to the CBSE
  Class N … paper pattern. Close to the paper pattern and built for practice;
  not an official CBSE paper." Never "PYQ", "previous year", "official", "exact
  CBSE".
- The Exact PYQ series has no blueprint-mode blurb; showing a past-paper claim
  while the series is dark would be false.
- The player and review for a series paper carry the same N-01 notice; a custom
  or chapter test carries none (it is lesson practice, not exam-pattern paper).

### 6.3 Starting a series paper

`POST /app/series/{slug}/start` checks that the `test_id` belongs to the series
named in the URL (`series_id` → `test_series.kind` matches the slug). A custom
test or another series' paper is "That paper is not here", never started under
the wrong label.

## 7. JSON contracts (shapes)

All responses are JSON, UTC ISO timestamps, `Cache-Control: no-store`. The
error envelope is the backend's existing `{code, message_key, trace_id,
retryable}`.

### 7.1 `POST /v1/tests/custom` → 201

```json
{"schema_version": 1, "test": {
  "test_id": "…", "series_id": null, "title": "Custom test",
  "chapter_ids": ["class-9-describing-motion-around-us"],
  "language": "en", "duration_s": 450, "total_marks": 5.0,
  "structure": {"source": "custom", "difficulty": "mixed",
                "question_count": 5, "chapters": 1,
                "requested_language": "en", "language_fallback": false},
  "status": "draft"}}
```

Errors: `422 E-VALIDATION` (count/duration/difficulty/chapters), `409
E-CONTENT-UNAVAILABLE` (fewer than three questions), `401`/`403`.

### 7.2 `POST /v1/tests/{test_id}/attempts` → 201

```json
{"schema_version": 1, "attempt": {"attempt_id": "…", "test_id": "…",
  "status": "in_progress", "score": null, "time_spent_s": null,
  "started_at": "…Z", "submitted_at": null},
 "test": {"…": "as above"}, "resumed": true}
```

### 7.3 `GET /v1/tests/attempts/{id}`

Returns `attempt`, `test`, `questions` (`Question.public()` rows: no `answer`,
`explanation`, `misconception`, `source_ref`; `source_type` is provenance, not
the key, and is used by the runtime `DEC-COMP-001` guard), `answers` keyed by question id
(saved answer/flag only), `index`, `question`, `counts`
(`question_count/answered/unanswered/correct/flagged`), `deadline`,
`remaining_s`, `expired`, `submitted`, `language`, `structure`, `series`.

### 7.4 `PATCH /v1/tests/attempts/{id}/answers`

```json
{"question_id": "q-…-en", "answer": {"index": 2}, "flagged": true,
 "time_ms": 4200}
```

`answer` is `{"index": n}` for MCQ/assertion-reason, `{"value": x}` for numeric,
or omitted for a flag-only save. The response is
`{"saved": {…}, "counts": {…}, "remaining_s": n}`. Errors: `422` malformed
answer, `409` closed/expired, `404` unknown/foreign attempt.

### 7.5 `POST …/submit` and `GET …/review`

`{"schema_version": 1, "review": {"state": "review", "attempt", "test",
"questions": [<question.review() + chosen/correct/marks/time>],
"counts", "summary": {"score", "earned", "possible", "accuracy_pct",
"answered", "unanswered", "correct", "flagged", "time_spent_s",
"answer_time_ms", "missed"}, "concepts", "chapters", "missed_question_ids",
"language", "series"}}`.

### 7.6 `GET /v1/tests/history`

`{"schema_version": 1, "items": [<attempt + title/kind/labels/score>],
"count", "status_filter", "kind_filter", "retry", "filters"}`.

### 7.7 `GET /v1/series` and `GET /v1/series/{slug}`

Catalogue: `{"class_level", "cards": [{"kind","slug","label","purpose",
"blurb","coverage","length","languages","language_label","notice_id",
"status","status_label","reason","paper_count","approved","minimum"}],
"chapter_count","notice","status_counts"}`. Detail adds the same definition,
`papers` (test_id, title, question_count, marks, duration, live attempt,
recommended), `language_note`, and the compliance `notice`.

## 8. Nav and event map

| Nav | Entry | Placement |
|---|---|---|
| App header / mobile menu | `Tests` → `/app/tests` | between Dashboard and Progress |

| Event | Where | Fields (no free text) |
|---|---|---|
| `test.session.created` | builder (custom/chapter/retry) | `source`, `question_count`, `chapters`, `language`, `language_fallback` |
| `test.attempt.started` | start/resume | `resumed`, `question_count` |
| `test.answer.saved` | autosave | `flagged`, `answered`, `question_count` |
| `test.attempt.submitted` | submit (service) | `question_count`, `answered`, `score`, `expired` |
| `test.attempt.progress_sync_failed` | submit rollup | `reason_code`; error class `store_error` |

Frontend analytics names from REQUIREMENTS §11 (`test_start`, `test_answer`,
`test_flag`, `test_submit`, `test_review`, `series_view`) are the browser event
catalogue; the server events above are the structured-log contract. They are
not duplicated as free-text fields.

## 9. States

The screen-state matrix rows live in
[`state-matrix.md`](state-matrix.md) (APP-14…APP-19). Summary:

| Screen | Empty | Partial | Error | Offline |
|---|---|---|---|---|
| hub | no imported bank → honest copy, no Start | thin bank (fewer than asked), language fallback | panel `notice--error` + retry | browser offline page (tests need the server) |
| builder | no chapters → "not enough imported questions" | selected chapter has fewer rows than asked | validation re-render with picks kept | browser offline page |
| player | n/a: a paper always has questions | unanswered/marked palette; expired state | 404 branded page / 503 panel; save failures announced | browser offline page; unsaved changes are not claimed saved |
| review | n/a | missing explanation labelled; not-submitted redirects | 404/503 page | browser offline page |
| history | no attempts for filter → clear filters | in-progress rows labelled | panel error | browser offline page |
| series | no papers → content pending | some series live, some pending/disabled | panel error | browser offline page |

Additional states: permission-denied is F0's 303 to `/login?next=`; reduced
motion has no animation (the timer is text); untranslated is English copy plus
the shell's saved-language note; quota is n/a (no voice control on these pages);
consent-missing is n/a.

## 10. Accessibility and performance

- Exam-paper player: one `fieldset`/`legend` per question, native radios or a
  labelled numeric input, 48 px option/control targets, palette links with
  visible state words + `aria-current`, `role="timer"` with `aria-live="off"`
  and a separate polite announcement region for the 10/5/1-minute marks.
- Submit confirmation and review: text labels plus marker shapes for
  correct/incorrect/unanswered (never colour alone), `<caption>` on the
  breakdown tables, native `<details>` for each question, 'Ask the tutor' is a
  normal link.
- 360 px: the hub/player/review grids stack to one column; the palette wraps;
  no horizontal overflow (asserted in `testing/frontend/test_tests_layout.py`).
- Performance: no framework, one small same-origin island (`tests.js`), no
  animation beyond the clock text, no external host. The island issues at most
  one PATCH per answer change (numeric debounced 900 ms). The JS is a few KB and
  is not on any lesson page.
- No JavaScript: creation, save, mark, submit, review, history, and series all
  work; the timer shows the server-rendered remaining time and stops updating.

## 11. Security and privacy

- Every learner read/write is owner-scoped in the store; a foreign attempt id is
  a 404 page / `404 E-NOT-FOUND`, never another student's row.
- Every write needs the session CSRF token (`X-CSRF-Token` or the hidden form
  field). A stale form is a branded 403, nothing written.
- Every HTML redirect is same-origin checked: `_redirect` refuses a scheme or
  host and only emits an `/app/...` path, so a crafted id can never turn a
  success redirect into an off-origin one.
- The answer key, explanation, misconception, and source ref never enter the
  player payload or HTML before submit. The review is the only post-submit
  shape, and only for the owner.
- Telemetry contains ids, counts, scores, and enum values; no prompt, option,
  chosen answer, explanation, email, or display name. Tests scan the new
  surface for secret-shaped strings.
- No free-text input exists on any test page (titles are server-generated), so
  the child cannot put personal text into the test surface.

## 12. Tests

```bash
python3 -m unittest testing.backend.test_web_tests -t .        # 43 tests
python3 -m unittest testing.frontend.test_tests_layout -t .    # 8 browser tests
python3 -m unittest discover -s testing/backend -t .           # full backend suite
python3 -m unittest discover -s testing/frontend -t .          # full frontend suite
```

`testing/backend/test_web_tests.py` covers the guard, CSRF, builder bounds and
selection, answer-key withholding, the contaminated-attempt refusal (player,
submit, and review), autosave/resume, the clock, grading with no negative
marking, idempotent submit, flag-only rows, review, history filters, retry, the
graded `test_submit` progress rollup, cross-account isolation, the series
catalogue/pending/dark states (including a dark detail that lists no papers),
the series-start ownership check, the pipeline parity check, the compliance
notice text (intro + footer placement on a detail page), empty states, the
Field Notes/no-inline contract, the a11y markup, and the no-secrets scan.
`testing/frontend/test_tests_layout.py` renders the real pages at 360 px and
exercises the autosave island against a stubbed same-origin endpoint (including
the "not saved" state) and the clock's threshold announcements in words.

## 13. Known debt

- **No P3 pack importer for series.** The six-series catalogue reads published
  `test_series`/`test` rows; P3's pack (`runs/exam/.../E4-publish/pack/`) has no
  DB import yet. Until it lands, the series pages are honest "content pending"
  for every class, which is exactly what the current gate verdict says. The F7
  player already serves any published row an operator imports.
- **Class 9/11 series.** The approved volume covers Class 10/12; the catalogue
  says "opens for Class 10 and 12" for 9/11. Chapter/custom tests work for all
  four classes.
- **Hindi notice copy.** `N-01`/`N-03` Hindi text is approved in
  `docs/compliance/notices.md`, but the shell UI is English-only until the
  UI-translation workstream; the page renders the approved English notice. This
  is the same posture as every other shell page.
- **No series progress event.** Series tests feed F3 through the same
  `test_submit` event as custom tests; there is no series-specific rollup.
- **Sections.** The paper model carries `test_question.section`, and the player
  renders it; the P3 importer (when it lands) must populate sections. Custom
  tests have no section.
