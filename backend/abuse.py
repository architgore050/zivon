"""Salted daily-rotating HMAC IP hash and per-family rate limiter (A-12, §8.3).

Rules (backend-spec §1.2 A-12, §8.3, db-spec §4.15):
- Raw client IP addresses are NEVER stored in memory or database tables.
- Only `HMAC_SHA256(ip, f"{daily_salt}:{utc_date}")` is stored in `abuse_bucket`.
- `abuse_bucket` rows expire after `<= 72 h` (`ABUSE_BUCKET_TTL_HOURS = 72`) and
  are NEVER joined to `device`, `session`, or any pseudonymous learner data.
- Per-family rate limits per IP hash, with per-family window sizes
  (data-and-api.md §4.1 — "window size per family, not just per-minute"):
  `api`: 30/min, `ws`: 10/min, `events`: 12/min, `reports`: 5/min,
  `delete`: 3/min, `static`: 100/min, `audio`: 60/min, and the
  personalized-learning families: `personalized_turn`: 6/min,
  `personalized_create`: 5/h, `personalized_read`: 60/min,
  `personalized_ip`: 20/min.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import ipaddress
import threading
from dataclasses import dataclass
from typing import Any, Final

from fastapi import Request

from .config import BackendConfig

ABUSE_BUCKET_TTL_HOURS: Final[int] = 72

# Window size per family, in seconds (§4.1: the create family is hourly).
FAMILY_WINDOW_SECONDS: Final[dict[str, int]] = {
    "api": 60,
    "ws": 60,
    "events": 60,
    "reports": 60,
    "delete": 60,
    "static": 60,
    "audio": 60,
    "personalized_turn": 60,
    "personalized_create": 3600,
    "personalized_read": 60,
    "personalized_ip": 60,
}

EXEMPT_PATHS: Final[frozenset[str]] = frozenset(
    {
        "/healthz",
        "/readyz",
        "/v1/health",
    }
)


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    family: str
    bucket_key: str
    count: int
    limit: int
    retry_after: int


def compute_ip_hmac(
    raw_ip: str,
    salt: str,
    *,
    utc_date: datetime.date | str | None = None,
) -> str:
    """Compute the daily-rotating salted HMAC-SHA256 hash of an IP address (A-12).

    Rotating the effective HMAC key daily by incorporating the UTC date ensures
    that across days the same IP produces an unlinkable digest without storing
    the raw IP anywhere.
    """
    cleaned_ip = (raw_ip or "127.0.0.1").strip().lower()
    if utc_date is None:
        day_str = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
    elif isinstance(utc_date, datetime.date):
        day_str = utc_date.strftime("%Y-%m-%d")
    else:
        day_str = str(utc_date).strip()

    daily_key = f"{salt}:{day_str}".encode()
    return hmac.new(daily_key, cleaned_ip.encode("utf-8"), hashlib.sha256).hexdigest()


def classify_endpoint_family(method: str, path: str) -> str | None:
    """Map an HTTP method and path to its rate-limit family (`backend-spec.md` §8.3).

    The personalized-learning families (data-and-api.md §4.1) are matched
    BEFORE the generic `/v1/*` catch-all: `personalized_turn` on the turn
    endpoint, `personalized_create` on session create, `personalized_read` on
    the surface's GETs, and `personalized_ip` as the brake on the remaining
    writes (preferences save/clear, session delete, session end).
    """
    if path in EXEMPT_PATHS:
        return None
    if path.startswith("/v1/admin"):
        return None
    if path in ("/v1/events", "/api/v1/events"):
        return "events"
    if path == "/v1/reports" and method.upper() == "POST":
        return "reports"
    if path == "/v1/data" and method.upper() == "DELETE":
        return "delete"
    if path.startswith("/audio/"):
        return "audio"
    if path.startswith(("/courses/", "/bundles/")) or path == "/courses.js":
        return "static"
    if path in ("/v1/voice", "/voice/ws"):
        return "ws"
    if path.startswith("/v1/personalized") or path == "/v1/me/preferences":
        method_upper = method.upper()
        if method_upper == "POST" and path.endswith("/turns"):
            return "personalized_turn"
        if method_upper == "POST" and path.rstrip("/") == "/v1/personalized/sessions":
            return "personalized_create"
        if method_upper == "GET":
            return "personalized_read"
        return "personalized_ip"
    if path.startswith("/v1/"):
        return "api"
    return None


def _valid_ip(value: str | None) -> str | None:
    """Return a normalised IP literal, or None for an empty/non-IP value."""
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return str(ipaddress.ip_address(cleaned))
    except ValueError:
        return None


def extract_client_ip(request: Request) -> str:
    """Extract the proxy-observed client IP for rate limiting.

    The edge nginx sets `X-Real-IP` to `$remote_addr` (overwriting whatever a
    client sent) and appends the connection peer to `X-Forwarded-For` with
    `$proxy_add_x_forwarded_for`. The **first** XFF element is therefore
    client-controlled and keying a limiter on it lets an attacker bypass the
    limit by rotating a spoofed header; the **last** element is the hop the
    proxy actually saw. Prefer `X-Real-IP`, then the last valid XFF hop, then
    the socket peer (voice/ws_api.py uses the same right-to-left rule).
    """
    real = _valid_ip(request.headers.get("X-Real-IP"))
    if real is not None:
        return real
    xff = request.headers.get("X-Forwarded-For", "").strip()
    if xff:
        for hop in reversed(xff.split(",")):
            valid = _valid_ip(hop)
            if valid is not None:
                return valid
    if request.client and request.client.host:
        return str(request.client.host)
    return "127.0.0.1"


class AbuseRateLimiter:
    """Per-family rate limiter backed by in-memory counters and `abuse_bucket` (U2)."""

    def __init__(self, config: BackendConfig, db: Any = None) -> None:
        self.config = config
        self.db = db
        self._lock = threading.Lock()
        self._active_ws_by_session: dict[str, int] = {}
        self._active_ws_cluster: int = 0

    def family_limit(self, family: str) -> int:
        limits = {
            "api": self.config.rate_limit_api_per_min,
            "ws": self.config.rate_limit_ws_per_min,
            "events": self.config.rate_limit_events_per_min,
            "reports": self.config.rate_limit_reports_per_min,
            "delete": self.config.rate_limit_delete_per_min,
            "static": 100,
            "audio": 60,
            "personalized_turn": self.config.rate_limit_personalized_turn_per_min,
            "personalized_create": self.config.rate_limit_personalized_create_per_hour,
            "personalized_read": self.config.rate_limit_personalized_read_per_min,
            "personalized_ip": self.config.rate_limit_personalized_ip_per_min,
        }
        return int(limits.get(family, self.config.rate_limit_api_per_min))

    def family_window_seconds(self, family: str) -> int:
        """Window size per family (§4.1): 60 s except the hourly create family."""
        return FAMILY_WINDOW_SECONDS.get(family, 60)

    def check_and_increment(
        self,
        raw_ip: str,
        family: str,
        *,
        now_dt: datetime.datetime | None = None,
    ) -> RateLimitDecision:
        """Increment the 60s window counter for `(ip_hmac, family)` and check limit."""
        now = now_dt or datetime.datetime.now(datetime.UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=datetime.UTC)

        day_str = now.strftime("%Y-%m-%d")
        bucket_key = compute_ip_hmac(raw_ip, self.config.ip_hash_salt, utc_date=day_str)
        window_s = self.family_window_seconds(family)
        window_dt = now.replace(second=0, microsecond=0)
        if window_s >= 3600:
            window_dt = window_dt.replace(minute=0)
        window_start = window_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_dt = window_dt + datetime.timedelta(hours=ABUSE_BUCKET_TTL_HOURS)
        expires_at = expires_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        limit = self.family_limit(family)
        elapsed = (now - window_dt).total_seconds()
        retry_after = max(1, int(window_s - elapsed))

        with self._lock:
            if self.db is not None:
                with self.db.transaction() as tx:
                    tx.execute(
                        """
                        INSERT INTO abuse_bucket (bucket_key, endpoint_family, window_start, count, expires_at)
                        VALUES (?, ?, ?, 1, ?)
                        ON CONFLICT (bucket_key, endpoint_family, window_start) DO UPDATE SET
                            count = abuse_bucket.count + 1
                        """,
                        (bucket_key, family, window_start, expires_at),
                    )
                    row = tx.fetchone(
                        """
                        SELECT count FROM abuse_bucket
                        WHERE bucket_key = ? AND endpoint_family = ? AND window_start = ?
                        """,
                        (bucket_key, family, window_start),
                    )
                    count = int(row["count"]) if row else 1
            else:
                count = 1

        allowed = count <= limit
        return RateLimitDecision(
            allowed=allowed,
            family=family,
            bucket_key=bucket_key,
            count=count,
            limit=limit,
            retry_after=0 if allowed else retry_after,
        )

    def check_http_request(self, request: Request) -> RateLimitDecision:
        """Evaluate rate limits for an incoming FastAPI HTTP Request."""
        family = classify_endpoint_family(request.method, request.url.path)
        if family is None:
            return RateLimitDecision(
                allowed=True,
                family="exempt",
                bucket_key="",
                count=0,
                limit=0,
                retry_after=0,
            )
        raw_ip = extract_client_ip(request)
        return self.check_and_increment(raw_ip, family)

    def try_acquire_ws_slot(self, session_id: str) -> bool:
        """Enforce 1 concurrent WS per session and 10 cluster-wide (§8.3)."""
        with self._lock:
            if self._active_ws_cluster >= self.config.ws_max_concurrent_cluster:
                return False
            curr = self._active_ws_by_session.get(session_id, 0)
            if curr >= self.config.ws_max_concurrent_per_session:
                return False
            self._active_ws_by_session[session_id] = curr + 1
            self._active_ws_cluster += 1
            return True

    def release_ws_slot(self, session_id: str) -> None:
        """Release a concurrent WS slot on disconnect."""
        with self._lock:
            curr = self._active_ws_by_session.get(session_id, 0)
            if curr > 0:
                if curr == 1:
                    self._active_ws_by_session.pop(session_id, None)
                else:
                    self._active_ws_by_session[session_id] = curr - 1
                self._active_ws_cluster = max(0, self._active_ws_cluster - 1)
