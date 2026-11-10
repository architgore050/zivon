"""Data models for the credit guard (ADR-0015, A-05, A-06)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GuardProfileConfig:
    """Singleton guard configuration loaded from `guard_profile` (id=1)."""

    mode: str = "normal"
    global_tranche: float = 1000.0
    per_user_cap: float = 30.0
    demo_global_tranche: float = 1000.0
    demo_per_user_cap: float = 100.0
    warn_threshold_pct: float = 15.0
    total_budget_credits: float = 10000.0
    demo_reserve_pct: float = 40.0

    @property
    def active_global_cap(self) -> float:
        return self.demo_global_tranche if self.mode == "demo" else self.global_tranche

    @property
    def active_device_cap(self) -> float:
        return self.demo_per_user_cap if self.mode == "demo" else self.per_user_cap

    @property
    def normal_ceiling_credits(self) -> float:
        """Maximum cumulative spend allowed in `normal` mode before hitting the 40% demo reserve."""
        reserve_ratio = max(0.0, min(100.0, self.demo_reserve_pct)) / 100.0
        return round(self.total_budget_credits * (1.0 - reserve_ratio), 4)


@dataclass(frozen=True)
class GuardStatus:
    """Snapshot of guard counters and state exposed to EX1-VOICE and EX3-OBS."""

    period: str
    mode: str
    global_state: str
    device_state: str
    effective_state: str
    global_used: float
    global_cap: float
    global_remaining: float
    device_used: float
    device_cap: float
    device_remaining: float
    total_programme_used: float
    total_programme_ceiling: float
    warn_threshold_pct: float

    @property
    def voice_flag(self) -> str:
        """Return session flag string (`voice_enabled` or `typed_only`)."""
        if self.effective_state == "exhausted":
            return "typed_only"
        return "voice_enabled"

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.period,
            "mode": self.mode,
            "global_state": self.global_state,
            "device_state": self.device_state,
            "effective_state": self.effective_state,
            "voice_flag": self.voice_flag,
            "global_used": round(self.global_used, 4),
            "global_cap": round(self.global_cap, 4),
            "global_remaining": round(self.global_remaining, 4),
            "device_used": round(self.device_used, 4),
            "device_cap": round(self.device_cap, 4),
            "device_remaining": round(self.device_remaining, 4),
            "total_programme_used": round(self.total_programme_used, 4),
            "total_programme_ceiling": round(self.total_programme_ceiling, 4),
            "warn_threshold_pct": round(self.warn_threshold_pct, 2),
        }


@dataclass(frozen=True)
class GuardDecision:
    """Result of an atomic pre-turn credit reservation/decrement."""

    allowed: bool
    reason: str
    status: GuardStatus
    reserved_credits: float = 0.0
