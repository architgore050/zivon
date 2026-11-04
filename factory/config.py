"""Config loading and validation.

Two layers, deliberately separate:

- config.json (committed at the repo root): the pipeline's BEHAVIOUR -
  learner, retrieval, limits, paths, perf, stage_overrides. Reviewable in
  git, identical on every machine. Validation is strict: unknown keys and
  wrong types are hard errors, because a typo in config must crash
  immediately, not silently run with defaults.
- Environment variables: everything about WHICH inference server to talk to
  (base url, model name, key, sampling knobs). Per AGENTS.md ("configuration
  lives in environment variables") and the deployment rule (secrets enter
  runtime only), these never appear in any file, image, manifest or artifact.

Required environment variables:
    ZIVON_BASE_URL   OpenAI-format base, e.g. http://127.0.0.1:8000/v1
    ZIVON_MODEL      model name exactly as the server reports it
Optional environment variables (defaults in parentheses):
    ZIVON_API_KEY    (unset = no Authorization header)
    ZIVON_JSON_MODE  (true)  response_format json_object
    ZIVON_TEMPERATURE(0.2)
    ZIVON_TIMEOUT_S  (3600)   a giant generation call is legitimate
    ZIVON_MAX_ATTEMPTS(3)
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

_STAGE_IDS = [
    "00-ingest",
    "01-locate",
    "02-generate",
    "03-check",
    "04-repair",
    "05-interactive",
    "06-render",
    "07-perf",
    "08-fixloop",
    "09-review",
    "10-reviewfix",
    "11-link",
]

_SPEC: dict[str, Any] = {
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
        "max_chars_design_context": int,
    },
    "paths": {
        "catalog": str,
        "pdf_cache": str,
        "text_cache": str,
        "runs": str,
        "frontend": str,
        "doctrine": str,
        "doctrine_examples": str,
    },
    "perf": {"profile": str, "fix_rounds": int},
    "repair": {"content_rounds": int, "code_rounds": int},
    "stage_overrides": dict,
}

_SERVER_DEFAULTS: dict[str, Any] = {
    "json_mode": True,
    "temperature": 0.2,
    # No completion cap is sent at all (2026-11-04 founder decision, removing
    # the 0.2.8 huge-max_tokens workaround): qwen thinks a lot and then gets
    # things right - one review call measured 49,750 completion tokens, mostly
    # thinking - so the server's own context decides answer length. timeout_s
    # stays huge; the Job's activeDeadlineSeconds is the backstop.
    "timeout_s": 3600.0,
    "max_attempts": 3,
}


@dataclass(frozen=True)
class Config:
    """Validated view: file sections in `data`, server settings from env."""

    data: dict[str, Any]
    server: dict[str, Any]
    root: Path = REPO_ROOT

    # -- section accessors -------------------------------------------------
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

    @property
    def repair(self) -> dict[str, Any]:
        return self.data["repair"]

    # -- derived ------------------------------------------------------------
    def repo_path(self, configured: str) -> Path:
        p = Path(configured)
        return p if p.is_absolute() else self.root / p

    def stage_override(self, stage_id: str) -> dict[str, Any]:
        ov = self.data["stage_overrides"].get(stage_id)
        if ov is None:
            return {}
        if not isinstance(ov, dict) or not set(ov) <= {"temperature"}:
            raise ConfigError(
                f"stage_overrides['{stage_id}'] must be an object with only "
                "a 'temperature' key"
            )
        return ov

    def api_key(self) -> str | None:
        """The API key, read from ZIVON_API_KEY. None means no auth header.

        The key never appears in config.json, logs, or artifacts.
        """
        return self.server["api_key"]


# --------------------------------------------------------------- server from env
def _env_raw(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def _env_number(name: str, default: float, *, integer: bool) -> float | int:
    raw = _env_raw(name)
    if raw is None:
        return int(default) if integer else default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(
            f"environment variable {name}={raw!r} is not a number "
            f"(expected {default if integer is False else int(default)})"
        ) from exc
    if integer:
        if value != int(value):
            raise ConfigError(f"environment variable {name}={raw!r} must be an integer")
        return int(value)
    return value


def _env_bool(name: str, default: bool) -> bool:
    raw = _env_raw(name)
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise ConfigError(
        f"environment variable {name}={raw!r} must be true/false (or 1/0, yes/no)"
    )


def _load_server_from_env() -> dict[str, Any]:
    """Build the server section from the environment. Missing required vars
    are the tripwire: the pipeline refuses to start without them."""
    base_url = _env_raw("ZIVON_BASE_URL")
    model = _env_raw("ZIVON_MODEL")
    if base_url is None or model is None:
        missing = [
            name
            for name, value in (
                ("ZIVON_BASE_URL", base_url),
                ("ZIVON_MODEL", model),
            )
            if value is None
        ]
        raise ConfigError(
            f"missing required environment variable(s): {', '.join(missing)}. "
            "Server settings live in the environment, never in files. Export them, e.g.:\n"
            "  export ZIVON_BASE_URL=http://127.0.0.1:8000/v1   # your OpenAI-format base\n"
            "  export ZIVON_MODEL=<model name as GET /v1/models reports it>\n"
            "  export ZIVON_API_KEY=<key>                        # only if your server needs auth\n"
            "(see docs/content-factory/config-reference.md and .env.example)"
        )
    if model == "CHANGE-ME":
        raise ConfigError(
            'ZIVON_MODEL is still the "CHANGE-ME" placeholder. Set it to the '
            "model name your server reports (e.g. via GET /v1/models)."
        )
    if not base_url.startswith(("http://", "https://")):
        raise ConfigError(
            f"ZIVON_BASE_URL={base_url!r} must start with http:// or https:// "
            "(the /chat/completions path is appended to it)"
        )
    max_attempts = _env_number("ZIVON_MAX_ATTEMPTS", 3, integer=True)
    if max_attempts < 1:
        raise ConfigError("ZIVON_MAX_ATTEMPTS must be >= 1")
    temperature = _env_number("ZIVON_TEMPERATURE", 0.2, integer=False)
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError("ZIVON_TEMPERATURE must be between 0.0 and 2.0")
    timeout_s = _env_number("ZIVON_TIMEOUT_S", 3600.0, integer=False)
    if timeout_s < 5:
        raise ConfigError("ZIVON_TIMEOUT_S must be >= 5 seconds")
    return {
        "base_url": base_url,
        "api_key": _env_raw("ZIVON_API_KEY"),
        "model": model,
        "json_mode": _env_bool("ZIVON_JSON_MODE", True),
        "temperature": temperature,
        "timeout_s": timeout_s,
        "max_attempts": max_attempts,
    }


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

    if "server" in data:
        raise ConfigError(
            f"{cfg_path}: the 'server' section is no longer read from files. "
            "Server settings (base_url, model, api key, sampling) come from the "
            "environment: ZIVON_BASE_URL, ZIVON_MODEL, ZIVON_API_KEY, ... "
            "Delete the section and export the variables "
            "(see docs/content-factory/config-reference.md)."
        )

    _validate(data, _SPEC, cfg_path)

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
    if data["repair"]["content_rounds"] < 1:
        raise ConfigError("repair.content_rounds must be >= 1")
    if data["repair"]["code_rounds"] < 1:
        raise ConfigError("repair.code_rounds must be >= 1")
    for stage_id in data["stage_overrides"]:
        if stage_id not in _STAGE_IDS:
            raise ConfigError(
                f"stage_overrides has unknown stage id '{stage_id}'. Valid ids: {_STAGE_IDS}"
            )
    return Config(
        data=data,
        server=_load_server_from_env(),
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
        if not isinstance(keys, dict):
            # Section validated as a whole elsewhere (e.g. stage_overrides: dict).
            if not isinstance(data[section], keys):
                raise ConfigError(
                    f"{cfg_path}: section '{section}' must be {keys.__name__}"
                )
            continue
        if not isinstance(data[section], dict):
            raise ConfigError(f"{cfg_path}: section '{section}' must be an object")
        for key, expected in keys.items():
            if key not in data[section]:
                raise ConfigError(f"{cfg_path}: missing required key '{section}.{key}'")
            value = data[section][key]
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
