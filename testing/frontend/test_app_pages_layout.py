"""Rendered app-page layout at 360 px (F3, REQUIREMENTS §15 / weak-Android base case).

Renders the real `/app` and `/app/progress` templates through the monolith's
TestClient, writes the HTML to a temp directory, and loads it in Chromium with
the real `frontend/assets` files routed in. Asserts no horizontal overflow at
360 px, the progress rows stack to one column, the five-state text is visible,
every control is at least 40 px tall, and the console is clean. No backend
server, no key, no network beyond the local fixture.
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
CHAPTER = "class-9-describing-motion-around-us"
CONCEPT = "class-9-describing-motion-around-us-sec-01"


class AppPagesLayoutTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-app-layout-")
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
                "email": "layout@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        assert registered.status_code == 201, registered.text
        csrf = client.get("/v1/auth/session").json()["csrf_token"]
        events = [
            {
                "kind": "lesson_block_view",
                "chapter_id": CHAPTER,
                "concept_id": CONCEPT,
                "payload": {"section_id": "sec-01", "source": "merge"},
            },
            {
                "kind": "practice_answer",
                "chapter_id": CHAPTER,
                "concept_id": CONCEPT,
                "payload": {"correct": True, "source": "merge"},
            },
        ]
        posted = client.post(
            "/v1/progress/events",
            json={"events": events},
            headers={"X-CSRF-Token": csrf},
        )
        assert posted.status_code == 200, posted.text
        for name, path in (
            ("dashboard.html", "/app"),
            ("progress.html", "/app/progress"),
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

    def test_dashboard_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("dashboard.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertEqual(page.locator("main").count(), 1)
            self.assertIn("Continue learning", page.inner_text("main"))
            self.assertIn("This week", page.inner_text("aside"))
            self.assertIn("4 days a week", page.inner_text("aside"))
            self.assertIn("Practising", page.inner_text("main"))
            # Interactive controls are touch-sized (inline prose links are not
            # controls; buttons, text-link actions and disclosures are).
            controls = page.locator(
                "main .btn, main .text-link, main button, main summary"
            )
            self.assertGreater(controls.count(), 2)
            for index in range(controls.count()):
                control = controls.nth(index)
                if not control.is_visible():
                    continue
                box = control.bounding_box()
                if box:
                    self.assertGreaterEqual(box["height"], 40, index)
        finally:
            context.close()

    def test_progress_map_stacks_and_publishes_state_text(self) -> None:
        context, page, errors = self._page("progress.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Where you are, chapter by chapter.", page.inner_text("main"))
            self.assertIn("How these states work", page.inner_text("main"))
            states = page.locator(".state")
            self.assertGreater(states.count(), 2)
            self.assertIn("Practising", page.inner_text(".state"))
            self.assertIn("Not started", page.inner_text("main"))
            columns = page.eval_on_selector(
                ".progress-chapter-head",
                "el => getComputedStyle(el).gridTemplateColumns",
            )
            self.assertEqual(
                len(columns.split(" ")),
                1,
                "progress rows must stack to one column at 360 px",
            )
            summary = page.locator("summary").first
            self.assertTrue(summary.is_visible())
            box = summary.bounding_box()
            assert box is not None
            self.assertGreaterEqual(box["height"], 40)
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
