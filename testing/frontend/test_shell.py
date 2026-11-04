"""Frontend shell tests: the hand-maintained landing page contract.

Level 1 (no browser): self-containment (shell AND published pages), internal
references, font licensing, and the published-catalogue integrity contract
(courses.js entries <-> the courses/ directories agree).
Level 2 (headless Chromium): clean load with zero console errors, accessibility
basics, the empty-STATE contract (against synthetic data), and catalogue
rendering from injected ZIVON_COURSES data.

Needs a Playwright browser once:  python -m playwright install chromium
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
INDEX = FRONTEND / "index.html"
CODE_FILES = [
    INDEX,
    FRONTEND / "courses.js",
    FRONTEND / "assets" / "zivon.js",
    FRONTEND / "assets" / "zivon.css",
]


class TestShellContract(unittest.TestCase):
    """Static checks on the shell source: no browser needed."""

    def test_self_contained_no_network_refs(self) -> None:
        # The repo rule: generated AND hand-maintained pages make no external calls.
        bad = re.compile(
            r"""(?:src|href)\s*=\s*["']https?://|url\(\s*["']?https?://|fetch\(|XMLHttpRequest"""
        )
        files = list(CODE_FILES)
        if (FRONTEND / "courses").is_dir():
            # Published snapshot (scripts/publish-frontend.sh) is held to the
            # same no-external-refs rule as the shell and as factory lint.
            files += [
                p
                for p in (FRONTEND / "courses").rglob("*")
                if p.suffix in {".html", ".js", ".css", ".json"}
            ]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                if bad.search(line):
                    self.fail(
                        f"{f.relative_to(REPO_ROOT)}:{line_no} touches the network: {line.strip()}"
                    )

    def test_internal_references_resolve(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"'#]+)["']""", html)
        local = [r for r in refs if not r.startswith(("http:", "https:", "mailto:"))]
        self.assertTrue(local, "expected local asset references in index.html")
        for ref in local:
            self.assertTrue(
                (FRONTEND / ref).exists(),
                f"index.html references missing file: {ref}",
            )

    def test_published_catalogue_entries_resolve(self) -> None:
        # Publish-flow contract (scripts/publish-frontend.sh): the repo copy of
        # courses.js IS the site manifest - every entry must resolve to a real
        # index.html with a manifest.json beside it (traceability), and every
        # topic directory on disk must be listed (a wholesale replacement never
        # leaves unlisted pages behind). Mirrors stage 11-link's publish smoke.
        if not (FRONTEND / "courses").is_dir():
            self.skipTest("no published catalogue in this checkout")
        entries = re.findall(
            r'"href":\s*"([^"]+)"',
            (FRONTEND / "courses.js").read_text(encoding="utf-8"),
        )
        self.assertTrue(entries, "courses/ exists but courses.js lists no entries")
        for href in entries:
            index = FRONTEND / href
            self.assertTrue(
                index.is_file(), f"courses.js entry resolves to nothing: {href}"
            )
            self.assertTrue(
                (index.parent / "manifest.json").is_file(),
                f"published page has no manifest.json: {index.parent}",
            )
        listed = {str((FRONTEND / e).parent) for e in entries}
        on_disk = {str(p.parent) for p in (FRONTEND / "courses").rglob("index.html")}
        self.assertEqual(
            on_disk - listed, set(), "published topic not listed in courses.js"
        )

    def test_fonts_are_shipped_with_license(self) -> None:
        self.assertTrue(
            (FRONTEND / "assets" / "fonts").is_dir(), "fonts must ship locally"
        )
        self.assertTrue(
            (FRONTEND / "assets" / "FONTS-LICENSE.md").exists(),
            "bundled fonts require a license record",
        )


class TestShellBehaviour(unittest.TestCase):
    """Real Chromium against file://frontend/index.html."""

    _pw: Any  # Playwright handle, injected in setUpClass
    _browser: Any  # Chromium browser, injected in setUpClass

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()

    def _new_page(self) -> tuple[Page, list[str]]:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        return page, errors

    def test_page_loads_clean_with_a11y_basics(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(INDEX.resolve().as_uri())
            self.assertEqual(errors, [], f"console/page errors on load: {errors}")
            self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
            self.assertTrue(page.title().startswith("Zivon"))
            self.assertIsNotNone(page.query_selector('meta[name="viewport"]'))
            self.assertIsNotNone(page.query_selector("#zn-courses[aria-label]"))
        finally:
            page.close()

    def test_empty_catalogue_contract(self) -> None:
        # Empty-STATE contract against a SYNTHETIC empty courses.js (request-time
        # fake, like the catalogue-render test below): zero cards, and the
        # human-readable empty state is revealed. The repo's live courses.js may
        # hold published entries (the publish flow commits generated pages);
        # that integrity is level-1 TestShellContract's job, never this test's.
        page, errors = self._new_page()
        try:
            page.route(
                "**/courses.js",
                lambda route: route.fulfill(
                    status=200,
                    body="window.ZIVON_COURSES=[];",
                    content_type="application/javascript",
                ),
            )
            page.goto(INDEX.resolve().as_uri())
            self.assertEqual(
                page.evaluate("document.querySelectorAll('#zn-courses a').length"), 0
            )
            self.assertFalse(
                page.evaluate("document.getElementById('zn-empty').hidden"),
                "empty-state message should be revealed when there are no courses",
            )
            self.assertEqual(errors, [], f"console/page errors: {errors}")
        finally:
            page.close()

    def test_catalogue_renders_from_courses_js(self) -> None:
        # Replace courses.js with fake catalogue data at request time, then
        # assert the renderer produced a well-formed card.
        fake = (
            "window.ZIVON_COURSES=[{course_id:'PHY9-MOTION',title:'Motion',"
            "chapter:'Motion and Force',href:'courses/motion/index.html',"
            "generated_at:'2026-11-02'}];"
        )
        page, errors = self._new_page()
        try:
            page.route(
                "**/courses.js",
                lambda route: route.fulfill(
                    status=200, body=fake, content_type="application/javascript"
                ),
            )
            page.goto(INDEX.resolve().as_uri())
            cards = page.query_selector_all("#zn-courses a.zn-card")
            self.assertEqual(len(cards), 1)
            text = cards[0].inner_text()
            self.assertIn("Motion", text)
            self.assertIn("Chapter: Motion and Force", text)
            self.assertIn("PHY9-MOTION", text)
            self.assertEqual(
                cards[0].get_attribute("href"), "courses/motion/index.html"
            )
            self.assertEqual(errors, [], f"console/page errors: {errors}")
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
