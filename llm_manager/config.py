"""LLMConfig: every knob of a model call is an input variable.

Constructor arguments are primary; `from_env()` fills them from environment
variables. The env names are the factory's historical ZIVON_* names, so the
factory's environment keeps working unchanged when it moves onto this module.

SEMANTIC CHANGE (2026-11-07, loud on purpose): `timeout_s` is no longer a
total cap. With `stream=True` (the default) it is the maximum INACTIVITY
between streamed chunks - a server generating tokens keeps the call alive, a
dead server is detected honestly. With `stream=False` it degrades to the
classic per-read-operation timeout of a non-streaming POST, which kills
nothing: a non-streaming response sends zero bytes until generation ends.
That gap is why streaming is the default and why `call_deadline_s` exists.

`max_tokens` deliberately has NO environment variable. The factory never sets
it: sending no completion cap is a standing founder decision (2026-11-04 -
Qwen thinks a lot and then gets things right; any cap is a truncation risk).
The knob exists purely so future consumers (translator, voice tooling) can
bound output programmatically from code.

This module is standalone: it imports nothing from factory/.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .errors import LLMManagerError


class LLMConfigError(LLMManagerError):
    """A required variable is missing, non-numeric, or out of range."""


@dataclass(frozen=True)
class LLMConfig:
    """All knobs of a model call. Frozen: a config is not mutated mid-run."""

    base_url: str
    model: str
    api_key: str | None = None
    temperature: float = 0.2
    json_mode: bool = True
    # Max INACTIVITY between streamed chunks (read timeout when not streaming).
    # SEMANTIC CHANGE 2026-11-07 - see the module docstring before changing it.
    timeout_s: float = 3600.0
    connect_timeout_s: float = 10.0
    # Total wall-clock cap per model call. 0 = no cap. On breach the stream is
    # closed mid-generation (which makes the server stop generating) and a
    # TransportError names the deadline.
    call_deadline_s: float = 0.0
    # Transport retries only: connection errors, timeouts, 429, 5xx. The
    # model's own repair budget is validation_rounds and is NOT shared.
    max_attempts: int = 3
    backoff_base_s: float = 2.0
    # The model's own repair budget per structured-output call (validation
    # rounds with the violation fed back). Transport retries do not consume it.
    validation_rounds: int = 5
    stream: bool = True
    # Ask for usage stats in the final stream chunk
    # (stream_options: {"include_usage": true}); set False if the server
    # rejects that field with a 400.
    stream_usage: bool = True
    # Progress-print cadence for observers (was the constant HEARTBEAT_S in
    # the old factory/llm.py).
    heartbeat_s: float = 60.0
    # Constructor-only: no env var on purpose (founder decision 2026-11-04).
    # None = no completion cap is sent.
    max_tokens: int | None = None

    # ------------------------------------------------------------------ env
    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> LLMConfig:
        """Build a config from ZIVON_* environment variables.

        Missing required variables are the tripwire: the error message carries
        a copy-pasteable export example. Non-numeric and out-of-range values
        fail loudly, the way factory/config.py validates its own env vars.
        """
        env_map: dict[str, str] = dict(os.environ) if env is None else dict(env)

        def raw(name: str) -> str | None:
            value = env_map.get(name)
            if value is None or not value.strip():
                return None
            return value.strip()

        base_url = raw("ZIVON_BASE_URL")
        model = raw("ZIVON_MODEL")
        if base_url is None or model is None:
            missing = [
                name
                for name, value in (
                    ("ZIVON_BASE_URL", base_url),
                    ("ZIVON_MODEL", model),
                )
                if value is None
            ]
            raise LLMConfigError(
                f"missing required environment variable(s): {', '.join(missing)}. "
                "Server settings live in the environment, never in files. Export them, e.g.:\n"
                "  export ZIVON_BASE_URL=http://127.0.0.1:8080/v1  # your OpenAI-format base\n"
                "  export ZIVON_MODEL=<model name as GET /v1/models reports it>\n"
                "  export ZIVON_API_KEY=<key>                       # only if your server needs auth\n"
                "(see llm_manager/README.md and .env.example)"
            )
        if not base_url.startswith(("http://", "https://")):
            raise LLMConfigError(
                f"ZIVON_BASE_URL={base_url!r} must start with http:// or https:// "
                "(the /chat/completions path is appended to it)"
            )

        temperature = _number(raw("ZIVON_TEMPERATURE"), 0.2, "ZIVON_TEMPERATURE")
        if not 0.0 <= temperature <= 2.0:
            raise LLMConfigError("ZIVON_TEMPERATURE must be between 0.0 and 2.0")
        timeout_s = _number(raw("ZIVON_TIMEOUT_S"), 3600.0, "ZIVON_TIMEOUT_S")
        if timeout_s < 5:
            raise LLMConfigError("ZIVON_TIMEOUT_S must be >= 5 seconds")
        connect_timeout_s = _number(
            raw("ZIVON_CONNECT_TIMEOUT_S"), 10.0, "ZIVON_CONNECT_TIMEOUT_S"
        )
        if connect_timeout_s < 1:
            raise LLMConfigError("ZIVON_CONNECT_TIMEOUT_S must be >= 1 second")
        call_deadline_s = _number(
            raw("ZIVON_CALL_DEADLINE_S"), 0.0, "ZIVON_CALL_DEADLINE_S"
        )
        if call_deadline_s < 0:
            raise LLMConfigError("ZIVON_CALL_DEADLINE_S must be >= 0 (0 = no cap)")
        max_attempts = int(
            _number(raw("ZIVON_MAX_ATTEMPTS"), 3, "ZIVON_MAX_ATTEMPTS", integer=True)
        )
        if max_attempts < 1:
            raise LLMConfigError("ZIVON_MAX_ATTEMPTS must be >= 1")
        backoff_base_s = _number(
            raw("ZIVON_BACKOFF_BASE_S"), 2.0, "ZIVON_BACKOFF_BASE_S"
        )
        if backoff_base_s < 0:
            raise LLMConfigError("ZIVON_BACKOFF_BASE_S must be >= 0")
        validation_rounds = int(
            _number(
                raw("ZIVON_VALIDATION_ROUNDS"),
                5,
                "ZIVON_VALIDATION_ROUNDS",
                integer=True,
            )
        )
        if validation_rounds < 1:
            raise LLMConfigError("ZIVON_VALIDATION_ROUNDS must be >= 1")
        heartbeat_s = _number(raw("ZIVON_HEARTBEAT_S"), 60.0, "ZIVON_HEARTBEAT_S")
        if heartbeat_s < 1:
            raise LLMConfigError("ZIVON_HEARTBEAT_S must be >= 1 second")

        return cls(
            base_url=base_url,
            model=model,
            api_key=raw("ZIVON_API_KEY"),
            temperature=temperature,
            json_mode=_bool(raw("ZIVON_JSON_MODE"), True, "ZIVON_JSON_MODE"),
            timeout_s=timeout_s,
            connect_timeout_s=connect_timeout_s,
            call_deadline_s=call_deadline_s,
            max_attempts=max_attempts,
            backoff_base_s=backoff_base_s,
            validation_rounds=validation_rounds,
            stream=_bool(raw("ZIVON_STREAM"), True, "ZIVON_STREAM"),
            stream_usage=_bool(raw("ZIVON_STREAM_USAGE"), True, "ZIVON_STREAM_USAGE"),
            heartbeat_s=heartbeat_s,
            # max_tokens intentionally NOT read from the environment (founder
            # decision 2026-11-04): only code can set a completion cap.
        )

    # --------------------------------------------------------------- mapping
    @classmethod
    def from_mapping(cls, server: dict[str, Any]) -> LLMConfig:
        """Build a config from a factory `cfg.server`-style dict.

        Missing optional keys fall back to the dataclass defaults, so older
        server dicts keep working. `api_key` passes through as-is (None = no
        Authorization header). `max_tokens` is not part of factory server
        dicts by design; pass it explicitly if a future consumer needs it.
        """
        known = {
            "base_url",
            "model",
            "api_key",
            "temperature",
            "json_mode",
            "timeout_s",
            "connect_timeout_s",
            "call_deadline_s",
            "max_attempts",
            "backoff_base_s",
            "validation_rounds",
            "stream",
            "stream_usage",
            "heartbeat_s",
        }
        unknown = set(server) - known
        if unknown:
            raise LLMConfigError(
                f"unknown server setting(s) {sorted(unknown)} - llm_manager does "
                "not accept them (max_tokens is constructor-only by design)"
            )
        fields = {f.name for f in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        return cls(**{key: server[key] for key in server if key in fields})


# ------------------------------------------------------------------ env helpers
def _number(
    raw: str | None, default: float, name: str, *, integer: bool = False
) -> float:
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise LLMConfigError(
            f"environment variable {name}={raw!r} is not a number "
            f"(expected {'an integer' if integer else 'a number'})"
        ) from exc
    if integer and value != int(value):
        raise LLMConfigError(f"environment variable {name}={raw!r} must be an integer")
    return value


def _bool(raw: str | None, default: bool, name: str) -> bool:
    if raw is None:
        return default
    lowered = raw.lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise LLMConfigError(
        f"environment variable {name}={raw!r} must be true/false (or 1/0, yes/no)"
    )
