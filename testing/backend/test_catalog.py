"""`/v1/catalog` stub contract tests (REQUIREMENTS §9.3; F0 fixture fallback)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app


class TestCatalogStub(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
        )
        self.app = create_app(cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.db = self.app.state.db

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_fixture_serves_release_classes_and_live_chapters(self) -> None:
        response = self.client.get("/v1/catalog")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "public, max-age=300")
        body = response.json()
        self.assertEqual(body["schema_version"], 1)
        self.assertEqual(body["subject"], "physics")
        self.assertEqual(
            [entry["class_level"] for entry in body["classes"]], [9, 10, 11, 12]
        )
        class_nine = body["classes"][0]["chapters"]
        motion = next(chapter for chapter in class_nine if chapter["slug"] == "motion")
        self.assertEqual(motion["status"], "live")
        self.assertEqual(motion["languages"], ["en", "hi", "hi-Latn"])
        self.assertEqual(motion["lesson_url"], "/courses/class-9-physics/motion/")
        self.assertEqual(int(motion["chapter_no"]), 8)
        self.assertEqual(body["classes"][1]["chapters"], [])

    def test_chapter_detail_and_unknown_slug(self) -> None:
        detail = self.client.get("/v1/catalog/chapters/motion")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["chapter"]["chapter_id"], "class-9-motion")
        self.assertEqual(detail.json()["concepts"], [])

        missing = self.client.get("/v1/catalog/chapters/does-not-exist")
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(missing.json()["code"], "E-NOT-FOUND")

    def test_database_rows_take_precedence_over_the_fixture(self) -> None:
        self.db.execute(
            """
            INSERT INTO syllabus_chapter (
                chapter_id, class_level, subject, chapter_no, slug,
                title_en, title_hi, status, languages, lesson_url
            ) VALUES ('class-10-light', 10, 'physics', 10, 'light',
                      'Light', 'प्रकाश', 'live', ?, '/courses/class-10-physics/light/')
            """,
            (json.dumps(["en", "hi"]),),
        )
        self.db.execute(
            """
            INSERT INTO concept (
                concept_id, chapter_id, slug, title_en, title_hi, order_index
            ) VALUES ('c-light-reflection', 'class-10-light', 'reflection',
                      'Reflection', 'परावर्तन', 1)
            """
        )
        body = self.client.get("/v1/catalog").json()
        class_ten = body["classes"][1]["chapters"]
        self.assertEqual([chapter["slug"] for chapter in class_ten], ["light"])
        self.assertEqual(int(class_ten[0]["concepts_count"]), 1)

        detail = self.client.get("/v1/catalog/chapters/light").json()
        self.assertEqual(detail["concepts"][0]["concept_id"], "c-light-reflection")
        self.assertEqual(
            set(detail["concepts"][0]),
            {
                "concept_id",
                "slug",
                "title_en",
                "title_hi",
                "description",
                "order_index",
            },
        )


if __name__ == "__main__":
    unittest.main()
