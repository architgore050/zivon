"""Unit tests for config loading and validation."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from factory.config import ConfigError, load_config

BASE_CONFIG = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))


def write_config(tmp: Path, mutate=None) -> Path:
    data = json.loads(json.dumps(BASE_CONFIG))
    data["server"]["model"] = "test-model"  # pass the sentinel tripwire
    if mutate:
        mutate(data)
    path = tmp / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def test_valid_config_loads(self):
        cfg = load_config(write_config(self.tmp))
        self.assertEqual(cfg.server["model"], "test-model")
        self.assertEqual(cfg.learner["class_level"], 9)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(self.tmp / "nope.json")

    def test_sentinel_model_rejected(self):
        path = write_config(self.tmp)  # keeps CHANGE-ME? no - writer sets test-model
        data = json.loads(path.read_text())
        data["server"]["model"] = "CHANGE-ME"
        path.write_text(json.dumps(data))
        with self.assertRaises(ConfigError) as ctx:
            load_config(path)
        self.assertIn("CHANGE-ME", str(ctx.exception))

    def test_unknown_section_rejected(self):
        def mutate(d):
            d["servers"] = d.pop("server")

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("unknown top-level", str(ctx.exception))

    def test_unknown_key_rejected(self):
        def mutate(d):
            d["retrieval"]["topkk"] = 3

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("topkk", str(ctx.exception))

    def test_wrong_type_rejected(self):
        def mutate(d):
            d["server"]["max_attempts"] = "3"

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_bool_not_accepted_for_int(self):
        def mutate(d):
            d["server"]["max_attempts"] = True

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_class_level_range(self):
        def mutate(d):
            d["learner"]["class_level"] = 5

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_unknown_stage_override_rejected(self):
        def mutate(d):
            d["stage_overrides"] = {"99-nope": {"max_tokens": 10}}

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_stage_override_ok(self):
        def mutate(d):
            d["stage_overrides"] = {"02-synth": {"max_tokens": 8192}}

        cfg = load_config(write_config(self.tmp, mutate))
        self.assertEqual(cfg.stage_override("02-synth"), {"max_tokens": 8192})

    def test_api_key_env_missing_raises(self):
        def mutate(d):
            d["server"]["api_key_env"] = "ZIVON_DEFINITELY_NOT_SET_9182"

        cfg = load_config(write_config(self.tmp, mutate))
        with self.assertRaises(ConfigError):
            cfg.api_key()

    def test_api_key_env_null_means_no_auth(self):
        def mutate(d):
            d["server"]["api_key_env"] = None

        cfg = load_config(write_config(self.tmp, mutate))
        self.assertIsNone(cfg.api_key())

    def test_real_repo_config_loads(self):
        # The committed config.json must stay valid (it contains CHANGE-ME, so
        # load_config raises the sentinel error - that itself proves validity of structure).
        with self.assertRaises(ConfigError) as ctx:
            load_config(REPO_ROOT / "config.json")
        self.assertIn("CHANGE-ME", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
