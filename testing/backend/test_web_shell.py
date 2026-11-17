"""Server-rendered web shell contract (`web/`, F0C).

Hermetic: SQLite in memory, the dev email sink, no network, no keys. Covers the
account guard (guest redirect, expired/garbage cookie, unavailable service),
the signed-in render, template/CSP/XSS contracts, and the nginx/Docker
wiring that makes `/app` reachable through the frontend image.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient
from starlette.requests import Request

from backend import BackendConfig, create_app
from web.context import (
    FlashMessage,
    ShellContext,
    ShellUser,
)
from web.nav import APP_NAV, PUBLIC_NAV, active_nav
from web.render import CSP_META, CSP_POLICY, csrf_field, render_page

REPO_ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "correct-horse-battery-staple"


class WebShellTests(unittest.TestCase):
    """The signed-in shell and its guard, against the real auth service."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=20,
            auth_register_per_min=20,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.templates = REPO_ROOT / "web" / "templates"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(
        self,
        *,
        email: str = "kid@example.com",
        display_name: str = "Asha",
        class_level: int | None = 9,
        language: str = "hi-IN",
    ) -> dict[str, Any]:
        response = self.client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": display_name,
                "class_level": class_level,
                "language": language,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        payload = self.client.get("/v1/auth/session").json()
        self.assertTrue(payload["authenticated"])
        return payload

    def _request(self, path: str = "/app") -> Request:
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "https",
            "path": path,
            "raw_path": path.encode("ascii"),
            "query_string": b"",
            "root_path": "",
            "headers": [],
            "client": ("127.0.0.1", 41000),
            "server": ("testserver", 443),
            "app": self.app,
        }
        return Request(scope)

    # -- guard --------------------------------------------------------------

    def test_guest_is_redirected_to_login_with_next(self) -> None:
        response = self.client.get("/app", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/app")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_redirect_preserves_the_query_in_next(self) -> None:
        response = self.client.get("/app?tab=today", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/login?next=/app%3Ftab%3Dtoday",
        )

    def test_garbage_cookie_is_a_guest_not_an_error(self) -> None:
        self.client.cookies.set("zivon_session", "not-a-real-token")
        response = self.client.get("/app", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/app")

    def test_unavailable_auth_service_renders_the_503_shell(self) -> None:
        self.app.state.auth = None
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 503)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn("Sign-in is temporarily unavailable", response.text)
        self.assertIn('class="site-head"', response.text)
        # The sign-in control would lead back into the failed service.
        self.assertNotIn(">Sign in<", response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_session_store_failure_renders_the_503_shell_not_json(self) -> None:
        class ExplodingAuth:
            def resolve(self, raw: str) -> None:
                del raw
                raise RuntimeError("session store down")

            def csrf_for(self, raw: str) -> str:
                del raw
                return "unused"

        self.client.cookies.set(self.cfg.auth_cookie_name, "any-token")
        self.app.state.auth = ExplodingAuth()
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 503)
        self.assertIn("text/html", response.headers["content-type"])
        self.assertIn('class="site-head"', response.text)
        self.assertNotIn('"code"', response.text)

    # -- signed-in render ---------------------------------------------------

    def test_authenticated_app_renders_the_shell_and_user_context(self) -> None:
        session = self.register(language="hi-IN", class_level=9)
        response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("Hello, Asha.", html)
        self.assertIn("Class 9 · CBSE · Hindi", html)
        self.assertIn("हिन्दी", html)
        # Sub-11px shell copy is English until the translation workstream, and
        # the page says so instead of silently mixing languages.
        self.assertIn("your Hindi choice is saved", html)

        # Base Field Notes §1-§9 chrome, from F1's public-site stylesheet.
        self.assertIn('class="shell shell--app"', html)
        self.assertIn('class="site-head"', html)
        self.assertIn('class="wrap page-head"', html)
        self.assertIn('class="site-foot"', html)
        self.assertIn('href="/assets/product.css"', html)
        self.assertIn('src="/assets/product.js"', html)
        self.assertIn('aria-current="page"', html)

        # Private page: noindex in the document and the response headers.
        self.assertIn('name="robots" content="noindex, nofollow"', html)
        self.assertIn("noindex", response.headers["x-robots-tag"])
        self.assertEqual(response.headers["cache-control"], "no-store")

        # The CSRF token is exposed for future forms; the session secrets are
        # not. `email`, `user_id`, and the raw cookie must never reach HTML.
        csrf_match = re.search(r'<meta name="csrf-token" content="([^"]+)">', html)
        assert csrf_match is not None, "shell must expose the CSRF token meta"
        self.assertEqual(csrf_match.group(1), session["csrf_token"])
        self.assertNotIn(session["user"]["user_id"], html)
        self.assertNotIn(session["user"]["email"], html)
        raw_cookie = self.client.cookies.get(self.cfg.auth_cookie_name)
        self.assertIsNotNone(raw_cookie)
        self.assertNotIn(raw_cookie, html)

    def test_shell_uses_no_lesson_page_devices(self) -> None:
        self.register()
        html = self.client.get("/app").text
        self.assertNotRegex(html, r"\bzn-[a-z0-9-]+")
        self.assertNotIn("zivon.css", html)
        self.assertNotIn("Caveat", html)

    def test_csp_header_and_meta_match_the_app_policy(self) -> None:
        self.register()
        response = self.client.get("/app")
        self.assertEqual(response.headers["content-security-policy"], CSP_POLICY)
        self.assertNotIn("unsafe-inline", response.headers["content-security-policy"])
        match = re.search(
            r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">',
            response.text,
        )
        assert match is not None, "shell must carry a meta CSP"
        self.assertEqual(match.group(1), CSP_META)

    def test_display_name_is_escaped(self) -> None:
        self.register(display_name="<script>alert(1)</script>")
        html = self.client.get("/app").text
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    # -- existing mounts stay intact ---------------------------------------

    def test_existing_routes_still_mount_alongside_the_shell(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        self.assertIn("/voice/ws", [getattr(r, "path", "") for r in self.app.routes])
        health = self.client.get("/v1/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")
        catalog = self.client.get("/v1/catalog")
        self.assertEqual(catalog.status_code, 200)
        session = self.client.get("/v1/auth/session")
        self.assertEqual(session.status_code, 200)
        self.assertFalse(session.json()["authenticated"])

    # -- shared context helpers --------------------------------------------

    def test_public_error_shell_renders_the_error_slot(self) -> None:
        shell = ShellContext.for_public(
            path="/app",
            page_title="Temporarily unavailable",
            error="A visible error line.",
            auth_available=False,
        )
        response = render_page(
            self._request(),
            "error.html",
            shell=shell,
            status_code=503,
            extra={"status_code": 503, "error_title": "Temporarily unavailable"},
        )
        html = bytes(response.body).decode("utf-8")
        self.assertEqual(response.status_code, 503)
        self.assertIn('role="alert"', html)
        self.assertIn("notice--error", html)
        self.assertIn("A visible error line.", html)
        self.assertNotIn(">Sign in<", html)

    def test_shell_user_exposes_only_display_context(self) -> None:
        user = ShellUser.from_user(
            {
                "user_id": "01user",
                "email": "kid@example.com",
                "display_name": " Asha ",
                "class_level": 9,
                "board": None,
                "language": "hi-IN",
            }
        )
        self.assertEqual(user.display_name, "Asha")
        self.assertEqual(user.class_label, "Class 9")
        self.assertEqual(user.board, "CBSE")
        self.assertEqual(user.language, "hi")
        self.assertEqual(user.account_line, "Class 9 · Hindi")
        self.assertFalse(hasattr(user, "email"))
        self.assertFalse(hasattr(user, "user_id"))
        self.assertFalse(hasattr(user, "session"))

    def test_class_and_language_fallbacks_are_honest(self) -> None:
        hinglish = ShellUser.from_user({"class_level": 10, "language": "hinglish"})
        self.assertEqual(hinglish.class_label, "Class 10")
        self.assertEqual(hinglish.language, "hi-Latn")
        self.assertEqual(hinglish.language_name, "Hinglish")
        self.assertIn("your Hinglish choice is saved", hinglish.language_note or "")

        guest_class = ShellUser.from_user({"class_level": None, "language": "ta-IN"})
        self.assertEqual(guest_class.class_label, "Class not set")
        self.assertEqual(guest_class.language, "en")
        self.assertIn("not built", guest_class.language_note or "")

    def test_nav_active_item_is_the_most_specific_match(self) -> None:
        self.assertEqual(active_nav("/app", APP_NAV), "dashboard")
        self.assertEqual(active_nav("/app/progress", APP_NAV), "dashboard")
        self.assertEqual(active_nav("/courses", APP_NAV), "courses")
        self.assertIsNone(active_nav("/app", PUBLIC_NAV))
        self.assertEqual(active_nav("/method/", PUBLIC_NAV), "method")

    def test_flash_message_rejects_a_non_notice_kind(self) -> None:
        with self.assertRaises(ValueError):
            FlashMessage("x", kind="danger")

    def test_csrf_field_escapes_the_token(self) -> None:
        markup = str(csrf_field('"><x'))
        self.assertNotIn('"><x', markup)
        self.assertIn("&#34;&gt;&lt;x", markup)
        self.assertEqual(str(csrf_field(None)), "")


class WebShellStaticContracts(unittest.TestCase):
    """Templates, nginx, and image wiring, checked without a browser."""

    def setUp(self) -> None:
        self.templates = REPO_ROOT / "web" / "templates"

    def test_every_page_template_extends_the_base_shell(self) -> None:
        pages = list((self.templates / "app").rglob("*.html")) + [
            self.templates / "error.html"
        ]
        self.assertTrue(pages)
        for path in pages:
            body = path.read_text(encoding="utf-8")
            self.assertIn('{% extends "base.html" %}', body, path.name)

    def test_base_shell_links_f1_assets_and_is_noindex(self) -> None:
        base = (self.templates / "base.html").read_text(encoding="utf-8")
        self.assertIn('href="/assets/product.css"', base)
        self.assertIn('src="/assets/product.js"', base)
        self.assertNotIn("zivon.css", base)
        self.assertIn('name="robots" content="noindex, nofollow"', base)
        self.assertIn("csrf-token", base)

    def test_templates_have_no_inline_script_style_or_handlers(self) -> None:
        for path in self.templates.rglob("*.html"):
            text = path.read_text(encoding="utf-8")
            for tag in re.findall(r"<script\b[^>]*>", text, re.IGNORECASE):
                self.assertIn("src=", tag, f"{path.name}: inline script")
            self.assertNotIn("<style", text.lower(), f"{path.name}: <style>")
            self.assertNotRegex(text, r"\sstyle\s*=", f"{path.name}: style attr")
            self.assertNotRegex(
                text,
                r"\son(?:click|change|submit|load|error)\s*=",
                f"{path.name}: inline handler",
            )

    def test_nginx_proxies_app_and_login_with_cookies_and_scoped_csp(self) -> None:
        nginx = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        for location in (
            "location = /app {",
            "location ^~ /app/ {",
            "location = /login {",
        ):
            self.assertIn(location, nginx)
        block = self._nginx_block(nginx, "location = /app {")
        self.assertIn(CSP_POLICY, block)
        self.assertIn("proxy_pass http://core-backend:8000;", block)
        self.assertIn("proxy_set_header Host $http_host;", block)
        self.assertIn("proxy_set_header X-Real-IP $remote_addr;", block)
        self.assertIn("proxy_set_header X-Forwarded-For", block)
        self.assertIn("proxy_set_header X-Forwarded-Proto", block)
        self.assertIn('Cache-Control "no-store"', block)
        self.assertIn('X-Robots-Tag "noindex, nofollow"', block)
        # Cookie and Set-Cookie pass through by default; a rewrite here would
        # silently break the HttpOnly session on every app page.
        self.assertNotIn("proxy_set_header Cookie", block)
        self.assertNotIn("proxy_hide_header Set-Cookie", block)
        login_block = self._nginx_block(nginx, "location = /login {")
        self.assertIn("proxy_pass http://core-backend:8000;", login_block)
        self.assertIn(CSP_POLICY, login_block)

    def test_backend_image_and_requirements_carry_the_web_shell(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile.backend").read_text(encoding="utf-8")
        self.assertIn("COPY web ./web", dockerfile)
        backend_req = (REPO_ROOT / "backend" / "requirements.txt").read_text(
            encoding="utf-8"
        )
        self.assertIn("jinja2==3.1.6", backend_req)
        root_req = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("jinja2==3.1.6", root_req)

    @staticmethod
    def _nginx_block(nginx: str, opener: str) -> str:
        pattern = re.escape(opener) + r"(.*?)\n    \}"
        match = re.search(pattern, nginx, re.DOTALL)
        if match is None:
            raise AssertionError(f"nginx block not found: {opener}")
        return match.group(1)


if __name__ == "__main__":
    unittest.main()
