# Performance Budget — Hard Runtime Gates, Soft Byte Reporting (Q-4)

- **Status:** binding for `EV-PERF-001`, `07-perf`, `08-fixloop` and the frontend wave.
- **Decision:** founder Q-4 clarification, 2026-11-15 (`tmp/agent-handshake/DECISIONS-2026-11-15.md`).
- **Measured:** 2026-11-16, `weak-android` profile, headless Chromium, `file://` pages.

The 60 KB number was a **downloaded/parsed JavaScript byte budget**, not a RAM
budget, and the current site already exceeded it (58–59 KB shell JS alone,
before per-topic `i18n`). Q-4 replaces it with a **hard runtime budget** and a
**soft byte report**. Do not reintroduce a hard byte gate.

## 1. Hard budget — blocks a release

Measured by `evals/checkers/perf_harness.py` on the `weak-android` profile
(360×640, DPR 2, CPU throttle 4×, 2 cores, 24 fps floor, 750 MB RSS ceiling):

| Budget | Limit | Source |
|---|---|---|
| Interactive | ≤ **3.0 s** from navigation start to a completed synthetic input dispatch | Q-4 |
| Interaction input response (click dispatch + forced layout) | ≤ **200 ms** | Q-4 |
| Longest task on the interaction path (scroll + first check click) | ≤ **200 ms** | Q-4 |
| Animation floor | ≥ **24 fps** median under 4× throttle | existing gate |
| Page load | ≤ 6.0 s (Phase-4 target 2.0 s, advisory) | 2026-11-04 founder decision |
| FCP | ≤ 3.5 s (Phase-4 target 1.2 s, advisory) | 2026-11-04 founder decision |
| Browser RSS (whole process tree) | ≤ **750 MB** | founder spec |
| Horizontal overflow at 360 px | ≤ **2 px** | doctrine §10.8 |

A hard miss on the topic page is a **fixable** `BudgetError` routed to
`08-fixloop`; a landing-page miss is unfixable by the pipeline and stops the
run (the shared shell is hand-maintained). A miss is reported by name
(`interactive input …ms > budget 200ms (interaction path)` /
`scroll/click long task …ms > budget 200ms (interaction path)`) so the fix
target is obvious.

The **load-path** long task (a task that starts before the interaction probe)
is measured and reported as `load_longest_task_ms`, but it is **monitored, not
blocking**: Q-4's hard long-task gate names the interaction path, and a shared
CI runner adds enough scheduler noise to make a load-path assertion flaky
(2026-11-16: `class-11-physics/laws-of-motion/hi` measured 245–324 ms locally
and 463 ms on CI, while its interaction probe stayed at 130–197 ms locally; the
CI run's 432 ms "interaction" task was a late-delivered load task, which the
`start`-timestamp classification now excludes).

`run_profile()` reports **two verdicts**: `load_pass`/`load_failures` for the
pre-Q-4 load/FCP/RAM/FPS/overflow contract (what `testing/frontend`'s snapshot
sweep asserts) and `pass`/`failures` for the full contract including Q-4. The
factory stage and `EV-PERF-001` gate on `pass`; a Q-4 miss is never hidden by a
`load_pass`. `interaction_input_ms` is the page's synchronous click/layout
cost; `interaction_longest_task_ms` is the PerformanceObserver evidence for the
deferred work the click triggers (plus any host stall), and both are hard gates
under the 200 ms budget.

**Known debt (recorded 2026-11-16).** The live page
`class-11-physics/laws-of-motion/hi` (16 checks, generated before Q-4) pays
188–278 ms in its first check-click handler under 4× throttle (reproduced
locally and on CI), so it fails the Q-4 interaction gate. It is not a golden
page and predates this gate; it is gated on its next republish (P5/Q-3), where
the factory/`EV-PERF-001` verdict is hard. Until then the frontend snapshot
test asserts `load_pass`; the hard Q-4 verdict is enforced by `EV-PERF-001`
and the factory `07-perf` stage (`factory/perf.py`).

## 2. Soft budget — reported, never blocks

| Report field | Soft limit | Notes |
|---|---|---|
| `shell_js_gzip_kb` | ≤ **150 KB** | first-party shell/app JS (`zivon.js`), gzip level 9 |
| `per_topic_js_gzip_kb` | reported separately | `page.js` + the per-locale `i18n` bundle |
| `css_gzip_kb` | ≤ **50 KB** | shell + page stylesheets, gzip level 9 |

`run_profile()` writes `asset_bytes` (per-role gzip sizes, cache-busting query
strings stripped, root-relative refs resolved against the site root) and
`soft_budgets` (`within_soft_budget`, both limits). `factory/perf.py` copies
`soft_budgets` into the stage output so the dashboard and the run report can
read it. A soft miss appends an **advisory**, never a `failure`; `pass` is
unchanged. If the soft budget is exceeded by a large margin, open a
performance task — do not block the feature (Q-4).

## 3. Measured baseline (2026-11-16)

`weak-android` profile, published pages as of `main` @ `55b6033`:

| Page | interactive | input (hard) | interaction long task (hard) | load-path task (advisory) | fps | RSS | shell JS gzip | per-topic JS gzip | CSS gzip |
|---|---|---|---|---|---|---|---|---|---|
| GT-01 `class-9-physics/how-forces-affect-motion` | 0.50 s | 0.4 ms | 54 ms | 132 ms | 59.9 | 469 MB | 58.4 KB | 1.9 KB | 11.4 KB |
| GT-02 `class-11-physics/motion-in-a-straight-line` | 0.76 s | 0.4 ms | 123 ms | 174 ms | 59.9 | 490 MB | 58.4 KB | 32.9 KB | 11.3 KB |
| Landing `frontend/index.html` | 0.17 s | 0.4 ms | 0 ms | 0 ms | 59.9 | 440 MB | 58.4 KB | — | 11.3 KB |

All three pass every hard and soft budget with wide margin. **Honesty note:**
the harness loads `file://`, so load/FCP and interactive exclude network
delivery; the runtime numbers above are the *runtime* budget, and the 6.0 s /
3.5 s network budgets remain the separate gate for a served page. Load-path
tasks up to 174 ms were observed on the golden pages; they are advisory per §1.
These are single runs on a shared machine — host load moves the observer
numbers by ~2×, which is why the hard input gate uses the page's own
click/layout cost and the observer stays visible in the report.

## 4. Where the numbers live

- Profiles: `evals/goldens/profiles/{weak-android,mid-laptop}.json` (canonical)
  and the legacy mirror `testing/content_factory/perf/profiles/` (shim path).
- Harness: `evals/checkers/perf_harness.py` (`run_profile`, `_judge`,
  `measure_asset_bytes`, `_soft_budget_report`).
- Card: `EV-PERF-001` (`DET-PERF01-BUDGET-GATE`).
- Stage: `factory/perf.py` (hard gate + `soft_budgets` in the stage output).
- Tests: `testing/content_factory/unit/test_perf_profile.py`,
  `testing/evals/test_quality_gates.py`.

## 5. Revisit trigger

Re-pin the numbers when the frontend wave changes the shell's byte size by
more than 20%, when a real device measurement contradicts the emulated
profile, or at the next Phase-4 frontend pass (which tightens load/FCP toward
2.0 s / 1.2 s with measured data in hand).
