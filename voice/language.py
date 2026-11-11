"""Reply-language resolution — product locales, precedence, prompt/TTS forms.

The tutor must answer in the same language the student just used (founder
requirement 2026-11-11): English, Hindi, or the code-mixed Hinglish that the
Prisma transcript carries. This module owns the three translations that were
previously scattered/implicit:

1. **Vendor → product locale.** Prisma v3.0 reports a detected language on its
   transcript event (``detected_language_code``: ``hi-IN``, ``en-IN``,
   ``hi-Latn``/``hi-en`` …; stt_client surfaces it as ``SttEvent.lang``).
   :func:`normalize_locale` maps that to one of :data:`LOCALES`
   (``en``, ``hi``, ``hi-Latn``) — the values the dock receives in
   ``language.detected`` (ws-contract.md §2).
2. **Precedence.** Latest Prisma detection > the ``session.start`` locale >
   the product default (:func:`resolve_reply_locale`). A typed turn has no
   fresh detection, so it inherits the session's last detected locale — the
   student's language does not flip just because they typed once.
3. **Prompt + TTS forms.** :func:`reply_language_line` is the per-turn prompt
   contract line; :func:`tts_language_for` is the Timbre ``language`` field
   (Timbre's code-mix is ``hi-en``; it has no ``hi-Latn``).

No ids, no transcript text: this module is a pure mapping (an instrumented
call site logs the locale only, never the words).
"""

from __future__ import annotations

__all__ = [
    "DEFAULT_LOCALE",
    "LOCALES",
    "locale_label",
    "locale_script",
    "normalize_locale",
    "reply_language_line",
    "resolve_reply_locale",
    "tts_language_for",
]

# The product's three reply locales (frontend/voice agreement, ws-contract §2).
LOCALES = ("en", "hi", "hi-Latn")

# The Hinglish default: the product is voice-first for Indian learners and
# code-mixing is the normal input (spec.md §2 stage 3), so an empty locale
# resolves to the mix rather than to either monolingual.
DEFAULT_LOCALE = "hi-Latn"

_SCRIPT = {"en": "Latn", "hi": "Deva", "hi-Latn": "Latn"}

_LABEL = {"en": "English", "hi": "Hindi", "hi-Latn": "Hinglish"}

# Vendor / client spellings → product locale. Keys are already normalised
# (lower-case, ``_`` → ``-``); regional suffixes are stripped by the caller.
_ALIASES = {
    "en": "en",
    "eng": "en",
    "english": "en",
    "hi": "hi",
    "hin": "hi",
    "hindi": "hi",
    "hi-latn": "hi-Latn",
    "hi-latn-in": "hi-Latn",
    "hinglish": "hi-Latn",
    "hi-en": "hi-Latn",
    "en-hi": "hi-Latn",
    "en-in-hi": "hi-Latn",
}

_INSTRUCTION = {
    "en": (
        "answer in English — the student is speaking English"
    ),
    "hi": (
        "answer in Hindi — the student is speaking Hindi"
    ),
    "hi-Latn": (
        "answer in Hinglish — the same Hindi-English mix the student used, "
        "keeping technical terms and proper nouns in English"
    ),
}


def normalize_locale(raw: str | None) -> str:
    """Map a vendor/client language tag to a product locale, or ``""``.

    ``hi-IN`` → ``hi``; ``en-IN`` → ``en``; ``hi-Latn``/``hi-en``/``hinglish``
    → ``hi-Latn``. Unknown values return ``""`` so the caller can fall through
    the precedence chain instead of guessing.
    """
    if not raw:
        return ""
    token = str(raw).strip().lower().replace("_", "-")
    if not token:
        return ""
    if token in _ALIASES:
        return _ALIASES[token]
    # Regional/compound suffix: hi-in, en-in, hi-latn-in, en-in-hi …
    head = token.split("-")
    if head and head[0] == "hi":
        if len(head) > 1 and head[1] == "latn":
            return "hi-Latn"
        return "hi"
    if head and head[0] == "en":
        if "hi" in head[1:]:
            return "hi-Latn"  # en-IN-hi style vendor mixes
        return "en"
    return ""


def resolve_reply_locale(
    *,
    detected: str | None,
    session_locale: str | None,
    default: str = DEFAULT_LOCALE,
) -> str:
    """Precedence: latest STT detection > session.start locale > default.

    Every value goes through :func:`normalize_locale`, so a vendor tag and a
    product locale are interchangeable at every level.
    """
    for raw in (detected, session_locale, default):
        locale = normalize_locale(raw)
        if locale:
            return locale
    return DEFAULT_LOCALE


def locale_label(locale: str) -> str:
    """Human name of a product locale (``English`` / ``Hindi`` / ``Hinglish``)."""
    return _LABEL.get(normalize_locale(locale), _LABEL[DEFAULT_LOCALE])


def locale_script(locale: str) -> str:
    """Script tag for ``language.detected`` (``Latn`` / ``Deva``)."""
    return _SCRIPT.get(normalize_locale(locale), "Latn")


def reply_language_line(locale: str) -> str:
    """The per-turn prompt contract line (data for the model, no ids).

    Shape: ``REPLY LANGUAGE: <label> — <instruction>``. The static system
    prompt points at this line; the value is per turn, which is why it rides
    with the request rather than the (cached) system prompt.
    """
    loc = normalize_locale(locale) or DEFAULT_LOCALE
    return f"REPLY LANGUAGE: {_LABEL[loc]} — {_INSTRUCTION[loc]}."


def tts_language_for(locale: str, default: str = "hi-en") -> str:
    """Timbre ``language`` value for a reply locale (OQ-03 verified codes).

    Timbre v3.0 takes ``en`` / ``hi`` / ``hi-en`` (its Hinglish code-mix);
    anything unknown falls back to the configured default so a missing
    mapping can never silence the tutor.
    """
    loc = normalize_locale(locale)
    if loc == "en":
        return "en"
    if loc == "hi":
        return "hi"
    return default
