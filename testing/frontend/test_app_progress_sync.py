"""Guest -> account sync island (F3, `/assets/app-progress.js`).

Hermetic browser test: a local fixture page carries the sync panel and the
real asset; `/v1/*` and `/catalogue.json` are fulfilled by Playwright routes.
No backend, no key, no network. Covers the offer, the additive merge, the
CSRF header, the catalogue's section -> concept mapping, the preserved local
copy, a failed merge, dismissal, the F4 shell seam, and saved-section removal.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET = REPO_ROOT / "frontend" / "assets" / "app-progress.js"
CHAPTER_KEY = "class-9-physics/describing-motion-around-us"
CHAPTER_ID = "class-9-describing-motion-around-us"
CONCEPT_ONE = f"{CHAPTER_ID}-sec-01"
CONCEPT_TWO = f"{CHAPTER_ID}-sec-02"

CATALOGUE = {
    "topics": [
        {
            "chapter_id": CHAPTER_ID,
            "course_id": "class-9-physics",
            "topic_slug": "describing-motion-around-us",
            "title": "Describing Motion Around Us",
            "href": f"courses/{CHAPTER_KEY}/index.html",
            "class": 9,
            "chapter": {"number": 4},
            "concepts": [
                {
                    "concept_id": CONCEPT_ONE,
                    "section_id": "sec-01",
                    "title": "Describing position",
                },
                {
                    "concept_id": CONCEPT_TWO,
                    "section_id": "sec-02",
                    "title": "Average speed",
                },
            ],
        }
    ]
}

SYNC_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="test-csrf">
<title>Sync fixture</title></head>
<body><main>
<section data-progress-sync hidden>
  <p data-sync-summary></p>
  <button type="button" data-sync-merge>Bring them in</button>
  <button type="button" data-sync-dismiss>Not now</button>
  <p data-sync-status role="status" aria-live="polite"></p>
</section>
</main>
<script src="/assets/app-progress.js"></script>
</body></html>
"""

BOOKMARK_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="test-csrf">
<title>Bookmarks fixture</title></head>
<body><main>
<p data-bookmark-status role="status" aria-live="polite"></p>
<ul class="bookmark-list">
  <li class="bookmark-row" data-bookmark-row>
    <p class="bookmark-title">Describing Motion Around Us</p>
    <button class="text-link bookmark-remove" type="button" data-bookmark-remove
      data-target-type="block" data-target-id="class-9-describing-motion-around-us:sec-03">Remove</button>
  </li>
</ul>
</main>
<script src="/assets/app-progress.js"></script>
</body></html>
"""

PROGRESS = {
    "v": 1,
    "chapters": {
        CHAPTER_KEY: {
            "sections": {"sec-01": {"first_seen": 1}, "sec-02": {"first_seen": 2}},
            "max_scroll_pct": 80,
            "completed": True,
            "updated_at": 1_700_000_000_000,
        }
    },
}

BOOKMARKS = {
    "v": 1,
    "items": [
        {
            "course": "class-9-physics",
            "topic": CHAPTER_KEY,
            "section_id": "sec-02",
            "block_id": "b-07",
            "title": "Average speed",
            "ts": 1_700_000_000_000,
        }
    ],
}


class AppProgressSyncTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-app-sync-")
        root = Path(cls._tmp.name)
        (root / "index.html").write_text(SYNC_PAGE, encoding="utf-8")
        lesson = root / "courses" / "class-9-physics" / "describing-motion-around-us"
        lesson.mkdir(parents=True)
        (lesson / "index.html").write_text(SYNC_PAGE, encoding="utf-8")
        (root / "bookmarks.html").write_text(BOOKMARK_PAGE, encoding="utf-8")
        cls._server = serve_static(root)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def _page(
        self,
        *,
        progress: dict[str, Any] | None = None,
        bookmarks: dict[str, Any] | None = None,
        shell: bool = False,
        api_status: int = 200,
        path: str = "/index.html",
    ) -> tuple[Any, Page, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        context = self._browser.new_context()
        context.route(
            "**/favicon.ico", lambda route: route.fulfill(status=204, body="")
        )
        context.route(
            "**/assets/app-progress.js",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=ASSET.read_text(encoding="utf-8"),
            ),
        )
        context.route(
            "**/catalogue.json",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(CATALOGUE),
            ),
        )
        event_calls: list[dict[str, Any]] = []
        bookmark_calls: list[dict[str, Any]] = []

        def handle_api(route: Any) -> None:
            request = route.request
            if request.method == "DELETE":
                bookmark_calls.append(
                    {
                        "method": "DELETE",
                        "url": request.url,
                        "csrf": request.headers.get("x-csrf-token"),
                    }
                )
                if api_status != 200:
                    route.fulfill(status=api_status, body="")
                    return
                route.fulfill(status=200, json={"ok": True, "removed": True})
                return
            body = request.post_data_json
            if "/v1/progress/events" in request.url:
                event_calls.append(
                    {"body": body, "csrf": request.headers.get("x-csrf-token")}
                )
            else:
                bookmark_calls.append(
                    {"body": body, "csrf": request.headers.get("x-csrf-token")}
                )
            if api_status != 200:
                route.fulfill(status=api_status, body="")
                return
            if "/v1/progress/events" in request.url:
                route.fulfill(
                    status=200,
                    json={"accepted": len(body["events"]), "rejected": []},
                )
            elif "items" in body:
                route.fulfill(
                    status=201,
                    json={
                        "items": [{} for _ in body["items"]],
                        "created": len(body["items"]),
                        "existing": 0,
                    },
                )
            else:
                route.fulfill(status=201, json={"item": {}, "created": True})

        context.route("**/v1/**", handle_api)
        if progress is not None:
            context.add_init_script(
                "localStorage.setItem('zivon.progress', "
                + json.dumps(json.dumps(progress))
                + ");"
            )
        if bookmarks is not None:
            context.add_init_script(
                "localStorage.setItem('zivon.bookmarks', "
                + json.dumps(json.dumps(bookmarks))
                + ");"
            )
        if shell:
            context.add_init_script(
                "window.__sink = null;"
                "window.ZivonLessonShell = {"
                "  getProgress: function () { return {sections: {"
                '    "sec-01": {first_seen: 1}}, max_scroll_pct: 40,'
                "    completed: false, updated_at: 1700000000000}; },"
                "  setProgressSink: function (fn) { window.__sink = fn; }"
                "};"
            )
        page = context.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"{self._base_url}{path}", wait_until="load")
        return context, page, event_calls, bookmark_calls, errors

    def _wait_offer(self, page: Page) -> None:
        page.wait_for_function(
            "() => { var p = document.querySelector('[data-progress-sync]');"
            " return p && !p.hidden; }",
            timeout=5000,
        )

    # -- tests --------------------------------------------------------------

    def test_no_local_data_keeps_the_offer_hidden(self) -> None:
        context, page, events, bookmarks, errors = self._page()
        try:
            self.assertTrue(page.locator("[data-progress-sync]").is_hidden())
            self.assertEqual(errors, [])
            self.assertEqual(events, [])
            self.assertEqual(bookmarks, [])
        finally:
            context.close()

    def test_merge_is_additive_mapped_and_keeps_the_device_copy(self) -> None:
        context, page, events, bookmark_calls, errors = self._page(
            progress=PROGRESS, bookmarks=BOOKMARKS
        )
        try:
            self._wait_offer(page)
            summary = page.inner_text("[data-sync-summary]")
            self.assertIn("1 chapter", summary)
            self.assertIn("1 saved section", summary)
            page.click("[data-sync-merge]")
            page.wait_for_function(
                "() => (document.querySelector('[data-sync-status]')||{}).textContent"
                ".indexOf('Brought in') === 0",
                timeout=5000,
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(events), 1)
            payload = events[0]["body"]["events"]
            kinds = [event["kind"] for event in payload]
            self.assertEqual(kinds.count("lesson_block_view"), 2)
            self.assertEqual(kinds.count("lesson_complete"), 1)
            self.assertEqual({event["chapter_id"] for event in payload}, {CHAPTER_ID})
            sections = {
                event["payload"].get("section_id")
                for event in payload
                if event["kind"] == "lesson_block_view"
            }
            self.assertEqual(sections, {"sec-01", "sec-02"})
            concepts = {
                event["payload"].get("section_id"): event.get("concept_id")
                for event in payload
                if event["kind"] == "lesson_block_view"
            }
            self.assertEqual(concepts["sec-01"], CONCEPT_ONE)
            self.assertEqual(concepts["sec-02"], CONCEPT_TWO)
            self.assertEqual(events[0]["csrf"], "test-csrf")
            self.assertEqual(
                bookmark_calls[0]["body"],
                {
                    "items": [
                        {
                            "target_type": "block",
                            "target_id": f"{CHAPTER_ID}:sec-02",
                        }
                    ]
                },
            )
            self.assertEqual(bookmark_calls[0]["csrf"], "test-csrf")

            local = page.evaluate(
                "() => ({progress: localStorage.getItem('zivon.progress'),"
                " bookmarks: localStorage.getItem('zivon.bookmarks'),"
                " marker: JSON.parse(localStorage.getItem('zivon.sync.v1')||'{}')})"
            )
            self.assertIsNotNone(local["progress"], "local progress must survive")
            self.assertIsNotNone(local["bookmarks"], "local bookmarks must survive")
            self.assertTrue(local["marker"].get("events"))
            self.assertTrue(local["marker"].get("bookmarks"))
        finally:
            context.close()

    def test_failed_merge_keeps_the_local_data_and_the_offer(self) -> None:
        context, page, events, _, errors = self._page(progress=PROGRESS, api_status=500)
        try:
            self._wait_offer(page)
            page.click("[data-sync-merge]")
            page.wait_for_function(
                "() => (document.querySelector('[data-sync-status]')||{}).textContent"
                ".indexOf('still on this device') !== -1",
                timeout=5000,
            )
            # The only console noise is the deliberate 500 response.
            self.assertTrue(all("500" in error for error in errors), errors)
            self.assertFalse(page.locator("[data-progress-sync]").is_hidden())
            marker = page.evaluate("() => localStorage.getItem('zivon.sync.v1')")
            self.assertIsNone(marker)
            self.assertIsNotNone(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            self.assertGreaterEqual(len(events), 1)
        finally:
            context.close()

    def test_not_now_dismisses_this_session_only(self) -> None:
        context, page, events, _, _ = self._page(progress=PROGRESS)
        try:
            self._wait_offer(page)
            page.click("[data-sync-dismiss]")
            self.assertTrue(page.locator("[data-progress-sync]").is_hidden())
            self.assertEqual(events, [])
            self.assertIsNotNone(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            self.assertIsNotNone(
                page.evaluate("() => sessionStorage.getItem('zivon.sync.dismissed')")
            )
        finally:
            context.close()

    def test_f4_shell_get_progress_and_sink_are_used(self) -> None:
        context, page, events, _, errors = self._page(
            shell=True, path=f"/courses/{CHAPTER_KEY}/"
        )
        try:
            self.assertTrue(
                page.evaluate("() => typeof window.__sink === 'function'"),
                "the island must register F4's progress sink",
            )
            self._wait_offer(page)
            page.click("[data-sync-merge]")
            page.wait_for_function(
                "() => (document.querySelector('[data-sync-status]')||{}).textContent"
                ".indexOf('Brought in') === 0",
                timeout=5000,
            )
            self.assertEqual(errors, [])
            payload = events[0]["body"]["events"]
            self.assertEqual({event["chapter_id"] for event in payload}, {CHAPTER_ID})
            self.assertEqual(
                {event["payload"].get("section_id") for event in payload},
                {"sec-01"},
            )
        finally:
            context.close()

    def test_saved_section_removal_calls_the_api_and_removes_the_row(self) -> None:
        context, page, _, bookmark_calls, errors = self._page(path="/bookmarks.html")
        try:
            page.click("[data-bookmark-remove]")
            page.wait_for_function(
                "() => (document.querySelector('[data-bookmark-status]')||{}).textContent"
                ".indexOf('Removed') === 0",
                timeout=5000,
            )
            self.assertEqual(errors, [])
            self.assertEqual(len(bookmark_calls), 1)
            self.assertIn("DELETE", bookmark_calls[0]["method"])
            self.assertIn("target_type=block", bookmark_calls[0]["url"])
            self.assertIn(
                "target_id=class-9-describing-motion-around-us%3Asec-03",
                bookmark_calls[0]["url"],
            )
            self.assertEqual(bookmark_calls[0]["csrf"], "test-csrf")
        finally:
            context.close()


if __name__ == "__main__":
    unittest.main()
