"""Series-pack import (`scripts/import_series_packs.py`, the P3 DB importer).

Hermetic SQLite in memory; the fixture is the synthetic minimal E4 pack at
`testing/backend/fixtures/series_packs/class-10/` (clearly marked synthetic),
and `question_bank` is seeded by the REAL assessment importer over the tracked
P2 packs — the production order (bank first, series second). Covers the row
mapping into `test_series`/`test`/`test_question` (per-language papers, slot
marks over bank marks, the dark exact-PYQ row), the integrity gate (a tampered
pack is refused whole), the publish-gate verdict, the DEC-COMP-001 verbatim
refusals, the question_bank prerequisite, idempotent re-import (including a
reordered paper), and the CLI.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
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
PACKS_DIR = REPO_ROOT / "testing" / "backend" / "fixtures" / "series_packs"
CLASS_PACK = "class-10"
BOARD_PAPER_EN = "class-10-board_practice-board-practice-p01-en"


def _load_script(name: str, filename: str) -> ModuleType:
    """Import a `scripts/` entry point the way an operator runs it."""
    path = REPO_ROOT / "scripts" / filename
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclasses resolve their module at exec time
    spec.loader.exec_module(module)
    return module


importer = _load_script("import_series_packs", "import_series_packs.py")
assessment_importer = _load_script(
    "import_assessment_packs_seed", "import_assessment_packs.py"
)


def _seed_bank(db: DatabaseEngine) -> None:
    """Import the tracked P2 packs with the real assessment importer."""
    assessment_importer.import_packs(db, REPO_ROOT / "sources" / "assessment" / "packs")


def _rewrite_json(path: Path, mutate: Callable[[dict[str, Any]], None]) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    mutate(payload)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _rehash(packs_dir: Path) -> None:
    """Recompute manifest.files + content_hash the way E4 wrote them."""

    def rebuild(manifest: dict[str, Any]) -> None:
        import hashlib

        files: dict[str, Any] = {}
        for name in sorted(importer.PACK_DATA_FILES):
            raw = (packs_dir / CLASS_PACK / name).read_bytes()
            files[name] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
        joined = "\n".join(
            f"{name}:{entry['sha256']}" for name, entry in sorted(files.items())
        )
        manifest["files"] = files
        manifest["content_hash"] = (
            "sha256:" + hashlib.sha256(joined.encode("utf-8")).hexdigest()
        )

    _rewrite_json(packs_dir / CLASS_PACK / "manifest.json", rebuild)


def _copy_fixture(target: Path) -> Path:
    packs_dir = target / "packs"
    shutil.copytree(PACKS_DIR, packs_dir)
    return packs_dir


class SeriesImportRowMappingTests(unittest.TestCase):
    """The happy path: the fixture pack lands with the documented mapping."""

    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        _seed_bank(self.db)
        self.results = importer.import_packs(self.db, PACKS_DIR)

    def count(self, table: str) -> int:
        row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
        assert row is not None
        return int(row["c"])

    def exam_pack_rows(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM assessment_pack WHERE kind = 'exam'"
        )
        assert row is not None
        return int(row["c"])

    def test_fixture_pack_imports_the_expected_rows(self) -> None:
        self.assertEqual(len(self.results), 1)
        result = self.results[0]
        self.assertEqual(result.class_num, 10)
        self.assertEqual(result.series_rows, 6)
        self.assertEqual(result.tests, 13)
        self.assertEqual(result.question_rows, 18)
        self.assertTrue(result.pack_id.startswith("exam-class-10-"))
        self.assertEqual(self.count("test_series"), 6)
        self.assertEqual(self.count("test"), 13)
        self.assertEqual(self.count("test_question"), 18)
        # One exam provenance row for this pack (the tracked P2 packs already
        # hold their own 'assessment' rows; the bank keeps growing as content
        # lands, so the assertion is scoped to this importer's rows).
        self.assertEqual(self.exam_pack_rows(), 1)

    def test_series_rows_carry_the_pack_metadata(self) -> None:
        row = self.db.fetchone(
            "SELECT kind, class_level, title, status, language_set, metadata "
            "FROM test_series WHERE series_id = 'class-10-board_practice'"
        )
        assert row is not None
        self.assertEqual(row["kind"], "board_practice")
        self.assertEqual(int(row["class_level"]), 10)
        self.assertEqual(row["title"], "Board practice")
        self.assertEqual(row["status"], "published")
        self.assertEqual(json.loads(row["language_set"]), ["en", "hi"])
        metadata = json.loads(row["metadata"])
        self.assertEqual(metadata["notice_id"], "N-01")
        self.assertIn("exam-class-10-", str(metadata["pack_id"]))

    def test_the_dark_exact_pyq_series_imports_as_draft(self) -> None:
        """DEC-COMP-001: no clearance means catalogue row only, never served."""
        row = self.db.fetchone(
            "SELECT status, metadata FROM test_series WHERE series_id = 'class-10-exact_pyq'"
        )
        assert row is not None
        self.assertEqual(row["status"], "draft")
        metadata = json.loads(row["metadata"])
        self.assertEqual(metadata["disabled_reason"], "no_verbatim_clearance")
        served = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM test WHERE series_id = 'class-10-exact_pyq'"
        )
        assert served is not None
        self.assertEqual(int(served["c"]), 0)

    def test_papers_import_per_language_with_slot_sections_and_marks(self) -> None:
        """One `test` per offered language; `test_question` points at that
        language's bank rows; the sheet's slot marks win over the bank marks
        (db-spec §4.19)."""
        row = self.db.fetchone(
            "SELECT title, language, duration_s, total_marks, status, chapter_ids, "
            "structure FROM test WHERE test_id = ?",
            (BOARD_PAPER_EN,),
        )
        assert row is not None
        self.assertEqual(row["language"], "en")
        self.assertEqual(row["status"], "published")
        # The pack's duration_min (180) for full-paper series.
        self.assertEqual(int(row["duration_s"]), 10800)
        # Earnable marks only: slot 1 + slot 2 (the empty 3-mark slot is not
        # earnable); the design total (6) lives in structure.
        self.assertEqual(float(row["total_marks"]), 3.0)
        self.assertEqual(
            json.loads(row["chapter_ids"]), ["class-10-light-reflection-and-refraction"]
        )
        structure = json.loads(row["structure"])
        self.assertEqual(structure["source"], "series_pack")
        self.assertEqual(structure["filled_slots"], 2)
        self.assertEqual(structure["total_slots"], 3)
        self.assertEqual(structure["design_marks_total"], 6)
        self.assertEqual(len(structure["sections"]), 3)
        questions = self.db.fetchall(
            "SELECT order_index, section, marks, question_id FROM test_question "
            "WHERE test_id = ? ORDER BY order_index",
            (BOARD_PAPER_EN,),
        )
        self.assertEqual(
            [
                (
                    int(q["order_index"]),
                    q["section"],
                    float(q["marks"]),
                    q["question_id"],
                )
                for q in questions
            ],
            [
                (1, "A", 1.0, "q-c10-light-002-en"),
                # The very_short slot awards 2 marks while the bank item is
                # authored for 1 — the paper marks are the ones that count.
                (2, "B", 2.0, "q-c10-light-003-en"),
            ],
        )

    def test_set_based_series_derive_their_duration_from_the_f7_convention(
        self,
    ) -> None:
        """No pack duration on sets: 90 s per question, like the F7 service."""
        row = self.db.fetchone(
            "SELECT language, duration_s, total_marks, structure FROM test "
            "WHERE test_id = 'class-10-challenge-challenge-set-01-hi-Latn'"
        )
        assert row is not None
        self.assertEqual(row["language"], "hi-Latn")
        self.assertEqual(int(row["duration_s"]), 90)
        self.assertEqual(float(row["total_marks"]), 1.0)
        structure = json.loads(row["structure"])
        self.assertEqual(structure["set_kind"], "set")
        self.assertEqual(structure["item_ids"], ["exam-q-c10-light-003"])

    def test_every_test_row_resolves_to_bank_rows_in_its_own_language(self) -> None:
        """The per-language join: no test may mix languages in its questions."""
        rows = self.db.fetchall(
            "SELECT t.test_id, t.language, tq.question_id FROM test t "
            "JOIN test_question tq ON tq.test_id = t.test_id"
        )
        self.assertGreater(len(rows), 0)
        for row in rows:
            suffix = f"-{row['language']}"
            self.assertTrue(
                str(row["question_id"]).endswith(suffix),
                f"{row['test_id']}: {row['question_id']} is not a {row['language']} row",
            )

    def test_the_imported_rows_are_served_by_the_store(self) -> None:
        """The consumer contract (backend/assessment/store.py) reads them."""
        from backend.assessment import list_series, list_test_questions, list_tests

        published = {row["kind"] for row in list_series(self.db, class_level=10)}
        self.assertEqual(
            published,
            {"ai_lesson", "pyq_pattern", "board_practice", "challenge", "loop"},
        )
        tests = list_tests(self.db, "class-10-board_practice")
        self.assertEqual(
            sorted((t["language"], t["total_marks"]) for t in tests),
            [("en", 3.0), ("hi", 3.0)],
        )
        questions = list_test_questions(self.db, BOARD_PAPER_EN)
        self.assertEqual(
            [(q["section"], float(q["marks"])) for q in questions],
            [("A", 1.0), ("B", 2.0)],
        )


class SeriesImportIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        _seed_bank(self.db)
        importer.import_packs(self.db, PACKS_DIR)

    def count(self, table: str) -> int:
        row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
        assert row is not None
        return int(row["c"])

    def test_reimport_is_idempotent(self) -> None:
        before = {
            table: self.count(table)
            for table in ("test_series", "test", "test_question", "assessment_pack")
        }
        importer.import_packs(self.db, PACKS_DIR)
        after = {table: self.count(table) for table in before}
        self.assertEqual(before, after)
        packs = self.db.fetchall(
            "SELECT pack_id, content_hash FROM assessment_pack WHERE kind = 'exam'"
        )
        self.assertEqual(len(packs), 1)
        self.assertEqual(packs[0]["content_hash"].startswith("sha256:"), True)

    def test_a_reordered_paper_replaces_its_rows_without_duplicates(self) -> None:
        """A re-export that reorders a paper must not collide on order_index."""
        with tempfile.TemporaryDirectory() as tmp:
            packs_dir = _copy_fixture(Path(tmp))

            def swap_slots(payload: dict[str, Any]) -> None:
                for entry in payload["series"]:
                    if entry["series_id"] == "board_practice":
                        slots = entry["papers"][0]["sections"]
                        slots[0], slots[1] = slots[1], slots[0]

            _rewrite_json(packs_dir / CLASS_PACK / "series.json", swap_slots)
            _rehash(packs_dir)
            importer.import_packs(self.db, packs_dir)
        questions = self.db.fetchall(
            "SELECT order_index, section, question_id FROM test_question "
            "WHERE test_id = ? ORDER BY order_index",
            (BOARD_PAPER_EN,),
        )
        self.assertEqual(
            [(int(q["order_index"]), q["section"]) for q in questions],
            [(1, "B"), (2, "A")],
        )
        self.assertEqual(self.count("test_question"), 18)
        self.assertEqual(self.count("test"), 13)


class SeriesImportRefusalTests(unittest.TestCase):
    """Every refusal writes nothing: the DB never holds half a pack."""

    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)
        _seed_bank(self.db)
        self._tmp = tempfile.TemporaryDirectory()
        self.packs_dir = _copy_fixture(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)

    def assert_refused(self, context: str) -> None:
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn(context, str(caught.exception))
        for table in ("test_series", "test", "test_question"):
            row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
            assert row is not None
            self.assertEqual(int(row["c"]), 0, f"{table} must stay empty")
        # The P2 seed wrote its own 'assessment' provenance rows; this importer
        # must not have written its 'exam' row.
        self.assertEqual(self.exam_pack_rows(), 0)

    def exam_pack_rows(self) -> int:
        row = self.db.fetchone(
            "SELECT COUNT(*) AS c FROM assessment_pack WHERE kind = 'exam'"
        )
        assert row is not None
        return int(row["c"])

    def test_a_tampered_data_file_is_refused_before_any_write(self) -> None:
        items = self.packs_dir / CLASS_PACK / "items.json"
        original = items.read_text(encoding="utf-8")
        items.write_text(
            original.replace('"marks": 1', '"marks": 2', 1), encoding="utf-8"
        )
        self.assert_refused("SHA-256")

    def test_a_failed_gate_verdict_is_refused(self) -> None:
        manifest = self.packs_dir / CLASS_PACK / "manifest.json"

        def fail_gate(payload: dict[str, Any]) -> None:
            gate = payload["gate"]
            assert isinstance(gate, dict)
            gate["verdict"] = "fail"
            gate["error_count"] = 3

        _rewrite_json(manifest, fail_gate)
        self.assert_refused("gate verdict")

    def test_a_blocked_publish_status_is_refused(self) -> None:
        """A pack that never passed the volume gate never lands."""
        manifest = self.packs_dir / CLASS_PACK / "manifest.json"

        def block(payload: dict[str, Any]) -> None:
            payload["publish"] = {
                "status": "blocked",
                "blockers": [
                    {
                        "rule": "series.minimum.challenge",
                        "severity": "major",
                        "message": "challenge is under its approved minimum",
                    }
                ],
                "reason_codes": ["volume"],
                "volume": {},
            }

        _rewrite_json(manifest, block)
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        message = str(caught.exception)
        self.assertIn("publish status is 'blocked'", message)
        self.assertIn("series.minimum.challenge", message)

    def test_a_missing_manifest_is_refused(self) -> None:
        (self.packs_dir / CLASS_PACK / "manifest.json").unlink()
        with self.assertRaises(importer.PackError):
            importer.import_packs(self.db, self.packs_dir)

    def test_a_missing_data_file_is_refused(self) -> None:
        (self.packs_dir / CLASS_PACK / "series.json").unlink()
        self.assert_refused("missing or empty")

    def test_a_content_hash_mismatch_is_refused(self) -> None:
        """A file whose own entry was re-hashed but not the aggregate."""
        items_path = self.packs_dir / CLASS_PACK / "items.json"
        original = items_path.read_text(encoding="utf-8")
        items_path.write_text(
            original.replace('"marks": 1', '"marks": 2', 1), encoding="utf-8"
        )

        def fix_file_entry(payload: dict[str, Any]) -> None:
            import hashlib

            raw = items_path.read_bytes()
            files = payload["files"]
            assert isinstance(files, dict)
            files["items.json"] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }

        _rewrite_json(self.packs_dir / CLASS_PACK / "manifest.json", fix_file_entry)
        self.assert_refused("content_hash does not match")

    def test_verbatim_rows_without_clearance_are_refused(self) -> None:
        """Exact-PYQ/verbatim content stays dark unless the pack is cleared."""
        items_path = self.packs_dir / CLASS_PACK / "items.json"

        def make_verbatim(payload: dict[str, Any]) -> None:
            items = payload["items"]
            assert isinstance(items, list)
            items[0]["source_type"] = "verbatim_cbse_paper"

        _rewrite_json(items_path, make_verbatim)
        _rehash(self.packs_dir)
        self.assert_refused("DEC-COMP-001")

    def test_exact_pyq_marked_enabled_without_a_clearance_is_refused(self) -> None:
        """The manifest cannot fake clearance by flipping its own flag."""
        manifest = self.packs_dir / CLASS_PACK / "manifest.json"

        def enable(payload: dict[str, Any]) -> None:
            compliance = payload["compliance"]
            assert isinstance(compliance, dict)
            compliance["exact_pyq_status"] = "enabled"

        _rewrite_json(manifest, enable)
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, self.packs_dir)
        self.assertIn("does not back it with a clearance", str(caught.exception))

    def test_a_disabled_series_may_not_carry_items(self) -> None:
        series_path = self.packs_dir / CLASS_PACK / "series.json"

        def smuggle(payload: dict[str, Any]) -> None:
            for entry in payload["series"]:
                if entry["series_id"] == "exact_pyq":
                    entry["item_ids"] = ["exam-q-c10-light-001"]

        _rewrite_json(series_path, smuggle)
        _rehash(self.packs_dir)
        self.assert_refused("disabled series exact_pyq still carries items")

    def test_an_unknown_series_kind_in_a_row_is_refused(self) -> None:
        items_path = self.packs_dir / CLASS_PACK / "items.json"

        def rename(payload: dict[str, Any]) -> None:
            items = payload["items"]
            assert isinstance(items, list)
            items[0]["series_ids"] = ["bogus_series"]

        _rewrite_json(items_path, rename)
        _rehash(self.packs_dir)
        self.assert_refused("names unknown series")

    def test_an_empty_packs_dir_is_refused(self) -> None:
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, Path(self._tmp.name) / "nope")
        self.assertIn("no pack directories", str(caught.exception))


class SeriesImportPrerequisiteTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseEngine.from_url("sqlite:///:memory:", auto_migrate=True)

    def test_the_question_bank_must_be_imported_first(self) -> None:
        """`test_question` is an FK into the bank; a miss refuses the pack."""
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, PACKS_DIR)
        message = str(caught.exception)
        self.assertIn("question_bank row(s) missing", message)
        self.assertIn("import_assessment_packs.py", message)
        for table in ("test_series", "test", "test_question"):
            row = self.db.fetchone(f"SELECT COUNT(*) AS c FROM {table}")
            assert row is not None
            self.assertEqual(int(row["c"]), 0)

    def test_a_bank_gap_is_named_in_the_refusal(self) -> None:
        """One missing bank row is enough to refuse, and it is named."""
        self.db.execute(
            "DELETE FROM question_bank WHERE question_id = 'q-c10-light-003-hi'"
        )
        with self.assertRaises(importer.PackError) as caught:
            importer.import_packs(self.db, PACKS_DIR)
        self.assertIn("q-c10-light-003-hi", str(caught.exception))


class SeriesImportCliTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.db_file = Path(self._tmp.name) / "series.db"

    def test_cli_dry_run_writes_nothing(self) -> None:
        code = importer.main(
            [
                "--packs-dir",
                str(PACKS_DIR),
                "--db-url",
                f"sqlite:///{self.db_file}",
                "--dry-run",
            ]
        )
        self.assertEqual(code, 0)
        self.assertFalse(
            self.db_file.exists(), "a dry run must not open or create the database"
        )

    def test_cli_import_needs_the_bank_first_and_then_writes(self) -> None:
        code = importer.main(
            ["--packs-dir", str(PACKS_DIR), "--db-url", f"sqlite:///{self.db_file}"]
        )
        self.assertEqual(code, 1)  # the bank is not imported in this fresh file
        db = DatabaseEngine.from_url(f"sqlite:///{self.db_file}", auto_migrate=False)
        _seed_bank(db)
        code = importer.main(
            [
                "--packs-dir",
                str(PACKS_DIR),
                "--db-url",
                f"sqlite:///{self.db_file}",
                "--no-migrate",
            ]
        )
        self.assertEqual(code, 0)
        row = db.fetchone("SELECT COUNT(*) AS c FROM test")
        assert row is not None
        self.assertEqual(int(row["c"]), 13)

    def test_cli_refusal_exits_non_zero_with_the_reason(self) -> None:
        packs_dir = _copy_fixture(Path(self._tmp.name))
        manifest = packs_dir / CLASS_PACK / "manifest.json"
        _rewrite_json(
            manifest,
            lambda payload: payload["gate"].__setitem__("verdict", "fail"),
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            code = importer.main(
                ["--packs-dir", str(packs_dir), "--db-url", f"sqlite:///{self.db_file}"]
            )
        self.assertEqual(code, 1)
        self.assertIn("refused", stderr.getvalue())


class SeriesImportContractTests(unittest.TestCase):
    def test_content_hash_formula_matches_the_pack_pipeline(self) -> None:
        from factory.series.publish import content_hash

        manifest = json.loads(
            (PACKS_DIR / CLASS_PACK / "manifest.json").read_text(encoding="utf-8")
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

    def test_the_fixture_pack_verifies(self) -> None:
        pack = importer.load_pack(PACKS_DIR / CLASS_PACK)
        self.assertEqual(pack.class_num, 10)
        self.assertEqual(len(pack.rows), 11)
        self.assertEqual(len(pack.series), 6)
        self.assertFalse(pack.cleared_for_verbatim)


if __name__ == "__main__":
    unittest.main()
