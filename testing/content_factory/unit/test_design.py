"""Unit tests for the design context loader (factory/design.py).

The doctrine + its examples are the single source of truth: the loader hands
them over LIVE, picks up new example files via the glob with no pipeline
change, derives the palette from the real shell stylesheet, and fails loudly
(never silently truncates) when the doctrine outgrows the model's budget.
"""

import dataclasses
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import design
from factory.config import ConfigError, load_config
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)

BASE_CONFIG = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def make_cfg(tmp: Path, mutate=None):
    data = json.loads(json.dumps(BASE_CONFIG))
    if mutate:
        mutate(data)
    path = tmp / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    saved = install_server_env()
    try:
        cfg = load_config(path)
    finally:
        release_server_env(saved)
    return cfg


class TestDesignLoader(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        # load_config roots relative paths at the config file's directory;
        # point root at the real repo so the SHIPPED doctrine, examples and
        # stylesheet are the ones under test.
        self.cfg = dataclasses.replace(make_cfg(self.tmp), root=REPO_ROOT)

    def test_doctrine_handed_over_live(self):
        text = design.doctrine_text(self.cfg)
        self.assertIn("Field Notes", text)
        self.assertIn("Lesson page", text)  # the v1.1 extension flows through

    def test_examples_glob_is_lesson_page_only(self):
        # 2026-11-04 (founder decision): factory context carries ONLY the
        # lesson-page examples. The main (post/brand) example stays a docs
        # asset - it must not bleed into generated pages.
        text = design.examples_text(self.cfg)
        self.assertIn("design-doctrine-lesson-example.html", text)
        self.assertNotIn("=== design-doctrine-example.html ===", text)

    def test_examples_are_framed_as_styling_only(self):
        # 2026-11-04 (founder): the example's plain-simple CONTENT was bleeding
        # into generated pages. Every stage that receives the examples must be
        # told, in the same breath, that they are a styling reference only.
        block = design.design_context(self.cfg, with_examples=True)
        self.assertIn("VISUAL STYLING REFERENCE ONLY", block)
        self.assertIn("never reuse or imitate their content", block)
        self.assertIn("dictated by the SOURCE MATERIAL", block)
        # the framing must come BEFORE the example bodies, never after them
        self.assertLess(
            block.index("VISUAL STYLING REFERENCE ONLY"),
            block.index("=== design-doctrine-lesson-example.html ==="),
        )

    def test_new_documents_flow_without_any_pipeline_change(self):
        # Open-endedness proof: a fake repo tree with its own doctrine, two
        # examples and stylesheet - the loader picks all of it up unchanged.
        fake = self.tmp / "fake-repo"
        (fake / "docs" / "frontend").mkdir(parents=True)
        (fake / "docs" / "frontend" / "design-doctrine.md").write_text(
            "# Doctrine\nrules here\n", encoding="utf-8"
        )
        (fake / "docs" / "frontend" / "design-doctrine-lesson-alpha.html").write_text(
            "<html>alpha demo</html>", encoding="utf-8"
        )
        (fake / "docs" / "frontend" / "design-doctrine-lesson-zeta.html").write_text(
            "<html>zeta demo</html>", encoding="utf-8"
        )
        (fake / "frontend" / "assets").mkdir(parents=True)
        (fake / "frontend" / "assets" / "zivon.css").write_text(
            ":root { --ink: #101010; }\n", encoding="utf-8"
        )
        cfg = dataclasses.replace(self.cfg, root=fake)
        block = design.design_context(cfg, with_examples=True)
        self.assertIn("rules here", block)
        self.assertIn("alpha demo", block)
        self.assertIn("zeta demo", block)
        self.assertIn("--ink: #101010", design.palette_text(cfg))

    def test_missing_doctrine_fails_loudly(self):
        cfg = dataclasses.replace(self.cfg, root=self.tmp)  # empty tree
        with self.assertRaises(ConfigError) as ctx:
            design.doctrine_text(cfg)
        self.assertIn("not found", str(ctx.exception))

    def test_budget_exceeded_fails_loudly_never_truncates(self):
        def mutate(data):
            data["limits"]["max_chars_design_context"] = 500

        cfg = dataclasses.replace(make_cfg(self.tmp, mutate), root=REPO_ROOT)
        with self.assertRaises(ConfigError) as ctx:
            design.design_context(cfg, with_examples=True)
        msg = str(ctx.exception)
        self.assertIn("chars", msg)
        self.assertIn("500", msg)

    def test_current_repo_fits_the_budget(self):
        # The shipped doctrine + examples must fit the shipped budget. If this
        # fails, the doctrine outgrew the model context and a human must
        # decide - which is exactly the point of the loud check.
        block = design.design_context(self.cfg, with_examples=True)
        self.assertLess(len(block), self.cfg.limits["max_chars_design_context"])


if __name__ == "__main__":
    unittest.main()
