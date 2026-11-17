"""Docs contract for `docs/content-factory/exam.md`.

The doc is the operator's contract, so the parts a reader acts on - the six
series, the approved minimums, the compliance flags and the doc map - must not
drift from the code. These are cheap text assertions, not a prose review.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from factory.exam import EXAM_STAGE_ORDER, PACK_LANGUAGES
from factory.series import MINIMUM_VOLUME, SERIES_ORDER

REPO = Path(__file__).resolve().parents[3]
DOC = REPO / "docs" / "content-factory" / "exam.md"
README = REPO / "sources" / "exam" / "README.md"


class ExamDocContract(unittest.TestCase):
    def setUp(self) -> None:
        self.text = DOC.read_text(encoding="utf-8")

    def test_doc_exists_and_is_substantive(self) -> None:
        self.assertTrue(DOC.is_file())
        self.assertGreater(len(self.text), 4000)

    def test_every_stage_and_series_is_named(self) -> None:
        for stage in EXAM_STAGE_ORDER:
            self.assertIn(stage, self.text)
        for series_id in SERIES_ORDER:
            self.assertIn(f"`{series_id}`", self.text)

    def test_approved_minimums_are_quoted_from_the_code(self) -> None:
        rows = "".join(
            line
            for line in self.text.splitlines()
            if line.startswith("| `") and "|" in line
        )
        for class_num in (10, 12):
            for series_id, minimum in MINIMUM_VOLUME[class_num].items():
                for key, value in minimum.items():
                    with self.subTest(series=series_id, key=key):
                        self.assertTrue(
                            re.search(rf"\b{value}\b", rows),
                            f"{series_id}.{key}={value} is not quoted in the doc",
                        )

    def test_compliance_links_and_flags_are_present(self) -> None:
        for token in (
            "docs/compliance/decision-log.md",
            "docs/compliance/notices.md",
            "EXAM_CONTENT_MODE",
            "EXAM_VERBATIM_CLEARANCE_ID",
            "SERIES_EXACT_PYQ_ENABLED",
            "DEC-COMP-001",
            "blueprint_only",
        ):
            self.assertIn(token, self.text)

    def test_language_policy_is_documented(self) -> None:
        for language in PACK_LANGUAGES:
            self.assertIn(language, self.text)

    def test_the_doc_map_and_runbook_point_at_it(self) -> None:
        agents = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertIn("`exam.md`", agents)
        runbook = (REPO / "docs" / "content-factory" / "runbook.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("python -m factory.exam", runbook)
        config = (REPO / "docs" / "content-factory" / "config-reference.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("## exam", config)

    def test_the_data_folder_says_it_holds_no_papers(self) -> None:
        text = README.read_text(encoding="utf-8")
        self.assertIn("never source text", text.lower())
        self.assertIn("DEC-COMP-001", text)
        for token in (".pdf", "no text", "source text"):
            self.assertIn(token, text)


if __name__ == "__main__":
    unittest.main()
