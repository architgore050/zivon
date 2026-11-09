"""Dashboard admin auth — exactly ADR-0026, nothing more.

Single shared secret (env `ZIVON_ADMIN_TOKEN`, mounted from the K8s Secret
`zivon-admin-auth`): login POSTs the token, the compare is constant-time, a
success sets an HttpOnly SameSite=Strict session cookie (opaque 128-bit id,
12 h TTL, 60 min idle re-auth, max 8 sessions with oldest evicted). Failures
get a generic 401, a 1 s constant delay, and an L3 `dashboard.auth_failure`
audit event; 5 failures / 15 min / source IP triggers a 15 min lockout
(`dashboard.auth_lockout`, CRITICAL). Fail-closed: with no secret configured
every admin route answers 503 and `dashboard.auth_unconfigured` is emitted
— the dashboard never falls back to open access.

Sessions live in-process (single replica; a pod restart drops them and
admins just re-login — accepted in ADR-0026). CSRF is the double-submit
token: rendered into each form, checked server-side on every action POST.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time
from dataclasses import dataclass, field

from logging_manager import ErrorClass, log_event

SESSION_COOKIE = "zivon_admin_session"
SESSION_TTL_S = 12 * 3600
SESSION_IDLE_S = 60 * 60
MAX_SESSIONS = 8
FAILURE_WINDOW_S = 15 * 60
FAILURE_LIMIT = 5
LOCKOUT_S = 15 * 60


def ip_truncated(ip: str) -> str:
    """A privacy-safe source marker for audit events (L3): IPv4 keeps its
    first two octets, anything else is not stored at all."""
    parts = ip.split(".")
    if len(parts) == 4:
        return ".".join(parts[:2]) + ".x.x"
    return "non-ipv4"


@dataclass
class _Session:
    id: str
    csrf: str
    created_at: float
    last_seen: float


@dataclass
class _FailureState:
    timestamps: list[float] = field(default_factory=list)
    locked_until: float = 0.0


class AdminAuth:
    def __init__(self) -> None:
        self.token: str | None = os.environ.get("ZIVON_ADMIN_TOKEN", "").strip() or None
        self._unconfigured_reported = False
        self.sessions: dict[str, _Session] = {}
        self.failures: dict[str, _FailureState] = {}
        self._boot_secret = secrets.token_hex(32)

    # ------------------------------------------------------------- config
    def configured(self) -> bool:
        if self.token is None and not self._unconfigured_reported:
            self._unconfigured_reported = True
            log_event(
                "dashboard.auth_unconfigured",
                {"secret_present": False},
                error_class=ErrorClass.AUTH_ERROR,
            )
        return self.token is not None

    # -------------------------------------------------------------- login
    def login_csrf_token(self) -> str:
        """The login form's CSRF token: HMAC over the issue time, valid for
        1 h (no session exists yet to bind it to)."""
        issued = int(time.time())
        digest = hmac.new(
            self._boot_secret.encode(), f"login:{issued}".encode(), hashlib.sha256
        ).hexdigest()
        return f"{issued}:{digest}"

    def login_csrf_valid(self, token: str) -> bool:
        try:
            issued_s, digest = token.split(":", 1)
            issued = int(issued_s)
        except ValueError:
            return False
        expected = hmac.new(
            self._boot_secret.encode(), f"login:{issued}".encode(), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(digest, expected) and time.time() - issued < 3600

    def login(self, token: str, source_ip: str) -> str | None:
        """Validate the token; returns the new session id, or None (after
        the constant delay + audit event)."""
        if not self.configured():
            return None
        state = self.failures.setdefault(source_ip, _FailureState())
        if time.time() < state.locked_until:
            log_event(
                "dashboard.auth_failure",
                {
                    "ip_truncated": ip_truncated(source_ip),
                    "attempts": len(state.timestamps),
                },
                error_class=ErrorClass.AUTH_ERROR,
            )
            return None
        ok = self.token is not None and hmac.compare_digest(token, self.token)
        if not ok:
            # ADR-0026: 1 s constant delay per failure (brute-force cost),
            # generic 401 (no enumeration surface), audited.
            time.sleep(1.0)
            state.timestamps = [
                ts for ts in state.timestamps if time.time() - ts < FAILURE_WINDOW_S
            ]
            state.timestamps.append(time.time())
            log_event(
                "dashboard.auth_failure",
                {
                    "ip_truncated": ip_truncated(source_ip),
                    "attempts": len(state.timestamps),
                },
                error_class=ErrorClass.AUTH_ERROR,
            )
            if len(state.timestamps) >= FAILURE_LIMIT:
                state.locked_until = time.time() + LOCKOUT_S
                log_event(
                    "dashboard.auth_lockout",
                    {
                        "ip_truncated": ip_truncated(source_ip),
                        "window_min": FAILURE_WINDOW_S // 60,
                    },
                    error_class=ErrorClass.AUTH_ERROR,
                )
            return None
        session_id = secrets.token_hex(16)  # opaque 128-bit id
        session = _Session(
            id=session_id,
            csrf=secrets.token_hex(16),
            created_at=time.time(),
            last_seen=time.time(),
        )
        self.sessions[session_id] = session
        self._evict_oldest()
        self.failures.pop(source_ip, None)
        log_event("dashboard.session_started", {"session_ref": session_id[:8]})
        return session_id

    def _evict_oldest(self) -> None:
        while len(self.sessions) > MAX_SESSIONS:
            oldest = min(self.sessions.values(), key=lambda s: s.last_seen)
            self.sessions.pop(oldest.id, None)

    # ------------------------------------------------------------ session
    def verify(self, session_id: str | None) -> bool:
        if session_id is None or not self.configured():
            return False
        session = self.sessions.get(session_id)
        if session is None:
            return False
        now = time.time()
        if (
            now - session.created_at > SESSION_TTL_S
            or now - session.last_seen > SESSION_IDLE_S
        ):
            self.sessions.pop(session_id, None)
            return False
        session.last_seen = now
        return True

    def csrf_for(self, session_id: str | None) -> str | None:
        session = self.sessions.get(session_id or "")
        return session.csrf if session else None

    def csrf_valid(self, session_id: str | None, token: str | None) -> bool:
        session = self.sessions.get(session_id or "")
        if session is None or not token:
            return False
        return hmac.compare_digest(token, session.csrf)

    def logout(self, session_id: str | None) -> None:
        self.sessions.pop(session_id or "", None)

    def open_sessions(self) -> int:
        return len(self.sessions)
