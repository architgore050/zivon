"""Assessment pack import (`scripts/import_assessment_packs.py`, W4 foundation).

Hermetic SQLite in memory; the tracked P2 packs under
`sources/assessment/packs/` are the fixture. Covers the integrity gate (a
tampered pack is refused whole), the gate verdict, chapter identity, the row
counts the practice/speaking features expect, idempotent re-import, and the
documented content-hash formula agreeing with the pipeline that wrote the pack.
"""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

from db import DatabaseEngine

REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "sources" / "assessment" / "packs"
MOTION = "class-9-describing-motion-around-us"
LIGHT = "class-10-light-reflection-and-refraction"
HUMAN_EYE = "class-10-the-human-eye-and-the-colourful-world"
ELECTRICITY = "class-10-electricity"
# The tracked packs directory holds every mirrored, gate-passed bank.
TRACKED_CHAPTERS = (MOTION, LIGHT, HUMAN_EYE, ELECTRICITY)


def _load_importer() -> ModuleType:
    """Import `scripts/import_assessment_packs.py` the way an operator runs it."""
    path = REPO_ROOT / "scripts" / "import_assessment_packs.py"
    spec = importlib.util.spec_from_file_location("import_assessment_packs", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module at exec time
    spec.loader.exec_module(module)
    return module


importer = _load_importer()


def _copy_packs(target: Path, chapters: tuple[str, ...] = (MOTION, LIGHT)) -> Path:
    for chapter in chapters:
        shutil.copytree(PACKS_DIR / chapter, target / chapter)
    return target


def _rewrite_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


class ImportTrackedPacksTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)

    def count(self, table: str) -> int:
        row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
        assert row is not None
        return int(row["c"])

    def test_tracked_packs_import_the_expected_rows(self) -> None:
        results = importer.import_packs(self.db, PACKS_DIR)
        self.assertEqual(len(results), len(TRACKED_CHAPTERS))
        self.assertEqual({result.chapter_id for result in results}, set(TRACKED_CHAPTERS))
        # 15 base items x 3 languages (motion) + 2 x 18 items x 3 languages
        # (the two C10 banks); 3 base prompts + 2 x 3 prompts x 3 languages.
        self.assertEqual(self.count("question_bank"), 198)
        self.assertEqual(self.count("speaking_prompt"), 36)
        self.assertEqual(self.count("topic_time_prior"), 28)
        self.assertEqual(self.count("assessment_pack"), len(TRACKED_CHAPTERS))

        motion = self.db.fetchone(
            "SELECT class_level, language, type, status, marks, expected_time_ms, "
            "pack_id FROM question_bank WHERE question_id = 'q-c9-motion-001-en'"
        )
        assert motion is not None
        self.assertEqual(motion["class_level"], 9)
        self.assertEqual(motion["language"], "en")
        self.assertEqual(motion["type"], "mcq")
        self.assertEqual(motion["status"], "reviewed")
        self.assertEqual(float(motion["marks"]), 1.0)
        self.assertEqual(int(motion["expected_time_ms"]), 47000)
        self.assertTrue(str(motion["pack_id"]).startswith("assessment-class-9-"))

        light = self.db.fetchone(
            "SELECT class_level FROM question_bank WHERE chapter_id = ? LIMIT 1",
            (LIGHT,),
        )
        assert light is not None
        self.assertEqual(light["class_level"], 10)

        chapter_prior = self.db.fetchone(
            "SELECT expected_time_ms, question_count, formula_version "
            "FROM topic_time_prior WHERE chapter_id = ? AND scope = 'chapter'",
            (MOTION,),
        )
        assert chapter_prior is not None
        self.assertEqual(int(chapter_prior["expected_time_ms"]), 94000)
        self.assertEqual(int(chapter_prior["question_count"]), 15)
        self.assertEqual(chapter_prior["formula_version"], "tp-v1")

        speaking = self.db.fetchone(
            "SELECT prompt, model_answer, status, length(key_ideas) AS ideas "
            "FROM speaking_prompt WHERE prompt_id = 'spk-c9-motion-001' AND language = 'hi'"
        )
        assert speaking is not None
        self.assertTrue(str(speaking["prompt"]).strip())
        self.assertTrue(str(speaking["model_answer"]).strip())
        self.assertEqual(speaking["status"], "reviewed")

    def test_reimport_is_idempotent(self) -> None:
        importer.import_packs(self.db, PACKS_DIR)
        before = {
            table: self.count(table)
            for table in (
                "question_bank",
                "speaking_prompt",
                "topic_time_prior",
                "assessment_pack",
            )
        }
        importer.import_packs(self.db, PACKS_DIR)
        after = {table: self.count(table) for table in before}
        self.assertEqual(before, after)
        # One provenance row per (chapter, content hash), not one per run.
        packs = self.db.fetchall(
            "SELECT chapter_id, content_hash FROM assessment_pack ORDER BY chapter_id"
        )
        self.assertEqual(len({row["chapter_id"] for row in packs}), len(TRACKED_CHAPTERS))
        self.assertEqual(len({row["content_hash"] for row in packs}), len(TRACKED_CHAPTERS))

    def test_question_time_prior_matches_the_question_row(self) -> None:
        importer.import_packs(self.db, PACKS_DIR)
        priors = json.loads(
            (PACKS_DIR / MOTION / "time-priors.json").read_text(encoding="utf-8")
        )["questions"]
        by_id = {
            str(row["question_id"]): int(row["expected_time_ms"]) for row in priors
        }
        for question_id in (
            "q-c9-motion-001-en",
            "q-c9-motion-003-en",
            "q-c9-motion-005-hi-Latn",
        ):
            stored = self.db.fetchone(
                "SELECT expected_time_ms FROM question_bank WHERE question_id = ?",
                (question_id,),
            )
            assert stored is not None, question_id
            self.assertEqual(int(stored["expected_time_ms"]), by_id[question_id])


class ImportIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        self._tmp = tempfile.TemporaryDirectory()
        self.packs_dir = _copy_packs(Path(self._tmp.name) / "packs", (MOTION,))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_tampered_pack_is_refused_before_any_write(self) -> None:
        questions = self.packs_dir / MOTION / "questions.json"
        original = questions.read_text(encoding="utf-8")
        questions.write_text(
            original.replace('"marks": 1', '"marks": 2', 1), encoding="utf-8"
        )
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn("SHA-256", str(caught.exception))
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM question_bank")
        assert row is not None
        self.assertEqual(int(row["c"]), 0)

    def test_a_failed_gate_verdict_is_refused(self) -> None:
        manifest = self.packs_dir / MOTION / "manifest.json"

        def fail_gate(payload: dict[str, object]) -> None:
            gate = payload["gate"]
            assert isinstance(gate, dict)
            gate["verdict"] = "fail"
            gate["error_count"] = 3

        _rewrite_json(manifest, fail_gate)
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn("gate verdict", str(caught.exception))

    def test_chapter_identity_must_match_the_directory(self) -> None:
        manifest = self.packs_dir / MOTION / "manifest.json"
        _rewrite_json(
            manifest, lambda payload: payload.__setitem__("chapter_id", LIGHT)
        )
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn("directory name", str(caught.exception))

    def test_a_pack_missing_a_data_file_is_refused(self) -> None:
        (self.packs_dir / MOTION / "time-priors.json").unlink()
        with self.assertRaises(importer.PackError):
            importer.import_packs(self.db, self.packs_dir)

    def test_an_unknown_manifest_entry_is_refused_before_reading_it(self) -> None:
        """The manifest cannot point the verifier at a file outside the pack."""
        manifest = self.packs_dir / MOTION / "manifest.json"

        def add_extra(payload: dict[str, object]) -> None:
            files = payload["files"]
            assert isinstance(files, dict)
            files["../outside.json"] = files["questions.json"]

        _rewrite_json(manifest, add_extra)
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn("unknown entries", str(caught.exception))
        row = self.db.fetchone("SELECT COUNT(*) AS c FROM question_bank")
        assert row is not None
        self.assertEqual(int(row["c"]), 0)

    def test_an_empty_directory_is_refused(self) -> None:
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, Path(self._tmp.name) / "nope")
        self.assertIn("no pack directories", str(caught.exception))

    def test_cli_dry_run_writes_nothing(self) -> None:
        db_file = Path(self._tmp.name) / "dry-run.db"
        code = importer.main(
            [
                "--packs-dir",
                str(self.packs_dir),
                "--db-url",
                f"sqlite:///{db_file}",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0)
        self.assertFalse(
            db_file.exists(), "a dry run must not open or create the database"
        )

    def test_content_hash_formula_matches_the_pack_pipeline(self) -> None:
        from factory.assessment.pack import content_hash

        manifest = json.loads(
            (PACKS_DIR / MOTION / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(
            importer._content_hash(manifest["files"]),
            content_hash(manifest["files"]),
        )
        self.assertEqual(
            set(manifest["files"]),
            set(importer.PACK_DATA_FILES),
            "the importer must know every data file the pipeline writes",
        )


if __name__ == "__main__":
    unittest.main()
