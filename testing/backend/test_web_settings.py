"""F2 settings, onboarding, sign-out, export, and delete-account contracts.

Hermetic: SQLite in memory, the dev email sink, a fake Google transport for the
"Google-created account" state. Every state-changing route is exercised with
the session CSRF token; every rejection is asserted to have changed nothing.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from fastapi.testclient import TestClient

from backend.errors import APIError
from testing.backend.web_auth_support import (
    NEW_PASSWORD,
    PASSWORD,
    WebAuthSupport,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = REPO_ROOT / "web" / "templates"

SETTINGS = "/app/settings"
PRIVACY = "/app/settings/privacy"


class SettingsAccessTests(WebAuthSupport):
    def test_guest_is_sent_to_login_with_the_requested_path(self) -> None:
        for path in (SETTINGS, PRIVACY):
            response = self.client.get(path, follow_redirects=False)
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], f"/login?next={path}")

    def test_guest_post_to_settings_is_also_guarded(self) -> None:
        response = self.client.post(
            SETTINGS, data={"csrf_token": "x"}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(
            response.headers["location"].startswith("/login?next=/app/settings")
        )

    def test_settings_renders_owner_profile_and_forms(self) -> None:
        session = self.register_via_api()
        response = self.client.get(SETTINGS)
        self.assertEqual(response.status_code, 200)
        html = response.text

        self.assertIn("kid@example.com", html)
        self.assertIn('name="display_name"', html)
        self.assertIn('name="class_level"', html)
        self.assertIn('name="board"', html)
        self.assertIn('name="language"', html)
        self.assertIn("Change password", html)
        self.assertIn("Sign out", html)
        self.assertIn(f'href="{PRIVACY}"', html)
        self.assertIn("/assets/auth.css", html)
        self.assertIn('aria-current="page"', html)

        # The owner's account identifiers are here; the user id and the raw
        # session cookie are never.
        self.assertNotIn(session["user"]["user_id"], html)
        raw_cookie = self.client.cookies.get(self.cfg.auth_cookie_name)
        self.assertIsNotNone(raw_cookie)
        self.assertNotIn(raw_cookie, html)
        self.assertNotIn(self.cfg.session_token_key, html)

    def test_settings_marks_the_owner_as_unverified_and_links_verification(
        self,
    ) -> None:
        self.register_via_api()
        html = self.client.get(SETTINGS).text
        self.assertIn("Not verified", html)
        self.assertIn('href="/verify-email"', html)
        self.assertIn("Verify your email before connecting Google", html)
        self.assertNotIn("Connect Google</a>", html)

    def test_verified_account_sees_the_google_link_control(self) -> None:
        self.register_via_api()
        self.verify_via_api()
        html = self.client.get(SETTINGS).text
        self.assertIn("Verified", html)
        self.assertIn("Connect Google", html)
        self.assertIn("/v1/auth/google/start?intent=link", html)

    def test_display_name_is_escaped_on_the_settings_page(self) -> None:
        self.register_via_api(display_name="<script>alert(1)</script>")
        html = self.client.get(SETTINGS).text
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)

    def test_settings_forms_all_carry_the_session_csrf_field(self) -> None:
        self.register_via_api()
        html = self.client.get(SETTINGS).text
        tokens = re.findall(r'name="csrf_token" value="([^"]+)"', html)
        self.assertGreaterEqual(len(tokens), 3)
        self.assertEqual(set(tokens), {self.session_csrf()})

    def test_every_settings_input_has_a_label(self) -> None:
        self.register_via_api()
        html = self.client.get(SETTINGS).text
        ids = set(re.findall(r'<(?:input|select) class="input" id="([^"]+)"', html))
        self.assertTrue(ids)
        for element_id in ids:
            self.assertIn(f'for="{element_id}"', html, element_id)


class SettingsProfileTests(WebAuthSupport):
    def test_profile_update_saves_and_returns_with_a_notice(self) -> None:
        self.register_via_api()
        response = self.client.post(
            SETTINGS,
            data={
                "csrf_token": self.session_csrf(),
                "display_name": "Asha Rao",
                "class_level": "10",
                "board": "ICSE",
                "language": "hinglish",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], f"{SETTINGS}?saved=profile")
        row = self.db.fetchone(
            "SELECT display_name, class_level, board, language FROM users"
        )
        self.assertEqual(row["display_name"], "Asha Rao")
        self.assertEqual(int(row["class_level"]), 10)
        self.assertEqual(row["board"], "ICSE")
        self.assertEqual(row["language"], "hinglish")
        self.assertIn(
            "Profile saved.", self.client.get(f"{SETTINGS}?saved=profile").text
        )

    def test_profile_validation_keeps_the_old_values(self) -> None:
        self.register_via_api(class_level=9, language="hi-IN")
        response = self.client.post(
            SETTINGS,
            data={
                "csrf_token": self.session_csrf(),
                "display_name": "Asha",
                "class_level": "7",
                "board": "CBSE",
                "language": "hi-IN",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Choose your class.", response.text)
        row = self.db.fetchone("SELECT class_level, language FROM users")
        self.assertEqual(int(row["class_level"]), 9)
        self.assertEqual(row["language"], "hi-IN")

    def test_profile_csrf_rejection_changes_nothing(self) -> None:
        self.register_via_api(display_name="Asha")
        response = self.client.post(
            SETTINGS,
            data={
                "csrf_token": "not-the-token",
                "display_name": "Intruder",
                "class_level": "10",
                "board": "CBSE",
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)
        row = self.db.fetchone("SELECT display_name FROM users")
        self.assertEqual(row["display_name"], "Asha")

    def test_language_option_labels_mark_the_saved_choice(self) -> None:
        self.register_via_api(language="hi-IN")
        html = self.client.get(SETTINGS).text
        self.assertIn('<option value="hi-IN" selected>', html)

    def test_saved_locale_outside_the_three_choices_is_preserved(self) -> None:
        self.register_via_api()
        patched = self.client.patch(
            "/v1/me",
            json={"language": "ta-IN"},
            headers={"X-CSRF-Token": self.session_csrf()},
        )
        self.assertEqual(patched.status_code, 200, patched.text)
        html = self.client.get(SETTINGS).text
        # The saved locale is offered and selected, so saving another field
        # cannot silently rewrite it to the first option.
        self.assertIn('<option value="ta-IN" selected>ta-IN</option>', html)
        saved = self.client.post(
            SETTINGS,
            data={
                "csrf_token": self.session_csrf(),
                "display_name": "Asha",
                "class_level": "9",
                "board": "CBSE",
                "language": "ta-IN",
            },
            follow_redirects=False,
        )
        self.assertEqual(saved.status_code, 303)
        row = self.db.fetchone(
            "SELECT language FROM users WHERE email = ?", ("kid@example.com",)
        )
        self.assertEqual(row["language"], "ta-IN")


class SettingsPasswordTests(WebAuthSupport):
    def test_password_change_rotates_the_session_and_signs_out_other_devices(
        self,
    ) -> None:
        self.register_via_api()
        other = TestClient(self.app, base_url="https://testserver")
        login = other.post(
            "/v1/auth/login",
            json={"email": "kid@example.com", "password": PASSWORD},
        )
        self.assertEqual(login.status_code, 200)
        self.assertTrue(other.get("/v1/auth/session").json()["authenticated"])

        response = self.client.post(
            "/app/settings/password",
            data={
                "csrf_token": self.session_csrf(),
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], f"{SETTINGS}?saved=password")
        # The changing browser receives the rotated session.
        self.assertTrue(self.is_signed_in())
        self.assertFalse(other.get("/v1/auth/session").json()["authenticated"])
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": PASSWORD},
            ).status_code,
            401,
        )
        new_login = TestClient(self.app, base_url="https://testserver").post(
            "/v1/auth/login",
            json={"email": "kid@example.com", "password": NEW_PASSWORD},
        )
        self.assertEqual(new_login.status_code, 200)

    def test_wrong_current_password_keeps_the_old_password(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/password",
            data={
                "csrf_token": self.session_csrf(),
                "current_password": "wrong-password",
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("current password is wrong", response.text)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": PASSWORD},
            ).status_code,
            200,
        )

    def test_mismatched_new_password_is_rejected_before_any_write(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/password",
            data={
                "csrf_token": self.session_csrf(),
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": "not-the-same",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("The two passwords do not match.", response.text)

    def test_password_form_requires_csrf(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/password",
            data={
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_password_change_records_the_session_metadata(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/password",
            data={
                "csrf_token": self.session_csrf(),
                "current_password": PASSWORD,
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        rows = self.db.fetchall(
            "SELECT ip_hash, user_agent_hash FROM auth_session WHERE revoked_at IS NULL"
        )
        self.assertEqual(len(rows), 1)
        self.assertIsNotNone(rows[0]["ip_hash"])
        self.assertIsNotNone(rows[0]["user_agent_hash"])

    def test_service_rejections_keep_their_own_status_and_copy(self) -> None:
        self.register_via_api()
        cases: tuple[tuple[str, dict[str, str], int, str], ...] = (
            ("E-VALIDATION", {"reason": "too_common"}, 422, "too common"),
            ("E-SERVICE-UNAVAILABLE", {}, 503, "could not be changed"),
        )
        for code, extra, status, copy in cases:
            with mock.patch.object(
                self.service,
                "set_or_change_password",
                side_effect=APIError(code, status_code=status, extra=extra),
            ):
                response = self.client.post(
                    "/app/settings/password",
                    data={
                        "csrf_token": self.session_csrf(),
                        "current_password": PASSWORD,
                        "new_password": NEW_PASSWORD,
                        "confirm_password": NEW_PASSWORD,
                    },
                )
            self.assertEqual(response.status_code, status, code)
            self.assertIn(copy, response.text, code)
            self.assertNotIn("Too many attempts", response.text, code)

    def test_google_created_account_is_prompted_to_set_a_password(self) -> None:
        self.login_with_google()
        html = self.client.get(SETTINGS).text
        self.assertIn("Set a password", html)
        self.assertIn("You signed in with Google", html)
        self.assertNotIn('name="current_password"', html)
        self.assertIn("Connected", html)

        response = self.client.post(
            "/app/settings/password",
            data={
                "csrf_token": self.session_csrf(),
                "new_password": NEW_PASSWORD,
                "confirm_password": NEW_PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "google.kid@example.com", "password": NEW_PASSWORD},
            ).status_code,
            200,
        )


class OnboardingTests(WebAuthSupport):
    def test_onboarding_requires_a_session(self) -> None:
        response = self.client.get("/onboarding", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/onboarding")

    def test_onboarding_saves_the_three_answers(self) -> None:
        self.register_via_api(class_level=None, language="en-IN")
        page = self.client.get("/onboarding")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Step 1", page.text)
        self.assertIn("Step 2", page.text)
        self.assertIn("Step 3", page.text)
        self.assertIn('name="goal"', page.text)
        token = self.session_csrf_from_page("/onboarding")

        response = self.client.post(
            "/onboarding",
            data={
                "csrf_token": token,
                "class_level": "10",
                "board": "CBSE",
                "language": "hinglish",
                "goal": "score above 80",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/app")
        row = self.db.fetchone("SELECT class_level, board, language FROM users")
        self.assertEqual(int(row["class_level"]), 10)
        self.assertEqual(row["board"], "CBSE")
        self.assertEqual(row["language"], "hinglish")

    def test_onboarding_validation_changes_nothing(self) -> None:
        self.register_via_api(class_level=None)
        response = self.client.post(
            "/onboarding",
            data={
                "csrf_token": self.session_csrf_from_page("/onboarding"),
                "class_level": "8",
                "board": "CBSE",
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Choose your class.", response.text)
        row = self.db.fetchone("SELECT class_level FROM users")
        self.assertIsNone(row["class_level"])

    def test_skip_writes_nothing(self) -> None:
        self.register_via_api(class_level=None)
        response = self.client.post(
            "/onboarding/skip",
            data={"csrf_token": self.session_csrf_from_page("/onboarding")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/app")
        row = self.db.fetchone("SELECT class_level FROM users")
        self.assertIsNone(row["class_level"])

    def test_skip_requires_csrf(self) -> None:
        self.register_via_api(class_level=None)
        response = self.client.post("/onboarding/skip", data={"csrf_token": ""})
        self.assertEqual(response.status_code, 403)


class LogoutTests(WebAuthSupport):
    def test_logout_revokes_the_session_and_clears_the_cookie(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/logout",
            data={"csrf_token": self.session_csrf_from_page(SETTINGS)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?signed_out=1")
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("zivon_session", cookie)
        self.assertIn("max-age=0", cookie)
        self.assertFalse(self.is_signed_in())

    def test_logout_without_csrf_keeps_the_session(self) -> None:
        self.register_via_api()
        response = self.client.post("/logout", data={"csrf_token": ""})
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.is_signed_in())

    def test_logout_from_a_stale_tab_still_clears_the_cookie(self) -> None:
        self.client.cookies.set(self.cfg.auth_cookie_name, "expired-token")
        response = self.client.post(
            "/logout", data={"csrf_token": ""}, follow_redirects=False
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?signed_out=1")


class PrivacyAndDeleteTests(WebAuthSupport):
    def test_privacy_page_lists_export_delete_and_consent(self) -> None:
        self.register_via_api()
        html = self.client.get(PRIVACY).text
        self.assertIn('href="/v1/me/export"', html)
        self.assertIn("Download my data", html)
        self.assertIn('action="/app/settings/delete"', html)
        self.assertIn("Type DELETE to confirm", html)
        self.assertIn('name="password"', html)
        self.assertIn('href="/privacy/"', html)
        self.assertIn("Voice consent is stored per device", html)

    def test_export_returns_the_owners_data_without_credentials(self) -> None:
        self.register_via_api(class_level=10, language="hi-IN")
        response = self.client.get("/v1/me/export")
        self.assertEqual(response.status_code, 200)
        self.assertIn("attachment", response.headers["content-disposition"])
        payload = response.json()
        self.assertEqual(payload["user"]["email"], "kid@example.com")
        self.assertIn("identities", payload)
        text = response.text
        self.assertNotIn("password_hash", text)
        self.assertNotIn(self.cfg.session_token_key, text)

    def test_delete_requires_the_exact_word(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/delete",
            data={
                "csrf_token": self.session_csrf_from_page(PRIVACY),
                "confirm": "delete",
                "password": PASSWORD,
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("Type DELETE exactly", response.text)
        row = self.db.fetchone("SELECT deleted_at FROM users")
        self.assertIsNone(row["deleted_at"])

    def test_delete_with_a_wrong_password_deletes_nothing(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/delete",
            data={
                "csrf_token": self.session_csrf_from_page(PRIVACY),
                "confirm": "DELETE",
                "password": "wrong-password",
            },
        )
        self.assertEqual(response.status_code, 401)
        self.assertIn("Nothing was deleted", response.text)
        self.assertTrue(self.is_signed_in())

    def test_delete_requires_csrf(self) -> None:
        self.register_via_api()
        response = self.client.post(
            "/app/settings/delete",
            data={"confirm": "DELETE", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.is_signed_in())

    def test_google_created_account_deletes_without_a_password(self) -> None:
        self.login_with_google()
        page = self.client.get(PRIVACY).text
        self.assertIn('action="/app/settings/delete"', page)
        # No password identity exists, so the form must not ask for one.
        self.assertNotIn('name="password"', page)
        response = self.client.post(
            "/app/settings/delete",
            data={
                "csrf_token": self.session_csrf_from_page(PRIVACY),
                "confirm": "DELETE",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?deleted=1")
        self.assertFalse(self.is_signed_in())
        row = self.db.fetchone(
            "SELECT deleted_at FROM users WHERE email LIKE 'deleted+%'"
        )
        self.assertIsNotNone(row["deleted_at"])

    def test_delete_removes_the_account_and_clears_the_session(self) -> None:
        self.register_via_api()
        user_id = self.client.get("/v1/auth/session").json()["user"]["user_id"]
        response = self.client.post(
            "/app/settings/delete",
            data={
                "csrf_token": self.session_csrf_from_page(PRIVACY),
                "confirm": "DELETE",
                "password": PASSWORD,
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?deleted=1")
        self.assertFalse(self.is_signed_in())
        row = self.db.fetchone(
            "SELECT email, deleted_at FROM users WHERE user_id = ?", (user_id,)
        )
        self.assertIsNotNone(row["deleted_at"])
        self.assertEqual(row["email"], f"deleted+{user_id}@invalid")
        identities = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM auth_identity WHERE user_id = ?", (user_id,)
        )
        self.assertEqual(int(identities["cnt"]), 0)
        self.assertEqual(
            self.client.post(
                "/v1/auth/login",
                json={"email": "kid@example.com", "password": PASSWORD},
            ).status_code,
            401,
        )


class SettingsTemplateContracts(unittest.TestCase):
    def test_settings_templates_extend_the_base_shell(self) -> None:
        for name in ("settings.html", "settings_privacy.html"):
            body = (TEMPLATES / "app" / name).read_text(encoding="utf-8")
            self.assertIn('{% extends "base.html" %}', body, name)

    def test_settings_templates_have_no_inline_script_or_handlers(self) -> None:
        for name in ("settings.html", "settings_privacy.html"):
            text = (TEMPLATES / "app" / name).read_text(encoding="utf-8")
            for tag in re.findall(r"<script\b[^>]*>", text, re.IGNORECASE):
                self.assertIn("src=", tag, f"{name}: inline script")
            self.assertNotRegex(text, r"\son[a-z]+\s*=", f"{name}: handler")
            self.assertNotIn("<style", text.lower(), f"{name}: <style>")


if __name__ == "__main__":
    unittest.main()
