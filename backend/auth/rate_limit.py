"""Per-endpoint auth rate limits (REQUIREMENTS §6.3, backend-spec §8.3).

Fixed 60-second windows keyed on the daily-rotating salted IP hash and the
endpoint family. In-memory by design: the monolith runs one replica in P0, and
the existing global abuse limiter (`backend/abuse.py`) has the same property.
A multi-replica deployment must move this counter to a shared store; that is
recorded in ADR-0029 rather than guessed at here.

The limiter is checked *before* password hashing so a flood never costs CPU.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from ..config import BackendConfig

MAX_TRACKED_KEYS: Final[int] = 10_000


@dataclass(frozen=True)
class LimitDecision:
    allowed: bool
    retry_after: int
    count: int
    limit: int


class AuthRateLimiter:
    """One fixed window per (family, ip_hash); expiry is lazy."""

    def __init__(
        self,
        config: BackendConfig,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self._clock = clock
        self._lock = threading.Lock()
        self._windows: dict[tuple[str, str], tuple[int, int]] = {}

    def limit_for(self, family: str) -> int:
        limits = {
            "register": self.config.auth_register_per_min,
            "login": self.config.auth_login_per_min,
            "reset": self.config.auth_reset_per_min,
            "verify": self.config.auth_verify_per_min,
            "google": self.config.auth_google_per_min,
        }
        # Unknown family falls back to the strictest limit, never to "unlimited".
        return int(limits.get(family, min(limits.values())))

    def check(self, family: str, ip_hash: str | None) -> LimitDecision:
        """Increment and evaluate the window for this caller."""
        limit = self.limit_for(family)
        key = (family, ip_hash or "anonymous")
        now = int(self._clock())
        window_start = now - (now % 60)
        with self._lock:
            if len(self._windows) > MAX_TRACKED_KEYS:
                self._prune(window_start)
            stored_window, count = self._windows.get(key, (window_start, 0))
            if stored_window != window_start:
                stored_window, count = window_start, 0
            count += 1
            self._windows[key] = (stored_window, count)
        return LimitDecision(
            allowed=count <= limit,
            retry_after=0 if count <= limit else max(1, 60 - (now % 60)),
            count=count,
            limit=limit,
        )

    def _prune(self, current_window: int) -> None:
        stale = [
            key
            for key, (window_start, _count) in self._windows.items()
            if window_start < current_window
        ]
        for key in stale:
            self._windows.pop(key, None)

    def reset(self) -> None:
        """Clear all windows (tests only)."""
        with self._lock:
            self._windows.clear()
