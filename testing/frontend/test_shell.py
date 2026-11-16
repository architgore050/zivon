"""Public-site contract: landing, catalogue, class pages, trust pages, 404.

Level 1 (no browser): page inventory, no external *resources*, internal
references, catalogue integrity, lesson-device scope guard, metadata, and the
nginx route that serves the hand-maintained catalogue.

Level 2 (headless Chromium): clean load with zero console errors, the Concept A
landing with JavaScript off, catalogue search/filter/empty/error states, class
pages, 360 px overflow, and basic accessibility.

Needs a Playwright browser once:  python -m playwright install chromium
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
INDEX = FRONTEND / "index.html"
CODE_FILES = [
    INDEX,
    FRONTEND / "courses.js",
    FRONTEND / "assets" / "zivon.js",
    FRONTEND / "assets" / "zivon.css",
    FRONTEND / "assets" / "product.js",
    FRONTEND / "assets" / "product.css",
]

# Route -> repo file. This is the static-site map; /courses is served by the
# exact-match nginx location from catalogue/index.html (see docker/nginx.conf)
# because frontend/courses/ is factory-owned and replaced wholesale on publish.
PUBLIC_PAGES: dict[str, Path] = {
    "/": FRONTEND / "index.html",
    "/courses": FRONTEND / "catalogue" / "index.html",
    "/class-9-physics/": FRONTEND / "class-9-physics" / "index.html",
    "/class-10-physics/": FRONTEND / "class-10-physics" / "index.html",
    "/class-11-physics/": FRONTEND / "class-11-physics" / "index.html",
    "/class-12-physics/": FRONTEND / "class-12-physics" / "index.html",
    "/method/": FRONTEND / "method" / "index.html",
    "/about/": FRONTEND / "about" / "index.html",
    "/pricing/": FRONTEND / "pricing" / "index.html",
    "/terms/": FRONTEND / "terms" / "index.html",
    "/contact/": FRONTEND / "contact" / "index.html",
    "/status/": FRONTEND / "status" / "index.html",
    "/privacy/": FRONTEND / "privacy" / "index.html",
}

# The browser server serves paths, not nginx's exact-match route. /courses is
# tested through its file path; the nginx routing is asserted separately.
BROWSER_PAGES = ["/", "/catalogue/", "/class-9-physics/", "/method/", "/about/",
                 "/pricing/", "/terms/", "/contact/", "/status/", "/privacy/"]

LESSON_DEVICE_MARKERS = [
    "zn-lang-bar",
    "zn-voice-dock",
    "zn-check",
    "zn-sim",
    "zn-reveal",
    "zn-page",
    "Caveat",
    'class="zn-diagram',
]


def _resolve_ref(ref: str, page: Path) -> Path | None:
    """Resolve a local reference the way the static server/nginx would.

    Returns None for anchors, mail links and external URLs (external *links*
    are allowed; external resources are caught by the resource regex).
    """
    raw = ref.split("?", 1)[0].split("#", 1)[0]
    if not raw or raw.startswith(("http:", "https:", "mailto:", "tel:", "//")):
        return None
    if raw.startswith("/"):
        if raw in ("/courses", "/courses/"):
            return FRONTEND / "catalogue" / "index.html"
        target = FRONTEND / raw.lstrip("/")
    else:
        target = page.parent / raw
    if target.is_dir():
        target = target / "index.html"
    return target


def _public_html() -> list[tuple[str, Path]]:
    return list(PUBLIC_PAGES.items()) + [("/404.html", FRONTEND / "404.html")]


class TestPublicSiteContract(unittest.TestCase):
    """Static contract: no browser needed."""

    def test_self_contained_no_external_resources(self) -> None:
        # A page may LINK out (the public issue tracker), but it may not LOAD
        # anything from another host: fonts, styles, scripts, images, fetches.
        external_src = re.compile(r"""\bsrc\s*=\s*["']https?://""", re.IGNORECASE)
        external_link = re.compile(
            r"""<link\b[^>]*\bhref\s*=\s*["']https?://""", re.IGNORECASE
        )
        external_css = re.compile(r"""url\(\s*["']?https?://""", re.IGNORECASE)
        external_io = re.compile(
            r"""(?:fetch|WebSocket|EventSource)\(\s*["']https?://""", re.IGNORECASE
        )
        files = list(CODE_FILES)
        files += [path for _, path in _public_html()]
        files += [path for path in (FRONTEND / "courses").rglob("*") if path.suffix in {".html", ".js", ".css", ".json"}]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for line_no, line in enumerate(text.splitlines(), 1):
                for pattern in (external_src, external_link, external_css, external_io):
                    if pattern.search(line):
                        self.fail(
                            f"{f.relative_to(REPO_ROOT)}:{line_no} loads an external "
                            f"resource: {line.strip()}"
                        )

    def test_internal_references_resolve(self) -> None:
        checked = 0
        for route, page in _public_html():
            self.assertTrue(page.is_file(), f"{route} is missing ({page})")
            html = page.read_text(encoding="utf-8")
            refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", html)
            self.assertTrue(refs, f"{route} has no local references")
            for ref in refs:
                target = _resolve_ref(ref, page)
                if target is None:
                    continue
                self.assertTrue(
                    target.is_file(),
                    f"{route} references missing file: {ref}",
                )
                checked += 1
        self.assertGreater(checked, 20, "expected a linked public site")

    def test_cache_busted_asset_refs_still_resolve(self) -> None:
        # A stale asset must never pin an old page; the query string is a cache
        # key, not part of the path. Every shipped public page carries ?v= and
        # still resolves after it is stripped.
        pages = [path for _, path in _public_html()]
        for page in pages:
            html = page.read_text(encoding="utf-8")
            refs = re.findall(r"""(?:src|href)\s*=\s*["']([^"']+)["']""", html)
            local = [
                ref
                for ref in refs
                if not ref.startswith(("http:", "https:", "mailto:", "tel:", "//", "#"))
            ]
            self.assertIn("?v=", html, f"{page.name} should cache-bust its assets")
            for ref in local:
                target = _resolve_ref(ref, page)
                if target is None:
                    continue
                self.assertTrue(
                    target.is_file(),
                    f"{page.relative_to(REPO_ROOT)} references missing file: {ref}",
                )

    def test_public_pages_have_metadata_and_one_h1(self) -> None:
        for route, page in _public_html():
            html = page.read_text(encoding="utf-8")
            self.assertRegex(html, r'<html\s+lang="en"', f"{route}: html lang")
            self.assertIn('name="viewport"', html, f"{route}: viewport")
            self.assertRegex(html, r"<title>[^<]+</title>", f"{route}: title")
            self.assertIn('name="description"', html, f"{route}: description")
            if route != "/404.html":
                self.assertIn('rel="canonical"', html, f"{route}: canonical")
            self.assertEqual(
                len(re.findall(r"<h1\b", html)), 1, f"{route}: exactly one h1"
            )
            self.assertIn('id="main"', html, f"{route}: main landmark")
            self.assertIn('class="skip" href="#main"', html, f"{route}: skip link")
            if route != "/404.html":
                self.assertIn(
                    'name="robots" content="index,follow"',
                    html,
                    f"{route}: indexable public page",
                )

    def test_landing_carries_social_metadata_and_json_ld(self) -> None:
        html = INDEX.read_text(encoding="utf-8")
        self.assertIn('property="og:type"', html)
        self.assertIn('property="og:url"', html)
        self.assertRegex(html, r'property="og:image"\s+content="https?://[^"]+"')
        self.assertRegex(html, r'name="twitter:image"\s+content="https?://[^"]+"')
        self.assertIn('type="application/ld+json"', html)
        self.assertIn('"@type":"WebSite"', html)

    def test_no_lesson_devices_on_public_pages(self) -> None:
        # Doctrine §0 scope guard: the public site uses base Field Notes §1-§9.
        # The privacy page keeps functional zn-privacy-* ids but must not load
        # the lesson stylesheet or any §10 component.
        for route, page in _public_html():
            html = page.read_text(encoding="utf-8")
            self.assertNotIn("assets/zivon.css", html, f"{route}: lesson stylesheet")
            for marker in LESSON_DEVICE_MARKERS:
                self.assertNotIn(marker, html, f"{route}: lesson device {marker!r}")
            self.assertNotIn("style=", html, f"{route}: inline style (CSP)")

    def test_no_official_affiliation_claims(self) -> None:
        forbidden = [
            "CBSE-approved",
            "CBSE approved",
            "official CBSE paper",
            "official CBSE question",
            "is affiliated with CBSE",
            "in partnership with CBSE",
        ]
        for route, page in _public_html():
            text = page.read_text(encoding="utf-8").lower()
            for phrase in forbidden:
                self.assertNotIn(
                    phrase.lower(), text, f"{route}: forbidden claim {phrase!r}"
                )

    def test_no_dead_form_or_payment_affordance(self) -> None:
        # Honest waitlist state: no form and no payment input until the backend
        # and accounts exist (F2/F11 handoff).
        for route in ("/pricing/", "/contact/"):
            html = PUBLIC_PAGES[route].read_text(encoding="utf-8")
            self.assertNotIn("<form", html.lower(), f"{route}: no dead form")
            self.assertNotIn('type="email"', html, f"{route}: no email field")
            self.assertNotIn('type="password"', html, f"{route}: no password field")

    def test_nginx_serves_the_catalogue_and_class_routes(self) -> None:
        nginx = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("location = /courses {", nginx)
        self.assertIn("try_files /catalogue/index.html =404;", nginx)
        for klass in (9, 10, 11, 12):
            self.assertRegex(
                nginx,
                rf"location = /courses/{klass}/physics\s+\{{ return 301 /class-{klass}-physics/; \}}",
            )

    def test_published_catalogue_entries_resolve(self) -> None:
        # Publish-flow contract (scripts/publish-frontend.sh): the repo copy of
        # courses.js IS the site manifest - every entry must resolve to a real
        # index.html with a manifest.json beside it (traceability), and every
        # topic directory on disk must be listed (a wholesale replacement never
        # leaves unlisted pages behind). Mirrors stage 11-link's publish smoke.
        if not (FRONTEND / "courses").is_dir():
            self.skipTest("no published catalogue in this checkout")
        courses_text = (FRONTEND / "courses.js").read_text(encoding="utf-8")
        entries = re.findall(r'"href":\s*"([^"]+)"', courses_text)
        self.assertTrue(entries, "courses/ exists but courses.js lists no entries")
        catalogue = json.loads(
            (FRONTEND / "catalogue.json").read_text(encoding="utf-8")
        )
        self.assertEqual(catalogue["catalogue_version"], 2)
        self.assertEqual(catalogue["integrity"]["status"], "ok", catalogue["integrity"])
        self.assertEqual(len(catalogue["topics"]), len(entries))
        locale_dirs = {"hi", "hi-Latn"}
        for href in entries:
            index = FRONTEND / href
            self.assertTrue(
                index.is_file(), f"courses.js entry resolves to nothing: {href}"
            )
            self.assertTrue(
                (index.parent / "manifest.json").is_file(),
                f"published page has no manifest.json: {index.parent}",
            )
        for topic in catalogue["topics"]:
            for locale, localized_href in topic.get("localized_hrefs", {}).items():
                self.assertTrue(
                    (FRONTEND / localized_href).is_file(),
                    f"catalogue localized href for {locale!r} resolves to nothing: "
                    f"{localized_href}",
                )
        listed = {str((FRONTEND / e).parent) for e in entries}
        on_disk: set[str] = set()
        localized: list[Path] = []
        for p in (FRONTEND / "courses").rglob("index.html"):
            if p.parent.name in locale_dirs:
                localized.append(p.parent)
            else:
                on_disk.add(str(p.parent))
        self.assertEqual(
            on_disk - listed, set(), "published topic not listed in courses.js"
        )
        for topic in localized:
            self.assertIn(
                str(topic.parent),
                listed,
                f"localized page for an unlisted topic: {topic}",
            )
            self.assertTrue(
                (topic.parent / "i18n" / f"{topic.name}.json").is_file(),
                f"localized page has no i18n bundle: {topic}",
            )

    def test_fonts_are_shipped_with_license(self) -> None:
        self.assertTrue(
            (FRONTEND / "assets" / "fonts").is_dir(), "fonts must ship locally"
        )
        self.assertTrue(
            (FRONTEND / "assets" / "FONTS-LICENSE.md").exists(),
            "bundled fonts require a license record",
        )


class TestPublicSiteBehaviour(unittest.TestCase):
    """Real Chromium against a static server over HTTP."""

    _pw: Any
    _browser: Any
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        cls._server = serve_static(FRONTEND)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()

    def _new_page(self, *, javascript: bool = True, width: int = 1280) -> tuple[Page, list[str]]:
        context = self._browser.new_context(
            viewport={"width": width, "height": 900},
            java_script_enabled=javascript,
        )
        page = context.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        return page, errors

    def test_landing_loads_clean_with_concept_a(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(f"{self._base_url}/")
            page.wait_for_timeout(500)
            self.assertEqual(errors, [], f"console/page errors on load: {errors}")
            self.assertEqual(page.evaluate("document.documentElement.lang"), "en")
            self.assertTrue(page.title().startswith("Zivon"))
            self.assertEqual(page.locator("h1").count(), 1)
            self.assertIn("Ask the page", page.locator("h1").inner_text())
            self.assertGreaterEqual(page.locator(".pen .uline").count(), 1)
            self.assertEqual(page.locator('a.btn[href="/courses"]').count(), 3)
            self.assertIn("not a recording", page.locator(".artifact-head .meta").first.inner_text())
            self.assertIn("16 N", page.locator(".artifact--tilt").inner_text())
            self.assertEqual(page.locator("[data-coverage] tbody tr").count(), 4)
            self.assertFalse(page.locator("[data-coverage]").is_hidden())
        finally:
            page.close()

    def test_landing_works_with_javascript_off(self) -> None:
        page, errors = self._new_page(javascript=False)
        try:
            page.goto(f"{self._base_url}/")
            self.assertIn("Ask the page", page.locator("h1").inner_text())
            self.assertIn("net force", page.locator(".artifact--tilt").inner_text())
            self.assertEqual(page.locator(".pen .uline").count(), 0)
            self.assertTrue(page.locator('a.btn[href="/courses"]').first.is_visible())
            self.assertIn("A video explains the step", page.locator(".pull").inner_text())
            self.assertIn("Is my voice recorded?", page.locator(".faq").inner_text())
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_catalogue_filters_searches_and_states(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(f"{self._base_url}/catalogue/")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 6)
            self.assertEqual(page.locator(".class-group-heading h3").count(), 2)
            self.assertIn("6 chapters live", page.locator("#catalogue-count").inner_text())
            self.assertIn("Class 10, Class 12", page.locator("#catalogue-coverage").inner_text())

            page.click('[data-class-filter="9"]')
            page.wait_for_timeout(100)
            self.assertEqual(page.locator(".chapter-card").count(), 2)
            self.assertIn("2 of 6 chapters shown", page.locator("#catalogue-count").inner_text())
            self.assertIn("Class 9", page.locator(".class-group-heading h3").first.inner_text())

            page.click('[data-class-filter="0"]')
            page.fill("#catalogue-search", "how forces")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 1)
            self.assertIn(
                "How Forces Affect Motion", page.locator(".chapter-card").inner_text()
            )
            self.assertIn("q=how+forces", page.url)

            page.fill("#catalogue-search", "zzzz")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 0)
            self.assertFalse(page.locator("#catalogue-empty").is_hidden())
            self.assertIn(
                "No chapter matches", page.locator("#catalogue-empty").inner_text()
            )

            page.click("#catalogue-clear")
            page.wait_for_timeout(200)
            self.assertEqual(page.locator(".chapter-card").count(), 6)
            self.assertEqual(errors, [], f"console/page errors: {errors}")
        finally:
            page.close()

    def test_catalogue_error_state_is_honest(self) -> None:
        page, errors = self._new_page()
        try:
            page.route(
                "**/courses.js",
                lambda route: route.fulfill(
                    status=200, body="", content_type="application/javascript"
                ),
            )
            page.goto(f"{self._base_url}/catalogue/")
            page.wait_for_timeout(200)
            self.assertFalse(page.locator("#catalogue-error").is_hidden())
            self.assertEqual(page.locator(".chapter-card").count(), 0)
            self.assertIn("did not load", page.locator("#catalogue-count").inner_text())
            self.assertEqual(page.locator("#catalogue-error a").get_attribute("href"), "/sitemap.xml")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_class_pages_render_live_and_empty_states(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(f"{self._base_url}/class-9-physics/")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 2)
            self.assertIn("2 chapters live", page.locator("#class-count").inner_text())
            self.assertTrue(page.locator("#class-empty").is_hidden())
            self.assertIn("Latest chapter published", page.locator("#class-latest").inner_text())

            page.goto(f"{self._base_url}/class-10-physics/")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 0)
            self.assertIn("No published chapter yet", page.locator("#class-count").inner_text())
            self.assertFalse(page.locator("#class-empty").is_hidden())

            page.goto(f"{self._base_url}/class-11-physics/")
            page.wait_for_timeout(300)
            self.assertEqual(page.locator(".chapter-card").count(), 4)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_every_public_page_loads_clean_at_360(self) -> None:
        for path in BROWSER_PAGES:
            page, errors = self._new_page(width=360)
            try:
                page.goto(f"{self._base_url}{path}")
                page.wait_for_timeout(300)
                self.assertEqual(errors, [], f"{path}: console/page errors: {errors}")
                self.assertEqual(page.locator("h1").count(), 1, f"{path}: one h1")
                overflow = page.evaluate(
                    "document.documentElement.scrollWidth > "
                    "document.documentElement.clientWidth"
                )
                self.assertFalse(overflow, f"{path}: horizontal overflow at 360 px")
            finally:
                page.close()

    def test_catalogue_lesson_links_resolve(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(f"{self._base_url}/catalogue/")
            page.wait_for_timeout(300)
            hrefs = page.eval_on_selector_all(
                ".chapter-card .chapter-title a", "els => els.map(e => e.getAttribute('href'))"
            )
            self.assertEqual(len(hrefs), 6)
            for href in hrefs:
                response = page.request.get(f"{self._base_url}{href}")
                self.assertEqual(response.status, 200, f"lesson link broke: {href}")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_accessibility_basics(self) -> None:
        page, errors = self._new_page()
        try:
            page.goto(f"{self._base_url}/catalogue/")
            page.wait_for_timeout(300)
            empty_links = page.evaluate(
                """() => Array.from(document.querySelectorAll('a')).filter(
                    (a) => !a.textContent.trim() && !a.getAttribute('aria-label')
                ).length"""
            )
            self.assertEqual(empty_links, 0, "every link needs an accessible name")
            self.assertEqual(page.locator("#catalogue-search").count(), 1)
            self.assertIsNotNone(
                page.evaluate(
                    "document.querySelector('label[for=\"catalogue-search\"]') ? 1 : null"
                )
            )
            self.assertEqual(
                page.evaluate(
                    "document.querySelector('#catalogue-count').getAttribute('aria-live')"
                ),
                "polite",
            )
            self.assertEqual(
                page.evaluate(
                    "document.querySelector('[data-class-filter]').tagName"
                ),
                "BUTTON",
            )
            self.assertEqual(errors, [])
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
