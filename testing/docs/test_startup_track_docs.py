"""Contract tests for the startup-track reframe (W0, 2026-11-15).

The reframe is docs-only, so these tests pin the few claims other agents and tools
depend on, without pinning prose:

1. `AGENTS.md` and `TIMELINE.md` carry a dated startup-track status banner, and the
   README says the project is on the startup track.
2. The challenge record is still present in `TIMELINE.md` and clearly marked
   historical (the 10 Nov 2026 deadline, the decision gates, the infra TODO).
3. `AGENTS.md` carries the current model-routing table with the four decided
   surfaces (tutor / voice / content generation / translation).
4. `AGENTS.md` lists `docs/compliance/` in the docs map, and the README points at
   the compliance work and the frozen full-frontend plan.

These are contract assertions, not copy-editing checks: wording, wrapping, and
section order may change freely. Update a test only when the underlying decision
changes (e.g. a founder decision changes a model in the routing table).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path
from typing import ClassVar

REPO_ROOT = Path(__file__).resolve().parents[2]

STATUS_BANNER = re.compile(
    r"^## Status \d{4}-\d{2}-\d{2} — startup track$", re.MULTILINE
)


def read(name: str) -> str:
    return (REPO_ROOT / name).read_text(encoding="utf-8")


def section(text: str, heading_prefix: str) -> str:
    """Return the text of the `##` section whose heading starts with the prefix."""
    match = re.search(rf"^## {re.escape(heading_prefix)}.*$", text, re.MULTILINE)
    if match is None:
        raise AssertionError(f"section not found: {heading_prefix!r}")
    rest = text[match.end() :]
    next_heading = re.search(r"^## ", rest, re.MULTILINE)
    return rest[: next_heading.start()] if next_heading else rest


def markdown_table(block: str) -> list[dict[str, str]]:
    """Parse the first pipe table in `block` into row dicts keyed by header cell."""
    lines = [
        line.strip() for line in block.splitlines() if line.strip().startswith("|")
    ]
    if len(lines) < 3:
        raise AssertionError("expected a markdown table with a header and >=1 row")
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines]
    header = rows[0]
    return [dict(zip(header, row, strict=False)) for row in rows[2:]]


class TestStatusBanner(unittest.TestCase):
    def test_agents_and_timeline_carry_a_dated_startup_status(self) -> None:
        for name in ("AGENTS.md", "TIMELINE.md"):
            with self.subTest(file=name):
                text = read(name)
                self.assertRegex(text, STATUS_BANNER)
                self.assertIn("startup track", text)

    def test_readme_states_the_startup_track(self) -> None:
        text = read("README.md")
        self.assertIn("post-challenge startup track", text)
        self.assertIn("product-market-fit testing", text)
        # The old hard deadline must not be presented as current.
        self.assertNotIn("Deadline: **10 November 2026", text)


class TestChallengeHistoryPreserved(unittest.TestCase):
    def test_timeline_keeps_the_historical_challenge_plan(self) -> None:
        text = read("TIMELINE.md")
        self.assertIn("## Reality Snapshot (challenge track — historical)", text)
        self.assertIn("Tue 10 Nov 2026, 11:59 PM IST", text)
        self.assertIn("Hard deadline (historical — closed 2026-11-15)", text)
        self.assertIn("## Decision Gates", text)
        # The infra TODO stays live working state, so it must not be deleted.
        self.assertIn("## Infra & Deployment TODO", text)

    def test_agents_has_a_marked_history_section(self) -> None:
        text = read("AGENTS.md")
        history = section(text, "History — the challenge track")
        self.assertIn("Great Indian AI Internship Challenge", history)
        self.assertIn("Gate A outcome", history)


class TestModelRoutingTable(unittest.TestCase):
    REQUIRED: ClassVar[dict[str, tuple[str, ...]]] = {
        "Student-facing tutor": ("Gemma 4 26B A4B", "Gemini API"),
        "Voice STT / TTS": ("Prisma v3.0", "Timbre v3.0"),
        "Internal content generation": ("DeepSeek V4.1 Flash", "OpenCode"),
        "Translation": ("Evon",),
    }

    def test_four_surfaces_are_routed(self) -> None:
        block = section(read("AGENTS.md"), "Current stack — model routing")
        rows = {
            row.get("Surface", ""): " ".join(
                value for key, value in row.items() if key != "Surface"
            )
            for row in markdown_table(block)
        }
        for surface, expected in self.REQUIRED.items():
            with self.subTest(surface=surface):
                self.assertIn(surface, rows)
                for token in expected:
                    self.assertIn(token, rows[surface])

    def test_routing_is_marked_revisable(self) -> None:
        block = section(read("AGENTS.md"), "Current stack — model routing")
        self.assertIn("not mandates", block)
        self.assertIn("founder", block.lower())


class TestDocsMapPointers(unittest.TestCase):
    def test_agents_docs_map_lists_compliance(self) -> None:
        text = read("AGENTS.md")
        self.assertRegex(text, r"(?m)^- `docs/compliance/` — ")
        self.assertIn("feature flag", section(text, "Documentation"))

    def test_readme_points_at_compliance_and_the_frozen_plan(self) -> None:
        text = read("README.md")
        self.assertIn("docs/compliance/", text)
        self.assertIn("FEATURE-MAP.md", text)
        self.assertIn("REQUIREMENTS.md", text)


if __name__ == "__main__":
    unittest.main()
