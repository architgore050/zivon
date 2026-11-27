"""Unit tests for the tracked syllabus module (issue #118, 2026-11-27).

Covers the CANONICAL chapter resolution (class + full normalized title, never
the renderer's truncated 40-char key), the explicit-alias mechanism, the
distinction between missing/corrupt syllabus data and a found chapter with
zero curated concepts, the concept metadata the facts reviewer consumes, and
the durable/atomic tracked-map persistence contract.
"""

from __future__ import annotations

import dataclasses
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory import syllabus
from factory.config import Config, load_config


def _real_cfg():
    """The repo's own tracked syllabus - every curated chapter must resolve."""
    os.environ.setdefault("ZIVON_BASE_URL", "http://127.0.0.1:9/v1")
    os.environ.setdefault("ZIVON_MODEL", "unit-test")
    return load_config()


def _write_syllabus(root: Path, classes: list[dict]) -> None:
    path = root / "sources" / "syllabus" / "syllabus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"classes": classes}), encoding="utf-8")


def _tmp_cfg(chapters: list[dict], *, corrupt: bool = False) -> Config:
    tmp = Path(tempfile.mkdtemp())
    cfg = dataclasses.replace(_real_cfg(), root=tmp)
    path = tmp / "sources" / "syllabus" / "syllabus.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if corrupt:
        path.write_text("{not json", encoding="utf-8")
    else:
        path.write_text(
            json.dumps({"classes": [{"class": 9, "chapters": chapters}]}),
            encoding="utf-8",
        )
    return cfg


class TestCanonicalChapterResolution(unittest.TestCase):
    """Every curated chapter resolves to its own id from (class, title)."""

    def test_every_curated_chapter_resolves_canonically(self):
        cfg = _real_cfg()
        unresolved: list[str] = []
        for entry in (syllabus.load_syllabus(cfg) or {}).get("classes", []):
            for ch in entry.get("chapters", []):
                resolved = syllabus.canonical_chapter_id(
                    cfg, ch["title"], entry.get("class")
                )
                if resolved != ch["chapter_id"]:
                    unresolved.append(f"{ch['chapter_id']} -> {resolved}")
        self.assertEqual(unresolved, [])

    def test_sound_waves_exceeds_the_renderer_slug_and_still_resolves(self):
        # the issue's example: the renderer's 40-char slug TRUNCATES this id
        cfg = _real_cfg()
        title = "Sound Waves: Characteristics and Applications"
        self.assertEqual(
            syllabus.located_chapter_id(title, 9),
            "class-9-sound-waves-characteristics-and-applicat",
        )
        self.assertEqual(
            syllabus.canonical_chapter_id(cfg, title, 9),
            "class-9-sound-waves-characteristics-and-applications",
        )
        self.assertIsNotNone(syllabus.resolve_chapter(cfg, title, 9))

    def test_alias_on_the_syllabus_record_resolves(self):
        ch = {
            "chapter_id": "class-9-sound-waves-characteristics-and-applications",
            "title": "Sound Waves: Characteristics and Applications",
            "aliases": ["sound waves and applications"],
            "concepts": [{"concept_id": "sw-1", "title": "Pitch", "description": ""}],
        }
        cfg = _tmp_cfg([ch])
        self.assertEqual(
            syllabus.canonical_chapter_id(cfg, "Sound Waves and Applications", 9),
            "class-9-sound-waves-characteristics-and-applications",
        )

    def test_class_scoping_excludes_other_classes(self):
        cfg = _real_cfg()
        # "Waves" is a class-11 chapter; asked as class 9 it must not resolve
        self.assertIsNone(syllabus.canonical_chapter_id(cfg, "Waves", 9))

    def test_uncurated_chapter_resolves_to_none(self):
        cfg = _real_cfg()
        self.assertIsNone(syllabus.resolve_chapter(cfg, "Motion", 9))


class TestSyllabusStates(unittest.TestCase):
    """Missing vs corrupt vs found-with-zero-concepts are distinct."""

    def test_found_chapter_with_zero_concepts_is_a_found_chapter(self):
        ch = {"chapter_id": "class-9-empty", "title": "Empty Chapter", "concepts": []}
        cfg = _tmp_cfg([ch])
        resolved = syllabus.resolve_chapter(cfg, "Empty Chapter", 9)
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved["chapter_id"], "class-9-empty")
        self.assertEqual(syllabus.curated_concept_ids(cfg, "class-9-empty"), [])
        self.assertEqual(syllabus.syllabus_state(cfg), "ok")

    def test_missing_syllabus_state(self):
        cfg = _tmp_cfg([])
        (cfg.root / "sources" / "syllabus" / "syllabus.json").unlink()
        self.assertEqual(syllabus.syllabus_state(cfg), "missing")
        self.assertIsNone(syllabus.load_syllabus(cfg))

    def test_corrupt_syllabus_state(self):
        cfg = _tmp_cfg([], corrupt=True)
        self.assertEqual(syllabus.syllabus_state(cfg), "corrupt")
        self.assertIsNone(syllabus.load_syllabus(cfg))


class TestCuratedConceptRecords(unittest.TestCase):
    def test_records_carry_title_and_description(self):
        ch = {
            "chapter_id": "class-9-motion",
            "title": "Motion",
            "concepts": [
                {"concept_id": "k2", "title": "Forces", "description": "Push"},
                {
                    "concept_id": "k1",
                    "title": "Motion",
                    "description": "Change of place",
                },
            ],
        }
        cfg = _tmp_cfg([ch])
        records = syllabus.curated_concepts(cfg, "class-9-motion")
        self.assertEqual([r["concept_id"] for r in records], ["k1", "k2"])
        self.assertEqual(records[0]["description"], "Change of place")


class TestTrackedMapPersistence(unittest.TestCase):
    """Atomic writes, canonical keying, and loud StageError persistence."""

    def _cfg_with_chapter(self) -> Config:
        ch = {
            "chapter_id": "class-9-motion",
            "title": "Motion",
            "concepts": [{"concept_id": "k1", "title": "Motion", "description": ""}],
        }
        return _tmp_cfg([ch])

    def _run_ctx(self, cfg: Config):
        from factory.artifacts import RunContext

        return RunContext(cfg.repo_path(cfg.paths["runs"]), "t-map")

    def _render_out(self, chapter_title: str = "Motion") -> dict:
        return {
            "manifest": {
                "chapter_id": "class-9-motion",
                "class": 9,
                "topic_slug": "motion",
                "course_id": "class-9-physics",
                "chapter": {"title": chapter_title},
            }
        }

    def test_payload_keys_by_the_canonical_chapter_id(self):
        # the renderer key is TRUNCATED for long ids; the tracked file must
        # still be keyed by the curated chapter's canonical id
        long_ch = {
            "chapter_id": "class-9-sound-waves-characteristics-and-applications",
            "title": "Sound Waves: Characteristics and Applications",
            "concepts": [{"concept_id": "sw-1", "title": "Pitch", "description": ""}],
        }
        cfg = _tmp_cfg([long_ch])
        run_ctx = self._run_ctx(cfg)
        render_out = {
            "manifest": {
                "chapter_id": "class-9-sound-waves-characteristics-and-applicat",
                "class": 9,
                "topic_slug": "sound-waves",
                "course_id": "class-9-physics",
                "chapter": {"title": "Sound Waves: Characteristics and Applications"},
            }
        }
        payload = syllabus.tracked_map_payload_for_run(
            cfg, run_ctx, render_out, {"sec-01": "sw-1"}
        )
        self.assertIsNotNone(payload)
        self.assertEqual(
            payload["chapter_id"],
            "class-9-sound-waves-characteristics-and-applications",
        )

    def test_tracked_write_is_atomic_and_complete(self):
        cfg = self._cfg_with_chapter()
        run_ctx = self._run_ctx(cfg)
        path = syllabus.write_tracked_map(
            cfg, run_ctx, self._render_out(), {"sec-01": "k1"}
        )
        self.assertIsNotNone(path)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["section_concept_map"], {"sec-01": "k1"})
        # no temp file survives an atomic write
        self.assertEqual([p.name for p in path.parent.iterdir()], [path.name])

    def test_tracked_write_failure_raises_persistence_error(self):
        from factory.errors import PersistenceError

        cfg = self._cfg_with_chapter()
        run_ctx = self._run_ctx(cfg)
        blocked = cfg.root / "blocked"  # a FILE, not a directory
        blocked.write_text("not a directory", encoding="utf-8")
        with (
            mock.patch(
                "factory.syllabus.tracked_map_path", return_value=blocked / "m.json"
            ),
            self.assertRaises(PersistenceError),
        ):
            syllabus.write_tracked_map(
                cfg, run_ctx, self._render_out(), {"sec-01": "k1"}
            )

    def test_durable_run_artifact_round_trips_the_payload(self):
        cfg = self._cfg_with_chapter()
        run_ctx = self._run_ctx(cfg)
        payload = syllabus.tracked_map_payload_for_run(
            cfg, run_ctx, self._render_out(), {"sec-01": "k1"}
        )
        artifact = syllabus.write_run_artifact(run_ctx, payload)
        self.assertEqual(json.loads(artifact.read_text(encoding="utf-8")), payload)
        self.assertEqual(
            artifact,
            syllabus.concept_map_artifact_path(run_ctx),
        )


if __name__ == "__main__":
    unittest.main()
