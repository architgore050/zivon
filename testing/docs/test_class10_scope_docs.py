"""Docs contract tests for the Class 10-only prototype scope (founder decision,
2026-11-19) and the campaign record `docs/content-factory/class-10-campaign.md`.

Deterministic, key-free checks that:

1. `AGENTS.md` and `TIMELINE.md` carry the dated 2026-11-19 status block that records
   the one-class prototype scope (the four NCERT Physics chapters) and the current
   wave status, and that the older multi-class prototype scope is marked superseded
   in place without being rewritten.
2. `README.md` states the one-class scope and points at the campaign record.
3. The campaign record pins the four chapter ids, the local-only generation rule, the
   per-chapter gates, and the exact environment-variable names — with no secret or
   clearance values.
4. Every relative link in the campaign record resolves.

These are contract assertions, not copy-editing checks: wording may change freely.
Update a test only when the underlying decision changes.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CAMPAIGN = REPO_ROOT / "docs" / "content-factory" / "class-10-campaign.md"

STATUS_BLOCK = re.compile(r"^## Status 2026-11-19 — startup track$", re.MULTILINE)
CHAPTER_IDS = (
    "class-10-light-reflection-and-refraction",
    "class-10-the-human-eye-and-the-colourful-world",
    "class-10-electricity",
    "class-10-magnetic-effects-of-electric-current",
)
ENV_NAMES = (
    "ZIVON_BASE_URL",
    "ZIVON_MODEL",
    "ZIVON_API_KEY",
    "ZIVON_NARRATION_ENABLED",
    "ZIVON_TIMBRE_API_KEY",
    "EXAM_CONTENT_MODE",
    "EXAM_VERBATIM_CLEARANCE_ID",
    "SERIES_EXACT_PYQ_ENABLED",
)
GATES = ("Translation gate", "Narration gate", "Assessment gate", "Series gate")
LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")
# An env assignment with a concrete value would be a secret/clearance leak; the
# doc must carry names only (the placeholder form `<...>` in a command is fine).
SECRET_VALUE_RE = re.compile(r"(?:API_KEY|CLEARANCE_ID)\s*=\s*[^<\s]")


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


class ScopeDecisionRecorded(unittest.TestCase):
    def test_dated_status_block_in_binding_docs(self) -> None:
        for name in ("AGENTS.md", "TIMELINE.md"):
            with self.subTest(file=name):
                text = read(name)
                self.assertRegex(text, STATUS_BLOCK)
                self.assertIn("one class only", text)
                self.assertIn("Class 10", text)
                self.assertIn("class-10-campaign.md", text)

    def test_multi_class_scope_marked_superseded_not_deleted(self) -> None:
        for name in ("AGENTS.md", "TIMELINE.md"):
            with self.subTest(file=name):
                text = read(name)
                self.assertIn("superseded", text)
                # The historical wording stays as written for the record.
                self.assertIn("Class 9/10", text)

    def test_wave_status_is_recorded(self) -> None:
        text = read("TIMELINE.md")
        for fact in ("F8 SWOT", "F10 admin", "PL1", "PL2", "PL3", "PL4", "PL5", "F11"):
            with self.subTest(fact=fact):
                self.assertIn(fact, text)

    def test_readme_states_the_one_class_scope(self) -> None:
        text = read("README.md")
        self.assertIn("one class only", text)
        self.assertIn("class-10-campaign.md", text)

    def test_campaign_doc_is_listed_in_the_docs_map(self) -> None:
        self.assertIn("docs/content-factory/class-10-campaign.md", read("AGENTS.md"))


class CampaignRecord(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(CAMPAIGN.is_file(), "class-10-campaign.md is missing")
        self.text = CAMPAIGN.read_text(encoding="utf-8")

    def test_campaign_doc_is_substantive(self) -> None:
        self.assertGreater(len(self.text), 1_000, "too thin to be a contract")

    def test_four_chapter_ids_are_pinned(self) -> None:
        for chapter_id in CHAPTER_IDS:
            with self.subTest(chapter=chapter_id):
                self.assertIn(f"`{chapter_id}`", self.text)

    def test_local_only_rule_and_run_commands_are_stated(self) -> None:
        self.assertIn("local-only", self.text)
        self.assertIn("--class 10", self.text)
        self.assertIn("--locales hi,hi-Latn", self.text)
        self.assertIn("on the founder's local machine only", self.text)
        self.assertIn("No `k8s/20` factory Job", self.text)

    def test_per_chapter_gates_are_stated(self) -> None:
        for gate in GATES:
            with self.subTest(gate=gate):
                self.assertIn(gate, self.text)

    def test_env_names_present_without_values(self) -> None:
        for env in ENV_NAMES:
            with self.subTest(env=env):
                self.assertIn(f"`{env}`", self.text)
        self.assertIsNone(
            SECRET_VALUE_RE.search(self.text),
            "no secret or clearance values in the doc",
        )
        self.assertIn("never committed", self.text)

    def test_current_state_is_recorded(self) -> None:
        text = " ".join(self.text.split())
        self.assertIn("two generated, two pending", text)
        self.assertIn("The Human Eye is generated", text)

    def test_no_placeholders(self) -> None:
        hits = [m.group(0) for m in PLACEHOLDER_RE.finditer(self.text)]
        self.assertEqual(hits, [], "placeholders are not allowed: " + ", ".join(hits))


class Links(unittest.TestCase):
    def test_every_relative_link_resolves(self) -> None:
        failures: list[str] = []
        for match in LINK_RE.finditer(CAMPAIGN.read_text(encoding="utf-8")):
            target = match.group(1)
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative = target.split("#", 1)[0]
            if not relative:
                continue
            candidate = (CAMPAIGN.parent / relative).resolve()
            if not candidate.exists():
                failures.append(target)
        self.assertEqual(
            failures, [], "unresolved relative links: " + ", ".join(failures)
        )


if __name__ == "__main__":
    unittest.main()
