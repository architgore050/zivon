"""Unit tests for voice.chunker (spec.md §13 test table).

Covers ADR-0019: strong boundaries incl. ।/ amongst Latin-script Hinglish,
no-split guarantees (numbers/decimals/units/tags/REF/domains), max-chars
clause fallback, the 250 ms flush deadline (with a fake clock), markup
stripping, and the first-chunk fast path.
"""

from __future__ import annotations

import unittest

from voice.chunker import Chunk, SegmentIds, SentenceChunker


def _chunker(clock=None, **kw: object) -> SentenceChunker:
    ids = SegmentIds()
    kw.setdefault("kind", "speech")
    if clock is not None:
        return SentenceChunker(ids, clock=clock, **kw)  # type: ignore[arg-type]
    return SentenceChunker(ids, **kw)  # type: ignore[arg-type]


def _texts(chunks: list[Chunk]) -> list[str]:
    return [c.text for c in chunks]


class StrongBoundaryTest(unittest.TestCase):
    def test_devanagari_danda_boundary(self) -> None:
        c = _chunker()
        out = c.feed("गति एक अवधारणा है।")
        out += c.flush()
        self.assertEqual(_texts(out), ["गति एक अवधारणा है।"])

    def test_question_exclamation_boundaries(self) -> None:
        c = _chunker()
        out = c.feed("Kya hua? Bahut badhiya!")
        self.assertEqual(_texts(out), ["Kya hua?", "Bahut badhiya!"])

    def test_latin_hinglish_mixed_script(self) -> None:
        c = _chunker()
        out = c.feed("Newton ka law yaad hai?\nChalo dekhte hain.")
        self.assertEqual(_texts(out), ["Newton ka law yaad hai?", "Chalo dekhte hain."])

    def test_newline_is_boundary_never_spoken(self) -> None:
        c = _chunker()
        out = c.feed("Pehli line.\nDoosri line.")
        self.assertEqual(_texts(out), ["Pehli line.", "Doosri line."])

    def test_decimal_not_split(self) -> None:
        c = _chunker()
        out = c.feed("Speed was 3.06 metre per second.")
        self.assertEqual(_texts(out), ["Speed was 3.06 metre per second."])

    def test_thousands_separator_not_split_by_clause_rule(self) -> None:
        c = _chunker()
        out = c.feed("Mass 1,000 kg izzat se, samjhe?")
        self.assertEqual(_texts(out), ["Mass 1,000 kg izzat se, samjhe?"])

    def test_domain_and_abbreviation_not_split(self) -> None:
        c = _chunker()
        out = c.feed("NCERT pe zivon.ai/docs par dekho, i.e. wahi page.")
        joined = " ".join(_texts(out))
        self.assertIn("zivon.ai/docs", joined)  # domain+path never split
        self.assertIn("i.e.", joined)  # dotted abbreviation stays intact

    def test_abbreviation_pause_tradeoff_documented(self) -> None:
        # "… e.g. next" may pause after the abbreviation (module docstring);
        # the guarantee is that "e.g." itself is never torn apart.
        c = _chunker()
        out = c.feed("Yeh e.g. example hai.")
        self.assertIn("e.g.", " ".join(_texts(out)))

    def test_segment_ids_monotonic(self) -> None:
        c = _chunker()
        out = c.feed("Ek. Do. Teen.")
        self.assertEqual([ch.segment_id for ch in out], [1, 2, 3])


class NoSplitGuaranteeTest(unittest.TestCase):
    def test_timbre_tag_never_split(self) -> None:
        t = [0.0]
        c = _chunker(clock=lambda: t[0])
        out = c.feed("Yeh dekho <pauses> aur suno, bahut interesting hai iska answer")
        t[0] += 1.0  # blow the flush deadline
        out += c.feed(" aur phir hum check karenge.")
        joined = " ".join(_texts(out))
        self.assertIn("<pauses>", joined)
        for chunk in out:
            self.assertNotIn("<", chunk.text.replace("<pauses>", ""))

    def test_tag_not_flushed_midway_by_deadline(self) -> None:
        t = [0.0]
        c = _chunker(clock=lambda: t[0])
        c.feed("Ab hum <slow")
        t[0] += 0.4  # deadline fires while a tag is open
        out = c.feed("> bolte hain. Done.")
        joined = _texts(out)
        self.assertTrue(any("<slow" in text for text in joined))

    def test_ref_line_held_until_newline_then_dropped(self) -> None:
        c = _chunker()
        out = c.feed(
            "REF: b1, b2, b3 and some very long tail text without any boundary at all"
        )
        self.assertEqual(_texts(out), [])  # held, never clause-flushed mid-REF
        out += c.feed("\nAb asli jawab yahan hai.")
        self.assertEqual(_texts(out), ["Ab asli jawab yahan hai."])
        self.assertEqual(c.dropped_ref, 1)  # REF is harness data, never speech


class ClauseFallbackTest(unittest.TestCase):
    def test_long_sentence_flushes_at_clause_boundary(self) -> None:
        c = _chunker()
        long_text = (
            "Yeh bahut lamba vakya hai jisme koi strong boundary nahi aayega jaldi se"
            " kyunki vakya ko jaan boojh kar itna lamba rakha gaya hai, par clause boundary yahan hai"
        )
        self.assertGreater(len(long_text), 140)
        out = c.feed(long_text)
        out += c.flush()  # the post-boundary remainder has no more boundaries
        self.assertTrue(out, "clause fallback must fire beyond 140 chars")
        self.assertTrue(all(len(t) <= 141 for t in _texts(out)))
        self.assertEqual(
            "".join(_texts(out)).replace(" ", ""), long_text.replace(" ", "")
        )

    def test_clause_boundary_respects_min_chars(self) -> None:
        c = _chunker(max_sent_chars=25, min_flush_chars=6)
        out = c.feed("short, clause, boundaries, here but nothing strong yet at all ok")
        self.assertTrue(out)
        self.assertTrue(_texts(out)[0].endswith(","))


class FlushDeadlineTest(unittest.TestCase):
    def test_flush_deadline_fires_at_word_edge(self) -> None:
        t = [0.0]
        c = _chunker(clock=lambda: t[0])
        c.feed("Yeh ek lamba bina-boundary vakya hai jo chalu ho gaya tha pehle")
        self.assertEqual(c.feed(""), [])  # not yet past deadline
        t[0] += 0.3  # 300 ms > 250 ms deadline
        out = c.feed(" aur aage badh raha hai abhi bhi")
        self.assertTrue(out, "deadline flush must emit at a word edge")
        self.assertEqual(c.deadline_flushes, 1)
        first = out[0]
        self.assertGreaterEqual(len(first.text), 40)

    def test_first_chunk_fast_path_from_first_token(self) -> None:
        t = [0.0]
        c = _chunker(clock=lambda: t[0])
        c.feed("Pehla token")
        t[0] += 0.3
        c.feed(" aur phir bahut saare tokens aate hain yahan")
        # pending is ≥ 40 chars and past deadline → flush happened
        self.assertEqual(c.deadline_flushes, 1)

    def test_short_pending_survives_deadline(self) -> None:
        t = [0.0]
        c = _chunker(clock=lambda: t[0])
        c.feed("Chhota.")
        t[0] += 0.5
        out = c.feed("")
        self.assertEqual(_texts(out), [])  # < 40 chars: keep waiting for boundary


class MarkupStripTest(unittest.TestCase):
    def test_markdown_stripped_from_spoken_text(self) -> None:
        c = _chunker()
        out = c.feed("**Newton** ka #1 rule hai: `F = ma`.")
        self.assertEqual(_texts(out), ["Newton ka 1 rule hai: F = ma."])

    def test_latex_stripped_keep_inner(self) -> None:
        c = _chunker()
        out = c.feed("Formula $v = u + at$ hai, yaad rakho!")
        self.assertEqual(_texts(out), ["Formula v = u + at hai, yaad rakho!"])

    def test_code_fence_dropped_silently(self) -> None:
        c = _chunker()
        out = c.feed("```python\nx = 1\n```\nAb samjho.")
        self.assertEqual(_texts(out), ["Ab samjho."])
        self.assertGreaterEqual(c.dropped_empty, 1)  # fence residue dropped

    def test_open_fence_holds_flush_until_closed(self) -> None:
        c = _chunker()
        out = c.feed("Dekho:\n```py\nx = 1")  # fence still open
        self.assertEqual(_texts(out), ["Dekho:"])  # prose before fence spoke
        out += c.feed("\n```\n")
        self.assertEqual(_texts(out), ["Dekho:"])  # fence content never spoken

    def test_markdown_only_chunk_dropped(self) -> None:
        c = _chunker()
        out = c.feed("***")
        self.assertEqual(_texts(out), [])
        out += c.flush()
        self.assertEqual(_texts(out), [])
        self.assertEqual(c.dropped_empty, 1)

    def test_flush_empty_pending_is_noop(self) -> None:
        c = _chunker()
        self.assertEqual(c.flush(), [])


if __name__ == "__main__":
    unittest.main()
