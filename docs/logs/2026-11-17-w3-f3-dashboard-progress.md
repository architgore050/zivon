# 2026-11-17 — W3 F3 dashboard and progress foundation

Branch: `feature/w3-f3-dashboard-progress` (based on `main` @ `d65b658`).

## Done

- **Progress domain** (`backend/progress/`): catalogue snapshot (DB → published
  `frontend/catalogue.json` → F0 fixture), event validation/writes, the five
  state rules, weekly rhythm (IST, last 7 days, goal 4), chapter detail,
  bookmark store, and evidence/activity decoration.
- **JSON APIs** (`backend/routes/progress.py`): `POST /v1/progress/events`
  (batch of 40, per-item rejects, no free text), `GET /v1/progress/summary`,
  `GET /v1/progress/chapters/{id}`, `GET/POST/DELETE /v1/bookmarks`. Reuses
  F0's account guard, CSRF check, and `/v1/*` rate-limit family.
- **Pages** (`web/`): real `/app` dashboard (continue, honest today plan, map
  snapshot, recent activity, weekly rhythm, counts, quick actions), new
  `/app/progress` (class → chapter → concept, rules published) and
  `/app/bookmarks`; nav gains Progress. Panel errors stay inside the page.
- **Guest sync** (`frontend/assets/app-progress.js`): reads F4's
  `zivon.progress` / `zivon.bookmarks`, folds `getProgress()` and registers
  `setProgressSink`, maps sections to concepts through `/catalogue.json`,
  merges additively with CSRF, writes per-part fingerprints, never deletes the
  device copy, and reports failure without losing data. Also removes saved
  sections through the DELETE API.
- **Styles** (`frontend/assets/app.css`): Field Notes §1–§9 app-page layout;
  360 px single-column rules; five state markers with text + shape, no colour
  only; no lesson §10 device.
- **Tests**: `testing/backend/test_progress_api.py` (17),
  `testing/backend/test_dashboard_pages.py` (10),
  `testing/frontend/test_app_progress_sync.py` (6, Playwright),
  `testing/frontend/test_app_pages_layout.py` (2, Playwright 360 px); F0C
  shell tests updated for the dashboard greeting and the Progress nav.
- **Catalogue fixture correction**: removed the stale `class-9-motion`
  placeholder from F0's tracked fixture (the published catalogue has not
  carried that topic since the P5 v9 publish), so the cluster fallback cannot
  send a student to a 404. F0's catalog test now asserts the live
  `describing-motion-around-us` entry and that `motion` stays gone.
- **Docs**: `docs/specs/frontend/dashboard-progress.md` (full contract),
  `state-matrix.md` APP-02/03/04, `web-shell.md` handoff/debt,
  `docs/specs/observability/instrumentation-map.csv` (3 progress rows) and
  the observability emitted list.

## Not done (owned elsewhere / later)

- F4's lesson-page sink push (POST on every write) — `setProgressSink` is the
  seam; F3's `/app` merge is the reliable path today.
- P1/P2 catalogue import (concept lists in the cluster; F0 fixture fallback
  has none).
- Practice/test/speaking players and their accuracy semantics (F5/F6/F7);
  SWOT (F8); settings/identity (F2).

## Next

- Review PR, then merge (review agent). After F5/F6/F7 land, revisit the
  “last 3 answers” window with their real score semantics.
