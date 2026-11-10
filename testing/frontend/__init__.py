"""Frontend tests: site shell contract, behaviour layer, perf budgets, and SEO.

Browser coverage requires Playwright. There is deliberately NO Selenium/psutil
fallback: a silent shim hides a broken environment and tests a different browser
stack than CI. If Playwright is missing, import fails loudly with the fix:

    pip install playwright
    python -m playwright install chromium
"""

from __future__ import annotations

import contextlib
import functools
import http.server
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Any

try:
    import playwright.sync_api  # noqa: F401
except ModuleNotFoundError as exc:  # pragma: no cover - environment guard
    raise ModuleNotFoundError(
        "The frontend test suite needs Playwright. Install it with:\n"
        "    pip install playwright\n"
        "    python -m playwright install chromium\n"
        "Then re-run: python -m unittest discover -s testing/frontend -t ."
    ) from exc


class _StaticHandler(http.server.SimpleHTTPRequestHandler):
    """Quiet static handler for browser tests (no request logging)."""

    def log_message(self, format: str, *args: Any) -> None:
        pass


@contextlib.contextmanager
def serve_static(root: str | Path) -> Iterator[str]:
    """Serve ``root`` over HTTP and yield its base URL.

    Browser tests load the shell from ``file://`` by default, and Chromium
    refuses ``@font-face``/``<link rel=preload crossorigin>`` fetches from an
    opaque ``file://`` origin ("blocked by CORS policy"). Real deployments are
    HTTP(S), so the font pipeline (and the perf budgets that measure it) is
    only honest over HTTP: every browser test that asserts a clean console or
    a load budget goes through this server.
    """
    handler = functools.partial(_StaticHandler, directory=str(root))
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=10)
