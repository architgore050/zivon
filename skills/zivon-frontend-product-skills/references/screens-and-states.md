# Screens and states

The screen inventory and the 11-state matrix. Use this before writing a screen
spec, and again before review. A screen is not built until every region has a
row and every state cell is either implemented or `n/a` with a reason.

The binding sources are `docs/specs/frontend/state-matrix.md` (the existing
implementation view), `docs/product/features.md` §5.4 (the canonical
product-state matrix), and `tmp/full-frontend/REQUIREMENTS.md` §10 (the
full-product screen specs). This file reconciles them into the working matrix
a frontend agent fills.

## 1. Screen inventory

| Group | Screen | Route | Surface | Primary data / API | Key events |
|---|---|---|---|---|---|
| Public | Landing | `/` | Static | None required; optional catalog summary | `landing_view`, `demo_play`, `cta_try` |
| Public | Catalogue | `/courses` | Static + optional progress decoration | `/v1/catalog`, `/v1/catalog/search`; progress if signed in | `catalogue_view`, `chapter_open`, `search` |
| Public | Class/course | `/courses/{class}/physics` | Static | `/v1/catalog/chapters?class=` | `course_view`, `chapter_open` |
| Public | Method, About, Pricing, Trust | `/method`, `/about`, `/pricing`, `/privacy`, `/terms`, `/contact`, `/status` | Static | Waitlist `POST /v1/waitlist`; privacy `GET /v1/data/challenge`, `DELETE /v1/data` | `pricing_view`, `waitlist_submit`, `delete_request` |
| Public | 404 | unmatched | Static | None | — |
| Lesson | Generated lesson | `/courses/{class}-physics/{chapter}/` | Static generated + shell islands | `manifest.json`, static narration, `/v1/session`, `/voice/ws`, `/v1/reports`, `/v1/events` | `lesson_view`, `block_view`, `sim_interact`, `check_answer`, `read_aloud`, `bookmark`, `ask_about_this` |
| Auth | Login, signup, verify, reset, onboarding, Google | `/login`, `/signup`, `/verify-email`, `/forgot-password`, `/reset-password`, `/onboarding`, `/auth/google/*` | SSR | `/v1/auth/*`, `/v1/me` | `signup_start`, `signup_complete`, `login`, `google_login`, `verify_email`, `reset_password`, `onboarding_complete` |
| App | Dashboard | `/app` | SSR | `/v1/progress/summary`, `/v1/swot`, `/v1/catalog` | `dashboard_view`, `continue_click`, `plan_start` |
| App | Practice hub | `/app/practice` | SSR | `/v1/practice/history`, `/v1/catalog`, `/v1/swot` | `practice_start` |
| App | Practice player | `/app/practice/{session_id}` | SSR + island | `/v1/practice/sessions/{id}`, `POST answers` | `practice_answer`, `hint`, `ask_tutor` |
| App | Practice summary | `/app/practice/{session_id}/summary` | SSR | Session result | `practice_complete`, `retry_mistakes` |
| App | Speaking hub | `/app/speaking` | SSR | `/v1/speaking/prompts` | `speaking_start` |
| App | Speaking recorder | `/app/speaking/{prompt_id}` | SSR + island | `POST /v1/speaking/attempts` (audio transient) | `speaking_submit`, `speaking_result`, `speaking_retry` |
| App | Tests hub | `/app/tests` | SSR | `/v1/tests/history`, `/v1/series` | `test_start`, `test_review` |
| App | Series catalogue/detail | `/app/series`, `/app/series/{slug}` | SSR | `/v1/series`, `/v1/series/{slug}` | `series_view` |
| App | Test builder | `/app/tests/new` | SSR | `/v1/tests/custom` | `test_start` |
| App | Test player | `/app/tests/{attempt_id}` | SSR + island | Start/resume, `PATCH answers`, submit | `test_answer`, `test_flag`, `test_submit`, `test_autosave_fail` |
| App | Results/review | `/app/tests/{attempt_id}/review` | SSR | `/v1/tests/attempts/{id}/review` | `test_review`, `ask_tutor` |
| App | Progress map | `/app/progress` | SSR | `/v1/progress/summary`, `/v1/progress/chapters/{id}` | `progress_view` |
| App | SWOT | `/app/swot` | SSR | `/v1/swot`, `/v1/swot/explain` | `swot_view`, `swot_card_open`, `swot_action` |
| App | Doubts | `/app/doubts`, `/app/doubts/{id}` | SSR | `/v1/doubts/*` | `doubt_open`, `doubt_history_open`, `doubt_delete` |
| App | Bookmarks | `/app/bookmarks` | SSR | `/v1/bookmarks/*` | `bookmark` |
| App | Settings/privacy | `/app/settings`, `/app/settings/privacy` | SSR | `/v1/me`, `/v1/me/export`, `/v1/me/delete` | `settings_save`, `language_change`, `delete_request`, `export_request` |
| Admin | Staff login + cockpit + panels | `/admin/*` | SSR, staff auth | `/v1/admin/*` | Staff-only audit events |

## 2. The eleven states

| State | Meaning | Default treatment |
|---|---|---|
| `default` | Loaded, populated, no special condition | The designed screen |
| `loading` | Data or an asset is still arriving | Server-rendered pages paint HTML first; islands show a quiet inline status, not a full-page spinner. Static pages have no loading state. |
| `empty` | The request succeeded and there is genuinely nothing | Honest copy + one next action; never a blank panel |
| `partial` | Some data/feature is absent but the page works | Render what exists; label what is missing; no dead links |
| `error` | A request or render failed | One sentence, a retry, and a way back; panel-level errors stay local |
| `offline` | The network is unavailable | Cached/static content keeps working; network actions disabled with a reason; no fake success |
| `permission-denied` | Mic, camera, notification, or role permission refused | Explain, offer the non-permission path, never re-prompt in a loop |
| `reduced-motion` | `prefers-reduced-motion: reduce` | No autoplay, no looping animation; one static draw; instant text |
| `untranslated` | The selected locale has no content | English string + visible marker; never silently mix |
| `quota-exhausted` | The voice credit guard is exhausted | Voice disabled with the ledger line; typed input and all reading/practice work |
| `consent-missing` | Voice/analytics consent not granted | Gate the mic; reading, sims, checks, typing work; decline never re-nags |

A state that cannot occur gets `n/a (reason)`. A blank cell is a defect.

Naming note: the existing SP5 matrix calls the credit state `over-credit-budget`;
the full-product name is `quota-exhausted`. They describe the same condition
(the voice guard has no budget left, while reading, simulations, checks, and
typing still work). Use the full-product name in new specs and map it back when
reading the older matrix.

## 3. The matrix

Cells name what the student perceives and, where useful, the code path
(`[static]`, `[ssr]`, `[island]`, `[kit]`).

| Screen | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| **Landing** | Notebook hero, real clip + transcript, mini-sim, one CTA `[static]` | Static paint; no spinner | n/a (fixed marketing copy) | Demo section absent if the clip is not published; page still sells the product | Demo fails → transcript + static still visible; no broken embed | Static page works; demo disabled with a reason | n/a (no mic/camera until the demo is pressed) | No autoplay; clip paused; static first frame | EN/HI/Hinglish variant or English + marker | n/a (no credits before voice) | n/a (no voice on the landing) |
| **Catalogue** | Class tabs, chapter cards, status, progress if signed in `[static]` + `[island]` | Static paint; progress decoration arrives later | No chapters for the filter → clear copy + reset filter | Some classes/chapters not live → status badge, no dead link | Catalogue fetch fails → static published list remains | Cached list + offline chip | n/a (public page) | Hover/focus colour only; no motion | English cards or localized variant + marker | n/a | n/a |
| **Lesson** | Ruled paper, text, diagram, sim, check, language bar, dock tab `[static]` + `[kit]` | Static HTML first; sim first frame inside budget | n/a (a published lesson has content; an empty page cannot publish) | Some blocks untranslated → English + marker; a missing narration asset → no button | Broken sim → on-canvas painter + text mirror; broken kit → content readable | Cached page + read-aloud; dock offline; typed path open | Mic denied → `MIC OFF` stamp + typed field; reading unaffected | One static sim draw; no bars/caret; instant caption | English + `.zn-untranslated-notice` per block | `text_only` dock + ledger line; reading/sims/typing free | Consent sheet before dock; decline hides voice quietly |
| **Auth** | One paper card: email/password, Google, guest link `[ssr]` | Submitting state on the button; fields disabled; no double submit | n/a (a form is never empty) | Email unverified / Google not linked → row state + action | Invalid credentials, rate limit, expired token, Google error → field-level copy | Submit disabled with a reason; password managers still work | n/a | No animated toggle or spinner; instant status text | UI strings per locale; English + marker if missing | n/a | n/a (voice consent is separate) |
| **Dashboard** | Greeting, continue, today, map, SWOT, recent, one primary CTA `[ssr]` | Server paints shell; panels may stream/skeleton | New user: no data → start a chapter/diagnostic, not empty cards | No SWOT yet → "not enough data"; no tests yet → hide the panel | Panel-level error; other panels keep working | Cached summary + offline banner; actions disabled with reason | n/a (no permission) | No animated counters or confetti | English + localized dashboard strings; marker where missing | Voice-limited notice; typed tutor remains | n/a (no mic on the dashboard) |
| **Progress** | Class → chapter → concept map with five mastery states `[ssr]` | Map skeleton by class/chapter | New user: all "Not started" + start action | Some chapters unrated or practice not ready → label, no fake state | Panel error + retry; other classes remain | Cached snapshot + timestamp; recompute disabled | n/a (private to the student) | No animated map or count-up | Labels/evidence per locale; marker if missing | n/a (no voice dependency) | n/a |
| **Practice** | Hub cards or one question, progress, hint, check, feedback `[ssr]` + `[island]` | Session loads; question shell first | No attempts → chapter drill is the empty state | Some chapters lack practice → disabled card with reason | Answer submit fails → keep answer, retry, no data loss | Loaded local pack works; tutor action disabled | n/a (no permission) | Feedback appears instantly; no shake animation | Question/option language per surface; English + marker if missing | Tutor action disabled; practice itself works | n/a (practice needs no voice consent) |
| **Speaking** | Prompt, 45 s timer, mic toggle, waveform, transcript, rubric `[ssr]` + `[island]` | Recording/transcribing/evaluating states with words, no fake percentage | No prompts for the chapter → browse another chapter | Rubric partially available → show what exists, label the rest | Upload/STT fails → retry; no data loss | Recording disabled; transcript/feedback already loaded remains | Mic denied → explain + retry or another prompt; no loop | Waveform static; timer still text; no pulsing | Prompt/feedback per locale; marker if missing | STT/TTS metered; the rest of the product remains usable | Consent gate before the mic; decline keeps the prompt readable |
| **Tests/series** | Hub, series cards, builder, exam paper, palette, review `[ssr]` + `[island]` | Test starts/resumes; autosave indicator | No tests/series yet → browse catalogue | Some papers/sections not ready → locked with reason; no dead start | Autosave fail → keep local, retry, tell the student; submit fail → keep answers | Loaded test continues; submission retries when online | n/a (no permission) | Timer is text; no pulsing palette; no animation | EN/HI for CBSE-style; EN/HI/Hinglish otherwise; marker if missing | Tutor action only; test itself works | n/a |
| **SWOT** | Four labelled quadrants with evidence cards + one next action `[ssr]` | Skeleton by quadrant, not a spinner | "Not enough data yet" + what to do to earn it | Some chapters unrated → "unrated" row, not a fake quadrant | Snapshot error → retry + link to progress; no stale claim | Cached snapshot + timestamp; recompute disabled | n/a (private to the student) | No quadrant animation; static cards | Labels/evidence per locale; marker if missing | n/a (no voice dependency) | n/a |
| **Doubts** | Saved text conversations: title, chapter, date, last message `[ssr]` | List skeleton; detail loads | No doubts yet → ask from a lesson | Deleted/empty thread → tombstone + back | Load/delete fails → retry; no silent loss | Cached list; new turns disabled with reason | n/a | No typing animation | History in the language it was spoken; UI chrome localized | Voice turns unavailable; typed history readable | Consent applies to new voice turns only |
| **Settings** | Profile, class/board/language, password, Google link, voice, accessibility, privacy, delete/export `[ssr]` | Save in progress; field-level status | n/a (form is never empty) | Email unverified / Google not linked → row state + action | Validation or save error tied to the field; delete failure deletes nothing | Read-only cached settings; save disabled with reason | n/a | No animated toggles | Labels localized; account data as stored | Voice settings still apply to typed mode | Consent status shown, not hidden |
| **Admin** | Cockpit, coverage, questions, series, blueprints, users, credits, reports, flags, evals, debt `[ssr]` | Panel skeletons | "No runs yet" / "No reports" per panel | One source down → panel error, other panels fine | Auth fail → login; 403 page; panel retry | n/a (staff tool on the cluster network) | 403 / role denied | No animated charts | English staff UI only | Guard badge shows exhausted | n/a |

## 4. Screen-specific notes

### Landing

The demo clip must have a transcript and controls; never autoplay. The
mini-simulation is a real kit sim, not a video. The primary CTA is one action.
No fake urgency, no testimonial carousel, no logo wall.

### Catalogue

Status is honest: `live`, `lesson only`, `in development`, `practice coming`,
`series available`. A card never links to a page that does not exist. Progress
decoration is additive; the catalogue works signed out.

### Lesson

The generated page is the content. The shell adds the language bar, read-aloud,
report, consent, and dock. With JavaScript off, the text, examples, diagrams,
checks, and sources remain readable. The dock never mount before consent. The
lesson has no “mark complete” button; progress is derived.

### Auth

One paper card, not a split-screen marketing page. Email/password and Google,
plus “continue as guest”. Errors are field-level and never enumerate accounts.
The reset and verification links are recovery flows, not alternate logins. A
Google-created account is prompted to set a password so both methods stay on
one identity. A guest's local progress is merged after sign-in with a summary;
never silently drop it.

### Dashboard

It answers “what should I do now?”, not “here are six charts”. One primary
action. A missed plan resets quietly; no streak loss, no guilt copy.

### Progress

Class → chapter → concept, with the five mastery states in words and shape.
Evidence is reachable per chapter; a thin sample is “Not started”/“Learning” or
“Unrated”, never “Confident”. Next step is one action. The map is private; no
parent or share view.

### Practice

One question at a time, feedback after commit, hint before commit only. Numeric
parse failure is a wrong-but-recoverable answer with a retry, never a crash.
The tutor action opens anchored to the question.

### Speaking

The transcript is shown as heard; no editing. Re-record instead. Rubric feedback
is labelled AI feedback, with key ideas present/missing and one next step. No
false precision. Raw audio is transient; only text is saved and deletable.

### Tests and series

Exam-paper layout: sections, marks, question numbers, palette, timer, mark for
review, autosave. Time expiry auto-submits with a warning. Review shows the
student answer, correct answer, explanation, and a tutor action. CBSE-style
series are EN/HI only and carry the approved copy.

The six series are **AI Lesson**, **PYQ Pattern**, **Exact PYQ**, **Board
Practice**, **Challenge**, and **Loop**. Every series card states its purpose,
coverage, length, difficulty, language set, and — for the board-style three —
the “close to the paper pattern / not an official CBSE paper” copy. No series
presented as a token sample; coverage is a gate, not a marketing line.

### SWOT

Default placement is relative to the student's own chapters, not a cohort.
Fewer than three chapters with evidence → “Not enough data yet”, not a rank.
Each card: quadrant, 2–3 plain-language reasons including pace, one next
action. No share, no parent, no leaderboard.

### Doubts

Saved text conversations only; no raw audio. Reopen and continue. Delete is
real. Offline shows the cached list and disables new turns with a reason.

### Settings

Every save is field-scoped. Email verification and Google link errors are
explained. Delete/export are real server actions with confirmation. The
privacy page states what is kept, for how long, and what deletion removes.

### Admin

Staff-only, aggregate-only, no student free text. Every panel has an empty and
a panel-error state. Privileged actions are audited. A 403 is a page, not a
stack trace.

## 5. Cross-cutting rows

| Concern | Rule |
|---|---|
| Fonts | Local `@font-face`, `font-display: swap`, system fallbacks; Devanagari fallback per glyph; a missing font degrades, never blocks. |
| JS failure | Content is readable; checks/sims inert; no blank page. The reading core survives. |
| Offline | Static pages and cached lessons work; network actions disable with a reason. |
| Auth | Guest can read/practise; private pages redirect to login with a safe return path; no redirect loop. |
| Deletion | A failed wipe deletes nothing local and says so; a successful wipe removes local keys after the server ack. |
| Time | Timers are text; a warning precedes expiry; an expired test auto-submits and says so. |
| Copy | Every state has copy; no invented state names; no raw error text or stack trace. |

## 6. Completeness check

- [ ] Every screen in scope has a row.
- [ ] Every region of the screen has a row or is covered by a parent row.
- [ ] All 11 states are present; every `n/a` has a reason.
- [ ] Each cell names a visible outcome, not “handled”.
- [ ] Each state names the code path that renders it.
- [ ] The failure-first review found no dead control, no fake success, no
      silent fallback.
- [ ] The state matrix is linked from the screen spec and the PR.
