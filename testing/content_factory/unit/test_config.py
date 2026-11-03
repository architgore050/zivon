"""Unit tests for config loading and validation.

Two layers: file sections (learner/retrieval/limits/paths/perf/repair/
stage_overrides) and server settings from the environment. Missing server
env is the tripwire - the pipeline refuses to start without it.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO_ROOT))

from factory.config import ConfigError, load_config

BASE_CONFIG = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))

_SERVER_VARS = (
    "ZIVON_BASE_URL",
    "ZIVON_MODEL",
    "ZIVON_API_KEY",
    "ZIVON_JSON_MODE",
    "ZIVON_TEMPERATURE",
    "ZIVON_TIMEOUT_S",
    "ZIVON_MAX_ATTEMPTS",
)


def write_config(tmp: Path, mutate=None) -> Path:
    data = json.loads(json.dumps(BASE_CONFIG))
    if mutate:
        mutate(data)
    path = tmp / "config.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self._env_saved = {k: os.environ.get(k) for k in _SERVER_VARS}
        os.environ["ZIVON_BASE_URL"] = "http://127.0.0.1:8000/v1"
        os.environ["ZIVON_MODEL"] = "test-model"

    def tearDown(self):
        for key, value in self._env_saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_valid_config_loads(self):
        cfg = load_config(write_config(self.tmp))
        self.assertEqual(cfg.server["model"], "test-model")
        self.assertEqual(cfg.server["base_url"], "http://127.0.0.1:8000/v1")
        self.assertEqual(cfg.learner["class_level"], 9)

    def test_missing_file(self):
        with self.assertRaises(ConfigError):
            load_config(self.tmp / "nope.json")

    def test_missing_base_url_rejected(self):
        os.environ.pop("ZIVON_BASE_URL")
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("ZIVON_BASE_URL", str(ctx.exception))

    def test_missing_model_rejected(self):
        os.environ.pop("ZIVON_MODEL")
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("ZIVON_MODEL", str(ctx.exception))

    def test_blank_env_value_counts_as_missing(self):
        os.environ["ZIVON_MODEL"] = "   "
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("ZIVON_MODEL", str(ctx.exception))

    def test_placeholder_model_rejected(self):
        os.environ["ZIVON_MODEL"] = "CHANGE-ME"
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("CHANGE-ME", str(ctx.exception))

    def test_bad_base_url_scheme_rejected(self):
        os.environ["ZIVON_BASE_URL"] = "127.0.0.1:8000/v1"
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("http://", str(ctx.exception))

    def test_non_numeric_env_rejected(self):
        os.environ["ZIVON_TIMEOUT_S"] = "huge"
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("ZIVON_TIMEOUT_S", str(ctx.exception))

    def test_non_integer_env_rejected(self):
        os.environ["ZIVON_MAX_ATTEMPTS"] = "2.5"
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("integer", str(ctx.exception))

    def test_bad_bool_env_rejected(self):
        os.environ["ZIVON_JSON_MODE"] = "maybe"
        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp))
        self.assertIn("ZIVON_JSON_MODE", str(ctx.exception))

    def test_env_defaults_and_overrides(self):
        cfg = load_config(write_config(self.tmp))
        self.assertIs(cfg.server["json_mode"], True)
        self.assertEqual(cfg.server["temperature"], 0.2)
        self.assertEqual(cfg.server["max_attempts"], 3)
        self.assertIsNone(cfg.server["api_key"])

        os.environ["ZIVON_JSON_MODE"] = "false"
        os.environ["ZIVON_TEMPERATURE"] = "0.7"
        os.environ["ZIVON_MAX_ATTEMPTS"] = "5"
        os.environ["ZIVON_API_KEY"] = "sekret"
        cfg = load_config(write_config(self.tmp))
        self.assertIs(cfg.server["json_mode"], False)
        self.assertEqual(cfg.server["temperature"], 0.7)
        self.assertEqual(cfg.server["max_attempts"], 5)
        self.assertEqual(cfg.api_key(), "sekret")

    def test_out_of_range_env_rejected(self):
        os.environ["ZIVON_MAX_ATTEMPTS"] = "0"
        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp))
        os.environ["ZIVON_TEMPERATURE"] = "9"
        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp))

    def test_server_section_in_file_rejected_with_hint(self):
        def mutate(d):
            d["server"] = {"base_url": "http://x", "model": "m"}

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("no longer read from files", str(ctx.exception))

    def test_unknown_section_rejected(self):
        def mutate(d):
            d["retrievals"] = d.pop("retrieval")

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
            d["retrieval"]["top_k"] = "3"

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_bool_not_accepted_for_int(self):
        def mutate(d):
            d["retrieval"]["top_k"] = True

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_class_level_range(self):
        def mutate(d):
            d["learner"]["class_level"] = 5

        with self.assertRaises(ConfigError):
            load_config(write_config(self.tmp, mutate))

    def test_unknown_stage_override_rejected(self):
        def mutate(d):
            d["stage_overrides"] = {"99-nope": {"temperature": 0.4}}

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("99-nope", str(ctx.exception))

    def test_stage_override_ok(self):
        def mutate(d):
            d["stage_overrides"] = {"02-generate": {"temperature": 0.4}}

        cfg = load_config(write_config(self.tmp, mutate))
        self.assertEqual(cfg.stage_override("02-generate"), {"temperature": 0.4})

    def test_missing_repair_section_rejected(self):
        def mutate(d):
            del d["repair"]

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("repair", str(ctx.exception))

    def test_repair_rounds_below_one_rejected(self):
        def mutate(d):
            d["repair"]["content_rounds"] = 0

        with self.assertRaises(ConfigError) as ctx:
            load_config(write_config(self.tmp, mutate))
        self.assertIn("content_rounds", str(ctx.exception))

    def test_real_repo_config_loads(self):
        # The committed config.json must stay structurally valid; with server
        # env present it loads cleanly (no server section lives in the file).
        cfg = load_config(REPO_ROOT / "config.json")
        self.assertEqual(cfg.learner["class_level"], 9)
        self.assertNotIn("server", cfg.data)
        self.assertEqual(cfg.repair["content_rounds"], 2)
        self.assertEqual(cfg.repair["code_rounds"], 2)


if __name__ == "__main__":
    unittest.main()
