"""Stage 07-perf: the Performance Engineer gate.

Runs the weak-hardware harness (testing/content_factory/perf/harness.py) against the staged
topic page and the landing page. Budgets come from the profile JSON named in
config.perf.profile. A miss is fatal for the stage; stage 08 owns fixing.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .artifacts import RunContext
from .config import Config
from .errors import BudgetError, FactoryError

STAGE_ID = "07-perf"

REPO_ROOT = Path(__file__).resolve().parent.parent


def _harness():
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from testing.content_factory.perf.harness import run_profile
    except ImportError as exc:
        raise FactoryError(
            STAGE_ID,
            f"the performance harness could not be imported ({exc}). "
            "Install playwright + psutil (`pip install -r requirements.txt`) and run "
            "`python -m playwright install chromium` once.",
        ) from exc
    return run_profile


def run(cfg: Config, run_ctx: RunContext, render_out: dict[str, Any]) -> dict[str, Any]:
    """Gate the staged topic page and the landing page on the perf profile.

    A topic-page miss is raised as a FIXABLE BudgetError: the orchestrator
    routes it to stage 08-fixloop, which repairs page.js/page.css and retests.
    A landing-page miss is NOT fixable (the shared layer is hand-maintained)
    and stops the run immediately with instructions.
    """
    run_profile = _harness()
    profile_path = cfg.repo_path(cfg.perf["profile"])
    site = Path(render_out["site_dir"])
    topic_url = (Path(render_out["topic_dir"]) / "index.html").as_uri()
    landing_url = (site / "index.html").as_uri()

    results: dict[str, Any] = {
        "profile": str(profile_path),
        "pages": {},
    }
    for label, url in (("topic_page", topic_url), ("landing_page", landing_url)):
        report = run_profile(url, profile_path)
        results["pages"][label] = report
        run_ctx.write_json(run_ctx.stage_dir(STAGE_ID) / f"{label}.perf.json", report)

    topic_report = results["pages"]["topic_page"]
    landing_report = results["pages"]["landing_page"]
    results["pass"] = topic_report["pass"] and landing_report["pass"]
    run_ctx.save_stage_output(STAGE_ID, results)

    if not landing_report["pass"]:
        raise BudgetError(
            STAGE_ID,
            "landing page budgets missed: "
            + "; ".join(landing_report["failures"])
            + " - the landing page and shared assets are hand-maintained; fix "
            "frontend/ directly. The topic fix loop cannot repair them.",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            fixable=False,
        )
    if not topic_report["pass"]:
        raise BudgetError(
            STAGE_ID,
            "topic page budgets missed: "
            + "; ".join(topic_report["failures"])
            + " - stage 08-fixloop repairs topic-local files (include it in --stages).",
            artifacts_dir=str(run_ctx.stage_dir(STAGE_ID)),
            fixable=True,
            report=topic_report,
        )
    return results
