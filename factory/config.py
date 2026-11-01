"""Global config loading and validation.

config.json at the repo root is the single source of truth for every tunable.
Validation is strict: unknown keys and wrong types are hard errors, because a
typo in config must crash immediately, not silently run with defaults.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ConfigError

REPO_ROOT = Path(__file__).resolve().parent.parent
# ZIVON_CONFIG lets tests and multi-repo setups point at another config file;
# production always uses config.json at the repo root.
CONFIG_PATH = (
    Path(os.environ["ZIVON_CONFIG"])
    if os.environ.get("ZIVON_CONFIG")
    else REPO_ROOT / "config.json"
)

_SENTINEL_MODEL = "CHANGE-ME"

_STAGE_IDS = [
    "00-ingest",
    "01-locate",
    "02-synth",
    "03-explain",
    "04-draft",
    "05-check",
    "06-interactive",
    "07-render",
    "08-perf",
    "09-fixloop",
    "10-review",
    "11-link",
]

_SPEC: dict[str, Any] = {
    "server": {
        "base_url": str,
        "api_key_env": (str, type(None)),
        "model": str,
        "json_mode": bool,
        "temperature": (int, float),
        "max_tokens": int,
        "timeout_s": (int, float),
        "max_attempts": int,
    },
    "learner": {"class_level": int, "language": str},
    "retrieval": {
        "embedding_model": str,
        "device": str,
        "top_k": int,
        "chunk_chars": int,
        "chunk_overlap": int,
    },
    "limits": {
        "max_chars_ncert_to_model": int,
        "max_chars_supplement_each": int,
        "max_chars_supplement_total": int,
    },
    "paths": {
        "catalog": str,
        "pdf_cache": str,
        "text_cache": str,
        "runs": str,
        "frontend": str,
        "doctrine": str,
        "doctrine_example": str,
    },
    "perf": {"profile": str, "fix_rounds": int},
    "stage_overrides": dict,
}


@dataclass(frozen=True)
class Config:
    """Validated view over config.json. Access raw sections via the mappings."""

    data: dict[str, Any]
    root: Path = REPO_ROOT

    # -- section accessors -------------------------------------------------
    @property
    def server(self) -> dict[str, Any]:
        return self.data["server"]

    @property
    def learner(self) -> dict[str, Any]:
        return self.data["learner"]

    @property
    def retrieval(self) -> dict[str, Any]:
        return self.data["retrieval"]

    @property
    def limits(self) -> dict[str, Any]:
        return self.data["limits"]

    @property
    def paths(self) -> dict[str, Any]:
        return self.data["paths"]

    @property
    def perf(self) -> dict[str, Any]:
        return self.data["perf"]

    # -- derived ------------------------------------------------------------
    def repo_path(self, configured: str) -> Path:
        p = Path(configured)
        return p if p.is_absolute() else self.root / p

    def stage_override(self, stage_id: str) -> dict[str, Any]:
        ov = self.data["stage_overrides"].get(stage_id)
        if ov is None:
            return {}
        if not isinstance(ov, dict) or not set(ov) <= {"temperature", "max_tokens"}:
            raise ConfigError(
                f"stage_overrides['{stage_id}'] must be an object with only "
                "'temperature' and/or 'max_tokens' keys"
            )
        return ov

    def api_key(self) -> str | None:
        """Resolve the API key from the environment variable NAMED in config.

        The key itself never appears in config.json, logs, or artifacts.
        """
        env_name = self.server["api_key_env"]
        if env_name is None:
            return None
        value = os.environ.get(env_name)
        if not value:
            raise ConfigError(
                f"config.json server.api_key_env names environment variable "
                f"'{env_name}' but it is not set. Export it (e.g. `export {env_name}=<key>`) "
                f"or set server.api_key_env to null if your server needs no auth."
            )
        return value


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(
            f"config file not found at {cfg_path}. "
            "config.json at the repo root is required; see docs/content-factory/config-reference.md."
        )
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"{cfg_path} is not valid JSON: {exc}") from exc

    if not isinstance(data, dict):
        raise ConfigError(f"{cfg_path} must contain a JSON object at the top level")

    _validate(data, _SPEC, cfg_path)

    if data["server"]["model"] == _SENTINEL_MODEL:
        raise ConfigError(
            'config.json server.model is still "CHANGE-ME". '
            "Set it to your model name as your OpenAI-format server reports it "
            "(e.g. via GET /v1/models)."
        )
    if data["server"]["max_attempts"] < 1:
        raise ConfigError("server.max_attempts must be >= 1")
    if data["learner"]["class_level"] not in range(6, 13):
        raise ConfigError(
            "learner.class_level must be 6..12 (the catalog covers classes 6-12)"
        )
    if data["learner"]["language"] != "en":
        raise ConfigError(
            "learner.language: only 'en' is supported in v1 (English-only material, "
            "founder decision 2026-11-01). Extend factory/agents.py deliberately to add more."
        )
    if data["retrieval"]["chunk_overlap"] >= data["retrieval"]["chunk_chars"]:
        raise ConfigError(
            "retrieval.chunk_overlap must be smaller than retrieval.chunk_chars"
        )
    if data["perf"]["fix_rounds"] < 1:
        raise ConfigError("perf.fix_rounds must be >= 1")
    for stage_id in data["stage_overrides"]:
        if stage_id not in _STAGE_IDS:
            raise ConfigError(
                f"stage_overrides has unknown stage id '{stage_id}'. Valid ids: {_STAGE_IDS}"
            )
    return Config(
        data=data,
        root=cfg_path.parent.resolve() if cfg_path != CONFIG_PATH else REPO_ROOT,
    )


def _validate(data: dict, spec: dict, cfg_path: Path) -> None:
    unknown_sections = set(data) - set(spec)
    if unknown_sections:
        raise ConfigError(
            f"{cfg_path}: unknown top-level section(s) {sorted(unknown_sections)}. "
            "See docs/content-factory/config-reference.md."
        )
    for section, keys in spec.items():
        if section not in data:
            raise ConfigError(f"{cfg_path}: missing required section '{section}'")
        if not isinstance(data[section], dict):
            raise ConfigError(f"{cfg_path}: section '{section}' must be an object")
        if not isinstance(keys, dict):
            # Section validated as a whole elsewhere (e.g. stage_overrides: dict).
            if not isinstance(data[section], keys):
                raise ConfigError(
                    f"{cfg_path}: section '{section}' must be {keys.__name__}"
                )
            continue
        for key, expected in keys.items():
            if key not in data[section]:
                raise ConfigError(f"{cfg_path}: missing required key '{section}.{key}'")
            value = data[section][key]
            if isinstance(expected, tuple):
                ok = isinstance(value, expected)
            else:
                ok = isinstance(value, expected)
            if expected in ((int, float), int) and isinstance(value, bool):
                ok = False  # bool is an int subclass; reject it explicitly
            if not ok:
                raise ConfigError(
                    f"{cfg_path}: '{section}.{key}' has wrong type "
                    f"(expected {expected}, got {type(value).__name__})"
                )
        unknown = set(data[section]) - set(keys)
        if unknown:
            raise ConfigError(
                f"{cfg_path}: unknown key(s) {sorted(unknown)} in section '{section}'. "
                "See docs/content-factory/config-reference.md for the allowed keys."
            )
