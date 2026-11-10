"""Tests for the EX8 narration upgrade: equation verbalization, the Timbre
v3.0 tag whitelist + caps, and OpenRouter-key reuse (no new secret var).

The verbalization is deterministic (select.py is pure — no I/O, no model
calls), so these tests need no environment and no network.
"""

from __future__ import annotations

import itertools
import os
import unittest
from pathlib import Path

from factory.narration.select import (
    ALLOWED_TAGS,
    EXCITED_TAG,
    MAX_TAGS_PER_UNIT,
    PAUSE_TAG,
    SENTENCES_PER_TAG,
    SLOW_TAG,
    TIMBRE_V3_TAGS,
    WHISPERS_TAG,
    NarrationUnit,
    spoken_text,
    strip_non_whitelisted_tags,
)

_REPO = Path(__file__).resolve().parents[2]


def _unit(*parts: str, block_id: str = "b-01", kind: str = "text") -> NarrationUnit:
    return NarrationUnit(block_id, kind, tuple(parts))


def _tags(text: str) -> list[str]:
    return [token for token in text.split() if token.startswith("<")]


class TestEquationVerbalization(unittest.TestCase):
    def test_ascii_super_and_plus(self):
        self.assertEqual(spoken_text(_unit("x^2 + 1")), "x squared plus 1")

    def test_braced_super_and_equals(self):
        self.assertEqual(spoken_text(_unit("v = u + at")), "v equals u plus at")

    def test_braced_power_three(self):
        self.assertEqual(spoken_text(_unit("x^{3}")), "x cubed")

    def test_general_power(self):
        self.assertEqual(spoken_text(_unit("x^n")), "x to the power of n")

    def test_subscripts(self):
        text = spoken_text(_unit("x_1 + x_{2}"))
        self.assertIn("x sub 1", text)
        self.assertIn("x sub 2", text)

    def test_unicode_superscript(self):
        text = spoken_text(_unit("v = x²"))
        self.assertIn("x squared", text)
        self.assertNotIn("²", text)

    def test_unicode_subscript(self):
        text = spoken_text(_unit("x₁"))
        self.assertIn("x sub 1", text)
        self.assertNotIn("₁", text)

    def test_unit_survives_generic_slash(self):
        # "3.06 metres per second squared" (SP1 Appendix A example shape):
        # the unit table must win over generic "/" and the "^" handler.
        text = spoken_text(_unit("v = 3.06 m/s2"))
        self.assertIn("3.06 metres per second squared", text)
        self.assertNotIn("/", text)
        self.assertNotIn("^", text)

    def test_unicode_unit_survives(self):
        text = spoken_text(_unit("v = 3.06 m/s²"))
        self.assertIn("3.06 metres per second squared", text)

    def test_integral_differential(self):
        text = spoken_text(_unit("∫ v dt"))
        self.assertEqual(text, "the integral of v with respect to time")

    def test_integral_of_velocity_example(self):
        text = spoken_text(_unit("∫ v dt is the integral of velocity"))
        self.assertIn("the integral of v with respect to time", text)
        self.assertIn("integral of velocity", text)

    def test_unicode_symbols(self):
        cases = {
            "×": "times",
            "±": "plus or minus",
            "≈": "is approximately",
            "→": "leads to",
            "∈": "is an element of",
            "√": "the square root of",
            "π": "pi",
            "θ": "theta",
            "λ": "lambda",
            "Δ": "delta",
            "≤": "is less than or equal to",
            "≠": "is not equal to",
            "∞": "infinity",
        }
        for symbol, spoken in cases.items():
            with self.subTest(symbol=symbol):
                text = spoken_text(_unit(f"a {symbol} b"))
                self.assertIn(spoken, text)
                self.assertNotIn(symbol, text)

    def test_latex_frac_sqrt(self):
        text = spoken_text(_unit("$x = \\frac{1}{2}$"))
        self.assertIn("1 divided by 2", text)
        self.assertNotIn("$", text)
        text = spoken_text(_unit("$\\sqrt{4}$"))
        self.assertIn("the square root of 4", text)
        self.assertNotIn("\\", text)

    def test_latex_greek_and_int(self):
        self.assertIn("theta", spoken_text(_unit("$\\theta$")))
        self.assertIn("the integral of", spoken_text(_unit("$\\int v dt$")))

    def test_percent_and_spaced_division(self):
        text = spoken_text(_unit("50% efficiency"))
        self.assertIn("50 percent", text)
        text = spoken_text(_unit("100 m / 20 s = 5 m/s"))
        self.assertIn("100 m divided by 20 s", text)
        self.assertIn("equals", text)
        self.assertIn("5 metres per second", text)

    def test_minus_does_not_eat_prose_hyphens(self):
        text = spoken_text(_unit("a well-known x-axis"))
        self.assertIn("well-known", text)
        self.assertIn("x-axis", text)
        text = spoken_text(_unit("a - b"))
        self.assertIn("a minus b", text)
        text = spoken_text(_unit("a-b"))
        # Letter-letter hyphen is prose, never minus.
        self.assertIn("a-b", text)

    def test_numbers_stay_digits(self):
        text = spoken_text(_unit("3.06 m/s"))
        self.assertIn("3.06", text)

    def test_hindi_readout_untouched(self):
        text = spoken_text(_unit("दूरी बढ़ती है"))
        self.assertEqual(text, "दूरी बढ़ती है")

    def test_bare_degrees(self):
        text = spoken_text(_unit("90°"))
        self.assertEqual(text, "90 degrees")


class TestTagCatalogAndWhitelist(unittest.TestCase):
    def test_catalog_is_the_verified_13(self):
        self.assertEqual(len(TIMBRE_V3_TAGS), 13)
        for tag in (
            "<laugh>",
            "<giggle>",
            "<sigh>",
            "<exhales>",
            "<sniffles>",
            "<yawns>",
            "<coughs>",
            "<clears throat>",
            "<whispers>",
            "<shouting>",
            "<excited>",
            "<slow>",
            "<pauses>",
        ):
            self.assertIn(tag, TIMBRE_V3_TAGS)

    def test_allowed_subset_matches_sp1_appendix_a(self):
        self.assertEqual(
            set(ALLOWED_TAGS),
            {"<pauses>", "<slow>", "<excited>", "<whispers>"},
        )
        self.assertEqual(PAUSE_TAG, "<pauses>")
        self.assertEqual(SLOW_TAG, "<slow>")
        self.assertEqual(EXCITED_TAG, "<excited>")
        self.assertEqual(WHISPERS_TAG, "<whispers>")

    def test_source_tags_never_survive_verbatim(self):
        text = spoken_text(
            _unit("First thought.", "<laugh>Hello there.", "<banana>World.")
        )
        for tag in TIMBRE_V3_TAGS:
            if tag not in ALLOWED_TAGS:
                self.assertNotIn(tag, text)
        self.assertNotIn("<banana>", text)
        self.assertIn("Hello there.", text)
        self.assertIn("World.", text)
        self.assertLessEqual(len(_tags(text)), 8)

    def test_only_whitelisted_tags_emitted(self):
        parts = tuple(f"Sentence number {i} explains a step." for i in range(20))
        text = spoken_text(_unit(*parts))
        self.assertTrue(_tags(text))
        for tag in _tags(text):
            self.assertIn(tag, ALLOWED_TAGS)
        self.assertNotIn(WHISPERS_TAG, text)  # never auto-emitted

    def test_strip_helper_passes_whitelist_only(self):
        cleaned = strip_non_whitelisted_tags(
            "a <laugh> b <pauses> c <banana> d <whispers> e"
        )
        self.assertNotIn("<laugh>", cleaned)
        self.assertNotIn("<banana>", cleaned)
        self.assertIn("<pauses>", cleaned)
        self.assertIn("<whispers>", cleaned)


class TestTagCaps(unittest.TestCase):
    def test_two_sentences_allow_one_tag(self):
        text = spoken_text(_unit("First paragraph.", "Second paragraph."))
        self.assertEqual(text, f"First paragraph. {PAUSE_TAG} Second paragraph.")
        self.assertEqual(len(_tags(text)), 1)

    def test_single_sentence_allows_no_tag(self):
        text = spoken_text(_unit("Speed"))
        self.assertEqual(text, "Speed")
        self.assertEqual(_tags(text), [])

    def test_long_block_capped_at_eight(self):
        parts = tuple(f"Sentence number {i} explains a step." for i in range(20))
        text = spoken_text(_unit(*parts))
        self.assertLessEqual(len(_tags(text)), MAX_TAGS_PER_UNIT)
        self.assertEqual(len(_tags(text)), MAX_TAGS_PER_UNIT)

    def test_cap_rate_is_one_per_two_sentences(self):
        # 4 punctuated sentences -> at most 2 tags (parts are the sentences).
        text = spoken_text(_unit("One.", "Two.", "Three.", "Four.", "Five.", "Six."))
        self.assertLessEqual(len(_tags(text)), 6 // SENTENCES_PER_TAG)

    def test_at_most_one_cue_per_boundary(self):
        # No two tags adjacent (never "<pauses> <slow>" back to back).
        text = spoken_text(
            _unit("First step.", "Compute x^2 + 1 equals 2.", "The answer is: 2.")
        )
        tokens = text.split()
        for first, second in itertools.pairwise(tokens):
            if first.startswith("<"):
                self.assertFalse(second.startswith("<"))

    def test_slow_precedes_equation_part(self):
        text = spoken_text(
            _unit("First thought.", "Compute x^2 + 1.", "Second thought.")
        )
        self.assertIn(f"{SLOW_TAG} Compute", text)

    def test_excited_precedes_worked_example_answer(self):
        text = spoken_text(
            _unit("Step one.", "Step two.", "The answer is: 5 metres per second.")
        )
        self.assertIn(f"{EXCITED_TAG} The answer is:", text)

    def test_delivery_funded_before_pauses(self):
        # A worked-example-shaped unit: slow + excited must survive even
        # though early breathing pauses compete for the same budget.
        text = spoken_text(
            _unit(
                "Worked example",
                "A car covers 100 m in 20 s. Find the speed.",
                "Recall the definition",
                "Speed is distance by time.",
                "Substitute",
                "100 m / 20 s = 5 m/s.",
                "The answer is: 5 m/s",
            )
        )
        self.assertIn(f"{SLOW_TAG} 100", text)
        self.assertIn(f"{EXCITED_TAG} The answer is:", text)
        self.assertLessEqual(len(_tags(text)), 8)

    def test_chars_still_counts_tags(self):
        unit = _unit("First paragraph.", "Second paragraph.")
        self.assertEqual(unit.chars, len(spoken_text(unit)))


class TestTimbreHarnessStrip(unittest.TestCase):
    def test_live_client_strips_non_whitelisted_tags(self):
        import httpx

        from factory.narration.timbre import LiveTimbreClient
        from testing.narration.test_narration_timbre import _env

        captured: dict[str, bytes] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = request.read()
            return httpx.Response(200, content=b"a")

        LiveTimbreClient(_env(), transport=httpx.MockTransport(handler)).synthesize(
            "hi <laugh> there <pauses> x", "en-IN"
        )
        import json

        body = json.loads(captured["json"])
        self.assertNotIn("<laugh>", body["text"])
        self.assertIn("<pauses>", body["text"])


class TestOpenRouterKeyReuse(unittest.TestCase):
    """The upgrade adds NO OpenRouter call and NO new key variable.

    The factory's key path is ZIVON_API_KEY (factory/config.py,
    llm_manager/config.py) fed by K8s Secret zivon-factory-env, with the
    OpenRouter upstream carried as the llm-manager node's ZIVON_BASE_URL.
    Deterministic verbalization needs none of it.
    """

    def _narration_sources(self) -> str:
        folder = _REPO / "factory" / "narration"
        return "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(folder.glob("*.py"))
        )

    def test_no_second_key_variable(self):
        # No code-level read of a second (OpenRouter-specific) key variable.
        # Prose mentions (this docstring, the module docstring recording the
        # decision) are fine; a quoted env-var name is code.
        sources = self._narration_sources()
        self.assertNotIn('"OPENROUTER_API_KEY"', sources)
        self.assertNotIn("'OPENROUTER_API_KEY'", sources)
        self.assertNotIn('get("OPENROUTER', sources)
        self.assertNotIn("get('OPENROUTER", sources)

    def test_reuse_recorded(self):
        sources = self._narration_sources()
        self.assertIn("ZIVON_API_KEY", sources)
        self.assertIn("zivon-factory-env", sources)

    def test_no_secret_literals(self):
        sources = self._narration_sources()
        for token in (
            "sk-",
            "sk-or-",
            "AIza",
            "deadbeef",
        ):
            self.assertNotIn(token, sources)

    def test_verbalization_needs_no_environment(self):
        saved = {
            key: os.environ.pop(key, None)
            for key in ("ZIVON_API_KEY", "ZIVON_BASE_URL", "ZIVON_MODEL")
        }
        try:
            text = spoken_text(_unit("x^2 + 1", "Second sentence here."))
            self.assertIn("squared", text)
        finally:
            for key, value in saved.items():
                if value is not None:
                    os.environ[key] = value


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
