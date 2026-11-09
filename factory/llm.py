"""Model calls for the content factory: a thin adapter over llm_manager.

Since 2026-11-07 the actual model handling lives in the standalone
`llm_manager` package (streaming calls, honest inactivity timeouts, a
per-call wall-clock deadline that aborts a runaway generation mid-stream,
transport retries, reusable validation rounds). This module keeps the
FACTORY's contracts on top of it:

- Public API unchanged: `LLMClient(cfg, run).call(stage_id, messages,
  schema, schema_name, temperature=None, extra_validator=None,
  round_tag=None) -> dict`. Every stage call site is untouched.
- Artifacts (2026-11-08): `attempts/[<round_tag>/]attempt-NN/request.json`
  (redacted wire copy), `response.json` (raw text), `meta.json` with all
  fields it always carried plus streaming evidence (`stream`, `first_token_s`,
  `chunks_received`, `call_deadline_s`, `finish_reason`) - and meta.json is
  now written for FAILED calls too (last heartbeat + error class), so a
  mid-call death leaves the same diagnosable trail as a completed call.
- Ledgers (2026-11-08): every attempt appends one line to the run's
  `calls_ledger.jsonl` (answered / rejected-with-reason / transport-failure,
  with latency, time-to-first-content and token usage) - the raw material
  for "what are the agents actually failing at".
- Errors unchanged: llm_manager failures surface as the same
  ModelCallError / SchemaError types the pipeline already handles; message
  shapes are preserved (updated only where streaming changed the truth -
  e.g. "validation rounds" now names the model's own repair budget, which is
  separate from the transport retry budget).

No completion cap is ever sent (2026-11-04 founder decision): the factory
sends no max_tokens at all - the server decides how long its answer, thinking
included, may be within its own context. The wall-clock backstops are
ZIVON_CALL_DEADLINE_S (per call) and the Job's activeDeadlineSeconds.

Observability: every call prints its start (naming the validation round), a
heartbeat with REAL streaming progress (`N chunks received` - a thinking
model waiting for its first token vs a streaming server are now visibly
different), and its end with latency + token usage. This module prints via
its observer; llm_manager itself never prints.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from llm_manager import (
    BadServerResponseError,
    LLMConfig,
    LLMManager,
    LLMObserver,
    NonRetryableHTTPError,
    TransportError,
    ValidationExhaustedError,
    build_wire_request,
    parse_json_object,
    run_validation_rounds,
)

from .artifacts import RunContext
from .config import Config
from .errors import ModelCallError, SchemaError

__all__ = ["LLMClient", "parse_json_object"]


class _StageObserver(LLMObserver):
    """The factory's in-flight voice: real streaming progress, not just
    elapsed time. llm_manager calls this every heartbeat_s while the call is
    in flight; nothing prints from inside llm_manager. The last heartbeat is
    also kept so a mid-call transport death can be written to meta.json -
    before 2026-11-08 a killed call left only request.json behind."""

    def __init__(self, stage_id: str):
        self.stage_id = stage_id
        self.last_elapsed_s: float | None = None
        self.last_chunks: int | None = None

    def on_progress(self, elapsed_s: float, chunks_received: int) -> None:
        self.last_elapsed_s = round(elapsed_s, 1)
        self.last_chunks = chunks_received
        print(
            f"[{self.stage_id}] still waiting on the model "
            f"({int(elapsed_s)}s, {chunks_received} chunks received...)"
        )


class LLMClient:
    def __init__(self, cfg: Config, run: RunContext):
        self.cfg = cfg
        self.run = run
        # The URL the factory talks to (diagnostics + error messages). In the
        # cluster this is the llm_manager Service; locally it may be the
        # inference server directly. llm_manager appends /chat/completions.
        self.url = cfg.server["base_url"].rstrip("/") + "/chat/completions"
        self._llm_config = LLMConfig.from_mapping(cfg.server)

    # ------------------------------------------------------------------ call
    def call(
        self,
        stage_id: str,
        messages: list[dict[str, Any]],
        schema: dict,
        schema_name: str,
        temperature: float | None = None,
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
        stage_dir = self.run.stage_dir(stage_id)
        attempts_dir = stage_dir / "attempts"
        if round_tag:
            attempts_dir = attempts_dir / round_tag
        rounds = self.cfg.server["validation_rounds"]
        round_note = f" [{round_tag}]" if round_tag else ""

        def call_fn(
            round_no: int, transcript: list[dict[str, Any]]
        ) -> tuple[str, str | None]:
            attempt_dir = attempts_dir / f"attempt-{round_no:02d}"
            wire = build_wire_request(self._llm_config, transcript, temperature, None)
            self.run.write_json(attempt_dir / "request.json", self._redact(wire))

            print(
                f"[{stage_id}] model call started{round_note} (validation "
                f"round {round_no}/{rounds}; a thinking model can take many "
                "minutes - heartbeats will show it is alive)"
            )
            observer = _StageObserver(stage_id)
            manager = LLMManager(self._llm_config, observer=observer)
            t0 = time.time()
            try:
                result = manager.complete(transcript, temperature=temperature)
            except (
                TransportError,
                NonRetryableHTTPError,
                BadServerResponseError,
            ) as exc:
                # Failure evidence (2026-11-08): a mid-call death must leave
                # the same diagnosable trail as a completed call - meta.json
                # with the last heartbeat + the error, and a ledger line.
                latency = round(time.time() - t0, 2)
                self.run.write_json(
                    attempt_dir / "meta.json",
                    {
                        "stage": stage_id,
                        "attempt": round_no,
                        "started_at": datetime.fromtimestamp(t0, UTC).isoformat(
                            timespec="seconds"
                        ),
                        "latency_s": latency,
                        "outcome": "transport-failure",
                        "error_class": type(exc).__name__,
                        "error": str(exc)[:400],
                        "last_heartbeat_s": observer.last_elapsed_s,
                        "chunks_received": observer.last_chunks,
                        "call_deadline_s": self._llm_config.call_deadline_s,
                    },
                )
                self.run.append_ledger(
                    "calls_ledger",
                    [
                        {
                            "stage": stage_id,
                            "round_tag": round_tag,
                            "attempt": round_no,
                            "outcome": "transport-failure",
                            "latency_s": latency,
                            "last_heartbeat_s": observer.last_elapsed_s,
                            "error_class": type(exc).__name__,
                            "error": str(exc)[:180],
                        }
                    ],
                )
                raise ModelCallError(stage_id, str(exc)) from exc
            latency = round(time.time() - t0, 2)
            usage = result.usage or {}
            print(
                f"[{stage_id}] model call finished in {latency}s"
                f"{self._usage_note(usage)}"
            )
            self.run.write_text(attempt_dir / "response.json", result.text)
            self.run.write_json(
                attempt_dir / "meta.json",
                {
                    "stage": stage_id,
                    "attempt": round_no,
                    "started_at": datetime.fromtimestamp(t0, UTC).isoformat(
                        timespec="seconds"
                    ),
                    "outcome": "answered",
                    "http_status": result.http_status,
                    "latency_s": latency,
                    "usage": usage,
                    "model": result.model,
                    "temperature": temperature,
                    "prompt_chars": sum(len(m.get("content", "")) for m in transcript),
                    "response_chars": len(result.text),
                    # additive streaming evidence (2026-11-07)
                    "finish_reason": result.finish_reason,
                    "stream": self._llm_config.stream,
                    "first_token_s": result.first_token_s,
                    "chunks_received": result.chunks_received,
                    "call_deadline_s": self._llm_config.call_deadline_s,
                },
            )
            self.run.append_ledger(
                "calls_ledger",
                [
                    {
                        "stage": stage_id,
                        "round_tag": round_tag,
                        "attempt": round_no,
                        "outcome": "answered",
                        "latency_s": latency,
                        "first_token_s": result.first_token_s,
                        "prompt_tokens": usage.get("prompt_tokens"),
                        "completion_tokens": usage.get("completion_tokens"),
                        "finish_reason": result.finish_reason,
                        "chunks_received": result.chunks_received,
                    }
                ],
            )
            return result.text, result.finish_reason

        try:
            return run_validation_rounds(
                call_fn,
                messages,
                schema,
                schema_name,
                rounds=rounds,
                extra_validator=extra_validator,
                on_reject=lambda no, err: self._reject(stage_id, round_tag, no, err),
            )
        except ValidationExhaustedError as exc:
            # The factory's operational guidance (runbook): a SchemaError is a
            # RESUME-able failure, not a dead end.
            raise SchemaError(
                stage_id,
                f"{exc} (each round may itself carry up to "
                f"{self._llm_config.max_attempts} transport retries). Re-trigger "
                "the run to RESUME: completed stages are kept and this stage "
                "re-runs with a fresh validation budget.",
                artifacts_dir=str(stage_dir),
            ) from exc

    # ------------------------------------------------------------- internals
    def _reject(
        self, stage_id: str, round_tag: str | None, attempt: int, error: str
    ) -> None:
        """Log a rejected attempt: the model gets the exact violation fed back
        (errors-as-context), the log shows why a retry is happening, and the
        calls_ledger records the rejection class for cross-run analysis."""
        print(
            f"[{stage_id}] attempt {attempt} rejected: {error[:180]} "
            "-> retrying with the error fed back to the model"
        )
        self.run.append_ledger(
            "calls_ledger",
            [
                {
                    "stage": stage_id,
                    "round_tag": round_tag,
                    "attempt": attempt,
                    "outcome": "rejected",
                    "reason": error[:180],
                }
            ],
        )

    @staticmethod
    def _usage_note(usage: dict) -> str:
        if not usage:
            return ""
        parts = [
            f"{key}={usage[key]}"
            for key in ("prompt_tokens", "completion_tokens")
            if key in usage
        ]
        return f" ({', '.join(parts)})" if parts else ""

    @staticmethod
    def _redact(request: dict) -> dict:
        """Copy of the request safe to persist (no secrets can be in it, but keep
        the guarantee explicit and future-proof). Image parts are scrubbed to
        a byte-count placeholder: data URIs would flood attempt artifacts with
        megabytes; the PNGs live in the stage's screenshots/ dir instead."""
        redacted = json.loads(json.dumps(request))  # deep copy
        for message in redacted.get("messages", []) or []:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not (isinstance(part, dict) and part.get("type") == "image_url"):
                    continue
                url = (part.get("image_url") or {}).get("url", "")
                part["image_url"] = {
                    "url": f"<redacted data-uri: {len(url)} chars; PNG in run screenshots/>"
                }
        return redacted
