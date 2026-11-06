"""Unit tests for the learner-class derivation (founder bug report 2026-11-06).

The run's learner class follows the topic actually used: --class overrides
config.json's learner.class_level, and after 01-locate the class follows the
chapter really found. A class-11 chapter must generate with class-11 prompts
and land in courses/class-11-physics/, never under the config default - the
old behaviour built 'Motion in a Straight Line' (class 11) as a class-9 page.
"""

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from testing.content_factory.unit._server_env import install_server_env, release_server_env

from factory.config import load_config
from factory.stages import _sync_learner_to_chapter, make_run_id, run_fingerprint


def _source_pack(chapter_class: int) -> dict:
    return {"chapter": {"class": chapter_class, "title": "MOTION IN A STRAIGHT LINE"}}


class TestLearnerClassDerivation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = install_server_env()
        cls.cfg = load_config(REPO_ROOT / "config.json")  # default class_level: 9

    @classmethod
    def tearDownClass(cls):
        release_server_env(cls.saved)

    def test_sync_follows_the_located_chapter(self):
        derived = _sync_learner_to_chapter(self.cfg, _source_pack(11))
        self.assertEqual(derived.learner["class_level"], 11)
        self.assertEqual(self.cfg.learner["class_level"], 9)  # original untouched

    def test_sync_keeps_config_when_chapter_matches(self):
        same = _sync_learner_to_chapter(self.cfg, _source_pack(9))
        self.assertIs(same, self.cfg)

    def test_sync_after_class_flag_is_a_noop(self):
        # --class 11 already filtered locate to class-11 books, so the chapter
        # class agrees and no second override fires.
        cfg11 = self.cfg.with_class_level(11)
        same = _sync_learner_to_chapter(cfg11, _source_pack(11))
        self.assertIs(same, cfg11)

    def test_fingerprint_refuses_the_old_wrong_class_run(self):
        # The killed class-11 run dir was built with the config default (9) in
        # its fingerprint. After the fix the same trigger carries learner 11,
        # so resume must refuse that dir and demand --fresh.
        chapter = "Motion in a Straight Line"
        old_shape = run_fingerprint(self.cfg, chapter, 11)  # learner 9 + filter 11
        new_shape = run_fingerprint(self.cfg.with_class_level(11), chapter, 11)
        self.assertNotEqual(old_shape, new_shape)

    def test_fingerprint_stable_for_matching_class(self):
        # A class-9 trigger (filter == config default) keeps its fingerprint:
        # healthy existing runs are not invalidated by this fix.
        self.assertEqual(
            run_fingerprint(self.cfg, "Motion", 9),
            run_fingerprint(self.cfg.with_class_level(9), "Motion", 9),
        )

    def test_run_id_still_carries_the_class(self):
        self.assertEqual(make_run_id("Motion in a Straight Line", 11),
                         "motion-in-a-straight-line-c11")


if __name__ == "__main__":
    unittest.main()
