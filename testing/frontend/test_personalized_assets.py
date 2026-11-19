"""PL4 asset contract tests (static, no browser): personalized.css/js.

The repo's frontend rule: same-origin only, no inline handlers, no framework,
reduced-motion and narrow-screen rules ship with the island, and the session
island never touches what the PL3 artifact bridge owns (iframe creation stays
in personalized-artifact.js).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CSS = (REPO_ROOT / "frontend" / "assets" / "personalized.css").read_text(
    encoding="utf-8"
)
JS = (REPO_ROOT / "frontend" / "assets" / "personalized.js").read_text(encoding="utf-8")

HUB = (REPO_ROOT / "web" / "templates" / "app" / "personalized_hub.html").read_text(
    encoding="utf-8"
)
SESSION = (
    REPO_ROOT / "web" / "templates" / "app" / "personalized_session.html"
).read_text(encoding="utf-8")
PARTIAL = (
    REPO_ROOT / "web" / "templates" / "app" / "partials" / "personal_instructions.html"
).read_text(encoding="utf-8")
SETTINGS = (REPO_ROOT / "web" / "templates" / "app" / "settings.html").read_text(
    encoding="utf-8"
)


class PersonalizedCssContract(unittest.TestCase):
    def test_no_external_host_or_lesson_kit(self) -> None:
        self.assertNotRegex(CSS, r"url\(\s*[\"']?(?:https?:)?//")
        self.assertNotIn("zivon.css", CSS)
        self.assertNotIn("Caveat", CSS)
        self.assertNotIn("Kalam", CSS)

    def test_carries_the_360px_and_reduced_motion_rules(self) -> None:
        self.assertIn("@media (max-width: 46rem)", CSS)
        self.assertIn("@media (prefers-reduced-motion: reduce)", CSS)

    def test_styles_only_its_own_scope_plus_the_pl3_viewer_box(self) -> None:
        # Every class selector is .pl-* or the PL3 viewer box the session page
        # embeds (its sizing lives here per workstreams.md §5, its behaviour
        # stays in personalized-artifact.js).
        selectors = re.findall(r"^\.([a-z][a-z0-9-]*)", CSS, re.MULTILINE)
        offenders = [
            s
            for s in selectors
            if not s.startswith("pl-") and not s.startswith("zn-art-viewer")
        ]
        self.assertEqual(offenders, [], f"out-of-scope selectors: {offenders}")
        self.assertTrue(selectors, "the sheet must style something")

    def test_no_gradients_shadows_or_grain(self) -> None:
        self.assertNotIn("gradient", CSS.lower())
        self.assertNotRegex(CSS, r"box-shadow")
        self.assertNotIn("backdrop-filter", CSS)


class PersonalizedJsContract(unittest.TestCase):
    def test_no_framework_no_eval_no_inline_html(self) -> None:
        self.assertNotIn("document.write", JS)
        self.assertNotRegex(JS, r"\beval\s*\(")
        self.assertNotIn(".innerHTML", JS)
        self.assertNotIn("dangerouslySetInnerHTML", JS)
        self.assertNotIn("require(", JS)
        self.assertNotIn("import(", JS)

    def test_csrf_comes_from_the_meta_only(self) -> None:
        self.assertIn('meta[name="csrf-token"]', JS)
        self.assertNotIn("localStorage", JS)
        self.assertNotIn("sessionStorage", JS)

    def test_artifact_urls_are_never_constructed(self) -> None:
        # §4.8: the artifact document URL is only ever the server-issued src
        # (payload or data-artifact-src). The status endpoint may be derived
        # from the payload id — the PL3 bridge does the same.
        self.assertIn("data-artifact-src", JS)
        self.assertIn("/status'", JS)
        src_assignments = re.findall(r"\.src\s*=\s*([^;]+);", JS)
        self.assertEqual(
            src_assignments,
            [],
            "the island must not assign an iframe src (the PL3 bridge owns it)",
        )
        self.assertNotIn("createObjectURL", JS)

    def test_mount_is_idempotent_and_noop_without_roots(self) -> None:
        self.assertIn("data-pl-mounted", JS)
        self.assertIn("window.ZivonPersonalized", JS)
        self.assertNotIn("fetch('http", JS)
        self.assertNotRegex(JS, r"https?://[a-z0-9.-]+\.(?:com|net|org|io|dev)")


class PersonalizedTemplateContract(unittest.TestCase):
    def test_pages_load_the_islands_as_same_origin_files(self) -> None:
        self.assertIn('href="/assets/personalized.css"', HUB)
        self.assertIn('href="/assets/personalized.css"', SESSION)
        self.assertIn('src="/assets/personalized.js" defer', SESSION)
        self.assertIn('src="/assets/personalized-artifact.js" defer', SESSION)
        # The hub has no turn stream, so it loads no island script.
        self.assertNotIn("personalized.js", HUB)

    def test_settings_keeps_the_one_include_line_contract(self) -> None:
        self.assertIn(
            '{% include "app/partials/personal_instructions.html" %}', SETTINGS
        )
        self.assertEqual(
            SETTINGS.count("personal_instructions.html"),
            1,
            "settings.html must include the PL4 partial exactly once",
        )
        self.assertIn('href="/assets/personalized.css"', SETTINGS)
        self.assertIn('src="/assets/personalized.js" defer', SETTINGS)

    def test_session_page_renders_no_check_answer_server_side(self) -> None:
        self.assertNotIn("answer_key", SESSION)
        # The viewer partial is the PL3 file; its src attr is server-issued.
        self.assertIn("artifact_viewer.html", SESSION)

    def test_privacy_page_carries_the_personalized_row(self) -> None:
        privacy = (
            REPO_ROOT / "web" / "templates" / "app" / "settings_privacy.html"
        ).read_text(encoding="utf-8")
        self.assertIn("90 days", privacy)
        self.assertIn("personalized-learning sessions", privacy)
        self.assertIn("no audio", privacy)

    def test_instructions_partial_holds_the_honest_boundaries(self) -> None:
        self.assertIn("What this can't do", PARTIAL)
        self.assertIn("safety rules", PARTIAL)
        self.assertIn('role="status"', PARTIAL)
        self.assertIn('maxlength="500"', PARTIAL)


if __name__ == "__main__":
    unittest.main()
