"""Tests for speakable-block selection (gap-register GAP-015 mini-spec).

Every rule below is the contract EX8 implements; the tests pin the contract,
not the implementation.
"""

from __future__ import annotations

import unittest

from factory.narration.select import (
    PAUSE_TAG,
    NarrationUnit,
    speakable_units,
    spoken_text,
)


def _lesson() -> dict:
    return {
        "title": "Motion in a Straight Line",
        "objectives": ["Describe displacement", "Distinguish speed and velocity"],
        "glossary": [{"term": "displacement", "definition": "change of position"}],
    }


def _blocks(*blocks: dict) -> dict:
    return {"blocks": list(blocks)}


def _block(bid: str, btype: str, spec: dict) -> dict:
    return {"id": bid, "type": btype, "spec": spec, "citations": []}


class TestMetaUnit(unittest.TestCase):
    def test_title_and_objectives_are_speakable(self):
        units = speakable_units(_lesson(), _blocks())
        self.assertEqual([u.block_id for u in units], ["b-00-meta"])
        self.assertEqual(units[0].kind, "meta")
        self.assertEqual(units[0].parts[0], "Motion in a Straight Line")
        self.assertIn("Describe displacement", units[0].parts)
        self.assertNotIn("change of position", units[0].parts)  # glossary excluded


class TestTextBlocks(unittest.TestCase):
    def test_full_prose_every_paragraph(self):
        blocks = _blocks(
            _block(
                "b-01",
                "text",
                {
                    "paragraphs": [
                        "Speed is distance by time.",
                        "Velocity has direction.",
                    ]
                },
            )
        )
        units = speakable_units(_lesson(), blocks)
        self.assertEqual(units[1].block_id, "b-01")
        self.assertEqual(
            units[1].parts, ("Speed is distance by time.", "Velocity has direction.")
        )

    def test_empty_prose_is_not_speakable(self):
        blocks = _blocks(_block("b-01", "text", {"paragraphs": []}))
        units = speakable_units(_lesson(), blocks)
        self.assertEqual([u.block_id for u in units], ["b-00-meta"])


class TestWorkedExample(unittest.TestCase):
    def test_problem_steps_and_answer_speakable(self):
        spec = {
            "problem": "A car covers 100 m in 20 s. Find the speed.",
            "steps": [
                {
                    "title": "Recall the definition",
                    "detail": "Speed is distance by time.",
                },
                {"title": "Substitute", "detail": "100 m / 20 s = 5 m/s."},
            ],
            "answer": "5 m/s",
        }
        units = speakable_units(
            _lesson(), _blocks(_block("b-02", "worked_example", spec))
        )
        parts = units[1].parts
        self.assertEqual(parts[0], "Worked example")
        self.assertIn("A car covers 100 m in 20 s. Find the speed.", parts)
        self.assertIn("Substitute", parts)
        self.assertIn("The answer is: 5 m/s", parts)


class TestCheckBlocks(unittest.TestCase):
    def test_question_and_options_only_never_the_answer(self):
        spec = {
            "question": "Which quantity has direction?",
            "format": "mcq",
            "options": ["Speed", "Velocity"],
            "answer_index": 1,
            "answer": "Velocity",
            "explanation": "Velocity is a vector.",
            "expected_understanding": "vectors vs scalars",
        }
        units = speakable_units(_lesson(), _blocks(_block("b-03", "check", spec)))
        spoken = " ".join(units[1].parts)
        self.assertIn("Which quantity has direction?", spoken)
        self.assertIn("Speed", spoken)
        self.assertIn("Velocity", spoken)
        self.assertNotIn("vector", spoken)  # explanation excluded
        self.assertNotIn(
            "vectors vs scalars", spoken
        )  # expected_understanding excluded
        self.assertNotIn("The answer is", spoken)

    def test_numeric_check_reads_only_the_question(self):
        spec = {
            "question": "How far in 10 s at 5 m/s?",
            "format": "numeric",
            "answer": "50",
        }
        units = speakable_units(_lesson(), _blocks(_block("b-04", "check", spec)))
        self.assertEqual(units[1].parts, ("How far in 10 s at 5 m/s?",))


class TestSimulationBlocks(unittest.TestCase):
    def test_title_description_and_readout_strings_never_js(self):
        spec = {
            "title": "Uniform motion",
            "description": "Drag the slider to change the speed.",
            "learning_goal": "see x = v t",  # excluded field
            "controls": [
                {
                    "id": "a",
                    "label": "speed m/s",
                    "min": 0,
                    "max": 5,
                    "step": 1,
                    "initial": 1,
                }
            ],
            "default_behaviour": "car moves",  # excluded field
        }
        interactive = {
            "b-05": {
                "files": {
                    "page.js": 'ctx.t_str("readout", "Position: {0} metres");\nvar code = "never spoken";'
                }
            }
        }
        units = speakable_units(
            _lesson(), _blocks(_block("b-05", "simulation", spec)), interactive
        )
        spoken = " ".join(units[1].parts)
        self.assertIn("Uniform motion", spoken)
        self.assertIn("Drag the slider", spoken)
        self.assertIn("Position: {0} metres", spoken)
        self.assertNotIn("never spoken", spoken)
        self.assertNotIn("see x = v t", spoken)
        self.assertNotIn("speed m/s", spoken)  # control labels excluded
        self.assertNotIn("car moves", spoken)

    def test_symbol_only_readouts_are_skipped(self):
        spec = {"title": "Sim", "description": "desc"}
        interactive = {
            "b-05": {
                "files": {
                    "page.js": 'ctx.t_str("u", "10 N"); ctx.t_str("v", "Distance covered");'
                }
            }
        }
        units = speakable_units(
            _lesson(), _blocks(_block("b-05", "simulation", spec)), interactive
        )
        self.assertEqual(units[1].parts, ("Sim", "desc", "Distance covered"))

    def test_animation_type_treated_like_simulation(self):
        spec = {"title": "Wave", "description": "A wave travels."}
        units = speakable_units(_lesson(), _blocks(_block("b-06", "animation", spec)))
        self.assertEqual(units[1].kind, "animation")
        self.assertEqual(units[1].parts, ("Wave", "A wave travels."))


class TestDiagramBlocks(unittest.TestCase):
    def test_svg_texts_only_when_present(self):
        spec = {
            "svg": "<svg viewBox='0 0 10 10'><text>x</text></svg>",
            "caption": "A velocity-time graph",
            "svg_texts": [{"id": "t-0", "source": "Velocity increases steadily"}],
        }
        units = speakable_units(_lesson(), _blocks(_block("b-07", "diagram", spec)))
        self.assertEqual(units[1].parts, ("Velocity increases steadily",))

    def test_english_v1_diagram_without_svg_texts_is_not_speakable(self):
        spec = {"svg": "<svg></svg>", "caption": "caption is on-request only"}
        units = speakable_units(_lesson(), _blocks(_block("b-07", "diagram", spec)))
        self.assertEqual([u.block_id for u in units], ["b-00-meta"])


class TestRevealAndOrdering(unittest.TestCase):
    def test_reveal_is_not_speakable(self):
        spec = {"title": "Why?", "steps": [{"title": "s", "detail": "d"}]}
        units = speakable_units(_lesson(), _blocks(_block("b-08", "reveal", spec)))
        self.assertEqual([u.block_id for u in units], ["b-00-meta"])

    def test_page_order_is_preserved(self):
        blocks = _blocks(
            _block("b-01", "text", {"paragraphs": ["one"]}),
            _block("b-02", "reveal", {"title": "t", "steps": []}),
            _block(
                "b-03", "check", {"question": "q?", "format": "numeric", "answer": "1"}
            ),
        )
        units = speakable_units(_lesson(), blocks)
        self.assertEqual([u.block_id for u in units], ["b-00-meta", "b-01", "b-03"])


class TestSpokenForm(unittest.TestCase):
    def test_parts_joined_by_pause_tags(self):
        unit = NarrationUnit("b-01", "text", ("First paragraph.", "Second paragraph."))
        text = spoken_text(unit)
        self.assertEqual(text, f"First paragraph. {PAUSE_TAG} Second paragraph.")

    def test_unit_pronunciation_rules_apply(self):
        unit = NarrationUnit(
            "b-01", "text", ("The car moves at 5 m/s2.", "Water boils at 100 °C.")
        )
        text = spoken_text(unit)
        self.assertIn("5 metres per second squared", text)
        self.assertIn("100 degrees Celsius", text)
        self.assertNotIn("m/s2", text)
        self.assertNotIn("°C", text)

    def test_whitespace_is_collapsed(self):
        unit = NarrationUnit("b-01", "text", ("line one\ncontinued   here",))
        self.assertEqual(spoken_text(unit), "line one continued here")

    def test_chars_counts_tags_included(self):
        unit = NarrationUnit("b-01", "text", ("abc", "de"))
        self.assertEqual(unit.chars, len(spoken_text(unit)))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
