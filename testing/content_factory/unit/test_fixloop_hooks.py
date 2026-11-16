"""Regression tests for the P1 hook contract surviving a repair rebuild.

`08-fixloop` and `10-reviewfix` re-emit `index.html` from corrected block specs.
Before 2026-11-16 that rebuild used the flat `_render_block` join, so a fix
round silently dropped every `<section class="zn-section">` wrapper and
`data-concept-id` hook while `manifest.json` kept claiming the block ->
section map - the page stopped agreeing with its own handoff and F4's drawer /
the tutor anchor / the P4 hook checker would address ids that were gone.
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import fixloop as fixloop_mod
from factory.artifacts import RunContext
from factory.hooks import hook_issues
from factory.render import run as render_run
from testing.content_factory.unit.test_render import make_cfg, minimal_inputs


def _render(tmp: Path):
    cfg, _frontend = make_cfg(tmp)
    run_ctx = RunContext(cfg.repo_path(cfg.paths["runs"]), "t-fixloop-hooks")
    source_pack, lesson, blocks, interactive = minimal_inputs()
    out = render_run(cfg, run_ctx, "Motion", source_pack, lesson, blocks, interactive)
    return cfg, out, blocks


class TestRepairRebuildPreservesHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.cfg, self.render_out, self.blocks = _render(self.tmp)
        self.topic = Path(self.render_out["topic_dir"])

    def _html(self) -> str:
        return (self.topic / "index.html").read_text(encoding="utf-8")

    def test_rebuild_from_blocks_keeps_sections_and_matches_the_manifest(self):
        manifest = json.loads((self.topic / "manifest.json").read_text())
        before = self._html()
        self.assertEqual(hook_issues(before, manifest), [])

        fixloop_mod._rebuild_html_if_needed(
            self.cfg, self.render_out, self.topic, self.blocks
        )

        after = self._html()
        self.assertEqual(hook_issues(after, manifest), [])
        self.assertEqual(
            after.count('class="zn-section"'),
            before.count('class="zn-section"'),
            "a repair rebuild must keep one wrapper per rendered section",
        )
        self.assertEqual(
            after.count("data-concept-id="),
            before.count("data-concept-id="),
            "a repair rebuild must keep every block's concept hook",
        )
        for section in manifest["sections"]:
            self.assertIn(f'id="{section["id"]}"', after)

    def test_corrected_block_still_renders_inside_its_section(self):
        corrected = json.loads(json.dumps(self.blocks["blocks"][0]))
        corrected["spec"]["paragraphs"][0] += " Repaired sentence."
        merged = {
            "blocks": [corrected, *self.blocks["blocks"][1:]],
        }
        fixloop_mod._rebuild_html_if_needed(
            self.cfg, self.render_out, self.topic, merged
        )
        html = self._html()
        manifest = json.loads((self.topic / "manifest.json").read_text())
        self.assertIn("Repaired sentence.", html)
        self.assertEqual(hook_issues(html), [])
        # The corrected block is still owned by the section the manifest says.
        owner = manifest["blocks"][corrected["id"]]["section_id"]
        self.assertIn(f'id="{owner}"', html)


if __name__ == "__main__":
    unittest.main()
