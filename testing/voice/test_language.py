"""Unit tests for voice.language (reply-language contract).

Covers the founder requirement of 2026-11-11: map Prisma's detected language
to product locales (``en`` / ``hi`` / ``hi-Latn``), resolve the precedence
(latest STT detection > session.start locale > default), and produce the
prompt line + Timbre language that follow it.
"""

from __future__ import annotations

import unittest

from voice.language import (
    DEFAULT_LOCALE,
    locale_label,
    locale_script,
    normalize_locale,
    reply_language_line,
    resolve_reply_locale,
    tts_language_for,
)


class NormalizeLocaleTest(unittest.TestCase):
    def test_hindi_variants(self) -> None:
        for raw in ("hi", "HI", "hi-IN", "hin", "hindi", "hi_IN"):
            self.assertEqual(normalize_locale(raw), "hi", raw)

    def test_english_variants(self) -> None:
        for raw in ("en", "en-IN", "eng", "english", "EN_in"):
            self.assertEqual(normalize_locale(raw), "en", raw)

    def test_hinglish_variants(self) -> None:
        for raw in ("hi-Latn", "hi-latn-in", "hi-en", "hinglish", "en-IN-hi"):
            self.assertEqual(normalize_locale(raw), "hi-Latn", raw)

    def test_unknown_is_empty_never_a_guess(self) -> None:
        for raw in ("", None, "ta", "auto", "indic-auto", "  "):
            self.assertEqual(normalize_locale(raw), "", str(raw))


class PrecedenceTest(unittest.TestCase):
    def test_latest_detection_beats_session_locale(self) -> None:
        self.assertEqual(
            resolve_reply_locale(detected="en-IN", session_locale="hi-Latn"),
            "en",
        )

    def test_session_locale_used_when_no_detection(self) -> None:
        self.assertEqual(resolve_reply_locale(detected="", session_locale="hi"), "hi")

    def test_default_when_both_missing(self) -> None:
        self.assertEqual(
            resolve_reply_locale(detected=None, session_locale=None), "hi-Latn"
        )

    def test_default_is_hinglish(self) -> None:
        self.assertEqual(DEFAULT_LOCALE, "hi-Latn")


class DisplayAndPromptTest(unittest.TestCase):
    def test_labels(self) -> None:
        self.assertEqual(locale_label("en"), "English")
        self.assertEqual(locale_label("hi"), "Hindi")
        self.assertEqual(locale_label("hi-Latn"), "Hinglish")

    def test_script_tags(self) -> None:
        self.assertEqual(locale_script("hi"), "Deva")
        self.assertEqual(locale_script("en"), "Latn")
        self.assertEqual(locale_script("hi-Latn"), "Latn")

    def test_reply_language_line_per_locale(self) -> None:
        en = reply_language_line("en")
        hi = reply_language_line("hi")
        hinglish = reply_language_line("hi-Latn")
        self.assertTrue(en.startswith("REPLY LANGUAGE: English — "))
        self.assertIn("answer in English", en)
        self.assertIn("answer in Hindi", hi)
        self.assertIn("Hinglish", hinglish)
        self.assertIn("same Hindi-English mix", hinglish)

    def test_unknown_locale_falls_back_to_default_line(self) -> None:
        self.assertEqual(reply_language_line("ta"), reply_language_line(DEFAULT_LOCALE))


class TtsLanguageTest(unittest.TestCase):
    def test_locale_to_timbre_codes(self) -> None:
        self.assertEqual(tts_language_for("en"), "en")
        self.assertEqual(tts_language_for("hi"), "hi")
        # Timbre's code-mix code is hi-en; there is no hi-Latn on the vendor.
        self.assertEqual(tts_language_for("hi-Latn"), "hi-en")

    def test_configured_default_is_kept(self) -> None:
        self.assertEqual(tts_language_for("hi-Latn", "auto"), "auto")
        self.assertEqual(tts_language_for("", "hi-en"), "hi-en")


if __name__ == "__main__":
    unittest.main()
