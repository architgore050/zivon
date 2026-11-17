# Dashboard, progress map, and saved sections (F3)

Status: implementation contract for the W3 F3 slice (landed 2026-11-17, branch
`feature/w3-f3-dashboard-progress`, based on `main` @ `d65b658`). It describes
code that exists: `backend/progress/`, `backend/routes/progress.py`,
`web/progress_views.py`, `web/routes/{app,progress}.py`, the three app
templates, `frontend/assets/app.css`, and `frontend/assets/app-progress.js`.

Consumes: `docs/specs/frontend/web-shell.md` (route/guard/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base Field Notes only; no §10 lesson
device), `docs/backend/db-spec.md` §4.18 (`lesson_progress`, `progress_event`,
`bookmark`), REQUIREMENTS §9.3/§9.7, §10.5/§10.17/§10.20, §11, §13.

Out of scope and owned elsewhere: practice (F5), speaking/explain-back (F6),
tests/series (F7), SWOT (F8), identity/settings (F2), admin (F10). The
dashboard links only to live routes and labels the rest “not live yet”.

## 1. Routes and code paths

| Route | Surface | Code |
|---|---|---|
| `/app` | SSR dashboard behind the F0C account guard | `web/routes/app.py`, `web/templates/app/dashboard.html` |
| `/app/progress` | SSR class → chapter → concept map | `web/routes/progress.py`, `web/templates/app/progress.html` |
| `/app/bookmarks` | SSR saved sections | `web/routes/progress.py`, `web/templates/app/bookmarks.html` |
| `/v1/progress/events` | JSON, POST batch | `backend/routes/progress.py` |
| `/v1/progress/summary` | JSON, GET | same |
| `/v1/progress/chapters/{id}` | JSON, GET | same |
| `/v1/bookmarks` | JSON, GET/POST/DELETE | same |

The pages extend `base.html`, load `/assets/product.css`, then
`/assets/app.css`, and load `/assets/app-progress.js` with `defer`. The nav
gains `Progress` in `web/nav.py`; `Bookmarks` stays reachable from the
dashboard/progress quick links rather than adding a fourth top-level entry.
The pages are `noindex`, `no-store`, and render no `zn-` lesson class.

## 2. JSON contracts

### 2.1 `POST /v1/progress/events`

Authenticated (F0 cookie) and CSRF-protected (`X-CSRF-Token`), same-origin.
Body:

```json
{"events": [{
  "kind": "lesson_block_view",
  "chapter_id": "class-9-describing-motion-around-us",
  "concept_id": "class-9-describing-motion-around-us-sec-01",
  "question_id": null,
  "payload": {"section_id": "sec-01", "blocks_seen": 2, "blocks_total": 9,
              "max_scroll_pct": 40, "source": "merge"},
  "occurred_at": "2026-11-17T06:00:00Z"
}]}
```

- Batch maximum **40** events (`413`/`422` envelope for more; the envelope is
  validated by Pydantic with `extra="forbid"`).
- `kind` is one of **five client kinds**:
  `lesson_block_view`, `lesson_complete`, `practice_answer`, `test_submit`,
  `speaking_attempt`. `bookmark_add` / `bookmark_remove` are written only by
  the bookmark endpoints, never accepted from this route.
- Validation is **per item**: a malformed event is reported in `rejected`
  (`{"index": i, "code": "E-EVT-SCHEMA"}`) and the rest of the batch is
  written atomically. A malformed envelope is a `422` with the standard
  `E-VALIDATION` error.
- `occurred_at` is optional. A sane past ISO timestamp is stored as the
  event's `created_at` (this keeps a device-merge honest about *when* the
  reading happened); a future timestamp is clamped to server receipt time; an
  unparseable/absent value uses server receipt time.

Payloads are an **allowlist**, not free-form JSON. No key outside the kind's
set is accepted; strings are accepted only for ids and the `source` enum, so
no free text can be stored.

| Kind | Allowed payload keys | Types / bounds |
|---|---|---|
| `lesson_block_view` | `section_id`, `blocks_seen`, `blocks_total`, `max_scroll_pct`, `source` | section id `[a-z0-9][a-z0-9-]{0,39}`; counts 0–10 000; pct 0–100; source `lesson_shell`\|`merge` |
| `lesson_complete` | `sections_seen`, `sections_total`, `max_scroll_pct`, `source` | same bounds |
| `practice_answer` | `correct`, `hints_used`, `time_ms`, `source` | bool; 0–20; 0–3 600 000 |
| `test_submit` | `correct`, `answered`, `total`, `score`, `source` | ints 0–1000; score 0–100 |
| `speaking_attempt` | `score`, `source` | 0–100 |

`chapter_id` matches `^[a-z0-9][a-z0-9/_-]{0,119}$` (the `/` form exists for
the F4 local key `course/topic`); concept/question ids match
`^[a-zA-Z0-9][a-zA-Z0-9._:-]{0,119}$`. Response:
`{"accepted": n, "rejected": [{"index": i, "code": "E-EVT-SCHEMA"}]}`.

Writing a lesson event upserts `lesson_progress` for that chapter:
`blocks_seen` is the **maximum** absolute value the client reported (a stale
merge cannot lower it), `blocks_total` the latest positive total, completion
is monotonic, and `updated_at` is the latest event time. Both kinds feed the
same “sections read” counter the UI renders: `lesson_block_view` reports it as
`blocks_seen`/`blocks_total`, `lesson_complete` as `sections_seen`/
`sections_total`, so a client that only reports completion still records how
far the student got.

### 2.2 `GET /v1/progress/summary`

```json
{
  "schema_version": 1, "rules_version": 1, "generated_at": "…Z",
  "is_new": false,
  "weekly": {"goal_days": 4, "days_active": 3, "today_active": true,
             "days": [{"date": "2026-11-11", "weekday": "Wed", "initial": "W",
                        "active": false, "is_today": false}]},
  "counts": {"chapters_started": 2, "chapters_completed": 1,
             "practice_answers_7d": 12, "active_days_7d": 3, "bookmarks": 2},
  "continue": {"chapter_id": "...", "title": "...", "lesson_url": "/courses/...",
               "class_level": 9, "sections_seen": 4, "sections_total": 9,
               "last_activity_at": "…Z"},
  "classes": [{"class_level": 9, "chapters": [{
      "chapter_id": "...", "title": "...", "chapter_no": 4,
      "lesson_url": "/courses/...", "status": "lesson_only",
      "state": "learning", "state_label": "Learning",
      "blocks_seen": 4, "blocks_total": 9,
      "evidence": {"events": 4, "sections_seen": 4, "practice_answers": 0,
                   "practice_correct": 0, "accuracy_pct": null,
                   "concepts_touched": 2, "last_activity_at": "…Z"}}]}],
  "recent": [{"kind": "lesson_block_view", "chapter_id": "...",
              "chapter_title": "...", "concept_id": "...",
              "created_at": "…Z"}],
  "catalogue_source": "database|published|fixture"
}
```

- `continue` is the most recent **in-progress** `lesson_progress` row, or the
  latest chapter with events that was never completed. A completed chapter is
  never the continue card.
- `classes` is the catalogue map with computed states (all four release
  classes, empty classes included). Activity in a chapter outside the
  catalogue appears in one extra group with `"class_level": null` and the
  humanized id as the title.
- `recent` is newest first, capped at 8, ids only.
- `catalogue_source` is honest: `database` (P1/P2 import has landed),
  `published` (`frontend/catalogue.json` is readable by this process), or
  `fixture` (F0's tracked stub; concepts may be empty).

### 2.3 `GET /v1/progress/chapters/{chapter_id}`

Chapter states per concept. `chapter_id` may contain `/` (path parameter).
Returns `{"chapter": <summary entry>, "concepts": [{"concept_id", "title",
"section_id", "state", "state_label", "evidence"}], "concepts_available":
bool}`. Unknown id with no events → `404 E-NOT-FOUND`; unknown id with events
→ `200` under its humanized id (`status: "unmatched"`).

### 2.4 `GET/POST/DELETE /v1/bookmarks`

- `GET` → `{"schema_version": 1, "count": n, "items": [{bookmark_id,
  target_type, target_id, created_at, chapter_id, chapter_title, section_id,
  lesson_url, label}]}`.
- `POST` body `{target_type, target_id}` → `201` when created, `200` when the
  same target already exists (`{"item": …, "created": bool}`). Idempotent.
  A bounded batch is the same route with `{"items": [...]}` (1–100 items) →
  `{"items": [...], "created": n, "existing": m}`; one invalid item rejects
  the batch before any write. The device merge uses the batch form so a
  100-item local store is one request, not 100 (the `/v1/*` family limit is
  30 requests/min per IP).
- `DELETE ?target_type=&target_id=` → `{"ok": true, "removed": bool, ...}`;
  a repeat delete is `removed: false`, not an error.
- `target_type` ∈ `chapter|concept|block|question`; chapter ids use the
  chapter pattern, the other types use `<chapter_id>:<object_id>`. A block
  target's `target_id` is `<chapter_id>:<section_id>` so the UI can deep-link
  `lesson_url#section_id`.
- Every create/remove also writes a `bookmark_add`/`bookmark_remove`
  `progress_event`, so saving is part of the weekly rhythm and the recent
  activity feed.

All four routes return `Cache-Control: no-store`. Auth is the F0 account
guard (`require_context`) and CSRF is F0's `require_csrf`; the global `/v1/*`
API family rate limit (30/min per IP hash) applies — no second limiter.

## 3. State rules (published on `/app/progress`)

The rules are versioned (`RULES_VERSION = 1`) and shown to the student in
plain words. There is no ability score and no comparison.

| State | Rule |
|---|---|
| **Not started** | no event for the chapter/concept |
| **Learning** | lesson activity only (`lesson_block_view` / `lesson_complete`), or a saved section (`bookmark_add`), with no practice evidence |
| **Practising** | ≥ 1 practice answer, test, or explain-back, and not below |
| **Confident** | ≥ 5 practice answers, ≥ 80% correct, and ≥ 2 of the last 3 answers correct |
| **Needs revision** | ≥ 3 practice answers and < 50% correct |

Precedence: `not_started` → `needs_revision` → `confident` → `practising` →
`learning`. Only `practice_answer` carries a correct/incorrect bit today;
`test_submit` and `speaking_attempt` count as practice activity but do not
move the accuracy figure. This is deliberate until F5/F7 define their score
semantics.

Events are ordered by `(created_at, event_id)`; a client that needs the
order of answers to be meaningful should send `occurred_at` (F5's player
sends one answer per request, so its order is the request order). Concept
states use the same rules on events with that `concept_id`; a concept with no
tagged events is **Not started** even when the chapter is Learning.
The guest merge maps `section_id → concept_id` from the published catalogue,
so a merged reading lights up the right concepts.

## 4. Weekly rhythm

- Window: the last **7 calendar days including today** in **IST**
  (`Asia/Kolkata`, fixed UTC+05:30 — no DST; no tzdata dependency).
- An active day is any event's IST date.
- Goal: **4 days a week** (`WEEKLY_GOAL_DAYS`), shown as “Goal: 4 days a week.”
- Copy is rhythm, not streak: “A rhythm, not a streak: a missed day does not
  reset anything.” No streak-loss framing, no badges.

## 5. Guest → account sync (`frontend/assets/app-progress.js`)

The device is the source of truth until the student chooses to merge. The
island **never deletes or rewrites** `zivon.progress` / `zivon.bookmarks`.

1. On an authenticated page, read both F4 keys. On a page that also mounts
   `window.ZivonLessonShell`, fold `getProgress()` (the in-memory record for
   the current `/courses/<course>/<topic>/` route) into the payload and
   register `setProgressSink(fn)` so a shell write refreshes the offer. On
   `/app` the shell does not exist and the store is read directly.
2. If there is content the marker does not cover, reveal the
   `partials/progress_sync.html` panel with counts (“N chapters (M sections
   read) and K saved sections”).
3. “Bring them in” fetches `/catalogue.json` (same origin) to map
   `course/topic → chapter_id` and `section_id → concept_id`. The catalogue
   entry carries `href` (`courses/<course>/<topic>/index.html`), not a
   `topic_slug` (`factory/render.py::_catalogue_entry`); the island derives
   the device-store key from `href` (falling back to `topic_slug` when a
   future publish adds it). It then:
   - `lesson_block_view` per read section (absolute `blocks_seen`, source
     `merge`), plus `lesson_complete` when the local record says completed;
   - one `POST /v1/bookmarks` per saved section (`block`,
     `<chapter_id>:<section_id>`).
   Batches are 40 events; the CSRF meta token is sent. If the catalogue fetch
   fails, the fallback chapter id is the local `course/topic` key (the API
   accepts it and the map shows it as unmatched) — data is not dropped
   because a file is briefly unavailable.
4. On success, write per-part fingerprints to `localStorage["zivon.sync.v1"]`
   (`events`, `bookmarks`, `merged_at`), leave the local copy untouched, and
   offer a link to the dashboard. The panel is not hidden: the success
   message stays until the next load.
5. On failure, no marker is written for the failed part, local data stays,
   and the copy says so (“They are still on this device; nothing was
   deleted.”). A per-item `rejected` entry in an otherwise-`200` events
   response counts as a failure for that part: the accounting must never say
   “brought in” while rows were refused. A retry is safe: lesson counters are
   max-upserts, bookmark posts are idempotent, and the weekly counts are
   distinct-day based.
6. “Not now” dismisses the offer for the current browser session
   (`sessionStorage`), not forever. A later change to the device progress
   (new fingerprint) re-offers it.

The fingerprints are a local, deterministic summary of the chapter keys,
section ids, completion flags, and bookmark identities — not a hash and not
PII. Nothing about the device leaves the browser except the events/bookmarks
the student chose to merge.

## 6. Dashboard (`/app`)

Sections, in order: greeting + class/board/language; sync offer (when
applicable); **Continue learning** (most recent incomplete chapter, with
sections read and last activity); **Today** (one honest action — continue,
start the first published chapter, or the catalogue; plus the explicit “five
practice questions and one explain-back are not live yet” note); **Physics
map** snapshot (up to four chapters of the student's class with state tags);
**Recent activity** (last 8, label + chapter + relative day); aside with
**This week** (7-day strip + goal), **So far** (3 counts, not a KPI wall), and
**Quick actions** (live links + honest not-live statuses).

New user: honest empty copy and a Start card; no invented activity.
Class with no published chapter: “No Class N chapter is published yet.”
No class set: catalogue prompt. Panel error: greeting stays, an error notice
with retry, no data block.

## 7. Progress map (`/app/progress`)

Class → chapter → concept map. Every chapter row: number, title (lesson
link), state, sections read, practice/accuracy evidence, next step, and a
`<details>` concept list (open for chapters with activity). Empty classes say
so. The “How these states work” disclosure publishes the exact rules.
No share link, no leaderboard, no parent view, no opaque score.

## 8. Saved sections (`/app/bookmarks`)

List with type label, chapter title, deep link (`#section_id` for blocks),
relative date, and a Remove button. Removing calls `DELETE /v1/bookmarks`
with the CSRF header, drops the row on success, and announces the result in
an `aria-live` status. Empty state points at the lesson Contents → Save path.

## 9. States

| State | Dashboard | Progress | Bookmarks |
|---|---|---|---|
| default | Continue/Today/map/recent/week | all classes + states + rules | saved list |
| loading | n/a (SSR completes before bytes; a slow DB is the panel error) | same | same |
| empty | new-user copy + Start card | all chapters Not started (the map is the content) | “Nothing saved yet.” |
| partial | class with no chapters; sync offer when local data exists | chapter without concepts says concept detail is unavailable; unmatched chapters under “Other activity” | — |
| error | panel notice + retry, greeting stays | panel notice + retry | panel notice + retry |
| offline | n/a server-side (navigation is the browser's offline page) | same | same |
| permission-denied | guest is 303 `/login?next=` (F0C) | same | same |
| reduced-motion | no animation | no animation; `<details>` is native | no animation |
| untranslated | English copy + saved-language note (shell contract) | same | same |
| quota-exhausted | n/a (voice credits are the dock's; no voice here) | n/a | n/a |
| consent-missing | n/a (voice consent is per device in the lesson) | n/a | n/a |

## 10. Accessibility, mobile, privacy

- Semantic landmarks (one `main`, one page `h1`), `aria-labelledby` sections,
  native `<details>` for rules/evidence, `role="alert"` for panel errors,
  `role="status"`/`aria-live` for sync and removal outcomes.
- State is text + a distinct marker shape (dashed, half-filled, hollow,
  filled green, hollow red), never colour alone.
- 360 px: single-column grid, progress rows stack, week chips wrap, controls
  ≥ 40 px; `testing/frontend/test_app_pages_layout.py` asserts no horizontal
  overflow in Chromium at 360 px and a clean console.
- No email, user id, session id, or cookie in HTML (F0C contract). The API
  never returns `user_id`. No free text in `progress_event.payload`; no
  parent access, public profile, share link, or leaderboard. Account deletion
  cascades through `users` (F0 tables), so events/bookmarks go with it.

## 11. Tests

| Suite | Command | Covers |
|---|---|---|
| Backend API | `python -m unittest discover -s testing/backend -t .` (also `testing/backend/test_progress_api.py`) | auth, CSRF, per-item validation, batch bounds, state rules, weekly rhythm, chapter detail, bookmark CRUD/idempotency, tenant isolation, no free text |
| Pages | `testing/backend/test_dashboard_pages.py` | new/partial/error states, rules copy, bookmark page, no PII/lesson devices, a11y/viewport static checks |
| Browser sync | `testing/frontend/test_app_progress_sync.py` | offer, additive mapped merge against the **real** `frontend/catalogue.json` entry (href-derived key; the fixture pins that the entry has no `topic_slug`), CSRF, preserved local copy, failed merge, per-item rejection, dismissal, F4 sink/`getProgress()`, bookmark removal |
| Browser layout | `testing/frontend/test_app_pages_layout.py` | 360 px overflow, stacked rows, touch targets, clean console |

All key-free and offline; no model call exists on this path.

## 12. Known debt / next

- The concept catalogue inside the backend image comes from the DB once the
  P1/P2 import lands; until then development/CI reads `frontend/catalogue.json`
  and the cluster falls back to F0's fixture (chapters without concepts).
  Closing this is P1/P2's import, not an F3 rewrite.
- `blocks_total` (sections per chapter) is not carried by the published
  catalogue, so “N of M sections” shows `N sections read` until F4/P1 expose a
  section count. The progress API already accepts and stores it.
- The lesson-page sink that would POST each write immediately is F4's
  `setProgressSink` consumer; F3's `/app` merge is the reliable path today.
  When F4 wires the sink, it should POST `/v1/progress/events` with the same
  payload shapes and the CSRF token it already has on the page.
- Practice/test/speaking events are accepted by the API so F5/F6/F7 can write
  them without a schema change; their player UIs and accuracy semantics are
  theirs.
- Aggregation reads the most recent **5,000** events per account
  (`EVENTS_READ_LIMIT`). At prototype scale that is years of activity; F8's
  `chapter_stat` materialization (REQUIREMENTS §8.4) is the eventual rollup
  and should replace the raw read before the limit can matter.
- The four **client analytics** events in REQUIREMENTS §11
  (`dashboard_view`, `continue_click`, `plan_start`, `progress_view`) are not
  emitted in this slice: `/api/v1/events`'s `VALID_EVT_IDS` whitelist
  (`backend/routes/student.py`) has no ids for them and the event contract is
  shared. The learning activity itself is already recorded by
  `/v1/progress/events`. Add the four client events with the event-contract
  owner when the whitelist extends.
