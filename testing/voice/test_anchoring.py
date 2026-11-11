"""Unit tests for voice.anchoring (spec.md §13 test table).

Covers: snapshot → bounded prompt context (≤ 600 chars); staleness; REF
unknown-id drop; the missing-snapshot F7 path; ADR-0014 validation rules.
"""

from __future__ import annotations

import unittest

from voice.anchoring import (
    ContextSnapshot,
    SnapshotError,
    build_prompt_context,
    parse_snapshot,
    resolve_refs,
    validate_ref_ids,
)
from voice.config import VoiceSettings

_PAYLOAD = {
    "topic_id": "motion",
    "class": "9",
    "chapter": "Motion",
    "block_id": "b-03",
    "block_type": "simulation",
    "sim_id": "zivon-sim-1",
    "sim_vars": {"v": "12", "t": "3"},
    "scroll_pct": 40,
    "lang_pref": "hi-en",
    "ts": 1000.0,
    "block_title": "Velocity-time graph",
    "block_text": "The graph shows uniform acceleration.",
    "visible_blocks": [
        {"id": "b-01", "type": "text", "title": "Intro"},
        {"id": "b-03", "type": "simulation", "title": "Graph sim"},
    ],
}


class ParseSnapshotTest(unittest.TestCase):
    def test_valid_payload_parses(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(snap.block_id, "b-03")
        self.assertEqual(snap.block_list, ("b-01", "b-03"))
        self.assertEqual(snap.sim_vars, {"v": "12", "t": "3"})

    def test_missing_required_field_rejected(self) -> None:
        payload = {k: v for k, v in _PAYLOAD.items() if k != "block_id"}
        with self.assertRaises(SnapshotError):
            parse_snapshot(payload)

    def test_oversized_payload_rejected(self) -> None:
        payload = {**_PAYLOAD, "block_text": "x" * 5000}
        with self.assertRaises(SnapshotError):
            parse_snapshot(payload)

    def test_sim_vars_type_validation(self) -> None:
        with self.assertRaises(SnapshotError):
            parse_snapshot({**_PAYLOAD, "sim_vars": {"v": {"nested": 1}}})

    def test_non_numeric_scroll_and_ts_raise_snapshot_error(self) -> None:
        # int("abc") / float({...}) must not escape as bare ValueError: the
        # WS handler catches SnapshotError and keeps the last good snapshot.
        with self.assertRaises(SnapshotError):
            parse_snapshot({**_PAYLOAD, "scroll_pct": "abc"})
        with self.assertRaises(SnapshotError):
            parse_snapshot({**_PAYLOAD, "ts": {"nested": 1}})

    def test_adr0014_visible_blocks_wording(self) -> None:
        snap = parse_snapshot({**_PAYLOAD, "visible_blocks": ["x1", "x2"]})
        self.assertEqual(snap.block_list, ("x1", "x2"))


class PromptContextTest(unittest.TestCase):
    def test_bounded_context_includes_essentials(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        block = build_prompt_context(snap, VoiceSettings(), stale=False)
        self.assertIn("page: Motion · Class 9", block)
        self.assertIn("section the student is looking at: Velocity-time graph", block)
        self.assertIn("The graph shows uniform acceleration.", block)
        self.assertIn("v=12", block)
        self.assertIn("other parts visible on this page: Intro; Graph sim", block)

    def test_prompt_context_has_no_machine_ids(self) -> None:
        # Founder requirement 2026-11-11: the model never sees b-NN /
        # block_id / block_type — only human-readable content.
        snap = parse_snapshot(_PAYLOAD)
        block = build_prompt_context(snap, VoiceSettings(), stale=False)
        self.assertNotIn("b-03", block)
        self.assertNotIn("b-01", block)
        self.assertNotIn("block_id", block)
        self.assertNotIn("block_type", block)
        self.assertNotIn("topic_id", block)
        self.assertNotRegex(block, r"\bb-\d+\b")

    def test_unknown_block_type_never_echoed_raw(self) -> None:
        snap = parse_snapshot({**_PAYLOAD, "block_type": "vendor_magic_type"})
        block = build_prompt_context(snap, VoiceSettings(), stale=False)
        self.assertNotIn("vendor_magic_type", block)

    def test_context_without_text_or_title_never_emits_an_id(self) -> None:
        snap = parse_snapshot(
            {
                **_PAYLOAD,
                "block_text": "",
                "block_title": "",
                "visible_blocks": ["b-01"],
            }
        )
        block = build_prompt_context(snap, VoiceSettings(), stale=False)
        self.assertIn("the part of the page the student is currently reading", block)
        self.assertNotIn("b-03", block)

    def test_block_text_capped_at_600_chars(self) -> None:
        snap = parse_snapshot({**_PAYLOAD, "block_text": "w" * 900})
        block = build_prompt_context(snap, VoiceSettings(), stale=False)
        text_line = next(
            line
            for line in block.splitlines()
            if line.startswith("what is on screen now (")
        )
        prefix = text_line.split(": ", 1)[0] + ": "
        self.assertLessEqual(len(text_line) - len(prefix), 600)

    def test_stale_snapshot_carries_honest_note(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        block = build_prompt_context(snap, VoiceSettings(), stale=True)
        self.assertIn("stale", block)
        self.assertIn("cannot see the page", block)

    def test_missing_snapshot_is_empty_f7_path(self) -> None:
        block = build_prompt_context(None, VoiceSettings(), stale=True)
        self.assertEqual(block, "")  # caller adds the honest note, no fake anchor


class RefValidationTest(unittest.TestCase):
    def test_valid_ids_pass(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(validate_ref_ids(("b-01", "b-03"), snap), ("b-01", "b-03"))

    def test_human_part_names_resolve_to_ids(self) -> None:
        # The prompt asks for names; the page JS still receives ids.
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(
            validate_ref_ids(("Velocity-time graph", "Intro"), snap),
            ("b-03", "b-01"),
        )

    def test_name_matching_is_case_insensitive(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(
            resolve_refs(("  velocity-time GRAPH  ",), snap), ("b-03",)
        )

    def test_unknown_ids_dropped(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(validate_ref_ids(("b-03", "b-99", "made-up"), snap), ("b-03",))

    def test_no_snapshot_no_highlight_never_error(self) -> None:
        self.assertEqual(validate_ref_ids(("b-01",), None), ())

    def test_empty_ref_no_highlight(self) -> None:
        snap = parse_snapshot(_PAYLOAD)
        self.assertEqual(validate_ref_ids((), snap), ())

    def test_snapshot_defaults_to_current_block_list(self) -> None:
        snap = ContextSnapshot(
            topic_id="t", class_name="9", chapter="c", block_id="b-2", block_type="text"
        )
        self.assertEqual(validate_ref_ids(("b-2", "b-x"), snap), ("b-2",))


if __name__ == "__main__":
    unittest.main()
