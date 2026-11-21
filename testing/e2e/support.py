"""Shared hermetic setup for the F11 acceptance-flow E2E suite.

One SQLite in-memory database per test class, seeded through the REAL
assessment-pack importer (the production seed path); one FastAPI app per test
over that store; the dev email sink; no network, no keys, no vendor. The
optional series-pack fixtures are imported through the real series importer
(the same one `scripts/import_series_packs.py` runs in the runbook).
"""

from __future__ import annotations

import importlib.util
import re
import sys
import tempfile
import unittest
import uuid
import wave
from io import BytesIO
from pathlib import Path
from types import ModuleType
from typing import Any

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.assessment import fetch_question, select_question_ids
from db import DatabaseEngine
from db.uuid7 import uuid7_str

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
SERIES_FIXTURE_DIR = REPO_ROOT / "testing" / "backend" / "fixtures" / "series_packs"
FRONTEND_DIR = REPO_ROOT / "frontend"
MOTION = "class-9-describing-motion-around-us"
LIGHT = "class-10-light-reflection-and-refraction"
FORCES = "class-9-how-forces-affect-motion"
ELECTRICITY = "class-10-electricity"
PASSWORD = "correct-horse-battery-staple"
DEV_DEVICE_ID = "0f0e0d0c-0b0a-4009-8007-000605040302"


def load_script(name: str, filename: str) -> ModuleType:
    """Import a `scripts/` entry point the way an operator runs it."""
    path = REPO_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


assessment_importer = load_script(
    "import_assessment_packs_e2e", "import_assessment_packs.py"
)


def make_config(root: Path, **overrides: Any) -> BackendConfig:
    """The hermetic app posture: memory DB, dev email sink, generous limits.

    Individual flow tests tighten one limit family through `overrides` when
    the rate-limit behaviour itself is under test.
    """
    defaults: dict[str, Any] = {
        "db_url": "sqlite:///:memory:",
        "env": "test",
        "runs_dir": str(root / "runs"),
        "cold_staging_dir": str(root / "cold"),
        "dev_email_dir": str(root / "dev-email"),
        "auth_cookie_secure": True,
        "app_base_url": "https://app.test",
        "auth_login_per_min": 100,
        "auth_register_per_min": 100,
        "auth_reset_per_min": 100,
        "auth_verify_per_min": 100,
        "auth_google_per_min": 100,
        "rate_limit_api_per_min": 10_000,
        "rate_limit_events_per_min": 10_000,
        "rate_limit_reports_per_min": 10_000,
        "rate_limit_delete_per_min": 10_000,
    }
    defaults.update(overrides)
    return BackendConfig(**defaults)


class E2EFlow(unittest.TestCase):
    """Base class: seeded store per class, one app + client per test."""

    db: DatabaseEngine

    @classmethod
    def setUpClass(cls) -> None:
        cls.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        assessment_importer.import_packs(cls.db, PACKS_DIR)

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.app = create_app(self._config(), db_engine=self.db)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.email = f"e2e-{uuid7_str()}@example.com"
        self.device_id = f"{uuid.uuid4()}"
        self.session = self.register_api(self.email)
        self.csrf = str(self.session["csrf_token"])

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- app posture ---------------------------------------------------------

    def _config(self) -> BackendConfig:
        return make_config(self.root)

    def guest_client(self) -> TestClient:
        """A second browser on the same app: no cookies, never signed in."""
        return TestClient(self.app, base_url="https://testserver")

    # -- account helpers -----------------------------------------------------

    def register_api(
        self,
        email: str | None = None,
        *,
        class_level: int | None = 9,
        language: str = "en-IN",
        client: TestClient | None = None,
    ) -> dict[str, Any]:
        target = client or self.client
        response = target.post(
            "/v1/auth/register",
            json={
                "email": email or f"e2e-{uuid7_str()}@example.com",
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": class_level,
                "language": language,
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return target.get("/v1/auth/session").json()

    def headers(self, csrf: str | None = None) -> dict[str, str]:
        return {"X-CSRF-Token": csrf or self.csrf}

    def page(self, path: str, *, status: int = 200) -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, status, f"{path}: {response.text[:400]}")
        return response.text

    def csrf_from_page(self, path: str, client: TestClient | None = None) -> str:
        target = client or self.client
        match = re.search(
            r'name="csrf_token"\s+value="([^"]+)"'
            r'|value="([^"]+)"\s+name="csrf_token"',
            target.get(path).text,
        )
        if match and match.group(1):
            return match.group(1)
        if match:
            return match.group(2)
        self.assertIsNotNone(match, f"no form CSRF token on {path}")
        assert match is not None
        return match.group(1)

    def guest_form_token(self, path: str, client: TestClient | None = None) -> str:
        """GET a guest page (issuing the nonce cookie) and return its token."""
        target = client or self.client
        response = target.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        match = re.search(
            r'<input type="hidden" name="csrf_token" value="([^"]+)"'
            r'|<input type="hidden" value="([^"]+)" name="csrf_token"',
            response.text,
        )
        self.assertIsNotNone(match, f"no guest CSRF token on {path}")
        assert match is not None
        return match.group(1) or match.group(2)

    # -- question helpers (the real bank, graded server-side) ----------------

    def bank_questions(self, chapter_id: str, count: int = 5) -> list[Any]:
        ids = select_question_ids(self.db, chapter_id, language="en")[:count]
        self.assertTrue(ids, f"no bank questions for {chapter_id}")
        return list(ids)

    def correct_answer(self, question_id: Any) -> dict[str, Any]:
        question = fetch_question(self.db, str(question_id))
        assert question is not None
        if question.type == "numeric":
            return {"value": float(question.answer["value"])}
        return {"index": int(question.answer["index"])}

    def wrong_answer(self, question_id: Any) -> dict[str, Any]:
        question = fetch_question(self.db, str(question_id))
        assert question is not None
        if question.type == "numeric":
            return {"value": float(question.answer["value"]) + 1000}
        index = int(question.answer["index"])
        return {"index": (index + 1) % max(1, len(question.options))}

    # -- progress merge helpers (the device-merge island contract) -----------

    def merge_events(
        self,
        events: list[dict[str, Any]],
        *,
        csrf: str | None = None,
        client: TestClient | None = None,
        expect: int = 200,
    ) -> dict[str, Any]:
        target = client or self.client
        response = target.post(
            "/v1/progress/events",
            json={"events": events},
            headers=self.headers(csrf),
        )
        self.assertEqual(response.status_code, expect, response.text)
        return response.json()

    def merge_bookmarks(
        self,
        items: list[dict[str, str]],
        *,
        csrf: str | None = None,
        client: TestClient | None = None,
        expect: int | tuple[int, ...] = (200, 201),
    ) -> dict[str, Any]:
        target = client or self.client
        response = target.post(
            "/v1/bookmarks", json={"items": items}, headers=self.headers(csrf)
        )
        expected = (expect,) if isinstance(expect, int) else expect
        self.assertIn(response.status_code, expected, response.text)
        return response.json()

    # -- speaking helpers ----------------------------------------------------

    wav_bytes = staticmethod(lambda seconds=2.0: wav_bytes(seconds))


class _SqliteCursor:
    """A psycopg-shaped cursor over the seeded SQLite database's read paths.

    The F10 panels are plain aggregate SELECTs with no bind parameters; this
    cursor keeps the real dashboard SQL and the real seeded rows — no fake
    numbers anywhere.
    """

    def __init__(self, db: DatabaseEngine) -> None:
        self._db = db
        self._rows: list[dict[str, Any]] | None = None

    def __enter__(self) -> _SqliteCursor:
        return self

    def __exit__(self, *args: object) -> None:
        self._rows = None

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> None:
        del params
        self._rows = self._db.fetchall(sql)

    def fetchall(self) -> list[dict[str, Any]]:
        assert self._rows is not None, "fetchall() before execute()"
        return self._rows

    def fetchone(self) -> dict[str, Any] | None:
        rows = self.fetchall()
        return rows[0] if rows else None

    def executemany(self, sql: str, seq: Any) -> None:
        del sql, seq


class _SqliteConnectionAdapter:
    """Adapts the seeded `DatabaseEngine` to the `ProductStore` reads."""

    def __init__(self, db: DatabaseEngine) -> None:
        self._db = db

    def cursor(self) -> _SqliteCursor:
        return _SqliteCursor(self._db)

    def close(self) -> None:
        del self


def product_store_over(db: DatabaseEngine) -> Any:
    """A `ProductStore` whose connection is the seeded SQLite database."""
    from dashboard.product import ProductStore

    store = ProductStore.__new__(ProductStore)
    store.connection = _SqliteConnectionAdapter(db)
    store.error = None
    return store


def patch_product_store(db: DatabaseEngine) -> Any:
    """Point `ProductStore.from_env` at the seeded SQLite database.

    Returns the restore callable (try/finally hygiene).
    """
    from dashboard import product as product_module

    store = product_store_over(db)
    original = product_module.ProductStore.from_env
    product_module.ProductStore.from_env = classmethod(lambda cls: store)  # type: ignore[method-assign]
    return original


__all__ = [
    "DEV_DEVICE_ID",
    "ELECTRICITY",
    "FORCES",
    "FRONTEND_DIR",
    "LIGHT",
    "MOTION",
    "PACKS_DIR",
    "PASSWORD",
    "SERIES_FIXTURE_DIR",
    "E2EFlow",
    "assessment_importer",
    "load_script",
    "make_config",
    "patch_product_store",
    "product_store_over",
]


def wav_bytes(seconds: float = 2.0) -> bytes:
    """A minimal 16 kHz mono PCM16 WAV — enough for the parser and the
    duration check; the mock pipeline never calls a vendor with it."""
    rate = 16_000
    frames = int(rate * seconds)
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * frames)
    return buffer.getvalue()
