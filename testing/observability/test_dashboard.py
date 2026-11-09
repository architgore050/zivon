"""Dashboard endpoint tests against seeded fixtures (dashboard-spec.md §3/§4).

The store seam is `LogStore.connection`: tests inject a stub connection whose
cursor returns seeded rows for the view SQL — no live Postgres needed. Auth
is exercised against the real ADR-0026 flow (fail-closed, lockout, CSRF,
session cookie)."""

from __future__ import annotations

import re
import unittest
import unittest.mock
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any, Self  # Self: PYI034 wants it on __enter__

from fastapi.testclient import TestClient

from dashboard import create_app
from dashboard.queries import LogStore

TOKEN = "dashboard-test-token-0123456789"


# ---------------------------------------------------------------------------
# a seeded stub connection: rows keyed by the view SQL's markers
# ---------------------------------------------------------------------------


def _ts(minutes_ago: int) -> str:
    return (datetime.now(UTC) - timedelta(minutes=minutes_ago)).isoformat()


class _FakeCursor:
    """Returns seeded rows per view SQL; columns are declared per branch so
    _fetchall's dict(zip(...)) builds the rows the templates expect."""

    def __init__(self, parent: _FakeConnection) -> None:
        self._parent = parent
        self._sql = ""
        self.description: Any = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._sql = sql
        self.description = [(name,) for name in self._columns_for(sql)]

    def _columns_for(self, sql: str) -> list[str]:
        if "percentile_cont" in sql and "fields ?" in sql:
            return ["p95", "avg_ms"]  # per-hop aggregates
        if "percentile_cont" in sql:
            return ["p50", "p95", "max_ms", "n"]  # overall voice window
        if "slowest_hop" in sql:
            return ["hop", "n"]
        if "credit.counter_update" in sql:
            return ["profile", "used", "cap", "ts"]
        if "credit.guard_blocked" in sql:
            return ["ts", "profile", "requested", "remaining"]
        if "redaction_violation" in sql:
            return ["ts", "event_ref", "key", "kind"]
        if "severity IN" in sql:
            return [
                "ts",
                "event",
                "component",
                "severity",
                "error_class",
                "run_id",
                "session_id",
                "turn_id",
                "request_id",
                "fields",
            ]
        if "factory.publish." in sql:
            return ["run_id", "event", "ts", "target", "reason_code", "asset_count"]
        if "factory.run.failed" in sql:
            return ["run_id", "ts"]
        if "factory.run.completed" in sql:
            return ["run_id", "ts", "blocks_published"]
        if "factory.run.%" in sql:
            return [
                "run_id",
                "event",
                "severity",
                "ts",
                "error_class",
                "chapter",
                "class_level",
                "reason_code",
            ]
        if "factory.stage." in sql:
            return [
                "stage",
                "event",
                "severity",
                "ts",
                "latency_ms",
                "error_class",
                "reason_code",
                "blocks",
                "attempts",
            ]
        if "factory.repair." in sql:
            return [
                "stage",
                "event",
                "ts",
                "round",
                "issues_count",
                "plateau",
                "cap_hit",
            ]
        if "factory.call." in sql:
            return [
                "event",
                "ts",
                "latency_ms",
                "error_class",
                "call_intent",
                "attempts",
            ]
        return []

    def fetchall(self) -> list[tuple[Any, ...]]:
        sql = self._sql
        if "FROM log_events" not in sql:
            return []
        if "percentile_cont" in sql and "fields ?" in sql:
            return [(580.0, 420.0)]
        if "percentile_cont" in sql:
            return [(3100.0, 3900.0, 4100.0, 12)]
        if "slowest_hop" in sql:
            return [("tts_first_audio", 7)]
        if "credit.counter_update" in sql:
            return [("demo", 1200, 2000, _ts(10)), ("normal", 900, 1000, _ts(5))]
        if "credit.guard_blocked" in sql:
            return [(_ts(3), "normal", "5", "25")]
        if "redaction_violation" in sql:
            return [(_ts(1), "factory.stage.ok", "token", "key-denylist")]
        if "severity IN" in sql:
            return [
                (
                    _ts(2),
                    "factory.run.failed",
                    "factory",
                    "ERROR",
                    "repair_exhausted",
                    "motion-c9",
                    None,
                    None,
                    None,
                    {},
                )
            ]
        if "factory.publish." in sql:
            return [(_ts(30), "factory.publish.ok", "motion-c9", "pvc", None, "3")]
        if "factory.run.failed" in sql:
            return [("motion-c9", _ts(2))]
        if "factory.run.completed" in sql:
            return [("motion-c9", _ts(20), "14")]
        if "factory.run.%" in sql:
            return [
                (
                    "motion-c9",
                    "factory.run.completed",
                    "INFO",
                    _ts(20),
                    None,
                    "Motion",
                    "9",
                    None,
                ),
                (
                    "motion-c9",
                    "factory.run.failed",
                    "ERROR",
                    _ts(2),
                    "repair_exhausted",
                    "Motion",
                    "9",
                    "catcher_exhausted",
                ),
            ]
        if "factory.stage." in sql:
            return [
                (
                    "02-generate",
                    "factory.stage.ok",
                    "INFO",
                    _ts(15),
                    61000,
                    None,
                    None,
                    "14",
                    "1",
                )
            ]
        if "factory.repair." in sql:
            return [
                ("08-fixloop", "factory.repair.round", _ts(14), "2", "1", None, None)
            ]
        if "factory.call." in sql:
            return [("factory.call.finished", _ts(16), 60000, None, "generate", "1")]
        return []

    def fetchone(self) -> None:
        return None

    def executemany(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, rows: dict[str, Any] | None = None) -> None:
        self.rows = rows or {}

    def cursor(self) -> _FakeCursor:
        return _FakeCursor(self)

    def close(self) -> None:
        return None


def _seeded_store() -> LogStore:
    return LogStore(connection=_FakeConnection())


@contextmanager
def _seeded_app():
    """create_app with the store seam pointing at the seeded stub."""
    import os

    os.environ["ZIVON_ADMIN_TOKEN"] = TOKEN
    os.environ.pop("ZIVON_LOG_DSN", None)
    original_from_env = LogStore.from_env
    LogStore.from_env = classmethod(lambda cls: _seeded_store())  # type: ignore[assignment]
    try:
        client = TestClient(create_app())
        yield client
    finally:
        LogStore.from_env = original_from_env  # type: ignore[assignment]
        os.environ.pop("ZIVON_ADMIN_TOKEN")


def _csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "no CSRF token rendered"
    return match.group(1)


def _login(client: TestClient) -> str:
    page = client.get("/admin/login")
    csrf = _csrf_of(page.text)
    response = client.post(
        "/admin/login", data={"token": TOKEN, "csrf": csrf}, follow_redirects=False
    )
    assert response.status_code == 303, response.status_code
    return csrf


# ---------------------------------------------------------------------------


class AuthTests(unittest.TestCase):
    def test_fail_closed_without_token(self) -> None:
        import os

        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        try:
            client = TestClient(create_app())
            self.assertEqual(client.get("/healthz").status_code, 200)
            self.assertEqual(client.get("/admin").status_code, 503)
            self.assertEqual(client.get("/admin/runs").status_code, 503)
            # healthz stays green even fail-closed (probes must not flap)
        finally:
            os.environ.pop("ZIVON_ADMIN_TOKEN", None)

    def test_unauthenticated_browser_is_redirected(self) -> None:
        with _seeded_app() as client:
            response = client.get(
                "/admin",
                headers={"accept": "text/html,application/xhtml+xml"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/admin/login")

    def test_unauthenticated_api_gets_401(self) -> None:
        with _seeded_app() as client:
            response = client.get(
                "/admin", headers={"accept": "application/json"}, follow_redirects=False
            )
            self.assertEqual(response.status_code, 401)

    def test_login_rejects_wrong_token_then_accepts_right(self) -> None:
        with _seeded_app() as client:
            page = client.get("/admin/login")
            csrf = _csrf_of(page.text)
            bad = client.post("/admin/login", data={"token": "nope", "csrf": csrf})
            self.assertEqual(bad.status_code, 401)
            good = client.post(
                "/admin/login",
                data={"token": TOKEN, "csrf": csrf},
                follow_redirects=False,
            )
            self.assertEqual(good.status_code, 303)
            cookie = good.headers["set-cookie"]
            self.assertIn("HttpOnly", cookie)
            self.assertIn(
                "SameSite=strict", cookie.replace("SameSite=Strict", "SameSite=strict")
            )

    def test_stale_login_csrf_is_rejected(self) -> None:
        with _seeded_app() as client:
            response = client.post(
                "/admin/login", data={"token": TOKEN, "csrf": "1:deadbeef"}
            )
            self.assertEqual(response.status_code, 401)

    def test_lockout_after_five_failures(self) -> None:
        with _seeded_app() as client:
            page = client.get("/admin/login")
            csrf = _csrf_of(page.text)
            for _ in range(5):
                client.post("/admin/login", data={"token": "nope", "csrf": csrf})
            sixth = client.post("/admin/login", data={"token": "nope", "csrf": csrf})
            self.assertEqual(sixth.status_code, 401)
            # even the CORRECT token is refused while locked out
            locked = client.post("/admin/login", data={"token": TOKEN, "csrf": csrf})
            self.assertEqual(locked.status_code, 401)


class SeededViewTests(unittest.TestCase):
    def test_overview_renders_seeded_tiles_and_alert_banner(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin")
            self.assertEqual(page.status_code, 200)
            self.assertIn("alert.pipeline_run_failed", page.text)
            self.assertIn("3900", page.text)  # the seeded p95

    def test_runs_view_lists_seeded_run(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/runs")
            self.assertIn("motion-c9", page.text)
            self.assertIn("manual-only", page.text)

    def test_voice_view_renders_percentiles_with_budget_line(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/voice")
            self.assertIn("4000", page.text)
            self.assertIn("p95", page.text.lower())

    def test_credits_view_renders_profiles_and_guard_refusals(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/credits")
            self.assertIn("demo", page.text)
            self.assertIn("normal", page.text)
            self.assertIn("Guard refusals", page.text)

    def test_errors_view_groups_by_class_and_pins_violations(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/errors")
            self.assertIn("repair_exhausted", page.text)
            self.assertIn("Redaction violations", page.text)
            self.assertIn("token", page.text)

    def test_publish_view_renders_honest_empty_or_seeded(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/publish")
            self.assertEqual(page.status_code, 200)

    def test_run_detail_renders_stages_repairs_calls(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/runs/motion-c9")
            self.assertEqual(page.status_code, 200)
            self.assertIn("Repair-catcher rounds", page.text)
            self.assertIn("factory.call.finished", page.text)


class HonestEmptyStateTests(unittest.TestCase):
    def test_views_render_no_data_when_store_is_unset(self) -> None:
        import os

        os.environ["ZIVON_ADMIN_TOKEN"] = TOKEN
        os.environ.pop("ZIVON_LOG_DSN", None)
        try:
            client = TestClient(create_app())
            _login(client)
            for path in ("/admin", "/admin/voice", "/admin/credits", "/admin/errors"):
                page = client.get(path)
                self.assertEqual(page.status_code, 200, path)
            self.assertIn("No voice traffic yet", client.get("/admin/voice").text)
            self.assertIn("No credit counters", client.get("/admin/credits").text)
        finally:
            os.environ.pop("ZIVON_ADMIN_TOKEN")


class ActionTests(unittest.TestCase):
    def test_buttons_require_csrf(self) -> None:
        with _seeded_app() as client:
            _login(client)
            response = client.post("/admin/actions/tests-now", data={"csrf": "bad"})
            self.assertEqual(response.status_code, 403)

    def test_tests_now_button_invokes_the_script(self) -> None:
        with (
            _seeded_app() as client,
            unittest.mock.patch("dashboard.app.subprocess.run", create=True) as run,
        ):
            run.return_value = unittest.mock.Mock(
                returncode=0, stdout="job/test-dashboard-1", stderr=""
            )
            _login(client)
            csrf = _csrf_of(client.get("/admin").text)
            response = client.post(
                "/admin/actions/tests-now",
                data={"csrf": csrf},
                headers={"accept": "text/html"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            args = run.call_args[0][0]
            self.assertIn("trigger-tests.sh", args[0])

    def test_factory_run_validates_topic_and_class(self) -> None:
        with _seeded_app() as client:
            _login(client)
            csrf = _csrf_of(client.get("/admin").text)
            self.assertEqual(
                client.post(
                    "/admin/actions/factory-run", data={"csrf": csrf, "topic": " "}
                ).status_code,
                422,
            )
            self.assertEqual(
                client.post(
                    "/admin/actions/factory-run",
                    data={"csrf": csrf, "topic": "Motion", "class_level": "42"},
                ).status_code,
                422,
            )

    def test_factory_run_refuses_while_a_job_is_active(self) -> None:
        import dashboard.app as mod

        with (
            _seeded_app() as client,
            unittest.mock.patch.object(
                mod, "factory_run_in_progress", return_value=True
            ),
        ):
            _login(client)
            csrf = _csrf_of(client.get("/admin").text)
            response = client.post(
                "/admin/actions/factory-run",
                data={
                    "csrf": csrf,
                    "topic": "Motion",
                    "class_level": "9",
                    "fresh": "1",
                },
            )
            self.assertEqual(response.status_code, 409)
            self.assertIn("manual-only", response.json()["error"])


class SecurityHeaderTests(unittest.TestCase):
    def test_csp_and_request_id_on_every_response(self) -> None:
        with _seeded_app() as client:
            response = client.get("/healthz")
            self.assertIn(
                "default-src 'self'", response.headers["content-security-policy"]
            )
            self.assertIn("nosniff", response.headers["x-content-type-options"])
            self.assertIn("no-store", response.headers["cache-control"])
            self.assertRegex(response.headers["x-request-id"], r"^[0-9a-f-]{36}$")
            # an inbound X-Request-Id is honored (logging-api.md §7)
            inbound = str(uuid.uuid4())
            echoed = client.get("/healthz", headers={"X-Request-Id": inbound})
            self.assertEqual(echoed.headers["x-request-id"], inbound)


if __name__ == "__main__":
    unittest.main()
