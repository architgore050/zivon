# SWOT — strengths, weaknesses, opportunities, threats (F8)

Status: implementation contract for the W5 F8 slice (branch
`cloud/w5-f8-swot`, based on `main` @ `27897a3`). It describes code that
exists: `backend/swot/`, `backend/routes/swot.py`, `backend/config.py`
(`ZIVON_SWOT_MODE`), `web/swot_views.py`, `web/routes/swot.py`, the two app
templates, the `SWOT` nav entry, the dashboard snapshot panel in
`web/templates/app/dashboard.html`, and `frontend/assets/app.css` (`.swot-*`).

Consumes: `docs/specs/frontend/web-shell.md` (route/guard/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base system only; no §10 lesson
device), `docs/backend/db-spec.md` §4.18–§4.19, the F3 progress read model
(`docs/specs/frontend/dashboard-progress.md`), the F5/F6/F7 learner tables,
and the A5 time-prior contract (`docs/content-factory/assessment.md` §6).
The frozen requirements live in the full-frontend plan §13 (workspace-local);
the screen method is worked through in
`skills/zivon-frontend-product-skills/references/worked-example.md` part A.

Out of scope and owned elsewhere: practice (F5), speaking (F6), tests/series
(F7), admin (F10). SWOT changes no practice/test UI, adds no paywall, and
calls no model.

## 1. Routes and code paths

| Route | Surface | Code |
|---|---|---|
| `/app/swot` | SSR 2×2 grid, auth required | `web/routes/swot.py`, `web/templates/app/swot.html` |
| `/app/swot/how` | SSR explainability page | `web/routes/swot.py`, `web/templates/app/swot_how.html` |
| `/v1/swot` | JSON, GET | `backend/routes/swot.py` |
| `/v1/swot/explain` | JSON, GET | same |

Both pages extend `base.html`, load `/assets/product.css` then
`/assets/app.css`, and need no island: SSR completes before bytes, and the
panel error is a rendered notice, not a spinner. The nav gains `SWOT`
between `Progress` and `Speak` (`web/nav.py`); the dashboard gains a
snapshot panel and a `SWOT` quick action. The pages are `noindex`,
`no-store`, and render no `zn-` lesson class.

## 2. What SWOT computes

Per chapter of the student's own catalogue (F3's snapshot: database →
published → fixture; live and lesson_only chapters only), from the student's
own rows plus two bounded chapter-level references:

- **Evidence**: `progress_event` (`practice_answer` with correct/hints/time
  and `question_id`, `test_submit` with per-chapter correct/answered/total,
  lesson events), the `speaking_attempt` table joined to `speaking_prompt`
  for the chapter (F6 never writes a speaking progress event), and
  `lesson_progress` counters.
- **Coverage**: the share of the chapter's served `question_bank` items the
  student has attempted (distinct question ids from progress events and the
  student's own practice rows). When the bank is empty the section counter
  (`blocks_seen` / `blocks_total`) is the denominator; when neither exists
  the chapter is honestly unrated ("coverage is unknown"), never guessed.
- **Recency**: every observation is weighted `0.5 ** (age_days / 21)` — a
  **21-day half-life** (`HALF_LIFE_DAYS`).
- **Trend**: the last **14 days** of accuracy against the student's older
  answers for the same chapter (`up` at ≥ +5 pts, `down` at ≤ −5, otherwise
  `steady`; no trend when fewer than 3 recent items or no baseline).
- **Pace**: the student's weighted mean answer time over the **effective
  time prior** — the A5 AI prior (`topic_time_prior`, scope `chapter`)
  refined by an **EWMA of all-student observed times** (`practice_attempt`,
  chronological, `PRIOR_EWMA_ALPHA = 0.3`, each observation capped at
  **3× the AI prior** — or the A5 300 s maximum when no prior exists — so
  one stalled attempt cannot move it). Until 5 capped observations exist the
  AI prior stands alone; the A5 prior is **never recomputed from history**
  (the materialized rollup db-spec Q13 reserves for SWOT remains future
  work — no migration in this slice).
- **Exam weight** (`syllabus_chapter.exam_weight`): priority inside a
  quadrant and an IMP marker at ≥ `EXAM_WEIGHT_IMP_MIN` (1.0). It is **not**
  a fifth quadrant. Real weights arrive with P3's blueprint; today the
  column is NULL everywhere, so no chapter is IMP — honestly.

## 3. Placement rules (rules version 1, formula `swot-v1`)

- A chapter is **rated** with ≥ 3 scored items (practice answers + test
  submits + scored explain-backs) and both axes measurable.
- **Performance axis**: recency-weighted accuracy (practice answers as
  0/1, a test submit as correct/answered). Speaking does not move accuracy —
  it is its own evidence line, exactly as in F3.
- **Coverage axis**: attempt rate (or the section counter fallback).
- **Relative mode (default, frozen)**: median split across the student's own
  rated chapters — performance ≥ median × coverage ≥ median →
  **Strength**; low performance × high coverage → **Weakness** (effort
  without results); high performance × low coverage → **Opportunity**
  (strong where touched, ground not covered); low × low → **Threat** (a
  watch-out, not a prediction).
- **Fewer than 3 rated chapters → no claim**: the page shows "Not enough
  data yet" and every chapter stays in the unrated row. Nothing is placed on
  a two-chapter median.
- **Absolute mode (dormant)**: `SWOT_MODE=absolute` replaces the medians
  with the fixed thresholds `ABSOLUTE_PERFORMANCE_HIGH_PCT = 75` and
  `ABSOLUTE_COVERAGE_HIGH_PCT = 60`. Implemented and tested, off by default,
  and never a student setting — see §8 (admin calibration note).
- **Order inside a quadrant**: IMP/board-weight first, then heavier exam
  weight, then the sharpest card (lowest performance in Weakness/Threat,
  highest in Strength/Opportunity), then chapter number.
- No ability score, no ranking, no comparison with another student, no
  parent/share/public surface. Account deletion cascades the evidence
  (F0 tables), so the SWOT goes with it.

## 4. JSON contracts

### 4.1 `GET /v1/swot`

```json
{
  "schema_version": 1, "rules_version": 1, "formula_version": "swot-v1",
  "mode": "relative", "generated_at": "…Z",
  "is_new": false, "enough_data": true,
  "rated_chapter_count": 3, "rated_min_chapters": 3,
  "quadrants": {"strength": [card], "weakness": [card],
                "opportunity": [card], "threat": [card]},
  "unrated": [card],
  "medians": {"performance_pct": 100.0, "coverage_pct": 55.6} | null,
  "snapshot": {"strength": card | null, "weakness": …,
               "opportunity": …, "threat": …},
  "rules": {"version": 1, "half_life_days": 21.0, "trend_window_days": 14,
            "rated_min_items": 3, "enough_data_min_chapters": 3,
            "exam_weight_imp_min": 1.0, "…"}
}
```

A **card** carries `chapter_id`, `title`, `class_level`, `chapter_no`,
`lesson_url`, `quadrant`, `rated`, `exam_weight`, `exam_priority`, `metrics`
(`weighted_accuracy_pct`, `coverage_pct`, `attempt_rate_pct`, `hint_rate`,
`time_ratio`, `speaking_score_pct`, `trend`, `scored_items`,
`last_activity_at`, `confidence`), **2–3 evidence bullets** (plain language,
pace included when it exists — "Taking about 2.1× the expected time per
answer — an exam-pace risk."), and **one next action** (`{text, url}`) whose
URL is always a live route (`/app/practice?chapter=…`, the lesson, or
`/app/progress`). An unrated card carries an honest `unrated_reason`.

### 4.2 `GET /v1/swot/explain`

The `/v1/swot` payload plus `method` (six numbered plain-language steps),
`metric_definitions` (name + one-sentence meaning for all seven metrics),
and `chapters` (every chapter with its quadrant, metrics, and unrated
reason). The `/app/swot/how` page renders exactly this.

Both routes: F0 account guard (`require_context`), GET (no CSRF write
check), `Cache-Control: no-store`, the global `/v1/*` rate-limit family
(30/min per IP hash), and no second limiter. The payload never contains the
user id, email, or session id. A store failure answers `503
E-SERVICE-UNAVAILABLE` after logging `swot.compute.failed` — nothing is
invented to fill a grid.

## 5. Dashboard snapshot (`/app`)

One panel between "Physics map" and "Recent activity": **SWOT snapshot** —
one strength / weakness / opportunity / threat line each (chapter title +
first evidence line + IMP marker when applicable), an honest "Not enough
data yet" line before the grid exists, an unavailable line when the
computation fails, and a link to `/app/swot`. The dashboard view model calls
`build_dashboard_snapshot` (`web/swot_views.py`), which never raises: a
failure degrades the panel only, never the F3 dashboard. F3's own tests keep
passing unchanged except the deliberate dead-link row: `/app/swot` moved
from the "not live yet" list to the live-link assertions in the same PR that
landed the route.

## 6. Logging

| Event | Severity | Fields | Emitter |
|---|---|---|---|
| `swot.view.served` | INFO | `mode`, `rated_count`, `unrated_count`, `enough_data` | `backend/routes/swot.py` |
| `swot.explain.served` | INFO | same | `backend/routes/swot.py` |
| `swot.snapshot.served` | INFO | `mode`, `enough_data` | `web/swot_views.py` |
| `swot.compute.failed` | WARNING | `reason_code` (error_class `store_error`) | `backend/routes/swot.py` |

Rows live in `docs/specs/observability/instrumentation-map.csv` (component
`swot`, privacy class L2 — counts and enums only, never a chapter id, user
id, or metric value) and `testing/observability/test_events.py` pins them.
The three client analytics events in the frozen plan (`swot_view`,
`swot_card_open`, `swot_action`) are **not emitted in this slice**: they go
through `/api/v1/events`, whose `VALID_EVT_IDS` whitelist is a shared
contract with F3's four deferred client events (same reason, same owner).
The page's server-side events above already record the view.

## 7. States, a11y, mobile, privacy

| State | `/app/swot` | `/app/swot/how` |
|---|---|---|
| default | 2×2 grid + unrated row + rules disclosure | method + medians + per-chapter table |
| loading | n/a (SSR completes before bytes) | n/a |
| empty (new user) | "Not enough data yet" + Start-a-practice action | method + "no medians yet" + empty-table copy |
| partial | some chapters unrated in their own row, never forced into a box | "Not rated" rows in the table |
| error | panel notice + retry + progress-map link; greeting-free but framed | panel notice + retry |
| offline | n/a server-side (navigation is the browser's offline page) | same |
| permission-denied | guest is 303 `/login?next=/app/swot` | same |
| reduced-motion | no animation anywhere on the page | same |
| untranslated | English copy; the shell's saved-language note covers the frame | same |
| quota-exhausted | n/a (SWOT spends no credits) | n/a |
| consent-missing | n/a (SWOT never uses the mic) | n/a |

- Quadrants are **words, never colour**: each box carries its heading, its
  one-line meaning, and an ink border; the IMP marker is a bordered word.
- One `main`, one `h1`, `aria-labelledby` on every section, native
  `<details>` for the rules, ≥ 40 px interactive rows.
- **360 px**: the grid collapses to one column (Strengths → Weaknesses →
  Opportunities → Threats, heading repeated per block), the card head
  stacks, the wide explainability table scrolls inside its own wrapper —
  `testing/frontend/test_swot_pages_layout.py` asserts the frame in
  Chromium.
- No email, user id, or session id in HTML; no parent view, share link,
  public profile, or leaderboard anywhere in the payload or the page.

## 8. Admin calibration note (IMP, thresholds, and the dormant mode)

For the operator; nothing here is a student setting.

- **SWOT_MODE** (`ZIVON_SWOT_MODE`, values `relative|absolute`, default
  `relative`, validated at boot): the relative median split is the frozen
  product behaviour. The absolute thresholds (75 % performance, 60 %
  coverage) are **implemented placeholders** kept dark until they are
  calibrated against a real cohort — the numbers behind "strong" must come
  from observed distributions (P3's blueprint plus the first cohort's
  `chapter_stat` rollup), not from this PR's judgement. Calibrate by running
  the explain payload across anonymized aggregates, fixing the two constants
  in `backend/swot/stats.py`, and recording the decision; flipping the env
  var alone is not a calibration.
- **IMP threshold** (`EXAM_WEIGHT_IMP_MIN = 1.0`): exam weights are NULL
  today (`pending_p3_blueprint` — P3 owns the real CBSE blueprint weights).
  When P3 lands them, revisit what "board-heavy" means in their scale
  before any student sees an IMP marker; the marker is a priority order +
  a word, never a score.
- **Time prior** (`PRIOR_MIN_OBSERVATIONS = 5`, `PRIOR_EWMA_ALPHA = 0.3`,
  outlier cap 3× prior): these are prototype-honest constants for the
  all-student EWMA. The bounded-window EWMA is the documented incremental
  shape; the eventual materialized rollup (db-spec Q13) replaces the
  request-time read. Tune only with recorded evidence.
- Everything the copy renders is published from `rules()` in the payload —
  the student-facing "How this works" page and this doc stay true without
  reading the code.

## 9. Tests

| Suite | Command | Covers |
|---|---|---|
| Rules (pure) | `python -m unittest testing.backend.test_swot_stats` | half-life weights, median split + quadrants, <3-chapters rule, absolute mode, IMP ordering, trend windows, EWMA + outlier cap, evidence/action shape, bank coverage |
| API + pages | `python -m unittest testing.backend.test_swot_api` | guest 401, user scoping, empty/new/partial states, speaking join, explain payload, absolute config, invalid-mode boot refusal, SSR states, noindex/no-PII/no-lesson-devices, nav + dashboard snapshot, failure degradation |
| F3 regression | `python -m unittest testing.backend.test_dashboard_pages` | dashboard unchanged apart from the deliberate SWOT-snapshot assertions |
| Layout | `python -m unittest testing.frontend.test_swot_pages_layout` | 360 px frame, stacked quadrants, touch targets, table scroll, clean console |
| Observability | `python -m unittest discover -s testing/observability -t .` | map rows resolve for the four `swot.*` events |

All key-free and offline; no model call exists on this path. No migration
ships in this slice: every query reads existing §4.18/§4.19 tables, and each
new read path degrades to "no data" when the pack import has not landed.

## 10. Known debt / next

- The `VALID_EVT_IDS` client-analytics extension (`swot_view`,
  `swot_card_open`, `swot_action`) waits on the shared event-contract owner,
  together with F3's four deferred client events (§6).
- Exam weights stay NULL until P3's blueprint (§8); the IMP marker is
  invisible in every environment until then — honest, not broken.
- `coverage_pct` leans on the served `question_bank` count; where the
  import has not landed, the section counter is the denominator and a
  chapter with practice answers but no lesson coverage is unrated with its
  reason shown, never guessed.
- The all-student time EWMA reads at most `TIME_SAMPLE_LIMIT` (200) rows per
  chapter, capped to the student's own practice chapters per request; the
  materialized rollup (db-spec Q13) is the scaling fix and stays future
  work.
- `/app/swot/how` is English-only like every other shell page (UI
  translation is its own workstream).
