"""Unit tests for factory/shots.py (rendered-screenshot capture for 09-review).

Capture is best-effort by contract: the design reviewer goes text-only
whenever playwright is missing or a render fails, so the failure paths
(the []-on-error guarantees) are pinned alongside the happy path. All
browser interaction is mocked - these tests never launch Chromium.
"""

import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import shots

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"fake-screenshot-payload"


class _FakeElement:
    def screenshot(self, path: str) -> None:
        Path(path).write_bytes(PNG_BYTES)


class _FakePage:
    def __init__(self, regions: dict[str, int]) -> None:
        self._regions = regions
        self.viewport = None
        self.closed = False

    def goto(self, url: str) -> None:
        pass

    def wait_for_timeout(self, ms: int) -> None:
        pass

    def query_selector_all(self, sel: str) -> list[_FakeElement]:
        return [_FakeElement() for _ in range(self._regions.get(sel, 0))]

    def close(self) -> None:
        self.closed = True


class _FakeBrowser:
    def __init__(self, regions: dict[str, int]) -> None:
        self._regions = regions
        self.pages: list[_FakePage] = []

    def new_page(self, viewport=None, **_kw):
        page = _FakePage(self._regions)
        page.viewport = viewport
        self.pages.append(page)
        return page

    def close(self) -> None:
        pass


class _FakeChromium:
    """Mirrors playwright's browser object: `.chromium.launch()`."""

    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser

    def launch(self) -> _FakeBrowser:
        return self._browser


class _FakePlaywright:
    def __init__(self, browser: _FakeBrowser) -> None:
        self.chromium = _FakeChromium(browser)


class _FakeSyncPlaywright:
    """Context-manager factory mirroring playwright's sync API."""

    def __init__(self, browser: _FakeBrowser) -> None:
        self._browser = browser

    def __call__(self):
        return self

    def __enter__(self) -> _FakePlaywright:
        return _FakePlaywright(self._browser)

    def __exit__(self, *args) -> None:
        pass


def _install(fake=None) -> None:
    module: Any = types.ModuleType("playwright")
    inner: Any = types.ModuleType("playwright.sync_api")
    if fake is not None:
        inner.sync_playwright = fake
    module.sync_api = inner
    sys.modules["playwright"] = module
    sys.modules["playwright.sync_api"] = inner


class TestShotsCapture(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.topic = self.tmp / "topic"
        self.topic.mkdir()
        (self.topic / "index.html").write_text("<html></html>", encoding="utf-8")
        self.out = self.tmp / "shots"

    def tearDown(self):
        sys.modules.pop("playwright", None)
        sys.modules.pop("playwright.sync_api", None)

    def test_missing_index_page_returns_empty(self):
        (self.topic / "index.html").unlink()
        _install(_FakeSyncPlaywright(_FakeBrowser({})))
        self.assertEqual(shots.capture(self.topic, self.out), [])

    def test_playwright_missing_returns_empty(self):
        sys.modules["playwright"] = None  # makes the import inside capture fail
        self.assertEqual(shots.capture(self.topic, self.out), [])

    def test_browser_failure_returns_empty(self):
        def boom():  # sync_playwright factory that fails on entry
            raise RuntimeError("no chromium here")

        _install(boom)
        self.assertEqual(shots.capture(self.topic, self.out), [])

    def test_capture_writes_every_visual_at_every_frame(self):
        browser = _FakeBrowser(
            {".zn-header": 1, "figure.zn-diagram": 2, "section.zn-sim": 1}
        )
        _install(_FakeSyncPlaywright(browser))
        manifest = shots.capture(self.topic, self.out)
        self.assertEqual(len(manifest), 4 * len(shots.VIEWPORTS))
        widths = {m["width"] for m in manifest}
        self.assertEqual(widths, set(shots.VIEWPORTS))
        for m in manifest:
            assert Path(m["path"]).read_bytes() == PNG_BYTES, m["label"]
            self.assertEqual(m["bytes"], len(PNG_BYTES))
        # browser got one page per viewport with the right sizes
        self.assertEqual(
            [p.viewport["width"] for p in browser.pages], list(shots.VIEWPORTS)
        )
        self.assertTrue(all(p.closed for p in browser.pages))
        # manifest is persisted next to the PNGs
        saved = json.loads((self.out / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["shots"], manifest)
        # screenshots are EVIDENCE: never inside the topic dir
        self.assertEqual(list(self.topic.glob("*.png")), [])

    def test_vision_parts_shape(self):
        shot = {
            "path": str(self.out / "s.png"),
            "width": 1280,
            "label": "diagram#1 @ 1280px",
            "bytes": len(PNG_BYTES),
        }
        (self.out / "s.png").parent.mkdir(parents=True, exist_ok=True)
        Path(shot["path"]).write_bytes(PNG_BYTES)
        parts = shots.vision_parts([shot])
        self.assertEqual(parts[0], {"type": "text", "text": "[diagram#1 @ 1280px]"})
        self.assertEqual(parts[1]["type"], "image_url")
        self.assertTrue(
            parts[1]["image_url"]["url"].startswith("data:image/png;base64,")
        )


if __name__ == "__main__":
    unittest.main()
