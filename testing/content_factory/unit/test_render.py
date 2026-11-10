"""Unit tests for stage 06-render and courses.js generation."""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.artifacts import RunContext
from factory.config import load_config
from factory.errors import LintError
from factory.render import run as render_run
from factory.render import write_courses_js
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


def make_cfg(tmp: Path):
    base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    base["paths"]["runs"] = str(tmp / "runs")
    frontend = tmp / "frontend"
    frontend.mkdir()
    shutil.copytree(REPO_ROOT / "frontend" / "assets", frontend / "assets")
    shutil.copy2(REPO_ROOT / "frontend" / "index.html", frontend / "index.html")
    base["paths"]["frontend"] = str(frontend)
    path = tmp / "config.json"
    path.write_text(json.dumps(base), encoding="utf-8")
    saved = install_server_env()  # server settings are env-only now
    try:
        cfg = load_config(path)
    finally:
        release_server_env(saved)
    return cfg, frontend


def minimal_inputs():
    lesson = json.loads((FIXTURES / "lesson.json").read_text())
    blocks = json.loads((FIXTURES / "blocks.json").read_text())
    interactive = {"b-06": json.loads((FIXTURES / "05-interactive.json").read_text())}
    source_pack = {
        "chapter": {
            "title": "Motion",
            "book_id": "fixture-ncert-9",
            "book_title": "Fixture Science Class 9",
            "class": 9,
            "file": "ch01.pdf",
            "pages": [1, 5],
            "matched_line": "Motion",
        },
        "ncert_text": "Motion text",
        "supplements": [
            {
                "source_id": "alt#c0000",
                "book_id": "alt-open-physics",
                "book_title": "Open Physics Notes",
                "page_from": 1,
                "page_to": 2,
                "score": 0.5,
                "text": "graph text",
            }
        ],
    }
    return source_pack, lesson, blocks, interactive


class TestRender(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, self.frontend = make_cfg(self.tmp)
        self.run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "t-render"
        )

    def test_render_produces_clean_page(self):
        source_pack, lesson, blocks, interactive = minimal_inputs()
        out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        topic = Path(out["topic_dir"])
        html = (topic / "index.html").read_text(encoding="utf-8")
        self.assertIn("Content-Security-Policy", html)
        self.assertIn('lang="en"', html)
        self.assertIn('data-answer-index="1"', html)
        self.assertIn('data-sim-id="b-06"', html)
        self.assertIn("<svg", html)  # diagram inlined
        self.assertTrue((topic / "page.js").exists())
        self.assertTrue((topic / "page.css").exists())
        self.assertIn("connect-src 'none'", html)
        # assets copied into staging
        self.assertTrue((Path(out["site_dir"]) / "assets" / "zivon.css").exists())
        self.assertTrue((Path(out["site_dir"]) / "assets" / "zivon.js").exists())
        self.assertTrue((Path(out["site_dir"]) / "courses.js").exists())
        # manifest written and complete
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["course_id"], "class-9-physics")
        self.assertTrue(manifest["sources"])

    def test_topic_identity_comes_from_the_chapter_not_the_lesson_title(self):
        # 2026-11-10 founder bug report: re-runs published a SECOND topic dir
        # for the same chapter because the slug/title came from the model's
        # lesson headline ("Laws of Motion: From Aristotle's Mistake to
        # Newton's Three Laws"). The chapter is the page's identity.
        source_pack, lesson, blocks, interactive = minimal_inputs()
        lesson = dict(lesson, title="Motion: A Tagline Sneaks In Here")
        out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        topic = Path(out["topic_dir"])
        self.assertEqual(topic.name, "motion")
        html = (topic / "index.html").read_text(encoding="utf-8")
        self.assertIn('<h1 class="zn-title">Motion</h1>', html)
        self.assertIn("<title>Motion - Zivon</title>", html)
        self.assertNotIn("A Tagline Sneaks In Here</h1>", html)
        manifest = json.loads((topic / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["title"], "Motion")
        # the model's own headline is kept on record, not used as identity
        self.assertEqual(manifest["lesson_title"], "Motion: A Tagline Sneaks In Here")

    def test_chapter_display_title_is_deterministic(self):
        from factory.render import chapter_display_title

        self.assertEqual(
            chapter_display_title("MOTION IN A STRAIGHT LINE"),
            "Motion in a Straight Line",
        )
        self.assertEqual(chapter_display_title("LAWS OF MOTION"), "Laws of Motion")
        self.assertEqual(
            chapter_display_title("UNITS AND MEASUREMENT"), "Units and Measurement"
        )

    def test_lint_failure_blocks_render(self):
        source_pack, lesson, blocks, interactive = minimal_inputs()
        interactive["b-06"]["files"]["page.js"] = "eval('1')"
        with self.assertRaises(LintError):
            render_run(
                self.cfg,
                self.run_ctx,
                "Motion",
                source_pack,
                lesson,
                blocks,
                interactive,
            )

    def test_no_page_js_when_no_interactive(self):
        source_pack, lesson, blocks, _ = minimal_inputs()
        blocks = {"blocks": [b for b in blocks["blocks"] if b["type"] != "simulation"]}
        out = render_run(
            self.cfg, self.run_ctx, "Motion", source_pack, lesson, blocks, {}
        )
        html = (Path(out["topic_dir"]) / "index.html").read_text(encoding="utf-8")
        self.assertNotIn('src="page.js"', html)
        self.assertFalse((Path(out["topic_dir"]) / "page.js").exists())

    def test_kit_chrome_is_rendered(self):
        # doctrine v1.6: the language bar is renderer-emitted kit chrome
        # (§10.5 - 09-review flagged its absence as a major on every run),
        # and every simulation carries the canonical readout element the
        # kit owns (.zn-sim-read - the 05 agent once invented .sim-read).
        source_pack, lesson, blocks, interactive = minimal_inputs()
        out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        html = (Path(out["topic_dir"]) / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="zn-lang-bar"', html)
        self.assertIn('aria-checked="true">English</button>', html)
        self.assertIn('<p class="zn-sim-read" aria-live="polite"></p>', html)

    def test_publish_prunes_stale_duplicate_topic_for_the_same_chapter(self):
        # 2026-11-10 founder bug report: two "Laws of Motion" cards on the
        # landing page, same content - the pre-fix slug was model-authored, so
        # each run left the previous directory behind. Publishing a chapter
        # must leave exactly ONE topic dir for it.
        from factory import link

        source_pack, lesson, blocks, interactive = minimal_inputs()
        out = render_run(
            self.cfg,
            self.run_ctx,
            "Motion",
            source_pack,
            lesson,
            blocks,
            interactive,
        )
        # a superseded duplicate from the old lesson-title-slug era
        stale = (
            self.frontend
            / "courses"
            / "class-9-physics"
            / "motion-a-tagline"
            / "manifest.json"
        )
        stale.parent.mkdir(parents=True)
        stale.write_text(
            json.dumps(
                {
                    "course_id": "class-9-physics",
                    "class": 9,
                    "title": "Motion: A Tagline",
                    "chapter": {"title": "Motion"},
                    "generated_at": "2026-11-09T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        # an unrelated topic of the SAME course must survive the pruning
        other = (
            self.frontend / "courses" / "class-9-physics" / "forces" / "manifest.json"
        )
        other.parent.mkdir(parents=True)
        other.write_text(
            json.dumps(
                {
                    "course_id": "class-9-physics",
                    "class": 9,
                    "title": "How Forces Affect Motion",
                    "chapter": {"title": "FORCES"},
                    "generated_at": "2026-11-09T00:00:00Z",
                }
            ),
            encoding="utf-8",
        )
        (other.parent / "index.html").write_text("<html></html>", encoding="utf-8")
        published = link.run(self.cfg, self.run_ctx, out)
        self.assertEqual(published["pruned_stale_topics"], ["motion-a-tagline"])
        self.assertFalse(stale.parent.exists())
        self.assertTrue(other.parent.exists())
        self.assertTrue(
            (self.frontend / "courses" / "class-9-physics" / "motion").exists()
        )
        entries = published["courses"]
        self.assertEqual(
            [e["href"].split("/")[-2] for e in entries],
            sorted(["motion", "forces"]),
        )

    def test_courses_js_regeneration(self):
        frontend = self.frontend
        write_courses_js(frontend)
        text = (frontend / "courses.js").read_text(encoding="utf-8")
        self.assertIn("window.ZIVON_COURSES = []", text)

    def test_courses_js_orders_by_chapter_number_not_run_order(self):
        # Entries may arrive in any run order (a class-11 chapter-2 topic can
        # be published before its chapter-1 topic); the catalogue must still
        # come out in true NCERT chapter order - numbers run continuously
        # across parts (Part II starts at 8). Unnumbered entries (older
        # manifests / non-NCERT topics) sort last within their class.
        import json

        frontend = self.frontend
        specs = [
            ("ch2-topic", 11, 2, "MOTION IN A STRAIGHT LINE"),
            ("ch1-topic", 11, 1, "UNITS AND MEASUREMENT"),
            ("unnum-topic", 11, None, "SOME SUPPLEMENT TOPIC"),
            ("c9-topic", 9, 6, "FORCE AND LAWS OF MOTION"),
        ]
        for slug, cls, number, chapter in specs:
            topic = frontend / "courses" / f"class-{cls}-physics" / slug
            topic.mkdir(parents=True)
            (topic / "index.html").write_text("<html></html>", encoding="utf-8")
            (topic / "manifest.json").write_text(
                json.dumps(
                    {
                        "course_id": f"class-{cls}-physics",
                        "class": cls,
                        "chapter": {"title": chapter, "number": number},
                        "title": chapter.title(),
                        "generated_at": "2026-11-09T00:00:00Z",
                    }
                ),
                encoding="utf-8",
            )
        entries = write_courses_js(frontend)
        order = [(e["class"], e["chapter_number"]) for e in entries]
        self.assertEqual(order, [(9, 6), (11, 1), (11, 2), (11, None)])


class TestDiagramAsAuthored(unittest.TestCase):
    """Doctrine v1.3 (founder ruling 2026-11-04): the handify_svg jitter pass is
    retired - diagram geometry renders exactly as the model authored it."""

    SVG = (
        '<svg viewBox="0 0 420 270">'
        '<line x1="30" y1="190" x2="390" y2="190" stroke="#1C1B18" stroke-width="3"/>'
        '<path d="M10 10 A5 5 0 0 1 20 20" fill="none"/>'
        '<circle cx="5" cy="5" r="2"/><text x="10" y="20">label</text></svg>'
    )

    def test_diagram_svg_is_inserted_verbatim(self):
        from factory.render import _render_block

        html = _render_block(
            {"id": "b-07", "type": "diagram", "spec": {"svg": self.SVG, "caption": "c"}}
        )
        self.assertIn('<line x1="30" y1="190" x2="390" y2="190"', html)
        self.assertIn('<path d="M10 10 A5 5 0 0 1 20 20"', html)
        self.assertNotIn(" Q", html)  # no hand-generator smoothing anywhere


if __name__ == "__main__":
    unittest.main()
