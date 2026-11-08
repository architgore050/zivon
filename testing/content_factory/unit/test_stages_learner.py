"""Unit tests for the learner-class derivation (founder decision 2026-11-06).

The run's learner class is per-run input, never config: config.json carries
NO learner.class_level (a config default for a per-run value is just a
hardcode with extra steps). The class comes from the --class flag or from the
chapter actually located by 01-locate. A class-11 chapter must generate with
class-11 prompts and land in courses/class-11-physics/, never under some
default - the old behaviour built 'Motion in a Straight Line' (class 11) as a
class-9 page.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.config import load_config
from factory.stages import (
    PIPELINE_VERSION,
    _sync_learner_to_chapter,
    make_run_id,
    run_fingerprint,
)
from testing.content_factory.unit._server_env import (
    install_server_env,
    release_server_env,
)


def _source_pack(chapter_class: int) -> dict:
    return {
        "chapter": {
            "class": chapter_class,
            "title": "MOTION IN A STRAIGHT LINE",
            "book_title": "NCERT Physics Class 11 (fixture)",
        }
    }


class TestLearnerClassDerivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = install_server_env()
        cls.cfg = load_config(REPO_ROOT / "config.json")  # carries NO class

    @classmethod
    def tearDownClass(cls):
        release_server_env(cls.saved)

    def test_config_carries_no_class(self):
        self.assertNotIn("class_level", self.cfg.learner)

    def test_sync_takes_the_class_from_the_located_chapter(self):
        derived = _sync_learner_to_chapter(self.cfg, _source_pack(11))
        self.assertEqual(derived.learner["class_level"], 11)
        self.assertNotIn("class_level", self.cfg.learner)  # original untouched

    def test_sync_keeps_the_class_set_by_class_flag(self):
        # --class 11 filtered locate to class-11 books, so the chapter class
        # agrees and no second derivation fires.
        cfg11 = self.cfg.with_class_level(11)
        same = _sync_learner_to_chapter(cfg11, _source_pack(11))
        self.assertIs(same, cfg11)

    def test_sync_refuses_a_flag_that_disagrees_with_the_chapter(self):
        # Harness guard: the chapter is the ground truth, never the flag.
        cfg11 = self.cfg.with_class_level(11)
        derived = _sync_learner_to_chapter(cfg11, _source_pack(9))
        self.assertEqual(derived.learner["class_level"], 9)

    def test_fingerprint_refuses_version4_run_dirs(self):
        # Version-4 dirs baked a config-default class into their fingerprint;
        # version-5 dirs were built under the blind catcher caps; version-7
        # dirs precede the kit-contract lint (0.3.14+) under which old
        # page.css (canvas sizing) fails lint. Any of those changed the stage
        # artifacts' contracts, so resume must refuse them (--fresh).
        self.assertEqual(PIPELINE_VERSION, "7")
        chapter = "Motion in a Straight Line"
        self.assertNotEqual(
            run_fingerprint(self.cfg, chapter, 11),
            run_fingerprint(self.cfg.with_class_level(9), chapter, 11),
        )

    def test_fingerprint_carries_the_class_flag_shape(self):
        # --class given vs omitted are different run shapes on purpose:
        # motion-c9 (flag) and motion (derived) are distinct dirs.
        self.assertNotEqual(
            run_fingerprint(self.cfg.with_class_level(9), "Motion", 9),
            run_fingerprint(self.cfg, "Motion", None),
        )

    def test_fingerprint_stable_across_calls(self):
        self.assertEqual(
            run_fingerprint(self.cfg, "Motion", None),
            run_fingerprint(self.cfg, "Motion", None),
        )

    def test_run_id_still_carries_the_class(self):
        self.assertEqual(
            make_run_id("Motion in a Straight Line", 11),
            "motion-in-a-straight-line-c11",
        )


if __name__ == "__main__":
    unittest.main()
