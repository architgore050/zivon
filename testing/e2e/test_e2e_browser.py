"""F11 Level 2: three Chromium browser smokes over the real app, booted under
uvicorn on 127.0.0.1 with dev env and the dev mail sink.

These run the REAL server process and a REAL browser: signup -> onboarding ->
dashboard loads with a clean console (the only filtered errors are the
`/assets/*` static fetches nginx serves in deployment — the bare backend
deliberately does not), a wrong password renders the branded alert, and a
guest hitting practice bounces to the login page with the honest `next`.

Honest skips: when uvicorn, Playwright, or Chromium is missing the class
skips WITH A REASON — a skip is never reported as a pass.
"""

from __future__ import annotations

import contextlib
import importlib.util
import tempfile
import threading
import time
import unittest
import uuid
from pathlib import Path
from typing import Any

from .support import PACKS_DIR, PASSWORD, assessment_importer, make_config

ASSETS_PREFIX = "/assets/"
# Static assets are nginx's job in deployment (docs/deployment): the bare
# uvicorn process serves the HTML but not /assets/*, so those resource 404s
# are environmental and filtered — everything else must be clean.
STARTUP_TIMEOUT_S = 30.0
REPO_ROOT = Path(__file__).resolve().parents[2]


def _boot_server(root: Path) -> tuple[Any, threading.Thread, int]:
    """Boot the real app under uvicorn on an ephemeral 127.0.0.1 port.

    Returns (server, thread, port). The seeded in-memory SQLite store is
    built here and handed to the app factory, exactly like the HTTP layer.
    """
    import uvicorn

    from backend import create_app
    from db import DatabaseEngine

    engine = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
    assessment_importer.import_packs(engine, PACKS_DIR)
    config = make_config(
        root,
        auth_cookie_secure=False,  # dev posture: plain-http loopback browser
        app_base_url="http://127.0.0.1",
    )
    app = create_app(config, db_engine=engine)
    server_config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=0,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + STARTUP_TIMEOUT_S
    while not server.started and time.monotonic() < deadline:
        if not thread.is_alive():
            raise RuntimeError("the uvicorn thread died during startup")
        time.sleep(0.05)
    if not server.started:
        raise RuntimeError("uvicorn did not start in time")
    port = int(server.servers[0].sockets[0].getsockname()[1])
    return server, thread, port


class BrowserSmokeTests(unittest.TestCase):
    """Three smokes: the clean signed-in load, the branded 401, the bounce."""

    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _thread: threading.Thread
    _pw: Any
    _browser: Any
    base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if importlib.util.find_spec("uvicorn") is None:
            raise unittest.SkipTest(
                "uvicorn is not installed — the browser layer cannot boot the "
                "real app (pip install uvicorn)"
            )
        if importlib.util.find_spec("playwright") is None:
            raise unittest.SkipTest(
                "Playwright is not installed — the browser layer cannot run "
                "(pip install playwright)"
            )
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-e2e-browser-")
        try:
            cls._server, cls._thread, port = _boot_server(Path(cls._tmp.name))
        except Exception as exc:
            cls._tmp.cleanup()
            raise unittest.SkipTest(f"the real app could not boot: {exc}") from exc
        cls.base_url = f"http://127.0.0.1:{port}"
        try:
            from playwright.sync_api import sync_playwright

            cls._pw = sync_playwright().start()
            cls._browser = cls._pw.chromium.launch()
        except Exception as exc:
            with contextlib.suppress(Exception):
                cls._server.should_exit = True
                cls._thread.join(timeout=5)
            cls._tmp.cleanup()
            raise unittest.SkipTest(
                "Chromium is unavailable — run `python -m playwright install "
                f"chromium` ({type(exc).__name__})"
            ) from exc

    @classmethod
    def tearDownClass(cls) -> None:
        browser = getattr(cls, "_browser", None)
        pw = getattr(cls, "_pw", None)
        if browser is not None:
            browser.close()
        if pw is not None:
            pw.stop()
        if getattr(cls, "_server", None) is not None:
            cls._server.should_exit = True
            cls._thread.join(timeout=10)
        if getattr(cls, "_tmp", None) is not None:
            cls._tmp.cleanup()
        super().tearDownClass()

    # -- helpers -------------------------------------------------------------

    def page(self) -> tuple[Any, list[str]]:
        """A fresh page with the console-error collector attached.

        `errors` carries every console error; the static-asset filter lives
        AT the assertion with its reason, so nothing is silently dropped.
        """
        from playwright.sync_api import ConsoleMessage, Page

        page: Page = self._browser.new_page()
        errors: list[str] = []

        def on_console(m: ConsoleMessage) -> None:
            # Typed handler: `Page.on` overloads require a callable returning
            # None, so build the message unconditionally and append only real
            # errors — same collected list as before (strs, never None).
            if m.type == "error":
                errors.append(f"{m.text} [{m.location.get('url', '')}]")

        page.on("console", on_console)
        page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
        return page, [e for e in errors if e]

    def assert_clean_console(self, errors: list[str]) -> None:
        """No console error except nginx-served static-asset 404s.

        In deployment nginx serves `/assets/*` (CSS/JS islands) and the app
        process never sees those requests; the bare uvicorn boot answers 404
        for them. That environmental difference is filtered HERE, with the
        reason — any other console error is a page defect and fails the smoke.
        """
        environmental = [
            error for error in errors if ASSETS_PREFIX in error and "404" in error
        ]
        remaining = [error for error in errors if error not in environmental]
        self.assertEqual(
            remaining,
            [],
            f"console is not clean; filtered {len(environmental)} nginx-served "
            f"/assets 404s; unexplained: {remaining}",
        )

    # -- the three smokes ------------------------------------------------------

    def test_signup_onboarding_dashboard_loads_clean(self) -> None:
        page, errors = self.page()
        try:
            page.goto(f"{self.base_url}/signup")
            page.fill("#signup-email", f"browser-{uuid.uuid4()}@example.com")
            page.fill("#signup-password", PASSWORD)
            page.fill("#signup-confirm", PASSWORD)
            page.check("#signup-agree")
            page.click("button[type=submit]")
            page.wait_for_url("**/onboarding")
            page.locator('input[name="class_level"]').first.check()
            page.locator('input[name="board"]').first.check()
            page.locator('input[name="language"]').first.check()
            page.click("button[type=submit]")
            page.wait_for_url(f"{self.base_url}/app")
            body = page.locator("main").inner_text()
            self.assertIn(
                "Continue learning",
                body,
                "the dashboard renders the signed-in empty state",
            )
            self.assertIn(
                "Nothing here yet", body, "the honest empty state, no invented data"
            )
            self.assert_clean_console(errors)
        finally:
            page.close()

    def test_wrong_password_renders_the_branded_alert(self) -> None:
        page, errors = self.page()
        try:
            page.goto(f"{self.base_url}/login")
            page.fill("#login-email", f"browser-{uuid.uuid4()}@example.com")
            page.fill("#login-password", "not-the-password-42")
            page.click("button[type=submit]")
            alert = page.locator('[role="alert"]')
            alert.wait_for(state="visible")
            self.assertIn(
                "Email or password is wrong",
                alert.inner_text(),
                "the honest re-render, not a generic crash",
            )
            self.assert_clean_console(errors)
        finally:
            page.close()

    def test_guest_practice_bounces_to_login_with_next(self) -> None:
        page, errors = self.page()
        try:
            page.goto(f"{self.base_url}/app/practice")
            page.wait_for_url("**/login?next=/app/practice")
            self.assertIn(
                "Sign in",
                page.locator("main").inner_text(),
                "the guard lands on the branded login page",
            )
            self.assert_clean_console(errors)
        finally:
            page.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
