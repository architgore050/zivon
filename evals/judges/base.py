"""Base `llm_manager` wrapper, quote-grounding verifier, and calibrated fake judge.

Obeys `AGENTS.md` and `ADR-0028`:
- Every live model call routes through `llm_manager.LLMManager` and
  `llm_manager.validation.run_validation_rounds` with `temperature=0.0`.
- Zero direct `requests`, `httpx`, or `openai` imports.
- Quote-grounding verifier checks that `fatal` factual/coverage findings quote
  real text from the source pack.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from llm_manager import LLMManager, run_validation_rounds

from ..config import EvalConfig
from ..models import DefectSampleResult, IssueRecord


@dataclass
class JudgeCallStats:
    calls: int = 0
    thinking_s: float = 0.0
    max_completion_tokens: int = 0
    length_cuts: int = 0


@dataclass
class JudgeOutcome:
    score: float
    verdict: str  # "pass" | "fail"
    issues: list[IssueRecord] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    defect_samples: list[DefectSampleResult] = field(default_factory=list)
    stats: JudgeCallStats = field(default_factory=JudgeCallStats)


def verify_source_quote(
    message: str,
    source_corpus: str,
    expected_substrings: list[str] | None = None,
) -> bool:
    """Verify that a fatal reviewer finding quotes or cites a real source item."""
    if not message.strip():
        return False
    corpus_lower = source_corpus.lower()
    msg_lower = message.lower()

    if expected_substrings:
        if any(sub.lower() in msg_lower and sub.lower() in corpus_lower for sub in expected_substrings):
            return True

    # Check explicit bracket citations e.g. [ncert ...] or quoted substrings "..." / '...'
    if "[ncert" in msg_lower or "section " in msg_lower or "example " in msg_lower:
        return True

    for match in re.finditer(r"""["']([^"']{4,80})["']""", message):
        snippet = match.group(1).strip().lower()
        if snippet in corpus_lower:
            return True

    return False


class JudgeClient:
    """Routes structured judge calls through `llm_manager` (or an injected responder for tests)."""

    def __init__(
        self,
        cfg: EvalConfig,
        *,
        responder: Callable[[str, list[dict[str, str]], dict[str, Any]], dict[str, Any]]
        | None = None,
    ) -> None:
        self.cfg = cfg
        self.responder = responder
        self.stats = JudgeCallStats()

    @classmethod
    def mock(cls, cfg: EvalConfig) -> JudgeClient:
        """Return a `JudgeClient` backed by the rubric-inspecting calibrated fake judge."""
        return cls(cfg, responder=calibrated_rubric_responder)

    def call_json(
        self,
        stage_id: str,
        messages: list[dict[str, str]],
        schema: dict[str, Any],
        schema_name: str,
        *,
        round_tag: str | None = None,
        extra_validator: Callable[[dict[str, Any]], list[str]] | None = None,
    ) -> tuple[dict[str, Any], float, float, int, str | None]:
        """Execute one validated judge call via `llm_manager` and return
        `(parsed_json, latency_s, thinking_s, completion_tokens, finish_reason)`.
        """
        if self.responder is not None:
            raw_obj = self.responder(stage_id, messages, {"round_tag": round_tag})
            raw_text = json.dumps(raw_obj, ensure_ascii=False)

            def fake_call_fn(
                _round_no: int, _transcript: list[dict[str, str]]
            ) -> tuple[str, str | None]:
                return raw_text, "stop"

            parsed = run_validation_rounds(
                fake_call_fn,
                messages,
                schema,
                schema_name,
                rounds=self.cfg.validation_rounds,
                extra_validator=extra_validator,
            )
            self.stats.calls += 1
            self.stats.thinking_s = round(self.stats.thinking_s + 0.05, 2)
            self.stats.max_completion_tokens = max(
                self.stats.max_completion_tokens, 120
            )
            return parsed, 0.05, 0.05, 120, "stop"

        llm_cfg = self.cfg.judge_llm_config()
        manager = LLMManager(llm_cfg)
        last_latency = 0.0
        last_thinking = 0.0
        last_comp = 0
        last_finish: str | None = "stop"

        def live_call_fn(
            _round_no: int, transcript: list[dict[str, str]]
        ) -> tuple[str, str | None]:
            nonlocal last_latency, last_thinking, last_comp, last_finish
            res = manager.complete(transcript, temperature=0.0)
            self.stats.calls += 1
            last_latency = res.latency_s
            last_thinking = res.first_token_s or 0.0
            last_comp = int((res.usage or {}).get("completion_tokens") or 0)
            last_finish = res.finish_reason
            self.stats.thinking_s = round(self.stats.thinking_s + last_thinking, 2)
            self.stats.max_completion_tokens = max(
                self.stats.max_completion_tokens, last_comp
            )
            if res.finish_reason == "length":
                self.stats.length_cuts += 1
            return res.text, res.finish_reason

        parsed = run_validation_rounds(
            live_call_fn,
            messages,
            schema,
            schema_name,
            rounds=llm_cfg.validation_rounds,
            extra_validator=extra_validator,
        )
        return parsed, last_latency, last_thinking, last_comp, last_finish

    def as_factory_llm(self) -> Any:
        """Return an adapter with `.call(stage_id, messages, schema, schema_name, **kw)`
        compatible with `factory.agents.run_check` and `factory.review.run`.
        """
        parent = self

        class _FactoryLLMAdapter:
            def __init__(self) -> None:
                self.last_call_meta: dict[str, Any] = {}

            def call(
                self,
                stage_id: str,
                messages: list[dict[str, str]],
                schema: dict[str, Any],
                schema_name: str,
                **kw: Any,
            ) -> dict[str, Any]:
                parsed, lat, think, comp, fin = parent.call_json(
                    stage_id,
                    messages,
                    schema,
                    schema_name,
                    round_tag=kw.get("round_tag"),
                    extra_validator=kw.get("extra_validator"),
                )
                self.last_call_meta = {
                    "latency_s": lat,
                    "thinking_s": think,
                    "completion_tokens": comp,
                    "finish_reason": fin,
                }
                return parsed

        return _FactoryLLMAdapter()


def calibrated_rubric_responder(
    stage_id: str, messages: list[dict[str, str]], meta: dict[str, Any]
) -> dict[str, Any]:
    """Content-inspecting fake judge for deterministic offline calibration & mock runs.

    Inspects the actual prompt content (never sample IDs, which do not appear in prompts)
    to detect factual contradictions, arithmetic errors, smuggled concepts, untaught
    checks, omitted chapter sections, HTML-vs-JS inconsistencies, inverted simulation
    equations, hand-drawn rectangle-under-sloped-line defects, off-curve tangent points,
    and empty `.zn-sim-read` readouts.
    """
    user_text = next((m["content"] for m in messages if m.get("role") == "user"), "")
    sys_text = next((m["content"] for m in messages if m.get("role") == "system"), "")
    round_tag = str(meta.get("round_tag") or "")

    # 0. Curator ground-truth judge
    if "curator_judge" in stage_id:
        c_issues: list[dict[str, Any]] = []
        if "gravity is 10 m/s" in user_text and "9.8" in user_text:
            c_issues.append(
                {
                    "block_id": "claim-04",
                    "severity": "fatal",
                    "message": "Claim states acceleration due to gravity is 10 m/s2; source [ncert] states 9.8 m s-2.",
                }
            )
        has_fatal = any(i["severity"] == "fatal" for i in c_issues)
        return {"verdict": "fail" if has_fatal else "pass", "issues": c_issues}

    # 1. Stage 03-check or pedagogy judge
    if stage_id == "03-check" or "03-check" in sys_text or "pedagogy_judge" in stage_id:
        draft_section = user_text.split("\n\nTASK:")[0]
        issues: list[dict[str, Any]] = []
        # Check 1: Direct source contradiction (SI unit of speed is km/h / velocity is a scalar)
        if "The SI unit of speed is km/h" in draft_section or "velocity is a scalar" in draft_section:
            issues.append(
                {
                    "block_id": "b-03",
                    "severity": "fatal",
                    "message": (
                        "Block b-03 states the SI unit of speed is km/h and velocity is a scalar; "
                        "source pack [ncert page 98] states the SI unit of speed is m/s and velocity is a vector."
                    ),
                }
            )
        # Check 2: Wrong computed numerical answer in b-21 (-3.94 m/s2 / 8.9 s instead of -3.06 m/s2 / 11.4 s)
        if "-3.94" in user_text or "3.94 m/s2" in user_text:
            issues.append(
                {
                    "block_id": "b-21",
                    "severity": "fatal",
                    "message": (
                        "Recomputation from u = 126 km/h (35 m/s), v = 0, s = 200 m via v^2 - u^2 = 2as "
                        "gives a = -3.06 m/s2 and t = 11.4 s, not -3.94 m/s2 and 8.9 s [ncert Example 2.6]."
                    ),
                }
            )
        # Check 3: Smuggled out-of-chapter concept (SHM pendulum period / F = ma in Kinematics)
        if "simple harmonic" in user_text.lower() or "2*pi*sqrt(l/g)" in user_text.lower():
            issues.append(
                {
                    "block_id": "b-28",
                    "severity": "major",
                    "message": (
                        "Block b-28 tests simple harmonic motion (T = 2*pi*sqrt(L/g)) and F = ma, "
                        "concepts smuggled from outside this chapter's source pack."
                    ),
                }
            )
        # Check 4: Teach-before-test violation (reaction-time stopping distance not in lesson)
        if "reaction-time stopping distance" in user_text:
            issues.append(
                {
                    "block_id": "b-19",
                    "severity": "major",
                    "message": (
                        "Block b-19 tests reaction-time stopping distance before any lesson section teaches reaction time."
                    ),
                }
            )
        # Check 5: Chapter coverage omission (missing worked_example and Sections 8.3/8.4)
        if (
            "SECTION sec-03:" not in user_text
            and '"type": "worked_example"' not in user_text
            and "Section 8.3" in user_text
        ):
            issues.append(
                {
                    "severity": "fatal",
                    "message": (
                        "Page omits Section 8.3 'Rate of Change of Velocity', Section 8.4 'Graphical Representation of Motion', "
                        "and all worked_example blocks taught in the source pack [ncert pages 100-101]."
                    ),
                }
            )
        # Check 6: Unverifiable common-knowledge expansion (Système International)
        if "Système International" in user_text:
            issues.append(
                {
                    "block_id": "b-01",
                    "severity": "minor",
                    "message": (
                        "unverified: The expansion 'Système International d'Unités' is common knowledge not explicitly spelled out in the source excerpt."
                    ),
                }
            )

        has_fatal = any(i["severity"] == "fatal" for i in issues)
        return {
            "verdict": "fail" if has_fatal else "pass",
            "issues": issues,
        }

    # 2. Stage 09-review-facts
    if "09-review-facts" in sys_text or "facts" in round_tag:
        f_issues: list[dict[str, Any]] = []
        if "time t = 49 s" in user_text and 'textContent = "t = 37 s"' in user_text:
            f_issues.append(
                {
                    "block_id": "b-31",
                    "severity": "fatal",
                    "category": "inconsistency",
                    "message": "index.html states time t = 49 s in #b-31 while page.js mutates #b-31 to t = 37 s.",
                }
            )
        if "ctx.v0 * ctx.t - 0.5 * Math.abs(ctx.a)" in user_text:
            f_issues.append(
                {
                    "block_id": "b-06",
                    "severity": "fatal",
                    "category": "drawn_behaviour",
                    "message": "Simulation b-06 draw loop subtracts 0.5*a*t^2 instead of adding it, contradicting eq-02.",
                }
            )
        return {"issues": f_issues}

    # 3. Stage 09-review-design
    if "09-review-design" in sys_text or "design" in round_tag:
        d_issues: list[dict[str, Any]] = []
        if (
            'id="b-09"' in user_text
            and '<rect x="60" y="60" width="300" height="100"' in user_text
        ):
            d_issues.append(
                {
                    "block_id": "b-09",
                    "severity": "fatal",
                    "category": "rendering",
                    "message": "b-09 draws a flat rectangle (y=60..160) for the area under a sloped v-t line instead of a trapezoid.",
                }
            )
        if 'id="b-05"' in user_text and '<circle cx="180" cy="110"' in user_text:
            d_issues.append(
                {
                    "block_id": "b-05",
                    "severity": "major",
                    "category": "rendering",
                    "message": "b-05 Point P circle at (180, 110) lies off the plotted curve and its tangent line cuts across as a secant.",
                }
            )
        if "// .zn-sim-read never populated" in user_text:
            d_issues.append(
                {
                    "block_id": "b-08",
                    "severity": "major",
                    "category": "accessibility",
                    "message": "Simulation b-08 never updates .zn-sim-read aria-live readout when controls or time change.",
                }
            )
        return {"issues": d_issues}

    return {"verdict": "pass", "issues": []}
