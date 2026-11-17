"""Shared hermetic setup for the F2 web auth/settings tests.

Not a test module (no `test_` prefix): it holds the app factory, the dev email
sink access, CSRF extraction, and the form helpers both test modules use.
SQLite in memory, the dev email sink, no network, no keys.
"""

from __future__ import annotations

import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app

PASSWORD = "correct-horse-battery-staple"
NEW_PASSWORD = "a-longer-quiet-river-42"


class FakeGoogleTransport:
    """Stands in for Google's token + userinfo endpoints (no network)."""

    def __init__(
        self,
        *,
        subject: str = "google-subject-1",
        email: str = "google.kid@example.com",
        name: str = "Google Kid",
    ) -> None:
        self.subject = subject
        self.email = email
        self.name = name

    def post_form(
        self, url: str, data: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]:
        del url, timeout_s
        if data.get("grant_type") != "authorization_code":
            raise AssertionError("unexpected Google token request")
        if not data.get("code_verifier"):
            raise AssertionError("PKCE verifier missing")
        return {"access_token": "fake-access-token", "token_type": "Bearer"}

    def get_json(
        self, url: str, headers: dict[str, str], *, timeout_s: float
    ) -> dict[str, Any]:
        del url, timeout_s
        if headers.get("Authorization") != "Bearer fake-access-token":
            raise AssertionError("userinfo called without the exchanged token")
        return {
            "sub": self.subject,
            "email": self.email,
            "email_verified": True,
            "name": self.name,
        }


class WebAuthSupport(unittest.TestCase):
    """One app + client per test; every helper crosses a real seam."""

    login_limit = 20
    register_limit = 20
    reset_limit = 20
    verify_limit = 20
    google_limit = 20
    google_configured = True

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            app_base_url="https://app.test",
            google_client_id="test-client-id" if self.google_configured else None,
            google_client_secret=(
                "test-client-secret" if self.google_configured else None
            ),
            auth_login_per_min=self.login_limit,
            auth_register_per_min=self.register_limit,
            auth_reset_per_min=self.reset_limit,
            auth_verify_per_min=self.verify_limit,
            auth_google_per_min=self.google_limit,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.service = self.app.state.auth
        self.sink = self.service.email
        self.db = self.app.state.db

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- session ------------------------------------------------------------

    def register_via_api(
        self,
        *,
        email: str = "kid@example.com",
        display_name: str = "Asha",
        class_level: int | None = 9,
        language: str = "en-IN",
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
        session = self.client.get("/v1/auth/session").json()
        self.assertTrue(session["authenticated"])
        return session

    def session_csrf(self) -> str:
        token = self.client.get("/v1/auth/session").json().get("csrf_token")
        self.assertIsInstance(token, str)
        return str(token)

    def session_csrf_from_page(self, path: str) -> str:
        match = re.search(
            r'name="csrf_token" value="([^"]+)"', self.client.get(path).text
        )
        self.assertIsNotNone(match, f"no form CSRF token on {path}")
        assert match is not None
        return match.group(1)

    def is_signed_in(self) -> bool:
        return bool(self.client.get("/v1/auth/session").json()["authenticated"])

    # -- guest forms --------------------------------------------------------

    def guest_form(self, path: str = "/login") -> str:
        """GET a guest page (issuing the nonce cookie) and return its token."""
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        match = re.search(
            r'<input type="hidden" name="csrf_token" value="([^"]+)">',
            response.text,
        )
        self.assertIsNotNone(match, f"no guest CSRF token on {path}")
        assert match is not None
        return match.group(1)

    # -- email sink ---------------------------------------------------------

    def token_from_sink(self, kind: str) -> str:
        message = self.sink.last(kind)
        if message is None:
            self.fail(f"no {kind} email was queued")
        match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.body or "")
        if match is None:
            self.fail(f"{kind} email has no token link")
        return str(match.group(1))

    def verify_via_api(self) -> None:
        token = self.token_from_sink("verify")
        response = self.client.post("/v1/auth/verify-email", json={"token": token})
        self.assertEqual(response.status_code, 200, response.text)


__all__ = ["NEW_PASSWORD", "PASSWORD", "FakeGoogleTransport", "WebAuthSupport"]
