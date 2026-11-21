"""Flow 2 (§17.1): login — email/password ok, wrong password, rate limit,
password reset, and the Google button's honesty (Google login is blocked on
founder credentials; the honest answer is all this flow asserts).

Web-form paths through `web/routes/auth.py`; the dev email sink carries the
one-time reset token. No network, no keys, no vendor.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi.testclient import TestClient

from backend import create_app
from db.uuid7 import uuid7_str

from .support import PASSWORD, E2EFlow, make_config

WRONG_COPY = "Email or password is wrong"
NEW_PASSWORD = "a-longer-quiet-river-42"


class LoginFlowTests(E2EFlow):
    """The signed-out entry path, all four honest outcomes."""

    def login(self, browser: Any, email: str, password: str) -> Any:
        token = self.guest_form_token("/login", client=browser)
        return browser.post(
            "/login",
            data={"csrf_token": token, "email": email, "password": password},
        )

    # -- wrong password ------------------------------------------------------

    def test_wrong_password_is_a_branded_401_no_session(self) -> None:
        browser = self.guest_client()
        response = self.login(browser, self.email, "not-the-password-42")
        self.assertEqual(response.status_code, 401, response.text)
        self.assertIn(WRONG_COPY, response.text, "honest re-render with the form")
        self.assertIn('role="alert"', response.text)
        session = browser.get("/v1/auth/session").json()
        self.assertFalse(session["authenticated"], "no session for a wrong password")

    def test_unknown_email_gets_the_same_honest_answer(self) -> None:
        browser = self.guest_client()
        response = self.login(browser, f"nobody-{uuid7_str()}@example.com", PASSWORD)
        self.assertEqual(response.status_code, 401)
        self.assertIn(WRONG_COPY, response.text)
        self.assertNotIn("No account", response.text, "no enumeration")

    def test_csrf_missing_is_a_403_not_a_login(self) -> None:
        browser = self.guest_client()
        response = browser.post(
            "/login",
            data={"email": self.email, "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)

    # -- the signup -> verification -> login chain ----------------------------

    def test_signup_verification_email_then_login_chain(self) -> None:
        """Signup queues the verification email in the dev sink; the token
        verifies; the verified account then logs in from a clean browser."""
        browser = self.guest_client()
        email = f"chain-{uuid7_str()}@example.com"
        self.signup_via_web(email, client=browser)
        message = self.app.state.auth.email.last("verify")
        self.assertIsNotNone(message, "the dev sink queued a verification email")
        assert message is not None
        self.assertEqual(message.to, email)
        match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.body or "")
        self.assertIsNotNone(match, "the verification email carries its token")
        assert match is not None
        verified = self.client.post(
            "/v1/auth/verify-email", json={"token": match.group(1)}
        )
        self.assertEqual(verified.status_code, 200, verified.text)

        fresh = self.guest_client()
        token = self.guest_form_token("/login", client=fresh)
        login = fresh.post(
            "/login",
            data={"csrf_token": token, "email": email, "password": PASSWORD},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303, login.text)
        self.assertEqual(login.headers["location"], "/app")
        session = fresh.get("/v1/auth/session").json()
        self.assertTrue(session["authenticated"])
        self.assertTrue(
            bool(session["user"]["email_verified"]), "the verification stuck"
        )

    # -- correct login -------------------------------------------------------

    def test_correct_login_reaches_the_dashboard(self) -> None:
        browser = self.guest_client()
        token = self.guest_form_token("/login", client=browser)
        response = browser.post(
            "/login",
            data={"csrf_token": token, "email": self.email, "password": PASSWORD},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/app")
        dashboard = browser.get("/app")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Asha", dashboard.text, "greeting names the account")

    def test_login_honours_the_next_parameter(self) -> None:
        browser = self.guest_client()
        token = self.guest_form_token("/login?next=/app/progress", client=browser)
        response = browser.post(
            "/login",
            data={
                "csrf_token": token,
                "email": self.email,
                "password": PASSWORD,
                "next": "/app/progress",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/app/progress")

    # -- rate limit ----------------------------------------------------------

    def test_login_rate_limit_answers_429_honestly(self) -> None:
        cfg = make_config(self.root, auth_login_per_min=1)
        app = create_app(cfg, db_engine=self.db)
        limiter = TestClient(app, base_url="https://testserver")
        token = self.guest_form_token("/login", client=limiter)
        first = limiter.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "no-such@example.com",
                "password": "wrong-password-1",
            },
        )
        self.assertEqual(first.status_code, 401, "a wrong attempt still spends")
        second = limiter.post(
            "/login",
            data={
                "csrf_token": token,
                "email": "no-such@example.com",
                "password": "wrong-password-2",
            },
        )
        self.assertEqual(second.status_code, 429, second.text[:400])
        self.assertIn("Too many attempts", second.text, "branded page, not JSON")
        self.assertIn("Retry-After", second.headers)

    # -- password reset ------------------------------------------------------

    def verify_email_via_sink(self) -> None:
        message = self.app.state.auth.email.last("verify")
        self.assertIsNotNone(message, "the dev sink queued a verification email")
        assert message is not None
        match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.body or "")
        assert match is not None, "the verification email carries its token"
        response = self.client.post(
            "/v1/auth/verify-email", json={"token": match.group(1)}
        )
        self.assertEqual(response.status_code, 200, response.text)

    def request_reset(self, browser: Any, email: str) -> None:
        token = self.guest_form_token("/forgot-password", client=browser)
        response = browser.post(
            "/forgot-password",
            data={"csrf_token": token, "email": email},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("reset link is on its way", response.text)
        self.assertIn("whether or not an account exists", response.text)

    def reset_token_from_sink(self) -> str:
        message = self.app.state.auth.email.last("reset")
        self.assertIsNotNone(message, "the dev sink queued a reset email")
        assert message is not None
        match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.body or "")
        assert match is not None, "the reset email carries the one-time token"
        return match.group(1)

    def submit_reset(
        self, browser: Any, token: str, new_password: str, *, expect: int = 303
    ) -> Any:
        # The reset form carries no session CSRF: the emailed one-time token
        # is the proof (state matrix, APP-02 CSRF boundary).
        response = browser.post(
            "/reset-password",
            data={
                "token": token,
                "password": new_password,
                "confirm_password": new_password,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, expect, response.text[:400])
        return response

    def test_password_reset_via_dev_sink(self) -> None:
        browser = self.guest_client()
        self.verify_email_via_sink()
        self.request_reset(browser, self.email)
        token = self.reset_token_from_sink()
        done = self.submit_reset(browser, token, NEW_PASSWORD)
        self.assertEqual(done.headers["location"], "/login?reset=1")

        # The old password no longer opens the account; the new one does.
        stale = self.guest_client()
        old_login = self.login(stale, self.email, PASSWORD)
        self.assertEqual(old_login.status_code, 401)
        self.assertIn(WRONG_COPY, old_login.text)

        fresh = self.guest_client()
        fresh_token = self.guest_form_token("/login", client=fresh)
        new_login = fresh.post(
            "/login",
            data={
                "csrf_token": fresh_token,
                "email": self.email,
                "password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 303, new_login.text)
        self.assertEqual(new_login.headers["location"], "/app")

    def test_reset_token_is_single_use(self) -> None:
        browser = self.guest_client()
        self.verify_email_via_sink()
        self.request_reset(browser, self.email)
        token = self.reset_token_from_sink()
        self.submit_reset(browser, token, NEW_PASSWORD)
        replay = self.submit_reset(
            self.guest_client(), token, "another-quiet-river-99", expect=400
        )
        self.assertIn("no longer valid", replay.text.lower())

    def test_forgot_password_for_unknown_email_stays_polite(self) -> None:
        browser = self.guest_client()
        self.request_reset(browser, f"ghost-{uuid7_str()}@example.com")
        self.assertIsNone(self.app.state.auth.email.last("reset"))

    # -- Google honesty (blocked on founder credentials) ----------------------

    def test_unconfigured_google_has_no_dead_button(self) -> None:
        browser = self.guest_client()
        login = browser.get("/login")
        self.assertEqual(login.status_code, 200)
        self.assertNotIn(
            "Continue with Google",
            login.text,
            "no button that cannot work when Google is not configured",
        )
        start = browser.get(
            "/v1/auth/google/start?intent=login&next=/app",
            follow_redirects=False,
        )
        self.assertEqual(start.status_code, 503, start.text[:200])
        self.assertEqual(start.json()["code"], "E-SERVICE-UNAVAILABLE")
