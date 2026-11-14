# testing/ - the repo's test sets

| Folder | What it covers | Run from repo root |
|---|---|---|
| [`content_factory/`](content_factory/README.md) | the whole build-time pipeline: unit sets, end-to-end vs the mock inference server, and `perf/` - the weak-hardware harness (a TOOL imported by stage 08, not a test) | `python -m unittest discover -s testing/content_factory/unit -t .` |
| `frontend/` | the hand-maintained site shell: load contract, self-containment, course-list rendering, quiz + ZivonSim behaviour in real Chromium | `python -m unittest discover -s testing/frontend -t .` |
| [`observability/`](observability/README.md) | the `logging_manager` contract harness + dashboard endpoint tests: redaction guarantees, JSON schema, correlation/headers, sinks + fallback, retention/store helpers, ADR-0026 auth flows, seeded-fixture views | `python -m unittest discover -s testing/observability -t .` |
| `evals/` | unit and calibration tests for the `evals/` framework: EvalCard/Golden schemas, deterministic-first funnel, 19-sample seeded-defect reviewer calibration (`03-check` + `09-review`), regression diff engine, dual-write store + Alembic migration, and DPDP child-privacy guardrails | `python -m unittest discover -s testing/evals -t .` |
| `voice/` | the voice loop (spec: `docs/specs/voice-agent/`): frame codec, chunker, brain/STT/TTS clients, session store + credit guard, WS state machine incl. failure modes F1–F8, latency-budget contract — all on mocks (`testing/voice/mocks/`), zero network, no keys | `python -m unittest discover -s testing/voice -t .` |
| `skills/` | the deterministic skill-bundle validator (`scripts/check_skills.py`) against good/bad fixtures, growth cases for secrets, PII, links, placeholders, and duplicate names, plus per-bundle contract tests (e.g. `zivon-evals-and-observability-skills`) | `python -m unittest discover -s testing/skills -t .` |

Folder names use underscores (`content_factory`) because Python package names cannot contain hyphens; docs call it the content-factory test set.

The `content_factory` and `frontend` sets run in CI (`.github/workflows/ci.yml`, `tests` job) and need **no API keys**; `testing/evals` runs via the eval-smoke job the CI/CD owner adds to the same workflow (`python -m evals run --suite smoke --fail-on-regression`). The frontend, integration, and eval-perf sets need a browser: `python -m playwright install chromium`.

## How the static frontend is tested (verdict + method)

A static site is testable at three levels, and this repo uses all three:

1. **Contract tests** (`test_shell.py`, no browser): self-containment (no network refs), internal references resolve to real files, font licensing present.
2. **Browser behaviour tests** (`test_shell.py`, `test_behaviour_layer.py`, headless Chromium): clean load with zero console errors, the empty-catalogue contract, catalogue rendering from injected `ZIVON_COURSES` data, quiz correct/incorrect flows, loud failure of broken simulations.
3. **Performance budgets**: `evals/checkers/perf_harness.py` (re-exported at `testing/content_factory/perf/harness.py`) profiles the published golden topic pages on the `weak-android` and `mid-laptop` profiles (`EV-PERF-001`). When headless Chromium is unavailable, the hardware budget is reported as skipped — it is never replaced with fabricated FPS/load numbers.

What we deliberately do NOT do: pixel/CSS visual tests, framework-style component tests. The shell is small and hand-maintained; contract + behaviour coverage is the right weight.
