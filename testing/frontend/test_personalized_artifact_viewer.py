"""PL3 artifact-viewer host-bridge tests (frontend/assets/personalized-artifact.js).

The artifact document is untrusted generated code; this module drives the REAL
host bridge in headless Chromium with a stub artifact document served from a
file URL and asserts the §5.4/§4 contracts:

- the created iframe carries exactly `sandbox="allow-scripts"` (opaque origin),
  `allow=""`, `referrerpolicy="no-referrer"`;
- a harness `ready` message from the frame clears the status region;
- a message from a foreign window is ignored;
- the watchdog unloads the frame and shows the fallback when no `ready`
  arrives (the interval is configurable via data-watchdog-ms for tests);
- a second load event (the self-navigation tell) unloads the frame;
- the report action dispatches the `zivon-artifact:report` event the session
  page JS (PL4) binds to `/v1/reports`.

Needs a Playwright browser once:  python -m playwright install chromium
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
VIEWER_JS_URI = (
    (REPO_ROOT / "frontend" / "assets" / "personalized-artifact.js").resolve().as_uri()
)
STUB_ARTIFACT_URI = (
    (
        REPO_ROOT
        / "evals"
        / "goldens"
        / "personalized"
        / "artifacts"
        / "good-concave-mirror.html"
    )
    .resolve()
    .as_uri()
)


def viewer_page(src: str = STUB_ARTIFACT_URI, extra_attr: str = "") -> str:
    """A host page carrying one artifact viewer (the PL3 partial's markup)."""
    return (
        "<!doctype html><html><head><meta charset='utf-8'></head><body>"
        "<div class='zn-art-viewer' data-artifact-viewer "
        "data-artifact-id='art123' data-artifact-kind='simulation' "
        "data-artifact-status='ready' "
        f"data-artifact-src='{src}' "
        "data-status-url='' data-chapter-id='class-10-light' "
        "data-fallback-kind='text'"
        f" {extra_attr} >"
        "<div class='zn-art-viewer-head'>"
        "<h3 class='zn-art-viewer-title'>Concave mirror</h3></div>"
        "<div class='zn-art-viewer-frame' data-art-frame hidden></div>"
        "<div class='zn-art-viewer-fallback' data-art-fallback hidden>"
        "<p class='zn-art-viewer-fallback-note' data-art-fallback-note></p>"
        "<div class='zn-art-viewer-fallback-body' data-art-fallback-body></div>"
        "</div>"
        "<p class='zn-art-viewer-status' data-art-status role='status' aria-live='polite'>"
        "Building a visual…</p>"
        "<div class='zn-art-viewer-actions'>"
        "<button type='button' data-art-action='reload'>Reload</button>"
        "<button type='button' data-art-action='pause'>Pause</button>"
        "<button type='button' data-art-action='report'>Report</button>"
        "</div>"
        "<p class='zn-art-viewer-meta'>Runs isolated — no network, no access to your account.</p>"
        "</div>"
        f"<script src='{VIEWER_JS_URI}'></script></body></html>"
    )


class ArtifactViewerBridgeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch()
        # The host page must be a real file so the file:// viewer script is
        # same-origin loadable (about:blank cannot fetch file: scripts).
        self._tmp = tempfile.TemporaryDirectory()
        self._host = Path(self._tmp.name) / "host.html"
        self._host.write_text(viewer_page(), encoding="utf-8")

    def tearDown(self) -> None:
        self._browser.close()
        self._pw.stop()
        self._tmp.cleanup()

    def _page(self, html: str | None = None) -> Any:
        page = self._browser.new_page(viewport={"width": 640, "height": 480})
        if html is None:
            page.goto(self._host.as_uri(), wait_until="load")
        else:
            target = Path(self._tmp.name) / "variant.html"
            target.write_text(html, encoding="utf-8")
            page.goto(target.as_uri(), wait_until="load")
        return page

    def test_iframe_carries_the_exact_sandbox_contract(self) -> None:
        page = self._page()
        page.wait_for_selector("[data-art-frame] iframe", state="attached")
        attrs = page.evaluate(
            "() => { const f = document.querySelector('[data-art-frame] iframe');"
            " return {sandbox: f.getAttribute('sandbox'), allow: f.getAttribute('allow'),"
            " referrer: f.getAttribute('referrerpolicy'), loading: f.getAttribute('loading')}; }"
        )
        self.assertEqual(attrs["sandbox"], "allow-scripts")
        self.assertNotIn("allow-same-origin", attrs["sandbox"] or "")
        self.assertEqual(attrs["allow"], "")
        self.assertEqual(attrs["referrer"], "no-referrer")
        self.assertEqual(attrs["loading"], "lazy")
        page.close()

    def test_harness_ready_clears_the_status_region(self) -> None:
        page = self._page()
        page.wait_for_function(
            "() => { const el = document.querySelector('[data-art-status]');"
            " return el && el.textContent === ''; }",
            timeout=8000,
        )
        page.close()

    def test_foreign_window_message_is_ignored(self) -> None:
        page = self._page(viewer_page(src="about:blank"))
        page.evaluate(
            "() => { window.postMessage({source: 'zivon-artifact', v: 1,"
            " type: 'ready'}, '*'); }"
        )
        page.wait_for_timeout(300)
        # The foreign message is ignored: the ready path never ran, so the
        # status region is never cleared.
        status = page.inner_text("[data-art-status]")
        self.assertNotEqual(status.strip(), "")
        page.close()

    def test_watchdog_shows_the_fallback_when_ready_never_arrives(self) -> None:
        # A document that never posts ready (blank), with a shrunken watchdog.
        page = self._page(
            viewer_page(src="about:blank", extra_attr="data-watchdog-ms='600'")
        )
        page.wait_for_selector("[data-art-fallback]:not([hidden])", timeout=8000)
        note = page.inner_text("[data-art-fallback-note]")
        self.assertIn("The visual didn", note)
        self.assertIn("load", note)
        frame_hidden = page.evaluate(
            "() => document.querySelector('[data-art-frame]').hidden"
        )
        self.assertTrue(frame_hidden)
        page.close()

    def test_self_navigation_second_load_unloads_the_frame(self) -> None:
        # The stub artifact navigates itself once after ready: the host must
        # treat the second load as a crash and unload the frame.
        page = self._page(
            viewer_page(src=STUB_ARTIFACT_URI, extra_attr="data-watchdog-ms='6000'")
        )
        # A second load event on the SAME frame is the §5.4 self-navigation
        # tell: the host unloads the frame and shows the fallback.
        page.evaluate(
            "() => { const f = document.querySelector('[data-art-frame] iframe');"
            " f.dispatchEvent(new Event('load')); }"
        )
        page.wait_for_selector("[data-art-fallback]:not([hidden])", timeout=8000)
        iframe_gone = page.evaluate(
            "() => !document.querySelector('[data-art-frame] iframe')"
        )
        self.assertTrue(iframe_gone)
        page.close()

    def test_report_action_dispatches_the_report_event(self) -> None:
        page = self._page()
        page.evaluate(
            "() => { window.__reports = []; document.addEventListener("
            "'zivon-artifact:report', (e) => window.__reports.push(e.detail)); }"
        )
        page.click("[data-art-action='report']")
        reports = page.evaluate("() => window.__reports")
        self.assertEqual(len(reports), 1)
        self.assertEqual(reports[0]["artifactId"], "art123")
        self.assertEqual(reports[0]["chapterId"], "class-10-light")
        page.close()

    def test_mount_is_idempotent(self) -> None:
        page = self._page(viewer_page(src="about:blank"))
        page.evaluate("() => window.ZivonArtifactViewer.mount(document)")
        page.evaluate("() => window.ZivonArtifactViewer.mount(document)")
        frames = page.evaluate(
            "() => document.querySelectorAll('[data-art-frame] iframe').length"
        )
        self.assertEqual(frames, 1)
        page.close()


if __name__ == "__main__":
    unittest.main()
