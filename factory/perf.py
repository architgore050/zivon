"""Stage 07-perf: the Performance Engineer gate.

Runs the weak-hardware harness (testing/content_factory/perf/harness.py) against the staged
topic page and the landing page. Budgets come from the profile JSON named in
config.perf.profile. A miss is fatal for the stage; stage 08 owns fixing.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from logging_manager import ErrorClass, log_event

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


_TIME_BUDGET = re.compile(
    r"^(?P<name>\w+) (?P<measured>[\d.]+)s > budget (?P<limit>[\d.]+)s"
)
_SCORE_BUDGET = re.compile(
    r"^(?P<name>\w+) (?P<measured>[\d.]+) < minimum (?P<limit>[\d.]+)"
)


def _emit_budget_fails(run_ctx: RunContext, report: dict[str, Any]) -> None:
    """One factory.perf.budget_fail event per missed budget (the map row:
    {budget_name, measured_ms, limit_ms}, latency=measured_ms). The harness
    report's failure strings are the measured record; numbers are parsed
    back out so the dashboard can gate on them."""
    for failure in report.get("failures", []):
        text = str(failure)
        fields: dict[str, Any] = {"budget_name": text.split(" ", 1)[0]}
        latency_ms: int | None = None
        match = _TIME_BUDGET.match(text)
        if match:
            measured_ms = int(float(match.group("measured")) * 1000)
            fields["measured_ms"] = measured_ms
            fields["limit_ms"] = int(float(match.group("limit")) * 1000)
            latency_ms = measured_ms
        else:
            score = _SCORE_BUDGET.match(text)
            if score:
                fields["measured"] = float(score.group("measured"))
                fields["limit"] = float(score.group("limit"))
        log_event(
            "factory.perf.budget_fail",
            fields,
            latency_ms=latency_ms,
            run_id=run_ctx.run_id,
            stage=STAGE_ID,
            error_class=ErrorClass.GATE_FAIL,
        )


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
        _emit_budget_fails(run_ctx, landing_report)
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
        _emit_budget_fails(run_ctx, topic_report)
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
