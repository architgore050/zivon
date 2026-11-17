"""SWOT computation (F8): where the student is strong, weak, opportunistic,
and exposed — from their own evidence only.

The frozen decisions this module implements (full-frontend plan §13 via
`skills/zivon-frontend-product-skills/references/worked-example.md`):

- **Relative by default.** Placement is the student's chapters against each
  other (performance × coverage, median split). Fewer than three rated
  chapters → the honest "not enough data yet" state, and no quadrant claim.
  The absolute-threshold mode exists behind `SWOT_MODE=relative|absolute`
  and is off by default; its constants are calibration placeholders (the
  admin note in `docs/specs/frontend/swot.md` records why they stay off).
- **Recency weighting.** Every observation decays with a 21-day half-life;
  a 14-day trend compares recent accuracy with the older baseline.
- **Exam weight is priority, not a quadrant.** A board-heavy chapter sorts to
  the top of Weakness/Threat and carries an IMP marker; it never creates a
  fifth box.
- **Weakness is effort without results; Threat is a watch-out, not a
  prediction.** No ability score, no leaderboard, no share surface.

Deterministic and versioned: `RULES_VERSION` gates the published copy and
`FORMULA_VERSION` the metric formulas, so a change to either is a visible
decision, never a silent drift.
"""

from __future__ import annotations

import datetime
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from ..progress.catalog import CatalogueSnapshot
from ..progress.store import EventRow, as_utc, to_iso
from .catalog import resolve_chapters

RULES_VERSION: Final[int] = 1
FORMULA_VERSION: Final[str] = "swot-v1"

# Recency: observations decay with a 21-day half-life (FEATURE-MAP §13).
HALF_LIFE_DAYS: Final[float] = 21.0
# The 14-day trend window, its minimum recent sample, and the +/- split.
TREND_WINDOW_DAYS: Final[int] = 14
TREND_MIN_RECENT: Final[int] = 3
TREND_DELTA_PCT: Final[float] = 5.0
# A chapter is rated when it carries at least this many scored items
# (practice answers + test submits + scored explain-backs).
RATED_MIN_ITEMS: Final[int] = 3
# The whole grid needs at least three rated chapters before a median split
# means anything (frozen: "unrated when < 3 chapters").
ENOUGH_DATA_MIN_CHAPTERS: Final[int] = 3
# Absolute-threshold mode (dormant): the placeholder split points. Calibration
# against real cohorts is the precondition for ever surfacing them.
ABSOLUTE_PERFORMANCE_HIGH_PCT: Final[float] = 75.0
ABSOLUTE_COVERAGE_HIGH_PCT: Final[float] = 60.0
# Exam weight >= this value marks a chapter IMP (priority inside a quadrant).
# Real weights arrive with P3's blueprint; until then the column is NULL and
# no chapter is IMP. Calibration note: docs/specs/frontend/swot.md §8.
EXAM_WEIGHT_IMP_MIN: Final[float] = 1.0
# The all-student time EWMA: the AI prior stands until this many capped
# observations exist (assessment.md §6: the prior is a starting guess that
# SWOT replaces with the all-student recency-weighted average).
PRIOR_MIN_OBSERVATIONS: Final[int] = 5
PRIOR_EWMA_ALPHA: Final[float] = 0.3
# Outlier cap: one absurdly slow attempt (a phone call mid-question) must not
# move the prior; each observation is capped at 3x the chapter's AI prior.
PRIOR_OUTLIER_CAP_FACTOR: Final[float] = 3.0
# No AI prior at all (pack not imported): cap observations at the A5 maximum.
PRIOR_FALLBACK_CAP_MS: Final[int] = 300_000
# Pace evidence bands (ratio of the student's own weighted mean time to the
# effective prior).
PACE_SLOW_RATIO: Final[float] = 1.5
PACE_FAST_RATIO: Final[float] = 0.5
# Hint-rate evidence band (mean hints per practice answer).
HINT_HEAVY_RATE: Final[float] = 1.0

QUADRANTS: Final[tuple[str, ...]] = (
    "strength",
    "weakness",
    "opportunity",
    "threat",
)
QUADRANT_LABELS: Final[dict[str, str]] = {
    "strength": "Strengths",
    "weakness": "Weaknesses",
    "opportunity": "Opportunities",
    "threat": "Threats",
}
QUADRANT_BLURBS: Final[dict[str, str]] = {
    "strength": "Solid work on chapters you have covered. Keep them warm.",
    "weakness": "Covered chapters where results trail the effort. Worth another pass.",
    "opportunity": "Chapters where you do well but have not covered much ground yet.",
    "threat": "Watch-outs: little coverage and low results so far. Start small, soon.",
}
MODES: Final[tuple[str, str]] = ("relative", "absolute")
TREND_LABELS: Final[dict[str, str]] = {
    "up": "Improving in the last 14 days",
    "steady": "Steady in the last 14 days",
    "down": "Slipping in the last 14 days",
}
NOT_ENOUGH_CHAPTERS_REASON: Final[str] = (
    "Placements need at least 3 rated chapters; yours has {rated} so far."
)


class SwotModeError(ValueError):
    """`SWOT_MODE` is neither `relative` nor `absolute`."""


def resolve_mode(raw: str | None) -> str:
    """Validate the configured mode; the default is relative (frozen)."""
    mode = (raw or "relative").strip().lower()
    if mode not in MODES:
        raise SwotModeError(f"SWOT_MODE must be one of {'|'.join(MODES)}")
    return mode


@dataclass(frozen=True)
class SwotInput:
    """Everything one computation reads, pre-fetched by the caller."""

    events: list[EventRow]
    speaking: list[dict[str, Any]]
    lesson_progress: list[dict[str, Any]]
    question_counts: dict[str, int]
    attempted: dict[str, set[str]]
    priors: dict[str, int]
    exam_weights: dict[str, float]
    catalogue: CatalogueSnapshot
    all_student_times: dict[str, list[tuple[datetime.datetime, int]]] = field(
        default_factory=dict
    )
    mode: str = "relative"
    now: datetime.datetime | None = None


def build_swot(*, data: SwotInput) -> dict[str, Any]:
    """Return the `/v1/swot` payload for one account."""
    now = data.now or datetime.datetime.now(datetime.UTC)
    chapters = _chapter_metrics(data, now)
    rated = [entry for entry in chapters if entry["rated"]]
    unrated = [entry for entry in chapters if not entry["rated"]]
    medians = _medians(rated) if data.mode == "relative" else None
    if medians is not None or data.mode == "absolute":
        # Relative mode places against the student's own medians; absolute
        # mode against the fixed (dormant) thresholds.
        for entry in rated:
            entry["quadrant"] = _place(entry, medians=medians)
    else:
        # Relative mode with too few rated chapters makes no placement claim.
        for entry in rated:
            entry["rated"] = False
            entry["unrated_reason"] = NOT_ENOUGH_CHAPTERS_REASON.format(
                rated=len(rated)
            )
        unrated = [entry for entry in chapters if not entry["quadrant"]]
        rated = []
    quadrants: dict[str, list[dict[str, Any]]] = {name: [] for name in QUADRANTS}
    for entry in rated:
        quadrants[entry["quadrant"]].append(entry)
    for name in QUADRANTS:
        quadrants[name] = sorted(
            quadrants[name], key=lambda entry: _urgency(name, entry)
        )
    enough = len(rated) >= ENOUGH_DATA_MIN_CHAPTERS
    snapshot = {
        name: quadrants[name][0] if quadrants[name] else None for name in QUADRANTS
    }
    return {
        "schema_version": 1,
        "rules_version": RULES_VERSION,
        "formula_version": FORMULA_VERSION,
        "mode": data.mode,
        "generated_at": to_iso(now),
        # "New" means no evidence at all (no events, no explain-backs) — the
        # pure "nothing here yet" copy; a student with some evidence but too
        # few rated chapters gets the not-enough-chapters copy instead.
        "is_new": not data.events and not data.speaking,
        "enough_data": enough,
        "rated_chapter_count": len(rated),
        "rated_min_chapters": ENOUGH_DATA_MIN_CHAPTERS,
        "quadrants": quadrants,
        "unrated": unrated,
        "medians": medians,
        "snapshot": snapshot,
        "rules": rules(data.mode),
    }


def build_swot_explain(*, data: SwotInput) -> dict[str, Any]:
    """Return the `/v1/swot/explain` payload: the method and this student's numbers."""
    payload = build_swot(data=data)
    payload["chapters"] = [
        {
            "chapter_id": entry["chapter_id"],
            "title": entry["title"],
            "quadrant": entry["quadrant"],
            "rated": entry["rated"],
            "metrics": entry["metrics"],
            "unrated_reason": entry["unrated_reason"],
        }
        for entry in payload["unrated"]
        + [item for name in QUADRANTS for item in payload["quadrants"][name]]
    ]
    payload["method"] = [
        (
            "Your chapter evidence is scored from your own practice answers, "
            "chapter tests, explain-backs, and reading — never from other "
            "students' results."
        ),
        (
            f"Every answer is weighted by recency with a "
            f"{HALF_LIFE_DAYS:.0f}-day half-life: last week counts more than "
            "last month."
        ),
        (
            "Performance is your recency-weighted accuracy. Coverage is how "
            "much of the chapter's question bank (or sections) you have "
            "reached."
        ),
        (
            "Chapters are placed by two medians across your own rated "
            "chapters: performance above or below your middle, coverage above "
            "or below your middle."
        ),
        (
            f"A chapter is rated only with at least {RATED_MIN_ITEMS} scored "
            "items; chapters with less evidence wait in their own row."
        ),
        (
            "Exam weight only reorders cards inside a box (and marks IMP); it "
            "never adds a fifth box and never compares you to anyone."
        ),
    ]
    payload["metric_definitions"] = [
        {
            "name": "weighted_accuracy_pct",
            "plain": "Recency-weighted share of correct first practice answers "
            "and chapter-test answers.",
        },
        {
            "name": "coverage_pct",
            "plain": "Share of the chapter's published questions you have "
            "attempted (or sections read when the bank is not imported).",
        },
        {
            "name": "attempt_rate_pct",
            "plain": "Distinct questions attempted out of the chapter's "
            "published bank.",
        },
        {"name": "hint_rate", "plain": "Average hints per practice answer."},
        {
            "name": "time_ratio",
            "plain": "Your weighted mean answer time over the expected time "
            "(the AI prior refined by an EWMA of all-student observed times, "
            "outlier-capped).",
        },
        {
            "name": "speaking_score_pct",
            "plain": "Recency-weighted mean of your explain-back scores.",
        },
        {
            "name": "trend",
            "plain": "Your last-14-days accuracy against your older answers "
            "for the same chapter.",
        },
    ]
    return payload


def rules(mode: str) -> dict[str, Any]:
    """The published constants (the page copy renders these, not prose)."""
    return {
        "version": RULES_VERSION,
        "formula_version": FORMULA_VERSION,
        "mode": mode,
        "half_life_days": HALF_LIFE_DAYS,
        "trend_window_days": TREND_WINDOW_DAYS,
        "trend_min_recent": TREND_MIN_RECENT,
        "trend_delta_pct": TREND_DELTA_PCT,
        "rated_min_items": RATED_MIN_ITEMS,
        "enough_data_min_chapters": ENOUGH_DATA_MIN_CHAPTERS,
        "absolute_performance_high_pct": ABSOLUTE_PERFORMANCE_HIGH_PCT,
        "absolute_coverage_high_pct": ABSOLUTE_COVERAGE_HIGH_PCT,
        "exam_weight_imp_min": EXAM_WEIGHT_IMP_MIN,
        "prior_min_observations": PRIOR_MIN_OBSERVATIONS,
        "prior_ewma_alpha": PRIOR_EWMA_ALPHA,
        "prior_outlier_cap_factor": PRIOR_OUTLIER_CAP_FACTOR,
    }


# --- per-chapter metrics -----------------------------------------------------


@dataclass(frozen=True)
class _Observation:
    """One scored observation with its recency weight."""

    at: datetime.datetime
    weight: float
    value: float  # 0..1 correctness (test submits carry their answer ratio)


def _chapter_metrics(data: SwotInput, now: datetime.datetime) -> list[dict[str, Any]]:
    catalogue = resolve_chapters(data.catalogue)
    progress_by_chapter = {str(row["chapter_id"]): row for row in data.lesson_progress}
    events_by_chapter: dict[str, list[EventRow]] = {}
    for event in data.events:
        if event.chapter_id:
            events_by_chapter.setdefault(str(event.chapter_id), []).append(event)
    speaking_by_chapter: dict[str, list[dict[str, Any]]] = {}
    for item in data.speaking:
        speaking_by_chapter.setdefault(item["chapter_id"], []).append(item)

    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for chapter_id, chapter in catalogue.items():
        seen.add(chapter_id)
        entries.append(
            _chapter_entry(
                data,
                chapter_id=chapter_id,
                title=chapter["title"],
                class_level=chapter["class_level"],
                chapter_no=chapter["chapter_no"],
                lesson_url=chapter["lesson_url"],
                events=events_by_chapter.get(chapter_id, []),
                speaking=speaking_by_chapter.get(chapter_id, []),
                progress=progress_by_chapter.get(chapter_id),
                now=now,
            )
        )
    # Activity outside the published catalogue stays visible under its
    # humanized id (F3's unmatched rule); it can still carry evidence.
    for chapter_id in sorted(set(events_by_chapter) - seen):
        entries.append(
            _chapter_entry(
                data,
                chapter_id=chapter_id,
                title=_humanize(chapter_id),
                class_level=None,
                chapter_no=0,
                lesson_url=None,
                events=events_by_chapter[chapter_id],
                speaking=speaking_by_chapter.get(chapter_id, []),
                progress=progress_by_chapter.get(chapter_id),
                now=now,
            )
        )
    return entries


def _chapter_entry(
    data: SwotInput,
    *,
    chapter_id: str,
    title: str,
    class_level: int | None,
    chapter_no: int,
    lesson_url: str | None,
    events: list[EventRow],
    speaking: list[dict[str, Any]],
    progress: dict[str, Any] | None,
    now: datetime.datetime,
) -> dict[str, Any]:
    ordered = sorted(events, key=lambda event: (event.created_at, event.event_id))
    observations: list[_Observation] = []
    hints = 0
    times: list[tuple[datetime.datetime, int]] = []
    question_ids: set[str] = set(data.attempted.get(chapter_id, set()))
    practice_count = 0
    test_count = 0
    for event in ordered:
        payload = event.payload
        at = event.created_at
        if event.kind == "practice_answer":
            practice_count += 1
            correct = payload.get("correct")
            if isinstance(correct, bool):
                observations.append(
                    _Observation(
                        at=at, weight=_weight(now, at), value=1.0 if correct else 0.0
                    )
                )
            hints += int(payload.get("hints_used") or 0)
            time_ms = payload.get("time_ms")
            if isinstance(time_ms, int) and time_ms > 0:
                times.append((at, time_ms))
            question = event.question_id
            if question:
                question_ids.add(str(question))
        elif event.kind == "test_submit":
            answered = payload.get("answered")
            correct = payload.get("correct")
            if (
                isinstance(answered, int)
                and answered > 0
                and isinstance(correct, int)
                and 0 <= correct <= answered
            ):
                test_count += 1
                observations.append(
                    _Observation(
                        at=at, weight=_weight(now, at), value=correct / answered
                    )
                )
    for item in speaking:
        at = as_utc(item["created_at"]) or now
        observations.append(
            _Observation(
                at=at, weight=_weight(now, at), value=float(item["score"]) / 100.0
            )
        )
    scored_items = practice_count + test_count + len(speaking)

    weighted_accuracy = _weighted_mean(
        [(item.value, item.weight) for item in observations]
    )
    performance = None if weighted_accuracy is None else weighted_accuracy * 100.0
    speaking_score = _weighted_mean(
        [
            (
                float(item["score"]) / 100.0,
                _weight(now, as_utc(item["created_at"]) or now),
            )
            for item in speaking
        ]
    )
    trend = _trend(observations, now)
    hint_rate = (hints / practice_count) if practice_count else None
    bank_count = data.question_counts.get(chapter_id, 0)
    attempt_rate = len(question_ids) * 100.0 / bank_count if bank_count > 0 else None
    coverage = attempt_rate
    if coverage is None and progress:
        seen_count = int(progress.get("blocks_seen") or 0)
        total = progress.get("blocks_total")
        if seen_count > 0 and total:
            coverage = min(100.0, seen_count * 100.0 / int(total))
    own_time = _weighted_mean([(float(ms), _weight(now, at)) for at, ms in times])
    prior = _effective_prior(
        ai_prior=data.priors.get(chapter_id),
        observations=data.all_student_times.get(chapter_id, []),
    )
    time_ratio = (
        own_time / prior
        if own_time is not None and prior is not None and prior > 0
        else None
    )
    exam_weight = data.exam_weights.get(chapter_id)
    metrics: dict[str, Any] = {
        "weighted_accuracy_pct": _round1(performance),
        "coverage_pct": _round1(coverage),
        "attempt_rate_pct": _round1(attempt_rate),
        "hint_rate": _round1(hint_rate),
        "time_ratio": _round1(time_ratio),
        "speaking_score_pct": _round1(
            None if speaking_score is None else speaking_score * 100.0
        ),
        "trend": trend,
        "scored_items": scored_items,
        "last_activity_at": _last_activity(ordered, speaking),
    }
    rated = (
        scored_items >= RATED_MIN_ITEMS
        and metrics["weighted_accuracy_pct"] is not None
        and metrics["coverage_pct"] is not None
    )
    metrics["confidence"] = _confidence(scored_items) if rated else None
    return {
        "chapter_id": chapter_id,
        "title": title,
        "class_level": class_level,
        "chapter_no": chapter_no,
        "lesson_url": lesson_url,
        "quadrant": None,
        "rated": rated,
        "exam_weight": exam_weight,
        "exam_priority": bool(
            exam_weight is not None and exam_weight >= EXAM_WEIGHT_IMP_MIN
        ),
        "metrics": metrics,
        "evidence": _evidence(metrics),
        "next_action": _next_action(
            metrics, lesson_url=lesson_url, chapter_id=chapter_id, rated=rated
        ),
        "unrated_reason": None if rated else _unrated_reason(metrics, scored_items),
    }


def _medians(rated: Sequence[Mapping[str, Any]]) -> dict[str, float] | None:
    """Median split over the student's own rated chapters."""
    if len(rated) < ENOUGH_DATA_MIN_CHAPTERS:
        return None
    performances = sorted(
        float(entry["metrics"]["weighted_accuracy_pct"]) for entry in rated
    )
    coverages = sorted(float(entry["metrics"]["coverage_pct"]) for entry in rated)
    return {
        "performance_pct": _median(performances),
        "coverage_pct": _median(coverages),
    }


def _place(entry: Mapping[str, Any], *, medians: Mapping[str, float] | None) -> str:
    metrics = entry["metrics"]
    performance = float(metrics["weighted_accuracy_pct"])
    coverage = float(metrics["coverage_pct"])
    if medians is not None:
        high_performance = performance >= medians["performance_pct"]
        high_coverage = coverage >= medians["coverage_pct"]
    else:
        # Absolute mode: the fixed, calibrated-elsewhere thresholds.
        high_performance = performance >= ABSOLUTE_PERFORMANCE_HIGH_PCT
        high_coverage = coverage >= ABSOLUTE_COVERAGE_HIGH_PCT
    if high_performance and high_coverage:
        return "strength"
    if not high_performance and high_coverage:
        return "weakness"
    if high_performance and not high_coverage:
        return "opportunity"
    return "threat"


def _urgency(quadrant: str, entry: Mapping[str, Any]) -> tuple[Any, ...]:
    """Order inside one quadrant: exam weight first, then the sharpest card."""
    weight = entry["exam_weight"] if entry["exam_weight"] is not None else 0.0
    performance = float(entry["metrics"]["weighted_accuracy_pct"])
    chapter_no = entry["chapter_no"]
    if quadrant in ("weakness", "threat"):
        # Board-heavy and lowest results first: the sharpest watch-out leads.
        return (0 if entry["exam_priority"] else 1, -weight, performance, chapter_no)
    # Board-heavy and strongest results first for the keep-it-warm boxes.
    return (0 if entry["exam_priority"] else 1, -weight, -performance, chapter_no)


def _weight(now: datetime.datetime, at: datetime.datetime) -> float:
    age_days = max(0.0, (now - at).total_seconds() / 86400.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def _weighted_mean(pairs: Sequence[tuple[float, float]]) -> float | None:
    total_weight = sum(weight for _, weight in pairs)
    if total_weight <= 0:
        return None
    return sum(value * weight for value, weight in pairs) / total_weight


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    count = len(ordered)
    middle = count // 2
    if count % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _trend(observations: Sequence[_Observation], now: datetime.datetime) -> str | None:
    """Last-14-days accuracy vs the older baseline for the same chapter."""
    cutoff = now - datetime.timedelta(days=TREND_WINDOW_DAYS)
    recent = [item for item in observations if item.at >= cutoff]
    older = [item for item in observations if item.at < cutoff]
    if len(recent) < TREND_MIN_RECENT or not older:
        return None
    recent_acc = sum(item.value * item.weight for item in recent) / sum(
        item.weight for item in recent
    )
    older_acc = sum(item.value * item.weight for item in older) / sum(
        item.weight for item in older
    )
    delta = (recent_acc - older_acc) * 100.0
    if delta >= TREND_DELTA_PCT:
        return "up"
    if delta <= -TREND_DELTA_PCT:
        return "down"
    return "steady"


def _effective_prior(
    *, ai_prior: int | None, observations: Sequence[tuple[datetime.datetime, int]]
) -> float | None:
    """The chapter's expected time: the AI prior refined by all-student EWMA.

    The EWMA is chained in chronological order with `PRIOR_EWMA_ALPHA`; each
    observation is capped at `PRIOR_OUTLIER_CAP_FACTOR` × the AI prior (or
    the A5 maximum when no prior exists) so one stalled attempt cannot move
    it. Until `PRIOR_MIN_OBSERVATIONS` capped observations exist, the AI
    prior stands alone; the A5 prior is never recomputed from history
    (assessment.md §6).
    """
    prior = ai_prior if (ai_prior is not None and ai_prior > 0) else None
    cap = (
        int(prior * PRIOR_OUTLIER_CAP_FACTOR)
        if prior is not None
        else PRIOR_FALLBACK_CAP_MS
    )
    capped = [min(max(1, int(ms)), cap) for _, ms in observations]
    if len(capped) < PRIOR_MIN_OBSERVATIONS:
        return float(prior) if prior is not None else None
    ewma = float(capped[0])
    for value in capped[1:]:
        ewma = (1.0 - PRIOR_EWMA_ALPHA) * ewma + PRIOR_EWMA_ALPHA * float(value)
    return ewma


def _confidence(scored_items: int) -> str:
    if scored_items >= 10:
        return "high"
    if scored_items >= 5:
        return "medium"
    return "low"


def _unrated_reason(metrics: Mapping[str, Any], scored_items: int) -> str:
    if metrics["weighted_accuracy_pct"] is None:
        return "No scored practice, test, or explain-back evidence yet."
    if metrics["coverage_pct"] is None:
        return (
            "Coverage is unknown: the chapter has no published question bank "
            "and no section total to measure against yet."
        )
    return (
        f"Only {scored_items} scored item(s) so far; "
        f"{RATED_MIN_ITEMS} unlock a placement."
    )


def _evidence(metrics: Mapping[str, Any]) -> list[str]:
    """2-3 plain-language bullets; pace is included when it exists."""
    bullets: list[str] = []
    accuracy = metrics["weighted_accuracy_pct"]
    if accuracy is not None:
        bullets.append(f"About {accuracy:.0f}% of scored answers correct.")
    coverage = metrics["coverage_pct"]
    if coverage is not None:
        bullets.append(f"Reached about {coverage:.0f}% of the chapter.")
    trend = metrics["trend"]
    if trend and len(bullets) < 3:
        bullets.append(TREND_LABELS[trend] + ".")
    time_ratio = metrics["time_ratio"]
    if time_ratio is not None and len(bullets) < 3:
        if time_ratio >= PACE_SLOW_RATIO:
            bullets.append(
                f"Taking about {time_ratio:.1f}× the expected time per answer "
                "— an exam-pace risk."
            )
        elif time_ratio <= PACE_FAST_RATIO:
            bullets.append(
                f"Answering in about {time_ratio:.1f}× the expected time — "
                "worth a second look before submitting."
            )
    hints = metrics["hint_rate"]
    if hints is not None and hints >= HINT_HEAVY_RATE and len(bullets) < 3:
        bullets.append(f"Uses about {hints:.1f} hints per practice answer.")
    speaking = metrics["speaking_score_pct"]
    if speaking is not None and len(bullets) < 3:
        bullets.append(f"Explain-backs average about {speaking:.0f}%.")
    return bullets[:3]


def _next_action(
    metrics: Mapping[str, Any],
    *,
    lesson_url: str | None,
    chapter_id: str,
    rated: bool,
) -> dict[str, Any]:
    """One honest action per card; the URL is always a live route."""
    accuracy = metrics["weighted_accuracy_pct"]
    coverage = metrics["coverage_pct"]
    if not rated:
        if accuracy is None:
            return {
                "text": "Do a short practice set on this chapter.",
                "url": f"/app/practice?chapter={chapter_id}",
            }
        return {
            "text": "Read the chapter and try its checks to build coverage.",
            "url": lesson_url or "/app/progress",
        }
    if accuracy is not None and accuracy < 50.0:
        return {
            "text": "Re-read the tricky sections, then retry a practice set.",
            "url": f"/app/practice?chapter={chapter_id}",
        }
    if coverage is not None and coverage < 40.0:
        return {
            "text": "Cover more of the chapter: the next sections are open.",
            "url": lesson_url or "/app/progress",
        }
    return {
        "text": "Keep it warm: one short practice set this week.",
        "url": f"/app/practice?chapter={chapter_id}",
    }


def _last_activity(
    events: Sequence[EventRow], speaking: Sequence[Mapping[str, Any]]
) -> str | None:
    stamps: list[datetime.datetime] = [event.created_at for event in events]
    stamps += [
        parsed
        for item in speaking
        if (parsed := as_utc(item["created_at"])) is not None
    ]
    return to_iso(max(stamps)) if stamps else None


def _round1(value: float | None) -> float | None:
    if value is None:
        return None
    if not math.isfinite(value):
        return None
    return round(value, 1)


def _humanize(chapter_id: str) -> str:
    raw = str(chapter_id or "").strip()
    if not raw:
        return "Untitled chapter"
    tail = raw.replace(":", "/").rstrip("/").split("/")[-1]
    words = tail.replace("-", " ").replace("_", " ").strip()
    if not words:
        return raw
    text = " ".join(words.split())
    return text[:1].upper() + text[1:]


__all__ = [
    "ABSOLUTE_COVERAGE_HIGH_PCT",
    "ABSOLUTE_PERFORMANCE_HIGH_PCT",
    "ENOUGH_DATA_MIN_CHAPTERS",
    "EXAM_WEIGHT_IMP_MIN",
    "FORMULA_VERSION",
    "HALF_LIFE_DAYS",
    "MODES",
    "PACE_FAST_RATIO",
    "PACE_SLOW_RATIO",
    "PRIOR_EWMA_ALPHA",
    "PRIOR_MIN_OBSERVATIONS",
    "PRIOR_OUTLIER_CAP_FACTOR",
    "QUADRANTS",
    "QUADRANT_BLURBS",
    "QUADRANT_LABELS",
    "RATED_MIN_ITEMS",
    "RULES_VERSION",
    "TREND_WINDOW_DAYS",
    "SwotInput",
    "SwotModeError",
    "build_swot",
    "build_swot_explain",
    "resolve_mode",
    "rules",
]
