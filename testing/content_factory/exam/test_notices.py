"""The approved notice copy is the doc, byte for byte.

`notices.md` is normative: the publish gate rejects a rendered notice that
differs from those strings. This test parses the Markdown and compares it to
`factory/exam/notices.py`, so the code cannot quietly drift from the approved
copy, and proves the renderer refuses a partial notice.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from factory.exam.errors import ExamCopyError
from factory.exam.notices import (
    NOTICE_PLACEHOLDERS,
    NOTICE_VERSION,
    NOTICES,
    notice_placeholders,
    paper_ref,
    paper_type_label,
    render_notice,
    scan_claims,
    series_name,
    subject_label,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
NOTICES_MD = REPO_ROOT / "docs" / "compliance" / "notices.md"


def notice_blocks() -> dict[str, str]:
    text = NOTICES_MD.read_text(encoding="utf-8")
    blocks = re.findall(r"```text\n(.*?)\n```", text, re.DOTALL)
    ids = ["N-01", "N-02", "N-03", "N-04", "N-05"]
    found: dict[str, str] = {}
    for index, notice_id in enumerate(ids):
        found[f"{notice_id}-en"] = blocks[index * 2]
        found[f"{notice_id}-hi"] = blocks[index * 2 + 1]
    return found


class NoticeTextTests(unittest.TestCase):
    def test_every_notice_matches_the_doc_byte_for_byte(self) -> None:
        for key, text in notice_blocks().items():
            notice_id, language = key.rsplit("-", 1)
            with self.subTest(notice=key):
                self.assertEqual(NOTICES[notice_id][language], text)

    def test_only_english_and_hindi_are_approved(self) -> None:
        for notice_id, locales in NOTICES.items():
            self.assertEqual(sorted(locales), ["en", "hi"], notice_id)

    def test_the_notice_version_is_recorded(self) -> None:
        self.assertEqual(NOTICE_VERSION, "1")

    def test_the_placeholder_contract_matches_the_doc(self) -> None:
        text = NOTICES_MD.read_text(encoding="utf-8")
        rows = {
            match.group(1): match.group(2)
            for match in re.finditer(
                r"^\| `\{\{([a-z_]+)\}\}` \|[^|]+\|[^|]+\| (.+?) \|$",
                text,
                re.MULTILINE,
            )
        }
        declared: dict[str, set[str]] = {}
        for placeholder, used_on in rows.items():
            declared[placeholder] = set(re.findall(r"N-0[1-5]", used_on))
        code: dict[str, set[str]] = {}
        for notice_id, placeholders in NOTICE_PLACEHOLDERS.items():
            for placeholder in placeholders:
                code.setdefault(placeholder, set()).add(notice_id)
        self.assertEqual(
            {key: sorted(value) for key, value in declared.items()},
            {key: sorted(value) for key, value in code.items()},
        )


class RenderTests(unittest.TestCase):
    def test_n01_renders_for_both_classes(self) -> None:
        english = render_notice(
            "N-01",
            "en",
            {"class_num": 10, "subject": subject_label("Science", "en")},
        )
        self.assertIn("CBSE Class 10 Science (Physics section)", english)
        self.assertIn("not CBSE questions", english)
        hindi = render_notice(
            "N-01",
            "hi",
            {"class_num": 12, "subject": subject_label("Physics", "hi")},
        )
        self.assertIn("भौतिकी", hindi)
        self.assertIn("12", hindi)

    def test_n02_resolves_a_set_code_and_a_question(self) -> None:
        rendered = render_notice(
            "N-02",
            "en",
            {
                "source_board": "CBSE",
                "class_num": 12,
                "subject": subject_label("Physics", "en"),
                "subject_code": "042",
                "paper_year": 2024,
                "paper_type": paper_type_label("main", "en"),
                "paper_ref": paper_ref("55/1/1", "23", "en"),
                "source_url": "https://www.cbse.gov.in/example.pdf",
            },
        )
        self.assertIn("Set 55/1/1, Question 23", rendered)
        self.assertIn("2024 main exam paper", rendered)
        self.assertIn("Reproduced unchanged", rendered)

    def test_paper_ref_drops_a_missing_set_code(self) -> None:
        self.assertEqual(paper_ref(None, "12", "en"), "Question 12")
        self.assertEqual(paper_ref(None, "12", "hi"), "प्रश्न 12")
        self.assertEqual(paper_ref("55/2/1", "9", "hi"), "सेट 55/2/1, प्रश्न 9")

    def test_localized_labels_come_from_the_approved_table(self) -> None:
        self.assertEqual(paper_type_label("sample", "en"), "sample paper")
        self.assertEqual(paper_type_label("sample", "hi"), "नमूना प्रश्न-पत्र")
        self.assertEqual(paper_type_label("compartment", "hi"), "कम्पार्टमेंट परीक्षा पेपर")
        self.assertEqual(series_name("past_year", "en"), "Past-year questions (CBSE)")
        self.assertEqual(series_name("past_year", "hi"), "पिछले वर्षों के प्रश्न (CBSE)")

    def test_an_unresolved_placeholder_raises(self) -> None:
        with self.assertRaises(ExamCopyError):
            render_notice("N-01", "en", {"class_num": 10})
        with self.assertRaises(ExamCopyError):
            render_notice("N-03", "en", {"series_name": "Past-year questions (CBSE)"})
        with self.assertRaises(ExamCopyError):
            render_notice("N-01", "hi-Latn", {"class_num": 10, "subject": "Physics"})

    def test_a_value_that_reintroduces_a_token_raises(self) -> None:
        with self.assertRaises(ExamCopyError):
            render_notice(
                "N-01",
                "en",
                {"class_num": "{{class_num}}", "subject": "Physics"},
            )

    def test_unknown_notice_id_raises(self) -> None:
        with self.assertRaises(ExamCopyError):
            render_notice("N-99", "en", {})
        with self.assertRaises(ExamCopyError):
            notice_placeholders("N-99")


class ClaimScanTests(unittest.TestCase):
    def test_the_approved_disclaimer_is_not_a_claim(self) -> None:
        text = (
            "Full-paper rehearsal close to the CBSE Class 10 Science paper pattern. "
            "Built for practice; not an official CBSE paper."
        )
        self.assertEqual(scan_claims(text), [])

    def test_a_positive_official_claim_is_flagged(self) -> None:
        findings = scan_claims("This is an official CBSE paper for Class 12.")
        self.assertEqual([finding["reason"] for finding in findings], ["official_cbse"])

    def test_previous_year_and_pyq_claims_are_flagged(self) -> None:
        reasons = {
            f["reason"] for f in scan_claims("Solve previous year questions and PYQs.")
        }
        self.assertEqual(reasons, {"previous_year_claim", "pyq_claim"})

    def test_affiliation_and_partnership_claims_are_flagged(self) -> None:
        for text, reason in (
            ("Zivon is affiliated with CBSE.", "cbse_affiliated"),
            ("A CBSE-approved series.", "cbse_approved"),
            ("Built in partnership with CBSE.", "cbse_partnership"),
            ("Exact CBSE paper, 2024.", "exact_cbse_claim"),
            ("The actual board paper.", "actual_board_paper_claim"),
            ("A past paper dump.", "past_paper_claim"),
        ):
            with self.subTest(text=text):
                reasons = {f["reason"] for f in scan_claims(text)}
                self.assertIn(reason, reasons)

    def test_scan_can_report_raw_phrases_when_asked(self) -> None:
        findings = scan_claims("not an exact CBSE paper", allow_negated=False)
        self.assertTrue(findings)


if __name__ == "__main__":
    unittest.main()
