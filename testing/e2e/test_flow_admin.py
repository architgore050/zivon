"""Flow 10 (§17.1): admin — coverage, series gate, question health, behind
the admin token (ADR-0026 on the dashboard, `X-Admin-Token` on the API).

The kid's session cookie is an account credential, not a staff one: every
`/v1/admin/*` path answers 401 to it and every F10 dashboard panel bounces it
(303 to the staff login for a browser, 401 JSON for an API client). The staff
panels read REAL aggregates: the store seam is pointed at the same seeded
SQLite store the student flows use (rows arrived through the real importers),
so the coverage/series/health numbers are computed, never faked.
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend import create_app as create_backend
from dashboard import create_app as create_dashboard

from .support import (
    SERIES_FIXTURE_DIR,
    E2EFlow,
    load_script,
    make_config,
    patch_product_store,
)

ADMIN_TOKEN = "e2e-admin-token-0123456789"
ADMIN_API_PATHS = (
    "/v1/admin/summary",
    "/v1/admin/sessions",
    "/v1/admin/credits",
    "/v1/admin/guard",
    "/v1/admin/runs",
    "/v1/admin/reports",
    "/v1/admin/audit",
)


class DashboardAdminFlowTests(E2EFlow):
    """The F10 panels + `/v1/admin/*` through the real guard flows.

    One setUp wires BOTH surfaces over the same seeded store: the student
    backend app (which issues the kid session cookie under test) and the
    dashboard app with `ProductStore.from_env` pointed at the seeded SQLite
    database. The salvaged file's second setUp silently replaced the first,
    which killed the dashboard-panel flow; this class has exactly one.
    """

    series_importer = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.series_importer = load_script(
            "import_series_packs_e2e_admin", "import_series_packs.py"
        )
        cls.series_importer.import_packs(cls.db, SERIES_FIXTURE_DIR)

    def setUp(self) -> None:
        super().setUp()
        self._restore = patch_product_store(self.db)
        os.environ["ZIVON_ADMIN_TOKEN"] = ADMIN_TOKEN
        self.dash = create_dashboard()
        self.dclient = TestClient(self.dash, base_url="https://testserver")
        cfg = make_config(self.root, admin_token=ADMIN_TOKEN)
        self.admin_app = create_backend(cfg, db_engine=self.db)
        self.admin_client = TestClient(self.admin_app, base_url="https://testserver")

    def tearDown(self) -> None:
        self.admin_client.close()
        self.dclient.close()
        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        self._restore()
        super().tearDown()

    # -- helpers -------------------------------------------------------------

    def login_admin(self, token: str) -> TestClient:
        """A staff browser: real /admin/login form POST, session cookie set."""
        browser = TestClient(self.dash, base_url="https://testserver")
        form = browser.get("/admin/login")
        self.assertEqual(form.status_code, 200, form.text)
        match = re.search(
            r'name="csrf"\s+value="([^"]+)"|value="([^"]+)"\s+name="csrf"',
            form.text,
        )
        self.assertIsNotNone(match, "the login form carries its CSRF field")
        assert match is not None
        csrf = match.group(1) or match.group(2)
        response = browser.post(
            "/admin/login",
            data={"csrf": csrf, "token": token},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/admin")
        return browser

    def panel_row_counts(self, table: str, column: str) -> dict[str, int]:
        """The seeded store's own aggregate, for cross-checking the panel."""
        rows = self.db.fetchall(
            f"SELECT {column} AS key, COUNT(*) AS n FROM {table} GROUP BY {column}"
        )
        return {str(row["key"]): int(row["n"]) for row in rows}

    # -- fail-closed without the token ----------------------------------------

    def test_fail_closed_without_the_token(self) -> None:
        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        bare = create_dashboard()
        client = TestClient(bare, base_url="https://testserver")
        try:
            response = client.get("/admin/content")
            self.assertEqual(response.status_code, 503, response.text[:300])
        finally:
            client.close()

    def test_unconfigured_api_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = make_config(Path(tmp), admin_token=None)
            app = create_backend(cfg, db_engine=self.db)
            client = TestClient(app, base_url="https://testserver")
            try:
                response = client.get("/v1/admin/summary")
                self.assertEqual(response.status_code, 503, response.text)
                self.assertEqual(response.json()["code"], "E-SERVICE-UNAVAILABLE")
            finally:
                client.close()

    # -- the kid session is not a staff credential -----------------------------

    def test_kid_session_cookie_never_grants_the_admin_api(self) -> None:
        """Every `/v1/admin/*` path answers 401 to the student's cookie+CSRF:
        the kid account header set carries no bearer token, and the API has
        no cookie path at all (ADR-0026)."""
        kid_headers = {"X-CSRF-Token": self.csrf, "X-Device-Id": self.device_id}
        for path in ADMIN_API_PATHS:
            response = self.admin_client.get(path, headers=kid_headers)
            self.assertEqual(
                response.status_code,
                401,
                f"{path}: a kid session must never open the admin API "
                f"({response.text[:200]})",
            )
        action = self.admin_client.post(
            "/v1/admin/actions/run-tests", json={}, headers=kid_headers
        )
        self.assertEqual(action.status_code, 401, action.text[:200])
        forged = self.admin_client.get(
            "/v1/admin/summary",
            headers={"Authorization": f"Bearer {self.csrf}"},
        )
        self.assertEqual(forged.status_code, 401, "a CSRF value is not a token")

    def test_kid_session_never_reaches_the_f10_panels(self) -> None:
        """The kid cookie on the dashboard: a browser gets the 303 staff
        login, an API client gets the 401 JSON — never a panel."""
        kid_cookie = self.client.cookies.get("zivon_session")
        self.assertTrue(kid_cookie, "the kid browser holds a session cookie")
        self.dclient.cookies.set("zivon_session", str(kid_cookie))
        html = self.dclient.get(
            "/admin/content",
            headers={"Accept": "text/html"},
            follow_redirects=False,
        )
        self.assertEqual(html.status_code, 303, html.text[:300])
        self.assertEqual(html.headers["location"], "/admin/login")
        api = self.dclient.get(
            "/admin/questions",
            headers={"Accept": "application/json"},
        )
        self.dclient.cookies.clear()
        self.assertEqual(api.status_code, 401, api.text[:300])
        self.assertEqual(api.json()["error"], "unauthenticated")

    # -- the staff path -------------------------------------------------------

    def test_wrong_staff_token_is_rejected_and_sets_no_session(self) -> None:
        browser = TestClient(self.dash, base_url="https://testserver")
        form = browser.get("/admin/login")
        match = re.search(
            r'name="csrf"\s+value="([^"]+)"|value="([^"]+)"\s+name="csrf"',
            form.text,
        )
        assert match is not None
        response = browser.post(
            "/admin/login",
            data={"csrf": match.group(1) or match.group(2), "token": "not-it"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 401, response.text[:300])
        self.assertIn("invalid token", response.text)
        panels = browser.get(
            "/admin", headers={"Accept": "text/html"}, follow_redirects=False
        )
        self.assertEqual(panels.status_code, 303, "no session was minted")

    def test_staff_login_renders_seeded_store_aggregates(self) -> None:
        """After the real staff login the panels show the seeded store's REAL
        numbers: bank health from question_bank, the imported series rows,
        and the honest empty coverage state (no content_page rows exist)."""
        browser = self.login_admin(ADMIN_TOKEN)
        questions = browser.get("/admin/questions")
        self.assertEqual(questions.status_code, 200, questions.text[:300])
        by_status = self.panel_row_counts("question_bank", "status")
        for status, count in by_status.items():
            self.assertIn(
                f"{status}: {count}",
                questions.text,
                "the bank-health tile mirrors the seeded store",
            )
        prompts = self.panel_row_counts("speaking_prompt", "status")
        for status, count in prompts.items():
            self.assertIn(
                f'<span class="state {status}">{status}</span></td><td>{count}</td>',
                questions.text,
                "the prompts table mirrors the seeded store's counts",
            )

        series = browser.get("/admin/series")
        self.assertEqual(series.status_code, 200, series.text[:300])
        series_rows = self.db.fetchall(
            "SELECT slug, status FROM test_series ORDER BY slug"
        )
        self.assertTrue(series_rows, "the series importer seeded the catalogue")
        for row in series_rows:
            self.assertIn(str(row["slug"]), series.text, "real series rows render")
        self.assertIn("class-10-board_practice", series.text)
        self.assertIn("published", series.text)

        coverage = browser.get("/admin/content")
        self.assertEqual(coverage.status_code, 200, coverage.text[:300])
        self.assertIn(
            "no pages registered yet",
            coverage.text,
            "honest empty coverage: the seeded store has no content_page rows",
        )

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


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
