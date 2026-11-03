"""OpenAI-format chat-completions client with full artifact logging.

Failure semantics (no silent fallbacks, ever):
- Network errors, timeouts, 429 and 5xx are retried up to ZIVON_MAX_ATTEMPTS
  with exponential backoff; each attempt's raw request/response is on disk.
- Any other HTTP error fails the stage immediately, with the server's body in
  the message (e.g. a 400 about response_format means: set ZIVON_JSON_MODE=false).
- Output must be a single JSON object. In json_mode the server enforces it;
  either way the text is parsed and validated against a JSON Schema (plus an
  optional extra_validator, e.g. a stage's rule checks). Validation failures
  are retried with the validator's error report fed back to the model, up to
  max_attempts, then the stage fails with SchemaError.

Server settings (base url, model, key, sampling) come from the environment -
see factory/config.py. The API key value is never written to any artifact:
the Authorization header is a header, and only the request body is persisted.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import jsonschema
import requests

from .artifacts import RunContext
from .config import Config
from .errors import ModelCallError, SchemaError

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


def _strip_code_fences(text: str) -> str:
    """Remove a single wrapping markdown code fence if present."""
    t = text.strip()
    if t.startswith("```"):
        first_newline = t.find("\n")
        if first_newline != -1:
            t = t[first_newline + 1 :]
        if t.rstrip().endswith("```"):
            t = t.rstrip()[:-3]
    return t.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse the model output into a JSON object. No salvage heuristics: if the
    model returned prose around the JSON, that is a validation failure and the
    caller retries with feedback."""
    cleaned = _strip_code_fences(text)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"output is not valid JSON: {exc}; first 200 chars: {cleaned[:200]!r}"
        ) from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"expected a JSON object, got {type(parsed).__name__}")  # noqa: TRY004 — ValueError is the contract callers catch
    return parsed


class LLMClient:
    def __init__(self, cfg: Config, run: RunContext):
        self.cfg = cfg
        self.run = run
        self.url = cfg.server["base_url"].rstrip("/") + "/chat/completions"
        self._api_key = cfg.api_key()

    # ------------------------------------------------------------------ call
    def call(
        self,
        stage_id: str,
        messages: list[dict[str, str]],
        schema: dict,
        schema_name: str,
        temperature: float | None = None,
        max_tokens: int | None = None,
        extra_validator: Callable[[dict[str, Any]], list[str]] | None = None,
        round_tag: str | None = None,
    ) -> dict[str, Any]:
        """One logged, validated model call. Returns the parsed JSON object.

        extra_validator: optional code-side check on the PARSED object (e.g.
        the stage's rule checks). Returning a non-empty list of problem
        strings is treated exactly like a schema failure: the problems are
        fed back to the model and the attempt is retried, same budget.

        round_tag: set by repair loops when a stage runs more than once per
        run (e.g. 03-check re-runs after 04-repair). Attempt artifacts then
        land under attempts/<round_tag>/attempt-NN/ so no round overwrites
        another round's evidence."""
        override = self.cfg.stage_override(stage_id)
        temperature = override.get(
            "temperature",
            temperature if temperature is not None else self.cfg.server["temperature"],
        )
        max_tokens = override.get(
            "max_tokens",
            max_tokens if max_tokens is not None else self.cfg.server["max_tokens"],
        )

        base_request = {
            "model": self.cfg.server["model"],
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if self.cfg.server["json_mode"]:
            base_request["response_format"] = {"type": "json_object"}

        # Transcript accumulates validator feedback across attempts.
        transcript = [dict(m) for m in messages]
        last_error = ""
        stage_dir = self.run.stage_dir(stage_id)
        attempts_dir = stage_dir / "attempts"
        if round_tag:
            attempts_dir = attempts_dir / round_tag

        for attempt in range(1, self.cfg.server["max_attempts"] + 1):
            request = dict(base_request)
            request["messages"] = [dict(m) for m in transcript]
            attempt_dir = attempts_dir / f"attempt-{attempt:02d}"
            self.run.write_json(attempt_dir / "request.json", self._redact(request))

            t0 = time.time()
            status, raw_text, usage = self._post(request, stage_id, attempt)
            latency = round(time.time() - t0, 2)
            self.run.write_text(attempt_dir / "response.json", raw_text)
            self.run.write_json(
                attempt_dir / "meta.json",
                {
                    "stage": stage_id,
                    "attempt": attempt,
                    "http_status": status,
                    "latency_s": latency,
                    "usage": usage,
                    "model": self.cfg.server["model"],
                },
            )

            try:
                parsed = parse_json_object(raw_text)
            except ValueError as exc:
                last_error = f"JSON parse failure: {exc}"
                self._feedback(transcript, raw_text, last_error)
                continue

            try:
                jsonschema.validate(instance=parsed, schema=schema)
            except jsonschema.ValidationError as exc:
                last_error = self._format_validation_error(exc)
                self._feedback(
                    transcript, raw_text, f"Schema validation failed: {last_error}"
                )
                continue

            if extra_validator is not None:
                problems = extra_validator(parsed)
                if problems:
                    last_error = "; ".join(problems[:12])
                    self._feedback(
                        transcript,
                        raw_text,
                        f"Rule checks failed: {last_error}",
                    )
                    continue

            return parsed

        raise SchemaError(
            stage_id,
            f"{schema_name}: output failed validation on all "
            f"{self.cfg.server['max_attempts']} attempts. Last error: {last_error}",
            artifacts_dir=str(stage_dir),
        )

    # ------------------------------------------------------------- internals
    def _post(
        self, request: dict, stage_id: str, attempt: int
    ) -> tuple[int, str, dict]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        backoff = 2.0
        for try_no in range(1, self.cfg.server["max_attempts"] + 1):
            try:
                resp = requests.post(
                    self.url,
                    headers=headers,
                    json=request,
                    timeout=self.cfg.server["timeout_s"],
                )
            except (requests.ConnectionError, requests.Timeout) as exc:
                if try_no == self.cfg.server["max_attempts"]:
                    raise ModelCallError(
                        stage_id,
                        f"could not reach inference server at {self.url} after "
                        f"{try_no} tries: {exc}. Is the server running and is "
                        "ZIVON_BASE_URL set correctly?",
                    ) from exc
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code in RETRYABLE_STATUS:
                if try_no == self.cfg.server["max_attempts"]:
                    raise ModelCallError(
                        stage_id,
                        f"server returned HTTP {resp.status_code} on all {try_no} tries. "
                        f"Body: {resp.text[:500]}",
                    )
                time.sleep(backoff)
                backoff *= 2
                continue

            if resp.status_code != 200:
                # Non-retryable client error: crash now with the server's words.
                hint = ""
                if resp.status_code == 400 and "response_format" in resp.text.lower():
                    hint = (
                        " Your server appears not to support response_format json_object;"
                        " set ZIVON_JSON_MODE=false in the environment and re-run."
                    )
                raise ModelCallError(
                    stage_id,
                    f"server rejected the call with HTTP {resp.status_code}: {resp.text[:500]}.{hint}",
                )

            try:
                payload = resp.json()
                content = payload["choices"][0]["message"]["content"]
                usage = payload.get("usage", {})
            except (KeyError, IndexError, ValueError) as exc:
                raise ModelCallError(
                    stage_id,
                    f"response did not match the OpenAI chat-completions shape ({exc}). "
                    f"Raw body starts with: {resp.text[:300]}",
                ) from exc
            return resp.status_code, content, usage

        raise ModelCallError(
            stage_id, "unreachable retry loop exit"
        )  # pragma: no cover

    @staticmethod
    def _feedback(
        transcript: list[dict[str, str]], bad_output: str, error: str
    ) -> None:
        transcript.append({"role": "assistant", "content": bad_output})
        transcript.append(
            {
                "role": "user",
                "content": (
                    f"{error}\n\nReturn the corrected COMPLETE JSON object only. "
                    "No prose, no markdown fences."
                ),
            }
        )

    @staticmethod
    def _format_validation_error(exc: jsonschema.ValidationError) -> str:
        path = "/".join(str(p) for p in exc.absolute_path) or "(root)"
        return f"at '{path}': {exc.message}"

    @staticmethod
    def _redact(request: dict) -> dict:
        """Copy of the request safe to persist (no secrets can be in it, but keep
        the guarantee explicit and future-proof)."""
        return json.loads(
            json.dumps(request)
        )  # deep copy; messages contain no auth material
