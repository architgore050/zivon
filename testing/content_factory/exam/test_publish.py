"""E4 publish: language-filtered rows, the blocked/ready decision, the pack.

The publish decision is the product's answer to "may this ship?". These tests
pin the two halves: a blocked pack is written as evidence and never mirrored,
and a row never claims a language its series does not offer.
"""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from factory.exam.blueprint import build_blueprint
from factory.exam.ingest import run_stage as ingest_run
from factory.exam.similarity import check_text, jaccard, normalize, shingles
from factory.exam.syllabus import chapters_for_class, load_syllabus
from factory.series.assembly import assemble_class
from factory.series.publish import (
    DATA_FILES,
    assemble_pack,
    content_hash,
    flatten_items,
    mirror_pack,
    run_stage,
    write_pack,
)
from testing.content_factory.exam.support import REPO_ROOT, temp_exam_config

SYLLABUS = REPO_ROOT / "sources" / "syllabus" / "syllabus.json"
GENERATED_AT = "2026-11-17T00:00:00+00:00"


class PublishTestBase(unittest.TestCase):
    cfg: Any
    chapters: list[dict[str, Any]]
    ingest: dict[str, Any]
    blueprint: dict[str, Any]
    series: dict[str, Any]
    pack: dict[str, Any]
    _handle: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.cfg, handle = temp_exam_config()
        cls._handle = handle
        cls.chapters = chapters_for_class(load_syllabus(SYLLABUS), 10)
        cls.ingest = ingest_run(cls.cfg)
        cls.blueprint = build_blueprint(
            cls.ingest, class_num=10, chapters=cls.chapters, policy=cls.cfg.blueprint
        )
        cls.series = assemble_class(
            cls.cfg,
            blueprint=cls.blueprint,
            ingest=cls.ingest,
            chapters=cls.chapters,
            generated_at=GENERATED_AT,
        )
        cls.pack = assemble_pack(
            cfg=cls.cfg,
            blueprint=cls.blueprint,
            ingest=cls.ingest,
            class_series=cls.series,
            chapters=cls.chapters,
            run_id="exam-class-10",
            generated_at=GENERATED_AT,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._handle.cleanup()


class RowTests(PublishTestBase):
    def test_rows_are_one_per_item_and_language(self) -> None:
        rows = self.pack["payloads"]["items.json"]["items"]
        keys = {(row["item_id"], row["language"]) for row in rows}
        self.assertEqual(len(keys), len(rows))
        self.assertEqual({row["language"] for row in rows}, {"en", "hi", "hi-Latn"})

    def test_a_board_series_never_claims_hinglish(self) -> None:
        rows = self.pack["payloads"]["items.json"]["items"]
        policies = {
            s["series_id"]: set(s["language_policy"])
            for s in self.pack["payloads"]["series.json"]["series"]
        }
        for row in rows:
            for series_id in row["series_ids"]:
                self.assertIn(row["language"], policies[series_id], row["question_id"])
        hinglish = [row for row in rows if row["language"] == "hi-Latn"]
        self.assertTrue(hinglish)
        for row in hinglish:
            self.assertNotIn("board_practice", row["series_ids"])
            self.assertNotIn("pyq_pattern", row["series_ids"])

    def test_every_row_carries_source_metadata(self) -> None:
        for row in self.pack["payloads"]["items.json"]["items"]:
            self.assertEqual(row["source_type"], "generated_blueprint")
            self.assertTrue(row["pattern_ref"])
            self.assertIn("similarity", row)
            self.assertIn("explanation", row)
            self.assertTrue(row["series_ids"])

    def test_flatten_skips_a_language_no_series_offers(self) -> None:
        item = copy.deepcopy(self.series["items"][0])
        item["series_ids"] = ["board_practice"]
        rows = flatten_items([item], self.series["series"])
        self.assertEqual({row["language"] for row in rows}, {"en", "hi"})

    def test_an_item_with_no_offered_language_is_not_exported(self) -> None:
        item = copy.deepcopy(self.series["items"][0])
        item["series_ids"] = ["not_a_series"]
        self.assertEqual(flatten_items([item], self.series["series"]), [])


class PackTests(PublishTestBase):
    def test_all_pack_files_are_present(self) -> None:
        self.assertEqual(set(self.pack["texts"]), set(DATA_FILES))
        papers = self.pack["payloads"]["papers.json"]
        self.assertFalse(papers["source_text_stored"])
        self.assertEqual(len(papers["papers"]), 7)

    def test_the_manifest_records_the_compliance_state(self) -> None:
        manifest = self.pack["manifest"]
        self.assertEqual(manifest["content_mode"], "blueprint_only")
        self.assertEqual(manifest["notice_version"], "1")
        compliance = manifest["compliance"]
        self.assertFalse(compliance["verbatim_allowed"])
        self.assertEqual(compliance["verbatim_items"], 0)
        self.assertEqual(compliance["third_party_items"], 0)
        self.assertEqual(compliance["source_corpus_items"], 0)
        self.assertEqual(compliance["notice_ids"], ["N-01"])
        self.assertEqual(
            compliance["exact_pyq_status"], "disabled:no_verbatim_clearance"
        )

    def test_a_blocked_pack_names_its_blockers_and_reasons(self) -> None:
        publish = self.pack["manifest"]["publish"]
        self.assertEqual(publish["status"], "blocked")
        self.assertTrue(publish["blockers"])
        self.assertIn("volume", publish["reason_codes"])
        for blocker in publish["blockers"]:
            self.assertIn(blocker["severity"], ("fatal", "major"))
            self.assertTrue(blocker["message"])

    def test_the_content_hash_is_stable_for_the_same_inputs(self) -> None:
        again = assemble_pack(
            cfg=self.cfg,
            blueprint=self.blueprint,
            ingest=self.ingest,
            class_series=self.series,
            chapters=self.chapters,
            run_id="exam-class-10",
            generated_at=GENERATED_AT,
        )
        self.assertEqual(
            again["manifest"]["content_hash"], self.pack["manifest"]["content_hash"]
        )

    def test_the_content_hash_changes_when_content_changes(self) -> None:
        files = dict(self.pack["manifest"]["files"])
        files["items.json"] = {**files["items.json"], "sha256": "0" * 64}
        self.assertNotEqual(content_hash(files), self.pack["manifest"]["content_hash"])

    def test_write_pack_writes_the_manifest_last_and_completely(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        directory = Path(tmp.name) / "pack"
        manifest = write_pack(directory, self.pack)
        for name in DATA_FILES:
            self.assertTrue((directory / name).is_file(), name)
        on_disk = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(on_disk["content_hash"], manifest["content_hash"])

    def test_a_blocked_pack_is_written_but_not_mirrored(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        export_dir = Path(tmp.name) / "exports"
        import dataclasses

        cfg = dataclasses.replace(self.cfg, export_dir=export_dir)
        output = run_stage(
            cfg=cfg,
            blueprint=self.blueprint,
            ingest=self.ingest,
            class_series=self.series,
            chapters=self.chapters,
            run_id="exam-class-10",
            generated_at=GENERATED_AT,
            pack_dir=Path(tmp.name) / "run" / "pack",
        )
        self.assertIsNone(output["exported_dir"])
        self.assertFalse(export_dir.exists())
        self.assertEqual(output["manifest"]["publish"]["status"], "blocked")

    def test_mirror_replaces_a_previous_copy(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        source = Path(tmp.name) / "pack"
        write_pack(source, self.pack)
        target = Path(tmp.name) / "out" / "class-10"
        target.mkdir(parents=True)
        (target / "stale.txt").write_text("old", encoding="utf-8")
        mirror_pack(source, target)
        self.assertFalse((target / "stale.txt").exists())
        self.assertTrue((target / "manifest.json").is_file())


class SimilarityGateTests(unittest.TestCase):
    SOURCE = (
        "A ray of light travelling in air enters a glass slab of refractive index "
        "one point five at an angle of incidence of forty five degrees calculate "
        "the angle of refraction inside the slab"
    )

    def test_normalisation_strips_punctuation_and_maps_digits(self) -> None:
        self.assertEqual(normalize("A ray, of LIGHT 45°!"), "a ray of light ##")

    def test_an_empty_corpus_is_vacuously_clear_not_a_fake_pass(self) -> None:
        record = check_text(self.SOURCE, [], checked_at="2026-11-17")
        self.assertEqual(record["verdict"], "vacuously_clear")
        self.assertEqual(record["corpus_size"], 0)
        self.assertIsNone(record["nearest_source_item_id"])

    def test_a_shared_eight_gram_blocks(self) -> None:
        record = check_text(
            self.SOURCE,
            [{"item_id": "src-1", "text": self.SOURCE}],
            checked_at="2026-11-17",
        )
        self.assertEqual(record["verdict"], "blocked")
        self.assertTrue(record["shared_ngram"])
        self.assertEqual(record["nearest_source_item_id"], "src-1")

    def test_an_independent_question_is_clear(self) -> None:
        record = check_text(
            "Explain why the sky looks blue during the day and red near sunset.",
            [{"item_id": "src-1", "text": self.SOURCE}],
            checked_at="2026-11-17",
        )
        self.assertEqual(record["verdict"], "clear")
        self.assertFalse(record["shared_ngram"])

    def test_jaccard_bounds(self) -> None:
        self.assertEqual(jaccard(set(), set()), 0.0)
        self.assertEqual(
            jaccard(shingles("a b c d e f g h"), shingles("a b c d e f g h")), 1.0
        )


if __name__ == "__main__":
    unittest.main()
