"""Reusable validation rounds: parse, validate, feed the violation back.

The model's own repair budget is SEPARATE from the transport budget: a schema
failure, a JSON parse failure, a truncated output (`finish_reason == "length"`)
or an extra_validator problem costs one validation ROUND and never consumes a
transport retry. Each failure's exact violation is fed back to the model
(errors-as-context, skills/prompting-and-agent-design): fix precisely the
reported problem, keep valid parts unchanged, return the corrected COMPLETE
JSON object only. After `rounds` rounds without a valid object,
ValidationExhaustedError carries the last error.

Transcript economy: only the LATEST rejected output stays in full; older ones
are trimmed to 1200 chars with a stub note (their full text lives in the
caller's attempt artifacts - the factory persists every request/response).

This module is standalone: it imports nothing from factory/.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import jsonschema

from .errors import ValidationExhaustedError

# Older rejected outputs are trimmed to this many chars (+ stub note).
TRIM_CHARS = 1200
_TRIM_STUB = (
    "\n... [earlier rejected output trimmed; the full text is in the attempt artifacts]"
)


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


def format_jsonschema_error(exc: jsonschema.ValidationError) -> str:
    """Compact, model-readable violation report (2026-11-05 founder run: jsonschema's
    default message embeds the whole rejected instance - once a 55k-char repr of 70
    blocks, which ballooned the retry transcript 110k -> 243k characters): path +
    what was expected + what arrived, never an instance dump."""
    path = "/".join(str(p) for p in exc.absolute_path) or "(root)"
    kw = exc.validator
    if kw == "type":
        want = exc.validator_value
        want = "/".join(want) if isinstance(want, list) else want
        size = (
            f" of {len(exc.instance)} items"
            if isinstance(exc.instance, (list, dict, str))
            else ""
        )
        return f"at '{path}': expected {want} here, got {_json_name(exc.instance)}{size}"
    if kw in ("maxItems", "minItems") and isinstance(exc.instance, list):
        word = "at most" if kw == "maxItems" else "at least"
        return f"at '{path}': expected {word} {exc.validator_value} items, got {len(exc.instance)}"
    if kw in ("maxLength", "minLength") and isinstance(exc.instance, str):
        word = "at most" if kw == "maxLength" else "at least"
        return (
            f"at '{path}': expected {word} {exc.validator_value} characters, "
            f"got {len(exc.instance)}"
        )
    msg = exc.message if len(exc.message) <= 240 else exc.message[:240] + "..."
    return f"at '{path}': {msg}"


def _json_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, str):
        return "string"
    return "number"


def run_validation_rounds(
    call_fn: Callable[[int, list[dict[str, str]]], tuple[str, str | None]],
    messages: list[dict[str, str]],
    schema: dict[str, Any],
    schema_name: str,
    *,
    rounds: int,
    extra_validator: Callable[[dict[str, Any]], list[str]] | None = None,
    on_reject: Callable[[int, str], None] | None = None,
) -> dict[str, Any]:
    """Run up to `rounds` validation rounds and return the first valid object.

    call_fn(round_no, transcript) performs ONE model call (with its artifacts
    and logging) and returns (text, finish_reason). on_reject(round_no, error)
    observes every rejected round (print, log, metric - caller's choice).

    extra_validator: optional code-side check on the PARSED object (e.g. a
    stage's rule checks). Returning a non-empty list of problem strings is
    treated exactly like a schema failure: the problems are fed back to the
    model and the round is retried from the same budget.
    """
    transcript = [dict(m) for m in messages]
    rejected_indexes: list[int] = []
    last_error = ""

    for round_no in range(1, rounds + 1):
        text, finish_reason = call_fn(round_no, [dict(m) for m in transcript])

        if finish_reason == "length":
            last_error = (
                "output was truncated (finish_reason=length): the server cut the "
                "response off at its context limit - return a more compact, "
                "complete JSON object"
            )
            _reject(transcript, rejected_indexes, text, last_error, round_no, on_reject)
            continue

        try:
            parsed = parse_json_object(text)
        except ValueError as exc:
            last_error = f"JSON parse failure: {exc}"
            _reject(transcript, rejected_indexes, text, last_error, round_no, on_reject)
            continue

        # Draft7 explicitly (the factory's schemas are Draft7; validator_for's
        # dialect sniffing could silently weaken validation on draft-specific
        # keywords). Report the best-match violation plus up to 3 more in ONE
        # turn (2026-11-05: the run burned one 50-minute attempt per error),
        # compact-formatted and hard-capped.
        errors = list(jsonschema.Draft7Validator(schema).iter_errors(parsed))
        if errors:
            best = jsonschema.exceptions.best_match(errors)
            others = [e for e in errors if e is not best][:3]
            last_error = " | ".join(format_jsonschema_error(e) for e in [best, *others])
            if len(last_error) > TRIM_CHARS:
                last_error = last_error[:TRIM_CHARS] + "..."
            _reject(
                transcript,
                rejected_indexes,
                text,
                f"Schema validation failed: {last_error}",
                round_no,
                on_reject,
            )
            continue

        if extra_validator is not None:
            problems = extra_validator(parsed)
            if problems:
                last_error = "; ".join(problems[:12])
                _reject(
                    transcript,
                    rejected_indexes,
                    text,
                    f"Rule checks failed: {last_error}",
                    round_no,
                    on_reject,
                )
                continue

        return parsed

    raise ValidationExhaustedError(
        f"{schema_name}: output failed validation on all {rounds} validation "
        f"rounds. Last error: {last_error}"
    )


def _reject(
    transcript: list[dict[str, str]],
    rejected_indexes: list[int],
    bad_output: str,
    error: str,
    round_no: int,
    on_reject: Callable[[int, str], None] | None,
) -> None:
    """Errors-as-context: append the rejected output + the exact violation,
    then trim every OLDER rejected output to 1200 chars (only the latest
    stays in full)."""
    for idx in rejected_indexes:
        content = transcript[idx]["content"]
        if len(content) > TRIM_CHARS:
            transcript[idx]["content"] = content[:TRIM_CHARS] + _TRIM_STUB
    rejected_indexes.append(len(transcript))
    transcript.append({"role": "assistant", "content": bad_output})
    transcript.append(
        {
            "role": "user",
            "content": (
                f"{error}\n\nFix the reported problem(s) and return the "
                "corrected COMPLETE JSON object only. Keep every part that "
                "was already valid unchanged. No prose, no markdown fences."
            ),
        }
    )
    if on_reject is not None:
        on_reject(round_no, error)
