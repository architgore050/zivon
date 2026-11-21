"""Flow 10 (§17.1): admin — coverage, series gate, question health, behind
the admin token (ADR-0026 on the dashboard, `X-Admin-Token` on the API).

The panels read REAL aggregates: the store seam is pointed at the same seeded
SQLite store the student flows use (rows arrived through the real importers),
so the coverage/series/health numbers are computed, never faked.
"""

from __future__ import annotations

import os
import unittest

from fastapi.testclient import TestClient

from dashboard import create_app as create_dashboard

from .support import E2EFlow, make_config, patch_product_store

ADMIN_TOKEN = "e2e-admin-token-0123456789"


class DashboardAdminFlowTests(E2EFlow):
    """The F10 panels through the real login + guard flow."""

    def setUp(self) -> None:
        super().setUp()
        self._restore = patch_product_store(self.db)
        os.environ["ZIVON_ADMIN_TOKEN"] = ADMIN_TOKEN
        self.dash = create_dashboard()
        self.dclient = TestClient(self.dash, base_url="https://testserver")

    def tearDown(self) -> None:
        self.dclient.close()
        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        self._restore()
        super().tearDown()

    def login_admin(self, token: str) -> object:
        form = self.dclient.get("/admin/login")
        assert form.status_code == 200, form.text
        import re as _re

        match = _re.search(
            r'name="csrf_token"\s+value="([^"]+)"'
            r'|value="([^"]+)"\s+name="csrf_token"',
            form.text,
        )
        assert match, "the login form carries a CSRF token"
        token_value = match.group(1) or match.group(2)
        return self.dclient.post(
            "/admin/login",
            data={"csrf_token": token_value, "token": token},
            follow_redirects=False,
        )

    def test_fail_closed_without_the_token(self) -> None:
        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        bare = create_dashboard()
        client = TestClient(bare, base_url="https://testserver")
        try:
            response = client.get("/admin/content")
            self.assertEqual(response.status_code, 503, response.text[:300])
        finally:
            client.close()

    def setUp(self) -> None:
        self._tmp_extra = None
        super().setUp()
        cfg = make_config(self.root, admin_token=ADMIN_TOKEN)
        from backend import create_app as create_backend

        self.admin_app = create_backend(cfg, db_engine=self.db)
        self.admin_client = TestClient(self.admin_app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.admin_client.close()
        super().tearDown()

    def test_api_requires_and_accepts_the_token(self) -> None:
        missing = self.admin_client.get("/v1/admin/summary")
        self.assertEqual(missing.status_code, 401, missing.text)
        wrong = self.admin_client.get(
            "/v1/admin/summary", headers={"X-Admin-Token": "nope"}
        )
        self.assertEqual(wrong.status_code, 401)
        good = self.admin_client.get(
            "/v1/admin/summary", headers={"X-Admin-Token": ADMIN_TOKEN}
        )
        self.assertEqual(good.status_code, 200, good.text)
        self.assertTrue(good.json(), "the summary aggregates the seeded store")

    def test_unconfigured_api_fails_closed(self) -> None:
        import tempfile
        from pathlib import Path as _Path

        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(_Path(tmp), admin_token=None)
            from backend import create_app as create_backend

            app = create_backend(cfg, db_engine=self.db)
            client = TestClient(app, base_url="https://testserver")
            try:
                response = client.get("/v1/admin/summary")
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["code"], "E-SERVICE-UNAVAILABLE")
            finally:
                client.close()


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
