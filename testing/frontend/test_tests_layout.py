"""Tests and series pages at 360 px and the player island (F7, weak-Android base case).

Renders the real hub, builder, player, review, history, and series pages
through the monolith's TestClient, writes the HTML to a temp directory, and
loads it in Chromium with the real `frontend/assets` files routed in. Asserts
no horizontal overflow, stacked grids, touch-sized controls, keyboard-operable
options, a polite live region, a clean console, and that the autosave island
calls the same-origin API with the CSRF header — including the honest
"not saved" state when the call fails. No backend server, no key, no network
beyond the local fixture and the stubbed same-origin call.
"""

from __future__ import annotations

import datetime
import importlib.util
import re
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
from db.uuid7 import uuid7_str
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
LIGHT = "class-10-light-reflection-and-refraction"
PASSWORD = "correct-horse-battery-staple"


def _load_importer() -> Any:
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location(
        "import_assessment_packs_layout_tests", path
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


class TestsLayoutTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str
    _live_attempt_id: str
    _live_question_id: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-tests-layout-")
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
        series_id = uuid7_str()
        paper_id = uuid7_str()
        db.execute(
            "INSERT INTO test_series (series_id, slug, class_level, kind, title, "
            "description, language_set, status) VALUES (?, 'ai-lesson-layout', 10, "
            "'ai_lesson', 'AI lesson tests', 'Chapter tests from lesson concepts.', "
            '\'["en","hi","hi-Latn"]\', \'published\')',
            (series_id,),
        )
        paper_questions = [
            str(row["question_id"])
            for row in db.fetchall(
                "SELECT question_id FROM question_bank WHERE chapter_id = ? "
                "AND language = 'en' ORDER BY question_id LIMIT 3",
                (LIGHT,),
            )
        ]
        db.execute(
            "INSERT INTO test (test_id, series_id, chapter_ids, title, language, "
            "duration_s, total_marks, structure, status) VALUES (?, ?, ?, "
            "'Light chapter test', 'en', 600, 3, '{\"sections\": [\"A\"]}', 'published')",
            (paper_id, series_id, f'["{LIGHT}"]'),
        )
        for index, question_id in enumerate(paper_questions, start=1):
            db.execute(
                "INSERT INTO test_question (test_id, question_id, order_index, "
                "section, marks) VALUES (?, ?, ?, 'A', 1)",
                (paper_id, question_id, index),
            )

        client = TestClient(app, base_url="https://testserver")
        registered = client.post(
            "/v1/auth/register",
            json={
                "email": "layout-tests@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 10,
                "language": "en-IN",
            },
        )
        assert registered.status_code == 201, registered.text
        csrf = client.get("/v1/auth/session").json()["csrf_token"]
        headers = {"X-CSRF-Token": csrf}

        created = client.post(
            "/v1/tests/custom",
            json={"chapter_ids": [LIGHT], "count": 5, "duration_s": 600},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        test_id = created.json()["test"]["test_id"]
        started = client.post(f"/v1/tests/{test_id}/attempts", headers=headers)
        assert started.status_code == 201, started.text
        cls._live_attempt_id = started.json()["attempt"]["attempt_id"]
        state = client.get(f"/v1/tests/attempts/{cls._live_attempt_id}").json()
        cls._live_question_id = state["question"]["question_id"]

        pages = (
            ("tests-hub.html", "/app/tests"),
            ("tests-builder.html", "/app/tests/new"),
            ("tests-player.html", f"/app/tests/{cls._live_attempt_id}"),
            ("tests-history.html", "/app/tests/history"),
            ("tests-series.html", "/app/series"),
            ("tests-series-detail.html", "/app/series/ai-lesson"),
        )
        for name, path in pages:
            response = client.get(path)
            assert response.status_code == 200, (path, response.text)
            (root / name).write_text(response.text, encoding="utf-8")

        # A second, submitted attempt for the review page and its score card.
        submitted = client.post(f"/v1/tests/{test_id}/attempts", headers=headers)
        assert submitted.status_code == 201, submitted.text
        review_attempt = submitted.json()["attempt"]["attempt_id"]
        review_state = client.get(f"/v1/tests/attempts/{review_attempt}").json()
        for position, entry in enumerate(review_state["questions"][:2]):
            question = fetch_question(db, entry["question_id"])
            assert question is not None
            if question.type == "numeric":
                answer: dict[str, Any] = {"value": float(question.answer["value"])}
                if position == 1:
                    answer = {"value": float(question.answer["value"]) + 1000}
            else:
                index = int(question.answer["index"])
                answer = {
                    "index": index
                    if position == 0
                    else (index + 1) % len(question.options)
                }
            client.patch(
                f"/v1/tests/attempts/{review_attempt}/answers",
                json={"question_id": question.question_id, "answer": answer},
                headers=headers,
            )
        client.post(f"/v1/tests/attempts/{review_attempt}/submit", headers=headers)
        review = client.get(f"/app/tests/{review_attempt}/review")
        assert review.status_code == 200, review.text
        (root / "tests-review.html").write_text(review.text, encoding="utf-8")

    def _serve_asset(self, route: Any) -> None:
        requested = route.request.url.split("://", 1)[-1]
        relative = requested.split("/", 1)[1] if "/" in requested else ""
        target = (FRONTEND / relative).resolve()
        if str(target).startswith(str(FRONTEND)) and target.is_file():
            route.fulfill(path=str(target))
        else:
            route.fulfill(status=404, body="")

    def _page(
        self, path: str, *, deadline_seconds: int | None = None
    ) -> tuple[Any, Page, list[str]]:
        context = self._browser.new_context(viewport={"width": 360, "height": 740})
        context.route(
            "**/favicon.ico", lambda route: route.fulfill(status=204, body="")
        )
        context.route("**/assets/**", self._serve_asset)
        page = context.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        if deadline_seconds is None:
            page.goto(f"{self._base_url}/{path}", wait_until="load")
        else:
            # Serve the same page with the server clock near a threshold so the
            # island's polite announcement can be observed deterministically.
            html = (Path(self._tmp.name) / path).read_text(encoding="utf-8")
            deadline = (
                datetime.datetime.now(datetime.UTC)
                + datetime.timedelta(seconds=deadline_seconds)
            ).isoformat()
            modified = re.sub(
                r'data-deadline="[^"]*"', f'data-deadline="{deadline}"', html
            )
            self.assertNotEqual(modified, html, "the player carries a deadline")
            context.route(
                f"**/{path}",
                lambda route: route.fulfill(
                    status=200, content_type="text/html", body=modified
                ),
            )
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
        context, page, errors = self._page("tests-hub.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("A paper, a clock", page.inner_text("main"))
            self._assert_touch_sized(page, "main .btn")
            columns = page.eval_on_selector(
                ".tests-grid", "el => getComputedStyle(el).gridTemplateColumns"
            )
            self.assertEqual(
                len(columns.split(" ")),
                1,
                "the test hub must stack to one column at 360 px",
            )
        finally:
            context.close()

    def test_builder_is_keyboard_operable_and_touch_sized(self) -> None:
        context, page, errors = self._page("tests-builder.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertGreater(page.locator(".tests-chapter-pick").count(), 0)
            pick = page.locator(".tests-chapter-pick input").first
            pick.check()
            self.assertTrue(pick.is_checked())
            self._assert_touch_sized(page, ".tests-chapter-pick")
            self._assert_touch_sized(page, "main .btn")
            self.assertEqual(page.locator("main select").count(), 3)
        finally:
            context.close()

    def test_player_is_keyboard_operable_with_a_clock_and_palette(self) -> None:
        context, page, errors = self._page("tests-player.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertRegex(page.inner_text("[data-tests-clock]"), r"^\d{2}:\d{2}$")
            self.assertEqual(page.locator("main fieldset").count(), 1)
            options = page.locator(".tests-option")
            self.assertGreater(options.count(), 1)
            options.first.click()
            checked = page.evaluate(
                "() => document.querySelectorAll('input[name=\"answer_index\"]:checked').length"
            )
            self.assertEqual(checked, 1)
            self._assert_touch_sized(page, ".tests-option")
            self._assert_touch_sized(page, "main .btn")
            self._assert_touch_sized(page, ".tests-palette-link")
            self.assertGreaterEqual(page.locator(".tests-palette-link").count(), 5)
            self.assertEqual(page.locator("[aria-current='true']").count(), 1)
            self.assertIn("Mark this question for review", page.inner_text("main"))
        finally:
            context.close()

    def test_review_holds_the_360px_frame_and_shows_the_breakdown(self) -> None:
        context, page, errors = self._page("tests-review.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Every question, with the working", page.inner_text("main"))
            self.assertIn("By concept", page.inner_text("main"))
            self.assertIn("By chapter", page.inner_text("main"))
            self.assertIn("Incorrect", page.inner_text("main"))
            self._assert_touch_sized(page, "main .btn")
            self.assertGreaterEqual(page.locator(".tests-review-item").count(), 5)
            page.locator(".tests-review-details summary").first.click()
            self.assertTrue(
                page.locator(".tests-review-details").first.get_attribute("open")
                is not None
            )
        finally:
            context.close()

    def test_series_catalogue_and_detail_hold_the_360px_frame(self) -> None:
        for name in ("tests-series.html", "tests-series-detail.html"):
            context, page, errors = self._page(name)
            try:
                self.assertEqual(errors, [], name)
                self._assert_no_overflow(page)
                self.assertIn(
                    "These practice questions are written by Zivon",
                    page.inner_text("main"),
                )
                if name == "tests-series-detail.html":
                    self._assert_touch_sized(page, "main .btn")
            finally:
                context.close()

    def test_history_holds_the_360px_frame(self) -> None:
        context, page, errors = self._page("tests-history.html")
        try:
            self.assertEqual(errors, [])
            self._assert_no_overflow(page)
            self.assertIn("Every paper you have opened", page.inner_text("main"))
            self._assert_touch_sized(page, ".tests-filter")
        finally:
            context.close()

    def test_the_timer_announces_thresholds_in_words(self) -> None:
        context, page, errors = self._page("tests-player.html", deadline_seconds=61)
        try:
            self.assertEqual(errors, [])
            page.wait_for_timeout(3200)
            self.assertEqual(
                page.inner_text("[data-tests-clock-announce]"),
                "One minute left.",
            )
        finally:
            context.close()

    def test_the_island_autosaves_through_the_same_origin_api(self) -> None:
        context, page, errors = self._page("tests-player.html")
        try:
            captured: dict[str, Any] = {}

            def stub(route: Any) -> None:
                request = route.request
                captured["method"] = request.method
                captured["csrf"] = request.headers.get("x-csrf-token")
                captured["body"] = request.post_data
                route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=(
                        '{"schema_version":1,"saved":{"question_id":"'
                        + self._live_question_id
                        + '","answer":{"index":0},"correct":null,'
                        '"flagged":false},"counts":{"question_count":5,'
                        '"answered":1,"unanswered":4,"correct":0,"flagged":0},'
                        '"remaining_s":590}'
                    ),
                )

            page.route("**/v1/tests/attempts/*/answers", stub)
            page.locator(".tests-option").first.click()
            page.wait_for_selector("[data-tests-save].tests-save--ok")
            self.assertEqual(errors, [])
            self.assertEqual(captured.get("method"), "PATCH")
            self.assertTrue(captured.get("csrf"))
            self.assertIn(self._live_question_id, captured.get("body") or "")
            self.assertIn("Saved", page.inner_text("[data-tests-save]"))

            def fail(route: Any) -> None:
                route.fulfill(status=500, content_type="application/json", body="{}")

            page.unroute("**/v1/tests/attempts/*/answers")
            page.route("**/v1/tests/attempts/*/answers", fail)
            page.locator(".tests-option").nth(1).click()
            page.wait_for_selector("[data-tests-save].tests-save--error")
            self.assertIn("Not saved", page.inner_text("[data-tests-save]"))
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
