"""F2 guest auth screens: render, validation, CSRF, rate limits, reset/verify.

Hermetic: SQLite in memory, the dev email sink, no network, no keys. Google is
never called from these tests; the one Google-related check reads the callback's
error-redirect contract on `/login?error=...`.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from testing.backend.web_auth_support import (
    NEW_PASSWORD,
    PASSWORD,
    WebAuthSupport,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "web" / "templates"


class LoginPageTests(WebAuthSupport):
    def test_login_page_renders_one_paper_card_with_fields_and_alternatives(
        self,
    ) -> None:
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn('class="auth-card"', html)
        self.assertIn('action="/login"', html)
        self.assertIn('name="email"', html)
        self.assertIn('name="password"', html)
        self.assertIn('autocomplete="current-password"', html)
        self.assertIn("Continue with Google", html)
        self.assertIn('href="/signup"', html)
        self.assertIn("Continue as guest", html)
        self.assertIn("/assets/auth.css", html)
        self.assertIn("/assets/auth.js", html)
        self.assertIn('name="robots" content="noindex, nofollow"', html)
        self.assertEqual(response.headers["cache-control"], "no-store")
        # One paper card, no §10 lesson device.
        self.assertNotIn("zivon.css", html)
        self.assertNotRegex(html, r"\bzn-[a-z0-9-]+")

    def test_guest_form_cookie_is_http_only_and_samesite_lax(self) -> None:
        response = self.client.get("/login")
        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "path=/"):
            self.assertIn(flag, cookie)
        self.assertIn("zivon_form_token", cookie)

    def test_login_screen_maps_google_callback_errors_without_echoing_a_code(
        self,
    ) -> None:
        html = self.client.get("/login?error=E-EMAIL-UNVERIFIED").text
        self.assertIn("Google did not confirm that email address", html)
        self.assertNotIn("E-EMAIL-UNVERIFIED", html)
        unknown = self.client.get("/login?error=whatever").text
        self.assertIn("Google sign-in could not be completed", unknown)

    def test_login_page_shows_safe_next_and_drops_a_foreign_host(self) -> None:
        html = self.client.get("/login?next=/app/practice/sess-1").text
        self.assertIn('name="next" value="/app/practice/sess-1"', html)
        evil = self.client.get("/login?next=//evil.example/steal").text
        self.assertIn('name="next" value="/app"', evil)
        self.assertNotIn("evil.example", evil)

    def test_signed_in_visitor_is_sent_on_instead_of_seeing_the_form(self) -> None:
        self.register_via_api()
        response = self.client.get("/login?next=/app/settings", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/app/settings")


class LoginSubmitTests(WebAuthSupport):
    def test_login_succeeds_and_sets_a_working_session(self) -> None:
        self.register_via_api(email="kid@example.com")
        self.client.cookies.clear()
        token = self.guest_form("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "Kid@Example.com",
                "password": PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/app")
        self.assertIn("zivon_session", response.headers["set-cookie"])
        self.assertTrue(self.is_signed_in())

    def test_wrong_password_and_unknown_email_look_identical(self) -> None:
        self.register_via_api(email="kid@example.com")
        self.client.cookies.clear()
        token = self.guest_form("/login")
        wrong = self.client.post(
            "/login",
            data={"csrf_token": token, "email": "kid@example.com", "password": "nope"},
        )
        unknown = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "ghost@example.com",
                "password": "nope",
            },
        )
        for response in (wrong, unknown):
            self.assertEqual(response.status_code, 401)
            self.assertIn("Email or password is wrong", response.text)
        self.assertFalse(self.is_signed_in())

    def test_missing_fields_re_render_with_aria_linked_errors(self) -> None:
        token = self.guest_form("/login")
        response = self.client.post(
            "/login", data={"csrf_token": token, "email": "", "password": ""}
        )
        self.assertEqual(response.status_code, 422)
        html = response.text
        self.assertIn('aria-invalid="true"', html)
        self.assertIn('aria-describedby="login-email-error"', html)
        self.assertIn('id="login-email-error"', html)
        self.assertIn("Enter your email address.", html)
        self.assertIn('role="alert"', html)

    def test_submitted_password_is_never_echoed_back(self) -> None:
        token = self.guest_form("/login")
        html = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "kid@example.com",
                "password": "leak-me-not-please",
            },
        ).text
        self.assertNotIn("leak-me-not-please", html)

    def test_guest_csrf_is_rejected_without_the_matching_cookie(self) -> None:
        token = self.guest_form("/login")
        self.client.cookies.clear()
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "kid@example.com",
                "password": PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)
        self.assertFalse(self.is_signed_in())

    def test_a_form_can_be_retried_after_a_validation_error(self) -> None:
        token = self.guest_form("/login")
        first = self.client.post(
            "/login", data={"csrf_token": token, "email": "", "password": ""}
        )
        self.assertEqual(first.status_code, 422)
        self.client.post(
            "/v1/auth/register",
            json={"email": "kid@example.com", "password": PASSWORD},
        )
        self.client.cookies.clear()
        token = self.guest_form("/login")
        response = self.client.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "kid@example.com",
                "password": PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_next_is_honoured_only_for_same_origin_paths(self) -> None:
        self.register_via_api(email="kid@example.com")
        for submitted, expected in (
            ("/app/practice/sess-1", "/app/practice/sess-1"),
            ("//evil.example/x", "/app"),
            ("https://evil.example/x", "/app"),
            ("/\\evil", "/app"),
        ):
            self.client.cookies.clear()
            token = self.guest_form("/login")
            response = self.client.post(
                "/login",
                data={
                    "csrf_token": token,
                    "email": "kid@example.com",
                    "password": PASSWORD,
                    "next": submitted,
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], expected, submitted)

    def test_unavailable_auth_service_renders_the_503_shell(self) -> None:
        self.app.state.auth = None
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 503)
        self.assertIn("Sign-in is temporarily unavailable", response.text)


class SignupTests(WebAuthSupport):
    def test_signup_creates_the_account_and_moves_to_onboarding(self) -> None:
        token = self.guest_form("/signup")
        response = self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "email": "new.kid@example.com",
                "password": PASSWORD,
                "confirm_password": PASSWORD,
                "agree": "yes",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/onboarding")
        self.assertTrue(self.is_signed_in())
        session = self.client.get("/v1/auth/session").json()
        self.assertEqual(session["user"]["email"], "new.kid@example.com")
        self.assertFalse(session["user"]["email_verified"])
        self.assertEqual(self.sink.last("verify").to, "new.kid@example.com")

    def test_signup_validation_names_every_fix_without_creating_an_account(
        self,
    ) -> None:
        token = self.guest_form("/signup")
        response = self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "email": "kid@example.com",
                "password": "short",
                "confirm_password": "different",
            },
        )
        self.assertEqual(response.status_code, 422)
        html = response.text
        self.assertIn("Use at least 10 characters.", html)
        self.assertIn("The two passwords do not match.", html)
        self.assertIn("agree to the Terms", html)
        self.assertFalse(self.is_signed_in())
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        self.assertEqual(int(row["cnt"]), 0)

    def test_duplicate_signup_points_at_sign_in(self) -> None:
        self.register_via_api(email="kid@example.com")
        self.client.cookies.clear()
        token = self.guest_form("/signup")
        response = self.client.post(
            "/signup",
            data={
                "csrf_token": token,
                "email": "kid@example.com",
                "password": PASSWORD,
                "confirm_password": PASSWORD,
                "agree": "yes",
            },
        )
        self.assertEqual(response.status_code, 409)
        self.assertIn("already has a Zivon account", response.text)
        self.assertIn('href="/login"', response.text)

    def test_signup_csrf_is_required(self) -> None:
        response = self.client.post(
            "/signup",
            data={
                "email": "kid@example.com",
                "password": PASSWORD,
                "confirm_password": PASSWORD,
                "agree": "yes",
            },
        )
        self.assertEqual(response.status_code, 403)
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        self.assertEqual(int(row["cnt"]), 0)


class VerifyEmailTests(WebAuthSupport):
    def test_without_a_token_the_page_is_honest_about_missing_resend(self) -> None:
        html = self.client.get("/verify-email").text
        self.assertIn("Open the verification link", html)
        self.assertIn("Resending is not built yet", html)
        self.assertNotIn('form method="post" action="/verify-email"', html)

    def test_token_page_posts_the_one_time_token(self) -> None:
        self.register_via_api(email="kid@example.com")
        token = self.token_from_sink("verify")
        html = self.client.get(f"/verify-email?token={token}").text
        self.assertIn(f'name="token" value="{token}"', html)
        self.assertIn("Verify this email", html)

    def test_signed_in_verification_returns_to_settings(self) -> None:
        self.register_via_api(email="kid@example.com")
        token = self.token_from_sink("verify")
        response = self.client.post(
            "/verify-email", data={"token": token}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/app/settings?verified=1")
        self.assertTrue(
            self.client.get("/v1/auth/session").json()["user"]["email_verified"]
        )

    def test_guest_verification_returns_to_login(self) -> None:
        self.register_via_api(email="kid@example.com")
        token = self.token_from_sink("verify")
        self.client.cookies.clear()
        response = self.client.post(
            "/verify-email", data={"token": token}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?verified=1")

    def test_a_used_or_unknown_token_is_a_honest_dead_end(self) -> None:
        self.register_via_api(email="kid@example.com")
        token = self.token_from_sink("verify")
        self.client.post("/verify-email", data={"token": token})
        again = self.client.post("/verify-email", data={"token": token})
        self.assertEqual(again.status_code, 400)
        self.assertIn("This link is no longer valid", again.text)
        self.assertIn('href="/login"', again.text)


class PasswordResetTests(WebAuthSupport):
    def _verified_account(self) -> str:
        self.register_via_api(email="kid@example.com")
        self.verify_via_api()
        return "kid@example.com"

    def test_reset_request_never_reveals_whether_the_address_exists(self) -> None:
        self._verified_account()
        self.sink.clear()
        unknown_token = self.guest_form("/forgot-password")
        unknown = self.client.post(
            "/forgot-password",
            data={"csrf_token": unknown_token, "email": "ghost@example.com"},
        )
        known_token = self.guest_form("/forgot-password")
        known = self.client.post(
            "/forgot-password",
            data={"csrf_token": known_token, "email": "kid@example.com"},
        )
        self.assertEqual(unknown.status_code, 200)
        self.assertEqual(known.status_code, 200)
        self.assertIn("If that address has a Zivon account", unknown.text)
        self.assertIn("If that address has a Zivon account", known.text)
        self.assertIsNotNone(self.sink.last("reset"))
        self.assertNotIn("ghost@example.com", unknown.text)

    def test_forgot_password_csrf_is_required(self) -> None:
        response = self.client.post(
            "/forgot-password", data={"email": "kid@example.com"}
        )
        self.assertEqual(response.status_code, 403)
        self.assertIsNone(self.sink.last("reset"))

    def test_reset_link_without_a_token_offers_a_fresh_request(self) -> None:
        response = self.client.get("/reset-password")
        self.assertEqual(response.status_code, 200)
        self.assertIn("reset link is incomplete", response.text)
        self.assertIn('href="/forgot-password"', response.text)

    def test_reset_consumes_the_token_and_revokes_sessions(self) -> None:
        email = self._verified_account()
        self.client.cookies.clear()
        token = self.guest_form("/forgot-password")
        self.client.post("/forgot-password", data={"csrf_token": token, "email": email})
        reset_token = self.token_from_sink("reset")

        page = self.client.get(f"/reset-password?token={reset_token}")
        self.assertIn(f'name="token" value="{reset_token}"', page.text)

        response = self.client.post(
            "/reset-password",
            data={
                "token": reset_token,
                "password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?reset=1")

        old = self.client.post(
            "/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        self.assertEqual(old.status_code, 401)
        new = self.client.post(
            "/v1/auth/login", json={"email": email, "password": NEW_PASSWORD}
        )
        self.assertEqual(new.status_code, 200, new.text)

        reuse = self.client.post(
            "/reset-password",
            data={
                "token": reset_token,
                "password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
        )
        self.assertEqual(reuse.status_code, 400)
        self.assertIn("This reset link is no longer valid", reuse.text)

    def test_mismatch_does_not_consume_the_token(self) -> None:
        email = self._verified_account()
        self.client.cookies.clear()
        token = self.guest_form("/forgot-password")
        self.client.post("/forgot-password", data={"csrf_token": token, "email": email})
        reset_token = self.token_from_sink("reset")
        bad = self.client.post(
            "/reset-password",
            data={
                "token": reset_token,
                "password": NEW_PASSWORD,
                "confirm_password": "not-the-same-value",
            },
        )
        self.assertEqual(bad.status_code, 422)
        self.assertIn("The two passwords do not match.", bad.text)
        good = self.client.post(
            "/reset-password",
            data={
                "token": reset_token,
                "password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(good.status_code, 303)


class GoogleUnconfiguredTests(WebAuthSupport):
    google_configured = False

    def test_google_button_is_replaced_by_an_honest_status(self) -> None:
        html = self.client.get("/login").text
        self.assertNotIn("/v1/auth/google/start", html)
        self.assertIn("Google sign-in is not set up on this server", html)


class LoginRateLimitTests(WebAuthSupport):
    login_limit = 1

    def test_login_rate_limit_is_rendered_honestly(self) -> None:
        self.register_via_api(email="kid@example.com")
        self.client.cookies.clear()
        token = self.guest_form("/login")
        self.client.post(
            "/login",
            data={"csrf_token": token, "email": "kid@example.com", "password": "no"},
        )
        response = self.client.post(
            "/login",
            data={"csrf_token": token, "email": "kid@example.com", "password": "no"},
        )
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many attempts", response.text)
        self.assertGreaterEqual(int(response.headers["retry-after"]), 1)


class SignupRateLimitTests(WebAuthSupport):
    register_limit = 1

    def test_signup_is_rate_limited_with_retry_after(self) -> None:
        token = self.guest_form("/signup")
        data = {
            "csrf_token": token,
            "email": "first@example.com",
            "password": PASSWORD,
            "confirm_password": PASSWORD,
            "agree": "yes",
        }
        self.assertEqual(
            self.client.post("/signup", data=data, follow_redirects=False).status_code,
            303,
        )
        self.client.cookies.clear()
        token = self.guest_form("/signup")
        data.update({"csrf_token": token, "email": "second@example.com"})
        response = self.client.post("/signup", data=data)
        self.assertEqual(response.status_code, 429)
        self.assertIn("Too many attempts", response.text)
        self.assertIn("retry-after", {key.lower() for key in response.headers})


class AuthTemplateContracts(unittest.TestCase):
    """Static rules for the new templates, checked without a browser."""

    def test_every_auth_template_extends_the_base_shell(self) -> None:
        pages = sorted((TEMPLATES / "auth").glob("*.html"))
        self.assertTrue(pages)
        for path in pages:
            body = path.read_text(encoding="utf-8")
            self.assertIn('{% extends "base.html" %}', body, path.name)

    def test_templates_have_no_inline_script_style_or_handlers(self) -> None:
        pages = sorted((TEMPLATES / "auth").glob("*.html"))
        for path in pages:
            text = path.read_text(encoding="utf-8")
            for tag in re.findall(r"<script\b[^>]*>", text, re.IGNORECASE):
                self.assertIn("src=", tag, f"{path.name}: inline script")
            self.assertNotIn("<style", text.lower(), f"{path.name}: <style>")
            self.assertNotRegex(text, r"\sstyle\s*=", f"{path.name}: style attr")
            self.assertNotRegex(text, r"\son[a-z]+\s*=", f"{path.name}: handler")

    def test_templates_load_nothing_from_a_third_party_host(self) -> None:
        for path in sorted((TEMPLATES / "auth").glob("*.html")):
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                text,
                r"\b(?:src|href)\s*=\s*[\"'](?:https?:)?//",
                f"{path.name}: third-party host",
            )

    def test_auth_assets_are_local_and_enhancement_only(self) -> None:
        css = (REPO_ROOT / "frontend" / "assets" / "auth.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("min-height: 48px", css)
        self.assertIn(".auth-choice", css)
        self.assertIn("@media (max-width: 26rem)", css)
        js = (REPO_ROOT / "frontend" / "assets" / "auth.js").read_text(encoding="utf-8")
        self.assertNotIn("http://", js)
        self.assertNotIn("https://", js)
        self.assertNotIn("eval(", js)

    def test_nginx_proxies_every_auth_path_with_the_private_header_set(self) -> None:
        nginx = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        match = re.search(
            r"location ~ \^/\(signup\|verify-email\|forgot-password\|reset-password"
            r"\|onboarding\|logout\)\$ \{(.*?)\n    \}",
            nginx,
            re.DOTALL,
        )
        self.assertIsNotNone(match, "auth proxy location missing")
        assert match is not None
        block = match.group(1)
        self.assertIn("form-action 'self'", block)
        self.assertIn("proxy_pass http://core-backend:8000;", block)
        self.assertIn('Cache-Control "no-store"', block)
        self.assertIn('X-Robots-Tag "noindex, nofollow"', block)
        self.assertNotIn("proxy_set_header Cookie", block)
        self.assertNotIn("proxy_hide_header Set-Cookie", block)


if __name__ == "__main__":
    unittest.main()
