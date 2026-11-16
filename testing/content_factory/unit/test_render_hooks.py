"""Renderer hooks, section ownership, manifest v2 and the catalogue (P1).

These are the deterministic contracts the product layers consume:
`data-block-type` on 100% of blocks, `data-element-id` where the component
inventory defines one, `<section class="zn-section">` wrappers that own their
blocks, the block -> section map in `manifest.json`, manifest v2 fields, and
`catalogue.json`. Everything here runs key-free and offline.
"""

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import ClassVar

from factory import identity, schemas, sections
from factory.hooks import hook_issues
from factory.render import CATALOGUE_NAME, write_courses_js
from factory.render import run as render_run
from testing.content_factory.unit.test_render import make_cfg, minimal_inputs

BLOCK_TAG_RE = re.compile(
    r"<(section|figure|fieldset)\b[^>]*class=\"[^\"]*\bzn-"
    r"(?:text|example|reveal|diagram|check|sim)\b[^\"]*\"[^>]*>"
)
TYPE_BY_CLASS = {
    "zn-text": "text",
    "zn-example": "worked_example",
    "zn-check": "check",
    "zn-reveal": "reveal",
    "zn-diagram": "diagram",
    "zn-sim": "simulation",
}


def _render(tmp: Path):
    cfg, _frontend = make_cfg(tmp)
    from factory.artifacts import RunContext

    run_ctx = RunContext(cfg.repo_path(cfg.paths["runs"]), "t-hooks")
    source_pack, lesson, blocks, interactive = minimal_inputs()
    out = render_run(cfg, run_ctx, "Motion", source_pack, lesson, blocks, interactive)
    topic = Path(out["topic_dir"])
    return out, topic, (topic / "index.html").read_text(encoding="utf-8")


class TestRendererHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out, self.topic, self.html = _render(self.tmp)

    def test_every_block_element_declares_its_type_and_concept(self):
        seen = 0
        for match in BLOCK_TAG_RE.finditer(self.html):
            tag = match.group(0)
            cls = re.search(r'class="([^"]*)"', tag).group(1)
            expected = next(
                (btype for cls_name, btype in TYPE_BY_CLASS.items() if cls_name in cls),
                None,
            )
            self.assertIsNotNone(expected, f"unknown block class: {tag}")
            self.assertIn(
                f'data-block-type="{expected}"',
                tag,
                f"block element lacks data-block-type: {tag}",
            )
            self.assertRegex(
                tag,
                r'data-concept-id="class-9-motion-sec-\d\d"',
                f"block element lacks data-concept-id: {tag}",
            )
            self.assertRegex(tag, r'\bid="b-\d+"', f"block lost its stable id: {tag}")
            seen += 1
        self.assertGreater(seen, 0, "expected rendered block elements")

    def test_every_block_sits_in_exactly_one_section_wrapper(self):
        wrappers = re.findall(
            r'<section class="zn-section" id="(sec-\d\d)" '
            r'data-section-id="sec-\d\d" data-concept-id="([^"]+)">(.*?)</section>',
            self.html,
            re.DOTALL,
        )
        self.assertTrue(wrappers, "expected zn-section wrappers")
        # Nesting makes the regex non-greedy-ambiguous, so count ownership by
        # the block ids each wrapper's body mentions instead.
        manifest = json.loads((self.topic / "manifest.json").read_text())
        owned = [bid for entry in manifest["sections"] for bid in entry["block_ids"]]
        block_ids = [f"b-{i:02d}" for i in range(1, 60)]
        rendered = [b for b in block_ids if f'id="{b}"' in self.html]
        self.assertEqual(
            sorted(owned),
            sorted(rendered),
            "manifest sections must own every rendered block exactly once",
        )
        self.assertEqual(len(owned), len(set(owned)), "a block is owned twice")
        for section_id, concept, _body in wrappers:
            self.assertEqual(concept, f"class-9-motion-{section_id}")

    def test_element_ids_follow_the_component_inventory(self):
        # Only ids whose element actually exists on a generated page.
        for element_id in (
            "EL-LES-01-001",  # kicker
            "EL-LES-01-002",  # title
            "EL-LES-01-010",  # text paragraph
            "EL-LES-01-014",  # diagram figure
            "EL-LES-01-015",  # diagram caption
            "EL-LES-01-018",  # simulation card
            "EL-LES-01-021",  # simulation canvas
            "EL-LES-01-025",  # check fieldset
            "EL-LES-01-028",  # check button
            "EL-LES-01-032",  # worked-example problem
            "EL-LES-01-036",  # glossary
            "EL-LES-01-037",  # sources footer
        ):
            self.assertIn(
                f'data-element-id="{element_id}"',
                self.html,
                f"missing inventory hook {element_id}",
            )
        # The dock / consent / language-bar ids belong to the shell kit: a
        # content page must never pre-empt them (ONE emitter per element).
        for shell_only in ("EL-LES-01-042", "EL-LES-01-057", "EL-LES-01-006"):
            self.assertNotIn(f'data-element-id="{shell_only}"', self.html)


class TestManifestV2(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.out, self.topic, self.html = _render(self.tmp)
        self.manifest = json.loads((self.topic / "manifest.json").read_text())

    def test_manifest_validates_against_the_v2_schema(self):
        import jsonschema

        jsonschema.Draft7Validator(schemas.MANIFEST_V2).validate(self.manifest)
        self.assertEqual(self.manifest["manifest_version"], 2)
        self.assertEqual(self.manifest["chapter_id"], "class-9-motion")
        self.assertEqual(self.manifest["lesson_id"], "class-9-motion")
        self.assertEqual(self.manifest["subject"], "physics")
        self.assertEqual(self.manifest["status"], "lesson_only")
        self.assertRegex(self.manifest["content_hash"], r"^sha256:[0-9a-f]{64}$")
        self.assertEqual(self.manifest["pipeline_version"], identity.pipeline_version())

    def test_languages_report_coverage_not_promises(self):
        languages = self.manifest["languages"]
        self.assertEqual(languages["default"], "en")
        self.assertEqual(languages["available"], ["en"])
        self.assertEqual(languages["missing"], ["hi", "hi-Latn"])

    def test_counts_cover_what_the_artifact_contains(self):
        counts = self.manifest["counts"]
        self.assertEqual(counts["lesson_blocks"], len(self.manifest["blocks"]))
        self.assertEqual(
            counts["lesson_blocks"],
            sum(
                counts[k]
                for k in (
                    "checks",
                    "worked_examples",
                    "diagrams",
                    "simulations",
                    "reveals",
                    "text_blocks",
                )
            ),
        )
        # Practice/tests are absent until P2/P3 produce them - never a fake 0.
        self.assertNotIn("practice_items", counts)
        self.assertNotIn("test_items", counts)

    def test_block_map_matches_sections_and_every_block(self):
        for block_id, entry in self.manifest["blocks"].items():
            self.assertRegex(block_id, r"^b-\d\d$")
            self.assertIn(entry["type"], schemas.BLOCK_TYPES)
            self.assertEqual(
                entry["concept_id"], f"class-9-motion-{entry['section_id']}"
            )
        owned = {
            bid: section["id"]
            for section in self.manifest["sections"]
            for bid in section["block_ids"]
        }
        self.assertEqual(
            owned, {b: e["section_id"] for b, e in self.manifest["blocks"].items()}
        )
        self.assertEqual(len(self.manifest["concepts"]), len(self.manifest["sections"]))

    def test_content_hash_is_stable_across_renders_and_follows_content(self):
        again, topic_again, _ = _render(Path(tempfile.mkdtemp()))
        del again
        manifest_again = json.loads((topic_again / "manifest.json").read_text())
        self.assertEqual(manifest_again["content_hash"], self.manifest["content_hash"])
        # Changing one paragraph changes the content identity.
        source_pack, lesson, blocks, interactive = minimal_inputs()
        blocks["blocks"][0]["spec"]["paragraphs"][0] += " One more sentence."
        cfg, _frontend = make_cfg(Path(tempfile.mkdtemp()))
        from factory.artifacts import RunContext

        out = render_run(
            cfg,
            RunContext(cfg.repo_path(cfg.paths["runs"]), "t-hooks-2"),
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        changed = json.loads((Path(out["topic_dir"]) / "manifest.json").read_text())
        self.assertNotEqual(changed["content_hash"], self.manifest["content_hash"])


class TestCatalogue(unittest.TestCase):
    def test_catalogue_has_one_entry_per_topic_and_reuses_manifest_core(self):
        tmp = Path(tempfile.mkdtemp())
        out, _topic, _html = _render(tmp)
        site = Path(out["site_dir"])
        catalogue = json.loads((site / CATALOGUE_NAME).read_text())
        self.assertEqual(catalogue["catalogue_version"], 1)
        self.assertEqual(len(catalogue["topics"]), 1)
        entry = catalogue["topics"][0]
        for key in (
            "href",
            "generated_at",
            "chapter_id",
            "lesson_id",
            "status",
            "languages",
            "counts",
            "concepts",
            "content_hash",
            "pipeline_version",
        ):
            self.assertIn(key, entry, f"catalogue entry lacks {key}")
        self.assertEqual(entry["href"], "courses/class-9-physics/motion/index.html")
        # courses.js stays the browser file with its existing shape.
        courses_js = (site / "courses.js").read_text()
        self.assertIn("window.ZIVON_COURSES", courses_js)

    def test_a_v1_manifest_still_loads(self):
        # Old artifacts must not break the catalogue: unknown v2 fields are
        # simply absent (never invented).
        tmp = Path(tempfile.mkdtemp())
        frontend = tmp / "frontend"
        topic = frontend / "courses" / "class-9-physics" / "motion"
        topic.mkdir(parents=True)
        (topic / "index.html").write_text("<!doctype html>", encoding="utf-8")
        v1_manifest = {
            "course_id": "class-9-physics",
            "class": 9,
            "topic_slug": "motion",
            "title": "Motion",
            "lesson_title": "Motion",
            "chapter": {
                "query": "Motion",
                "title": "MOTION",
                "book": "NCERT",
                "pages": [1, 2],
                "number": 6,
            },
            "sources": [],
            "run_id": "old-run",
            "generated_at": "2026-11-01T00:00:00Z",
            "block_counts": {"text": 1},
        }
        (topic / "manifest.json").write_text(json.dumps(v1_manifest), encoding="utf-8")
        entries = write_courses_js(frontend)
        self.assertEqual(entries[0]["title"], "Motion")
        catalogue = json.loads((frontend / CATALOGUE_NAME).read_text())
        entry = catalogue["topics"][0]
        self.assertEqual(entry["href"], "courses/class-9-physics/motion/index.html")
        self.assertNotIn("chapter_id", entry)
        self.assertNotIn("content_hash", entry)

    def test_an_unreadable_manifest_fails_loudly(self):
        # A topic that silently disappears from courses.js/catalogue.json is
        # worse than a failed publish: the page exists but nothing can list
        # it. The scan must raise, never skip.
        tmp = Path(tempfile.mkdtemp())
        frontend = tmp / "frontend"
        topic = frontend / "courses" / "class-9-physics" / "motion"
        topic.mkdir(parents=True)
        (topic / "manifest.json").write_text("{not json", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            write_courses_js(frontend)
        self.assertIn("manifest.json", str(ctx.exception))


class TestSectionOwnership(unittest.TestCase):
    LESSON: ClassVar[dict] = {
        "sections": [
            {
                "id": "sec-01",
                "title": "Forces",
                "paragraphs": ["A push or a pull is a force."],
            },
            {
                "id": "sec-02",
                "title": "Friction",
                "paragraphs": [
                    "Friction opposes the sliding of one surface over another surface."
                ],
            },
        ]
    }

    def _text_block(self, block_id, text):
        return {
            "id": block_id,
            "type": "text",
            "spec": {"paragraphs": [text]},
            "citations": [],
        }

    def test_authored_section_id_wins(self):
        blocks = [
            self._text_block("b-01", "unrelated words about nothing much"),
            self._text_block("b-02", "friction opposes sliding"),
        ]
        blocks[1]["section_id"] = "sec-01"
        ownership = sections.resolve_sections(self.LESSON, blocks)
        self.assertEqual(ownership.by_block["b-02"], "sec-01")
        self.assertEqual(ownership.authored, 1)

    def test_ownership_is_monotone_and_covers_every_block(self):
        blocks = [
            self._text_block("b-01", "A push or a pull is a force."),
            {
                "id": "b-02",
                "type": "check",
                "spec": {
                    "question": "What is friction?",
                    "options": ["a force", "a mass"],
                },
                "citations": [],
            },
            self._text_block("b-03", "A push or a pull is a force."),  # backwards
            self._text_block(
                "b-04",
                "Friction opposes the sliding of one surface over another surface.",
            ),
        ]
        ownership = sections.resolve_sections(self.LESSON, blocks)
        self.assertEqual(set(ownership.by_block), {"b-01", "b-02", "b-03", "b-04"})
        order = [ownership.by_block[b] for b in ("b-01", "b-02", "b-03", "b-04")]
        self.assertEqual(order, ["sec-01", "sec-01", "sec-01", "sec-02"])

    def test_no_sections_means_no_ownership(self):
        ownership = sections.resolve_sections(
            {"sections": []}, [self._text_block("b-01", "x")]
        )
        self.assertEqual(ownership.by_block, {})


class TestIdentity(unittest.TestCase):
    def test_the_grade_defect_cannot_reach_a_manifest(self):
        # The live page whose chapter.title was "Grade": unusable, so the
        # operator's query is the honest fallback.
        self.assertFalse(identity.is_usable_chapter_title("Grade"))
        self.assertEqual(
            identity.repair_chapter_title(
                "Grade", matched_line=None, query="Describing Motion Around Us"
            ),
            "Describing Motion Around Us",
        )
        self.assertEqual(
            identity.repair_chapter_title("LAWS OF MOTION"), "LAWS OF MOTION"
        )

    def test_page_furniture_is_not_a_title(self):
        for junk in (
            "Grade 7",
            "Class 9",
            "Science 134",
            "Chapter-04.indd 48",
            "Fig. 6.3: (a) A ball",
            "contents",
            "134",
        ):
            self.assertFalse(
                identity.is_usable_chapter_title(junk), f"{junk!r} must be rejected"
            )
        self.assertIsNone(identity.repair_chapter_title("Grade", query="Grade 9"))

    def test_ids_are_stable_and_readable(self):
        chapter = identity.chapter_id(9, "motion")
        self.assertEqual(chapter, "class-9-motion")
        self.assertEqual(identity.lesson_id(9, "motion"), chapter)
        self.assertEqual(
            identity.concept_id(chapter, "sec-03"), "class-9-motion-sec-03"
        )


class TestHookContractChecker(unittest.TestCase):
    """`factory.hooks.hook_issues` is the assertion P4 registers for the eval
    cards (EV-SYN-001 render contract / EV-VIS-002 metadata conformance). Its
    negative cases must fire on exactly the defects they name."""

    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        _out, topic, self.html = _render(tmp)
        self.manifest = json.loads((topic / "manifest.json").read_text())
        self.assertEqual(hook_issues(self.html, self.manifest), [])

    def test_a_block_without_a_type_hook_is_reported(self):
        broken = self.html.replace(' data-block-type="check"', "", 1)
        issues = hook_issues(broken)
        self.assertTrue(any("data-block-type" in issue for issue in issues), issues)

    def test_a_block_outside_a_section_wrapper_is_reported(self):
        # Move one block out of its wrapper: the id must not be owned twice.
        broken = self.html.replace(
            '<section class="zn-section" id="sec-01" '
            'data-section-id="sec-01" data-concept-id="class-9-motion-sec-01">',
            '<div class="zn-section" data-section-id="sec-01" '
            'data-concept-id="class-9-motion-sec-01">',
            1,
        ).replace("</section>", "</div>", 1)
        issues = hook_issues(broken)
        self.assertTrue(any("zn-section" in issue for issue in issues), issues)

    def test_a_manifest_that_disagrees_with_the_page_is_reported(self):
        manifest = json.loads(json.dumps(self.manifest))
        first_block = next(iter(manifest["blocks"]))
        manifest["blocks"][first_block]["section_id"] = "sec-99"
        issues = hook_issues(self.html, manifest)
        self.assertTrue(
            any(
                first_block in issue and "manifest section" in issue for issue in issues
            ),
            issues,
        )

    def test_a_manifest_missing_a_rendered_block_is_reported(self):
        manifest = json.loads(json.dumps(self.manifest))
        dropped = next(iter(manifest["blocks"]))
        del manifest["blocks"][dropped]
        issues = hook_issues(self.html, manifest)
        self.assertTrue(
            any(
                dropped in issue and "absent from manifest" in issue for issue in issues
            ),
            issues,
        )


if __name__ == "__main__":
    unittest.main()
