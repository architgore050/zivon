# Personalized learning frontend — hub, session, settings section, artifact viewer (PL4)

Status: implementation contract for the W5.5 PL4 slice (branch
`cloud/w5-5-pl4-frontend`, based on `main` @ `9e07400`). It describes code that
exists: `web/routes/personalized.py`, `web/personalized_views.py`,
`web/templates/app/personalized_hub.html`, `web/templates/app/personalized_session.html`,
`web/templates/app/partials/personal_instructions.html`, the `Learn` nav entry,
`frontend/assets/personalized.css`, `frontend/assets/personalized.js`, the
`/app/settings` include + `web/routes/settings.py` view key, and the
privacy-page row. The teaching turn itself is PL2's `API-PL-10` SSE/JSON API;
this document specifies only the pages and islands around it.

Consumes: `docs/specs/frontend/web-shell.md` (guard/CSP/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base system only — **no §10 lesson
device**), `docs/specs/personalized-learning/spec.md` (SCR-PL-01…05 and the
copy rules), `data-and-api.md` §4 (endpoint contract), `agent-and-rag.md` §3.2
(event catalogue), `interactive-artifacts.md` §5/§12 (the PL3 viewer partial +
host bridge), and `workstreams.md` §5 (PL4 ownership).

## 1. Routes and code paths

| Route | Methods | Purpose | Code |
|---|---|---|---|
| `/app/personalized` | GET | the hub: picker, weakness field, quota strip, saved-session list | `personalized_hub` |
| `/app/personalized/start` | POST | start a session from the form (API-PL-05 rules) | `personalized_start` |
| `/app/personalized/{session_id}` | GET | the session screen: transcript, check, composer, artifact cards | `personalized_session` |
| `/app/personalized/{session_id}/end` | POST | end the session (API-PL-11's store path) | `personalized_end` |
| `/app/personalized/{session_id}/delete` | POST | hard-delete after the confirm disclosure (API-PL-08) | `personalized_delete` |
| `/app/settings/instructions` | POST | save/clear personal instructions (API-PL-02/03 rules) | `settings_instructions_submit` |

All are `include_in_schema=False`, `noindex`, `no-store`, behind the F0C
guard: a guest is `303 /login?next=<path>`, unavailable auth is the 503 shell,
and another user's session id is a **branded 404**, never a 403 (no existence
oracle). The nav gains `Learn` (`/app/personalized`) between `SWOT` and
`Speak`.

The read models are computed in Python (`web/personalized_views.py`):
`safe_hub_view`/`safe_session_view` wrap the PL1 `PersonalizedStore` and
`QuotaService` plus the RAG catalog seam (`app.state.personalized_index_catalog`,
the same callable `API-PL-04` reads); a storage failure degrades to the honest
error view, never a JSON 500. The write routes call the same PL1 domain
functions the JSON API uses (`PersonalizedStore.create_session/end_session/
delete_session`, `save_preferences`/`clear_preferences`) with
`AuthService.verify_csrf` — there is no second write path, and **no route here
re-implements turn admission, quota reservation, or scoring**: the teaching
turn is always the island calling `API-PL-10`.

## 2. The hub (`SCR-PL-01`)

- Chapter picker: one native `<select>` with per-class `<optgroup>`s — the
  spec's class-grouped picker; a separate class-tab control would duplicate
  what the optgroup labels already carry (§0.1 value-addition filter). Only
  chapters with RAG index coverage are offered; `tier: source` renders the
  text badge `(source only)` in the option label (never colour alone).
- Concept picker: disabled until a chapter is chosen ("Choose a chapter
  first"); the island filters the server-rendered `<optgroup>`s by chapter.
  Without JavaScript the concept pick is unavailable — the weakness field
  covers the same need, and the select carries the reason.
- Weakness field: 500-char maxlength, live counter, stored with the session,
  never logged (the privacy note is in the hint).
- Start / Start from the chapter beginning: two submit buttons
  (`mode=diagnose` / `mode=beginning` → `skip_diagnostic`). Both are disabled
  when `start_blocked` — kill switch, quota exhausted (user/global), the daily
  session allowance spent, or no index coverage — with the honest reason in a
  `role="status"` line under the buttons.
- Quota strip (`SCR-PL-05`): `N turns left today · resets 00:00 IST` in the
  page meta, `role="status"`; warn ≤ 15% remaining is the same line (no
  countdown, no urgency styling); exhausted and kill-switch copies come from
  `personalized_views` and match `spec.md` §5.2.
- Saved sessions: title, stage tag, relative time, the 83-day warning
  ("Deletes in 7 days · export it"), Continue, Export (the `API-PL-09`
  attachment link), and Delete behind a confirm-then-do `<details>`
  disclosure with CSRF.
- Empty: "No sessions yet. Start with the chapter you're studying." — no fake
  cards. Footer line: "Practice questions are AI-generated in the board-exam
  style. They are not official CBSE questions." (spec.md §9).

## 3. The session screen (`SCR-PL-02`)

Server-rendered transcript (the last 50 messages) + one island
(`personalized.js`) for the live turn loop.

- Cards are built by `_message_cards` from the stored rows: teaching text with
  citation chips (label + locator) or the honest "No page reference was found
  for this part" note when `ungrounded`; the key statement; student turns;
  check cards with the question, options (radiogroup) or a numeric input with
  the unit, and "AI-generated practice" in the kicker when the item is
  generated (§9); feedback attached to its check (`Correct.` / `Not yet —
  let's look again.` + expected + explanation, shape words plus the left-rule
  accent — never colour alone); stage lines; the mastery summary with the
  per-concept status and evidence counts.
- The stored answer key never reaches the page (`_message_out` does not
  serialize it; a test pins `answer_key`/key text absence).
- Header: title, stage tag, quota strip, and the personalization line
  "Using your learning preferences · Edit" only when the account has saved
  instructions (spec.md §1.5). Notices: soft nudge at 40 turns, the 60-turn
  cap ("continue from your last session" from the hub), the completed state
  (read-only transcript, no composer), and the quota/kill-switch copies.
- Composer: `Explain directly` / `I'm stuck` (`explain_directly` / `hint`) —
  both disabled server-side with the title "Submit the open check first" when
  a check is open, because `turn_router` prevalidation rejects those actions
  while a check is armed (§4.6); the island mirrors the same rule after every
  event. The message input (`message` action, 2000 chars, never graded) and
  Send. End session is a plain CSRF form — not buried, no confirmation dialog,
  reversible by resuming (spec.md §2.6).
- The island (`window.ZivonPersonalized.mount`, idempotent): fetch + SSE
  parsing of the §3.2 catalogue with `X-CSRF-Token` from the meta tag, one
  `aria-live="polite"` announcement per turn ("Zivon is writing…" then the
  first line, never per token), check submit with the §3.2 body, quota strip
  update on `turn.done`, honest error cards (`E-PL-MODEL-DOWN`,
  `E-QUOTA-EXHAUSTED`, `E-PL-TURN-OPEN`, `E-RATE-LIMIT`) each with Retry, one
  idempotent network retry with the **same** `client_turn_id` (§3.4), the
  offline state (composer disabled + "Reconnect to continue", transcript
  stays readable), and the JSON assembled-turn fallback when
  `ReadableStream` is unavailable. `401/403` reloads the page so the guard's
  `303` carries `next` back to the session (PL-F9).
- "Load earlier" appears only when the 50-message window is full; one page
  back per load (R1 scope, no virtualization).
- Reports: the teaching card's "Report a physics mistake" posts
  `POST /v1/reports` with `category=wrong_physics`, and the artifact viewer's
  Report event posts `category=broken_sim`; both send
  `course_id=personalized/<chapter_id>` (non-catalogue namespace) and the
  message/artifact id in `block_id` — the §4.11 constraints, no new endpoint.

## 4. Artifact viewer (`SCR-PL-03`)

The session screen embeds the PL3 partial
(`web/templates/app/partials/artifact_viewer.html`) and its host bridge
(`/assets/personalized-artifact.js`) — PL4 owns only the box sizing in
`personalized.css` and the report bridge. States:

| Artifact state | What the student sees |
|---|---|
| `ready` | the partial with the server-issued `src`; sandbox iframe contract unchanged (`allow-scripts` only, `allow=""`, `no-referrer`, watchdog) |
| `pending` | the partial without a `src`; status line "Building a visual…"; the bridge polls `API-PL-14` |
| `failed` | a server-rendered fallback card: "The visual didn't build. Here's the diagram instead." + the validated fallback SVG (or the ask-for-text line) — no JS needed |
| missing/other ids | nothing (no empty card) |

The client never constructs an artifact URL: `src` is carried from the
serializer or the status payload; the island only ever forwards the
server-issued value into the viewer card.

## 5. Settings section (`SCR-PL-04`)

`personal_instructions.html` is included once by `app/settings.html` (plus its
two asset lines); `web/routes/settings.py` adds one allow-listed view key
(`personal_instructions`, the account's own C22 value). The form posts to
`/app/settings/instructions`; every outcome is a `303` back to
`/app/settings` and the partial renders the status from the query params, so
the F2 route needs no other edit:

- Save: normalized + validated by the PL1 domain function; the status line is
  `role="status"` — "Saved. Zivon will use this from your next question."
  (the field applies from the next turn, never "immediately").
- Rejection (`too_long | contact_details | system_instruction | control_chars`):
  `role="alert"` copy that says what happened and that nothing was saved; the
  previous value is untouched (validation raises before any write).
- Clear: confirm-then-do through a `<details>` disclosure ("Clear your
  learning preferences? Lessons will use the default style."); idempotent.
- Empty: "No preferences yet — the default style is already good."
- The island's counter gates Save (disabled while unchanged or over 500).
- The boundary note: "What this can't do: change safety rules, make Zivon
  ignore the lesson, or ask you for personal information."

## 6. State matrix

Legend: `n/a (reason)` is a valid cell. The canonical 11-state vocabulary plus
the `auth-required` row (spec.md §7).

### 6.1 Hub

| State | What the student sees | Rendered by |
|---|---|---|
| default | picker + weakness field + sessions + quota strip | `personalized_hub` |
| loading | n/a — SSR completes before bytes | — |
| empty | "No sessions yet…" + the start form | template empty branch |
| partial | source-only badges; no coverage → honest notice + catalogue link | `_catalog_chapters` / `no_content` |
| error | store failure → "Personalized learning is unavailable right now…" + retry | `safe_hub_view` error view |
| offline | browser offline page; no queued writes (form POST) | n/a (server) |
| auth-required | `303 /login?next=/app/personalized` | the F0C guard |
| permission-denied | n/a — a valid session owns its own list; another owner's id never appears | — |
| reduced-motion | no animation; CSS guard present | `prefers-reduced-motion` block |
| untranslated | English copy; saved language shown in the shell | shell note |
| quota-exhausted | Start disabled + honest copy; Continue/Export/Delete stay enabled | `start_blocked` / `start_note` |
| consent-missing | n/a — no microphone on this surface | — |

### 6.2 Session

| State | What the student sees | Rendered by |
|---|---|---|
| default | transcript, check, composer, quota, stage tag | `personalized_session` |
| loading | streaming teach card + "Zivon is writing…" live line; check disabled while streaming | island `handleEvent` |
| empty | diagnose stage with no card yet → the composer's Explain/Continue starts the first turn | island |
| partial | pending artifact ("Building a visual…"), ungrounded note, "Load earlier" | serializer + island |
| error | honest error card + Retry (same `client_turn_id`); the turn is not counted complete | `buildErrorCard` |
| offline | transcript readable; composer disabled + "Reconnect to continue"; no queued turns | island offline handler |
| auth-required | `303 /login?next=/app/personalized/{id}` | the F0C guard |
| permission-denied | another user's session → branded 404 page | `_not_found` |
| reduced-motion | no animation; artifacts start paused via the PL3 bridge | CSS guard + bridge |
| untranslated | English UI; teaching text follows the session language (PL2 contract) | — |
| quota-exhausted | turn blocked before spend: honest strip + copy; the in-progress turn finishes | quota view + `E-QUOTA-EXHAUSTED` card |
| consent-missing | n/a (no mic) | — |

### 6.3 Artifact viewer

| State | What the student sees |
|---|---|
| default | ready artifact, title, controls, sandbox meta line |
| loading | "Building a visual…" status line; teaching text already readable |
| empty | no artifact reference → nothing rendered (no empty card) |
| partial | failed build → server-rendered fallback card + note |
| error | iframe watchdog/second-load → the PL3 bridge unloads the frame and shows the fallback |
| offline | cached HTML may render; a new build is the turn's business, never a client retry |
| permission-denied | unreferenced artifact id → `404` at `API-PL-13/14` |
| reduced-motion | paused static frame + Play (the PL3 bridge) |
| untranslated | title/fallback in the session language where available |
| quota-exhausted | builds stop at the server; the fallback carries the turn |
| consent-missing | n/a |

### 6.4 Settings instructions section

| State | What the student sees |
|---|---|
| default | saved text (or empty), counter, Save/Clear |
| loading | n/a — SSR |
| empty | "No preferences yet — the default style is already good." |
| partial | kill switch → save/clear render the 503 page with the honest notice; the field itself is not metered |
| error | rejection → `role="alert"` copy + previous value untouched; store down → `instructions_error=unavailable` |
| offline | unsaved edits stay on screen; the POST fails and the browser surfaces it |
| auth-required | guest → `303 /login?next=/app/settings` |
| permission-denied | n/a — the field is the caller's own account; absent for guests |
| reduced-motion | n/a (no animation) |
| untranslated | English copy; the field's content is the student's own words |
| quota-exhausted | n/a — preferences are not metered (§5.2) |
| consent-missing | n/a |

## 7. Accessibility and performance

- One `<h1>` per page; labels for every input (`test_every_settings_input…`
  pattern extended to the hub); `role="status"` for quota and save statuses;
  `role="alert"` for errors; `aria-live="polite"` on the transcript's live
  region (first line + completion, not every token); visible `:focus-visible`
  from the kit; ≥ 44 px targets for options and buttons; correctness is words
  + a rule accent, never colour alone.
- 360 px: single-column grid, full-width buttons, no horizontal overflow
  (`max-width: 46rem` block), the artifact box drops to a 4/3 aspect.
- Soft budgets: one island script + one stylesheet for the surface; no
  framework, no build step; the artifact box is fixed-aspect so streaming
  never shifts layout.

## 8. Privacy

- The transcript, weakness, and answers are C23: rendered only to the owner,
  never logged. The page tests scan the JSONL fallback sink for the student's
  words after a save + start (`PrivacyLogTests`).
- Export is the `API-PL-09` attachment; delete is hard and immediate after
  the confirm disclosure; the privacy page carries the personalized row
  (what is stored, 90-day retention, export/delete, no audio).
- No raw audio anywhere; no share links; no student text in `title` (the
  server generates titles from chapter/concept, PL1's rule).

## 9. Tests

`python -m unittest discover -s testing/backend -t .` runs
`testing/backend/test_personalized_web_pages.py` — guard (guest GET/POST →
`303`), CSRF matrix (start/end/delete/instructions), the honest states
(kill switch, quota allowance, no-coverage, ambiguous weakness, unknown
chapter), owner scoping (404 for another user's session, GET and DELETE), the
no-answer-key rule, artifact pending/ready/failed rendering, feedback
attachment, mastery summary, the 83-day warning, the settings
save/clear/rejection matrix, the log-sink redaction scan, and the a11y checks
(one `h1`, labels, live region, no inline script, no `zn-` lesson device).

`python -m unittest discover -s testing/frontend -t .` runs
`testing/frontend/test_personalized_assets.py` (asset + template contracts)
and `testing/frontend/test_personalized_session_island.py` (headless Chromium:
SSE stream rendering, the answer body + CSRF header, feedback disabling, quota
update, error card + same-id retry, offline state, artifact bridge
delegation, instructions counter).

## 10. Known debt and handoffs

| Item | Owner | Note |
|---|---|---|
| Founder visual verdict | founder (same-agent protocol) | The example-first protocol was not run for this slice; the screens follow the base system and the spec's layout sketches. Record the verdict before public launch. |
| Dashboard quick action | F3 owner | workstreams.md §5 leaves the "Learn" quick action to F3; only the nav entry landed here. |
| No-JS session turns | F11/PL follow-up | Turns need the island; without JS the transcript is readable and the check card says submitting needs JavaScript. A server-side answer route would duplicate PL2 admission and was deliberately not built. |
| Untranslated UI | UI-translation workstream | Copy is English; the shell carries the saved-language note. |
| Concept pick without JS | PL follow-up | The concept select stays disabled until a chapter is chosen; with JS it filters. The weakness field covers the same intent server-side. |
| Deck coverage for `mode='chat'` | PL follow-up | The store accepts chat sessions; the hub starts learning sessions and both render in the transcript as today. |
