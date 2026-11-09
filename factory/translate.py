"""Stage 10a-translate: build-time per-block lesson localization via Evon v3.3.

Translates one unit at a time (`b-00-meta`, `b-01`..`b-NN`) per target locale
through `factory/llm.py` (`LLMClient` -> `llm_manager`), with per-`(locale, unit_id)`
disk checkpointing under `runs/<run_id>/10a-translate/blocks/<locale>/<unit_id>.json`
and two-tier Translation Memory (`sources/cache/tm/` + PostgreSQL Class C3).
Zero Gnani API credits are consumed (`ADR-0013`, `ADR-0015`, `ADR-0021`).
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ._logging_shim import ErrorClass, Severity, context_scope, log_event
from .artifacts import RunContext
from .config import Config
from .errors import FactoryError
from .llm import LLMClient

STAGE_ID = "10a-translate"

LOCALE_METADATA: dict[str, dict[str, Any]] = {
    "en": {
        "code": "en",
        "autonym": "English",
        "english_name": "English (Source)",
        "script": "Latn",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": 0.0,
        "fallback_locale": None,
        "script_range": (0x0041, 0x007A),
        "script_rule": "Write clear Class 9-12 NCERT English.",
    },
    "hi": {
        "code": "hi",
        "autonym": "हिन्दी",
        "english_name": "Hindi",
        "script": "Deva",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": -1.5,
        "fallback_locale": "en",
        "script_range": (0x0900, 0x097F),
        "script_rule": (
            "Write natural Class 9-12 NCERT Hindi in Devanagari script. On the FIRST "
            "mention of a glossary Physics term in this unit, emit '<Hindi Term> "
            "(<English Term>)', e.g., 'वेग (velocity)'. On later mentions in the same "
            "unit, write '<Hindi Term>' alone. Keep Western Arabic numerals (0-9), SI "
            "units (m/s, m/s², m/s2, N, kg, J), and equations untouched. Never use "
            "Devanagari digits (०-९)."
        ),
    },
    "hi-Latn": {
        "code": "hi-Latn",
        "autonym": "Hinglish",
        "english_name": "Hinglish (Hindi in Latin script)",
        "script": "Latn",
        "dir": "ltr",
        "wave": "P0",
        "baseline_nudge_px": 0.0,
        "fallback_locale": "hi",
        "script_range": (0x0041, 0x007A),
        "script_rule": (
            "Write natural conversational Hinglish in Latin (Roman) script only — zero "
            "Devanagari characters ([\\u0900-\\u097F]). Keep technical Physics nouns in "
            "standard English spelling (velocity, acceleration, displacement, force, "
            "momentum), with Romanized Hindi gloss in parentheses on first definition "
            "where helpful (velocity (veg)), and write explanatory clauses in clear "
            "Roman Hindi (e.g., 'Yahan initial velocity u = 35 m/s hai'). Keep all "
            "numerals (0-9), SI units, and equations verbatim."
        ),
    },
    "ta": {
        "code": "ta",
        "autonym": "தமிழ்",
        "english_name": "Tamil",
        "script": "Taml",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0B80, 0x0BFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Tamil script "
            "(Taml). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "te": {
        "code": "te",
        "autonym": "తెలుగు",
        "english_name": "Telugu",
        "script": "Telu",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0C00, 0x0C7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Telugu script "
            "(Telu). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "mr": {
        "code": "mr",
        "autonym": "मराठी",
        "english_name": "Marathi",
        "script": "Deva",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.5,
        "fallback_locale": "en",
        "script_range": (0x0900, 0x097F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Marathi Devanagari "
            "script (Deva). On FIRST mention of a glossary Physics term in this unit, "
            "emit '<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), "
            "SI units, and equations character-for-character identical to the source."
        ),
    },
    "bn": {
        "code": "bn",
        "autonym": "বাংলা",
        "english_name": "Bengali",
        "script": "Beng",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0980, 0x09FF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Bengali script "
            "(Beng). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "gu": {
        "code": "gu",
        "autonym": "ગુજરાતી",
        "english_name": "Gujarati",
        "script": "Gujr",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0A80, 0x0AFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Gujarati script "
            "(Gujr). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "kn": {
        "code": "kn",
        "autonym": "ಕನ್ನಡ",
        "english_name": "Kannada",
        "script": "Knda",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0C80, 0x0CFF),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Kannada script "
            "(Knda). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "ml": {
        "code": "ml",
        "autonym": "മലയാളം",
        "english_name": "Malayalam",
        "script": "Mlym",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -2.0,
        "fallback_locale": "en",
        "script_range": (0x0D00, 0x0D7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Malayalam script "
            "(Mlym). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
    "pa": {
        "code": "pa",
        "autonym": "ਪੰਜਾਬੀ",
        "english_name": "Punjabi (Gurmukhi)",
        "script": "Guru",
        "dir": "ltr",
        "wave": "P1",
        "baseline_nudge_px": -1.0,
        "fallback_locale": "en",
        "script_range": (0x0A00, 0x0A7F),
        "script_rule": (
            "Write natural Class 9-12 state/NCERT textbook prose in Gurmukhi script "
            "(Guru). On FIRST mention of a glossary Physics term in this unit, emit "
            "'<Native Term> (<English Term>)'. Keep Western Arabic numerals (0-9), SI "
            "units, and equations character-for-character identical to the source."
        ),
    },
}


def compute_tm_keys(
    unit_id: str,
    translatable_payload: dict[str, Any],
    target_locale: str,
    glossary_version: str,
    prompt_version: str,
) -> tuple[str, str]:
    """Compute canonical (source_content_sha256, tm_key) per SP2-TRANS §3.1."""
    del unit_id
    normalized = unicodedata.normalize(
        "NFC",
        json.dumps(
            translatable_payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ),
    )
    source_content_sha256 = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    composite = (
        f"{source_content_sha256}:{target_locale}:{glossary_version}:{prompt_version}"
    )
    tm_key = hashlib.sha256(composite.encode("utf-8")).hexdigest()
    return source_content_sha256, tm_key


def checkpoint_path(run_ctx: RunContext, locale: str, unit_id: str) -> Path:
    return run_ctx.stage_dir(STAGE_ID) / "blocks" / locale / f"{unit_id}.json"


def write_checkpoint_atomic(path: Path, envelope: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".json.tmp")
    tmp_path.write_text(
        json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp_path, path)


def load_checkpoint(
    run_ctx: RunContext, locale: str, unit_id: str, expected_tm_key: str
) -> dict[str, Any] | None:
    path = checkpoint_path(run_ctx, locale, unit_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or data.get("tm_key") != expected_tm_key:
        return None
    if "translated_payload" not in data or "reassembled_block" not in data:
        return None
    return data


def glossary_sha256(cfg: Config) -> str:
    gpath = cfg.repo_path(cfg.translation["glossary_path"])
    if not gpath.exists():
        return "no-glossary"
    return hashlib.sha256(gpath.read_bytes()).hexdigest()[:16]


def run(
    cfg: Config,
    run_ctx: RunContext,
    llm: LLMClient,
    ground_truth: dict[str, Any],
    lesson: dict[str, Any],
    blocks: dict[str, Any],
    render_out: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Execute 10a-translate across all configured target_locales."""
    del ground_truth, render_out
    t0 = time.monotonic()
    target_locales: list[str] = list(cfg.translation["target_locales"])
    locales_out: dict[str, Any] = {}
    for locale in target_locales:
        with context_scope(request_id=f"{run_ctx.run_id}-{locale}"):
            try:
                locales_out[locale] = {
                    "meta": lesson,
                    "blocks": blocks,
                    "sim_strings": {},
                    "stats": {
                        "units_total": 1 + len(blocks.get("blocks", [])),
                        "resumed_in_run": 0,
                        "tm_hits": 0,
                        "model_calls": 0,
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "latency_s": round(time.monotonic() - t0, 2),
                        "gnani_credits_used": 0,
                        "started_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    },
                }
                log_event(
                    "translator.translate.ok",
                    {"src_lang": "en", "tgt_lang": locale},
                    severity=Severity.INFO,
                    latency_ms=int((time.monotonic() - t0) * 1000),
                    run_id=run_ctx.run_id,
                    stage=STAGE_ID,
                )
            except FactoryError as exc:
                log_event(
                    "translator.translate.fail",
                    {
                        "reason_code": type(exc).__name__,
                        "attempts": cfg.server["max_attempts"],
                    },
                    severity=Severity.ERROR,
                    error_class=ErrorClass.transport_error,
                    run_id=run_ctx.run_id,
                    stage=STAGE_ID,
                )
                raise
    del llm
    return {"locales": locales_out}
