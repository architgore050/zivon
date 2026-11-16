"""Weak-hardware performance harness & `EV-PERF-001` deterministic checkers.

Canonical home migrated from `testing/content_factory/perf/harness.py` per
`docs/specs/evals/migration-map.csv` row 35 (`ALIGN-PERF-SHIM`).

Simulates a low-end Android phone on a real Chromium instance:
- CPU throttling via CDP (Emulation.setCPUThrottlingRate) - each JS op costs N x
- optional CPU affinity restriction (pin the browser to N cores; Linux)
- RAM measured as the peak RSS of the whole Chromium process tree (psutil)
- load budget from wall-clock time around page.goto(wait_until="load")
- FCP/LCP from PerformanceObserver (init script, buffered entries)
- FPS sampled from requestAnimationFrame deltas during scripted interactions
- console errors and page errors fail the run outright
"""

from __future__ import annotations

import argparse
import gzip
import json
import re
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

from ..config import EvalConfig
from ..models import EvalCard, IssueRecord

REQUIRED_PROFILE_KEYS: dict[str, Any] = {
    "viewport_width": int,
    "viewport_height": int,
    "device_scale_factor": (int, float),
    "cpu_throttle_rate": (int, float),
    "ram_budget_mb": (int, float),
    "load_budget_s": (int, float),
    "fcp_budget_s": (int, float),
    "fps_min": (int, float),
    # Q-4 hard runtime budget: the page must answer input within this window
    # (weak-android), and no single long task on load/scroll/click may exceed
    # `long_task_budget_ms`. Bytes are SOFT (reported, never blocking).
    "interactive_budget_s": (int, float),
    "long_task_budget_ms": (int, float),
    "soft_js_gzip_kb": (int, float),
    "soft_css_gzip_kb": (int, float),
    "sim_seconds": (int, float),
    "pin_cores": (int, type(None)),
    "scroll": bool,
    "click_checks": bool,
}

# Phase-4 frontend tightening targets (A-EVAL-03 in open-questions.md)
PHASE_4_LOAD_TARGET_S = 2.0
PHASE_4_FCP_TARGET_S = 1.2


# Chromium launch args for the perf stage. The pages under test load from
# file://, where Chromium gives the document an opaque origin and blocks
# CORS-required subresources - the hand-maintained shell's font preloads and
# @font-face woff2 files - exactly like a cross-origin fetch. Production
# serves the same files over HTTP(S) where they load normally, so the flag
# restores production-load semantics for the measurement; it is a
# test-transport concern only and must never appear in product code.
CHROMIUM_LAUNCH_ARGS = ["--allow-file-access-from-files"]


def load_profile(path: str | Path) -> dict[str, Any]:
    profile = json.loads(Path(path).read_text(encoding="utf-8"))
    for key, types in REQUIRED_PROFILE_KEYS.items():
        if key not in profile:
            raise ValueError(f"profile {path}: missing key '{key}'")
        if not isinstance(profile[key], types) or (
            isinstance(profile[key], bool) and types is not bool
        ):
            raise ValueError(
                f"profile {path}: '{key}' has wrong type, expected {types}"
            )
    return profile


class _TreeRSS:
    """Peak RSS of a process tree, sampled in the background."""

    def __init__(self, root_pid: int):
        import psutil

        self._psutil = psutil
        self._root = psutil.Process(root_pid)
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def _tree_rss_mb(self) -> float:
        procs = [self._root, *self._root.children(recursive=True)]
        total = 0
        for p in procs:
            try:
                total += p.memory_info().rss
            except (self._psutil.NoSuchProcess, self._psutil.AccessDenied):
                continue
        return total / (1024 * 1024)

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.peak_mb = max(self.peak_mb, self._tree_rss_mb())
            except self._psutil.NoSuchProcess:
                break
            time.sleep(0.1)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> float:
        self.peak_mb = max(self.peak_mb, self._tree_rss_mb())
        self._stop.set()
        self._thread.join(timeout=2)
        return self.peak_mb


def _pin_browser_cores(psutil: Any, proc: Any, cores: list[int]) -> None:
    try:
        proc.cpu_affinity(cores)
        for child in proc.children(recursive=True):
            child.cpu_affinity(cores)
    except (AttributeError, psutil.AccessDenied, OSError) as exc:
        raise RuntimeError(
            f"could not pin browser to cores {cores}: {exc}. "
            "Set pin_cores to null in the profile to skip core pinning."
        ) from exc


def run_profile(url: str, profile_path: str | Path) -> dict[str, Any]:
    profile = load_profile(profile_path)
    from playwright.sync_api import sync_playwright

    report: dict[str, Any] = {
        "url": url,
        "profile": str(profile_path),
        "viewport_width": profile["viewport_width"],
        "budgets": {
            "load_s": profile["load_budget_s"],
            "fcp_s": profile["fcp_budget_s"],
            "ram_mb": profile["ram_budget_mb"],
            "fps_min": profile["fps_min"],
            "interactive_s": profile["interactive_budget_s"],
            "long_task_ms": profile["long_task_budget_ms"],
        },
        "measured": {},
        "asset_bytes": {},
        "soft_budgets": {},
        "console_errors": [],
        "page_errors": [],
        "failures": [],
        "advisories": [],
        "pass": False,
    }

    with sync_playwright() as p:
        existing = _chromium_pids()
        browser = _launch(p)
        try:
            browser_pid = _browser_pid(existing)
            rss = _TreeRSS(browser_pid) if browser_pid else None
            if rss:
                rss.start()

            context = browser.new_context(
                viewport={
                    "width": profile["viewport_width"],
                    "height": profile["viewport_height"],
                },
                device_scale_factor=profile["device_scale_factor"],
                is_mobile=True,
            )
            page = context.new_page()
            page.on(
                "console",
                lambda msg: (
                    report["console_errors"].append(msg.text)
                    if msg.type == "error"
                    else None
                ),
            )
            page.on("pageerror", lambda err: report["page_errors"].append(str(err)))

            cdp = context.new_cdp_session(page)
            cdp.send(
                "Emulation.setCPUThrottlingRate", {"rate": profile["cpu_throttle_rate"]}
            )

            if profile["pin_cores"]:
                import psutil

                proc = psutil.Process(browser_pid)
                _pin_browser_cores(psutil, proc, list(range(profile["pin_cores"])))

            # First-visit consent (§10.14) is chrome, not lesson content, and
            # its "declined" state is the pure-reading budget target. Set it
            # before load so no gate/PUT request pollutes the measurement.
            page.add_init_script(
                "try { localStorage.setItem('zivon.consent', 'declined'); } catch (e) {}"
            )
            page.add_init_script("""
                window.__zivonPerf = {fcp: null, lcp: null, longtasks: []};
                try {
                  new PerformanceObserver((list) => {
                    for (const e of list.getEntries()) {
                      if (e.name === 'first-contentful-paint') window.__zivonPerf.fcp = e.startTime;
                    }
                  }).observe({type: 'paint', buffered: true});
                  new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    if (entries.length) {
                      window.__zivonPerf.lcp = entries[entries.length - 1].startTime;
                    }
                  }).observe({type: 'largest-contentful-paint', buffered: true});
                  new PerformanceObserver((list) => {
                    for (const e of list.getEntries()) {
                      window.__zivonPerf.longtasks.push({start: e.startTime, duration: e.duration});
                    }
                  }).observe({type: 'longtask', buffered: true});
                } catch (e) {}
            """)

            t0 = time.time()
            page.goto(url, wait_until="load", timeout=60000)
            load_s = time.time() - t0

            overflow_px = page.evaluate(
                "Math.max(0, document.documentElement.scrollWidth - window.innerWidth)"
            )

            # Interaction latency: how long after navigation start the synthetic
            # click lands, and how long the page's own handler + forced layout
            # takes (the input-response cost a student feels). The delta is the
            # Q-4 hard signal; PerformanceObserver long-task entries are
            # reported separately because on a shared CI runner they catch
            # host/OS stalls that a blank page exhibits too (2026-11-16: the
            # same page measured 0 ms and 287 ms in consecutive runs while its
            # click/scroll input cost stayed at 5-10 ms).
            interactive = page.evaluate("""
                () => {
                  const el = document.querySelector(
                    '.zn-check-btn, .zn-sim-canvas, canvas, button, a, body'
                  );
                  const t0 = performance.now();
                  if (el) {
                    try {
                      el.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
                    } catch (e) {}
                    void el.getBoundingClientRect();
                  }
                  const t1 = performance.now();
                  return {at: t1, input_ms: t1 - t0};
                }
            """)
            interactive_ms = float(interactive.get("at", 0.0))
            interaction_input_ms = float(interactive.get("input_ms", 0.0))
            # Classify long tasks by their real start time, not by array index:
            # a PerformanceObserver entry arrives a task later, so a load-path
            # task can be delivered after the click probe and be miscounted as
            # an interaction task (the CI runner showed exactly that).
            interaction_start_ms = float(page.evaluate("() => performance.now()"))
            fps = _sample_fps(page, profile)
            longtasks = page.evaluate("() => window.__zivonPerf.longtasks || []")

            metrics = cdp.send("Performance.getMetrics")
            js_heap_mb = 0.0
            for m in metrics["metrics"]:
                if m["name"] == "JSHeapUsedSize":
                    js_heap_mb = m["value"] / (1024 * 1024)

            peak_rss = rss.stop() if rss else 0.0
            perf_obj = page.evaluate("window.__zivonPerf || {}")

            longest_task_ms = round(
                max((float(t.get("duration", 0.0)) for t in longtasks), default=0.0),
                1,
            )
            load_tasks = [
                t
                for t in longtasks
                if float(t.get("start", 0.0)) < interaction_start_ms
            ]
            load_task_ms = round(
                max((float(t.get("duration", 0.0)) for t in load_tasks), default=0.0),
                1,
            )
            interaction_tasks = [
                t
                for t in longtasks
                if float(t.get("start", 0.0)) >= interaction_start_ms
            ]
            scroll_task_ms = round(
                max(
                    (float(t.get("duration", 0.0)) for t in interaction_tasks),
                    default=0.0,
                ),
                1,
            )
            report["measured"] = {
                "load_s": round(load_s, 2),
                "fcp_s": round((perf_obj.get("fcp") or 0) / 1000, 2),
                "lcp_s": round((perf_obj.get("lcp") or 0) / 1000, 2),
                "interactive_s": round(float(interactive_ms) / 1000, 2),
                "interaction_input_ms": round(interaction_input_ms, 1),
                "fps_median": round(fps, 1) if fps else None,
                "longest_task_ms": longest_task_ms,
                "load_longest_task_ms": load_task_ms,
                "interaction_longest_task_ms": scroll_task_ms,
                "long_tasks_total": len(longtasks),
                "peak_browser_rss_mb": round(peak_rss, 1),
                "js_heap_mb": round(js_heap_mb, 2),
                "overflow_px": int(overflow_px),
                "cpu_throttle_rate": profile["cpu_throttle_rate"],
            }
            report["asset_bytes"] = measure_asset_bytes(url)
            report["soft_budgets"] = _soft_budget_report(
                report.get("asset_bytes") or {},
                profile["soft_js_gzip_kb"],
                profile["soft_css_gzip_kb"],
            )
        finally:
            browser.close()

    _judge(report)
    return report


def _launch(playwright: Any) -> Any:
    """Launch Chromium with the perf stage's file-access args (see above).

    The args list is copied: Playwright may retain and even mutate the list,
    which must never leak back into the module constant.
    """
    return playwright.chromium.launch(headless=True, args=list(CHROMIUM_LAUNCH_ARGS))


def _chromium_pids() -> set[int] | None:
    """All chrome/chromium pids currently on the machine (None: no psutil)."""
    try:
        import psutil
    except ImportError:
        return None
    if psutil is None:
        return None
    pids: set[int] = set()
    for proc in psutil.process_iter(["name"]):
        try:
            name = (proc.info["name"] or "").lower()
            if name.startswith(("chrome", "chromium")):
                pids.add(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def _browser_pid(existing: set[int] | None) -> int | None:
    """Identify the main chromium process spawned by THIS launch."""
    if existing is None:
        return None
    try:
        import psutil
    except ImportError:
        return None
    if psutil is None:
        return None
    fallback: int | None = None
    new_pids = (_chromium_pids() or set()) - existing
    for pid in new_pids:
        try:
            cmdline = " ".join(psutil.Process(pid).cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        if "--type=" not in cmdline and "--headless" in cmdline:
            return pid
        if fallback is None or pid < fallback:
            fallback = pid
    return fallback


def _sample_fps(page: Any, profile: dict[str, Any]) -> float | None:
    if profile["scroll"]:
        page.mouse.move(5, 5)
        for _ in range(6):
            page.mouse.wheel(0, 240)
            page.wait_for_timeout(120)
    if profile["click_checks"]:
        buttons = page.locator(".zn-check-btn")
        if buttons.count():
            buttons.first.click()
            page.wait_for_timeout(200)
    has_canvas = page.locator("canvas.zn-sim-canvas").count() > 0
    watch_seconds = profile["sim_seconds"] if has_canvas else 1.0
    deltas = page.evaluate(f"""
        (async () => {{
          const stamps = [];
          const start = performance.now();
          await new Promise((resolve) => {{
            function tick(now) {{
              stamps.push(now);
              if ((now - start) / 1000 >= {watch_seconds}) resolve();
              else requestAnimationFrame(tick);
            }}
            requestAnimationFrame(tick);
          }});
          const deltas = [];
          for (let i = 1; i < stamps.length; i++) deltas.push(stamps[i] - stamps[i - 1]);
          return deltas;
        }})()
    """)
    if not deltas:
        return None
    median_ms = statistics.median(deltas)
    return 1000.0 / median_ms if median_ms > 0 else None


def measure_asset_bytes(url: str) -> dict[str, Any]:
    """Gzip size of the page's first-party JS/CSS, split by role (Q-4 soft).

    Reports, never blocks:
    - `shell_js`  = the shared shell/app bundle (`zivon.js`)
    - `page_js`   = the topic's own `page.js`
    - `i18n_js`   = the topic's per-locale string bundle
    - `css`       = shell + page stylesheets

    Only local `file://` pages are measurable this way; a remote URL returns
    `{"measured": False}` rather than inventing numbers.
    """
    from urllib.parse import unquote, urlparse

    parsed = urlparse(url)
    if parsed.scheme != "file":
        return {"measured": False, "reason": "not a local file:// page"}
    page_path = Path(unquote(parsed.path))
    if not page_path.is_file():
        return {"measured": False, "reason": f"page not found: {page_path}"}
    html = page_path.read_text(encoding="utf-8", errors="replace")
    refs = [
        *re.findall(
            r"""<script\b[^>]*\bsrc\s*=\s*["']([^"']+)["']""", html, re.IGNORECASE
        ),
        *re.findall(
            r"""<link\b[^>]*\brel\s*=\s*["']stylesheet["'][^>]*\bhref\s*=\s*["']([^"']+)["']""",
            html,
            re.IGNORECASE,
        ),
        *re.findall(
            r"""<link\b[^>]*\bhref\s*=\s*["']([^"']+\.css)["'][^>]*\brel\s*=\s*["']stylesheet["']""",
            html,
            re.IGNORECASE,
        ),
    ]
    budgets: dict[str, float] = {
        "shell_js": 0.0,
        "page_js": 0.0,
        "i18n_js": 0.0,
        "css": 0.0,
    }
    counted: set[Path] = set()
    for ref in refs:
        if ref.startswith(("http://", "https://", "//", "data:")):
            continue
        # Cache-busting query strings and fragments are not part of the path.
        clean = ref.split("?", 1)[0].split("#", 1)[0]
        candidates = [(page_path.parent / clean).resolve()]
        if clean.startswith("/"):
            # Root-relative refs resolve against the site root: the nearest
            # ancestor that actually contains the file.
            candidates = [
                (parent / clean.lstrip("/")).resolve()
                for parent in [page_path.parent, *page_path.parent.parents]
            ]
        target = next((c for c in candidates if c.is_file()), None)
        if target is None or target in counted:
            continue
        counted.add(target)
        try:
            size = len(gzip.compress(target.read_bytes(), compresslevel=9))
        except OSError:
            continue
        name = target.name
        parts = target.parts
        if name.endswith(".css"):
            budgets["css"] += size / 1024
        elif name == "zivon.js":
            budgets["shell_js"] += size / 1024
        elif name == "page.js":
            budgets["page_js"] += size / 1024
        elif "i18n" in parts or name.startswith("i18n"):
            budgets["i18n_js"] += size / 1024
    out: dict[str, Any] = {"measured": bool(counted), "files": len(counted)}
    for key, kb in budgets.items():
        out[f"{key}_gzip_kb"] = round(kb, 2)
    return out


def _soft_budget_report(
    asset_bytes: dict[str, Any], js_budget_kb: float, css_budget_kb: float
) -> dict[str, Any]:
    """Q-4 soft byte report: measured sizes and pass/fail against the soft
    budget. The result is advisory only - it never reaches `failures`."""
    shell = float(asset_bytes.get("shell_js_gzip_kb", 0.0))
    topic = float(asset_bytes.get("page_js_gzip_kb", 0.0)) + float(
        asset_bytes.get("i18n_js_gzip_kb", 0.0)
    )
    css = float(asset_bytes.get("css_gzip_kb", 0.0))
    return {
        "measured": bool(asset_bytes.get("measured")),
        "shell_js_gzip_kb": round(shell, 1),
        "per_topic_js_gzip_kb": round(topic, 1),
        "css_gzip_kb": round(css, 1),
        "detail_gzip_kb": {
            "shell_js": round(shell, 2),
            "page_js": round(float(asset_bytes.get("page_js_gzip_kb", 0.0)), 2),
            "i18n_js": round(float(asset_bytes.get("i18n_js_gzip_kb", 0.0)), 2),
            "css": round(css, 2),
        },
        "soft_js_budget_kb": float(js_budget_kb),
        "soft_css_budget_kb": float(css_budget_kb),
        "within_soft_budget": shell <= js_budget_kb and css <= css_budget_kb,
    }


def _judge(report: dict[str, Any]) -> None:
    """Score one harness run.

    Two verdicts on purpose:

    - `load_pass` / `load_failures` - the pre-Q-4 budgets (load, FCP, RAM,
      FPS, overflow, console/page errors). `testing/frontend` keeps asserting
      this contract for the whole published snapshot.
    - `pass` / `failures` - everything `load_pass` covers **plus** the Q-4
      runtime gates (interactive <= 3 s, input response <= 200 ms, no long task
      > 200 ms on the interaction path). The factory stage and `EV-PERF-001`
      gate on this stricter verdict.

    Both lists are always reported, so a Q-4 miss is never hidden by the
    legacy assertion.
    """
    m = report["measured"]
    budgets = report["budgets"]
    load_failures: list[str] = []
    q4_failures: list[str] = []
    advisories: list[str] = []
    if m["load_s"] > budgets["load_s"]:
        load_failures.append(f"load {m['load_s']}s > budget {budgets['load_s']}s")
    elif m["load_s"] > PHASE_4_LOAD_TARGET_S:
        advisories.append(
            f"load {m['load_s']}s exceeds Phase-4 target {PHASE_4_LOAD_TARGET_S}s"
        )
    if m["fcp_s"] and m["fcp_s"] > budgets["fcp_s"]:
        load_failures.append(f"FCP {m['fcp_s']}s > budget {budgets['fcp_s']}s")
    elif m["fcp_s"] and m["fcp_s"] > PHASE_4_FCP_TARGET_S:
        advisories.append(
            f"FCP {m['fcp_s']}s exceeds Phase-4 target {PHASE_4_FCP_TARGET_S}s"
        )
    if m["peak_browser_rss_mb"] > budgets["ram_mb"]:
        load_failures.append(
            f"browser RSS {m['peak_browser_rss_mb']}MB > budget {budgets['ram_mb']}MB"
        )
    if m["fps_median"] is not None and m["fps_median"] < budgets["fps_min"]:
        load_failures.append(f"FPS {m['fps_median']} < minimum {budgets['fps_min']}")
    if m.get("overflow_px", 0) > 2:
        load_failures.append(
            f"horizontal overflow {m['overflow_px']}px at {report['viewport_width']}px "
            "viewport (doctrine §10.8 frame check)"
        )
    if report["page_errors"]:
        load_failures.append(f"page errors: {report['page_errors']}")
    if report["console_errors"]:
        load_failures.append(f"console errors: {report['console_errors'][:5]}")

    interactive_budget = budgets.get("interactive_s")
    if (
        interactive_budget is not None
        and m.get("interactive_s") is not None
        and m["interactive_s"] > interactive_budget
    ):
        q4_failures.append(
            f"interactive {m['interactive_s']}s > budget {interactive_budget}s"
        )
    long_task_budget = budgets.get("long_task_ms")
    # Q-4 hard gate: a long task on the *interaction path* blocks. The
    # load-path task is reported (it is real evidence) but monitored only:
    # Q-4 names the interaction path, and a shared CI runner adds enough
    # scheduler noise to make a load-path 200 ms assertion flaky.
    load_task_ms = m.get("load_longest_task_ms", m.get("longest_task_ms"))
    if (
        long_task_budget is not None
        and load_task_ms is not None
        and load_task_ms > long_task_budget
    ):
        advisories.append(
            f"load-path long task {load_task_ms}ms > {long_task_budget}ms "
            "(monitored, not blocking; Q-4's hard gate is the interaction path)"
        )
    if (
        long_task_budget is not None
        and m.get("interaction_input_ms") is not None
        and m["interaction_input_ms"] > long_task_budget
    ):
        q4_failures.append(
            f"interactive input {m['interaction_input_ms']}ms > budget "
            f"{long_task_budget}ms (interaction path)"
        )
    if (
        long_task_budget is not None
        and m.get("interaction_longest_task_ms")
        and m["interaction_longest_task_ms"] > long_task_budget
    ):
        q4_failures.append(
            f"scroll/click long task {m['interaction_longest_task_ms']}ms > "
            f"budget {long_task_budget}ms (interaction path)"
        )
    soft = report.get("soft_budgets") or {}
    if soft.get("measured") and not soft.get("within_soft_budget", True):
        advisories.append(
            "soft byte budget exceeded: shell JS "
            f"{soft['shell_js_gzip_kb']} KB (soft {soft['soft_js_budget_kb']} KB), "
            f"CSS {soft['css_gzip_kb']} KB (soft {soft['soft_css_budget_kb']} KB) "
            "- monitored, not blocking (Q-4)"
        )
    report["load_failures"] = load_failures
    report["q4_failures"] = q4_failures
    report["failures"] = load_failures + q4_failures
    report["advisories"] = advisories
    report["load_pass"] = not load_failures
    report["pass"] = not report["failures"]


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:  # noqa: BLE001
        return False


def check_golden_perf_budgets(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """Deterministic check `DET-PERF01-BUDGET-GATE` for `EV-PERF-001`."""
    issues: list[IssueRecord] = []
    suite = context.get("suite", "smoke")

    # 1. Verify both canonical profiles load and match schema
    weak_path = cfg.goldens_dir / "profiles" / "weak-android.json"
    mid_path = cfg.goldens_dir / "profiles" / "mid-laptop.json"
    for p in (weak_path, mid_path):
        if not p.exists():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PERF01-BUDGET-GATE",
                    category="other",
                    message=f"missing canonical perf profile: {p}",
                )
            )
            return issues
        try:
            load_profile(p)
        except ValueError as exc:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PERF01-BUDGET-GATE",
                    category="other",
                    message=str(exc),
                )
            )
            return issues

    active_profile = mid_path if suite == "smoke" else weak_path
    has_chromium = _chromium_available()
    metrics_acc: dict[str, Any] = context.setdefault("metrics", {})
    measured_topics: list[dict[str, Any]] = []

    for topic_rel in card.golden_inputs.get("topics", []):
        tdir = cfg.repo_root / topic_rel
        exp_path = tdir / "expected.json"
        ref_path = tdir / "artifact_ref.json"
        if not exp_path.exists() or not ref_path.exists():
            continue
        exp = json.loads(exp_path.read_text(encoding="utf-8"))
        ref = json.loads(ref_path.read_text(encoding="utf-8"))
        budgets = exp["perf_budgets"]
        if budgets["ram_budget_mb"] > 750 or budgets["fps_min"] < 24:
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PERF01-BUDGET-GATE",
                    category="other",
                    message=f"{exp['golden_id']} perf_budgets violate weak-android floor (750MB / 24fps)",
                )
            )

        page_path: Path | None = None
        if ref.get("published_dir"):
            page_path = cfg.repo_root / ref["published_dir"] / "index.html"
        elif ref.get("reference_html"):
            page_path = cfg.repo_root / ref["reference_html"]

        if page_path and page_path.exists() and has_chromium:
            # In container/sandbox without multi-core pinning permissions, use a temp copy with pin_cores=None if needed
            rep = _safe_run_profile(page_path.resolve().as_uri(), active_profile)
            measured_topics.append(
                {"topic": exp["topic_slug"], **rep.get("measured", {})}
            )
            if not rep["pass"]:
                for fail_msg in rep["failures"]:
                    issues.append(
                        IssueRecord(
                            severity="fatal",
                            check_id="DET-PERF01-BUDGET-GATE",
                            category="frame" if "overflow" in fail_msg else "other",
                            message=f"{exp['topic_slug']}: {fail_msg}",
                        )
                    )
        elif page_path and page_path.exists():
            # No headless Chromium: static asset-size check only. FPS / load /
            # RSS are NOT measured and must not be invented.
            total_bytes = sum(
                f.stat().st_size for f in page_path.parent.glob("*") if f.is_file()
            )
            measured_topics.append(
                {
                    "topic": exp["topic_slug"],
                    "static_bundle_kb": round(total_bytes / 1024, 1),
                }
            )
            if total_bytes > 2 * 1024 * 1024:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-PERF01-BUDGET-GATE",
                        category="other",
                        message=f"{exp['topic_slug']} static bundle {total_bytes}B exceeds 2MB weak-Android budget",
                    )
                )

    budget_topics = [m for m in measured_topics if "load_s" in m]
    metrics_acc["topics_measured"] = len(measured_topics)
    metrics_acc["topics_budget_measured"] = len(budget_topics)
    if budget_topics:
        metrics_acc["load_s_max"] = max(float(m["load_s"]) for m in budget_topics)
        fps_values = [
            float(m["fps_median"]) for m in budget_topics if "fps_median" in m
        ]
        rss_values = [
            float(m["peak_browser_rss_mb"])
            for m in budget_topics
            if "peak_browser_rss_mb" in m
        ]
        if fps_values:
            metrics_acc["fps_min_observed"] = min(fps_values)
        if rss_values:
            metrics_acc["peak_rss_mb_max"] = max(rss_values)

    if not has_chromium and not issues:
        context.setdefault("skipped_checks", {})["DET-PERF01-BUDGET-GATE"] = (
            "headless Chromium unavailable; hardware budget not measured"
        )
    elif has_chromium and not budget_topics and not issues:
        context.setdefault("skipped_checks", {})["DET-PERF01-BUDGET-GATE"] = (
            "no published golden topic page found to profile"
        )
    return issues


def _safe_run_profile(url: str, profile_path: Path) -> dict[str, Any]:
    try:
        return run_profile(url, profile_path)
    except RuntimeError as exc:
        if "could not pin browser to cores" in str(exc):
            import tempfile

            prof = json.loads(profile_path.read_text(encoding="utf-8"))
            prof["pin_cores"] = None
            with tempfile.NamedTemporaryFile(
                "w", suffix=".json", encoding="utf-8", delete=True
            ) as tf:
                json.dump(prof, tf)
                tf.flush()
                return run_profile(url, tf.name)
        raise


def check_fixloop_pedagogy_preservation(
    cfg: EvalConfig, card: EvalCard, context: dict[str, Any]
) -> list[IssueRecord]:
    """Deterministic check `DET-PERF01-PEDAGOGY-GUARD` for `EV-PERF-001`."""
    issues: list[IssueRecord] = []
    # Verify on all published courses that every data-sim-id in index.html has a matching
    # ZivonSim.register("<id>", ...) in page.js (fixloop never stripped a simulation).
    courses_dir = cfg.frontend_dir / "courses"
    if not courses_dir.is_dir():
        return issues

    for index_html in sorted(courses_dir.rglob("index.html")):
        tdir = index_html.parent
        html_text = index_html.read_text(encoding="utf-8")
        sim_ids = re.findall(r'data-sim-id=["\']([^"\']+)["\']', html_text)
        if not sim_ids:
            continue
        # Localized pages reference ../page.js; resolve the actual script
        # instead of assuming it sits next to every index.html.
        js_ref = re.search(r'<script[^>]+src=["\']([^"\']*page\.js)["\']', html_text)
        js_path = (tdir / js_ref.group(1)).resolve() if js_ref else tdir / "page.js"
        if not js_path.exists():
            issues.append(
                IssueRecord(
                    severity="fatal",
                    check_id="DET-PERF01-PEDAGOGY-GUARD",
                    category="drawn_behaviour",
                    message=f"{tdir.name}: index.html declares simulations {sim_ids} but page.js is missing",
                )
            )
            continue
        js_text = js_path.read_text(encoding="utf-8")
        registered = set(
            re.findall(r'ZivonSim\.register\(\s*["\']([^"\']+)["\']', js_text)
        )
        for sid in sim_ids:
            if sid not in registered:
                issues.append(
                    IssueRecord(
                        severity="fatal",
                        check_id="DET-PERF01-PEDAGOGY-GUARD",
                        block_id=sid,
                        category="drawn_behaviour",
                        message=f"{tdir.name}: simulation {sid} missing from page.js ZivonSim.register calls",
                    )
                )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Zivon weak-hardware perf harness")
    parser.add_argument("--url", required=True)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--out", default=None, help="write the JSON report here")
    args = parser.parse_args()
    report = run_profile(args.url, args.profile)
    text = json.dumps(report, indent=2)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
