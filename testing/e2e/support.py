"""Shared hermetic setup for the F11 acceptance-flow E2E suite.

One SQLite in-memory database per test class, seeded through the REAL
assessment-pack importer (the production seed path); one FastAPI app per test
over that store; the dev email sink; no network, no keys, no vendor. The
optional series-pack fixtures are imported through the real series importer
(the same one `scripts/import_series_packs.py` runs in the runbook).
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import tempfile
import unittest
import uuid
import wave
from io import BytesIO
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any, Self

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.assessment import fetch_question, select_question_ids
from backend.speaking import (
    SpeakingEvaluationError,
    Transcript,
    key_ideas,
    parse_evaluation,
)
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
PROMPT_ID = "spk-c9-motion-001"
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

    def signup_via_web(self, email: str, client: TestClient | None = None) -> None:
        """Sign up through the real `/signup` form (no API shortcut)."""
        target = client or self.client
        token = self.guest_form_token("/signup", client=target)
        response = target.post(
            "/signup",
            data={
                "csrf_token": token,
                "email": email,
                "password": PASSWORD,
                "confirm_password": PASSWORD,
                "agree": "yes",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        self.assertEqual(response.headers["location"], "/onboarding")

    def grant_consent(
        self,
        device: str | None = None,
        *,
        client: TestClient | None = None,
        notice_version: str | None = None,
        action: str = "granted",
    ) -> dict[str, Any]:
        """Open (or close) the device-scoped voice consent gate.

        The route defaults the notice version to the config's current one, so
        an omitted `notice_version` grants consent against the live notice.
        """
        payload: dict[str, Any] = {
            "device_pseudo_id": device or self.device_id,
            "consent_version": "v1",
            "guardian_flag": True,
            "action": action,
            "source": "overlay",
        }
        if notice_version is not None:
            payload["notice_version"] = notice_version
        response = (client or self.client).put("/v1/consent", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

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

    def attach_speaking_double(self, **overrides: Any) -> SpeakingPipelineDouble:
        """Mount a pipeline double at the `app.state.speaking` vendor seam.

        The route resolves the pipeline through `pipeline_for(app)`, which
        returns whatever is mounted on the state, so the STT/brain vendors
        never load and no credential is read.
        """
        double = SpeakingPipelineDouble(**overrides)
        self.app.state.speaking = double
        return double

    def post_speaking_attempt(
        self,
        *,
        prompt_id: str = PROMPT_ID,
        language: str = "en",
        audio: bytes | None = None,
        device: str | None = None,
        csrf: str | None = None,
        content_type: str = "audio/wav",
        client: TestClient | None = None,
    ) -> Any:
        """One explain-back upload through the real route contract."""
        target = client or self.client
        headers = {
            "Content-Type": content_type,
            "X-CSRF-Token": csrf or self.csrf,
            "X-Device-Id": device or self.device_id,
        }
        return target.post(
            "/v1/speaking/attempts",
            params={"prompt_id": prompt_id, "language": language},
            content=wav_bytes() if audio is None else audio,
            headers=headers,
        )

    wav_bytes = staticmethod(lambda seconds=2.0: wav_bytes(seconds))


class SpeakingPipelineDouble:
    """Stands in for Prisma STT + the tutor model at the `app.state.speaking`
    seam.

    Same shape as the real `SpeakingPipeline` (`available`, `mock_mode`,
    `settings`, async `transcribe`/`evaluate`), records every call so the
    consent gate can be proven to run BEFORE any audio moves, and grades
    through the real rubric parser so the route's band/feedback mapping is
    the production code path.
    """

    def __init__(
        self,
        *,
        transcript: str = (
            "Distance is the whole path and displacement is the net change."
        ),
        present: int = 3,
        available: bool = True,
        mock: bool = False,
        fail_evaluation: bool = False,
    ) -> None:
        self.settings = SimpleNamespace(
            credit_stt_seconds_per_point=30, brain_model="test-model"
        )
        self.available = available
        self.mock_mode = mock
        self.transcript_text = transcript
        self.present = present
        self.fail_evaluation = fail_evaluation
        self.calls: list[tuple[str, Any]] = []

    async def transcribe(self, pcm: bytes, *, language: str) -> Transcript:
        self.calls.append(("transcribe", len(pcm)))
        return Transcript(
            text=self.transcript_text,
            language=language,
            duration_ms=round(len(pcm) / 2 / 16000 * 1000),
            stt_ms=12,
            mock=self.mock_mode,
        )

    async def evaluate(self, prompt: dict[str, Any], transcript: str) -> Any:
        self.calls.append(("evaluate", transcript))
        if self.fail_evaluation:
            raise SpeakingEvaluationError("test model down")
        payload = {
            "ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "present": index < self.present,
                    "evidence": (
                        "distance is the whole path" if index < self.present else ""
                    ),
                }
                for index, idea in enumerate(key_ideas(prompt))
            ],
            "feedback": {
                "what_went_well": "You named distance clearly.",
                "next_step": "Add why a round trip has zero displacement.",
            },
        }
        return parse_evaluation(
            json.dumps(payload),
            prompt=prompt,
            model=str(self.settings.brain_model),
            mock=self.mock_mode,
        )


class _DescriptionColumn:
    """One `cursor.description` column: psycopg-shaped (`.name`) and indexable."""

    def __init__(self, raw: Any) -> None:
        self._raw = tuple(raw)
        self.name = str(self._raw[0])

    def __getitem__(self, index: int) -> Any:
        return self._raw[index]

    def __len__(self) -> int:
        return len(self._raw)


class _SqliteCursor:
    """A psycopg-shaped cursor over the seeded SQLite database's read paths.

    `description` carries `.name` (plus index access) and the rows are plain
    value tuples, so `ProductStore` reads the REAL seeded aggregates through
    its production SQL — no fake numbers anywhere. The F10 panels are plain
    aggregate SELECTs; a `%s` placeholder is translated to SQLite's `?` when
    parameters are passed.
    """

    def __init__(self, db: DatabaseEngine) -> None:
        self._db = db
        self._description: tuple[_DescriptionColumn, ...] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        self._description = None
        self._rows = []

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> _SqliteCursor:
        adapted = sql
        bound = tuple(params)
        if bound and "%s" in adapted:
            adapted = adapted.replace("%s", "?")
        with self._db.transaction() as tx:
            cursor = tx.execute(adapted, bound)
            self._description = tuple(
                _DescriptionColumn(column) for column in (cursor.description or ())
            )
            self._rows = [tuple(row) for row in cursor.fetchall()]
        return self

    @property
    def description(self) -> tuple[_DescriptionColumn, ...] | None:
        return self._description

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._rows)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._rows[0] if self._rows else None

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
    product_module.ProductStore.from_env = classmethod(lambda cls: store)  # type: ignore[assignment]
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
    "PROMPT_ID",
    "SERIES_FIXTURE_DIR",
    "E2EFlow",
    "SpeakingPipelineDouble",
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
