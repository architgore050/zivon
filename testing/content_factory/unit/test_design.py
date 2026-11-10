"""Unit tests for the design context loader (factory/design.py).

Note: Shipped-doctrine context budget and COMPONENT DEMOS framing checks were
migrated to `evals/checkers/prompt_contract_checks.py` (`EV-VIS-001`) per
`docs/specs/evals/migration-map.csv` row 19.
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
        self.cfg = dataclasses.replace(make_cfg(self.tmp), root=REPO_ROOT)

    def test_doctrine_handed_over_live(self):
        text = design.doctrine_text(self.cfg)
        self.assertIn("Field Notes", text)
        self.assertIn("Lesson page", text)

    def test_new_documents_flow_without_any_pipeline_change(self):
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
        cfg = dataclasses.replace(self.cfg, root=self.tmp)
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


if __name__ == "__main__":
    unittest.main()
