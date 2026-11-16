"""Docs contract tests for docs/compliance/ (C0 compliance research).

These are deterministic, key-free, offline checks that the compliance folder
stays internally consistent: every decision has a row, every row is cited, every
notice id is used, every placeholder is declared, every source is dated, and
every relative link resolves. They do not judge the legal reasoning — that is a
human/counsel job — they stop the evidence chain from rotting silently.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FOLDER = REPO / "docs" / "compliance"
README = FOLDER / "README.md"
MEMO = FOLDER / "cbse-exam-content.md"
DECISIONS = FOLDER / "decision-log.md"
NOTICES = FOLDER / "notices.md"
SOURCES = FOLDER / "sources.md"

CONFIDENCE = ("[STRONG]", "[MODERATE]", "[WEAK]", "[ASSUMPTION]")
REQUIRED_MEMO_SECTIONS = (
    "## 0. Bottom line",
    "## 1. Scope, method and limits",
    "## 2. Does copyright subsist",
    "## 3. Does any statutory exception",
    "## 4. What CBSE's own terms say",
    "## 5. Content-type matrix",
    "## 6. Decision",
    "## 7. What P3 must build",
    "## 8. What the student sees",
    "## 9. Residual risk register",
    "## 10. Counsel brief",
    "## 11. Review triggers",
    "## Appendix A",
    "## Appendix B",
)


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class ComplianceDocsContract(unittest.TestCase):
    def test_required_files_exist_and_are_substantive(self) -> None:
        for path in (README, MEMO, DECISIONS, NOTICES, SOURCES):
            with self.subTest(path=path.name):
                self.assertTrue(path.is_file(), f"{path} is missing")
                self.assertGreater(
                    len(read(path)), 500, f"{path.name} is too thin to be a contract"
                )

    def test_readme_states_disclaimer_scope_and_cadence(self) -> None:
        text = read(README).lower()
        self.assertIn("not legal advice", text)
        self.assertIn("## scope", text)
        self.assertIn("quarterly", text)
        self.assertIn("decision-log.md", text)

    def test_memo_has_the_required_sections_in_order(self) -> None:
        text = read(MEMO)
        positions = []
        for heading in REQUIRED_MEMO_SECTIONS:
            index = text.find(heading)
            self.assertNotEqual(index, -1, f"missing section: {heading}")
            positions.append(index)
        self.assertEqual(positions, sorted(positions), "memo sections are out of order")

    def test_findings_are_sequential_tagged_and_unique(self) -> None:
        text = read(MEMO)
        numbers = [int(n) for n in re.findall(r"^\*\*F-(\d{2}) —", text, re.MULTILINE)]
        self.assertGreaterEqual(len(numbers), 15, "expected the full findings set")
        self.assertEqual(numbers, sorted(numbers), "findings are out of order")
        self.assertEqual(len(numbers), len(set(numbers)), "duplicate finding id")
        self.assertEqual(numbers, list(range(1, len(numbers) + 1)), "finding id gap")

        finding_starts = [
            (match.start(), int(match.group(1)))
            for match in re.finditer(r"^\*\*F-(\d{2}) —", text, re.MULTILINE)
        ]
        for index, (start, finding_id) in enumerate(finding_starts):
            end = (
                finding_starts[index + 1][0]
                if index + 1 < len(finding_starts)
                else len(text)
            )
            block = text[start:end]
            with self.subTest(finding=f"{finding_id:02d}"):
                self.assertTrue(
                    any(tag in block for tag in CONFIDENCE),
                    f"F-{finding_id:02d} has no confidence tag",
                )

    def test_decision_ids_are_defined_and_cited(self) -> None:
        log_text = read(DECISIONS)
        memo_text = read(MEMO)
        defined = re.findall(r"^\| `DEC-COMP-(\d{3})`", log_text, re.MULTILINE)
        self.assertEqual(
            defined, ["001", "002", "003", "004", "005", "006", "007", "008"]
        )
        cited = set(re.findall(r"DEC-COMP-(\d{3})", memo_text))
        self.assertEqual(cited, set(defined), "memo and decision log disagree")
        for decision_id in defined:
            with self.subTest(decision=decision_id):
                row = re.search(
                    rf"^\| `DEC-COMP-{decision_id}` \|(.+)$", log_text, re.MULTILINE
                )
                if row is None:
                    self.fail(f"DEC-COMP-{decision_id} row missing")
                self.assertGreaterEqual(
                    row.group(1).count("|"), 6, "decision row is missing columns"
                )

    def test_counsel_questions_are_defined_and_cited(self) -> None:
        log_text = read(DECISIONS)
        memo_text = read(MEMO)
        defined = re.findall(r"^\| `CQ-(\d{2})`", log_text, re.MULTILINE)
        self.assertEqual(len(defined), 10, "expected ten counsel questions")
        self.assertEqual(defined, [f"{n:02d}" for n in range(1, 11)])
        cited = set(re.findall(r"CQ-(\d{2})", memo_text))
        self.assertTrue(cited, "memo cites no counsel question")
        self.assertLessEqual(cited, set(defined), "memo cites an undefined CQ id")
        self.assertIn("CQ-01", memo_text)
        self.assertIn("CQ-10", memo_text)

    def test_notice_ids_are_defined_and_used(self) -> None:
        notice_text = read(NOTICES)
        memo_text = read(MEMO)
        defined = re.findall(r"^## (N-\d{2}) —", notice_text, re.MULTILINE)
        self.assertEqual(defined, ["N-01", "N-02", "N-03", "N-04", "N-05"])
        for notice_id in defined:
            with self.subTest(notice=notice_id):
                self.assertIn(notice_id, memo_text, f"{notice_id} is never used")
        self.assertIn("not affiliated", notice_text)
        self.assertIn("They are not CBSE questions", notice_text)
        self.assertIn("this is not an official CBSE paper", notice_text)

    def test_notices_are_bilingual(self) -> None:
        text = read(NOTICES)
        devanagari = re.findall(r"[\u0900-\u097F]", text)
        self.assertGreater(len(devanagari), 100, "Hindi notice copy is missing")
        self.assertIn("पेपर", text)

    def test_notice_contract_declares_localized_labels(self) -> None:
        """Every placeholder that renders words must have a Hindi value too."""
        text = read(NOTICES)
        for label in (
            "मुख्य परीक्षा पेपर",
            "नमूना प्रश्न-पत्र",
            "सेट 55/1/1, प्रश्न 23",
            "भौतिकी",
        ):
            with self.subTest(label=label):
                self.assertIn(label, text, "missing localized notice value")

    def _notice_block(self, text: str, notice_id: str, language: str) -> str:
        heading = re.search(rf"^## {notice_id} .*$", text, re.MULTILINE)
        if heading is None:
            self.fail(f"{notice_id} has no heading")
        rest = text[heading.end() :]
        nxt = re.search(r"^## ", rest, re.MULTILINE)
        section = rest[: nxt.start()] if nxt else rest
        match = re.search(
            rf"\*\*{language}\*\*\n\n```text\n(.*?)\n```", section, re.DOTALL
        )
        if match is None:
            self.fail(f"{notice_id} has no {language} copy")
        return match.group(1)

    def test_notices_render_cleanly_in_both_modes_and_languages(self) -> None:
        """Render every notice with real values: no doubled word, no leaked token."""
        text = read(NOTICES)
        base = {
            "contact_email": "compliance@example.com",
            "source_board": "CBSE",
            "class_num": "12",
            "subject_code": "042",
            "paper_year": "2024",
            "source_url": "https://www.cbse.gov.in/example-paper.pdf",
        }
        # (language, subject, series_name, {paper: (paper_type, paper_ref)}, ascii allowed)
        languages: list[tuple[str, str, str, dict[str, tuple[str, str]], set[str]]] = [
            (
                "EN",
                "Physics",
                "Past-year questions (CBSE)",
                {
                    "main": ("main exam paper", "Set 55/1/1, Question 23"),
                    "sample": ("sample paper", "Question 12"),
                },
                {"CBSE"},
            ),
            (
                "HI",
                "भौतिकी",
                "पिछले वर्षों के प्रश्न (CBSE)",
                {
                    "main": ("मुख्य परीक्षा पेपर", "सेट 55/1/1, प्रश्न 23"),
                    "sample": ("नमूना प्रश्न-पत्र", "प्रश्न 12"),
                },
                {"CBSE"},
            ),
        ]
        for notice_id in ("N-01", "N-02", "N-03", "N-04"):
            for language, subject, series_name, papers, ascii_allow in languages:
                block = self._notice_block(text, notice_id, language)
                for paper, (paper_type, paper_ref) in papers.items():
                    resolved = dict(
                        base,
                        subject=subject,
                        series_name=series_name,
                        paper_type=paper_type,
                        paper_ref=paper_ref,
                    )
                    with self.subTest(notice=notice_id, lang=language, paper=paper):
                        rendered = block
                        for name, value in resolved.items():
                            rendered = rendered.replace("{{" + name + "}}", value)
                        self.assertNotIn("{{", rendered, "unresolved placeholder")
                        doubled = re.findall(r"\b(\w+) \1\b", rendered)
                        self.assertEqual(
                            doubled, [], f"notice renders a doubled word: {doubled}"
                        )
                        if language != "HI":
                            continue
                        scrubbed = rendered.replace(base["source_url"], "").replace(
                            base["contact_email"], ""
                        )
                        leaked = set(re.findall(r"[A-Za-z]{4,}", scrubbed))
                        self.assertLessEqual(
                            leaked,
                            ascii_allow,
                            f"Hindi notice carries an English label: {leaked}",
                        )

    def test_placeholders_are_declared_and_all_used(self) -> None:
        text = read(NOTICES)
        start = text.index("<!-- placeholder-contract:start -->")
        end = text.index("<!-- placeholder-contract:end -->")
        contract = text[start:end]
        body = text[:start] + text[end:]

        declared = set(re.findall(r"`\{\{([a-z_]+)\}\}`", contract))
        used = set(re.findall(r"\{\{([a-z_]+)\}\}", body))
        self.assertTrue(declared, "placeholder contract table is empty")
        self.assertEqual(declared, used, "declared and used placeholders disagree")
        self.assertTrue(
            all(re.fullmatch(r"[a-z_]+", name) for name in declared),
            "placeholder names must be lower_snake_case",
        )

    def test_unresolved_placeholder_is_a_publish_error(self) -> None:
        text = read(NOTICES)
        self.assertIn("publish error", text.lower())
        self.assertIn("unresolved", text.lower())

    def test_decision_is_blueprint_only_and_verbatim_is_gated(self) -> None:
        log_text = read(DECISIONS)
        memo_text = read(MEMO)
        self.assertIn("EXAM_CONTENT_MODE=blueprint_only", log_text)
        self.assertIn("No clearance exists", log_text)
        self.assertIn("_(none)_", log_text)
        self.assertIn("Blueprint-only is the shipping default", memo_text)
        self.assertIn("EXAM_VERBATIM_CLEARANCE_ID", memo_text)

    def test_sources_are_dated_and_have_a_status(self) -> None:
        text = read(SOURCES)
        self.assertIn("2026-11-15", text)
        rows = [line for line in text.splitlines() if re.match(r"^\| S-\d{2} \|", line)]
        self.assertGreaterEqual(len(rows), 20, "expected the full source register")
        for row in rows:
            cells = [cell.strip() for cell in row.split("|")[1:-1]]
            with self.subTest(source=cells[0]):
                self.assertEqual(len(cells), 5, "source row must have five columns")
                self.assertIn("https://", cells[2], "source row has no URL")
                self.assertTrue(cells[3], "source row has no fetch status")
                self.assertTrue(cells[4], "source row says what it establishes")

    def test_source_ids_have_no_orphans(self) -> None:
        defined = set(re.findall(r"^\| (S-\d{2}) \|", read(SOURCES), re.MULTILINE))
        cited = set(re.findall(r"\b(S-\d{2})\b", read(MEMO)))
        self.assertLessEqual(cited, defined, "memo cites an undefined source")
        orphans = defined - cited
        self.assertFalse(orphans, f"sources never cited in the memo: {sorted(orphans)}")

    def test_secondary_sources_are_defined_before_use(self) -> None:
        defined = set(re.findall(r"^\| (X-\d{2}) \|", read(SOURCES), re.MULTILINE))
        cited = set(re.findall(r"\bX-\d{2}\b", read(MEMO)))
        self.assertTrue(defined, "secondary-source register is empty")
        self.assertLessEqual(cited, defined, "memo cites an undefined secondary source")
        self.assertTrue(cited, "memo cites no secondary source")

    def test_relative_markdown_links_resolve(self) -> None:
        link = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for path in sorted(FOLDER.glob("*.md")):
            for target in link.findall(read(path)):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                with self.subTest(file=path.name, target=target):
                    self.assertTrue(
                        (path.parent / relative).exists(),
                        f"{path.name} links to missing {target}",
                    )

    def test_no_unfinished_markers(self) -> None:
        for path in sorted(FOLDER.glob("*.md")):
            text = read(path)
            for token in ("TODO", "TBD", "FIXME", "XXX"):
                with self.subTest(file=path.name, token=token):
                    self.assertNotIn(token, text)

    def test_agents_docs_map_lists_the_folder(self) -> None:
        self.assertIn(
            "docs/compliance/",
            read(REPO / "AGENTS.md"),
            "AGENTS.md docs map must list docs/compliance/",
        )


if __name__ == "__main__":
    unittest.main()
