# testing/ - the repo's test sets

| Folder | What it covers | Run from repo root |
|---|---|---|
| [`content_factory/`](content_factory/README.md) | the whole build-time pipeline: unit sets, end-to-end vs the mock inference server, and `perf/` - the weak-hardware harness (a TOOL imported by stage 08, not a test) | `python -m unittest discover -s testing/content_factory/unit -t .` |
| `frontend/` | the hand-maintained site shell: load contract, self-containment, course-list rendering, quiz + ZivonSim behaviour in real Chromium | `python -m unittest discover -s testing/frontend -t .` |

Folder names use underscores (`content_factory`) because Python package names cannot contain hyphens; docs call it the content-factory test set.

All sets run in CI (`.github/workflows/ci.yml`, `tests` job) and need **no API keys**. The frontend and integration sets need a browser: `python -m playwright install chromium`.

## How the static frontend is tested (verdict + method)

A static site is testable at three levels, and this repo uses all three:

1. **Contract tests** (`test_shell.py`, no browser): self-containment (no network refs), internal references resolve to real files, font licensing present.
2. **Browser behaviour tests** (`test_shell.py`, `test_behaviour_layer.py`, headless Chromium): clean load with zero console errors, the empty-catalogue contract, catalogue rendering from injected `ZIVON_COURSES` data, quiz correct/incorrect flows, loud failure of broken simulations.
3. **Performance budgets**: `testing/content_factory/perf/harness.py` gates the landing page on the weak-android profile (run by stage 08 and manually).

What we deliberately do NOT do: pixel/CSS visual tests, framework-style component tests. The shell is small and hand-maintained; contract + behaviour coverage is the right weight.
