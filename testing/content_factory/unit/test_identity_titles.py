"""Chapter-title resolution: the "Grade" defect class (P1, 2026-11-16).

NCERT PDFs put page furniture in the same text layer as the chapter opener -
running headers ("Curiosity - Textbook of Science for Grade 8"), chapter
markers ("CHAPTER FOUR"), sidebar content and letter-spaced display type. One
published page carried ``chapter.title = "Grade"`` because the title picker
took the first title-shaped fragment it saw.

These tests pin the rules on synthetic page text (hermetic, no PDF cache):
a wrapped opener title is reconstructed, a drop-cap opener is reconstructed,
furniture and prose never become a title, and the locator's fallback title is
the opener title rather than a fragment.
"""

import unittest

from factory import identity
from factory.locate import _opener_title, _title_candidates


def page(*lines, number=1):
    return {"page": number, "text": "\n".join(lines)}


class TestOpenerTitle(unittest.TestCase):
    def test_a_wrapped_title_is_rejoined(self):
        # NCERT science-9 ch04 prints the title over two display lines.
        pages = [
            page(
                "Describing Motion",
                "Around Us",
                "Chapter",
                "4",
                "Everything in nature is in motion, from massive astronomical",
            )
        ]
        self.assertEqual(_opener_title(pages), "Describing Motion Around Us")

    def test_a_drop_cap_opener_is_reconstructed(self):
        # NCERT physics-11 openers split every word with a display drop cap.
        pages = [
            page(
                "C",
                "HAPTER",
                "F",
                "OUR",
                "L",
                "AWS OF",
                "M",
                "OTION",
                "4.1 INTRODUCTION",
                "In the preceding Chapter, our concern was to describe the",
            )
        ]
        self.assertEqual(_opener_title(pages), "LAWS OF MOTION")

    def test_a_running_header_is_not_the_title(self):
        pages = [
            page(
                "8",
                "Curiosity — Textbook of Science for Grade 8",
                "2",
                "The Invisible Living",
                "World: Beyond Our",
                "Naked Eye",
                "z Have you ever wondered what you might see?",
            )
        ]
        self.assertEqual(
            _opener_title(pages),
            "The Invisible Living World: Beyond Our Naked Eye",
        )

    def test_letter_spaced_display_type_falls_through(self):
        # "The Wonderful World of Science" then the letter-spaced "Chapter"
        # fragments must not be glued onto the title.
        pages = [
            page(
                "The Wonderful World of Science",
                "1",
                "C",
                "h",
                "a",
                "p t",
                "e",
                "r",
                "As human beings, we have always been curious about our",
            )
        ]
        self.assertEqual(_opener_title(pages), "The Wonderful World of Science")

    def test_prose_at_the_top_is_not_a_title(self):
        pages = [
            page(
                "Immersion into social media is spurring rise in loneliness",
                "and comparison among young people.",
            )
        ]
        self.assertIsNone(_opener_title(pages))


class TestTitleCandidates(unittest.TestCase):
    def test_the_opener_title_outranks_fragments(self):
        pages = [
            page(
                "Describing Motion",
                "Around Us",
                "Chapter",
                "4",
                "Everything in nature is in motion, from massive astronomical",
                "objects to subatomic particles.",
                "Think It Over",
                "Grade 6",
                "Curiosity",
                "Chapter 5",
                "Grade 7",
                "Curiosity",
                "Chapter 8",
                "Chapter-04.indd 48 Chapter-04.indd 48 28-04-2026 15:15:25",
            )
        ]
        candidates = _title_candidates(pages)
        self.assertEqual(candidates[0], "Describing Motion Around Us")
        for junk in ("Grade 7", "Grade 6", "Curiosity"):
            self.assertNotIn(junk, candidates)

    def test_a_chapter_marker_follower_must_be_title_shaped(self):
        pages = [
            page(
                "SOME CHAPTER", "CHAPTER TEN", "Sound is an everyday sensory experience"
            )
        ]
        self.assertNotIn(
            "Sound is an everyday sensory experience", _title_candidates(pages)
        )

    def test_section_numbers_are_not_chapter_titles(self):
        pages = [
            page(
                "6.1 I",
                "NTRODUCTION",
                "Electricity and magnetism were considered separate and unrelated",
            )
        ]
        self.assertEqual(_title_candidates(pages), [])


class TestRepairChapterTitle(unittest.TestCase):
    def test_furniture_is_replaced_by_the_operator_query(self):
        self.assertEqual(
            identity.repair_chapter_title(
                "Grade", matched_line=None, query="Describing Motion Around Us"
            ),
            "Describing Motion Around Us",
        )

    def test_a_real_title_is_kept_verbatim(self):
        self.assertEqual(
            identity.repair_chapter_title("LAWS OF MOTION"), "LAWS OF MOTION"
        )

    def test_nothing_usable_means_no_title(self):
        self.assertIsNone(
            identity.repair_chapter_title("Grade", matched_line="Grade 9", query=None)
        )


if __name__ == "__main__":
    unittest.main()
