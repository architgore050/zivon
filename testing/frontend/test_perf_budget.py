"""Performance budget tests for the Zivon frontend shell and published pages.

Implements `docs/specs/frontend/perf-budget-tests.md`:
- `test_landing_load_budget`: harness-driven load of `frontend/index.html` on
  the `weak-android` profile (load + FCP inside profile budgets, 0 overflow,
  0 console/page errors).
- `test_published_snapshot_load_budget`: harness-driven load of each published
  `frontend/courses/*/index.html` against the `weak-android` profile.
- `test_sim_fps_under_throttle`: >= `fps_min` (24 fps under 4x CPU throttle)
  across `sim_seconds` (3 s) for a kit-registered synthetic sim.
- `test_ram_budget`: browser-process tree RSS <= `ram_budget_mb` (750 MB).
- `test_no_long_tasks_blocking_input`: no main-thread LongTask > 200 ms after
  load during scroll + check-click pass (INP <= 200 ms proxy).
- `test_cls_under_threshold`: layout shift (CLS) <= 0.1 with fonts loading.
- `test_reduced_motion_single_draw`: `prefers-reduced-motion: reduce` emulated
  -> a registered sim's `draw` runs EXACTLY once (no rAF loop).
- `test_sim_read_mirror_populated`: after `sim_seconds`, `.zn-sim-read` is
  non-empty (enforces the 040410 live-validation contract).
- `test_font_payload_budget`: total transfer size of active `.woff2` fonts in
  `frontend/assets/fonts/` <= `FONT_BUDGET_KB` (spec C4; the budget lives here,
  in the frontend suite that enforces it - content-factory perf profiles carry
  page budgets only).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard / serve_static
from testing.content_factory.perf.harness import load_profile, run_profile
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
WEAK_ANDROID = (
    REPO_ROOT
    / "testing"
    / "content_factory"
    / "perf"
    / "profiles"
    / "weak-android.json"
)
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()
# Font payload budget for the frontend shell (spec C4). Owned here, not in the
# content-factory page profiles: those describe page load, this describes the
# shell asset weight.
FONT_BUDGET_KB = 300.0


def _synthetic_sim_html(include_explicit_mirror: bool = False) -> str:
    mirror_update = (
        "document.querySelector('.zn-sim-read').textContent = "
        "'x = ' + (ctx.values.v * ctx.t).toFixed(1) + ' m';"
        if include_explicit_mirror
        else ""
    )
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        f"<link rel='stylesheet' href='{ZIVON_CSS_URI}'></head><body>"
        "<main class='zn-page'>"
        "<header class='zn-header'><p class='zn-kicker'>class-9-physics</p>"
        "<h1 class='zn-title'>Uniform Motion</h1></header>"
        "<section class='zn-text'>"
        "<p>Position changes linearly with time when velocity is constant.</p>"
        "</section>"
        "<section class='zn-sim zn-sim-b-01' id='b-01' data-sim-id='b-01'>"
        "<h3>Uniform motion track</h3>"
        "<div class='zn-sim-controls'>"
        "<label class='zn-sim-control'><span>Speed (m/s)</span>"
        "<input type='range' data-control='v' min='1' max='10' step='1' value='4'>"
        "<output>4</output></label></div>"
        "<div class='zn-sim-canvas-wrap'>"
        "<canvas class='zn-sim-canvas' width='480' height='320'></canvas></div>"
        "<p class='zn-sim-read' aria-live='polite'></p>"
        "<p class='zn-sim-desc'>Block moving at constant velocity along axis.</p>"
        "</section>"
        "<fieldset class='zn-check' id='b-02' data-format='mcq' data-answer-index='1'>"
        "<legend>What is the slope of the position-time graph?</legend>"
        "<label class='zn-opt'><input type='radio' name='q' value='0'>"
        "<span>Time</span></label>"
        "<label class='zn-opt'><input type='radio' name='q' value='1'>"
        "<span>Velocity</span></label>"
        "<button type='button' class='zn-check-btn'>Check</button>"
        "<p class='zn-check-feedback' aria-live='polite'></p>"
        "</fieldset>"
        "</main>"
        f"<script src='{ZIVON_JS_URI}'></script>"
        "<script>"
        "window.__drawCount = 0;"
        "window.ZivonSim.register('b-01', {"
        "  init: function (ctx) { ctx.g.fillStyle = '#1C1B18'; },"
        "  draw: function (ctx) {"
        "    window.__drawCount += 1;"
        "    ctx.g.clearRect(0, 0, ctx.width, ctx.height);"
        "    var x = ((ctx.t * ctx.values.v * 20) % (ctx.width - 40)) + 20;"
        "    ctx.g.fillStyle = '#1F3A9E';"
        "    ctx.g.fillRect(x, ctx.height / 2 - 12, 24, 24);"
        f"    {mirror_update}"
        "  }"
        "});"
        "</script></body></html>"
    )


class TestPerfBudget(unittest.TestCase):
    """Enforces the low-end Android performance budgets in CI."""

    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str
    _landing_report: dict[str, Any] | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-perf-")
        # Serve frontend/ over HTTP: a file:// origin cannot load the woff2
        # @font-face (CORS), and the font payload IS part of the budget.
        cls._server = serve_static(FRONTEND)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._tmp.cleanup()

    @classmethod
    def _get_landing_report(cls) -> dict[str, Any]:
        if cls._landing_report is None:
            cls._landing_report = run_profile(
                f"{cls._base_url}/index.html", WEAK_ANDROID
            )
        return cls._landing_report

    def test_landing_load_budget(self) -> None:
        report = self._get_landing_report()
        self.assertTrue(
            report["pass"],
            f"landing page failed weak-android perf budget: {report['failures']} "
            f"(measured={report['measured']}, budgets={report['budgets']})",
        )

    def test_published_snapshot_load_budget(self) -> None:
        courses_dir = FRONTEND / "courses"
        if not courses_dir.is_dir():
            self.skipTest("no published catalogue in this checkout")
        pages = sorted(courses_dir.rglob("index.html"))
        if not pages:
            self.skipTest("courses/ contains no index.html pages")
        for page_path in pages:
            rel_url = "/" + str(page_path.relative_to(FRONTEND))
            report = run_profile(f"{self._base_url}{rel_url}", WEAK_ANDROID)
            rel = page_path.relative_to(REPO_ROOT)
            self.assertTrue(
                report["pass"],
                f"published page {rel} failed weak-android budget: "
                f"{report['failures']} "
                f"(measured={report['measured']}, budgets={report['budgets']})",
            )

    def test_sim_fps_under_throttle(self) -> None:
        profile = load_profile(WEAK_ANDROID)
        syn_file = Path(self._tmp.name) / "sim_fps.html"
        syn_file.write_text(_synthetic_sim_html(True), encoding="utf-8")
        report = run_profile(syn_file.resolve().as_uri(), WEAK_ANDROID)
        fps = report["measured"].get("fps_median")
        self.assertIsNotNone(fps, f"expected median FPS measurement, got {report}")
        throttle = profile["cpu_throttle_rate"]
        self.assertGreaterEqual(
            float(fps),
            float(profile["fps_min"]),
            f"FPS {fps} < profile fps_min {profile['fps_min']} under {throttle}x",
        )
        self.assertTrue(
            report["pass"],
            f"sim FPS harness run failed: {report['failures']}",
        )

    def test_ram_budget(self) -> None:
        profile = load_profile(WEAK_ANDROID)
        report = self._get_landing_report()
        rss_mb = float(report["measured"]["peak_browser_rss_mb"])
        budget_mb = float(profile["ram_budget_mb"])
        self.assertLessEqual(
            rss_mb,
            budget_mb,
            f"browser process tree RSS {rss_mb} MB > ram_budget_mb {budget_mb} MB",
        )

    def test_no_long_tasks_blocking_input(self) -> None:
        syn_file = Path(self._tmp.name) / "long_tasks.html"
        syn_file.write_text(_synthetic_sim_html(True), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": 360, "height": 640},
                    device_scale_factor=2,
                    is_mobile=True,
                )
                page = ctx.new_page()
                # Consent is chrome, not lesson content: measure the reading
                # path (declined) so the first-visit sheet never covers the
                # controls under test.
                page.add_init_script(
                    "try { localStorage.setItem('zivon.consent', 'declined'); } catch (e) {}"
                )
                page.add_init_script(
                    """
                    window.__zivonLongTasks = [];
                    window.__zivonPostLoad = false;
                    window.addEventListener('load', () => {
                      setTimeout(() => { window.__zivonPostLoad = true; }, 50);
                    });
                    try {
                      new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                          if (window.__zivonPostLoad && entry.duration > 200) {
                            window.__zivonLongTasks.push(entry.duration);
                          }
                        }
                      }).observe({type: 'longtask', buffered: true});
                    } catch (e) {}
                    """
                )
                page.goto(syn_file.resolve().as_uri(), wait_until="load")
                page.wait_for_timeout(100)
                for _ in range(3):
                    page.mouse.wheel(0, 180)
                    page.wait_for_timeout(60)
                page.click("input[value='1']")
                page.click(".zn-check-btn")
                page.wait_for_timeout(120)
                long_tasks: list[Any] = page.evaluate("window.__zivonLongTasks || []")
                self.assertEqual(
                    long_tasks,
                    [],
                    f"LongTasks > 200 ms detected during input: {long_tasks}",
                )
            finally:
                browser.close()

    def test_cls_under_threshold(self) -> None:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": 360, "height": 640},
                    device_scale_factor=2,
                    is_mobile=True,
                )
                page = ctx.new_page()
                page.add_init_script(
                    """
                    window.__zivonCLS = 0;
                    try {
                      new PerformanceObserver((list) => {
                        for (const entry of list.getEntries()) {
                          if (!entry.hadRecentInput) {
                            window.__zivonCLS += entry.value;
                          }
                        }
                      }).observe({type: 'layout-shift', buffered: true});
                    } catch (e) {}
                    """
                )
                # Over HTTP like production: file:// changes font loading and
                # therefore the layout-shift sequence this test measures.
                page.goto(f"{self._base_url}/index.html", wait_until="load")
                page.wait_for_timeout(250)
                cls_score = float(page.evaluate("window.__zivonCLS || 0"))
                self.assertLessEqual(
                    cls_score,
                    0.1,
                    f"Cumulative Layout Shift {cls_score:.4f} exceeds CWV budget 0.1",
                )
            finally:
                browser.close()

    def test_reduced_motion_single_draw(self) -> None:
        syn_file = Path(self._tmp.name) / "reduced_motion.html"
        syn_file.write_text(_synthetic_sim_html(True), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(
                    viewport={"width": 360, "height": 640},
                    reduced_motion="reduce",
                )
                page = ctx.new_page()
                if hasattr(page, "emulate_media"):
                    page.emulate_media(reduced_motion="reduce")
                page.goto(syn_file.resolve().as_uri(), wait_until="load")
                page.wait_for_timeout(350)
                draws = int(page.evaluate("window.__drawCount || 0"))
                self.assertEqual(
                    draws,
                    1,
                    f"expected 1 static draw under reduced-motion, got {draws}",
                )
            finally:
                browser.close()

    def test_sim_read_mirror_populated(self) -> None:
        # Verifies that even if a Builder page.js leaves .zn-sim-read untouched,
        # the kit populates a non-empty summary so screen readers never see a
        # silent live region (040410 live-validation finding).
        syn_file = Path(self._tmp.name) / "sim_mirror.html"
        syn_file.write_text(_synthetic_sim_html(False), encoding="utf-8")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(syn_file.resolve().as_uri(), wait_until="load")
                page.wait_for_timeout(200)
                mirror_text = str(
                    page.evaluate(
                        "document.querySelector('.zn-sim-read').textContent || ''"
                    )
                ).strip()
                self.assertTrue(
                    mirror_text,
                    "expected .zn-sim-read live region to be non-empty after sim start",
                )
            finally:
                browser.close()

    def test_font_payload_budget(self) -> None:
        budget_kb = FONT_BUDGET_KB
        fonts_dir = FRONTEND / "assets" / "fonts"
        woff2_files = list(fonts_dir.glob("*.woff2"))
        names = [f.name for f in woff2_files]
        self.assertEqual(
            len(woff2_files),
            4,
            f"expected 4 subsetted .woff2 font files in {fonts_dir}, found {names}",
        )
        total_kb = sum(f.stat().st_size for f in woff2_files) / 1024.0
        self.assertLessEqual(
            total_kb,
            budget_kb,
            f"woff2 font payload {total_kb:.1f} KB > FONT_BUDGET_KB {budget_kb:.1f} KB",
        )


if __name__ == "__main__":
    unittest.main()
