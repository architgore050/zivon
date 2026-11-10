"""Unit tests for the harness Chromium launch arguments.

The perf harness loads staged pages from ``file://``. Chromium gives those
documents an opaque origin, so CORS-required subresources (the shell's woff2
font preloads, @font-face) are blocked - a test-transport artifact, since
production serves the same files over HTTP(S). The harness therefore launches
with ``--allow-file-access-from-files``; this test guards that flag, because
losing it silently turns font CORS errors into perf-gate failures.

No real browser is launched here.
"""

import sys
import types
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from testing.content_factory.perf import harness


class FakeChromium:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.browser = object()

    def launch(self, **kwargs):
        self.calls.append(kwargs)
        return self.browser


class TestLaunchArgs(unittest.TestCase):
    def test_launch_enables_file_access_for_file_urls(self):
        chromium = FakeChromium()
        playwright = types.SimpleNamespace(chromium=chromium)

        browser = harness._launch(playwright)

        self.assertIs(browser, chromium.browser)
        self.assertEqual(len(chromium.calls), 1)
        call = chromium.calls[0]
        self.assertTrue(call["headless"])
        self.assertIn("--allow-file-access-from-files", call["args"])

    def test_launch_copies_the_flag_list(self):
        # _launch must hand Chromium a copy: a mutated list must not leak into
        # the module constant and change every later profile run.
        chromium = FakeChromium()
        harness._launch(types.SimpleNamespace(chromium=chromium))
        chromium.calls[0]["args"].append("--mutated")
        self.assertNotIn("--mutated", harness.CHROMIUM_LAUNCH_ARGS)


if __name__ == "__main__":
    unittest.main()
