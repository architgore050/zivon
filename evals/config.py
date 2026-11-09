"""Evaluation configuration (`EvalConfig`).

Reads `ZIVON_*` and `ZIVON_EVAL_*` (plus `EVAL_*` aliases) environment variables
with zero secrets stored in files. Supports key-free execution in `--suite smoke`
while building an `llm_manager.LLMConfig` with `temperature=0.0` (ADR-0028) when
judge or reviewer-calibration model calls are invoked.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from llm_manager import LLMConfig, LLMConfigError

REPO_ROOT = Path(__file__).resolve().parents[1]


class EvalConfigError(ValueError):
    """Raised when an eval configuration setting is invalid or missing."""


def _clean_env(env_map: dict[str, str], key: str) -> str | None:
    val = env_map.get(key)
    if val is None or not val.strip():
        return None
    return val.strip()


def _parse_float(raw: str | None, default: float, name: str) -> float:
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise EvalConfigError(
            f"environment variable {name}={raw!r} must be a number"
        ) from exc


def _parse_int(raw: str | None, default: int, name: str) -> int:
    if raw is None:
        return default
    try:
        val = float(raw)
    except ValueError as exc:
        raise EvalConfigError(
            f"environment variable {name}={raw!r} must be an integer"
        ) from exc
    if val != int(val):
        raise EvalConfigError(f"environment variable {name}={raw!r} must be an integer")
    return int(val)


def _parse_bool(raw: str | None, default: bool, name: str) -> bool:
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise EvalConfigError(
        f"environment variable {name}={raw!r} must be true/false (or 1/0, yes/no)"
    )


@dataclass(frozen=True)
class EvalConfig:
    """Immutable configuration for an evaluation run."""

    repo_root: Path = REPO_ROOT
    runs_dir: Path = REPO_ROOT / "runs"
    evals_runs_dir: Path = REPO_ROOT / "evals_runs"
    goldens_dir: Path = REPO_ROOT / "evals" / "goldens"
    cards_dir: Path = REPO_ROOT / "evals" / "cards"
    frontend_dir: Path = REPO_ROOT / "frontend"
    sources_catalog: Path = REPO_ROOT / "sources" / "catalog.json"
    db_url: str | None = None
    store_backend: str = "dual"
    mock_mode: bool = False
    generator_base_url: str | None = None
    generator_model: str = "unconfigured"
    judge_base_url: str | None = None
    judge_model: str = "unconfigured"
    api_key: str | None = None
    timeout_s: float = 600.0
    connect_timeout_s: float = 10.0
    call_deadline_s: float = 1800.0
    max_attempts: int = 3
    backoff_base_s: float = 2.0
    validation_rounds: int = 5
    stream: bool = True
    stream_usage: bool = True
    json_mode: bool = True
    heartbeat_s: float = 60.0
    factory_image_tag: str = "0.3.17"

    @property
    def golden_dir(self) -> Path:
        """Compatibility alias for `goldens_dir`."""
        return self.goldens_dir

    @property
    def code_model(self) -> str:
        """Compatibility alias for `generator_model`."""
        return self.generator_model

    @classmethod
    def from_env(
        cls,
        env: dict[str, str] | None = None,
        *,
        repo_root: Path | None = None,
    ) -> EvalConfig:
        """Construct `EvalConfig` from environment variables.

        Note: `ZIVON_BASE_URL` and `ZIVON_MODEL` are NOT required at config load
        time so `python -m evals run --suite smoke` runs 100% key-free in CI.
        Judge calls validate endpoint presence via `judge_llm_config()`.
        """
        env_map: dict[str, str] = dict(os.environ) if env is None else dict(env)
        root = (repo_root or REPO_ROOT).resolve()

        runs_raw = _clean_env(env_map, "ZIVON_RUNS_DIR")
        evals_runs_raw = _clean_env(env_map, "ZIVON_EVAL_RUNS_DIR") or _clean_env(
            env_map, "EVAL_RUNS_DIR"
        )
        goldens_raw = _clean_env(env_map, "ZIVON_EVAL_GOLDENS_DIR")
        cards_raw = _clean_env(env_map, "ZIVON_EVAL_CARDS_DIR")
        frontend_raw = _clean_env(env_map, "ZIVON_FRONTEND_DIR")

        gen_base = _clean_env(env_map, "ZIVON_BASE_URL")
        gen_model = _clean_env(env_map, "ZIVON_MODEL") or "unconfigured"
        judge_base = _clean_env(env_map, "ZIVON_EVAL_BASE_URL") or gen_base
        judge_model = _clean_env(env_map, "ZIVON_EVAL_JUDGE_MODEL") or gen_model
        api_key = _clean_env(env_map, "ZIVON_EVAL_API_KEY") or _clean_env(
            env_map, "ZIVON_API_KEY"
        )
        db_url = _clean_env(env_map, "ZIVON_DB_URL") or _clean_env(
            env_map, "EVAL_DB_URL"
        )
        store_backend = (
            _clean_env(env_map, "ZIVON_EVAL_STORE_BACKEND")
            or _clean_env(env_map, "EVAL_STORE_BACKEND")
            or "dual"
        )
        mock_raw = _clean_env(env_map, "ZIVON_EVAL_MOCK") or _clean_env(
            env_map, "EVAL_MOCK_MODE"
        )
        mock_mode = _parse_bool(mock_raw, False, "EVAL_MOCK_MODE")

        timeout_s = _parse_float(
            _clean_env(env_map, "ZIVON_TIMEOUT_S"), 600.0, "ZIVON_TIMEOUT_S"
        )
        if timeout_s < 5.0:
            raise EvalConfigError("ZIVON_TIMEOUT_S must be >= 5 seconds")
        connect_timeout_s = _parse_float(
            _clean_env(env_map, "ZIVON_CONNECT_TIMEOUT_S"),
            10.0,
            "ZIVON_CONNECT_TIMEOUT_S",
        )
        if connect_timeout_s < 1.0:
            raise EvalConfigError("ZIVON_CONNECT_TIMEOUT_S must be >= 1 second")
        call_deadline_s = _parse_float(
            _clean_env(env_map, "ZIVON_CALL_DEADLINE_S"),
            1800.0,
            "ZIVON_CALL_DEADLINE_S",
        )
        if call_deadline_s < 0.0:
            raise EvalConfigError("ZIVON_CALL_DEADLINE_S must be >= 0")
        max_attempts = _parse_int(
            _clean_env(env_map, "ZIVON_MAX_ATTEMPTS"), 3, "ZIVON_MAX_ATTEMPTS"
        )
        if max_attempts < 1:
            raise EvalConfigError("ZIVON_MAX_ATTEMPTS must be >= 1")
        backoff_base_s = _parse_float(
            _clean_env(env_map, "ZIVON_BACKOFF_BASE_S"), 2.0, "ZIVON_BACKOFF_BASE_S"
        )
        if backoff_base_s < 0.0:
            raise EvalConfigError("ZIVON_BACKOFF_BASE_S must be >= 0")
        validation_rounds = _parse_int(
            _clean_env(env_map, "ZIVON_VALIDATION_ROUNDS"),
            5,
            "ZIVON_VALIDATION_ROUNDS",
        )
        if validation_rounds < 1:
            raise EvalConfigError("ZIVON_VALIDATION_ROUNDS must be >= 1")
        heartbeat_s = _parse_float(
            _clean_env(env_map, "ZIVON_HEARTBEAT_S"), 60.0, "ZIVON_HEARTBEAT_S"
        )
        if heartbeat_s < 1.0:
            raise EvalConfigError("ZIVON_HEARTBEAT_S must be >= 1 second")

        return cls(
            repo_root=root,
            runs_dir=Path(runs_raw) if runs_raw else root / "runs",
            evals_runs_dir=(
                Path(evals_runs_raw) if evals_runs_raw else root / "evals_runs"
            ),
            goldens_dir=(
                Path(goldens_raw) if goldens_raw else root / "evals" / "goldens"
            ),
            cards_dir=Path(cards_raw) if cards_raw else root / "evals" / "cards",
            frontend_dir=Path(frontend_raw) if frontend_raw else root / "frontend",
            sources_catalog=root / "sources" / "catalog.json",
            db_url=db_url,
            store_backend=store_backend,
            mock_mode=mock_mode,
            generator_base_url=gen_base,
            generator_model=gen_model,
            judge_base_url=judge_base,
            judge_model=judge_model,
            api_key=api_key,
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            call_deadline_s=call_deadline_s,
            max_attempts=max_attempts,
            backoff_base_s=backoff_base_s,
            validation_rounds=validation_rounds,
            stream=_parse_bool(_clean_env(env_map, "ZIVON_STREAM"), True, "ZIVON_STREAM"),
            stream_usage=_parse_bool(
                _clean_env(env_map, "ZIVON_STREAM_USAGE"), True, "ZIVON_STREAM_USAGE"
            ),
            json_mode=_parse_bool(
                _clean_env(env_map, "ZIVON_JSON_MODE"), True, "ZIVON_JSON_MODE"
            ),
            heartbeat_s=heartbeat_s,
            factory_image_tag=(
                _clean_env(env_map, "ZIVON_FACTORY_IMAGE_TAG") or "0.3.17"
            ),
        )

    def judge_llm_config(
        self,
        *,
        call_deadline_s: float | None = None,
        max_tokens: int | None = None,
    ) -> LLMConfig:
        """Build the `llm_manager.LLMConfig` for LLM-as-judge calls (ADR-0028).

        Judge calls always use `temperature=0.0` (greedy decoding) and route
        through `llm_manager`.
        """
        if not self.judge_base_url or self.judge_model == "unconfigured":
            raise LLMConfigError(
                "missing required environment variable(s) for LLM judge: "
                "ZIVON_BASE_URL (or ZIVON_EVAL_BASE_URL) and ZIVON_MODEL "
                "(or ZIVON_EVAL_JUDGE_MODEL). Export them or run `--suite smoke`."
            )
        if not self.judge_base_url.startswith(("http://", "https://")):
            raise LLMConfigError(
                f"judge base_url={self.judge_base_url!r} must start with http:// or https://"
            )
        return LLMConfig(
            base_url=self.judge_base_url,
            model=self.judge_model,
            api_key=self.api_key,
            temperature=0.0,
            json_mode=self.json_mode,
            timeout_s=self.timeout_s,
            connect_timeout_s=self.connect_timeout_s,
            call_deadline_s=(
                self.call_deadline_s if call_deadline_s is None else call_deadline_s
            ),
            max_attempts=self.max_attempts,
            backoff_base_s=self.backoff_base_s,
            validation_rounds=self.validation_rounds,
            stream=self.stream,
            stream_usage=self.stream_usage,
            heartbeat_s=self.heartbeat_s,
            max_tokens=max_tokens,
        )

    def to_factory_server_dict(self) -> dict[str, Any]:
        """Return a `cfg.server`-compatible mapping for `factory.llm.LLMClient`."""
        if not self.judge_base_url or self.judge_model == "unconfigured":
            raise LLMConfigError(
                "cannot build factory server config without ZIVON_BASE_URL and ZIVON_MODEL"
            )
        return {
            "base_url": self.judge_base_url,
            "model": self.judge_model,
            "api_key": self.api_key,
            "temperature": 0.0,
            "json_mode": self.json_mode,
            "timeout_s": self.timeout_s,
            "connect_timeout_s": self.connect_timeout_s,
            "call_deadline_s": self.call_deadline_s,
            "max_attempts": self.max_attempts,
            "backoff_base_s": self.backoff_base_s,
            "validation_rounds": self.validation_rounds,
            "stream": self.stream,
            "stream_usage": self.stream_usage,
            "heartbeat_s": self.heartbeat_s,
        }
