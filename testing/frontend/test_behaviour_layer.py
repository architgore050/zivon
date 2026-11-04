"""Shared behaviour layer tests (frontend/assets/zivon.js): quiz wiring + ZivonSim.

Builds synthetic pages in a temp dir that load the REAL zivon.js, then drives
them with real clicks in headless Chromium. These blocks appear on generated
topic pages; the generator is tested elsewhere - here we test the runtime the
pages depend on.

Needs a Playwright browser once:  python -m playwright install chromium
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
ZIVON_JS_URI = (REPO_ROOT / "frontend" / "assets" / "zivon.js").resolve().as_uri()

MCQ_PAGE = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'></head><body>"
    "<fieldset class='zn-check' data-format='mcq' data-answer-index='1'>"
    "<input type='radio' name='q' value='0'><label>2 m/s^2</label>"
    "<input type='radio' name='q' value='1'><label>9.8 m/s^2</label>"
    "<button class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "</fieldset>"
    "<script src='" + ZIVON_JS_URI + "'></script></body></html>"
)

NUMERIC_PAGE = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'></head><body>"
    "<fieldset class='zn-check' data-format='numeric' data-answer='9.8'>"
    "<input class='zn-numeric-input' value='9.81'>"
    "<button class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "</fieldset>"
    "<script src='" + ZIVON_JS_URI + "'></script></body></html>"
)

SIM_ERROR_PAGE = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'></head><body>"
    "<div data-sim-id='s1'><canvas width='300' height='200'></canvas></div>"
    "<script src='" + ZIVON_JS_URI + "'></script>"
    "<script>window.ZivonSim.register('s1', { init: function () { throw new Error('boom'); },"
    " draw: function () {} });</script></body></html>"
)


class TestBehaviourLayer(unittest.TestCase):
    _pw: Any  # Playwright handle, injected in setUpClass
    _browser: Any  # Chromium browser, injected in setUpClass
    _tmp: tempfile.TemporaryDirectory  # scratch dir for synthetic pages

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-fe-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    def _goto(self, html: str) -> tuple[Page, list[str]]:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        f = Path(self._tmp.name) / "page.html"
        f.write_text(html, encoding="utf-8")
        page.goto(f.resolve().as_uri())
        return page, errors

    def test_mcq_correct_and_retry_feedback(self) -> None:
        page, errors = self._goto(MCQ_PAGE)
        try:
            page.click("input[value='1']")
            page.click(".zn-check-btn")
            fb = page.query_selector(".zn-check-feedback")
            assert fb is not None
            self.assertEqual(fb.inner_text(), "✓ Correct.")
            self.assertIn("correct", fb.get_attribute("class") or "")

            # retry is allowed: wrong answer after a right one must say "try again"
            page.click("input[value='0']")
            page.click(".zn-check-btn")
            self.assertEqual(fb.inner_text(), "✗ Not yet - try again.")
            self.assertIn("wrong", fb.get_attribute("class") or "")
            self.assertEqual(errors, [], f"console/page errors: {errors}")
        finally:
            page.close()

    def test_numeric_answer_within_tolerance(self) -> None:
        # 9.81 vs expected 9.8: inside the 1% tolerance -> Correct.
        page, errors = self._goto(NUMERIC_PAGE)
        try:
            page.click(".zn-check-btn")
            fb = page.query_selector(".zn-check-feedback")
            assert fb is not None
            self.assertEqual(fb.inner_text(), "✓ Correct.")
            self.assertEqual(errors, [], f"console/page errors: {errors}")
        finally:
            page.close()

    def test_broken_simulation_fails_loudly(self) -> None:
        # zivon.js contract: a sim that throws must log "ZivonSim:" and paint the
        # error on canvas - never fail silently.
        page, errors = self._goto(SIM_ERROR_PAGE)
        try:
            self.assertTrue(
                any("ZivonSim" in e for e in errors),
                f"expected a loud ZivonSim console error, got: {errors}",
            )
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
