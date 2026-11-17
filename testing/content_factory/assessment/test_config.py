"""Assessment config: key-free dry run, strict validation, CLI overrides."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from factory.assessment.config import (
    DEFAULT_ASSESSMENT_SECTION,
    AssessmentConfig,
    AssessmentConfigError,
)
from factory.config import ConfigError, load_config

REPO_ROOT = Path(__file__).resolve().parents[3]


class TestAssessmentConfig(unittest.TestCase):
    def test_for_repo_builds_tracked_paths_and_policy(self) -> None:
        cfg = AssessmentConfig.for_repo(REPO_ROOT)
        self.assertEqual(
            cfg.syllabus_path, REPO_ROOT / "sources" / "syllabus" / "syllabus.json"
        )
        self.assertEqual(
            cfg.chapters_dir, REPO_ROOT / "sources" / "syllabus" / "chapters"
        )
        self.assertEqual(cfg.policy.min_items, 15)
        self.assertEqual(cfg.policy.max_items, 20)
        self.assertEqual(cfg.generator, "seed")
        self.assertEqual(cfg.languages, ("en", "hi", "hi-Latn"))

    def test_section_overrides_reach_the_policy(self) -> None:
        cfg = AssessmentConfig.for_repo(
            REPO_ROOT,
            section={"min_items_per_chapter": 10, "max_items_per_chapter": 12},
        )
        self.assertEqual(cfg.policy.min_items, 10)
        self.assertEqual(cfg.policy.max_items, 12)

    def test_language_set_is_fixed(self) -> None:
        with self.assertRaises(AssessmentConfigError):
            AssessmentConfig.for_repo(REPO_ROOT, section={"languages": ["en"]})

    def test_unknown_generator_is_refused(self) -> None:
        with self.assertRaises(AssessmentConfigError):
            AssessmentConfig.for_repo(REPO_ROOT, generator="magic")

    def test_from_config_applies_cli_overrides(self) -> None:
        cfg = load_config(REPO_ROOT / "config.json", require_server=False)
        with tempfile.TemporaryDirectory() as td:
            override = Path(td)
            assessment = AssessmentConfig.from_config(
                cfg, generator="seed", export_dir=override, runs_dir=override / "runs"
            )
            self.assertEqual(assessment.export_dir, override)
            self.assertEqual(assessment.runs_dir, override / "runs")
            self.assertIs(assessment.model_cfg, cfg)

    def test_default_section_is_present_in_the_committed_config(self) -> None:
        data = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertEqual(data["assessment"], DEFAULT_ASSESSMENT_SECTION)


class TestConfigLoader(unittest.TestCase):
    def test_dry_run_load_does_not_require_a_model_endpoint(self) -> None:
        with mock.patch.dict(
            os.environ, {"ZIVON_BASE_URL": "", "ZIVON_MODEL": ""}, clear=False
        ):
            cfg = load_config(REPO_ROOT / "config.json", require_server=False)
        self.assertEqual(cfg.server["base_url"], "")
        self.assertEqual(cfg.server["model"], "unconfigured")

    def test_lesson_pipeline_still_requires_the_endpoint(self) -> None:
        with (
            mock.patch.dict(
                os.environ, {"ZIVON_BASE_URL": "", "ZIVON_MODEL": ""}, clear=False
            ),
            self.assertRaises(ConfigError),
        ):
            load_config(REPO_ROOT / "config.json")

    def test_legacy_config_without_the_section_still_loads(self) -> None:
        data = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        data.pop("assessment")
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            cfg = load_config(path, require_server=False)
        self.assertEqual(cfg.data["assessment"], DEFAULT_ASSESSMENT_SECTION)

    def _config_with(self, **assessment_overrides) -> Path:
        data = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        data["assessment"].update(assessment_overrides)
        tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - deleted below
            "w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(data, tmp)
        tmp.close()
        self.addCleanup(Path(tmp.name).unlink)
        return Path(tmp.name)

    def test_invalid_generator_is_refused(self) -> None:
        path = self._config_with(generator="magic")
        with self.assertRaises(ConfigError):
            load_config(path, require_server=False)

    def test_invalid_item_bounds_are_refused(self) -> None:
        path = self._config_with(min_items_per_chapter=25, max_items_per_chapter=20)
        with self.assertRaises(ConfigError):
            load_config(path, require_server=False)

    def test_invalid_language_set_is_refused(self) -> None:
        path = self._config_with(languages=["en", "hi"])
        with self.assertRaises(ConfigError):
            load_config(path, require_server=False)

    def test_assessment_stage_temperature_override_is_allowed(self) -> None:
        data = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        data["stage_overrides"] = {"A3-practice-items": {"temperature": 0.4}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            cfg = load_config(path, require_server=False)
        self.assertEqual(cfg.stage_override("A3-practice-items"), {"temperature": 0.4})

    def test_unknown_assessment_stage_override_is_refused(self) -> None:
        data = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        data["stage_overrides"] = {"A9-nope": {"temperature": 0.4}}
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_config(path, require_server=False)


if __name__ == "__main__":
    unittest.main()
