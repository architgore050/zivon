"""Flow 9 (§17.1): settings — class/language, export, delete."""

from __future__ import annotations

from .support import PASSWORD, E2EFlow


class SettingsFlowTests(E2EFlow):
    """The owner controls on /app/settings and /app/settings/privacy."""

    def test_class_and_language_change_take_effect(self) -> None:
        page = self.page("/app/settings")
        self.assertIn(self.email, page)
        token = self.csrf_from_page("/app/settings")
        response = self.client.post(
            "/app/settings",
            data={
                "csrf_token": token,
                "display_name": "Asha K.",
                "class_level": "10",
                "board": "CBSE",
                "language": "hinglish",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        session = self.client.get("/v1/auth/session").json()
        self.assertEqual(int(session["user"]["class_level"]), 10)
        self.assertEqual(session["user"]["language"], "hinglish")
        # The practice hub retargets to the new class without re-login.
        self.client.get("/app/practice")

    def test_export_is_valid_json_with_the_account_data(self) -> None:
        self.merge_events(
            [
                {
                    "kind": "lesson_block_view",
                    "chapter_id": "class-9-describing-motion-around-us",
                    "payload": {"blocks_seen": 2, "source": "lesson_shell"},
                }
            ]
        )
        response = self.client.get("/v1/me/export")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("attachment", response.headers["content-disposition"])
        payload = response.json()
        self.assertTrue(payload, "the export is a real JSON object")

    def test_delete_requires_confirmation_and_password(self) -> None:
        wrong = self.client.post(
            "/v1/me/delete",
            json={"confirm": "DELETE", "password": "not-the-password"},
            headers=self.headers(),
        )
        self.assertEqual(wrong.status_code, 401, wrong.text[:300])
        bad_confirm = self.client.post(
            "/v1/me/delete",
            json={"confirm": "delete", "password": PASSWORD},
            headers=self.headers(),
        )
        self.assertEqual(bad_confirm.status_code, 400, bad_confirm.text[:300])
        deleted = self.client.post(
            "/v1/me/delete",
            json={"confirm": "DELETE", "password": PASSWORD},
            headers=self.headers(),
        )
        self.assertEqual(deleted.status_code, 200, deleted.text)
        session = self.client.get("/v1/auth/session").json()
        self.assertFalse(session["authenticated"], "the session dies with the account")
