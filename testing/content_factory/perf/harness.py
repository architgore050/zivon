"""Backward-compatibility re-export shim (`ALIGN-PERF-SHIM`).

Canonical implementation moved to `evals/checkers/perf_harness.py` per
`docs/specs/evals/migration-map.csv` row 35. Kept so `factory/perf.py` and
`factory/fixloop.py` continue to import without breakage.
"""

from __future__ import annotations

import sys

from evals.checkers.perf_harness import (  # noqa: F401
    REQUIRED_PROFILE_KEYS,
    _browser_pid,
    _chromium_pids,
    _judge,
    _pin_browser_cores,
    _sample_fps,
    _TreeRSS,
    load_profile,
    main,
    run_profile,
)

if __name__ == "__main__":
    sys.exit(main())
