"""Tests for factory.textops: title normalisation/exact matching, PDF text
cleaning, and deterministic chunking with overlap."""

from __future__ import annotations

import unittest
from itertools import pairwise

from factory.textops import (
    chunk_text,
    clean_pdf_text,
    normalize_title,
    titles_equivalent,
)


class TestNormalizeTitle(unittest.TestCase):
    def test_lowercases_and_strips_punctuation(self):
        self.assertEqual(
            normalize_title("Motion and Measurement of Distances"),
            "motionandmeasurementofdistances",
        )

    def test_drops_digits_kept_as_alphanumeric(self):
        # digits are alphanumeric: they survive normalisation
        self.assertEqual(normalize_title("Chapter 9: Motion"), "chapter9motion")

    def test_collapses_all_whitespace_and_symbols(self):
        self.assertEqual(normalize_title("  Force \t&-\n Pressure!  "), "forcepressure")

    def test_empty_and_punctuation_only(self):
        self.assertEqual(normalize_title(""), "")
        self.assertEqual(normalize_title(" *** --- "), "")


class TestTitlesEquivalent(unittest.TestCase):
    def test_exact_match_after_normalisation(self):
        self.assertTrue(titles_equivalent("Motion", "MOTION"))
        self.assertTrue(titles_equivalent("Motion", " motion "))

    def test_user_title_contained_in_document_title(self):
        self.assertTrue(
            titles_equivalent("Motion", "Motion and Measurement of Distances")
        )

    def test_reverse_containment_is_not_a_match(self):
        # the document title being inside the user's query must NOT count,
        # otherwise 'Motion and Measurement of Distances' would match 'Motion'
        self.assertFalse(
            titles_equivalent("Motion and Measurement of Distances", "Motion")
        )

    def test_unrelated_titles(self):
        self.assertFalse(titles_equivalent("Motion", "Gravitation"))

    def test_empty_side_never_matches(self):
        self.assertFalse(titles_equivalent("", "Motion"))
        self.assertFalse(titles_equivalent("Motion", ""))
        self.assertFalse(titles_equivalent("???", "Motion"))


class TestCleanPdfText(unittest.TestCase):
    def test_nbsp_becomes_space(self):
        self.assertEqual(clean_pdf_text("Motion\u00a0and\u00a0Rest"), "Motion and Rest")

    def test_runs_of_spaces_and_tabs_collapse(self):
        self.assertEqual(clean_pdf_text("a  b\t\t c"), "a b c")

    def test_three_or_more_newlines_collapse_to_paragraph_break(self):
        self.assertEqual(
            clean_pdf_text("para one\n\n\n\n\npara two"), "para one\n\npara two"
        )

    def test_single_newlines_are_preserved(self):
        self.assertEqual(clean_pdf_text("line one\nline two"), "line one\nline two")

    def test_outer_whitespace_stripped(self):
        self.assertEqual(clean_pdf_text("  \n text \n "), "text")

    def test_symbol_font_private_use_runs_decode_to_ascii(self):
        # NCERT physics-11 prelims arrive as U+F0XX runs (XX = ASCII code)
        garbled = (
            "\uf050\uf041\uf052\uf054 \uf049\n"
            "\uf054\uf045\uf058\uf054\uf042\uf04f\uf04f\uf04b \uf046\uf04f\uf052\n"
            "\uf020 \uf043\uf04c\uf041\uf053\uf053 \uf020 \uf058\uf049"
        )
        self.assertEqual(clean_pdf_text(garbled), "PART I\nTEXTBOOK FOR\n CLASS XI")

    def test_non_printable_private_use_glyphs_are_dropped(self):
        self.assertEqual(clean_pdf_text("\uf001ab\uf0ffcd"), "abcd")


class TestChunkText(unittest.TestCase):
    def test_empty_text_gives_no_chunks(self):
        self.assertEqual(chunk_text("", 100, 20), [])
        self.assertEqual(chunk_text("   ", 100, 20), [])

    def test_chunk_chars_must_exceed_overlap(self):
        with self.assertRaises(ValueError):
            chunk_text("abc", 10, 10)
        with self.assertRaises(ValueError):
            chunk_text("abc", 5, 10)

    def test_short_text_is_one_chunk(self):
        self.assertEqual(chunk_text("hello", 100, 20), ["hello"])

    def test_exact_fit_single_chunk_no_extra(self):
        self.assertEqual(chunk_text("a" * 10, 10, 3), ["a" * 10])

    def test_chunks_cover_all_text_in_order(self):
        text = "".join(chr(ord("A") + i % 26) for i in range(250))
        chunk_chars, overlap = 100, 20
        chunks = chunk_text(text, chunk_chars, overlap)
        self.assertGreater(len(chunks), 1)
        # precise invariant of this chunker: each chunk contributes its first
        # (chunk_chars - overlap) fresh characters, the last chunk the remainder
        step = chunk_chars - overlap
        rebuilt = "".join(c[:step] for c in chunks[:-1]) + chunks[-1]
        self.assertEqual(rebuilt, text)

    def test_overlap_shares_boundary_content(self):
        text = "0123456789" * 10  # 100 chars
        chunks = chunk_text(text, 40, 10)
        self.assertGreaterEqual(len(chunks), 3)
        # consecutive chunks share `overlap` characters
        for a, b in pairwise(chunks):
            self.assertTrue(text.find(a) <= text.find(b))
            tail = a[-10:]
            self.assertEqual(tail, b[:10])


if __name__ == "__main__":
    unittest.main()
