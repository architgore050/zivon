"""Explain-back rubric contract: model verdict in, deterministic band out.

The tutor model judges *meaning* — whether each authored key idea appears in
the student's own words, in English, Hindi, or Hinglish. It never decides the
band, the count, or a percentage: this module maps its structured verdict onto
the authored thresholds (`pass_ratio` / `strong_ratio`), exactly once, in
code. That split is the repo's reviewer rule (`skills/prompting-and-agent-design`):
the model produces evidence, the harness computes the verdict.

Output contract (validated here, not trusted):

```json
{
  "ideas": [
    {"idea_id": "spk-c9-motion-001-idea-01", "present": true,
     "evidence": "distance is the whole path"}
  ],
  "feedback": {
    "what_went_well": "You named distance and displacement clearly.",
    "next_step": "Add why a round trip has zero displacement."
  }
}
```

Rules enforced by code:

- one entry per authored idea id (unknown ids are dropped; a missing entry is
  "not covered", never a crash);
- `present` must be a JSON boolean; strings are not truthiness-coerced;
- evidence is a short verbatim fragment, bounded, and only kept when the idea
  is present;
- feedback is bounded prose; a missing or empty field gets a deterministic
  fallback so the student never sees a blank AI label;
- the band comes from the authored ratios, not from the model.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

__all__ = [
    "BAND_LABELS",
    "BAND_NOTES",
    "MAX_EVIDENCE_CHARS",
    "MAX_FEEDBACK_CHARS",
    "Evaluation",
    "EvaluationError",
    "band_for_ratio",
    "key_ideas",
    "parse_evaluation",
    "thresholds",
]

MAX_EVIDENCE_CHARS: Final[int] = 160
MAX_FEEDBACK_CHARS: Final[int] = 240
DEFAULT_MAX_DURATION_S: Final[int] = 45
DEFAULT_PASS_RATIO: Final[float] = 0.6
DEFAULT_STRONG_RATIO: Final[float] = 0.85

BAND_LABELS: Final[dict[str, str]] = {
    "strong": "Strong explanation",
    "pass": "Clear explanation",
    "needs_practice": "Needs another try",
}
BAND_NOTES: Final[dict[str, str]] = {
    "strong": "You covered almost every key idea. Read the model answer once and keep it warm.",
    "pass": "You covered the main ideas. One more pass over the missing ideas will make it solid.",
    "needs_practice": "You made a start. Re-read the model answer, then record again and name each key idea.",
}

_CODEFENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.IGNORECASE | re.DOTALL)


class EvaluationError(ValueError):
    """The model did not produce the rubric contract; the attempt keeps its text."""

    def __init__(self, code: str = "E-SPEAKING-EVALUATION", detail: str = "") -> None:
        super().__init__(detail or code)
        self.code = code


@dataclass(frozen=True)
class Evaluation:
    """One validated rubric result, ready for the API and the attempt row."""

    ideas: tuple[dict[str, Any], ...]
    ideas_present: int
    ideas_total: int
    ratio: float
    band: str
    what_went_well: str
    next_step: str
    model: str
    mock: bool = False

    @property
    def band_label(self) -> str:
        return BAND_LABELS[self.band]

    @property
    def band_note(self) -> str:
        return BAND_NOTES[self.band]

    @property
    def score(self) -> float:
        """Stored 0–100 evidence value; the UI shows counts and a band, not this."""
        return round(100.0 * self.ratio, 2)

    def rubric_scores(self) -> dict[str, Any]:
        """The bounded `speaking_attempt.rubric_scores` payload.

        The store refuses > 2000 chars. Presence flags are the load-bearing
        part and stay; if a prompt ever ships enough ideas that the evidence
        quotes would overflow, they are dropped rather than losing the whole
        attempt to a payload validation error.
        """
        payload: dict[str, Any] = {
            "ideas_present": self.ideas_present,
            "ideas_total": self.ideas_total,
            "ratio": round(self.ratio, 4),
            "band": self.band,
            "ideas": [
                {
                    "idea_id": idea["idea_id"],
                    "present": bool(idea["present"]),
                    "evidence": str(idea.get("evidence") or ""),
                }
                for idea in self.ideas
            ],
        }
        if len(json.dumps(payload, ensure_ascii=False)) > 1_900:
            for row in payload["ideas"]:
                row["evidence"] = ""
        return payload

    def feedback(self) -> dict[str, Any]:
        """The bounded `speaking_attempt.feedback` payload (AI-labelled)."""
        return {
            "band": self.band,
            "label": "AI feedback",
            "what_went_well": self.what_went_well,
            "next_step": self.next_step,
            "model": self.model,
            "mock": self.mock,
        }

    def public(self) -> dict[str, Any]:
        """API shape: idea text, presence, and the student's own evidence."""
        return {
            "band": self.band,
            "band_label": self.band_label,
            "band_note": self.band_note,
            "ideas_present": self.ideas_present,
            "ideas_total": self.ideas_total,
            "ratio": round(self.ratio, 4),
            "key_ideas": [dict(idea) for idea in self.ideas],
            "what_went_well": self.what_went_well,
            "next_step": self.next_step,
            "mock": self.mock,
        }


def key_ideas(prompt: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return the authored ideas as `{idea_id, text, concept_id?}` in order."""
    raw = prompt.get("key_ideas")
    ideas: list[dict[str, Any]] = []
    if not isinstance(raw, list):
        return ideas
    for index, entry in enumerate(raw):
        if not isinstance(entry, Mapping):
            continue
        text = str(entry.get("text") or "").strip()
        if not text:
            continue
        idea_id = str(entry.get("idea_id") or f"idea-{index + 1}").strip()
        concept_id = entry.get("concept_id")
        ideas.append(
            {
                "idea_id": idea_id,
                "text": text,
                "concept_id": str(concept_id) if concept_id else None,
            }
        )
    return ideas


def thresholds(prompt: Mapping[str, Any]) -> dict[str, float]:
    """Authored thresholds with sane defaults; never trust a bad stored value."""
    raw = prompt.get("rubric")
    rubric = raw if isinstance(raw, Mapping) else {}

    def _ratio(name: str, default: float) -> float:
        value = rubric.get(name, default)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return default
        return min(1.0, max(0.0, float(value)))

    max_duration = rubric.get("max_duration_s", DEFAULT_MAX_DURATION_S)
    if isinstance(max_duration, bool) or not isinstance(max_duration, (int, float)):
        max_duration = DEFAULT_MAX_DURATION_S
    return {
        "max_duration_s": min(60.0, max(10.0, float(max_duration))),
        "pass_ratio": _ratio("pass_ratio", DEFAULT_PASS_RATIO),
        "strong_ratio": _ratio("strong_ratio", DEFAULT_STRONG_RATIO),
    }


def band_for_ratio(ratio: float, rubric: Mapping[str, float]) -> str:
    """Map coverage onto the authored bands (the only place a band is decided)."""
    if ratio >= float(rubric.get("strong_ratio", DEFAULT_STRONG_RATIO)):
        return "strong"
    if ratio >= float(rubric.get("pass_ratio", DEFAULT_PASS_RATIO)):
        return "pass"
    return "needs_practice"


def _extract_json(text: str) -> dict[str, Any]:
    candidate = text.strip()
    fenced = _CODEFENCE.search(candidate)
    if fenced:
        candidate = fenced.group(1).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        raise EvaluationError(detail="no JSON object in the model output")
    try:
        payload = json.loads(candidate[start : end + 1])
    except (TypeError, ValueError) as exc:
        raise EvaluationError(detail="model output was not valid JSON") from exc
    if not isinstance(payload, dict):
        raise EvaluationError(detail="model output was not a JSON object")
    return payload


def _bounded_text(value: Any, *, limit: int) -> str:
    if value is None:
        return ""
    return str(value).strip()[:limit]


def _feedback_text(
    payload: Mapping[str, Any], present: int, total: int, missing: list[str]
) -> tuple[str, str]:
    raw = payload.get("feedback")
    feedback = raw if isinstance(raw, Mapping) else {}
    went_well = _bounded_text(feedback.get("what_went_well"), limit=MAX_FEEDBACK_CHARS)
    next_step = _bounded_text(feedback.get("next_step"), limit=MAX_FEEDBACK_CHARS)
    if not went_well:
        went_well = (
            f"You covered {present} of {total} key ideas."
            if present
            else "You made a start by answering the prompt out loud."
        )
    if not next_step:
        next_step = (
            "Re-read the model answer and record once more, naming: "
            + ", ".join(missing[:3])
            if missing
            else "Read the model answer once and keep the wording you used."
        )
    return went_well, next_step


def parse_evaluation(
    text: str,
    *,
    prompt: Mapping[str, Any],
    model: str,
    mock: bool = False,
) -> Evaluation:
    """Validate one model verdict and compute the band deterministically."""
    ideas = key_ideas(prompt)
    if not ideas:
        raise EvaluationError(detail="prompt has no key ideas")
    payload = _extract_json(text)
    entries = payload.get("ideas")
    if not isinstance(entries, list) or not entries:
        raise EvaluationError(detail="model output has no ideas array")
    by_id: dict[str, Mapping[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        idea_id = str(entry.get("idea_id") or "").strip()
        if idea_id:
            by_id[idea_id] = entry
    known = {idea["idea_id"] for idea in ideas}
    if not known.intersection(by_id):
        raise EvaluationError(detail="model output names none of the authored ideas")

    rows: list[dict[str, Any]] = []
    missing: list[str] = []
    for idea in ideas:
        entry = by_id.get(idea["idea_id"], {})
        present = entry.get("present") is True
        evidence = ""
        if present:
            evidence = _bounded_text(entry.get("evidence"), limit=MAX_EVIDENCE_CHARS)
        if not present:
            missing.append(idea["text"])
        rows.append(
            {
                "idea_id": idea["idea_id"],
                "text": idea["text"],
                "concept_id": idea.get("concept_id"),
                "present": present,
                "evidence": evidence,
            }
        )
    present_count = sum(1 for row in rows if row["present"])
    ratio = present_count / len(rows)
    rubric = thresholds(prompt)
    band = band_for_ratio(ratio, rubric)
    went_well, next_step = _feedback_text(payload, present_count, len(rows), missing)
    return Evaluation(
        ideas=tuple(rows),
        ideas_present=present_count,
        ideas_total=len(rows),
        ratio=ratio,
        band=band,
        what_went_well=went_well,
        next_step=next_step,
        model=model,
        mock=mock,
    )


def mock_evaluation(
    *, prompt: Mapping[str, Any], model: str, mock: bool = True
) -> Evaluation:
    """Clearly labelled demo result used when no vendor credentials exist.

    The UI banners it; the API sets `mock: true`; nothing here ever runs in a
    production deployment (`SpeakingPipeline` refuses the mode outside dev).
    """
    ideas = key_ideas(prompt)
    rows = tuple(
        {
            "idea_id": idea["idea_id"],
            "text": idea["text"],
            "concept_id": idea.get("concept_id"),
            "present": True,
            "evidence": "Demo mode sample — the scorer is not connected.",
        }
        for idea in ideas
    )
    return Evaluation(
        ideas=rows,
        ideas_present=len(rows),
        ideas_total=len(rows),
        ratio=1.0 if rows else 0.0,
        band=band_for_ratio(1.0 if rows else 0.0, thresholds(prompt)),
        what_went_well=(
            "Demo feedback: the explain-back scorer is not connected, so every "
            "key idea is marked as covered."
        ),
        next_step=(
            "Demo mode only. With live credentials this box is written by the "
            "tutor model from your transcript."
        ),
        model=model,
        mock=mock,
    )
