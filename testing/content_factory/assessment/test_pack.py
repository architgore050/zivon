"""A6-publish-export: pack shape, hashes, determinism and atomic mirroring."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from factory.assessment import pack as pack_stage
from factory.assessment.config import AssessmentConfig
from factory.assessment.pipeline import assemble_chapter_pack
from factory.assessment.schemas import (
    ASSESSMENT_PACK_MANIFEST,
    ASSESSMENT_QUESTIONS,
    ASSESSMENT_SPEAKING_ROWS,
    TIME_PRIORS,
)
from factory.assessment.validators import validate_schema

REPO_ROOT = Path(__file__).resolve().parents[3]
CHAPTER = "class-9-describing-motion-around-us"


class PackTestBase(unittest.TestCase):
    cfg: AssessmentConfig
    result: dict
    assembled: dict
    payloads: dict
    manifest: dict

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg = AssessmentConfig.for_repo(REPO_ROOT)
        cls.result = assemble_chapter_pack(cls.cfg, CHAPTER)
        cls.assembled = cls.result["assembled"]
        cls.payloads = cls.assembled["payloads"]
        cls.manifest = cls.assembled["manifest"]


class TestPackPayloads(PackTestBase):
    def test_manifest_matches_its_schema(self) -> None:
        validate_schema(self.manifest, ASSESSMENT_PACK_MANIFEST, "pack manifest")

    def test_questions_match_the_export_schema(self) -> None:
        validate_schema(
            self.payloads["questions.json"], ASSESSMENT_QUESTIONS, "questions.json"
        )

    def test_speaking_rows_match_their_schema(self) -> None:
        validate_schema(
            self.payloads["speaking.json"], ASSESSMENT_SPEAKING_ROWS, "speaking.json"
        )

    def test_time_priors_match_their_schema(self) -> None:
        validate_schema(self.payloads["time-priors.json"], TIME_PRIORS, "time-priors")

    def test_pack_has_five_data_files_plus_the_manifest(self) -> None:
        self.assertEqual(
            set(self.payloads),
            {
                "syllabus.json",
                "concepts.json",
                "questions.json",
                "speaking.json",
                "time-priors.json",
            },
        )
        self.assertEqual(set(self.manifest["files"]), set(self.payloads))

    def test_counts_agree_with_the_rows(self) -> None:
        counts = self.manifest["counts"]
        self.assertEqual(counts["base_items"], 15)
        self.assertEqual(counts["question_rows"], 45)
        self.assertEqual(counts["speaking_prompts"], 3)
        self.assertEqual(
            len(self.payloads["questions.json"]["questions"]),
            counts["question_rows"],
        )
        self.assertEqual(len(self.payloads["speaking.json"]["prompts"]), 9)

    def test_every_question_row_carries_the_required_bank_fields(self) -> None:
        required = {
            "question_id",
            "base_item_id",
            "class_level",
            "chapter_id",
            "concept_id",
            "type",
            "difficulty",
            "marks",
            "language",
            "source_type",
            "source_ref",
            "prompt",
            "answer",
            "explanation",
            "expected_time_ms",
            "status",
            "review_mode",
            "version",
            "generator",
            "run_id",
        }
        for row in self.payloads["questions.json"]["questions"]:
            self.assertLessEqual(required, set(row))

    def test_review_mode_is_honest_about_the_gate(self) -> None:
        for row in self.payloads["questions.json"]["questions"]:
            self.assertEqual(row["review_mode"], "deterministic")
            self.assertEqual(row["status"], "reviewed")

    def test_distractor_index_survives_where_a_misconception_exists(self) -> None:
        rows = [
            row
            for row in self.payloads["questions.json"]["questions"]
            if row.get("misconception")
        ]
        self.assertTrue(rows)
        for row in rows:
            if row["type"] in ("mcq", "assertion_reason"):
                self.assertIn("distractor_index", row)

    def test_file_hashes_match_the_bytes(self) -> None:
        for name, entry in self.manifest["files"].items():
            text = self.assembled["texts"][name]
            import hashlib

            self.assertEqual(
                entry["sha256"], hashlib.sha256(text.encode("utf-8")).hexdigest()
            )
            self.assertEqual(entry["bytes"], len(text.encode("utf-8")))

    def test_generated_at_does_not_change_the_content_hash(self) -> None:
        other = assemble_chapter_pack(
            self.cfg, CHAPTER, generated_at="2030-01-01T00:00:00+00:00"
        )
        self.assertEqual(
            other["assembled"]["manifest"]["content_hash"],
            self.manifest["content_hash"],
        )

    def test_content_hash_is_deterministic_across_assemblies(self) -> None:
        again = assemble_chapter_pack(self.cfg, CHAPTER)
        self.assertEqual(
            again["assembled"]["manifest"]["content_hash"],
            self.manifest["content_hash"],
        )


class TestPackWriter(PackTestBase):
    def test_write_pack_creates_every_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            pack_dir = Path(td) / "pack"
            manifest = pack_stage.write_pack(pack_dir, self.assembled)
            for name in pack_stage.DATA_FILES:
                self.assertTrue((pack_dir / name).is_file(), name)
            self.assertTrue((pack_dir / "manifest.json").is_file())
            on_disk = json.loads(
                (pack_dir / "manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(on_disk["content_hash"], manifest["content_hash"])

    def test_mirror_replaces_the_target_wholesale(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "pack"
            pack_stage.write_pack(source, self.assembled)
            target = Path(td) / "exports" / CHAPTER
            target.mkdir(parents=True)
            (target / "stale.json").write_text("{}", encoding="utf-8")
            returned = pack_stage.mirror_pack(source, target)
            self.assertEqual(returned, target)
            self.assertFalse((target / "stale.json").exists())
            self.assertTrue((target / "manifest.json").is_file())
            self.assertFalse(target.with_name(target.name + ".tmp").exists())

    def test_export_dir_override_writes_a_chapter_directory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            export = Path(td) / "exports"
            cfg = self.cfg.with_overrides(export_dir=export)
            chapter = self.result["chapter"]
            output = pack_stage.run_stage(
                cfg,
                chapter,
                syllabus=self.result["syllabus"],
                graph=self.result["graph"],
                items_output=self.result["items"],
                speaking_output=self.result["speaking"],
                priors_output=self.result["priors"],
                run_id="assessment-preview",
                generated_at="1970-01-01T00:00:00+00:00",
                pack_dir=Path(td) / "stage" / "pack",
            )
            self.assertEqual(
                Path(output["exported_dir"]), export / chapter["chapter_id"]
            )
            self.assertTrue(
                (export / chapter["chapter_id"] / "manifest.json").is_file()
            )


if __name__ == "__main__":
    unittest.main()
