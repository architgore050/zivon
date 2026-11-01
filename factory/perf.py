"""Stage 08-perf: the Performance Engineer gate.

Runs the weak-hardware harness (testing/perf/harness.py) against the staged
topic page and the landing page. Budgets come from the profile JSON named in
config.perf.profile. A miss is fatal for the stage; stage 09 owns fixing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .errors import BudgetError, FactoryError

STAGE_ID = "08-perf"

REPO_ROOT = Path(__file__).resolve().parent.parent


def _harness():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from testing.perf.harness import run_profile  # noqa: PLC0415
    except ImportError as exc:
        raise FactoryError(
            STAGE_ID,
            f"the performance harness could not be imported ({exc}). "
            "Install playwright + psutil (`pip install -r requirements.txt`) and run "
            "`python -m playwright install chromium` once.",
        ) from exc
    return run_profile


def run(cfg: Config, run_ctx: RunContext, render_out: dict[str, Any]) -> dict[str, Any]:
    run_profile = _harness()
    profile_path = cfg.repo_path(cfg.perf["profile"])
    site = Path(render_out["site_dir"])
    topic_url = (Path(render_out["topic_dir"]) / "index.html").as_uri()
    landing_url = (site / "index.html").as_uri()

    results = {
        "profile": str(profile_path),
        "pages": {},
    }
    failures = []
    for label, url in (("topic_page", topic_url), ("landing_page", landing_url)):
        report = run_profile(url, profile_path)
        results["pages"][label] = report
        if not report["pass"]:
            failures.append(f"{label}: " + "; ".join(report["failures"]))
        run_ctx.write_json(run_ctx.stage_dir(STAGE_ID) / f"{label}.perf.json", report)

    results["pass"] = not failures
    run_ctx.save_stage_output(STAGE_ID, results)
    if failures:
        raise BudgetError(
            STAGE_ID,
            "performance budgets missed: " + " | ".join(failures) +
            " - stage 09-fixloop will attempt repairs (see its artifacts).",
        )
    return results
