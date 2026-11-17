"""Explain-back (F6) runtime: transient audio, transcript, rubric, nothing raw.

The package is deliberately small and testable:

- `audio` — the one accepted WAV shape, bounded, in memory only;
- `rubric` — the model-verdict contract and the deterministic band mapping;
- `pipeline` — the shipped voice vendors (Prisma STT + tutor brain) behind one
  `SpeakingPipeline`, with an explicitly labelled dev mock mode.

No module here writes audio to disk, imports a new vendor SDK, or decides a
product state. Routes map the typed outcomes to HTTP; the store owns rows.
"""

from __future__ import annotations

from .audio import (
    MAX_UPLOAD_BYTES,
    AudioError,
    WavAudio,
    parse_wav,
    pcm_frames,
    stt_credit_points,
)
from .pipeline import (
    MOCK_TRANSCRIPT,
    SpeakingEvaluationError,
    SpeakingPipeline,
    SpeakingUnavailableError,
    Transcript,
    TranscriptError,
    pipeline_for,
)
from .rubric import (
    BAND_LABELS,
    BAND_NOTES,
    Evaluation,
    EvaluationError,
    key_ideas,
    parse_evaluation,
    thresholds,
)

__all__ = [
    "BAND_LABELS",
    "BAND_NOTES",
    "MAX_UPLOAD_BYTES",
    "MOCK_TRANSCRIPT",
    "AudioError",
    "Evaluation",
    "EvaluationError",
    "SpeakingEvaluationError",
    "SpeakingPipeline",
    "SpeakingUnavailableError",
    "Transcript",
    "TranscriptError",
    "WavAudio",
    "key_ideas",
    "parse_evaluation",
    "parse_wav",
    "pcm_frames",
    "pipeline_for",
    "stt_credit_points",
    "thresholds",
]
