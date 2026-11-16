"""Tests for the zivon-landing-page-skills bundle.

The bundle is documentation, but its layout, trigger surface, contracts, and
research discipline are checkable. Run from the repo root:
  python -m unittest discover -s testing/skills -t .
"""

from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BUNDLE = REPO / "skills" / "zivon-landing-page-skills"


def _load_validator():
    path = REPO / "scripts" / "check_skills.py"
    spec = importlib.util.spec_from_file_location("check_skills_landing", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_skills_landing"] = module
    spec.loader.exec_module(module)
    return module


validator = _load_validator()


class LandingPageBundleTests(unittest.TestCase):
    REQUIRED = (
        "SKILL.md",
        "README.md",
        "references/audience-and-emotion.md",
        "references/narrative-frameworks.md",
        "references/page-anatomy.md",
        "references/copywriting-and-microcopy.md",
        "references/art-direction.md",
        "references/proof-and-trust.md",
        "references/motion-and-performance.md",
        "references/measurement.md",
        "references/critique-rubric.md",
        "references/teardowns.md",
        "references/sources.md",
        "templates/landing-brief.md",
        "templates/storyboard.md",
        "templates/wireframe.md",
        "templates/copy-deck.md",
        "templates/hero-variants.md",
        "templates/critique-sheet.md",
        "examples/zivon-landing-brief.md",
    )

    ANTI_PATTERNS = (
        "SaaS hero",
        "Gradient",
        "Vague AI claims",
        "Fake social proof",
        "Feature dump",
        "Stock photo",
        "cosplay",
        "Motion for its own sake",
    )

    FRAMEWORKS = ("PAS", "AIDA", "StoryBrand", "BAB", "FAB", "4U")

    def _text(self, relative: str) -> str:
        return (BUNDLE / relative).read_text(encoding="utf-8")

    def test_required_files_exist(self) -> None:
        missing = [name for name in self.REQUIRED if not (BUNDLE / name).is_file()]
        self.assertEqual(missing, [])

    def test_strict_validation_passes(self) -> None:
        skills, findings = validator.validate_bundle(BUNDLE, strict=True)
        self.assertEqual(
            [skill.name for skill in skills], ["zivon-landing-page-skills"]
        )
        self.assertEqual(findings, [], [finding.render() for finding in findings])

    def test_frontmatter_carries_triggers_and_evidence_date(self) -> None:
        fields, _ = validator.parse_frontmatter(self._text("SKILL.md"))
        self.assertEqual(fields["name"], "zivon-landing-page-skills")
        self.assertIn("use when", fields["description"].lower())
        self.assertGreaterEqual(len(fields["description"]), 80)
        self.assertLessEqual(len(fields["description"]), 1024)
        raw = self._text("SKILL.md")
        self.assertIn("metadata:", raw)
        self.assertIn("owner: zivon", raw)
        self.assertIn('version: "1.0"', raw)
        self.assertIn('evidence_date: "2026-11-16"', raw)

    def test_every_reference_is_named_with_a_load_condition(self) -> None:
        body = self._text("SKILL.md")
        references = sorted((BUNDLE / "references").glob("*.md"))
        self.assertGreaterEqual(len(references), 10)
        for path in references:
            self.assertIn(
                f"references/{path.name}",
                body,
                f"{path.name} is not linked from SKILL.md",
            )
        # The reference map must say WHEN to read each file, not just link it.
        self.assertIn("| Read this | When |", body)
        self.assertGreaterEqual(body.count("| [references/"), len(references))

    def test_value_addition_test_is_decision_grade(self) -> None:
        skill = self._text("SKILL.md")
        self.assertIn("value-addition test", skill.lower())
        for criterion in (
            "A reason to believe",
            "A reason to act",
            "The ability to act",
            "The answer to a live objection",
        ):
            self.assertIn(criterion, skill, f"value test missing {criterion!r}")
        # Applied to all three levels, not just sections.
        for level in ("section", "element", "word"):
            self.assertIn(level, skill.lower())
        self.assertIn("Apply it three times", skill)

    def test_anti_pattern_list_names_the_founder_briefed_failures(self) -> None:
        skill = self._text("SKILL.md")
        for token in self.ANTI_PATTERNS:
            self.assertIn(token, skill, f"anti-pattern {token!r} missing")

    def test_lesson_page_extension_is_explicitly_forbidden(self) -> None:
        skill = self._text("SKILL.md")
        art = self._text("references/art-direction.md")
        rubric = self._text("references/critique-rubric.md")
        self.assertIn("§10 never appears here", skill)
        self.assertIn("§10 guard", art)
        for device in (
            "ruled-line",
            "Caveat",
            "Taped paper cards",
            "language bar",
            "voice dock",
        ):
            self.assertIn(device, art, f"§10 ban must name {device!r}")
        # A tripped §10 leak is a hard gate in the rubric, not a style note.
        self.assertIn("Doctrine §10 devices", rubric)
        self.assertIn("G5", rubric)

    def test_narrative_frameworks_are_lenses_not_stacked_spines(self) -> None:
        text = self._text("references/narrative-frameworks.md")
        for name in self.FRAMEWORKS:
            self.assertIn(name, text, f"framework {name!r} missing")
        self.assertIn("one spine", text.lower())
        self.assertIn("Frankenpage", text)
        for beat in (
            "Hook",
            "Tension",
            "Guide",
            "Plan",
            "Proof",
            "Offer",
            "Action",
        ):
            self.assertIn(beat, text, f"default spine missing {beat!r}")

    def test_page_anatomy_covers_every_required_section(self) -> None:
        text = self._text("references/page-anatomy.md")
        for section in (
            "Top bar",
            "Hero",
            "Live specimen",
            "Mechanism",
            "Proof",
            "Coverage",
            "Privacy",
            "Founder",
            "Objections",
            "Final CTA",
            "Footer",
        ):
            self.assertIn(section, text, f"section {section!r} missing")
        self.assertIn("Omit when", text)
        self.assertIn("Failure mode", text)
        # Order is an argument decision, with constraints.
        self.assertIn("Order rules", text)

    def test_copy_reference_encodes_copy_contracts(self) -> None:
        text = self._text("references/copywriting-and-microcopy.md")
        for token in (
            "One promise",
            "substitution test",
            "Headline formulas",
            "CTA copy",
            "Microcopy",
            "No fake urgency",
            "Hinglish",
            "Words to avoid",
        ):
            self.assertIn(token, text, f"copy reference missing {token!r}")
        # The banned-word table must name the category's own worst words.
        for word in ("personalised", "interactive", "AI-powered"):
            self.assertIn(word, text, f"banned-word list missing {word!r}")

    def test_proof_reference_is_legal_and_specific(self) -> None:
        text = self._text("references/proof-and-trust.md")
        for token in (
            "16 CFR Part 465",
            "16 CFR Part 255",
            "2024",
            "claim ledger",
            "official",
            "NCERT",
            "docs/compliance",
        ):
            self.assertIn(token, text, f"proof reference missing {token!r}")
        self.assertIn("fake reviews and testimonials are prohibited", text.lower())

    def test_performance_reference_pins_the_measured_thresholds(self) -> None:
        text = self._text("references/motion-and-performance.md")
        for token in (
            "2.5 s",
            "200 ms",
            "0.1",
            "75th percentile",
            "prefers-reduced-motion",
            "3 seconds",
            "24 fps",
            "60 fps",
            "150 KB",
            "50 KB",
            "transcript",
        ):
            self.assertIn(token, text, f"performance reference missing {token!r}")
        # Doc-sync pin: the retired 60 KB figure was a JS byte budget, not RAM.
        self.assertIn("not a\nRAM budget", text)

    def test_measurement_names_the_frozen_events_and_refuses_vanity(self) -> None:
        text = self._text("references/measurement.md")
        for token in (
            "landing_view",
            "demo_play",
            "cta_try",
            "cta_login",
            "chapter_open",
        ):
            self.assertIn(token, text, f"event {token!r} missing")
        self.assertIn("Metrics to refuse", text)
        for vanity in ("Pageviews", "Bounce rate", "Time on page"):
            self.assertIn(vanity, text, f"vanity metric {vanity!r} not refused")

    def test_critique_rubric_has_nine_dimensions_and_hard_gates(self) -> None:
        text = self._text("references/critique-rubric.md")
        dimensions = re.findall(r"^### D(\d)\.", text, re.MULTILINE)
        self.assertEqual(dimensions, [str(n) for n in range(1, 10)])
        gates = re.findall(r"^\| G(\d+) \|", text, re.MULTILINE)
        self.assertEqual(gates, [str(n) for n in range(1, 11)])
        self.assertIn("honesty", text.lower())
        self.assertIn("36/45", text)
        self.assertIn("Request changes", text)

    def test_teardowns_are_real_linked_pages_with_dates(self) -> None:
        text = self._text("references/teardowns.md")
        urls = re.findall(r"\*\*Accessed:\*\*", text)
        self.assertGreaterEqual(len(urls), 5, "teardowns need 5-10 entries")
        self.assertLessEqual(len(urls), 10, "teardowns need 5-10 entries")
        self.assertIn("2026-11-16", text)
        for host in (
            "https://stripe.com",
            "https://linear.app",
            "https://www.gov.uk",
            "https://www.berkshirehathaway.com",
        ):
            self.assertIn(host, text, f"teardown missing {host}")
        # Link and learn, never copy.
        self.assertIn("never reproduce their copy", text)
        self.assertIn("What to learn", text)
        self.assertIn("What not to copy", text)

    def test_sources_are_dated_tagged_and_bounded(self) -> None:
        text = self._text("references/sources.md")
        rows = re.findall(r"^\| S(\d+) \|", text, re.MULTILINE)
        self.assertGreaterEqual(len(rows), 10, "sources must be 10-20")
        self.assertLessEqual(len(rows), 20, "sources must be 10-20")
        self.assertIn("2026-11-16", text)
        self.assertIn("[E]", text)
        self.assertIn("[P]", text)
        # The register must separate evidence from practitioner opinion.
        self.assertIn("Practitioner frameworks", text)
        self.assertIn("Limits of this research", text)
        # Perishable claims are explicitly flagged for re-verification.
        self.assertIn("Re-verification", text)

    def test_templates_are_usable_forms(self) -> None:
        expectations = {
            "templates/landing-brief.md": (
                "What would have to be true",
                "Must not exploit",
                "Proof available today",
                "Open questions",
            ),
            "templates/storyboard.md": (
                "Value test",
                "chain check",
                "deletion check",
                "Mobile order",
            ),
            "templates/wireframe.md": (
                "360 px",
                "1280 px",
                "One pen annotation",
                "Artifact spec",
            ),
            "templates/copy-deck.md": (
                "The promise",
                "CTA",
                "Microcopy and states",
                "Banned-word pass",
                "Multi-language pass",
            ),
            "templates/hero-variants.md": (
                "Outcome",
                "Mechanism",
                "Objection",
                "Tension",
                "Artifact",
                "pre-register",
            ),
            "templates/critique-sheet.md": (
                "Gates",
                "Total",
                "Verdict",
                "Second scorer",
            ),
        }
        for relative, tokens in expectations.items():
            text = self._text(relative)
            for token in tokens:
                self.assertIn(token, text, f"{relative} missing {token!r}")

    def test_readme_records_scope_provenance_and_read_order(self) -> None:
        text = self._text("README.md")
        for token in (
            "Read order",
            "Scope",
            "Provenance and sources",
            "Changelog",
            "design-doctrine.md",
            "docs/compliance/",
            "zivon-frontend-product-skills",
            "2026-11-16",
        ):
            self.assertIn(token, text, f"README must cover {token!r}")

    def test_worked_example_is_a_brief_not_an_approved_page(self) -> None:
        text = self._text("examples/zivon-landing-brief.md")
        self.assertIn("not approved copy", text)
        self.assertIn("founder", text.lower())
        # It must demonstrate the refusals, not just describe them.
        for refusal in (
            "Fear of boards",
            "Parental disappointment",
            "Fake urgency",
            "Invented proof",
        ):
            self.assertIn(refusal, text, f"worked example must refuse {refusal!r}")
        # It must show the measurement and the open questions.
        self.assertIn("chapter_open", text)
        self.assertIn("Open questions for the founder", text)
        # A proposed change to the frozen section list is flagged, not taken.
        self.assertIn("flagged not taken", text)

    def test_no_competing_authority_is_created(self) -> None:
        """The bundle interprets the doctrine; it must not claim to own it."""
        readme = self._text("README.md")
        art = self._text("references/art-direction.md")
        skill = self._text("SKILL.md")
        self.assertIn("The doctrine wins every conflict", skill)
        self.assertIn("does not add design tokens", readme)
        self.assertIn("derivation for the founder's verdict", art)
        # The reference implementation is named, not re-derived.
        self.assertIn("design-doctrine-example.html", art)
        # No invented hex values beyond the doctrine's own palette.
        self.assertNotRegex(art, r"#[0-9A-Fa-f]{6}")
