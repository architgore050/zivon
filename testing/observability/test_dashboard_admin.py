"""F10 admin-panel tests (docs/specs/frontend/admin.md): staff auth/guard,
aggregate-only reads, honest empty/partial states, and the privacy contract —
no student free text, no PII, no performance columns on any panel.

The store seams are the real `LogStore`/`ProductStore` connection attributes:
tests inject stub connections whose cursors return seeded rows per SQL marker
(no live Postgres). Auth runs the real ADR-0026 flow. Eval evidence is a temp
directory shaped like `evals_runs/` (the ledger + per-run report dirs)."""

from __future__ import annotations

import json
import os
import re
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Self

from fastapi.testclient import TestClient

from dashboard import create_app
from dashboard.product import ProductStore
from dashboard.queries import LogStore

from .support import ObservabilityTest

TOKEN = "dashboard-test-token-0123456789"

F10_PANELS = (
    "/admin/content",
    "/admin/questions",
    "/admin/series",
    "/admin/quality",
    "/admin/users",
    "/admin/reports",
    "/admin/flags",
    "/admin/evals",
)

SEEDED_REPORT_ID = "018f-aaaa-bbbb-cccc-dddd"
UNKNOWN_REPORT_ID = "ffffffff-ffff-ffff-ffff-ffffffffffff"

# Synthetic strings with a purpose: the free-text and PII strings are asserted
# ABSENT from every panel (NFR-30; admin.md privacy contract).
REPORT_TEXT = "the spring constant drawing looks wrong to me here"
REPORT_EMAIL = "learner-7@example.com"

# Content columns that must never be SELECTed onto a panel: item text and
# student words (NFR-30, F-OPS-ADM-01 AC-4). `misconception` is only ever
# aggregated (COUNT/SUM), never selected as a value.
_ITEM_TEXT_COLUMNS = ("prompt", "options", "answer", "explanation")


# ---------------------------------------------------------------------------
# seeded stub connection: rows keyed by the product SQL's markers
# ---------------------------------------------------------------------------


def _norm(sql: str) -> str:
    """Marker canonical form: whitespace collapsed, commas stripped, so the
    seed markers read like the SQL's column lists without punctuation."""
    return " ".join(sql.replace(",", " ").split())


class _FakeCursor:
    """Returns seeded rows per view SQL; column tuples (name,) feed
    _fetchall's getattr(c, "name", c[0]) — tuples have no .name so the
    eager default indexes [0], matching psycopg's description objects."""

    def __init__(self, parent: _FakeConnection) -> None:
        self._parent = parent
        self._sql = ""
        self.description: Any = None

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        self._sql = _norm(sql)
        self.description = [(name,) for name in self._columns_for(self._sql)]

    def _columns_for(self, sql: str) -> list[str]:
        if "class_level COUNT(*) AS pages" in sql:
            return ["class_level", "pages"]
        if "class_level status COUNT(*) AS versions" in sql:
            return ["class_level", "status", "versions"]
        if "live_pages" in sql:
            return ["class_level", "locale", "live_pages"]
        if "AS bundles" in sql:
            return ["locale", "bundles", "reviewed", "published"]
        if "assets COUNT(DISTINCT course_id)" in sql:
            return ["locale", "assets", "courses"]
        if "status COUNT(*) AS n FROM question_bank" in sql:
            return ["status", "n"]
        if "type COUNT(*) AS n" in sql:
            return ["type", "n"]
        if "difficulty COUNT(*) AS n" in sql:
            return ["difficulty", "n"]
        if "language COUNT(*) AS n FROM question_bank" in sql:
            return ["language", "n"]
        if "class_level COUNT(*) AS n FROM question_bank" in sql:
            return ["class_level", "n"]
        if "kind gate_verdict COUNT(*)" in sql:
            return ["kind", "gate_verdict", "n"]
        if "FROM speaking_prompt GROUP BY status" in sql:
            return ["status", "n"]
        if "FROM speaking_prompt GROUP BY language" in sql:
            return ["language", "n"]
        if "concepts_without_questions" in sql:
            return ["chapter_id", "concepts_without_questions"]
        if "topic_time_prior" in sql:
            return ["n"]
        if "series_id s.slug" in sql:
            return [
                "series_id",
                "slug",
                "class_level",
                "kind",
                "title",
                "status",
                "language_set",
                "tests",
                "questions",
            ]
        if "pack_id kind chapter_id" in sql:
            return [
                "pack_id",
                "kind",
                "chapter_id",
                "class_level",
                "pack_version",
                "gate_verdict",
                "counts",
                "imported_at",
            ]
        if "misconception_flagged" in sql:
            return [
                "total",
                "drafts",
                "retired",
                "misconception_flagged",
                "judged_mode",
                "human_mode",
            ]
        if "failing FROM assessment_pack" in sql:
            return ["kind", "failing"]
        if "unreviewed FROM language_bundle" in sql:
            return ["locale", "unreviewed"]
        if "pages_without_live" in sql:
            return ["pages_without_live"]
        if "category COUNT(*) AS n FROM problem_report" in sql:
            return ["category", "n"]
        if "role COUNT(*)" in sql:
            return ["role", "n"]
        if "email_verified_at IS NOT NULL" in sql:
            return ["n"]
        if "deleted_at IS NOT NULL" in sql:
            return ["n"]
        if "request_id scope status counts" in sql:
            return [
                "request_id",
                "scope",
                "status",
                "counts",
                "requested_at",
                "completed_at",
            ]
        if "FROM problem_report WHERE report_id" in sql:
            return ["status"]
        if "report_id course_id class_level" in sql:
            return [
                "report_id",
                "course_id",
                "class_level",
                "block_id",
                "category",
                "status",
                "created_at",
                "resolved_at",
            ]
        if "status COUNT(*) AS n FROM problem_report" in sql:
            return ["status", "n"]
        if "FROM guard_profile WHERE id" in sql:
            return [
                "mode",
                "global_tranche",
                "per_user_cap",
                "demo_global_tranche",
                "demo_per_user_cap",
                "warn_threshold_pct",
                "total_budget_credits",
                "demo_reserve_pct",
                "updated_at",
                "updated_by",
            ]
        if "guard_profile.flip" in sql:
            return ["at", "actor", "target", "before_hash", "after_hash"]
        return []

    def fetchall(self) -> list[tuple[Any, ...]]:
        sql = self._sql
        if self._parent.broken:
            raise RuntimeError("product store offline")
        if "class_level COUNT(*) AS pages" in sql:
            return [(9, 2), (10, 3)]
        if "class_level status COUNT(*) AS versions" in sql:
            return [(9, "published", 2), (10, "reviewed", 1)]
        if "live_pages" in sql:
            return [(9, "en-IN", 2), (9, "hi-IN", 1)]
        if "AS bundles" in sql:
            return [("en-IN", 5, 5, 4), ("hi-IN", 3, 2, 1)]
        if "assets COUNT(DISTINCT course_id)" in sql:
            return [("en-IN", 24, 2)]
        if "status COUNT(*) AS n FROM question_bank" in sql:
            return [("published", 40), ("draft", 7)]
        if "type COUNT(*) AS n" in sql:
            return [("mcq", 30), ("numeric", 17)]
        if "difficulty COUNT(*) AS n" in sql:
            return [("easy", 20), ("medium", 17), ("hard", 10)]
        if "language COUNT(*) AS n FROM question_bank" in sql:
            return [("en", 40), ("hi", 12), ("hi-Latn", 5)]
        if "class_level COUNT(*) AS n FROM question_bank" in sql:
            return [(9, 25), (10, 22)]
        if "kind gate_verdict COUNT(*)" in sql:
            return [("assessment", "pass", 4), ("exam", "fail", 1)]
        if "FROM speaking_prompt GROUP BY status" in sql:
            return [("published", 9)]
        if "FROM speaking_prompt GROUP BY language" in sql:
            return [("en", 5), ("hi", 4)]
        if "concepts_without_questions" in sql:
            return [("motion-c9", 2)]
        if "topic_time_prior" in sql:
            return [(18,)]
        if "series_id s.slug" in sql:
            return [
                (
                    "series-1",
                    "ai-lesson-c9",
                    9,
                    "ai_lesson",
                    "AI Lesson 9",
                    "published",
                    '["en","hi"]',
                    3,
                    30,
                )
            ]
        if "pack_id kind chapter_id" in sql:
            return [
                (
                    "exam-pack-1",
                    "exam",
                    "motion-c9",
                    9,
                    1,
                    "pass",
                    '{"questions": 31}',
                    "2026-11-17T00:00:00Z",
                )
            ]
        if "misconception_flagged" in sql:
            return [(47, 7, 2, 9, 3, 1)]
        if "failing FROM assessment_pack" in sql:
            return [("exam", 1)]
        if "unreviewed FROM language_bundle" in sql:
            return [("hi-Latn", 4)]
        if "pages_without_live" in sql:
            return [(1,)]
        if "category COUNT(*) AS n FROM problem_report" in sql:
            return [("wrong_physics", 2)]
        if "role COUNT(*)" in sql:
            return [("staff", 1), ("student", 12)]
        if "email_verified_at IS NOT NULL" in sql:
            return [(9,)]
        if "deleted_at IS NOT NULL" in sql:
            return [(3,)]
        if "request_id scope status counts" in sql:
            return [
                (
                    "req-1",
                    "device",
                    "completed",
                    '{"sessions": 2}',
                    "2026-11-17T00:00:00Z",
                    "2026-11-17T00:01:00Z",
                )
            ]
        if "FROM problem_report WHERE report_id" in sql:
            if self._parent.last_params and self._parent.last_params[0] == (
                UNKNOWN_REPORT_ID
            ):
                return []
            return [("open",)]
        if "report_id course_id class_level" in sql:
            return [
                (
                    SEEDED_REPORT_ID,
                    "motion-c9",
                    9,
                    "b-04",
                    "wrong_physics",
                    "open",
                    "2026-11-17T00:00:00Z",
                    None,
                )
            ]
        if "status COUNT(*) AS n FROM problem_report" in sql:
            return [("open", 2), ("fixed", 1)]
        if "FROM guard_profile WHERE id" in sql:
            return [
                (
                    "normal",
                    1000,
                    30,
                    1000,
                    100,
                    15,
                    10000,
                    40,
                    "2026-11-17T00:00:00Z",
                    "seed",
                )
            ]
        if "guard_profile.flip" in sql:
            return [
                ("2026-11-17T00:00:00Z", "admin", "guard_profile", "normal", "demo")
            ]
        return []

    def fetchone(self) -> tuple[Any, ...] | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def executemany(self, *args: object) -> None:
        return None


class _FakeConnection:
    def __init__(self, broken: bool = False) -> None:
        self.broken = broken
        self.last_params: tuple[Any, ...] = ()
        self.executed: list[str] = []
        self.params: list[tuple[Any, ...]] = []

    def cursor(self) -> _FakeCursor:
        cursor = _FakeCursor(self)
        original = cursor.execute

        def record(sql: str, params: tuple[Any, ...] = ()) -> None:
            self.executed.append(_norm(sql))
            self.params.append(params)
            self.last_params = params
            original(sql, params)

        cursor.execute = record  # type: ignore[method-assign]  # test stub records SQL
        return cursor

    def close(self) -> None:
        return None


def _seeded_product(broken: bool = False) -> ProductStore:
    return ProductStore(connection=_FakeConnection(broken=broken))


@contextmanager
def _seeded_app(*, product: ProductStore | None = None) -> Any:
    """create_app with both store seams pointing at ONE shared seeded stub —
    the client exposes it as `client.product_store` for write-side asserts."""
    os.environ["ZIVON_ADMIN_TOKEN"] = TOKEN
    os.environ.pop("ZIVON_LOG_DSN", None)
    os.environ.pop("ZIVON_PRODUCT_DSN", None)
    shared = product if product is not None else _seeded_product()
    original_log = LogStore.from_env
    original_product = ProductStore.from_env
    LogStore.from_env = classmethod(lambda cls: LogStore(connection=_FakeConnection()))  # type: ignore[assignment]
    ProductStore.from_env = classmethod(lambda cls: shared)  # type: ignore[assignment]
    try:
        client = TestClient(create_app())
        client.product_store = shared  # type: ignore[attr-defined]
        yield client
    finally:
        LogStore.from_env = original_log  # type: ignore[assignment]
        ProductStore.from_env = original_product  # type: ignore[assignment]
        os.environ.pop("ZIVON_ADMIN_TOKEN")


def _csrf_of(html: str) -> str:
    match = re.search(r'name="csrf" value="([^"]+)"', html)
    assert match, "no CSRF token rendered"
    return match.group(1)


def _login(client: TestClient) -> None:
    page = client.get("/admin/login")
    csrf = _csrf_of(page.text)
    response = client.post(
        "/admin/login", data={"token": TOKEN, "csrf": csrf}, follow_redirects=False
    )
    assert response.status_code == 303, response.status_code


def _product_sql(client: TestClient) -> list[str]:
    return client.product_store.connection.executed  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------


class AuthAndGuardTests(unittest.TestCase):
    """Every F10 panel sits behind the same ADR-0026 guard (admin.md §5)."""

    def test_fail_closed_without_token_blocks_every_panel(self) -> None:
        os.environ.pop("ZIVON_ADMIN_TOKEN", None)
        try:
            client = TestClient(create_app())
            for path in F10_PANELS:
                with self.subTest(path=path):
                    self.assertEqual(client.get(path).status_code, 503)
        finally:
            os.environ.pop("ZIVON_ADMIN_TOKEN", None)

    def test_unauthenticated_browser_is_redirected(self) -> None:
        with _seeded_app() as client:
            for path in F10_PANELS:
                response = client.get(
                    path,
                    headers={"accept": "text/html,application/xhtml+xml"},
                    follow_redirects=False,
                )
                with self.subTest(path=path):
                    self.assertEqual(response.status_code, 303)
                    self.assertEqual(response.headers["location"], "/admin/login")

    def test_unauthenticated_api_client_gets_401(self) -> None:
        with _seeded_app() as client:
            response = client.get("/admin/users", follow_redirects=False)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json()["error"], "unauthenticated")

    def test_report_status_change_requires_csrf(self) -> None:
        with _seeded_app() as client:
            _login(client)
            response = client.post(
                "/admin/reports/018f-aaaa-bbbb-cccc-dddd/status",
                data={"status": "fixed", "csrf": "bad"},
            )
            self.assertEqual(response.status_code, 403)


class ContentCoverageTests(unittest.TestCase):
    def test_seeded_counts_render(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/content")
            self.assertEqual(page.status_code, 200)
            self.assertIn("pages registered in the catalogue", page.text)
            self.assertIn(">9<", page.text)
            self.assertIn("published", page.text)
            self.assertIn("en-IN", page.text)
            self.assertIn("hi-IN", page.text)
            self.assertIn("build-time, C-051", page.text)

    def test_empty_store_renders_honest_empty_states(self) -> None:
        with _seeded_app(product=ProductStore(connection=None)) as client:
            _login(client)
            page = client.get("/admin/content")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn("panel error", page.text)
            self.assertIn("no pages registered yet", page.text)
            self.assertIn("nothing live yet", page.text)
            self.assertIn("no bundles yet", page.text)
            self.assertIn("no narration assets yet", page.text)


class QuestionBankHealthTests(unittest.TestCase):
    def test_seeded_axes_render_aggregates_only(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/questions")
            self.assertEqual(page.status_code, 200)
            self.assertIn("published: 40", page.text)
            self.assertIn("draft: 7", page.text)
            self.assertIn("mcq: 30", page.text)
            self.assertIn("hi-Latn: 5", page.text)
            self.assertIn("gate verdict", page.text)
            self.assertIn("concepts without questions", page.text)
            self.assertIn("motion-c9", page.text)

    def test_no_item_text_column_is_ever_selected(self) -> None:
        with _seeded_app() as client:
            _login(client)
            client.get("/admin/questions")
            bank_sql = [sql for sql in _product_sql(client) if "question_bank" in sql]
            self.assertTrue(bank_sql, "the health view queried the bank")
            for sql in bank_sql:
                with self.subTest(sql=sql[:80]):
                    for column in _ITEM_TEXT_COLUMNS:
                        self.assertNotIn(column, sql)


class SeriesBlueprintTests(unittest.TestCase):
    def test_seeded_series_and_packs_render(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/series")
            self.assertEqual(page.status_code, 200)
            self.assertIn("ai-lesson-c9", page.text)
            self.assertIn("ai_lesson", page.text)
            self.assertIn("en, hi", page.text)
            self.assertIn("exam-pack-1", page.text)
            self.assertIn("questions: 31", page.text)

    def test_empty_series_renders_honest_copy(self) -> None:
        with _seeded_app(product=ProductStore(connection=None)) as client:
            _login(client)
            page = client.get("/admin/series")
            self.assertIn("no series yet", page.text)
            self.assertIn("no exam/series packs imported yet", page.text)


class QualityDebtTests(unittest.TestCase):
    def test_debt_tiles_and_tables_render(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/quality")
            self.assertEqual(page.status_code, 200)
            self.assertIn("draft items", page.text)
            self.assertIn("misconception-flagged", page.text)
            self.assertIn("hi-Latn", page.text)
            self.assertIn("wrong_physics", page.text)

    def test_no_item_text_column_is_ever_selected(self) -> None:
        with _seeded_app() as client:
            _login(client)
            client.get("/admin/quality")
            for sql in _product_sql(client):
                with self.subTest(sql=sql[:80]):
                    for column in _ITEM_TEXT_COLUMNS:
                        self.assertNotIn(column, sql)


class UsersSupportTests(unittest.TestCase):
    def test_aggregates_and_deletion_queue_render(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/users")
            self.assertEqual(page.status_code, 200)
            self.assertIn("active student accounts: 12", page.text)
            self.assertIn("active staff accounts: 1", page.text)
            self.assertIn("deletion-request queue", page.text)
            self.assertIn("completed", page.text)
            self.assertIn("sessions: 2", page.text)

    def test_no_pii_on_the_users_panel(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/users")
            self.assertNotIn(REPORT_EMAIL, page.text)
            self.assertNotIn("user_id", page.text)
            self.assertNotIn("device_pseudo", page.text)
            # the executed SQL never selects the identifying columns either
            for sql in _product_sql(client):
                with self.subTest(sql=sql[:80]):
                    self.assertNotIn("email,", sql)
                    self.assertNotIn("user_id", sql)
                    self.assertNotIn("device_pseudo_id", sql)

    def test_no_performance_data_anywhere(self) -> None:
        with _seeded_app() as client:
            _login(client)
            for path in ("/admin/users", "/admin/reports"):
                page = client.get(path)
                with self.subTest(path=path):
                    for banned in ("score", "transcript", "accuracy"):
                        self.assertNotIn(banned, page.text.lower())


class ReportsInboxTests(ObservabilityTest):
    def test_inbox_renders_without_free_text(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/reports")
            self.assertEqual(page.status_code, 200)
            self.assertIn("018f-aaaa-bbbb", page.text)
            self.assertIn("wrong_physics", page.text)
            self.assertIn("WITHOUT their free text", page.text)
            self.assertNotIn(REPORT_TEXT, page.text)

    def test_report_text_column_is_never_selected(self) -> None:
        with _seeded_app() as client:
            _login(client)
            client.get("/admin/reports")
            report_sql = [
                sql for sql in _product_sql(client) if "problem_report" in sql
            ]
            self.assertTrue(report_sql, "the inbox queried problem_report")
            for sql in report_sql:
                with self.subTest(sql=sql[:80]):
                    self.assertNotIn("text", sql.replace("context", ""))

    def test_status_filter_narrows_rows(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/reports", params={"status": "open"})
            self.assertEqual(page.status_code, 200)
            self.assertIn("filtered: open", page.text)

    def test_invalid_status_filter_falls_back_to_all(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/reports", params={"status": "DROP"})
            self.assertEqual(page.status_code, 200)
            self.assertIn("reports (latest 100)", page.text)

    def test_status_change_is_csrf_checked_validated_audited(self) -> None:
        with _seeded_app() as client:
            _login(client)
            csrf = _csrf_of(client.get("/admin/reports").text)
            response = client.post(
                f"/admin/reports/{SEEDED_REPORT_ID}/status",
                data={"status": "fixed", "csrf": csrf},
                headers={"accept": "text/html"},
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)
            self.assertEqual(response.headers["location"], "/admin/reports?saved=1")
            event = self.last_event("dashboard.report_status_changed")
            # the correlation key matches the map row exactly (report_id, not
            # a renamed field — the map is the per-event source of truth)
            self.assertEqual(event["fields"]["report_id"], SEEDED_REPORT_ID)
            self.assertNotIn("report_ref", event["fields"])
            self.assertEqual(event["fields"]["from_status"], "open")
            self.assertEqual(event["fields"]["to_status"], "fixed")
            self.assertNotIn(REPORT_TEXT, json.dumps(event["fields"]))
            writes = _product_sql(client)
            self.assertTrue(any("UPDATE problem_report" in sql for sql in writes))
            self.assertTrue(any("INSERT INTO audit_log" in sql for sql in writes))

    def test_status_change_rejects_bad_enum_and_unknown_report(self) -> None:
        with _seeded_app() as client:
            _login(client)
            csrf = _csrf_of(client.get("/admin").text)
            bad_enum = client.post(
                f"/admin/reports/{SEEDED_REPORT_ID}/status",
                data={"status": "closed", "csrf": csrf},
            )
            self.assertEqual(bad_enum.status_code, 422)
            unknown = client.post(
                f"/admin/reports/{UNKNOWN_REPORT_ID}/status",
                data={"status": "fixed", "csrf": csrf},
            )
            self.assertEqual(unknown.status_code, 404)
            malformed = client.post(
                "/admin/reports/..%2Fescape/status",
                data={"status": "fixed", "csrf": csrf},
            )
            self.assertIn(malformed.status_code, (404, 422))

    def test_reopening_a_report_clears_resolved_at(self) -> None:
        """admin.md §4: resolved_at is set for the two terminal statuses and
        cleared back to NULL when a report reopens."""
        store = _seeded_product()
        self.assertEqual(
            store.set_report_status(SEEDED_REPORT_ID, "fixed"),
            {"before": "open", "after": "fixed"},
        )
        self.assertEqual(
            store.set_report_status(SEEDED_REPORT_ID, "open"),
            {"before": "open", "after": "open"},
        )
        updates = [
            params
            for sql, params in zip(
                store.connection.executed,
                store.connection.params,  # type: ignore[attr-defined]
            )
            if "UPDATE problem_report" in sql
        ]
        self.assertEqual(len(updates), 2, "two status writes, one per change")
        # terminal status stamps the retention clock; reopen clears it again
        self.assertIsNotNone(updates[0][1])
        self.assertIsNone(updates[1][1])

    def test_status_change_on_broken_store_answers_503(self) -> None:
        with _seeded_app(product=_seeded_product(broken=True)) as client:
            _login(client)
            csrf = _csrf_of(client.get("/admin").text)
            response = client.post(
                f"/admin/reports/{SEEDED_REPORT_ID}/status",
                data={"status": "fixed", "csrf": csrf},
            )
            self.assertEqual(response.status_code, 503)


class FlagsTests(unittest.TestCase):
    def test_live_profile_and_flip_history_render(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/flags")
            self.assertEqual(page.status_code, 200)
            self.assertIn("normal", page.text)
            self.assertIn(">1000<", page.text)
            self.assertIn("guard profile flip history", page.text)
            self.assertIn("admin", page.text)

    def test_documented_flags_name_their_source_doc(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/flags")
            self.assertIn("EXAM_CONTENT_MODE", page.text)
            self.assertIn("blueprint_only", page.text)
            for source in (
                "docs/content-factory/exam.md",
                "docs/compliance/",
                "AGENTS.md",
            ):
                with self.subTest(source=source):
                    self.assertIn(source, page.text)


class EvalPanelTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.eval_dir = Path(self._tmp.name)
        os.environ["ZIVON_EVAL_RUNS_DIR"] = str(self.eval_dir)

    def tearDown(self) -> None:
        os.environ.pop("ZIVON_EVAL_RUNS_DIR", None)
        self._tmp.cleanup()

    def _seed_run(self, run_id: str, overall_pass: bool, cards: list[dict]) -> None:
        run_dir = self.eval_dir / run_id
        run_dir.mkdir(parents=True)
        report = {
            "eval_run_id": run_id,
            "suite": "smoke",
            "pipeline_version": 1,
            "factory_image_tag": "0.1.0",
            "git_sha": "57147bb",
            "prompt_bundle_sha256": "x",
            "generator_model": "g",
            "judge_model": "j",
            "started_at": "2026-11-17T00:00:00Z",
            "completed_at": "2026-11-17T00:01:00Z",
            "duration_s": 12.0,
            "overall_pass": overall_pass,
            "regression_detected": False,
            "baseline_eval_run_id": None,
            "summary": {
                "cards_total": len(cards),
                "cards_passed": len(cards),
                "cards_failed": 0,
                "cards_skipped": 0,
            },
            "cards": cards,
        }
        (run_dir / "eval_report.json").write_text(json.dumps(report), encoding="utf-8")
        ledger_row = {
            k: report[k]
            for k in (
                "eval_run_id",
                "suite",
                "overall_pass",
                "regression_detected",
                "started_at",
                "duration_s",
                "generator_model",
                "judge_model",
                "git_sha",
            )
        }
        with (self.eval_dir / "eval_runs_ledger.jsonl").open(
            "a", encoding="utf-8"
        ) as fh:
            fh.write(json.dumps(ledger_row) + "\n")

    def test_missing_evidence_dir_is_honest(self) -> None:
        os.environ["ZIVON_EVAL_RUNS_DIR"] = str(self.eval_dir / "absent")
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/evals")
            self.assertEqual(page.status_code, 200)
            self.assertIn("not mounted", page.text)

    def test_seeded_ledger_and_detail_render(self) -> None:
        run_id = "eval-smoke-20261117T000000Z-57147bb-f35e0c"
        self._seed_run(
            run_id,
            True,
            [
                {
                    "card_id": "EV-VIS-001",
                    "stage": "VIS",
                    "topic_slug": None,
                    "verdict": "pass",
                    "deterministic_score": 1.0,
                    "judge_score": None,
                    "fatal_count": 0,
                    "major_count": 0,
                    "minor_count": 0,
                    "unverified_count": 0,
                    "model_calls": 0,
                }
            ],
        )
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/evals")
            self.assertIn(run_id, page.text)
            detail = client.get(f"/admin/evals/{run_id}")
            self.assertEqual(detail.status_code, 200)
            self.assertIn("EV-VIS-001", detail.text)
            self.assertIn("deterministic-first funnel", detail.text)

    def test_unknown_and_traversal_ids_404(self) -> None:
        with _seeded_app() as client:
            _login(client)
            self.assertEqual(client.get("/admin/evals/nope").status_code, 404)
            self.assertEqual(
                client.get("/admin/evals/..%2F..%2Fsecrets").status_code, 404
            )

    def test_torn_ledger_line_does_not_break_the_view(self) -> None:
        run_id = "eval-smoke-20261117T000001Z-57147bb-f35e0c"
        (self.eval_dir / "eval_runs_ledger.jsonl").write_text(
            '{"eval_run_id": "torn"\n', encoding="utf-8"
        )
        self._seed_run(run_id, True, [])
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/evals")
            self.assertEqual(page.status_code, 200)
            self.assertIn(run_id, page.text)


class PartialStateTests(unittest.TestCase):
    def test_broken_product_store_is_a_panel_error_not_a_crash(self) -> None:
        with _seeded_app(product=_seeded_product(broken=True)) as client:
            _login(client)
            for path in F10_PANELS[:-1]:  # /admin/evals is the file seam
                page = client.get(path)
                with self.subTest(path=path):
                    self.assertEqual(page.status_code, 200)
                    self.assertIn("panel error", page.text)
                    self.assertIn("product store offline", page.text)
            # the log-store views are a different source and stay fine
            runs_page = client.get("/admin/runs")
            self.assertEqual(runs_page.status_code, 200)
            self.assertIn("manual-only", runs_page.text)

    def test_dsn_unset_renders_empty_states_not_errors(self) -> None:
        with _seeded_app(product=ProductStore(connection=None)) as client:
            _login(client)
            page = client.get("/admin/quality")
            self.assertEqual(page.status_code, 200)
            self.assertNotIn("panel error", page.text)
            self.assertIn("question-bank size", page.text)


class A11yAndStatesTests(unittest.TestCase):
    def test_every_panel_is_annotated_english_html(self) -> None:
        with _seeded_app() as client:
            _login(client)
            for path in F10_PANELS:
                page = client.get(path)
                with self.subTest(path=path):
                    self.assertEqual(page.status_code, 200)
                    self.assertIn('<html lang="en">', page.text)
                    self.assertIn("viewport", page.text)

    def test_tables_carry_captions_and_scoped_headers(self) -> None:
        with _seeded_app() as client:
            _login(client)
            for path in F10_PANELS:
                page = client.get(path)
                with self.subTest(path=path):
                    if "<table" not in page.text:
                        continue
                    self.assertIn("<caption>", page.text)
                    self.assertIn('scope="col"', page.text)

    def test_report_form_selects_are_labelled(self) -> None:
        with _seeded_app() as client:
            _login(client)
            page = client.get("/admin/reports")
            self.assertIn("visually-hidden", page.text)
            self.assertIn("filter by status", page.text.lower())

    def test_narrow_viewport_rules_exist(self) -> None:
        css = Path("dashboard/static/dashboard.css").read_text(encoding="utf-8")
        self.assertIn(".table-scroll", css)
        self.assertIn("overflow-x: auto", css)
        # a containing block for the visually-hidden labels inside table
        # cells: without it they escape the wrapper clip and widen the
        # document scroll area at 360 px (regression: reports panned 200 px)
        self.assertIn(
            "position: relative", css.split(".table-scroll {")[1].split("}")[0]
        )
        self.assertIn("@media (max-width: 640px)", css)
        self.assertIn(".visually-hidden", css)
