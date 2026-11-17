# Admin surfaces (`/admin/*`) — F10 staff cockpit

Status: implementation contract for the W5 F10 admin workstream (landed 2026-11-17,
branch `cloud/w5-f10-admin`, based on `main` @ `27897a3`). It describes the code
that exists in `dashboard/`; the F10 panels extend the admin dashboard v0
(`docs/specs/observability/dashboard-spec.md`) rather than replacing it.

The admin surface is **not part of the student web shell** —
`web-shell.md` §7: admin keeps its separate staff session and
container/surface. Visual authority for staff pages is the dashboard's own
plain system-UI sheet (`dashboard/static/dashboard.css`); the Field Notes
doctrine applies to student-facing surfaces, and §10 lesson devices are
banned here exactly as they are on `/app`.

## 1. What F10 adds

F-OPS-ADM-01 (`docs/product/features.md`) defined the founder cockpit: live
sessions, credit burn, engagement, run status, and the report inbox, behind
NEED-015. The W5 F10 scope extends the cockpit with the product-side panels a
running prototype needs: content coverage, question-bank health,
series/blueprint status, users (delete/export support only), feature flags,
eval results (ADM-10), and the content-quality debt ledger.

| Panel | Route | Serves | Data source |
|---|---|---|---|
| Overview | `/admin` | tiles for every view below + the two trigger buttons | `LogStore` aggregates |
| Factory runs | `/admin/runs`, `/admin/runs/{run_id}` | V1 (unchanged) | `log_events` + `runs/` PVC |
| Test suite | `/admin/tests` | V2 (unchanged) | kubectl Jobs + log tail |
| Voice latency | `/admin/voice` | V3 (unchanged) | `voice.turn.e2e_latency` |
| Credits | `/admin/credits` | V4 (unchanged) | `credit.counter_update` events |
| Errors | `/admin/errors` | V5 (unchanged) | `log_events` ERROR/CRITICAL |
| Publish | `/admin/publish` | V6 (unchanged) | `factory.publish.*` |
| **Content coverage** | `/admin/content` | F10 | `content_page`, `page_version`, `live_pointer`, `language_bundle`, `narration_asset` |
| **Question-bank health** | `/admin/questions` | F10 | `question_bank`, `assessment_pack`, `speaking_prompt`, `concept`, `topic_time_prior` |
| **Series / blueprint** | `/admin/series` | F10 | `test_series`, `test`, `test_question`, `assessment_pack` (exam/series kinds) |
| **Content-quality debt** | `/admin/quality` | F10 | aggregate debt queries over the same product tables + `problem_report` |
| **Users (support)** | `/admin/users` | F10 | `users` aggregates + `deletion_request` queue |
| **Report inbox** | `/admin/reports` | F10 | `problem_report` (without the free-text column) |
| **Flags & config** | `/admin/flags` | F10 | `guard_profile` + `audit_log` (flips) + documented decisions |
| **Eval results** | `/admin/evals`, `/admin/evals/{eval_run_id}` | ADM-10 | `evals_runs/` ledger + per-run `eval_report.json` |

The route table above is the route map; the JSON API (API-A1..A10 under
`/v1/admin/*`, `backend/routes/admin.py`) is unchanged — the dashboard is the
HTML front, the JSON API stays the scripted path, and both authenticate with
the same fail-closed admin token (ADR-0026, `docs/backend/adr/0026-admin-auth.md`).

## 2. Data access and honesty rules

- The product panels read the core-backend DB through `dashboard/product.py`
  (`ProductStore`): DSN from `ZIVON_PRODUCT_DSN`, falling back to
  `ZIVON_LOG_DSN` — the log store and the product tables share the backend
  database (`docs/deployment/secrets.md`), so no new service, no new
  migration, and no second credential is introduced.
- The eval panel reads the eval evidence directory (`EvalRunsStore`):
  `ZIVON_EVAL_RUNS_DIR` — `evals_runs/` in the repo, the `zivon-sources` PVC
  subPath `evals` in-cluster (written by the `eval-suite` CronJob, `k8s/52-eval-cronjob.yaml`).
  It is read-only; the panel never writes eval artifacts.
- A store that cannot be reached or that errors is rendered as a **panel
  error** (`role="alert"`), never as a fake empty table. A store that is
  simply not configured (no DSN) renders the honest empty states. This is
  the same rule `dashboard/queries.py` already applies to the log store.
- Panels ≤ 5 min lag is inherent: every view is computed at request time
  (NFR-26).

## 3. Privacy contract (binding, test-pinned)

NFR-30, F-OPS-ADM-01 AC-4, and the DPDP minimization rule all reduce to one
contract for staff panels: **aggregates and references only — never content,
never identity.**

1. Student free text never renders: `problem_report.text` is never selected;
   `speaking_attempt.transcript` is never selected. The inbox shows category
   + page/block reference + status (INF-096's zero-transcript rule generalised).
2. No account identity: emails, `user_id`, and `device_pseudo_id` never
   render on the users panel; the deletion queue shows `request_id`, scope,
   status, timestamps, and the deleted-rows counts only.
3. No learner performance anywhere: no scores, transcripts, or progress rows
   on any panel. The users panel is delete/export **support** — the flows
   themselves stay student-owned (`/privacy` deletion, `GET /v1/me/export`).
4. Question content never leaves the DB: the bank panel shows counts by
   status/type/difficulty/language/class and pack gate verdicts — never
   `prompt`, `options`, `answer`, or `explanation` columns.
5. Blueprint-only discipline is visible: the series panel shows pack counts
   and gate verdicts, never paper content (`docs/compliance/`, DEC-COMP-001).
6. The eval detail view renders card verdicts and issue counts; judge
   transcripts and issue bodies stay in the run directory (the curation
   front per `docs/specs/evals/` is the ledger + run dir + PR evidence).

`testing/observability/test_dashboard_admin.py` pins the contract both ways:
it asserts the rendered HTML excludes synthetic free-text/PII strings AND
that the executed SQL never selects the banned columns.

## 4. Write actions

The F10 panels add exactly one write: the report inbox's status change
(F-OPS-ADM-01 EARS 4, open → fixed → shipped-next-run).

- Route: `POST /admin/reports/{report_id}/status`, form field `status` +
  the session CSRF token (double-submit, ADR-0026 §5).
- Validation mirrors API-A6: the status enum is closed
  (`open`/`fixed`/`shipped_next_run`), a wrong status is `422`, an unknown
  report is `404`, a broken store answers `503`, a bad CSRF token is `403`.
- `resolved_at` is set for the two terminal statuses and cleared back to
  `NULL` when a report reopens.
- Every accepted change writes an `audit_log` row (actor `dashboard`,
  action `report.status`, before/after) — the same audit API-A6 writes —
  and emits `dashboard.report_status_changed` (L3, declared in
  `docs/specs/observability/instrumentation-map.csv`). The report text is
  never in the event fields.
- The flag panel is deliberately read-only: the guard profile toggle stays
  API-A4's POST (it is audited there); the dashboard shows the live profile
  row and the flip history but does not duplicate the control.

## 5. State matrix (SCR-ADM-01, all eleven states)

`n/a` always carries a reason; a blank cell is a defect
(`docs/specs/frontend/state-matrix.md`).

| Region | default | loading | empty | partial | error | offline | permission-denied | reduced-motion | untranslated | quota-exhausted | consent-missing |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Any F10 panel | tables/tiles from live aggregates | n/a (SSR completes before bytes; a slow DB is the panel-error path) | honest per-table empty copy naming the producer | product store down → `panel error` alert, log-store views unaffected | 503 fail-closed page when the admin token is unset | n/a (staff tool on the cluster network / port-forward) | guest → `303 /admin/login`; API client → `401` | n/a (no animation; CSS has no transitions) | staff UI is English by design (features.md SCR-ADM-01 row) | n/a (no credits are spent on staff views) | n/a (ops views are aggregates; no consent gate) |
| `/admin/content` rows | per-class counts, versions by status, live pointers, bundle/narration coverage | n/a | "no pages registered yet" / "nothing live yet" / "no bundles yet" / "no narration assets yet" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/questions` rows | bank shape by axis, pack gates, concept-coverage gaps | n/a | "bank empty — run the assessment pipeline + import" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/series` rows | six-series catalogue + exam/series packs with gate verdicts | n/a | "no series yet" / "no exam/series packs imported yet" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/quality` rows | debt tiles + failing packs + unreviewed bundles + open content reports | n/a | "no failed packs" / "every bundle is reviewed — or none exist yet" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/users` rows | account aggregates + deletion-request queue | n/a | "no active accounts yet" / "no deletion requests — the queue fills when a student clears their data" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/reports` rows | inbox rows (no text column) + status counts + filter | n/a | "inbox empty — student reports land here from the lesson page's report form" | panel error; a failed status change answers 503 with the store error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/flags` rows | live guard profile + flip history + documented decisions | n/a | "no flips recorded" / profile row missing → "guard_profile row not found" | panel error | as above | n/a | as above | n/a | n/a | n/a | n/a |
| `/admin/evals` rows | ledger runs + per-card verdicts | n/a | "no eval runs recorded yet" (with the key-free command to produce one) | evidence dir not mounted → "not mounted" honest state naming the expected path | as above | n/a | as above | n/a | n/a | n/a | n/a |

The `partial` cell is the load-bearing one: each store is a separate source,
so a product-DB outage degrades only the F10 panels while runs/voice/errors
keep rendering — the same "one panel's source down → panel error; others
fine" behaviour the features.md state matrix promises for SCR-ADM-01.

## 6. Accessibility and responsive rules

- Every table carries a `<caption>` naming the aggregate and
  `<th scope="col">` headers; the state pill always carries its word
  (`pass`/`fail`/`draft`/…), never hue alone.
- Form controls are labelled: the filter select has a visible label, the
  per-row status selects a `visually-hidden` label tied to the row.
- No inline script/style, no external assets (CSP `default-src 'self'`,
  unchanged `SECURITY_HEADERS` in `dashboard/app.py`).
- 360 px: wide tables scroll inside `.table-scroll` (`overflow-x: auto`)
  instead of stretching the page; tiles collapse to one column under 640 px;
  the nav wraps. The fix is containment, never `overflow-x: hidden` on the
  body.

## 7. Tests

`python -m unittest discover -s testing/observability -t .` runs
`testing/observability/test_dashboard_admin.py` (34 tests, key-free):
fail-closed auth on every panel, browser/API guard split, CSRF enforcement,
aggregate renders from seeded stub connections, honest empty states, the
partial-failure split (broken product store vs healthy log store), the
privacy contract (no free text/PII/performance in HTML or SQL), the report
status write (303 + audit row + event; 403/422/404/503 paths), eval ledger
seeding/torn-line tolerance/path traversal, and the a11y/responsive rules.

The instrumentation contract (`dashboard.report_status_changed`) is pinned by
`testing/observability/test_events.py` against
`docs/specs/observability/instrumentation-map.csv`.

## 8. Known debt / open items

- The flags panel documents env-side content modes from the frozen decisions
  instead of reading another pod's environment; if a runtime flag registry
  ever lands (a backend change), the panel's documented-decisions table is
  its first consumer.
- The eval evidence mount in `k8s/23-dashboard-deployment.yaml` assumes the `zivon-sources` PVC subPath
  `evals` layout `k8s/52-eval-cronjob.yaml` writes; a pod restarted before the first eval run
  shows the honest "not mounted" state until the CronJob writes evidence.
- Alert acknowledgement (dashboard-spec §4) and a Grafana link-out for the
  product-DB aggregates remain P1; the F10 panels surface conditions, they
  do not page anyone.
- Element IDs: SCR-ADM-01's inventory rows (EL-ADM-001…012) predate the F10
  panels; the new panels reuse those element contracts (tables, states,
  staff-English copy) rather than minting new IDs — the panel-to-element
  mapping above is the traceability record.
