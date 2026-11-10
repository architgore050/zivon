"""Config loading and validation.

Two layers, deliberately separate:

- config.json (committed at the repo root): the pipeline's BEHAVIOUR -
  learner, retrieval, limits, paths, perf, repair, translation,
  stage_overrides. Reviewable in git, identical on every machine. Validation is
  strict: unknown keys and wrong types are hard errors, because a typo in
  config must crash immediately, not silently run with defaults.
- Environment variables: everything about WHICH model path to talk to
  (base url, model name, key, sampling and streaming knobs). Per AGENTS.md
  ("configuration lives in environment variables") and the deployment rule
  (secrets enter runtime only), these never appear in any file, image,
  manifest or artifact.

Required environment variables:
    ZIVON_BASE_URL   OpenAI-format base, e.g. http://127.0.0.1:8000/v1
                     (locally the server or the llm_manager node; in the
                     cluster the llm_manager Service - see config-reference.md)
    ZIVON_MODEL      model name exactly as the server reports it
Optional environment variables (defaults in parentheses):
    ZIVON_API_KEY    (unset = no Authorization header)
    ZIVON_JSON_MODE  (true)  response_format json_object
    ZIVON_TEMPERATURE(0.2)
    ZIVON_TIMEOUT_S  (3600)  NOW (2026-11-07): max inactivity between streamed
                             chunks (read timeout only when ZIVON_STREAM=false)
    ZIVON_MAX_ATTEMPTS(3)    transport retries inside one model call
    ZIVON_STREAM     (true)  streaming model calls (the honest timeout path)
    ZIVON_STREAM_USAGE (true) usage stats in the final stream chunk
    ZIVON_CALL_DEADLINE_S (0) total wall-clock cap per model call (0 = none)
    ZIVON_CONNECT_TIMEOUT_S (10)
    ZIVON_BACKOFF_BASE_S (2.0)
    ZIVON_HEARTBEAT_S (60)   progress-print cadence
    ZIVON_VALIDATION_ROUNDS (5) the model's own repair budget per stage call
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
    "10a-translate",
    "10b-transcheck",
    "10c-transrepair",
    "10d-transrender",
    "11-link",
    "12-narration",
]

SUPPORTED_TARGET_LOCALES = {
    "hi",
    "hi-Latn",
    "ta",
    "te",
    "mr",
    "bn",
    "gu",
    "kn",
    "ml",
    "pa",
}

_DEFAULT_TRANSLATION: dict[str, Any] = {
    "enabled": False,
    "target_locales": ["hi", "hi-Latn"],
    "optional_locales": [],
    "glossary_path": "sources/glossary/physics_glossary.json",
    "ui_strings_path": "sources/glossary/ui_strings.json",
    "prompt_version": "1",
    "max_chars_neighbour_context": 600,
}

_SPEC: dict[str, Any] = {
    "learner": {"language": str},
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
    "repair": {
        "content_rounds": int,
        "code_rounds": int,
        "translation_rounds": int,
        "stall_rounds": int,
    },
    "translation": {
        "enabled": bool,
        "target_locales": list,
        "optional_locales": list,
        "glossary_path": str,
        "ui_strings_path": str,
        "prompt_version": str,
        "max_chars_neighbour_context": int,
    },
    "stage_overrides": dict,
}

_SERVER_DEFAULTS: dict[str, Any] = {
    "json_mode": True,
    "temperature": 0.2,
    # No completion cap is sent at all (2026-11-04 founder decision, removing
    # the 0.2.8 huge-max_tokens workaround): qwen thinks a lot and then gets
    # things right - one review call measured 49,750 completion tokens, mostly
    # thinking - so the server's own context decides answer length. timeout_s
    # stays huge: it kills a genuinely hung call on its own; there is no
    # wall-clock cap on the run itself (founder decision 2026-11-06).
    "timeout_s": 3600.0,
    # max_attempts is the TRANSPORT budget only (2026-11-06 founder decision):
    # connection errors / timeouts / 429 / 5xx retried inside one model call.
    "max_attempts": 3,
    # Streaming model calls (2026-11-07): bytes flow as tokens are generated,
    # so timeout_s means INACTIVITY between chunks (an honest dead-server
    # signal) and call_deadline_s can abort a runaway generation mid-stream.
    "stream": True,
    "stream_usage": True,
    "call_deadline_s": 0.0,
    "connect_timeout_s": 10.0,
    "backoff_base_s": 2.0,
    "heartbeat_s": 60.0,
    # validation_rounds is the model's own repair budget: how many times a
    # stage call may produce output that fails JSON/schema/rule validation
    # and get the exact violation fed back to fix it (errors-as-context).
    # Sharing one tiny budget with transport retries made every stage depend
    # on the model one-shotting its output - founder decision 2026-11-06 to
    # separate and widen it: the pipeline is continuous improvement.
    "validation_rounds": 5,
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

    @property
    def translation(self) -> dict[str, Any]:
        return self.data["translation"]

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

    def with_class_level(self, class_level: int) -> Config:
        """Derived view carrying the run's learner class.

        config.json holds NO class (founder decision 2026-11-06: a config
        default for a per-run value is just a hardcode with extra steps). The
        class enters a run exactly one way per source: the --class CLI flag
        (run_pipeline) or the class of the chapter actually located
        (01-locate handoff). The original config is never mutated."""
        if not isinstance(class_level, int) or isinstance(class_level, bool):
            raise ConfigError(
                f"learner.class_level must be an int (got {class_level!r})"
            )
        if class_level not in range(6, 13):
            raise ConfigError(f"learner.class_level must be 6..12 (got {class_level})")
        data = dict(self.data)
        data["learner"] = {**data["learner"], "class_level": class_level}
        return Config(data=data, server=self.server, root=self.root)

    def with_locales(self, locales: list[str]) -> Config:
        """Derived view enabling translation for the specified target locales."""
        _validate_locale_list(locales, "translation.target_locales")
        if not locales:
            raise ConfigError("translation.target_locales must not be empty")
        data = dict(self.data)
        data["translation"] = {
            **data["translation"],
            "enabled": True,
            "target_locales": list(locales),
        }
        return Config(data=data, server=self.server, root=self.root)

    def learner_class(self) -> int:
        """The run's learner class. Set by --class or by 01-locate's chapter;
        a stage asking for it before either is a wiring bug - fail loudly,
        never guess."""
        value = self.data["learner"].get("class_level")
        if value is None:
            raise ConfigError(
                "this run has no learner class yet: it comes from --class or "
                "from the chapter located by 01-locate - a stage used it too early"
            )
        return value


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
            "  export ZIVON_BASE_URL=http://127.0.0.1:8080/v1   # your OpenAI-format base\n"
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
    validation_rounds = _env_number("ZIVON_VALIDATION_ROUNDS", 5, integer=True)
    if validation_rounds < 1:
        raise ConfigError("ZIVON_VALIDATION_ROUNDS must be >= 1")
    temperature = _env_number("ZIVON_TEMPERATURE", 0.2, integer=False)
    if not 0.0 <= temperature <= 2.0:
        raise ConfigError("ZIVON_TEMPERATURE must be between 0.0 and 2.0")
    timeout_s = _env_number("ZIVON_TIMEOUT_S", 3600.0, integer=False)
    if timeout_s < 5:
        raise ConfigError("ZIVON_TIMEOUT_S must be >= 5 seconds")
    connect_timeout_s = _env_number("ZIVON_CONNECT_TIMEOUT_S", 10.0, integer=False)
    if connect_timeout_s < 1:
        raise ConfigError("ZIVON_CONNECT_TIMEOUT_S must be >= 1 second")
    call_deadline_s = _env_number("ZIVON_CALL_DEADLINE_S", 0.0, integer=False)
    if call_deadline_s < 0:
        raise ConfigError("ZIVON_CALL_DEADLINE_S must be >= 0 (0 = no cap)")
    backoff_base_s = _env_number("ZIVON_BACKOFF_BASE_S", 2.0, integer=False)
    if backoff_base_s < 0:
        raise ConfigError("ZIVON_BACKOFF_BASE_S must be >= 0")
    heartbeat_s = _env_number("ZIVON_HEARTBEAT_S", 60.0, integer=False)
    if heartbeat_s < 1:
        raise ConfigError("ZIVON_HEARTBEAT_S must be >= 1 second")
    # Gateway routing headers (2026-11-10 OpenCode Go: x-opencode-session).
    # The node path already reads these; the factory path must forward them
    # too, or every call to the Go gateway fails with MissingSessionID.
    extra_headers: dict[str, str] = {}
    raw_headers = _env_raw("ZIVON_EXTRA_HEADERS")
    if raw_headers:
        try:
            parsed_headers = json.loads(raw_headers)
        except json.JSONDecodeError as exc:
            raise ConfigError(
                "ZIVON_EXTRA_HEADERS must be a JSON object of header names to "
                f'values, e.g. \'{{"x-opencode-session": "zivon-factory"}}\': {exc}'
            ) from exc
        if not isinstance(parsed_headers, dict):
            raise ConfigError("ZIVON_EXTRA_HEADERS must be a JSON object")
        extra_headers = {str(k): str(v) for k, v in parsed_headers.items()}
    return {
        "base_url": base_url,
        "api_key": _env_raw("ZIVON_API_KEY"),
        "model": model,
        "json_mode": _env_bool("ZIVON_JSON_MODE", True),
        "temperature": temperature,
        "timeout_s": timeout_s,
        "max_attempts": max_attempts,
        "stream": _env_bool("ZIVON_STREAM", True),
        "stream_usage": _env_bool("ZIVON_STREAM_USAGE", True),
        "call_deadline_s": call_deadline_s,
        "connect_timeout_s": connect_timeout_s,
        "backoff_base_s": backoff_base_s,
        "validation_rounds": validation_rounds,
        "heartbeat_s": heartbeat_s,
        "extra_headers": extra_headers,
        "user_agent": _env_raw("ZIVON_USER_AGENT") or "",
        "reasoning_effort": _env_raw("ZIVON_REASONING_EFFORT") or None,
    }


def _validate_locale_list(locales: list[Any], field_name: str) -> None:
    for loc in locales:
        if not isinstance(loc, str):
            raise ConfigError(
                f"{field_name} entries must be strings (got {type(loc).__name__})"
            )
        if loc == "ur":
            raise ConfigError(
                f"{field_name}: 'ur' (Urdu RTL) is explicitly out of scope in v1/P1 "
                "(ADR-0009 / SP2-TRANS §2.1)"
            )
        if loc not in SUPPORTED_TARGET_LOCALES:
            raise ConfigError(
                f"{field_name} contains unsupported locale {loc!r}. "
                f"Supported target locales: {sorted(SUPPORTED_TARGET_LOCALES)}"
            )


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

    if "class_level" in data.get("learner", {}):
        raise ConfigError(
            f"{cfg_path}: learner.class_level is no longer a config value "
            "(founder decision 2026-11-06). The run's class comes from the "
            "--class flag or from the chapter actually located. Delete the key."
        )

    # Backfill additive translation keys for legacy v7 test fixtures that
    # construct minimal config dicts without the translation section.
    if "translation" not in data:
        data["translation"] = json.loads(json.dumps(_DEFAULT_TRANSLATION))
    if (
        isinstance(data.get("repair"), dict)
        and "translation_rounds" not in data["repair"]
    ):
        data["repair"]["translation_rounds"] = 6

    _validate(data, _SPEC, cfg_path)

    if data["learner"]["language"] != "en":
        raise ConfigError(
            "learner.language: only 'en' is supported in v1 (English-only material, "
            "founder decision 2026-11-01). Extend factory/agents.py deliberately to add more."
        )
    if data["retrieval"]["chunk_overlap"] >= data["retrieval"]["chunk_chars"]:
        raise ConfigError(
            "retrieval.chunk_overlap must be smaller than retrieval.chunk_chars"
        )
    if data["perf"]["fix_rounds"] < 1 or data["perf"]["fix_rounds"] > 20:
        raise ConfigError("perf.fix_rounds must be 1..20")
    if data["repair"]["content_rounds"] < 1 or data["repair"]["content_rounds"] > 20:
        raise ConfigError("repair.content_rounds must be 1..20")
    if data["repair"]["code_rounds"] < 1 or data["repair"]["code_rounds"] > 20:
        raise ConfigError("repair.code_rounds must be 1..20")
    if (
        data["repair"]["translation_rounds"] < 1
        or data["repair"]["translation_rounds"] > 20
    ):
        raise ConfigError("repair.translation_rounds must be 1..20")
    if data["repair"]["stall_rounds"] < 1 or data["repair"]["stall_rounds"] > 10:
        raise ConfigError("repair.stall_rounds must be 1..10")

    trans = data["translation"]
    _validate_locale_list(trans["target_locales"], "translation.target_locales")
    _validate_locale_list(trans["optional_locales"], "translation.optional_locales")
    if trans["enabled"] and not trans["target_locales"]:
        raise ConfigError(
            "translation.target_locales must not be empty when translation.enabled is true"
        )
    if (
        trans["max_chars_neighbour_context"] < 100
        or trans["max_chars_neighbour_context"] > 4000
    ):
        raise ConfigError("translation.max_chars_neighbour_context must be 100..4000")
    if not trans["prompt_version"].strip():
        raise ConfigError("translation.prompt_version must not be empty")

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
