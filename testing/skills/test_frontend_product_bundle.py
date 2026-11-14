"""Tests for the zivon-frontend-product-skills bundle.

The bundle is documentation, but its layout, trigger surface, and contracts
are checkable. Run from the repo root:
  python -m unittest discover -s testing/skills -t .
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "zivon-frontend-product-skills"


def _load_validator():
    path = REPO / "scripts" / "check_skills.py"
    spec = importlib.util.spec_from_file_location("check_skills_frontend", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills_frontend"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


class FrontendProductBundleTests(unittest.TestCase):
    REQUIRED = (
        "SKILL.md",
        "README.md",
        "references/design-system.md",
        "references/app-shell-and-routing.md",
        "references/screens-and-states.md",
        "references/component-patterns.md",
        "references/accessibility-performance-seo.md",
        "references/visual-review-protocol.md",
        "references/frontend-testing.md",
        "references/worked-example.md",
        "templates/screen-spec.md",
        "templates/state-matrix.md",
        "templates/component-checklist.md",
        "templates/visual-verdict.md",
    )

    ELEVEN_STATES = (
        "default",
        "loading",
        "empty",
        "partial",
        "error",
        "offline",
        "permission-denied",
        "reduced-motion",
        "untranslated",
        "quota-exhausted",
        "consent-missing",
    )

    REQUIRED_SCREENS = (
        "Landing",
        "Catalogue",
        "Lesson",
        "Dashboard",
        "Practice",
        "Speaking",
        "Tests",
        "SWOT",
        "Doubts",
        "Settings",
        "Admin",
    )

    def _text(self, relative: str) -> str:
        return (BUNDLE / relative).read_text(encoding="utf-8")

    def test_required_files_exist(self) -> None:
        missing = [name for name in self.REQUIRED if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])
        self.assertTrue((REPO / "scripts" / "check_skills.py").is_file())

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual(
            [skill.name for skill in skills], ["zivon-frontend-product-skills"]
        )
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_frontmatter_carries_trigger_and_evidence_date(self) -> None:
        fields, _ = validator.parse_frontmatter(self._text("SKILL.md"))
        self.assertEqual(fields["name"], "zivon-frontend-product-skills")
        self.assertIn("use when", fields["description"].lower())
        self.assertGreaterEqual(len(fields["description"]), 80)
        raw = self._text("SKILL.md")
        self.assertIn("metadata:", raw)
        self.assertIn("evidence_date:", raw)
        self.assertIn('evidence_date: "2026-11-14"', raw)
        self.assertIn('version: "1.0"', raw)
        self.assertIn("owner: zivon", raw)

    def test_reference_map_mentions_every_reference(self) -> None:
        body = self._text("SKILL.md")
        for path in sorted((BUNDLE / "references").glob("*.md")):
            self.assertIn(path.name, body, f"{path.name} is not in the SKILL.md map")

    def test_state_matrix_names_all_eleven_states(self) -> None:
        text = self._text("references/screens-and-states.md")
        for state in self.ELEVEN_STATES:
            self.assertIn(f"`{state}`", text, f"state {state!r} missing")
        self.assertIn("n/a (reason)", text)

    def test_screen_matrix_covers_the_product_surfaces(self) -> None:
        text = self._text("references/screens-and-states.md")
        for screen in self.REQUIRED_SCREENS:
            self.assertIn(screen, text, f"screen {screen!r} missing from the inventory")
        self.assertIn("/app/swot", text)
        self.assertIn("/courses/{class}-physics/{chapter}/", text)
        self.assertIn("/admin/*", text)

    def test_static_ssr_and_no_spa_are_taught(self) -> None:
        skill = self._text("SKILL.md")
        routing = self._text("references/app-shell-and-routing.md")
        for token in ("Static", "SSR", "no SPA", "server-rendered"):
            self.assertIn(token.lower(), skill.lower(), f"SKILL.md must teach {token}")
        for token in (
            "nginx",
            "HttpOnly",
            "SameSite=Lax",
            "same-origin",
            "hi-Latn",
            "noindex",
            "canonical",
            "JSON-LD",
            "hreflang",
        ):
            self.assertIn(token, routing, f"routing reference must cover {token}")

    def test_accessibility_and_performance_contracts(self) -> None:
        text = self._text("references/accessibility-performance-seo.md")
        for token in (
            "WCAG 2.2 AA",
            "44",
            "reduced-motion",
            "weak-Android",
            "60 KB",
            "120 KB",
            "LCP",
            "INP",
            "CLS",
            "JSON-LD",
            "hreflang",
            "canonical",
        ):
            self.assertIn(token, text, f"quality reference must cover {token}")

    def test_visual_review_protocol_is_complete(self) -> None:
        text = self._text("references/visual-review-protocol.md")
        for token in (
            "localhost",
            "8101",
            "verdict",
            "same agent session",
            "doctrine",
            "No product PR before the verdict",
        ):
            self.assertIn(token.lower(), text.lower(), f"protocol must cover {token}")

    def test_templates_are_complete(self) -> None:
        expectations = {
            "templates/screen-spec.md": (
                "Identity",
                "States",
                "Accessibility",
                "Tests",
            ),
            "templates/state-matrix.md": ("default", "consent-missing", "Completeness"),
            "templates/component-checklist.md": ("Markup contract", "States", "Review"),
            "templates/visual-verdict.md": (
                "Verdict",
                "Doctrine decision",
                "Implementation",
            ),
        }
        for relative, headings in expectations.items():
            text = self._text(relative)
            for heading in headings:
                self.assertIn(heading, text, f"{relative} missing {heading!r}")

    def test_readme_records_scope_provenance_and_read_order(self) -> None:
        text = self._text("README.md")
        for token in (
            "Read order",
            "Scope",
            "Provenance and sources",
            "2026-11-14",
            "zivon-frontend-skills",
            "seo-optimization.md",
            "implementation entry point",
        ):
            self.assertIn(token, text, f"README must cover {token}")

    def test_worked_example_names_the_rejected_patterns(self) -> None:
        text = self._text("references/worked-example.md")
        for token in ("SaaS dashboard", "Gradients", "Leaderboards", "SPA"):
            self.assertIn(token, text, f"worked example must name {token}")


if __name__ == "__main__":
    unittest.main()
