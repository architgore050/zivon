"""Rendered SWOT pages at 360 px (F8; the weak-Android base case).

Same harness as `test_app_pages_layout.py`: the real templates render through
the monolith's TestClient, the HTML is loaded in Chromium with the real
`frontend/assets` files routed in, and the page must hold the 360 px frame —
no horizontal overflow, quadrants stacked to one column, touch-sized controls,
clean console.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard
from backend import BackendConfig, create_app
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
PASSWORD = "correct-horse-battery-staple"
CHAPTER_A = "class-9-describing-motion-around-us"
CHAPTER_B = "class-9-how-forces-affect-motion"
CHAPTER_C = "class-11-units-and-measurement"


class SwotPagesLayoutTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-swot-layout-")
        root = Path(cls._tmp.name)
        cls._render_pages(root)
        cls._server = serve_static(root)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    @classmethod
    def _render_pages(cls, root: Path) -> None:
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            auth_cookie_secure=True,
            rate_limit_api_per_min=200,
        )
        app = create_app(cfg)
        client = TestClient(app, base_url="https://testserver")
        registered = client.post(
            "/v1/auth/register",
            json={
                "email": "swotlayout@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        assert registered.status_code == 201, registered.text
        csrf = client.get("/v1/auth/session").json()["csrf_token"]
        events: list[dict[str, Any]] = []
        profiles = (
            (CHAPTER_A, 6, 9, [True] * 6),
            (CHAPTER_B, 5, 9, [False] * 6),
            (CHAPTER_C, 3, 9, [True] * 4),
        )
        for chapter_id, seen, total, flags in profiles:
            events.append(
                {
                    "kind": "lesson_block_view",
                    "chapter_id": chapter_id,
                    "payload": {
                        "section_id": "sec-01",
                        "blocks_seen": seen,
                        "blocks_total": total,
                    },
                }
            )
            events.extend(
                {
                    "kind": "practice_answer",
                    "chapter_id": chapter_id,
                    "payload": {"correct": flag, "hints_used": 0, "time_ms": 30000},
                }
                for flag in flags
            )
        posted = client.post(
            "/v1/progress/events",
            json={"events": events},
            headers={"X-CSRF-Token": csrf},
        )
        assert posted.status_code == 200, posted.text
        for name, path in (
            ("swot.html", "/app/swot"),
            ("swot_how.html", "/app/swot/how"),
        ):
            response = client.get(path)
            assert response.status_code == 200, response.text
            (root / name).write_text(response.text, encoding="utf-8")

    def _page(self, path: str) -> tuple[Any, Page, list[str]]:
        context = self._browser.new_context(viewport={"width": 360, "height": 740})
        context.route(
            "**/favicon.ico", lambda route: route.fulfill(status=204, body="")
        )

        def serve_asset(route: Any) -> None:
            requested = route.request.url.split("://", 1)[-1]
            relative = requested.split("/", 1)[1] if "/" in requested else ""
            target = (FRONTEND / relative).resolve()
            if str(target).startswith(str(FRONTEND)) and target.is_file():
                route.fulfill(path=str(target))
            else:
                route.fulfill(status=404, body="")

        context.route("**/assets/**", serve_asset)
        page = context.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{self._base_url}/{path}", wait_until="load")
        page.wait_for_timeout(80)
        return context, page, errors

    def _assert_no_overflow(self, page: Page) -> None:
        metrics = page.evaluate(
            "() => ({html: document.documentElement.scrollWidth,"
            " body: document.body.scrollWidth,"
            " viewport: window.innerWidth})"
        )
        self.assertLessEqual(metrics["html"], metrics["viewport"], metrics)
        self.assertLessEqual(metrics["body"], metrics["viewport"], metrics)

    def test_swot_grid_stacks_and_stays_readable_at_360px(self) -> None:
        context, page, errors = self._page("swot.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertEqual(page.locator("main").count(), 1)
            text = page.inner_text("main")
            for label in ("Strengths", "Weaknesses", "Opportunities", "Threats"):
                self.assertIn(label, text)
            # 360 px stacks the quadrants: one grid column, not two.
            columns = page.eval_on_selector(
                ".swot-grid",
                "el => getComputedStyle(el).gridTemplateColumns",
            )
            self.assertEqual(
                len(columns.split(" ")),
                1,
                "SWOT quadrants must stack to one column at 360 px",
            )
            # Every card names its evidence and one next action; controls are
            # touch-sized.
            self.assertGreaterEqual(page.locator(".swot-card").count(), 2)
            self.assertIn("correct", text)
            self.assertIn("/app/practice", self.content_hrefs(page))
            controls = page.locator("main .btn, main .text-link, main summary")
            for index in range(controls.count()):
                control = controls.nth(index)
                if not control.is_visible():
                    continue
                box = control.bounding_box()
                if box:
                    self.assertGreaterEqual(box["height"], 40, index)
            # No colour-only quadrant: each carries its heading word.
            self.assertIn("Watch-outs", text)
        finally:
            context.close()

    def test_swot_how_table_scrolls_inside_its_container_at_360px(self) -> None:
        context, page, errors = self._page("swot_how.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("How your SWOT is computed.", page.inner_text("main"))
            # The wide numbers table scrolls in its own wrapper; the page frame
            # never overflows (asserted above).
            wrap = page.locator(".swot-table-wrap")
            self.assertEqual(wrap.count(), 1)
            self.assertIn("weighted_accuracy_pct", page.inner_text("main"))
            method_lines = page.locator(".swot-method-list li")
            self.assertGreaterEqual(method_lines.count(), 5)
        finally:
            context.close()

    def content_hrefs(self, page: Page) -> str:
        return " ".join(
            page.eval_on_selector_all(
                "main a", "els => els.map(el => el.getAttribute('href'))"
            )
        )


if __name__ == "__main__":
    unittest.main()
