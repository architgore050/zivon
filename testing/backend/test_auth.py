"""End-to-end account/auth contract tests (REQUIREMENTS §6, §9; ADR-0029).

Hermetic: SQLite in memory, the dev email sink, and a fake Google transport.
No network, no secrets, no live Google/Argon2-parameter tuning.
"""

from __future__ import annotations

import re
import tempfile
import unittest
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from db.uuid7 import uuid7_str

PASSWORD = "correct-horse-battery-staple"


class FakeGoogleTransport:
    """Stands in for Google's token + userinfo endpoints (no network)."""

    def __init__(
        self,
        *,
        subject: str = "google-subject-1",
        email: str = "kid@example.com",
        email_verified: bool = True,
        name: str = "Kid",
    ) -> None:
        self.subject = subject
        self.email = email
        self.email_verified = email_verified
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
            "email_verified": self.email_verified,
            "name": self.name,
        }


class AuthTestCase(unittest.TestCase):
    login_limit = 20

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            admin_token="test-admin-token",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            app_base_url="https://app.test",
            google_client_id="test-client-id",
            google_client_secret="test-client-secret",
            auth_login_per_min=self.login_limit,
            auth_register_per_min=20,
            auth_reset_per_min=20,
            auth_verify_per_min=20,
            auth_google_per_min=20,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.service = self.app.state.auth
        self.sink = self.service.email
        self.db = self.app.state.db

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(self, email: str = "kid@example.com", **extra: Any) -> Any:
        return self.client.post(
            "/v1/auth/register",
            json={"email": email, "password": PASSWORD, **extra},
        )

    def csrf(self) -> str:
        payload = self.client.get("/v1/auth/session").json()
        token = payload.get("csrf_token")
        self.assertIsInstance(token, str)
        return str(token)

    def token_from_sink(self, kind: str) -> str:
        message = self.sink.last(kind)
        if message is None:
            self.fail(f"no {kind} email was queued")
        match = re.search(r"[?&]token=([A-Za-z0-9_\-]+)", message.body or "")
        if match is None:
            self.fail(f"{kind} email has no token link")
        return str(match.group(1))

    def verify_email(self, email: str = "kid@example.com") -> None:
        response = self.client.post(
            "/v1/auth/verify-email",
            json={"token": self.token_from_sink("verify")},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def user_id(self) -> str:
        return str(self.client.get("/v1/auth/session").json()["user"]["user_id"])

    def start_google(
        self, *, intent: str = "login", transport: FakeGoogleTransport | None = None
    ) -> tuple[str, str]:
        if transport is not None:
            self.service.google.transport = transport
        response = self.client.get(
            f"/v1/auth/google/start?intent={intent}&next=/app",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302, response.text)
        location = response.headers["location"]
        self.assertTrue(location.startswith("https://accounts.google.com/"))
        state = parse_qs(urlparse(location).query)["state"][0]
        return location, state

    def finish_google(self, state: str) -> Any:
        return self.client.get(
            f"/v1/auth/google/callback?code=fake-code&state={state}",
            follow_redirects=False,
        )


class TestRegistrationAndSession(AuthTestCase):
    def test_register_creates_account_and_sets_session_cookie(self) -> None:
        response = self.register("Kid@Example.com")
        self.assertEqual(response.status_code, 201, response.text)
        body = response.json()
        self.assertTrue(body["authenticated"])
        self.assertEqual(body["user"]["email"], "kid@example.com")
        self.assertFalse(body["user"]["email_verified"])
        self.assertTrue(body["password_set"])
        self.assertFalse(body["google_linked"])
        self.assertTrue(body["csrf_token"])

        cookie = response.headers["set-cookie"].lower()
        for flag in ("httponly", "secure", "samesite=lax", "path=/", "max-age="):
            self.assertIn(flag, cookie)

        session = self.client.get("/v1/auth/session").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["email"], "kid@example.com")
        self.assertEqual(session["user"]["role"], "student")

        message = self.sink.last("verify")
        self.assertIsNotNone(message)
        self.assertEqual(message.to, "kid@example.com")

    def test_guest_session_probe_is_not_an_error(self) -> None:
        response = self.client.get("/v1/auth/session")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"authenticated": False, "user": None, "csrf_token": None},
        )

    def test_duplicate_registration_is_a_conflict_case_insensitively(self) -> None:
        self.assertEqual(self.register("kid@example.com").status_code, 201)
        response = self.register("KID@example.com")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-CONFLICT")
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        self.assertEqual(int(row["cnt"]), 1)

    def test_weak_password_is_rejected_with_a_reason(self) -> None:
        short = self.client.post(
            "/v1/auth/register", json={"email": "a@example.com", "password": "short"}
        )
        self.assertEqual(short.status_code, 422)
        self.assertEqual(short.json()["reason"], "too_short")
        common = self.client.post(
            "/v1/auth/register",
            json={"email": "b@example.com", "password": "password123"},
        )
        self.assertEqual(common.status_code, 422)
        self.assertEqual(common.json()["reason"], "too_common")

    def test_logout_revokes_the_session_and_clears_the_cookie(self) -> None:
        self.register()
        response = self.client.post(
            "/v1/auth/logout", headers={"X-CSRF-Token": self.csrf()}
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("zivon_session", response.headers["set-cookie"])
        self.assertIn("max-age=0", response.headers["set-cookie"].lower())
        self.assertFalse(self.client.get("/v1/auth/session").json()["authenticated"])

    def test_expired_session_is_rejected(self) -> None:
        self.register()
        self.db.execute(
            "UPDATE auth_session SET expires_at = '2000-01-01T00:00:00.000Z'"
        )
        self.assertFalse(self.client.get("/v1/auth/session").json()["authenticated"])
        self.assertEqual(self.client.get("/v1/me").status_code, 401)


class TestLogin(AuthTestCase):
    def test_login_returns_a_session_for_the_right_password(self) -> None:
        self.register()
        self.client.post("/v1/auth/logout", headers={"X-CSRF-Token": self.csrf()})
        response = self.client.post(
            "/v1/auth/login", json={"email": "kid@example.com", "password": PASSWORD}
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["authenticated"])

    def test_wrong_password_and_unknown_email_are_indistinguishable(self) -> None:
        self.register()
        self.client.post("/v1/auth/logout", headers={"X-CSRF-Token": self.csrf()})
        wrong = self.client.post(
            "/v1/auth/login",
            json={"email": "kid@example.com", "password": "not-the-password"},
        )
        unknown = self.client.post(
            "/v1/auth/login",
            json={"email": "nobody@example.com", "password": PASSWORD},
        )
        for response in (wrong, unknown):
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "E-AUTH-INVALID")
            self.assertEqual(response.json()["message_key"], "error.auth_invalid")
            self.assertNotIn("user", response.json())


class TestLoginRateLimit(AuthTestCase):
    login_limit = 3

    def test_login_attempts_are_rate_limited_with_retry_after(self) -> None:
        for _ in range(self.login_limit):
            response = self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": "wrong-password"},
            )
            self.assertEqual(response.status_code, 401)
        limited = self.client.post(
            "/v1/auth/login",
            json={"email": "kid@example.com", "password": "wrong-password"},
        )
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.json()["code"], "E-RATE-LIMIT")
        self.assertGreaterEqual(int(limited.headers["Retry-After"]), 1)


class TestEmailLifecycle(AuthTestCase):
    def test_verification_token_is_single_use(self) -> None:
        self.register()
        token = self.token_from_sink("verify")
        first = self.client.post("/v1/auth/verify-email", json={"token": token})
        self.assertEqual(first.status_code, 200)
        second = self.client.post("/v1/auth/verify-email", json={"token": token})
        self.assertEqual(second.status_code, 400)
        self.assertEqual(second.json()["code"], "E-TOKEN-INVALID")
        self.assertTrue(self.client.get("/v1/me").json()["user"]["email_verified"])

    def test_reset_changes_the_password_and_revokes_old_sessions(self) -> None:
        self.register()
        self.verify_email()
        old_cookie = self.client.cookies.get("zivon_session")
        self.assertIsNotNone(old_cookie)

        self.assertEqual(
            self.client.post(
                "/v1/auth/request-password-reset",
                json={"email": "kid@example.com"},
            ).status_code,
            202,
        )
        new_password = "a-brand-new-secret-42"
        reset = self.client.post(
            "/v1/auth/reset-password",
            json={"token": self.token_from_sink("reset"), "new_password": new_password},
        )
        self.assertEqual(reset.status_code, 200, reset.text)

        self.client.cookies.set("zivon_session", str(old_cookie))
        self.assertFalse(self.client.get("/v1/auth/session").json()["authenticated"])
        self.client.cookies.clear()
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": PASSWORD},
            ).status_code,
            401,
        )
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": new_password},
            ).status_code,
            200,
        )

    def test_reset_request_does_not_reveal_an_unknown_address(self) -> None:
        response = self.client.post(
            "/v1/auth/request-password-reset",
            json={"email": "nobody@example.com"},
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.json(), {"ok": True})
        self.assertEqual(self.sink.messages("reset"), [])

    def test_unverified_account_gets_no_reset_mail(self) -> None:
        self.register()
        self.client.post(
            "/v1/auth/request-password-reset", json={"email": "kid@example.com"}
        )
        self.assertIsNone(self.sink.last("reset"))


class TestGoogleAuth(AuthTestCase):
    def test_google_creates_one_account_then_resolves_by_subject(self) -> None:
        transport = FakeGoogleTransport()
        _url, state = self.start_google(transport=transport)
        first = self.finish_google(state)
        self.assertEqual(first.status_code, 303)
        self.assertEqual(first.headers["location"], "/app")
        session = self.client.get("/v1/auth/session").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(session["user"]["email"], "kid@example.com")
        self.assertTrue(session["user"]["email_verified"])
        self.assertFalse(session["password_set"])
        self.assertTrue(session["google_linked"])
        user_id = session["user"]["user_id"]

        _url, state = self.start_google(transport=transport)
        second = self.finish_google(state)
        self.assertEqual(second.status_code, 303)
        self.assertEqual(
            self.client.get("/v1/auth/session").json()["user"]["user_id"], user_id
        )
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        self.assertEqual(int(row["cnt"]), 1)

    def test_google_links_to_an_existing_verified_email_account(self) -> None:
        self.register("kid@example.com")
        local_user_id = self.user_id()
        self.verify_email()

        transport = FakeGoogleTransport(subject="google-subject-2")
        _url, state = self.start_google(transport=transport)
        response = self.finish_google(state)
        self.assertEqual(response.status_code, 303)
        session = self.client.get("/v1/auth/session").json()
        self.assertEqual(session["user"]["user_id"], local_user_id)
        self.assertTrue(session["google_linked"])
        self.assertTrue(session["password_set"])
        row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM auth_identity WHERE user_id = ?",
            (local_user_id,),
        )
        self.assertEqual(int(row["cnt"]), 2)

    def test_google_unverified_email_does_not_create_or_link(self) -> None:
        transport = FakeGoogleTransport(email_verified=False)
        _url, state = self.start_google(transport=transport)
        response = self.finish_google(state)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?error="))
        self.assertEqual(
            response.headers["location"], "/login?error=E-EMAIL-UNVERIFIED"
        )
        row = self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")
        self.assertEqual(int(row["cnt"]), 0)

    def test_google_state_mismatch_is_rejected(self) -> None:
        self.start_google(transport=FakeGoogleTransport())
        response = self.client.get(
            "/v1/auth/google/callback?code=fake-code&state=forged",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?error=E-AUTH-INVALID")
        self.assertEqual(
            int(self.db.fetchone("SELECT COUNT(*) AS cnt FROM users")["cnt"]), 0
        )

    def test_link_intent_requires_a_verified_local_email(self) -> None:
        self.register()
        unverified = self.client.get(
            "/v1/auth/google/start?intent=link", follow_redirects=False
        )
        self.assertEqual(unverified.status_code, 403)
        self.assertEqual(unverified.json()["code"], "E-EMAIL-UNVERIFIED")

        self.verify_email()
        _url, state = self.start_google(
            intent="link", transport=FakeGoogleTransport(subject="google-subject-3")
        )
        response = self.finish_google(state)
        self.assertEqual(response.status_code, 303)
        self.assertTrue(self.client.get("/v1/auth/session").json()["google_linked"])

    def test_google_only_account_sets_a_password_before_password_login(self) -> None:
        _url, state = self.start_google(
            transport=FakeGoogleTransport(subject="google-subject-4")
        )
        self.assertEqual(self.finish_google(state).status_code, 303)
        self.assertFalse(self.client.get("/v1/auth/session").json()["password_set"])

        set_password = self.client.post(
            "/v1/me/password",
            json={"new_password": "a-google-only-secret-9"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(set_password.status_code, 200, set_password.text)
        self.assertTrue(set_password.json()["password_set"])
        login = self.client.post(
            "/v1/auth/login",
            json={"email": "kid@example.com", "password": "a-google-only-secret-9"},
        )
        self.assertEqual(login.status_code, 200, login.text)

    def test_google_start_is_503_when_not_configured(self) -> None:
        import dataclasses

        unconfigured = dataclasses.replace(
            self.cfg, google_client_id=None, google_client_secret=None
        )
        client = TestClient(create_app(unconfigured), base_url="https://testserver")
        response = client.get("/v1/auth/google/start", follow_redirects=False)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "E-SERVICE-UNAVAILABLE")


class TestCsrfAndPassword(AuthTestCase):
    def test_state_changing_calls_require_the_csrf_header(self) -> None:
        self.register()
        missing = self.client.patch("/v1/me", json={"class_level": 9})
        self.assertEqual(missing.status_code, 403)
        self.assertEqual(missing.json()["code"], "E-AUTH-CSRF")
        allowed = self.client.patch(
            "/v1/me",
            json={"class_level": 9},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed.json()["user"]["class_level"], 9)

    def test_profile_patch_validates_fields(self) -> None:
        self.register()
        response = self.client.patch(
            "/v1/me",
            json={"language": "hi"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["language"], "hi-IN")
        bad = self.client.patch(
            "/v1/me",
            json={"class_level": 15},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(bad.json()["reason"], "invalid_class_level")

    def test_password_change_rotates_the_session_and_csrf(self) -> None:
        self.register()
        old_csrf = self.csrf()
        old_cookie = self.client.cookies.get("zivon_session")
        response = self.client.post(
            "/v1/me/password",
            json={
                "current_password": PASSWORD,
                "new_password": "another-good-secret-7",
            },
            headers={"X-CSRF-Token": old_csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        new_csrf = response.json()["csrf_token"]
        self.assertNotEqual(new_csrf, old_csrf)
        self.assertNotEqual(self.client.cookies.get("zivon_session"), old_cookie)

        # The rotated session keeps working; the old CSRF value does not.
        self.assertTrue(self.client.get("/v1/auth/session").json()["authenticated"])
        stale = self.client.patch(
            "/v1/me", json={"board": "ICSE"}, headers={"X-CSRF-Token": old_csrf}
        )
        self.assertEqual(stale.status_code, 403)

    def test_wrong_current_password_cannot_change_the_password(self) -> None:
        self.register()
        response = self.client.post(
            "/v1/me/password",
            json={"current_password": "wrong", "new_password": "another-good-secret-7"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 401)


class TestDeleteAndExport(AuthTestCase):
    def _seed_learning_data(self, user_id: str) -> None:
        self.db.execute(
            """
            INSERT INTO lesson_progress (user_id, chapter_id, status, last_block_id, blocks_seen)
            VALUES (?, 'class-9-motion', 'in_progress', 'b-03', 3)
            """,
            (user_id,),
        )
        self.db.execute(
            """
            INSERT INTO progress_event (event_id, user_id, kind, chapter_id)
            VALUES (?, ?, 'lesson_block_view', 'class-9-motion')
            """,
            (uuid7_str(), user_id),
        )
        self.db.execute(
            """
            INSERT INTO bookmark (bookmark_id, user_id, target_type, target_id)
            VALUES (?, ?, 'chapter', 'class-9-motion')
            """,
            (uuid7_str(), user_id),
        )

    def test_export_contains_own_data_and_no_secrets(self) -> None:
        self.register()
        user_id = self.user_id()
        self._seed_learning_data(user_id)
        response = self.client.get("/v1/me/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment; filename=", response.headers["content-disposition"])
        body = response.text
        self.assertIn("class-9-motion", body)
        self.assertIn("lesson_progress", body)
        self.assertIn("bookmarks", body)
        self.assertNotIn("argon2", body)
        self.assertNotIn("password_hash", body)
        self.assertNotIn("token_hash", body)

    def test_delete_removes_learning_data_and_blocks_login(self) -> None:
        self.register()
        user_id = self.user_id()
        self.verify_email()
        self._seed_learning_data(user_id)
        response = self.client.post(
            "/v1/me/delete",
            json={"confirm": "DELETE", "password": PASSWORD},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200, response.text)
        deleted = response.json()["deleted"]
        self.assertEqual(deleted["lesson_progress"], 1)
        self.assertEqual(deleted["progress_events"], 1)
        self.assertEqual(deleted["bookmarks"], 1)
        self.assertEqual(deleted["sessions"], 1)

        user = self.db.fetchone(
            "SELECT email, display_name, deleted_at FROM users WHERE user_id = ?",
            (user_id,),
        )
        self.assertIsNotNone(user["deleted_at"])
        self.assertTrue(str(user["email"]).startswith("deleted+"))
        self.assertIsNone(user["display_name"])
        self.assertEqual(
            int(self.db.fetchone("SELECT COUNT(*) AS cnt FROM lesson_progress")["cnt"]),
            0,
        )
        self.assertFalse(self.client.get("/v1/auth/session").json()["authenticated"])
        login = self.client.post(
            "/v1/auth/login", json={"email": "kid@example.com", "password": PASSWORD}
        )
        self.assertEqual(login.status_code, 401)

    def test_delete_requires_the_confirmation_string_and_password(self) -> None:
        self.register()
        wrong_confirm = self.client.post(
            "/v1/me/delete",
            json={"confirm": "yes", "password": PASSWORD},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(wrong_confirm.status_code, 400)
        self.assertEqual(wrong_confirm.json()["code"], "E-CONFIRM-REQUIRED")
        wrong_password = self.client.post(
            "/v1/me/delete",
            json={"confirm": "DELETE", "password": "nope"},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(wrong_password.status_code, 401)

    def test_unauthenticated_me_is_rejected(self) -> None:
        for method, path, body in (
            ("get", "/v1/me", None),
            ("post", "/v1/me/delete", {"confirm": "DELETE"}),
            ("get", "/v1/me/export", None),
        ):
            if body is None:
                response = getattr(self.client, method)(path)
            else:
                response = getattr(self.client, method)(path, json=body)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["code"], "E-AUTH-REQUIRED")


class TestDeviceLink(AuthTestCase):
    def test_register_attaches_an_existing_voice_device(self) -> None:
        device_id = str(uuid.uuid4())
        bootstrap = self.client.post(
            "/v1/session", json={"device_pseudo_id": device_id, "lang": "hi"}
        )
        self.assertEqual(bootstrap.status_code, 200, bootstrap.text)
        self.register(device_pseudo_id=device_id)
        row = self.db.fetchone(
            "SELECT user_id FROM device WHERE device_pseudo_id = ?", (device_id,)
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["user_id"], self.user_id())

    def test_me_device_links_another_device_with_csrf(self) -> None:
        self.register()
        device_id = str(uuid.uuid4())
        missing = self.client.post(
            "/v1/me/device", json={"device_pseudo_id": device_id}
        )
        self.assertEqual(missing.status_code, 403)
        linked = self.client.post(
            "/v1/me/device",
            json={"device_pseudo_id": device_id},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(linked.status_code, 200, linked.text)
        row = self.db.fetchone(
            "SELECT user_id FROM device WHERE device_pseudo_id = ?", (device_id,)
        )
        self.assertEqual(row["user_id"], self.user_id())


if __name__ == "__main__":
    unittest.main()
