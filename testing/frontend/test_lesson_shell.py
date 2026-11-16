"""F4 lesson shell (SCR-LES-01.R0/R13/R14/R15) — shell chrome around a
generated lesson page.

Contract under test (`docs/specs/frontend/lesson-shell.md`):

1. The shell mounts on the published lesson pages without touching the lesson
   body (block count, titles and reading order survive) and with zero console
   errors.
2. The chapter drawer lists the manifest `sections` (block -> section map),
   tracks the current section, and is keyboard operable (Esc closes, focus
   returns to the toggle, a jump moves reading position and focus).
3. Previous/next chapter links come from `catalogue.json` (same course order),
   and a page with no neighbour renders no link (never a dead control).
4. Reading progress is device-local (`localStorage["zivon.progress"]`), drives
   the 2 px bar, emits `EVT-section_viewed` with a measured dwell bucket, keeps
   what the device already recorded across a reload (and never re-emits a
   section it already counted), and needs every section read before it claims
   completion.
5. Bookmarks are device-local (`localStorage["zivon.bookmarks"]`), survive a
   reload, and toggle `aria-pressed`.
6. "Ask about this" anchors the next tutor turn to that block: the explicit
   anchor wins over the viewport anchor and the dock opens expanded.
7. `buildContextSnapshot()` never lets a `sec-NN` section wrapper into the
   voice context (regression for the F4 context bug), and an explicit anchor
   deep in the lesson keeps its real block type.
8. The end-of-lesson CTA links only to pages that exist; practice and
   explain-back are honest non-interactive "coming soon" statuses, and a
   chapter without a successor renders no empty row.
9. Declined voice consent hides the Ask entry and every per-block chip
   (doctrine §10.14) while reading, the drawer and progress keep working.
10. 360 px: no horizontal overflow, shell controls >= 40 px, drawer fits.
11. With JavaScript off the lesson is fully readable and no shell chrome
    exists (progressive enhancement, shell-injection.md "content-first").
12. A content-only fixture without a manifest or catalogue still gets the
    drawer from the DOM and hides the chapter links (no invented data).

Browser tests serve `frontend/` over HTTP (fonts + `manifest.json` +
`catalogue.json` are same-origin fetches); the fixture test uses `file://` like
the other shell tests.
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
FRONTEND = REPO_ROOT / "frontend"
LESSON_URL = "/courses/class-9-physics/describing-motion-around-us/index.html"
LESSON_DIR = FRONTEND / "courses" / "class-9-physics" / "describing-motion-around-us"
LAST_LESSON_URL = "/courses/class-9-physics/how-forces-affect-motion/index.html"
NEXT_LESSON_URL = "/courses/class-9-physics/how-forces-affect-motion/"
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()

CONTENT_ONLY_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    f"<link rel='stylesheet' href='{ZIVON_CSS_URI}'></head><body>"
    "<main class='zn-page'>"
    "<header class='zn-header'><p class='zn-kicker'>class-9-physics</p>"
    "<h1 class='zn-title'>Fixture Lesson</h1></header>"
    "<section class='zn-section' id='sec-01' data-section-id='sec-01'>"
    "<section class='zn-text' id='b-01' data-block-type='text'>"
    "<p>Speed is distance divided by time.</p></section>"
    "<section class='zn-text' id='b-02' data-block-type='text'>"
    "<p>Velocity also carries a direction.</p></section>"
    "</section>"
    "<section class='zn-section' id='sec-02' data-section-id='sec-02'>"
    "<section class='zn-text' id='b-03' data-block-type='text'>"
    "<p>Acceleration is the rate of change of velocity.</p></section>"
    "</section>"
    "<footer class='zn-footer'><p class='zn-sources'>NCERT Grade 9 Science</p></footer>"
    "</main>"
    f"<script src='{ZIVON_JS_URI}'></script>"
    "</body></html>"
)


def _manifest_sections() -> list[dict[str, Any]]:
    manifest = json.loads((LESSON_DIR / "manifest.json").read_text(encoding="utf-8"))
    return list(manifest["sections"])


class TestLessonShell(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(headless=True)
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-lesson-shell-")
        cls._server = serve_static(FRONTEND)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    # -- helpers ---------------------------------------------------------

    def _new_page(
        self,
        *,
        viewport: dict[str, int] | None = None,
        consent: str | None = "granted",
        javascript: bool = True,
        reduced_motion: str | None = None,
    ) -> tuple[Any, Page, list[str]]:
        context_args: dict[str, Any] = {
            "viewport": viewport or {"width": 1280, "height": 900},
            "java_script_enabled": javascript,
        }
        if reduced_motion:
            context_args["reduced_motion"] = reduced_motion
        context = self._browser.new_context(**context_args)
        # No page in this repo ships a favicon, so Chromium's implicit
        # /favicon.ico probe 404s and logs a console error on the FIRST
        # navigation of a browser process only (later pages hit the same-process
        # cache). That made the clean-console assertions depend on test order.
        # The icon is not this contract's business: answer it here.
        context.route(
            "**/favicon.ico",
            lambda route: route.fulfill(status=204, body=""),
        )
        page = context.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        if consent:
            page.add_init_script(
                "try { localStorage.setItem('zivon.consent', '"
                + consent
                + "'); } catch (e) {}"
            )
        return context, page, errors

    def _open_lesson(
        self, url: str = LESSON_URL, **kwargs: Any
    ) -> tuple[Any, Page, list[str]]:
        context, page, errors = self._new_page(**kwargs)
        page.goto(f"{self._base_url}{url}", wait_until="load")
        if kwargs.get("javascript", True):
            page.wait_for_function(
                "() => document.body.getAttribute('data-zn-lessonshell-mounted') === 'true'",
                timeout=5000,
            )
            page.wait_for_timeout(120)
        return context, page, errors

    # -- 1. mount + lesson body untouched --------------------------------

    def test_published_lesson_mounts_shell_and_keeps_the_body(self) -> None:
        context, page, errors = self._open_lesson()
        try:
            self.assertEqual(errors, [], f"lesson shell must load clean, got {errors}")
            self.assertEqual(page.locator(".zn-appbar").count(), 1, "one app bar")
            self.assertEqual(
                page.eval_on_selector(
                    ".zn-appbar",
                    "el => Boolean(el.closest('.zn-page'))",
                ),
                False,
                "the app bar is shell chrome outside the ruled paper",
            )
            self.assertEqual(
                page.locator(".zn-page > .zn-header").count(),
                1,
                "the generated lesson header is still the page's own header",
            )
            self.assertEqual(
                page.locator(".zn-page > .zn-section").count(),
                7,
                "every generated section wrapper is still in place",
            )
            self.assertEqual(
                page.locator("[data-block-type]").count(),
                42,
                "all generated blocks survive the shell mount",
            )
            self.assertIn(
                "Everything around us is in motion",
                page.inner_text("[data-block-type]"),
                "lesson text is still on the page",
            )
            # No §10 device leaked into the shell: the app bar carries none of
            # the lesson-page component classes.
            leaked = page.eval_on_selector(
                ".zn-appbar",
                """el => ['zn-lang-bar','zn-title','zn-check','zn-sim','zn-reveal','zn-diagram']
                    .filter(c => el.querySelector('.' + c) || el.classList.contains(c))""",
            )
            self.assertEqual(
                leaked, [], "shell chrome must not borrow §10 lesson devices"
            )
        finally:
            context.close()

    # -- 2. consent gate: voice affordances are device-local and gated ---

    def test_declined_consent_hides_voice_affordances(self) -> None:
        """Declined voice must leave no dead affordance (doctrine §10.14).

        The per-block chips and the app-bar Ask entry exist only when voice can
        actually open; reading, the drawer and progress never depend on them.
        """
        context, page, errors = self._open_lesson(consent="declined")
        try:
            self.assertEqual(errors, [], f"declined page must load clean, got {errors}")
            self.assertTrue(
                page.eval_on_selector(".zn-appbar-ask", "el => el.hidden"),
                "no Ask entry when voice is off on this device",
            )
            self.assertEqual(
                page.locator(".zn-ask-block").count(),
                0,
                "no per-block chips when voice is off on this device",
            )
            self.assertEqual(
                page.evaluate("() => document.body.getAttribute('data-zn-voice')"),
                "off",
            )
            self.assertEqual(
                page.evaluate("() => window.ZivonLessonShell.openTutor(null)"),
                {"opened": False, "reason": "consent_declined"},
            )
            # The lesson and the navigation still work without voice consent.
            self.assertEqual(page.locator(".zn-page > .zn-section").count(), 7)
            self.assertIn(
                "Everything around us is in motion",
                page.inner_text("[data-block-type]"),
            )
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            self.assertFalse(
                page.eval_on_selector("#zn-chapter-drawer", "el => el.hidden"),
                "the drawer is not a voice surface",
            )
        finally:
            context.close()

    # -- 3. drawer sections + current position ---------------------------

    def test_drawer_lists_manifest_sections_and_tracks_position(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            self.assertTrue(
                page.eval_on_selector("#zn-chapter-drawer", "el => el.hidden"),
                "the drawer starts closed",
            )
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_timeout(80)
            self.assertEqual(
                page.get_attribute("#zn-contents-toggle", "aria-expanded"), "true"
            )
            self.assertEqual(
                page.get_attribute("#zn-contents-toggle", "aria-controls"),
                "zn-chapter-drawer",
                "the toggle names the panel it controls",
            )
            expected = [s["title"] for s in _manifest_sections()]
            got = page.eval_on_selector_all(
                "#zn-chapter-drawer .zn-drawer-link .zn-drawer-title",
                "els => els.map(e => e.textContent.trim())",
            )
            self.assertEqual(got, expected, "drawer sections come from the manifest")

            page.evaluate("() => document.getElementById('sec-04').scrollIntoView()")
            page.wait_for_timeout(250)
            current = page.eval_on_selector_all(
                "#zn-chapter-drawer .zn-drawer-link[aria-current='location']",
                "els => els.map(e => e.textContent.trim())",
            )
            self.assertEqual(len(current), 1, "exactly one current section")
            self.assertIn("Average acceleration", current[0])
            self.assertEqual(
                page.get_attribute(
                    "#zn-chapter-drawer .zn-drawer-item[data-current='true']",
                    "data-section-id",
                ),
                "sec-04",
                "the current marker follows the reading position",
            )
        finally:
            context.close()

    # -- 4. keyboard: Esc closes, jump moves focus ----------------------

    def test_drawer_is_keyboard_operable(self) -> None:
        # Reduced motion makes the section jump instant (`behavior: auto`), so
        # the assertion is about focus and position, not animation timing.
        context, page, _ = self._open_lesson(reduced_motion="reduce")
        try:
            page.click("#zn-contents-toggle")
            page.wait_for_timeout(80)
            self.assertEqual(
                page.evaluate(
                    "() => document.activeElement.closest('#zn-chapter-drawer') !== null"
                ),
                True,
                "opening the drawer moves focus into it",
            )
            page.keyboard.press("Escape")
            page.wait_for_timeout(80)
            self.assertTrue(
                page.eval_on_selector("#zn-chapter-drawer", "el => el.hidden")
            )
            self.assertEqual(
                page.evaluate("() => document.activeElement.id"),
                "zn-contents-toggle",
                "Esc returns focus to the control that opened the drawer",
            )

            # Keyboard jump: focus a section link, activate it, land in it.
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_timeout(80)
            page.focus(
                "#zn-chapter-drawer .zn-drawer-item[data-section-id='sec-05'] .zn-drawer-link"
            )
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)
            self.assertTrue(
                page.eval_on_selector("#zn-chapter-drawer", "el => el.hidden")
            )
            top = page.eval_on_selector(
                "#sec-05", "el => Math.round(el.getBoundingClientRect().top)"
            )
            self.assertLessEqual(
                top, 120, "the jumped-to section is at the top of the viewport"
            )
            self.assertEqual(
                page.evaluate("() => document.activeElement.id"),
                "sec-05",
                "reading focus lands in the section that was chosen",
            )
        finally:
            context.close()

    # -- 5. previous / next chapter -------------------------------------

    def test_chapter_links_only_point_at_published_pages(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_function(
                "() => document.querySelector('#zn-chapter-drawer .zn-drawer-chapters a[rel=next]')",
                timeout=5000,
            )
            next_href = page.get_attribute(
                "#zn-chapter-drawer .zn-drawer-chapters a[rel=next]", "href"
            )
            self.assertEqual(next_href, NEXT_LESSON_URL)
            self.assertEqual(
                page.locator(
                    "#zn-chapter-drawer .zn-drawer-chapters a[rel=prev]"
                ).count(),
                0,
                "the first chapter has no previous chapter (no dead link)",
            )
            self.assertEqual(
                page.request.get(f"{self._base_url}{next_href}").status,
                200,
                "the next-chapter link resolves",
            )
            self.assertEqual(
                page.get_attribute("#zn-next-chapter a[rel=next]", "href"),
                NEXT_LESSON_URL,
                "the end-of-lesson CTA carries the same next chapter",
            )
        finally:
            context.close()

        context, page, _ = self._open_lesson(url=LAST_LESSON_URL)
        try:
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_function(
                "() => document.querySelector('#zn-chapter-drawer .zn-drawer-chapters a[rel=prev]')",
                timeout=5000,
            )
            self.assertEqual(
                page.get_attribute(
                    "#zn-chapter-drawer .zn-drawer-chapters a[rel=prev]", "href"
                ),
                "/courses/class-9-physics/describing-motion-around-us/",
            )
            self.assertEqual(
                page.locator(
                    "#zn-chapter-drawer .zn-drawer-chapters a[rel=next]"
                ).count(),
                0,
                "the last chapter has no next chapter (no dead link)",
            )
            self.assertTrue(
                page.eval_on_selector("#zn-next-chapter", "el => el.hidden"),
                "no next-chapter CTA on the last chapter",
            )
            self.assertFalse(
                page.is_visible("#zn-next-chapter"),
                "the hidden next-chapter row leaves no empty dashed row on the paper",
            )
        finally:
            context.close()

    def test_chapter_hrefs_use_the_catalogue_localized_routes(self) -> None:
        """A locale a chapter does not ship must never be guessed.

        `catalogue.json` publishes `localized_hrefs` (exactly the routes that
        exist per locale) and `missing_locales`; the shell resolves chapter
        links through that map and falls back to English, never to a `/hi/`
        path the topic does not have.
        """
        context, page, _ = self._open_lesson()
        try:
            resolved = page.evaluate(
                """() => {
                  /* The reader's language is the persisted locale (the same
                     key the language bar writes). */
                  localStorage.setItem('zivon_locale', 'hi');
                  const resolve = window.ZivonLessonShell.resolveTopicHref;
                  return {
                    hi: resolve({href: 'courses/c/h/index.html', localized_hrefs: {
                      en: 'courses/c/h/index.html', hi: 'courses/c/h/hi/index.html'}}),
                    noHindi: resolve({href: 'courses/c/h/index.html', localized_hrefs: {
                      en: 'courses/c/h/index.html'}}),
                    legacy: resolve({href: 'courses/c/h/index.html'})
                  };
                }"""
            )
            self.assertEqual(resolved["hi"], "/courses/c/h/hi/")
            self.assertEqual(
                resolved["noHindi"],
                "/courses/c/h/",
                "a missing locale falls back to the English page, not a 404 path",
            )
            # A pre-`localized_hrefs` catalogue keeps the router's guess (that
            # is exactly the gap P5's map closes; F1 owns the hub renderer).
            self.assertEqual(resolved["legacy"], "/courses/c/h/hi/")
        finally:
            context.close()

    # -- 6. reading progress (local + telemetry) ------------------------

    def test_reading_progress_is_local_and_emits_section_views(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            start = int(page.get_attribute("#zn-read-progress", "aria-valuenow") or "0")
            page.evaluate("() => document.getElementById('sec-05').scrollIntoView()")
            page.wait_for_timeout(300)
            page.evaluate("() => document.getElementById('sec-08').scrollIntoView()")
            page.wait_for_timeout(300)
            after = int(page.get_attribute("#zn-read-progress", "aria-valuenow") or "0")
            self.assertGreater(after, start, "the reading progress rule advances")
            self.assertLessEqual(after, 100)

            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            record = stored["chapters"]["class-9-physics/describing-motion-around-us"]
            self.assertTrue(record["sections"], "sections read are stored locally")
            self.assertGreater(record["max_scroll_pct"], 0)
            self.assertGreaterEqual(record["last_section"][:4], "sec-")

            events = page.evaluate("() => window.ZivonEvents.getQueue()")
            section_events = [e for e in events if e["evt"] == "EVT-section_viewed"]
            self.assertTrue(section_events, "section views reach the event queue")
            self.assertIn(
                section_events[0]["props"]["dwell_bucket"],
                {"<5s", "5-30s", ">30s"},
                "dwell is measured, never fabricated",
            )
            self.assertEqual(
                section_events[0]["evt_id"],
                "EVT-F02",
                "EVT-section_viewed maps to the SP3 frontend.section_view row",
            )
        finally:
            context.close()

    def test_reading_every_section_to_the_end_marks_the_lesson_complete(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            section_ids = [
                s["id"]
                for s in page.evaluate("() => window.ZivonLessonShell.getSections()")
            ]
            for section_id in section_ids:
                page.evaluate(
                    "id => document.getElementById(id).scrollIntoView()", section_id
                )
                page.wait_for_timeout(160)
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            events = [
                e
                for e in page.evaluate("() => window.ZivonEvents.getQueue()")
                if e["evt"] == "EVT-lesson_complete"
            ]
            self.assertEqual(len(events), 1, "completion is emitted exactly once")
            self.assertEqual(events[0]["evt_id"], "EVT-F15")
            self.assertEqual(events[0]["props"]["sections_seen"], len(section_ids))
            self.assertGreaterEqual(events[0]["props"]["scroll_pct"], 90)
            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            record = stored["chapters"]["class-9-physics/describing-motion-around-us"]
            self.assertTrue(record["completed"], "completion is stored locally")

            # A completed chapter is a per-chapter fact: reopening it must not
            # emit completion again just because the counters were rehydrated.
            page.reload(wait_until="load")
            page.wait_for_function(
                "() => document.body.getAttribute('data-zn-lessonshell-mounted') === 'true'",
                timeout=5000,
            )
            page.wait_for_timeout(300)
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(300)
            again = [
                e
                for e in page.evaluate("() => window.ZivonEvents.getQueue()")
                if e["evt"] == "EVT-lesson_complete"
            ]
            self.assertEqual(
                again, [], "a reload of a finished chapter emits no new completion"
            )
        finally:
            context.close()

    def test_scrolling_to_the_end_alone_is_not_completion(self) -> None:
        """Completion needs evidence: scrolled to the end is not "read".

        Without this negative case a regression that drops the "every section
        read" half of the gate would still be green (the happy-path test reads
        every section), and the product would claim completion it never saw.
        """
        context, page, _ = self._open_lesson()
        try:
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(400)
            events = [
                e
                for e in page.evaluate("() => window.ZivonEvents.getQueue()")
                if e["evt"] == "EVT-lesson_complete"
            ]
            self.assertEqual(events, [], "scrolling to the end is not completion")
            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            record = stored["chapters"]["class-9-physics/describing-motion-around-us"]
            self.assertFalse(record["completed"])
            self.assertLess(
                len(record["sections"]),
                len(page.evaluate("() => window.ZivonLessonShell.getSections()")),
                "a fast jump to the bottom does not fabricate section reads",
            )
        finally:
            context.close()

    def test_reading_progress_survives_reload_without_double_counting(self) -> None:
        """The device store is the source of truth for "read".

        Reading half a chapter, closing the tab and coming back must not reset
        the drawer to "0 of N" (the progress rule "never goes backwards"), and
        the sections already recorded must not emit `EVT-section_viewed` again.
        """
        context, page, _ = self._open_lesson()
        try:
            for section_id in ("sec-03", "sec-04"):
                page.evaluate(
                    "id => document.getElementById(id).scrollIntoView()", section_id
                )
                page.wait_for_timeout(250)
            before_bar = int(
                page.get_attribute("#zn-read-progress", "aria-valuenow") or "0"
            )
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            before_text = page.inner_text("#zn-chapter-drawer .zn-drawer-progress")
            self.assertIn("2 of 7", before_text)

            page.reload(wait_until="load")
            page.wait_for_function(
                "() => document.body.getAttribute('data-zn-lessonshell-mounted') === 'true'",
                timeout=5000,
            )
            page.wait_for_timeout(200)
            self.assertGreaterEqual(
                int(page.get_attribute("#zn-read-progress", "aria-valuenow") or "0"),
                before_bar,
                "the progress rule keeps what the device already recorded",
            )
            # pagehide closes the section the student was on, so the store can
            # hold one more section than the drawer showed before the reload.
            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.progress')")
            )
            stored_sections = stored["chapters"][
                "class-9-physics/describing-motion-around-us"
            ]["sections"]
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            after_text = page.inner_text("#zn-chapter-drawer .zn-drawer-progress")
            self.assertIn(
                f"{len(stored_sections)} of 7",
                after_text,
                f"the drawer shows what the device recorded: {after_text}",
            )
            self.assertGreaterEqual(len(stored_sections), 3)

            # Leaving an already-read section must not emit it a second time.
            page.evaluate("() => document.getElementById('sec-05').scrollIntoView()")
            page.wait_for_timeout(300)
            replayed = [
                e
                for e in page.evaluate("() => window.ZivonEvents.getQueue()")
                if e["evt"] == "EVT-section_viewed"
                and e["props"].get("section_id") in set(stored_sections)
            ]
            self.assertEqual(
                replayed,
                [],
                "a reloaded, already-read section is not re-emitted",
            )
        finally:
            context.close()

    # -- 7. bookmarks ---------------------------------------------------

    def test_bookmark_toggles_and_survives_reload(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_timeout(80)
            save = "#zn-chapter-drawer .zn-drawer-item[data-section-id='sec-03'] .zn-drawer-save"
            self.assertEqual(page.get_attribute(save, "aria-pressed"), "false")
            page.click(save)
            self.assertEqual(page.get_attribute(save, "aria-pressed"), "true")
            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.bookmarks')")
            )
            self.assertEqual(
                [it["section_id"] for it in stored["items"]],
                ["sec-03"],
                "the bookmark stores the section, not free text",
            )
            self.assertEqual(
                [it["block_id"] for it in stored["items"]],
                ["b-07"],
                "the bookmark carries the first block id as its jump target",
            )

            page.reload(wait_until="load")
            page.wait_for_function(
                "() => document.body.getAttribute('data-zn-lessonshell-mounted') === 'true'",
                timeout=5000,
            )
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_timeout(80)
            self.assertEqual(
                page.get_attribute(save, "aria-pressed"),
                "true",
                "the bookmark survives a reload (device-local)",
            )
            page.click(save)
            self.assertEqual(page.get_attribute(save, "aria-pressed"), "false")
            stored = json.loads(
                page.evaluate("() => localStorage.getItem('zivon.bookmarks')")
            )
            self.assertEqual(stored["items"], [], "un-saving removes the entry")
        finally:
            context.close()

    # -- 8. ask about this: explicit anchor -----------------------------

    def test_ask_about_this_anchors_the_next_turn_to_the_block(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            self.assertEqual(
                page.locator(".zn-ask-block").count(),
                42,
                "one quiet affordance per block",
            )
            # WCAG 2.5.3 label-in-name: the accessible name starts with the
            # visible words, so speech-input users can say "Ask about this".
            first_label = page.get_attribute(".zn-ask-block", "aria-label") or ""
            self.assertTrue(
                first_label.startswith("Ask about this"),
                f"accessible name must contain the visible label: {first_label}",
            )
            page.evaluate("() => document.getElementById('sec-06').scrollIntoView()")
            page.wait_for_timeout(250)
            page.evaluate(
                "() => document.querySelector(\".zn-ask-block[data-block-id='b-13']\").click()"
            )
            page.wait_for_timeout(250)
            snapshot = page.evaluate(
                "() => window.ZivonStateMatrix.buildContextSnapshot()"
            )
            self.assertEqual(
                snapshot["block_id"],
                "b-13",
                "the explicit anchor wins over the viewport anchor",
            )
            self.assertEqual(snapshot["block_type"], "worked_example")
            self.assertEqual(
                page.evaluate("() => window.ZivonVoiceDock.getContainment()"),
                "expanded",
                "the dock opens on the anchored block instead of a second chat surface",
            )
            self.assertTrue(
                page.eval_on_selector(
                    "#b-13", "el => el.classList.contains('zn-tutor-highlight')"
                ),
                "the anchored block is ringed so page and dock read as one conversation",
            )
            events = page.evaluate("() => window.ZivonEvents.getQueue()")
            asked = [e for e in events if e["evt"] == "EVT-ask_about_this"]
            self.assertEqual(len(asked), 1)
            self.assertEqual(asked[0]["props"]["block_id"], "b-13")
            self.assertTrue(asked[0]["props"]["opened"])
        finally:
            context.close()

    # -- 9. context snapshot excludes section wrappers ------------------

    def test_context_snapshot_excludes_section_wrappers(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            snapshot = page.evaluate(
                "() => window.ZivonStateMatrix.buildContextSnapshot()"
            )
            ids = [b["id"] for b in snapshot["visible_blocks"]]
            self.assertTrue(ids, "the snapshot still lists blocks")
            self.assertFalse(
                [i for i in ids if i.startswith("sec-")],
                f"section wrappers must never enter the voice context: {ids}",
            )
            self.assertFalse(snapshot["block_id"].startswith("sec-"))
            for block_id in ids:
                self.assertEqual(
                    page.eval_on_selector(
                        f"#{block_id}",
                        "el => el.getAttribute('data-block-type') !== null",
                    ),
                    True,
                    f"{block_id} is a real block (data-block-type hook)",
                )
            # The anchor is the block nearest the viewport centre, not the
            # section wrapper that contains it.
            page.evaluate("() => document.getElementById('sec-05').scrollIntoView()")
            page.wait_for_timeout(250)
            mid = page.evaluate("() => window.ZivonStateMatrix.buildContextSnapshot()")
            self.assertIn(mid["block_id"], {b["id"] for b in mid["visible_blocks"]})
            self.assertFalse(mid["block_id"].startswith("sec-"))
        finally:
            context.close()

    # -- 10. end-of-lesson CTA honesty ----------------------------------

    def test_end_of_lesson_cta_is_honest(self) -> None:
        context, page, _ = self._open_lesson()
        try:
            self.assertEqual(
                page.locator(".zn-lesson-next").count(),
                1,
                "one end-of-lesson block, inside the page before the footer",
            )
            self.assertEqual(
                page.eval_on_selector(
                    ".zn-lesson-next",
                    "el => el.compareDocumentPosition(el.parentNode.querySelector('.zn-footer')) & Node.DOCUMENT_POSITION_FOLLOWING ? 'before-footer' : 'after-footer'",
                ),
                "before-footer",
            )
            soon = page.eval_on_selector_all(
                ".zn-next-soon",
                "els => els.map(e => [e.textContent.trim(), e.getAttribute('aria-disabled'), Boolean(e.querySelector('a, button'))])",
            )
            self.assertEqual(len(soon), 2, "practice and explain-back are both honest")
            for text, disabled, interactive in soon:
                self.assertIn("coming soon", text)
                self.assertEqual(disabled, "true")
                self.assertFalse(interactive, "a coming-soon row is not a dead control")
            self.assertTrue(
                page.eval_on_selector(
                    "#zn-next-chapter a[rel=next]", "el => el.href.length > 0"
                )
            )
            self.assertTrue(
                page.is_visible("#zn-next-chapter a[rel=next]"),
                "the next-chapter row is rendered when the chapter has a successor",
            )
            page.click(".zn-next-contents")
            page.wait_for_timeout(80)
            self.assertFalse(
                page.eval_on_selector("#zn-chapter-drawer", "el => el.hidden"),
                "back-to-contents opens the same chapter drawer",
            )
        finally:
            context.close()

    # -- 11. 360 px frame ----------------------------------------------

    def test_mobile_360_frame_has_no_overflow(self) -> None:
        context, page, errors = self._open_lesson(
            viewport={"width": 360, "height": 640}
        )
        try:
            self.assertEqual(errors, [])
            self.assertEqual(
                page.evaluate(
                    "() => document.documentElement.scrollWidth - window.innerWidth"
                ),
                0,
                "the shell adds no horizontal overflow at 360 px",
            )
            self.assertFalse(
                page.is_visible(".zn-appbar-nav"),
                "desktop nav collapses into the drawer on phones",
            )
            for selector in ["#zn-contents-toggle", ".zn-appbar-ask", ".zn-ask-block"]:
                box = page.eval_on_selector(
                    selector, "el => el.getBoundingClientRect().height"
                )
                self.assertGreaterEqual(box, 40, f"{selector} keeps a 44 px-ish target")
            page.evaluate("() => window.ZivonLessonShell.openDrawer()")
            page.wait_for_timeout(80)
            self.assertEqual(
                page.eval_on_selector(
                    "#zn-chapter-drawer",
                    "el => Math.round(el.getBoundingClientRect().width)",
                ),
                360,
                "the drawer is full-width on a phone",
            )
            self.assertTrue(page.is_visible("#zn-chapter-drawer .zn-drawer-nav"))
            self.assertEqual(
                page.evaluate(
                    "() => document.documentElement.scrollWidth - window.innerWidth"
                ),
                0,
                "an open drawer adds no horizontal overflow",
            )
        finally:
            context.close()

    # -- 12. JavaScript off ---------------------------------------------

    def test_lesson_is_readable_with_javascript_off(self) -> None:
        context, page, _ = self._open_lesson(javascript=False)
        try:
            self.assertEqual(
                page.locator("[data-block-type]").count(),
                42,
                "every block still ships as HTML with JS off",
            )
            self.assertIn("Everything around us is in motion", page.inner_text("body"))
            self.assertEqual(page.locator(".zn-appbar").count(), 0)
            self.assertEqual(page.locator("#zn-chapter-drawer").count(), 0)
            self.assertEqual(
                page.evaluate("() => document.body.scrollWidth - window.innerWidth"), 0
            )
        finally:
            context.close()

    # -- 13. content-only fixture, no manifest / catalogue --------------

    def test_content_only_fixture_gets_shell_without_manifest_or_catalogue(
        self,
    ) -> None:
        fixture = Path(self._tmp.name) / "content-only.html"
        fixture.write_text(CONTENT_ONLY_HTML, encoding="utf-8")
        context, page, errors = self._new_page()
        try:
            page.goto(fixture.resolve().as_uri(), wait_until="load")
            page.wait_for_function(
                "() => document.body.getAttribute('data-zn-lessonshell-mounted') === 'true'",
                timeout=5000,
            )
            page.wait_for_timeout(150)
            self.assertEqual(errors, [], f"fixture must load clean, got {errors}")
            self.assertEqual(
                page.eval_on_selector_all(
                    "#zn-chapter-drawer .zn-drawer-link .zn-drawer-title",
                    "els => els.map(e => e.textContent.trim())",
                ),
                [
                    "Speed is distance divided by time.",
                    "Acceleration is the rate of change of velocity.",
                ],
                "without a manifest the drawer derives titles from the DOM",
            )
            self.assertEqual(
                page.locator("#zn-chapter-drawer .zn-drawer-chapters a").count(),
                0,
                "no catalogue -> no chapter links (never an invented destination)",
            )
            self.assertTrue(
                page.eval_on_selector("#zn-next-chapter", "el => el.hidden"),
                "no catalogue -> no next-chapter CTA",
            )
            self.assertFalse(
                page.is_visible("#zn-next-chapter"),
                "no catalogue -> no empty next-chapter row either",
            )
        finally:
            context.close()
