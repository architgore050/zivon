# Performance budget tests — how the shell enforces its budgets in CI

Agent: SP5-FRONT · Status: SPEC of the test extension (no code in this change;
the execution agent implements it — see §6 for the CI wiring note that goes to
the CI/CD agent, since `ci.yml` is out of this agent's boundary).

Consumes: `testing/content_factory/perf/harness.py` (the weak-hardware harness,
a runtime TOOL imported by factory stage 08), `perf/profiles/weak-android.json`
+ `mid-laptop.json`, `testing/frontend/` (3-level test convention), the
founder's budget rulings (TIMELINE: loosened 2026-11-04, re-tighten at Phase 4),
the brief's binding target (page load < 2 s, ~60 fps on low-end Android).

---

## 1. The two budget eras (both binding, at different times)

The founder's ruling (TIMELINE 2026-11-03/04, recorded in the profile itself):
load/FCP budgets were loosened 3× because no generated page had been measured
under the tight numbers yet — "the perf gate must not mask the pipeline's real
timing story". fps (24 under 4× throttle ≈ 60 fps on the device) and RAM
(750 MB) stay at founder spec throughout. The brief re-states the final target.

| Metric | Era 1 — today's enforced gate | Era 2 — Phase-4 re-tighten (the brief's target) |
|---|---|---|
| page load (weak-android profile) | ≤ 6.0 s | **< 2.0 s** |
| FCP | ≤ 3.5 s | ≤ 1.2 s |
| fps under 4× CPU throttle | ≥ 24 (≈ 60 fps on device) | ≥ 24 (same) |
| browser-process RAM | ≤ 750 MB | ≤ 750 MB |
| viewport / throttle / pin | 360×640 @ dsf 2, throttle 4, 2 pinned cores | same |

Rule: **thresholds live in the profile JSON, never in test code.** Era 2 is
Phase-4 work (`weak-android.json`'s own notes say so); the test file must not
need to change when the founder re-tightens — only the JSON does.

## 2. What exists today and the gap this spec closes

| Exists | Gap |
|---|---|
| harness gates GENERATED pages inside the pipeline (stage 08) against the profiles | the SHELL (landing page) and the PUBLISHED SNAPSHOT in `frontend/courses/` are never perf-gated in CI — a shell regression ships green |
| `testing/frontend/test_shell.py` (contract + clean-load/a11y behaviour), `test_behaviour_layer.py` (quiz + ZivonSim) | no reduced-motion test, no `.zn-sim-read` mirror test, no CLS/long-task/INP assertions, no font-payload budget |
| CI `tests` job runs both frontend files (headless Chromium available) | no perf test in CI at all |

## 3. The extension: `testing/frontend/test_perf_budget.py`

One new file in the existing layout (`testing/frontend/`, underscore package,
Playwright Chromium, no new dependencies — it imports the existing harness).

### 3.1 Test inventory (names are the contract)

| Test | Asserts | Era |
|---|---|---|
| `test_landing_load_budget` | harness-driven load of `frontend/index.html` on the weak-android profile: load + FCP inside the profile's budgets | both (JSON-driven) |
| `test_published_snapshot_load_budget` | same, for each `frontend/courses/*/index.html` when a snapshot exists (skip, with the shell's own message discipline, when `courses/` is absent) | both |
| `test_sim_fps_under_throttle` | ≥ `fps_min` (24) across `sim_seconds` (3 s) for a kit-registered synthetic sim (the `test_behaviour_layer.py` synthetic-page pattern) | both |
| `test_ram_budget` | browser-process tree ≤ `ram_budget_mb` (750) | both |
| `test_no_long_tasks_blocking_input` | no main-thread task > 200 ms after load during scroll + check-click pass (INP proxy; the SEO plan's ≤ 200 ms INP rides this) | both |
| `test_cls_under_threshold` | layout shift ≤ 0.1 with fonts swapping (the woff2 migration, spec C4, must not regress this) | both |
| `test_reduced_motion_single_draw` | `prefers-reduced-motion: reduce` emulated → a registered sim's `draw` runs EXACTLY once (instrument via a counting wrapper) | era-independent |
| `test_sim_read_mirror_populated` | after `sim_seconds`, `.zn-sim-read` is non-empty (the 040410 Builder-defect class, enforced on the shell side of the contract) | era-independent |
| `test_font_payload_budget` | total transfer size of `assets/fonts/*` ≤ the profile's `font_budget_kb` (new profile key; §4) | era-gated |

### 3.2 Mechanics

- Reuse the harness as stage 08 does — `run_profile(url, profile_path)`
  (harness.py L120) returns the measured report; `_judge` (L320) already fails
  on load/FCP/RAM/fps **plus horizontal overflow > 2 px (the doctrine §10.8
  frame check) and any page/console error** — so the shell tests inherit the
  overflow + clean-load gates for free by measuring through the same instrument
  (no second harness to rot). File URLs work the way `test_shell.py` drives
  them; the harness takes any `--url`.
- Synthetic sim pattern copied from `test_behaviour_layer.py` (temp dir, real
  `zivon.js`, counting wrapper around `draw`), so the test never depends on a
  published page existing.
- Every budget read from `perf/profiles/weak-android.json`; the file grows one
  key in Era 2: `font_budget_kb` (add in the same patch as the test — profiles
  are data, tests are code).
- Failure messages name the budget, the measured value, and the profile key —
  a red build must be self-explaining (repo review principle: evidence over
  opinion).

## 4. Font payload — the concrete Era-2 blocker (finding)

Measured at BASE (`du -h frontend/assets/fonts/`):

| File | Size |
|---|---|
| BricolageGrotesque-Variable.ttf | 400 KB |
| Caveat-Variable.ttf | 396 KB |
| CourierPrime-Regular.ttf | 72 KB |
| CourierPrime-Bold.ttf | 72 KB |
| **total shipped per lesson page** | **~940 KB** |

Against a < 2 s load on a 3G-class connection this is the dominant cost — more
than the CSS (24 KB), JS (20 KB), HTML (4 KB) and a typical page.js (8 KB)
combined by two orders of magnitude. Spec C4 (spec.md §12.2) is therefore the
only realistic path inside the Era-2 budget: subset + woff2 (~70–90% smaller
for these faces [V: woff2 compression vs TTF is well-established; measure the
actual output]), keep the TTFs as fallback, `preload` Bricolage + Courier
Prime regular only, keep `FONTS-LICENSE.md` truthful. `test_font_payload_budget`
is the guardrail that makes C4 stick and prevents re-gression by a future
font drop. Era 1 keeps the current files (the loosened gate tolerates them);
`font_budget_kb` starts generous (e.g. 1000) and re-tightens with the rest.

## 5. Reduced motion — what is already true and what the test pins

- True today (verified in `zivon.js::startSim`): `prefers-reduced-motion: reduce`
  → exactly one `draw`, no rAF loop; the lesson chrome has no animation at all
  (doctrine §10.8), so the sim is the only motion source.
- `test_reduced_motion_single_draw` pins this contract so a future kit
  animation (or a Builder shortcut around the runtime) cannot silently regress
  it. Any future kit animation must gate on the same media query at the kit
  level (spec.md §10).

## 6. CI wiring (for the CI/CD agent — NOT edited by this patch series)

`integration_notes` summary, expanded: add `python -m unittest discover -s
testing/frontend -t .` ALREADY covers the new file automatically once it lands
(the `tests` job's existing discover command picks it up — no yml change
strictly required while it stays under `testing/frontend/`). If the Lighthouse
lab-vitals job from `skills/zivon-frontend-skills/seo-optimization.md` §5 is
wanted, that IS a new workflow/job — CI/CD agent's call, spec'd in
`seo-plan.md` §6. Budgets stay in JSON so no CI change is needed for the Era-2
re-tighten.

## 7. Running it locally

```bash
python -m playwright install chromium        # once
python -m unittest discover -s testing/frontend -t . -v   # everything, including the new file
```

Manual harness run against the shell (same instrument + flags the pipeline and
the new tests use):

```bash
python -m testing.content_factory.perf.harness \
    --url file:///ABS/path/to/frontend/index.html \
    --profile testing/content_factory/perf/profiles/weak-android.json \
    --out /tmp/perf-report.json            # exit 0 = pass; JSON report names every failure
```
