"""End-to-end integration test for the golden Motion (Class 9) translation pipeline (10a -> 10b -> 10c -> 10d -> 11-link)."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from testing.translation._test_env import (
    ensure_test_dependencies,
    install_translation_env,
    restore_translation_env,
)

ensure_test_dependencies()

from factory import link, render, transcheck, translate
from factory.artifacts import RunContext
from factory.config import load_config
from factory.lint import lint_generated, lint_js
from factory.llm import LLMClient
from testing.translation.mock_translation_node import start_translation_mock

FIXTURES = REPO_ROOT / "testing" / "content_factory" / "mocks" / "fixtures"


class TestTranslationPipelineE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.server, cls.base_url, cls.state = start_translation_mock()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="zivon-trans-e2e-"))
        self.saved_env = install_translation_env(self.base_url)
        self.state.calls.clear()
        self.state.scripted_review_issues.clear()
        self.state.scripted_bad_unit_first_attempt.clear()

        self.frontend = self.tmp / "frontend"
        self.frontend.mkdir()
        shutil.copytree(REPO_ROOT / "frontend" / "assets", self.frontend / "assets")
        shutil.copy2(REPO_ROOT / "frontend" / "index.html", self.frontend / "index.html")
        shutil.copy2(REPO_ROOT / "frontend" / "courses.js", self.frontend / "courses.js")

        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        base["paths"]["runs"] = str(self.tmp / "runs")
        base["paths"]["text_cache"] = str(self.tmp / "cache")
        base["paths"]["frontend"] = str(self.frontend)
        cfg_path = self.tmp / "config.json"
        cfg_path.write_text(json.dumps(base), encoding="utf-8")
        self.cfg = load_config(cfg_path).with_locales(["hi", "hi-Latn"])

        self.lesson = json.loads(
            (FIXTURES / "lesson.json").read_text(encoding="utf-8")
        )
        self.blocks = json.loads(
            (FIXTURES / "blocks.json").read_text(encoding="utf-8")
        )
        self.ground_truth = json.loads(
            (FIXTURES / "gt.json").read_text(encoding="utf-8")
        )
        self.interactive = {
            "b-06": json.loads(
                (FIXTURES / "05-interactive.json").read_text(encoding="utf-8")
            )
        }
        self.source_pack = {
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

    def tearDown(self) -> None:
        restore_translation_env(self.saved_env)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_golden_motion_topic_end_to_end_hi_and_hinglish(self) -> None:
        run_ctx = RunContext(
            self.cfg.repo_path(self.cfg.paths["runs"]), "e2e-trans-motion"
        )
        llm = LLMClient(self.cfg, run_ctx)

        # Stage 06-render (canonical English page)
        render_out = render.run(
            self.cfg,
            run_ctx,
            "Motion",
            self.source_pack,
            self.lesson,
            self.blocks,
            self.interactive,
        )

        # Inject a first-attempt regional numeral violation on (hi, b-03) to verify
        # LLMClient extra_validator retry inside 10a-translate
        self.state.scripted_bad_unit_first_attempt.add(("hi", "b-03"))

        # Stage 10a-translate
        translate_out = translate.run(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            render_out,
        )
        self.assertIn("hi", translate_out["locales"])
        self.assertIn("hi-Latn", translate_out["locales"])
        self.assertEqual(
            translate_out["locales"]["hi"]["stats"]["gnani_credits_used"], 0
        )

        # Stage 10b-transcheck
        transcheck_out = transcheck.run(
            self.cfg,
            run_ctx,
            llm,
            self.ground_truth,
            self.lesson,
            self.blocks,
            translate_out,
        )
        self.assertEqual(
            transcheck_out["verdict"],
            "pass",
            f"Unexpected issues: {transcheck_out}",
        )

        # Stage 10d-transrender
        transrender_out = render.render_localized(
            self.cfg,
            run_ctx,
            "Motion",
            self.source_pack,
            self.lesson,
            self.blocks,
            render_out,
            translate_out,
            transcheck_out,
        )
        self.assertTrue(transrender_out["manifest_updated"])
        self.assertEqual(
            transrender_out["locales_available"], ["en", "hi", "hi-Latn"]
        )

        # Stage 11-link (publishes into self.frontend)
        link_out = link.run(self.cfg, run_ctx, render_out)
        self.assertEqual(link_out["course_count"], 1)
        self.assertEqual(
            set(link_out["published_locale_hubs"]), {"hi", "hi-Latn"}
        )

        pub_topic = Path(link_out["published_to"])
        self.assertTrue((pub_topic / "index.html").is_file())
        self.assertTrue((pub_topic / "i18n.js").is_file())
        self.assertTrue((pub_topic / "i18n" / "en.json").is_file())
        self.assertTrue((pub_topic / "i18n" / "hi.json").is_file())
        self.assertTrue((pub_topic / "i18n" / "hi-Latn.json").is_file())
        self.assertTrue((pub_topic / "hi" / "index.html").is_file())
        self.assertTrue((pub_topic / "hi-Latn" / "index.html").is_file())
        self.assertTrue((self.frontend / "hi" / "index.html").is_file())
        self.assertTrue((self.frontend / "hi-Latn" / "index.html").is_file())

        # Verify Hindi HTML route attributes, language bar, data-i18n anchors, and strict lints
        hi_html = (pub_topic / "hi" / "index.html").read_text(encoding="utf-8")
        self.assertIn('<html lang="hi" data-script="Deva">', hi_html)
        self.assertIn('data-current-locale="hi"', hi_html)
        self.assertIn('data-i18n="b-00-meta.title"', hi_html)
        self.assertIn('data-i18n="b-05.svg_texts.t-0"', hi_html)
        self.assertIn('<script src="../i18n.js"></script>', hi_html)
        self.assertIn('<script src="../page.js"></script>', hi_html)
        self.assertEqual(lint_generated("", "", hi_html), [])

        # Verify Hinglish HTML route has Latin script metadata
        hinglish_bundle = json.loads(
            (pub_topic / "i18n" / "hi-Latn.json").read_text(encoding="utf-8")
        )
        self.assertEqual(hinglish_bundle["script"], "Latn")
        self.assertEqual(hinglish_bundle["status"], "verified")

        # Verify i18n.js passes lint_js with zero network URLs
        i18n_js = (pub_topic / "i18n.js").read_text(encoding="utf-8")
        self.assertEqual(lint_js("i18n.js", i18n_js), [])
        self.assertIn("window.ZIVON_I18N =", i18n_js)

        # Verify CP-TRN-004 metadata in manifest.json and courses.js
        manifest = json.loads(
            (pub_topic / "manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["default_locale"], "en")
        self.assertEqual(manifest["locales_available"], ["en", "hi", "hi-Latn"])
        self.assertIn("hi", manifest["titles_by_locale"])
        self.assertEqual(
            manifest["translation_status"]["hi"]["status"], "verified"
        )

        courses_entry = link_out["courses"][0]
        self.assertEqual(
            courses_entry["locales_available"], ["en", "hi", "hi-Latn"]
        )
        self.assertIn("hi-Latn", courses_entry["titles_by_locale"])



    def test_stages_orchestrator_runs_10a_to_11_link_and_handles_optional_fallback(
        self,
    ) -> None:
        from factory.stages import run_fingerprint, run_pipeline

        # Pre-seed a run directory with 01-locate, 02-generate, 05-interactive, and 06-render outputs
        run_id = "e2e-stages-orch"
        run_ctx = RunContext(self.cfg.repo_path(self.cfg.paths["runs"]), run_id)
        cfg9 = self.cfg.with_class_level(9)
        run_ctx.set_fingerprint(run_fingerprint(cfg9, "Motion", 9))
        run_ctx.save_stage_output("01-locate", self.source_pack)
        run_ctx.mark_stage("01-locate", "ok")
        run_ctx.save_stage_output(
            "02-generate",
            {
                "ground_truth": self.ground_truth,
                "lesson": self.lesson,
                "blocks": self.blocks,
            },
        )
        run_ctx.mark_stage("02-generate", "ok")
        run_ctx.save_stage_output("05-interactive", self.interactive)
        run_ctx.mark_stage("05-interactive", "ok")
        render_out = render.run(
            self.cfg,
            run_ctx,
            "Motion",
            self.source_pack,
            self.lesson,
            self.blocks,
            self.interactive,
        )
        run_ctx.save_stage_output("06-render", render_out)
        run_ctx.mark_stage("06-render", "ok")

        # Script one recoverable reviewer issue on hi/b-01 so 10c-transrepair is exercised in stages.py
        self.state.scripted_review_issues["hi"] = [
            [
                {
                    "block_id": "b-01",
                    "severity": "major",
                    "category": "glossary_term",
                    "message": "Include parenthetical gloss on first mention of motion.",
                }
            ],
            [],
        ]

        res = run_pipeline(
            self.cfg,
            "Motion",
            9,
            run_id=run_id,
            only_stages={
                "10a-translate",
                "10b-transcheck",
                "10c-transrepair",
                "10d-transrender",
                "11-link",
            },
        )
        self.assertTrue(res["ok"])
        status = json.loads((run_ctx.dir / "status.json").read_text(encoding="utf-8"))
        for st in (
            "10a-translate",
            "10b-transcheck",
            "10c-transrepair",
            "10d-transrender",
            "11-link",
        ):
            self.assertEqual(status["stages"][st]["state"], "ok", st)


if __name__ == "__main__":
    unittest.main()
