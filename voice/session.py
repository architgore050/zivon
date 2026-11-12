"""Session store adapter, session tokens, rate limits, credit guard.

spec.md §3 ``session`` module: session state (ADR-0002 memory + Postgres
rows), ``voice_turn`` rows (Appendix B, A-02 7-day TTL), and the credit
ledger + guard checks (§8, ADR-0015 / NEED-009). Voice adds no new store:
the core backend (EX0) owns the real Postgres implementation and injects it
via ``mount_voice``; the in-memory implementations here are the ADR-0002
default (lost-on-crash acceptable, 1 replica at demo scale) and the test
seam.

Auth (GAP-003, backend-spec §8.1): ``session_token`` = HMAC-signed
``{session_id, device_pseudo_id, iat, exp 12 h}`` — validated the same way
whether it arrives as the ``?session_token=`` query parameter (S0) or inside
``session.start`` (SP1 ws-contract). Invalid/expired → close 4401. Tokens
never appear in logs.

Rate limits (GAP-003, backend-spec §8.3): ws connects ≤ 10/min per IP hash
**and** per pseudonymous device id (the secondary bucket keeps the limit
meaningful behind an ingress, where every direct peer is the proxy pod),
1 concurrent channel per session, 10 cluster-wide (process-global at the P0
1-replica scale). IP hash = HMAC(salt + IST date, ip) truncated, salted from
``ZIVON_IP_HASH_SALT`` — the raw IP is never stored, and buckets expire
≤ 72 h.

Credit guard units (OQ-06 placeholder): every counter is in credit POINTS —
1 point = 30 s Prisma audio = 300 Timbre characters (see ``credit_points``),
so the per-user cap (30/day) and the A-07 turn estimate (≈ 3 points) are
commensurable. Caps and actuals are never mixed with raw vendor units.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time
import uuid
import zoneinfo
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from .config import VoiceSettings
from .logging_surface import ErrorClass, Severity, log_event

__all__ = [
    "CreditGuard",
    "GuardDecision",
    "IpRateLimiter",
    "SessionIdentity",
    "SessionStore",
    "TokenValidator",
    "TurnRecord",
    "TurnRepository",
    "VoiceSession",
    "credit_points",
    "issue_session_token",
    "turn_estimate",
]

_IST = zoneinfo.ZoneInfo("Asia/Kolkata")
_TOKEN_TTL_S = 12 * 3600  # backend-spec §8.1: exp 12 h


# --- session token (API-001 / GAP-003) ---------------------------------------


@dataclass(frozen=True)
class SessionIdentity:
    session_id: str
    device_pseudo_id: str


def issue_session_token(
    session_id: str, device_pseudo_id: str, key: str, *, now: float | None = None
) -> str:
    """HMAC-sign a session token (dev/tests; core backend issues the real one)."""
    issued = now if now is not None else time.time()
    payload = json.dumps(
        {
            "session_id": session_id,
            "device_pseudo_id": device_pseudo_id,
            "iat": int(issued),
            "exp": int(issued + _TOKEN_TTL_S),
        },
        separators=(",", ":"),
        sort_keys=True,
    )
    import base64

    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    # Full HMAC-SHA256 hex digest: this must stay byte-compatible with the
    # core backend's IdentityManager._sign (backend/identity.py), because the
    # core backend issues the real session_token and this package only
    # validates it (EX6 weld: a truncated digest silently 4401'd every
    # backend-issued token).
    sig = hmac.new(key.encode(), body.encode(), hashlib.sha256).hexdigest()
    return f"{body}.{sig}"


class TokenValidator:
    """Validates both S0 (query param) and SP1 (session.start) ingress shapes."""

    def __init__(self, key: str) -> None:
        self._key = key

    def validate(
        self, token: str | None, *, now: float | None = None
    ) -> SessionIdentity | None:
        if not token or not self._key or "." not in token:
            return None
        import base64

        body, _, sig = token.rpartition(".")
        if not body or not sig:
            return None
        expected = hmac.new(
            self._key.encode(), body.encode(), hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        try:
            padded = body + "=" * (-len(body) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode()))
            session_id = payload["session_id"]
            device = payload["device_pseudo_id"]
            if float(payload["exp"]) < (now if now is not None else time.time()):
                return None  # expired
        except (KeyError, ValueError, TypeError):
            return None
        if not session_id or not device:
            return None
        return SessionIdentity(session_id=str(session_id), device_pseudo_id=str(device))


# --- rate limits (GAP-003) -----------------------------------------------------


class IpRateLimiter:
    """Salted daily-rotating IP hash buckets; raw IPs are never kept.

    Buckets are keyed on HMAC(salt + IST date, ip)[:16] and pruned past 72 h
    (backend-spec §8.3 posture). In-process at the P0 1-replica scale; the
    cluster cap is enforced as the process-global session ceiling.
    """

    BUCKET_TTL_S = 72 * 3600

    def __init__(
        self, settings: VoiceSettings, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._salt = settings.ip_hash_salt
        self._windows: dict[str, list[float]] = {}
        self._bucket_ts: dict[str, float] = {}

    def hash_ip(self, ip: str) -> str:
        moment = datetime.fromtimestamp(self._clock(), tz=UTC).astimezone(_IST)
        day = moment.strftime("%Y%m%d")  # injected clock: testable, daily-rotating
        material = f"{self._salt}:{day}:{ip}"
        return hmac.new(material.encode(), b"ip", hashlib.sha256).hexdigest()[:16]

    def allow_connect(self, ip: str) -> bool:
        """ws family: ≤ 10 connects/min per IP hash (GAP-003)."""
        return self._allow(f"ip:{ip}", self.hash_ip(ip))

    def allow_device(self, device_pseudo_id: str) -> bool:
        """Secondary bucket on the (post-auth) pseudonymous device id.

        Behind an ingress the direct peer is the proxy pod, so the IP bucket
        alone degrades to one global bucket; the device bucket keeps the
        per-client limit meaningful and survives NAT/egress sharing.
        """
        if not self._salt:  # salt unconfigured: fail open but loudly
            return True
        material = f"{self._salt}:device:{device_pseudo_id}"
        key = hmac.new(material.encode(), b"dev", hashlib.sha256).hexdigest()[:16]
        return self._allow(f"dev:{key}", key)

    def _allow(self, bucket: str, key: str) -> bool:
        if not self._salt:  # salt unconfigured: fail open but loudly
            log_event(
                "voice.ratelimit.unsalted",
                {},
                severity=Severity.WARNING,
                error_class=ErrorClass.AUTH_ERROR,
            )
            return True
        now = self._clock()
        self._prune(now)
        window = [t for t in self._windows.get(bucket, []) if now - t < 60.0]
        if len(window) >= self._settings.ws_connects_per_min:
            self._windows[bucket] = window
            return False
        window.append(now)
        self._windows[bucket] = window
        self._bucket_ts[bucket] = now
        return True

    def _prune(self, now: float) -> None:
        stale = [k for k, ts in self._bucket_ts.items() if now - ts > self.BUCKET_TTL_S]
        for key in stale:
            self._windows.pop(key, None)
            self._bucket_ts.pop(key, None)


# --- credit guard (ADR-0015 / NEED-009; spec.md §8 hooks) ----------------------


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    state: str  # ok | warn | exhausted | reserved_mode
    reason_code: str  # "" | credit.over_daily | credit.over_session
    reserved: int = 0


@dataclass
class _PeriodCounters:
    reserved: int = 0
    spent: int = 0


class CreditGuard:
    """Two-dimension hot counters: global daily tranche + per-user/session cap.

    In-memory implementation of the ADR-0015 reserve-before-turn pattern (the
    Postgres impl is EX0's ``guard_counter`` upsert; the semantics here mirror
    it: reserve an estimate before the turn, reconcile actuals at turn end).
    Single-event-loop asyncio → check-then-reserve is atomic per session; an
    in-progress turn is never cut by the guard (backend-spec §8.4).

    Hooks (spec.md §8): H1 = :meth:`check_start`, H2 = :meth:`check_turn`,
    H3 = the TTS char cap (tts_client), H4 = :meth:`commit_turn`.
    """

    def __init__(
        self,
        settings: VoiceSettings,
        *,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._settings = settings
        # The period key is the IST calendar day, so the guard MUST use wall
        # time. It owns its clock instead of taking the caller's monotonic
        # latency clock (that mix put spend in the 1970 bucket).
        self._clock = clock
        self._global: dict[str, _PeriodCounters] = {}  # period -> counters
        self._per_user: dict[tuple[str, str], _PeriodCounters] = {}  # period, user
        self._per_session: dict[
            tuple[str, str], _PeriodCounters
        ] = {}  # period, session

    def _period(self, now: float | None = None) -> str:
        moment = datetime.fromtimestamp(
            now if now is not None else self._clock(), tz=UTC
        ).astimezone(_IST)
        return moment.strftime("%Y-%m-%d")  # tranche resets 00:00 IST

    def _limits(self, profile: str) -> tuple[int, int, str]:
        if profile == "demo":
            return (
                self._settings.credit_demo_tranche,
                self._settings.credit_demo_session_cap,
                "credit.over_session",
            )
        return (
            self._settings.credit_daily_tranche,
            self._settings.credit_per_user_cap,
            "credit.over_daily",
        )

    def _budget(self, profile: str) -> int:
        """The binding budget for the warn state (per-user cap usually binds).

        The warn threshold must be measured against whatever dimension binds
        a single user — comparing the remaining points to 15 % of the *global*
        tranche would mark every free-trial user permanently "warn" (30-point
        cap < 150-point global warn line).
        """
        tranche, cap, _ = self._limits(profile)
        return min(tranche, cap)

    def remaining(
        self,
        profile: str,
        user_key: str,
        now: float | None = None,
        session_id: str = "",
    ) -> int:
        """Credits left under BOTH dimensions (ADR-0015 reserve semantics).

        ``normal`` caps per USER per day; ``demo`` caps per SESSION (spec.md
        §8) — pass ``session_id`` for demo sessions, else the cap check
        falls back to the user dimension.
        """
        tranche, cap, _ = self._limits(profile)
        period = self._period(now)
        counters = self._global.setdefault(period, _PeriodCounters())
        global_left = max(0, tranche - counters.reserved - counters.spent)
        if profile == "demo" and session_id:
            bucket = self._per_session.setdefault(
                (period, session_id), _PeriodCounters()
            )
        else:
            bucket = self._per_user.setdefault((period, user_key), _PeriodCounters())
        bucket_left = max(0, cap - bucket.reserved - bucket.spent)
        return min(global_left, bucket_left)

    def check_start(
        self,
        profile: str,
        user_key: str,
        now: float | None = None,
        session_id: str = "",
    ) -> GuardDecision:
        """H1 — at session.start: remaining tranche (profile-aware) vs 0."""
        remaining = self.remaining(profile, user_key, now, session_id=session_id)
        if remaining <= 0:
            _, _, reason = self._limits(profile)
            return GuardDecision(False, "exhausted", reason)
        budget = self._budget(profile)
        warn_at = int(budget * self._settings.credit_warn_ratio)
        state = "warn" if remaining <= warn_at else "ok"
        return GuardDecision(True, state, "")

    def check_turn(
        self,
        profile: str,
        user_key: str,
        session_id: str,
        estimate: int,
        now: float | None = None,
    ) -> GuardDecision:
        """H2 — after stt.final, before the brain call: reserve the estimate.

        Atomic reserve against BOTH dimensions (global tranche AND the
        per-user / per-session cap); the reservation is corrected to actuals
        at commit_turn (ADR-0015 reconciliation).
        """
        period = self._period(now)
        tranche, cap, reason = self._limits(profile)
        counters = self._global.setdefault(period, _PeriodCounters())
        if counters.reserved + counters.spent + estimate > tranche:
            return GuardDecision(False, "exhausted", "credit.over_daily")
        if profile == "demo":
            key = (period, session_id)
            store = self._per_session
        else:
            key = (period, user_key)
            store = self._per_user
        user_counters = store.setdefault(key, _PeriodCounters())
        if user_counters.reserved + user_counters.spent + estimate > cap:
            return GuardDecision(False, "exhausted", reason)
        counters.reserved += estimate
        user_counters.reserved += estimate
        remaining_global = max(0, tranche - counters.reserved - counters.spent)
        remaining_user = max(0, cap - user_counters.reserved - user_counters.spent)
        remaining = min(remaining_global, remaining_user)
        budget = self._budget(profile)
        state = (
            "exhausted"
            if remaining == 0
            else (
                "warn"
                if remaining <= int(budget * self._settings.credit_warn_ratio)
                else "ok"
            )
        )
        return GuardDecision(True, state, "", reserved=estimate)

    def commit_turn(
        self,
        profile: str,
        user_key: str,
        session_id: str,
        estimate: int,
        actual: int,
        now: float | None = None,
    ) -> None:
        """H4 — turn end: replace the estimate with the actual spend."""
        period = self._period(now)
        counters = self._global.setdefault(period, _PeriodCounters())
        counters.reserved = max(0, counters.reserved - estimate)
        counters.spent += actual
        if profile == "demo":
            store = self._per_session
            key = (period, session_id)
        else:
            store = self._per_user
            key = (period, user_key)
        user_counters = store.setdefault(key, _PeriodCounters())
        user_counters.reserved = max(0, user_counters.reserved - estimate)
        user_counters.spent += actual


def credit_points(
    settings: VoiceSettings, *, stt_seconds: float = 0.0, tts_chars: int = 0
) -> int:
    """Convert vendor usage into credit POINTS (the guard's single unit).

    1 point == ``credit_stt_seconds_per_point`` seconds of Prisma audio and
    == ``credit_tts_chars_per_point`` Timbre characters (tags included). The
    factors are OQ-06 placeholders; caps, tranches, reservations and actuals
    all speak this unit, so a cap of 30/day is meaningful against a turn.
    """
    stt_seconds_per_point = max(1, settings.credit_stt_seconds_per_point)
    tts_chars_per_point = max(1, settings.credit_tts_chars_per_point)
    stt = math.ceil(stt_seconds / stt_seconds_per_point) if stt_seconds > 0 else 0
    tts = math.ceil(tts_chars / tts_chars_per_point) if tts_chars > 0 else 0
    return stt + tts


def turn_estimate(settings: VoiceSettings, *, typed: bool = False) -> int:
    """The per-turn estimate in credit POINTS (A-07 figures, converted).

    A voice turn reserves ≈ 15 s STT + 600 TTS chars → 3 points with the
    default factors; a typed turn spends no STT → 2 points (it still speaks,
    so its TTS share is reserved and billed — spec.md §8, backend-spec §7.2).
    """
    return credit_points(
        settings,
        stt_seconds=0 if typed else settings.credit_turn_estimate_stt_s,
        tts_chars=settings.credit_turn_estimate_tts_chars,
    )


# --- session state + voice_turn rows (ADR-0002, Appendix B, A-02) --------------


@dataclass
class VoiceSession:
    """One dock session's live state (C5 — lost-on-crash acceptable)."""

    session_id: str
    device_pseudo_id: str
    profile: str = "normal"  # server-asserted (spec.md §11), never client-claimed
    state: str = "idle"
    locale: str = "hi-en"
    text_only: bool = False  # F6 demo downgrade
    # Reply language (voice/language.py): latest Prisma detection > the
    # session.start locale > the product default. ``announced_locale`` is
    # what the dock was last told in ``language.detected`` (emit on change).
    detected_locale: str = ""
    reply_locale: str = ""
    announced_locale: str = ""
    snapshot: dict[str, Any] | None = None  # context.snapshot (latest-wins)
    snapshot_at: float = 0.0
    user_key: str = ""
    turn_idx: int = 0
    last_state_message: dict[str, Any] | None = None
    last_turn_end: dict[str, Any] | None = None
    last_turn_end_at: float = 0.0
    recent_fillers: list[str] = field(default_factory=list)  # no repeat, last 3
    interrupt_times: list[float] = field(default_factory=list)  # F8 storm window


@dataclass
class TurnRecord:
    """One ``voice_turn`` row (spec.md Appendix B; DDL belongs to the DB spec).

    Schema law (ADR-0008 + A-02): there is NO audio field on this record and
    never will be — ``testing/voice/test_session.py`` asserts it structurally.
    Transcripts live here and in structured logs never (logging-api.md §6).
    """

    id: str
    session_id: str
    turn_idx: int
    role: str  # student | tutor | event
    text: str
    lang: str = ""
    stt_confidence: float | None = None
    block_ids_ref: tuple[str, ...] = ()
    latency_ms: dict[str, int | None] = field(default_factory=dict)
    usage_json: dict[str, Any] = field(default_factory=dict)
    credit_cost: float = 0.0
    profile: str = "normal"
    created_at: float = field(default_factory=time.time)


class TurnRepository(Protocol):
    """The store seam the core backend implements over Postgres (A-02)."""

    async def append_turn(self, record: TurnRecord) -> None: ...

    async def recent_turns(
        self, session_id: str, limit: int = 6
    ) -> list[TurnRecord]: ...

    async def purge_expired(self, now: float | None = None) -> int: ...


class InMemoryTurnRepository:
    """Memory turn rows with the A-02 7-day hard-delete TTL (default + tests)."""

    TTL_DAYS = 7

    def __init__(self, *, clock: Callable[[], float] = time.time) -> None:
        self._rows: list[TurnRecord] = []
        self._clock = clock

    async def append_turn(self, record: TurnRecord) -> None:
        self._rows.append(record)

    async def recent_turns(self, session_id: str, limit: int = 6) -> list[TurnRecord]:
        rows = [r for r in self._rows if r.session_id == session_id]
        return rows[-limit:]

    async def purge_expired(self, now: float | None = None) -> int:
        """``voice.purge_expired`` — the daily TTL purge hook (A-02)."""
        cutoff = (now or self._clock()) - self.TTL_DAYS * 86400
        keep = [r for r in self._rows if r.created_at >= cutoff]
        deleted = len(self._rows) - len(keep)
        self._rows = keep
        return deleted


class SessionStore:
    """In-memory session registry (ADR-0002 decision U1) + concurrency caps.

    Max 1 concurrent channel per session; cluster cap 10 concurrent (A-07,
    NFR-13) enforced process-globally at the P0 1-replica scale. The core
    backend swaps in the real store via ``mount_voice(sessions=...)``.
    """

    MAX_SESSIONS = 1000  # memory bound; ADR-0002: lost-on-crash acceptable

    def __init__(
        self, settings: VoiceSettings, *, clock: Callable[[], float] = time.time
    ) -> None:
        self._settings = settings
        self._clock = clock
        self._sessions: dict[str, VoiceSession] = {}
        self._open_channels: set[str] = set()

    def get(self, session_id: str) -> VoiceSession | None:
        return self._sessions.get(session_id)

    def create(
        self, identity: SessionIdentity, profile: str, locale: str
    ) -> VoiceSession:
        session = VoiceSession(
            session_id=identity.session_id,
            device_pseudo_id=identity.device_pseudo_id,
            profile=profile,
            locale=locale,
            user_key=identity.device_pseudo_id,
        )
        while len(self._sessions) >= self.MAX_SESSIONS:
            # evict the oldest session row (C5 state only; durable rows live
            # in Postgres via the core backend's store adapter)
            oldest = next(iter(self._sessions))
            if oldest in self._open_channels:
                break  # never evict a live channel
            self._sessions.pop(oldest)
        self._sessions[session.session_id] = session
        return session

    def acquire_channel(self, session_id: str) -> bool:
        """Max 1 concurrent channel per session + the global ceiling."""
        if session_id in self._open_channels:
            return False
        if len(self._open_channels) >= self._settings.ws_max_concurrent_sessions:
            return False
        self._open_channels.add(session_id)
        return True

    def release_channel(self, session_id: str) -> None:
        self._open_channels.discard(session_id)

    def replay_window_alive(
        self, session: VoiceSession, now: float | None = None
    ) -> bool:
        """ADR-0002: 60 s final-message replay window held in pod memory."""
        moment = now or self._clock()
        return (
            bool(session.last_turn_end)
            and moment - session.last_turn_end_at <= self._settings.resume_window_s
        )

    def count(self) -> int:
        return len(self._open_channels)


def new_turn_id() -> str:
    return str(uuid.uuid4())
