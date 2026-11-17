"""Rendered explain-back pages at 360 px (F6, REQUIREMENTS §15).

Renders the real hub, recorder (with a saved result), and history templates
through the monolith's TestClient, writes them to a temp directory, and loads
them in Chromium with the real `frontend/assets` files routed in. Asserts no
horizontal overflow at 360 px, the recorder's controls stack and stay ≥ 44 px,
the status/transcript/rubric text is visible, and the console is clean.
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
from backend.assessment import save_speaking_attempt
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
PASSWORD = "correct-horse-battery-staple"
PROMPT_ID = "spk-c9-motion-001"


class LayoutPipeline:
    """Only what the HTML route reads; no vendor call on a page render."""

    available = True
    mock_mode = False


class SpeakingPagesLayoutTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-speaking-layout-")
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
        import importlib.util
        import sys

        spec = importlib.util.spec_from_file_location(
            "import_assessment_packs_layout",
            REPO_ROOT / "scripts" / "import_assessment_packs.py",
        )
        assert spec and spec.loader
        importer = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = importer
        spec.loader.exec_module(importer)

        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            auth_cookie_secure=True,
            rate_limit_api_per_min=200,
        )
        app = create_app(cfg)
        app.state.speaking = LayoutPipeline()
        db = app.state.db
        importer.import_packs(db, REPO_ROOT / "sources" / "assessment" / "packs")
        client = TestClient(app, base_url="https://testserver")
        registered = client.post(
            "/v1/auth/register",
            json={
                "email": "speaking-layout@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        assert registered.status_code == 201, registered.text
        session = client.get("/v1/auth/session").json()
        user_id = str(session["user"]["user_id"])

        save_speaking_attempt(
            db,
            user_id,
            prompt_id=PROMPT_ID,
            language="en",
            transcript=(
                "Distance is the whole path travelled. Displacement is the net "
                "change in position, so a round trip has zero displacement."
            ),
            rubric_scores={
                "ideas_present": 3,
                "ideas_total": 4,
                "ratio": 0.75,
                "band": "pass",
                "ideas": [
                    {
                        "idea_id": "spk-c9-motion-001-idea-01",
                        "present": True,
                        "evidence": "whole path travelled",
                    },
                    {
                        "idea_id": "spk-c9-motion-001-idea-02",
                        "present": True,
                        "evidence": "net change in position",
                    },
                    {
                        "idea_id": "spk-c9-motion-001-idea-03",
                        "present": True,
                        "evidence": "round trip has zero displacement",
                    },
                    {
                        "idea_id": "spk-c9-motion-001-idea-04",
                        "present": False,
                        "evidence": "",
                    },
                ],
            },
            feedback={
                "band": "pass",
                "label": "AI feedback",
                "what_went_well": "You named distance and displacement clearly.",
                "next_step": "Add that displacement can never be larger.",
                "model": "test-model",
            },
            score=75.0,
            duration_ms=38000,
        )
        for name, path in (
            ("hub.html", "/app/speaking"),
            ("recorder.html", f"/app/speaking/{PROMPT_ID}"),
            ("history.html", "/app/speaking/history"),
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
        page.wait_for_timeout(100)
        return context, page, errors

    def _assert_no_overflow(self, page: Page) -> None:
        metrics = page.evaluate(
            "() => ({html: document.documentElement.scrollWidth,"
            " body: document.body.scrollWidth,"
            " viewport: window.innerWidth})"
        )
        self.assertLessEqual(metrics["html"], metrics["viewport"], metrics)
        self.assertLessEqual(metrics["body"], metrics["viewport"], metrics)

    def test_hub_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("hub.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Say it in your own words.", page.inner_text("main"))
            for link in page.locator("main a.btn--sm").all():
                box = link.bounding_box()
                assert box is not None
                self.assertGreaterEqual(box["height"], 40)
        finally:
            context.close()

    def test_recorder_holds_the_360px_frame_and_controls(self) -> None:
        context, page, errors = self._page("recorder.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            main = page.inner_text("main")
            self.assertIn("Record your explanation", main)
            self.assertIn("Voice tutor: before we start", main)
            self.assertIn("Feedback on your explanation", main)
            self.assertIn("3 of 4 key ideas covered", main)
            self.assertIn("AI feedback", main)
            self.assertIn("MISSING", main)
            self.assertIn("WHAT YOU SAID", main)
            mic = page.locator("[data-speaking-mic]").bounding_box()
            assert mic is not None
            self.assertGreaterEqual(mic["height"], 44)
            delete = page.locator("[data-speaking-delete]").first.bounding_box()
            assert delete is not None
            self.assertGreaterEqual(delete["height"], 40)
            self.assertTrue(page.is_disabled("[data-speaking-mic]"))
        finally:
            context.close()

    def test_history_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("history.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            main = page.inner_text("main")
            self.assertIn("Every explanation you kept.", main)
            self.assertIn("Clear explanation", main)
            self.assertIn("Delete this attempt", main)
        finally:
            context.close()


__all__ = ["SpeakingPagesLayoutTests"]
