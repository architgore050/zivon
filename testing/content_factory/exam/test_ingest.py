"""E1 ingest: pattern-metadata fidelity and the no-source-text guarantee."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from factory.exam import ingest as ingest_stage
from factory.exam.errors import ExamGateError
from testing.content_factory.exam.support import REPO_ROOT, temp_exam_config

PAPERS = REPO_ROOT / "sources" / "exam" / "papers"
SAMPLE = PAPERS / "cbse-c12-physics-2024-main.json"


def load_document() -> dict:
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def rules(report: dict) -> set[str]:
    return {issue["rule"] for issue in report["issues"]}


class IngestTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.cfg, self._cfg_handle = temp_exam_config()
        self.cfg = self._replace_papers_dir(self.dir)

    def tearDown(self) -> None:
        self._cfg_handle.cleanup()
        self._tmp.cleanup()

    def _replace_papers_dir(self, path: Path):
        import dataclasses

        return dataclasses.replace(self.cfg, papers_dir=path)

    def write(self, document: dict, name: str = "paper.json") -> None:
        (self.dir / name).write_text(
            json.dumps(document, ensure_ascii=False), encoding="utf-8"
        )

    def run_gate(self) -> dict:
        try:
            return ingest_stage.run_stage(self.cfg)
        except ExamGateError as exc:
            return {"gate": exc.report, "raised": True}


class ShippedFixturesTests(IngestTestBase):
    def test_the_tracked_fixtures_ingest_cleanly(self) -> None:
        output = ingest_stage.run_stage(self._replace_papers_dir(PAPERS))
        self.assertEqual(output["gate"]["verdict"], "pass")
        self.assertFalse(output["source_text_stored"])
        self.assertEqual(output["counts"]["papers"], 14)
        self.assertEqual(output["counts"]["questions"], 329)
        self.assertEqual(
            output["counts"]["by_paper_type"],
            {
                "compartment": 2,
                "main": 10,
                "sample": 2,
            },
        )
        self.assertEqual(output["counts"]["by_class"], {"10": 7, "12": 7})

    def test_every_paper_carries_provenance_and_a_file_hash(self) -> None:
        output = ingest_stage.run_stage(self._replace_papers_dir(PAPERS))
        for paper in output["papers"]:
            self.assertTrue(paper["provenance"]["source_url"].startswith("https://"))
            self.assertFalse(paper["provenance"]["verified"])
            self.assertEqual(len(paper["file_sha256"]), 64)
            self.assertIsNone(paper["set_code"])

    def test_paper_records_never_carry_a_text_key(self) -> None:
        output = ingest_stage.run_stage(self._replace_papers_dir(PAPERS))
        forbidden = {"text", "prompt", "options", "answer", "passage", "solution"}
        for question in output["questions"]:
            self.assertFalse(forbidden & set(question), question)
        for paper in output["papers"]:
            self.assertFalse(forbidden & set(paper), paper)


class IngestGateTests(IngestTestBase):
    def test_a_text_field_is_a_fatal_source_text_finding(self) -> None:
        document = load_document()
        document["questions"][0]["text"] = (
            "A verbatim question that must never be stored"
        )
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.source_text", rules(result["gate"]))
        self.assertEqual(result["gate"]["verdict"], "fail")

    def test_a_nested_text_field_is_caught_too(self) -> None:
        document = load_document()
        document["provenance"]["passage"] = "some quoted source text"
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.source_text", rules(result["gate"]))

    def test_a_marks_mismatch_is_fatal(self) -> None:
        document = load_document()
        document["questions"][0]["marks"] = 5
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.marks_sum", rules(result["gate"]))
        self.assertIn("exam.paper.sections", rules(result["gate"]))

    def test_an_unknown_chapter_is_fatal(self) -> None:
        document = load_document()
        document["questions"][0]["chapter_id"] = "class-12-not-a-chapter"
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.question.chapter_unknown", rules(result["gate"]))

    def test_a_chapter_from_another_class_is_fatal(self) -> None:
        document = load_document()
        document["questions"][0]["chapter_id"] = (
            "class-10-light-reflection-and-refraction"
        )
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.question.chapter_class", rules(result["gate"]))

    def test_the_wrong_subject_code_is_fatal(self) -> None:
        document = load_document()
        document["subject_code"] = "086"
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.class_subject", rules(result["gate"]))

    def test_the_wrong_scope_is_fatal(self) -> None:
        document = load_document()
        document["scope"] = "physics_section"
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.scope", rules(result["gate"]))

    def test_a_section_count_mismatch_is_fatal(self) -> None:
        document = load_document()
        document["sections"][0]["question_count"] = 15
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.sections", rules(result["gate"]))

    def test_a_duplicate_paper_id_is_fatal(self) -> None:
        document = load_document()
        self.write(document, "a.json")
        self.write(copy.deepcopy(document), "b.json")
        result = self.run_gate()
        self.assertIn("exam.paper.duplicate", rules(result["gate"]))

    def test_a_pdf_in_the_fixture_tree_is_fatal(self) -> None:
        self.write(load_document())
        (self.dir / "cbse-paper.pdf").write_bytes(b"%PDF-1.4 not allowed")
        result = self.run_gate()
        self.assertIn("exam.paper.source_file", rules(result["gate"]))

    def test_missing_provenance_fails_schema(self) -> None:
        document = load_document()
        document.pop("provenance")
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.paper.schema", rules(result["gate"]))

    def test_a_marks_type_mismatch_is_fatal(self) -> None:
        document = load_document()
        # A 5-mark MCQ is not the paper template's shape.
        document["questions"][0]["marks"] = 5
        document["questions"][0]["type"] = "mcq"
        self.write(document)
        result = self.run_gate()
        self.assertIn("exam.question.marks_type", rules(result["gate"]))

    def test_an_unexpected_json_document_fails_loudly(self) -> None:
        from factory.exam.errors import ExamStageError

        (self.dir / "broken.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ExamStageError):
            ingest_stage.run_stage(self.cfg)


class IngestNullSetCodeTests(IngestTestBase):
    def test_a_main_paper_without_a_set_code_is_recorded_debt(self) -> None:
        self.write(load_document())
        result = self.run_gate()
        self.assertEqual(result["gate"]["verdict"], "pass")
        issues = [
            issue
            for issue in result["gate"]["issues"]
            if issue["rule"] == "exam.paper.set_code"
        ]
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "minor")


if __name__ == "__main__":
    unittest.main()
