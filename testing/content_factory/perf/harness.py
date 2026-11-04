"""Weak-hardware performance harness (the Performance Engineer's instrument).

Simulates a low-end Android phone on a real Chromium instance:
- CPU throttling via CDP (Emulation.setCPUThrottlingRate) - each JS op costs N x
- optional CPU affinity restriction (pin the browser to N cores; Linux)
- RAM measured as the peak RSS of the whole Chromium process tree (psutil)
- load budget from wall-clock time around page.goto(wait_until="load"); the
  browser is launched and throttled BEFORE the timer starts, so browser
  startup is never counted - but each page gets a fresh browser with a cold
  cache (first-visit reality, no warm-up)
- FCP/LCP from PerformanceObserver (init script, buffered entries)
- FPS sampled from requestAnimationFrame deltas during scripted interactions
  (scroll, click the first check button, run any canvas simulation)
- console errors and page errors fail the run outright

Usage:
    python -m testing.content_factory.perf.harness --url <file:// or https://> --profile testing/content_factory/perf/profiles/weak-android.json

Or programmatically:
    from testing.content_factory.perf.harness import run_profile
    report = run_profile(url, profile_path)

The profile JSON is the tuning knob for how harshly we test. See
testing/content_factory/perf/profiles/weak-android.json for the default.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import threading
import time
from pathlib import Path
from typing import Any

REQUIRED_PROFILE_KEYS: dict[str, Any] = {
    "viewport_width": int,
    "viewport_height": int,
    "device_scale_factor": (int, float),
    "cpu_throttle_rate": (int, float),
    "ram_budget_mb": (int, float),
    "load_budget_s": (int, float),
    "fcp_budget_s": (int, float),
    "fps_min": (int, float),
    "sim_seconds": (int, float),
    "pin_cores": (int, type(None)),
    "scroll": bool,
    "click_checks": bool,
}


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


def _pin_browser_cores(psutil, proc, cores: list[int]) -> None:
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
        },
        "measured": {},
        "console_errors": [],
        "page_errors": [],
        "failures": [],
        "pass": False,
    }

    with sync_playwright() as p:
        # Snapshot chrome/chromium processes BEFORE the launch: the harness
        # must measure the browser IT spawned, never a browser that happens
        # to be open on the machine (e.g. the developer's own Chrome).
        existing = _chromium_pids()
        browser = p.chromium.launch(headless=True)
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

            page.add_init_script("""
                window.__zivonPerf = {fcp: null, lcp: null};
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
                } catch (e) {}
            """)

            t0 = time.time()
            page.goto(url, wait_until="load", timeout=60000)
            load_s = time.time() - t0

            # Frame adaptation gate (doctrine §10.8): nothing may overflow the
            # viewport horizontally at this profile's width.
            overflow_px = page.evaluate(
                "Math.max(0, document.documentElement.scrollWidth - window.innerWidth)"
            )

            # FPS sampling: scroll, click checks, then sample rAF deltas.
            fps = _sample_fps(page, profile)

            metrics = cdp.send("Performance.getMetrics")
            js_heap_mb = 0.0
            for m in metrics["metrics"]:
                if m["name"] == "JSHeapUsedSize":
                    js_heap_mb = m["value"] / (1024 * 1024)

            peak_rss = rss.stop() if rss else 0.0
            perf_obj = page.evaluate("window.__zivonPerf || {}")

            report["measured"] = {
                "load_s": round(load_s, 2),
                "fcp_s": round((perf_obj.get("fcp") or 0) / 1000, 2),
                "lcp_s": round((perf_obj.get("lcp") or 0) / 1000, 2),
                "fps_median": round(fps, 1) if fps else None,
                "peak_browser_rss_mb": round(peak_rss, 1),
                "js_heap_mb": round(js_heap_mb, 2),
                "overflow_px": int(overflow_px),
                "cpu_throttle_rate": profile["cpu_throttle_rate"],
            }
        finally:
            browser.close()

    _judge(report)
    return report


def _chromium_pids() -> set[int] | None:
    """All chrome/chromium pids currently on the machine (None: no psutil)."""
    try:
        import psutil
    except ImportError:
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
    """Identify the main chromium process spawned by THIS launch.

    Candidates are the chrome/chromium pids that appeared after the launch
    snapshot. The main browser process is the one whose cmdline has no
    --type= flag (renderers, gpu and zygote children all have one) and that
    carries --headless (we always launch headless). Fallback: the lowest new
    pid. Returns None when nothing new appeared or psutil is unavailable."""
    if existing is None:
        return None
    try:
        import psutil
    except ImportError:
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


def _judge(report: dict[str, Any]) -> None:
    m = report["measured"]
    budgets = report["budgets"]
    failures = []
    if m["load_s"] > budgets["load_s"]:
        failures.append(f"load {m['load_s']}s > budget {budgets['load_s']}s")
    if m["fcp_s"] and m["fcp_s"] > budgets["fcp_s"]:
        failures.append(f"FCP {m['fcp_s']}s > budget {budgets['fcp_s']}s")
    if m["peak_browser_rss_mb"] > budgets["ram_mb"]:
        failures.append(
            f"browser RSS {m['peak_browser_rss_mb']}MB > budget {budgets['ram_mb']}MB"
        )
    if m["fps_median"] is not None and m["fps_median"] < budgets["fps_min"]:
        failures.append(f"FPS {m['fps_median']} < minimum {budgets['fps_min']}")
    if m.get("overflow_px", 0) > 2:
        failures.append(
            f"horizontal overflow {m['overflow_px']}px at {report['viewport_width']}px "
            "viewport (doctrine §10.8 frame check)"
        )
    if report["page_errors"]:
        failures.append(f"page errors: {report['page_errors']}")
    if report["console_errors"]:
        failures.append(f"console errors: {report['console_errors'][:5]}")
    report["failures"] = failures
    report["pass"] = not failures


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
