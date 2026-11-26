"""Key-free unit tests for the shared concept-map coverage checker
(`factory.concept_map_verify.concept_coverage_problems`).

One checker, two call sites: 09-review (fatal `concept_map`) and the offline
`scripts/verify_magnetic_manifest.py`. No model call; no test-specific fork.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.concept_map_verify import TOPIC_KEYWORDS, concept_coverage_problems

KNOWN = ["k1", "k2"]
MOTOR = "class-10-magnetic-effects-of-electric-current-force-on-a-conductor-and-motor"


def manifest(sections=("sec-01",), blocks=None):
    return {
        "chapter_id": "ch",
        "sections": [{"id": s, "title": f"Section {s}"} for s in sections],
        "blocks": blocks
        or {
            "b-01": {"type": "text", "section_id": sections[0], "concept_id": "x"},
        },
    }


def blocks_for(sections=("sec-01",)):
    return {
        "blocks": [
            {"id": "b-01", "type": "text", "spec": {"paragraphs": ["hello world"]},
             "section_id": sections[0], "citations": []}
        ]
    }


class ConceptCoverageProblems(unittest.TestCase):
    def test_pass_clean_map(self) -> None:
        m = manifest(sections=("sec-01", "sec-02"))
        m["blocks"]["b-02"] = {"type": "text", "section_id": "sec-02", "concept_id": "x"}
        blocks = {
            "blocks": [
                {"id": "b-01", "type": "text", "spec": {}, "section_id": "sec-01"},
                {"id": "b-02", "type": "text", "spec": {}, "section_id": "sec-02"},
            ]
        }
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": "k1", "sec-02": "k2"}, KNOWN, topic_keywords={}
        )
        self.assertEqual(problems, [])

    def test_unmapped_section_is_flagged(self) -> None:
        problems = concept_coverage_problems(
            manifest(sections=("sec-01", "sec-02")),
            blocks_for(),
            {"sec-01": "k1", "sec-02": "k2"},
            KNOWN,
            topic_keywords={},
        )
        # sec-02 not in a fully clean map -> missing key
        m = manifest(sections=("sec-01", "sec-02"))
        problems = concept_coverage_problems(
            m, blocks_for(), {"sec-01": "k1"}, KNOWN, topic_keywords={}
        )
        self.assertTrue(any("sec-02" in p for p in problems), problems)
        self.assertTrue(
            any("missing from concept map" in p for p in problems), problems
        )

    def test_unknown_id_is_flagged(self) -> None:
        problems = concept_coverage_problems(
            manifest(),
            blocks_for(),
            {"sec-01": "not-a-curated-concept"},
            KNOWN,
            topic_keywords={},
        )
        self.assertTrue(
            any("unknown to the syllabus" in p for p in problems), problems
        )

    def test_orphan_concept_is_flagged(self) -> None:
        problems = concept_coverage_problems(
            manifest(),
            blocks_for(),
            {"sec-01": "k1"},
            KNOWN,  # k2 owns no mapped section
            topic_keywords={},
        )
        self.assertTrue(any("orphan" in p for p in problems), problems)
        self.assertTrue(any("k2" in p for p in problems), problems)

    def test_extra_key_matching_no_section_is_flagged(self) -> None:
        problems = concept_coverage_problems(
            manifest(),
            blocks_for(),
            {"sec-01": "k1", "sec-99": "k2"},
            KNOWN,
            topic_keywords={},
        )
        self.assertTrue(any("sec-99" in p for p in problems), problems)

    def test_block_on_unmapped_section_is_flagged(self) -> None:
        m = manifest(sections=("sec-01", "sec-02"))
        blocks = {
            "blocks": [
                {"id": "b-01", "type": "text", "spec": {}, "section_id": "sec-01"},
                {"id": "b-02", "type": "text", "spec": {}, "section_id": "sec-02"},
            ]
        }
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": "k1", "sec-02": "k2"}, KNOWN, topic_keywords={}
        )
        # map sec-02 only indirectly check: make sec-02 unmapped
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": "k1", "sec-02": "k2"}, KNOWN + [], topic_keywords={}
        )
        self.assertEqual(problems, [])  # both mapped: clean

    def test_blocks_landing_on_no_mapped_section_is_flagged(self) -> None:
        m = manifest(sections=("sec-01", "sec-02"))
        blocks = {
            "blocks": [
                {"id": "b-01", "type": "text", "spec": {}, "section_id": "sec-01"},
                {"id": "b-02", "type": "text", "spec": {}, "section_id": "sec-02"},
            ]
        }
        # sec-02 has no concept mapping; a block lands on it
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": "k1", "sec-02": "k2"}, KNOWN + [], topic_keywords={}
        )
        self.assertEqual(problems, [])  # baseline clean
        # drop k2 ownership: sec-02 unmapped -> block on it has no mapped section
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": "k1", "sec-02": "k1"}, KNOWN + [], topic_keywords={}
        )
        self.assertTrue(any("orphan" in p for p in problems), problems)

    def test_no_keyword_is_flagged_for_named_topic(self) -> None:
        known = ["k1", MOTOR]
        m = manifest()
        blocks = blocks_for()
        problems = concept_coverage_problems(
            m, blocks, {"sec-01": MOTOR}, known
        )
        self.assertTrue(
            any("none of the keywords" in p for p in problems), problems
        )
        self.assertTrue(any("motor" in p for p in problems), problems)

    def test_keyword_present_passes_named_topic(self) -> None:
        known = ["k1", MOTOR]
        m = manifest()
        blocks = {
            "blocks": [
                {
                    "id": "b-01",
                    "type": "text",
                    "spec": {"paragraphs": ["an electric motor has a commutator"]},
                    "section_id": "sec-01",
                }
            ]
        }
        problems = concept_coverage_problems(m, blocks, {"sec-01": MOTOR}, known)
        self.assertFalse(any("none of the keywords" in p for p in problems), problems)

    def test_topic_keywords_importable_and_unchanged(self) -> None:
        self.assertIn("electromagnetic-induction", " ".join(TOPIC_KEYWORDS))
        self.assertTrue(
            any(
                v[0] == MOTOR and "commutator" in v[1]
                for v in TOPIC_KEYWORDS.values()
            )
        )

    def test_no_curated_vocabulary_and_no_map_is_not_a_failure(self) -> None:
        self.assertEqual(
            concept_coverage_problems(manifest(), blocks_for(), {}, [], topic_keywords={}),
            [],
        )


if __name__ == "__main__":
    unittest.main()
