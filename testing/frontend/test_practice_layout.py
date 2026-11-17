"""Practice pages at 360 px and the player island (F5, weak-Android base case).

Renders the real `/app/practice`, player, answered player, and summary through
the monolith's TestClient, writes the HTML to a temp directory, and loads it in
Chromium with the real `frontend/assets` files routed in. Asserts no horizontal
overflow, stacked rows, touch-sized controls, keyboard-operable options, a
polite live region, a clean console, and that the JavaScript check calls the
same-origin API with the CSRF header and renders the server's verdict.
No backend server, no key, no network beyond the local fixture and the stubbed
same-origin answer call.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard
from backend import BackendConfig, create_app
from backend.assessment import fetch_question
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
PASSWORD = "correct-horse-battery-staple"


def _load_importer() -> Any:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location(
        "import_assessment_packs_layout", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


class PracticeLayoutTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str
    _question_id: str
    _answered_question_id: str
    _session_id: str
    _island_session_id: str
    _island_question_id: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-practice-layout-")
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
    def _config(cls, root: Path) -> BackendConfig:
        return BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(root / "runs"),
            cold_staging_dir=str(root / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=100,
            auth_register_per_min=100,
            rate_limit_api_per_min=10_000,
        )

    @classmethod
    def _render_pages(cls, root: Path) -> None:
        app = create_app(cls._config(root))
        db = app.state.db
        importer.import_packs(db, PACKS_DIR)
        client = TestClient(app, base_url="https://testserver")
        registered = client.post(
            "/v1/auth/register",
            json={
                "email": "layout-practice@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        assert registered.status_code == 201, registered.text
        csrf = client.get("/v1/auth/session").json()["csrf_token"]
        created = client.post(
            "/v1/practice/sessions",
            json={"mode": "chapter", "chapter_id": MOTION},
            headers={"X-CSRF-Token": csrf},
        )
        assert created.status_code == 201, created.text
        session_id = created.json()["session"]["session_id"]
        state = client.get(f"/v1/practice/sessions/{session_id}").json()
        cls._question_id = state["question"]["question_id"]
        question = fetch_question(db, cls._question_id)
        assert question is not None
        answer = (
            {"value": float(question.answer["value"])}
            if question.type == "numeric"
            else {"index": int(question.answer["index"])}
        )
        answered = client.post(
            f"/v1/practice/sessions/{session_id}/answers",
            json={"question_id": cls._question_id, "answer": answer, "time_ms": 4200},
            headers={"X-CSRF-Token": csrf},
        )
        assert answered.status_code == 200, answered.text
        cls._answered_question_id = cls._question_id
        cls._session_id = session_id

        # Render the open player and its answered state BEFORE closing the set;
        # a completed set redirects the player to the summary.
        pages = (
            ("practice-hub.html", "/app/practice"),
            ("practice-player.html", f"/app/practice/{session_id}"),
            (
                "practice-answered.html",
                f"/app/practice/{session_id}?answered={cls._question_id}",
            ),
        )
        for name, path in pages:
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
            (root / name).write_text(response.text, encoding="utf-8")

        summary = client.post(
            f"/v1/practice/sessions/{session_id}/complete",
            headers={"X-CSRF-Token": csrf},
        )
        assert summary.status_code == 200, summary.text
        closed = client.get(f"/app/practice/{session_id}/summary")
        assert closed.status_code == 200, closed.text
        (root / "practice-summary.html").write_text(closed.text, encoding="utf-8")

        # A second, uncompleted player for the island test.
        second = client.post(
            "/v1/practice/sessions",
            json={"mode": "chapter", "chapter_id": MOTION},
            headers={"X-CSRF-Token": csrf},
        )
        assert second.status_code == 201, second.text
        cls._island_session_id = second.json()["session"]["session_id"]
        island_state = client.get(
            f"/v1/practice/sessions/{cls._island_session_id}"
        ).json()
        cls._island_question_id = island_state["question"]["question_id"]
        island = client.get(f"/app/practice/{cls._island_session_id}")
        assert island.status_code == 200, island.text
        (root / "practice-island.html").write_text(island.text, encoding="utf-8")

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

    def _assert_touch_sized(self, page: Page, selector: str) -> None:
        controls = page.locator(selector)
        self.assertGreater(controls.count(), 0, selector)
        for index in range(controls.count()):
            control = controls.nth(index)
            if not control.is_visible():
                continue
            box = control.bounding_box()
            if box:
                self.assertGreaterEqual(box["height"], 40, (selector, index))

    def test_hub_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("practice-hub.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertEqual(page.locator("main").count(), 1)
            self.assertIn("One question at a time", page.inner_text("main"))
            self.assertIn("Start the Daily 5", page.inner_text("main"))
            self._assert_touch_sized(page, "main .btn")
            columns = page.eval_on_selector(
                ".practice-grid", "el => getComputedStyle(el).gridTemplateColumns"
            )
            self.assertEqual(
                len(columns.split(" ")),
                1,
                "the practice grid must stack to one column at 360 px",
            )
        finally:
            context.close()

    def test_player_is_keyboard_operable_with_a_live_region(self) -> None:
        context, page, errors = self._page("practice-player.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertEqual(page.locator('main [aria-live="polite"]').count(), 1)
            self.assertEqual(page.locator("main fieldset").count(), 1)
            self.assertEqual(page.locator("main progress").count(), 1)
            options = page.locator(".practice-option")
            self.assertGreater(options.count(), 1)
            first = options.first
            first.click()
            checked = page.evaluate(
                "() => document.querySelectorAll('input[name=\"answer_index\"]:checked').length"
            )
            self.assertEqual(checked, 1)
            self._assert_touch_sized(page, ".practice-option")
            self._assert_touch_sized(page, "main .btn")
            self.assertIn("Check answer", page.inner_text("main"))
        finally:
            context.close()

    def test_feedback_state_shows_the_explanation_and_next(self) -> None:
        context, page, errors = self._page("practice-answered.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Correct.", page.inner_text("[data-feedback]"))
            self.assertIn("Why?", page.inner_text("[data-feedback]"))
            self.assertIn("Ask the tutor on this chapter", page.inner_text("main"))
            self.assertTrue(page.locator("[data-next-link]").is_visible())
        finally:
            context.close()

    def test_summary_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("practice-summary.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Where the marks came from", page.inner_text("main"))
            self.assertIn("First attempts", page.inner_text("main"))
            self._assert_touch_sized(page, "main .btn")
        finally:
            context.close()

    def test_the_island_checks_through_the_same_origin_api(self) -> None:
        context, page, errors = self._page("practice-island.html")
        try:
            captured: dict[str, Any] = {}

            def stub(route: Any) -> None:
                request = route.request
                captured["csrf"] = request.headers.get("x-csrf-token")
                captured["body"] = request.post_data
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"schema_version":1,"attempt":{"attempt_no":1,'
                        '"correct":false},"feedback":{"correct":false,'
                        '"answer":{"index":0},"explanation":"Because the net '
                        'change is 40 m.","misconception":"Adding the outward '
                        'trip only.","unit":null},"answered_count":1,'
                        '"correct_count":0,"question_count":10,"next_index":1,'
                        '"complete_available":false}'
                    ),
                )

            page.route("**/v1/practice/sessions/*/answers", stub)
            page.locator(".practice-option").first.click()
            page.get_by_role("button", name="Check answer").click()
            page.wait_for_selector(".practice-feedback-inner")
            self.assertEqual(errors, [])
            self.assertTrue(captured.get("csrf"))
            self.assertIn(self._island_question_id, captured.get("body") or "")
            self.assertIn("Not quite.", page.inner_text("[data-feedback]"))
            self.assertIn("Because the net change", page.inner_text("[data-feedback]"))
            self.assertTrue(page.locator("[data-next-link]").is_visible())
            self.assertTrue(
                page.get_by_role("button", name="Try this one again").is_visible()
            )
            page.get_by_role("button", name="Try this one again").click()
            self.assertEqual(page.inner_text("[data-feedback]").strip(), "")
            self.assertTrue(
                page.get_by_role("button", name="Check answer").is_enabled()
            )
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
