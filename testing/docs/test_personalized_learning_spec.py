"""Docs contract tests for docs/specs/personalized-learning/ (W5.5).

Deterministic, key-free checks that the spec folder stays a buildable contract:
every required file and section exists, every relative link resolves, every
open founder decision carries a recommendation/owner/status, the eval cards and
workstreams are present, the feature-addition decision log parses, and the
free-prototype rule (no paywall/payment/plan) cannot rot silently.

These are contract assertions, not copy-editing checks: wording may change.
Update a test only when the underlying decision changes.
"""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
FOLDER = REPO / "docs" / "specs" / "personalized-learning"

FILES = (
    "README.md",
    "feature-addendum.md",
    "spec.md",
    "agent-and-rag.md",
    "interactive-artifacts.md",
    "data-and-api.md",
    "security-privacy.md",
    "evals.md",
    "workstreams.md",
    "decisions.md",
)

REQUIRED_HEADINGS: dict[str, tuple[str, ...]] = {
    "README.md": (
        "## Scope",
        "## Non-goals",
        "## Actors and jobs",
        "## Read order",
        "## Dependencies on existing specs",
        "## Status and exit gate",
    ),
    "feature-addendum.md": (
        "## 2. Tension deltas",
        "## 3. Jobs and metrics added",
        "## 4. Feature cards",
        "## 5. Screens and regions",
        "## 6. UI element inventory",
        "## 7. Traceability check",
    ),
    "spec.md": (
        "## 1. Personal instructions",
        "## 2. Personalized learning",
        "## 3. Saved conversations",
        "## 4. Interactive artifacts",
        "## 5. Free prototype",
        "## 6. Screens",
        "## 7. States",
        "## 8. Failure modes",
        "## 9. Notices",
        "## 10. Accessibility",
    ),
    "agent-and-rag.md": (
        "## 2. Teaching state machine",
        "## 3. The turn protocol",
        "## 4. Prompt contract",
        "## 6. RAG contract",
        "## 7. Model routing",
        "## 8. Prompt-injection defense",
        "## 9. Eval hooks",
    ),
    "interactive-artifacts.md": (
        "## 2. Artifact request contract",
        "## 3. Generation pipeline",
        "## 4. Generated HTML contract",
        "## 5. Sandbox",
        "## 6. Review pipeline",
        "## 7. Cache, versioning, deletion",
        "## 8. Fallback",
        "## 9. Abuse controls",
        "## 10. Tests",
    ),
    "data-and-api.md": (
        "## 1. Data classes",
        "## 2. Tables",
        "## 3. Entities",
        "## 4. API contract",
        "## 5. Voice-tutor prompt assembly",
        "## 6. Test seams",
    ),
    "security-privacy.md": (
        "## 3. Threat model",
        "## 4. Detailed controls",
        "## 7. Deletion / retention matrix",
        "## 9. Compliance flags",
        "## 10. Test summary",
    ),
    "evals.md": (
        "## 2. `EV-PL-001`",
        "## 3. `EV-PL-002`",
        "## 4. `EV-PL-003`",
        "## 5. `EV-PL-004`",
        "## 6. `EV-PL-005`",
        "## 7. Golden inventory",
        "## 8. Evidence",
        "## 9. Cost budget",
    ),
    "workstreams.md": (
        "## 1. Ownership map",
        "## 2. PL1",
        "## 3. PL2",
        "## 4. PL3",
        "## 5. PL4",
        "## 6. PL5",
        "## 7. Integration",
        "## 9. Definition of done",
    ),
    "decisions.md": (
        "## D-PL-01",
        "## D-PL-02",
        "## D-PL-03",
        "## D-PL-04",
        "## D-PL-05",
        "## D-PL-06",
        "## D-PL-07",
        "## D-PL-08",
        "## D-PL-09",
        "## D-PL-10",
        "## D-PL-11",
    ),
}

TABLE_NAMES = (
    "user_preferences",
    "personalized_session",
    "personalized_message",
    "personalized_artifact",
    "personalized_usage",
    "personalized_quota",
)

LINK_RE = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
PLACEHOLDER_RE = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b")
FORBIDDEN_TABLE_RE = re.compile(
    r"create\s+table[^\n]*(plan|subscription|payment|entitlement)",
    re.IGNORECASE,
)


def read(name: str) -> str:
    return (FOLDER / name).read_text(encoding="utf-8")


class SpecFiles(unittest.TestCase):
    def test_required_files_exist_and_are_substantive(self) -> None:
        for name in FILES:
            with self.subTest(file=name):
                path = FOLDER / name
                self.assertTrue(path.is_file(), f"{name} is missing")
                self.assertGreater(
                    len(read(name)), 1_000, f"{name} is too thin to be a contract"
                )

    def test_decision_log_csv_parses(self) -> None:
        path = FOLDER / "decision-log-addendum.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            rows = list(reader)
            self.assertEqual(
                reader.fieldnames,
                [
                    "cand_id",
                    "candidate",
                    "layer",
                    "job_moment",
                    "mechanism_and_evidence_tag",
                    "removal_test",
                    "cost",
                    "risk",
                    "metric",
                    "outcome",
                    "reason_or_merge_target",
                    "revisit_trigger",
                ],
            )
        self.assertEqual(len(rows), 30, "expected the full 30-candidate log")


class RequiredSections(unittest.TestCase):
    def test_each_file_has_its_required_headings(self) -> None:
        for name, headings in REQUIRED_HEADINGS.items():
            text = read(name)
            for heading in headings:
                with self.subTest(file=name, heading=heading):
                    self.assertIn(heading, text)


class Links(unittest.TestCase):
    def test_every_relative_link_resolves(self) -> None:
        failures: list[str] = []
        for name in (*FILES, "decision-log-addendum.csv"):
            if not name.endswith(".md"):
                continue
            path = FOLDER / name
            for match in LINK_RE.finditer(read(name)):
                target = match.group(1)
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                relative = target.split("#", 1)[0]
                if not relative:
                    continue
                candidate = (path.parent / relative).resolve()
                if not candidate.exists():
                    failures.append(f"{name}: {target}")
        self.assertEqual(
            failures, [], "unresolved relative links: " + ", ".join(failures)
        )


class Decisions(unittest.TestCase):
    def test_each_open_decision_has_recommendation_owner_and_status(self) -> None:
        text = read("decisions.md")
        for number in range(1, 12):
            with self.subTest(decision=f"D-PL-{number:02d}"):
                start = text.find(f"## D-PL-{number:02d}")
                self.assertNotEqual(start, -1)
                end = text.find("## D-PL-", start + 1)
                if end == -1:
                    end = text.find("## Assumptions", start + 1)
                block = text[start:end]
                self.assertIn("**Recommendation:**", block)
                self.assertIn("**Owner:**", block)
                self.assertIn("**Status:**", block)

    def test_decision_ids_are_exactly_one_to_eleven(self) -> None:
        text = read("decisions.md")
        ids = re.findall(r"^## D-PL-(\d{2})", text, re.MULTILINE)
        self.assertEqual(ids, [f"{n:02d}" for n in range(1, 12)])


class EvalsAndWorkstreams(unittest.TestCase):
    def test_eval_cards_are_exactly_five_and_have_checkers(self) -> None:
        text = read("evals.md")
        ids = re.findall(r"EV-PL-(\d{3})", text)
        self.assertEqual(sorted(set(ids)), ["001", "002", "003", "004", "005"])
        for number in range(1, 6):
            with self.subTest(card=f"EV-PL-{number:03d}"):
                self.assertIn(f"DET-PL0{number}", text)
        self.assertIn("runs/evals/", text)
        self.assertIn("deterministic", text.lower())

    def test_workstreams_are_pl1_to_pl5_with_ownership(self) -> None:
        text = read("workstreams.md")
        for number in range(1, 6):
            with self.subTest(workstream=f"PL{number}"):
                self.assertIn(f"## {number + 1}. PL{number}", text)
                self.assertIn(f"**PL{number}**", text)
        self.assertIn("| Workstream | Owns | Depends on | Blocks |", text)

    def test_feature_cards_are_present(self) -> None:
        text = read("feature-addendum.md")
        for number in range(1, 7):
            with self.subTest(card=f"PL-F{number}"):
                self.assertIn(f"### PL-F{number}", text)


class DataAndPrivacy(unittest.TestCase):
    def test_required_tables_are_declared(self) -> None:
        text = read("data-and-api.md")
        for name in TABLE_NAMES:
            with self.subTest(table=name):
                self.assertIn(f"`{name}`", text)

    def test_tables_are_covered_by_the_retention_matrix(self) -> None:
        text = read("security-privacy.md")
        for name in TABLE_NAMES:
            with self.subTest(table=name):
                self.assertIn(name, text)

    def test_threat_model_has_sixteen_controls(self) -> None:
        text = read("security-privacy.md")
        ids = re.findall(r"\*\*T-PL-(\d{2})\*\*", text)
        self.assertEqual(ids, [f"{n:02d}" for n in range(1, 17)])

    def test_privacy_and_legal_flags_are_present(self) -> None:
        text = read("security-privacy.md").lower()
        self.assertIn("dpdp", text)
        self.assertIn("not legal advice", text)
        self.assertIn("child", text)


class FreePrototype(unittest.TestCase):
    def test_no_paywall_rule_is_stated(self) -> None:
        readme = " ".join(read("README.md").split()).lower()
        spec = " ".join(read("spec.md").split()).lower()
        self.assertIn("no paywall", readme)
        self.assertIn("no paywall", spec)

    def test_no_plan_or_payment_tables_or_creation(self) -> None:
        text = read("data-and-api.md")
        self.assertIn("No paywall tables", text)
        self.assertIsNone(FORBIDDEN_TABLE_RE.search(text))
        for name in ("plan", "subscription", "payment", "entitlement"):
            with self.subTest(name=name):
                self.assertIsNone(
                    re.search(rf"^### 2\.\d+ `{name}", text, re.MULTILINE),
                    f"a {name} table was declared",
                )


class RepoPointers(unittest.TestCase):
    def test_agents_docs_map_lists_the_folder(self) -> None:
        text = (REPO / "AGENTS.md").read_text(encoding="utf-8")
        self.assertRegex(text, r"(?m)^- `docs/specs/personalized-learning/` — ")
        self.assertIn("W5.5", text)

    def test_timeline_carries_the_wave_and_the_spec_pointer(self) -> None:
        text = (REPO / "TIMELINE.md").read_text(encoding="utf-8")
        self.assertIn("**W5.5**", text)
        self.assertIn("### W5.5 — Personalized Learning", text)
        self.assertIn("docs/specs/personalized-learning/", text)

    def test_readme_points_at_the_folder(self) -> None:
        text = (REPO / "README.md").read_text(encoding="utf-8")
        self.assertIn("docs/specs/personalized-learning/", text)


class NoPlaceholders(unittest.TestCase):
    def test_no_todo_markers_in_the_folder(self) -> None:
        hits: list[str] = []
        for name in FILES:
            for match in PLACEHOLDER_RE.finditer(read(name)):
                hits.append(f"{name}: {match.group(0)}")
        self.assertEqual(hits, [], "placeholders are not allowed: " + ", ".join(hits))


if __name__ == "__main__":
    unittest.main()
