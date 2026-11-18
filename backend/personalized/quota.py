"""Free-tier quota counters (C25, data-and-api.md §2.6; D-PL-01 recommendations).

Hot per-(IST-day, scope, scope_key) counters in `personalized_quota`, with the
race-free reserve/actualize/release discipline of `guard/service.py` (ADR-0015
transactional guard, copied per workstreams.md §2) and one deliberate
difference: the **user row and the global row are updated in the same
transaction**, so the sum can never exceed either cap (§2.6).

Caps are config (`ZIVON_PERSONALIZED_*`), never a table — a founder change is
an env change, not a migration. The numbers are the D-PL-01 recommendations
(open decision): 40 turns/user/day, 2 concurrent turns/user, 5 sessions/user/
day, 12 artifact builds/user/day, 1,500 turns/day globally, 300 artifact
builds/day globally; warn at 15 % remaining; reset at 00:00 IST.

Atomicity note (skills/zivon-backend-engineering-skills §3): the guard lives
in the SQL predicate (`WHERE turns_used + turns_reserved < cap`), never in a
check-then-act app branch — the DBAPI cursor's rowcount decides. SQLite runs
under `BEGIN IMMEDIATE` (engine-serialized); the single-replica Postgres
deployment of the prototype serializes concurrent writers per row.
"""

from __future__ import annotations

import datetime
import zoneinfo
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

from ..logging_shim import ErrorClass, log_event

if TYPE_CHECKING:
    from db.engine import DatabaseEngine

_IST: Final[zoneinfo.ZoneInfo] = zoneinfo.ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class QuotaCaps:
    """D-PL-01 recommendations; overridden from `ZIVON_PERSONALIZED_*` config."""

    turns_per_user_per_day: int = 40
    turn_concurrency: int = 2
    sessions_per_user_per_day: int = 5
    artifacts_per_user_per_day: int = 12
    turns_global_per_day: int = 1500
    artifacts_global_per_day: int = 300
    warn_remaining_ratio: float = 0.15


@dataclass(frozen=True)
class QuotaDecision:
    """Result of one reserve attempt (`reason` empty when allowed)."""

    allowed: bool
    reason: str
    period: str
    user_state: str
    global_state: str
    turns_remaining: int
    artifacts_remaining: int


def ist_period(now_dt: datetime.datetime | None = None) -> str:
    """The IST day key (`YYYY-MM-DD`) a quota period is scoped to (§2.6)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    return now.astimezone(_IST).strftime("%Y-%m-%d")


def ist_reset_at(now_dt: datetime.datetime | None = None) -> str:
    """Next 00:00 IST boundary as a UTC ISO string (the usage endpoint's reset_at)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    ist_now = now.astimezone(_IST)
    next_midnight = (ist_now + datetime.timedelta(days=1)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return (
        next_midnight.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"
    )


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _day_start_utc_iso(now_dt: datetime.datetime | None = None) -> str:
    """UTC ISO instant of 00:00 IST today (created_at >= compare for day counts)."""
    now = now_dt or datetime.datetime.now(datetime.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=datetime.UTC)
    ist_now = now.astimezone(_IST)
    midnight = ist_now.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def _compute_state(used: int, reserved: int, cap: int, warn_ratio: float) -> str:
    remaining = cap - used - reserved
    if remaining <= 0:
        return "exhausted"
    if cap > 0 and remaining <= cap * warn_ratio:
        return "warn"
    return "ok"


class QuotaService:
    """Atomic reserve/actualize/release for the user + global quota rows (§2.6)."""

    def __init__(self, db: DatabaseEngine, caps: QuotaCaps | None = None) -> None:
        self.db = db
        self.caps = caps or QuotaCaps()

    # --- row plumbing -------------------------------------------------------

    def _ensure_rows_tx(
        self, tx: Any, period: str, user_id: str
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        now = _utc_now_iso()
        tx.execute(
            """
            INSERT INTO personalized_quota (period, scope, scope_key, updated_at)
            VALUES (?, 'user', ?, ?)
            ON CONFLICT (period, scope, scope_key) DO NOTHING
            """,
            (period, user_id, now),
        )
        tx.execute(
            """
            INSERT INTO personalized_quota (period, scope, scope_key, updated_at)
            VALUES (?, 'global', 'global', ?)
            ON CONFLICT (period, scope, scope_key) DO NOTHING
            """,
            (period, now),
        )
        user_row = tx.fetchone(
            """
            SELECT period, scope, scope_key, turns_used, turns_reserved,
                   artifact_used, artifact_reserved, state
            FROM personalized_quota WHERE period = ? AND scope = 'user' AND scope_key = ?
            """,
            (period, user_id),
        )
        global_row = tx.fetchone(
            """
            SELECT period, scope, scope_key, turns_used, turns_reserved,
                   artifact_used, artifact_reserved, state
            FROM personalized_quota
            WHERE period = ? AND scope = 'global' AND scope_key = 'global'
            """,
            (period,),
        )
        assert user_row is not None and global_row is not None
        return user_row, global_row

    def _user_row(self, user_id: str, period: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            """
            SELECT period, scope, scope_key, turns_used, turns_reserved,
                   artifact_used, artifact_reserved, state
            FROM personalized_quota
            WHERE period = ? AND scope = 'user' AND scope_key = ?
            """,
            (period, user_id),
        )

    def _global_row(self, period: str) -> dict[str, Any] | None:
        return self.db.fetchone(
            """
            SELECT period, scope, scope_key, turns_used, turns_reserved,
                   artifact_used, artifact_reserved, state
            FROM personalized_quota
            WHERE period = ? AND scope = 'global' AND scope_key = 'global'
            """,
            (period,),
        )

    @staticmethod
    def _rowcount(cursor: Any) -> int:
        return int(getattr(cursor, "rowcount", 0) or 0)

    def _blocked_decision(
        self,
        period: str,
        caps: QuotaCaps,
        reason: str,
        user_row: dict[str, Any] | None,
        global_row: dict[str, Any],
    ) -> QuotaDecision:
        """Build the refusal decision. The `personalized.quota.blocked` event
        is logged by the CALLER after the transaction closes: the event's DB
        sink opens its own engine transaction, and nesting that inside the
        quota transaction breaks the atomic pair (found by the PL2 turn
        tests). Counts/enums only — never student data."""
        user_used = int(user_row["turns_used"]) if user_row else 0
        user_reserved = int(user_row["turns_reserved"]) if user_row else 0
        user_state = (
            "exhausted"
            if reason.endswith("turn_cap") and reason.startswith("user")
            else _compute_state(
                user_used,
                user_reserved,
                caps.turns_per_user_per_day,
                caps.warn_remaining_ratio,
            )
        )
        return QuotaDecision(
            allowed=False,
            reason=reason,
            period=period,
            user_state=user_state,
            global_state=str(global_row["state"]),
            turns_remaining=max(
                0, caps.turns_per_user_per_day - user_used - user_reserved
            ),
            artifacts_remaining=max(
                0,
                caps.artifacts_per_user_per_day
                - (int(user_row["artifact_used"]) if user_row else 0),
            ),
        )

    def _allowed_decision(
        self,
        period: str,
        caps: QuotaCaps,
        user_row: dict[str, Any],
        global_row: dict[str, Any],
        user_state: str,
    ) -> QuotaDecision:
        return QuotaDecision(
            allowed=True,
            reason="",
            period=period,
            user_state=user_state,
            global_state=str(global_row["state"]),
            turns_remaining=max(
                0,
                caps.turns_per_user_per_day
                - int(user_row["turns_used"])
                - int(user_row["turns_reserved"]),
            ),
            artifacts_remaining=max(
                0,
                caps.artifacts_per_user_per_day
                - int(user_row["artifact_used"])
                - int(user_row["artifact_reserved"]),
            ),
        )

    # --- turns --------------------------------------------------------------

    def reserve_turn(
        self,
        user_id: str,
        *,
        now_dt: datetime.datetime | None = None,
    ) -> QuotaDecision:
        """Admit at most one in-flight turn: reserve on user AND global rows.

        Admitted only if `turns_used + turns_reserved < cap` and
        `turns_reserved < concurrency` on the user row, and
        `turns_used + turns_reserved < global cap` on the global row — all in
        the one transaction that increments both `turns_reserved` counters
        (§2.6: both or neither; a failed global update raises so the engine
        transaction rolls the user-side increment back with it).
        """
        caps = self.caps
        period = ist_period(now_dt)
        now = _utc_now_iso()
        blocked: QuotaDecision | None = None
        decision: QuotaDecision | None = None
        with self.db.transaction() as tx:
            user_row, global_row = self._ensure_rows_tx(tx, period, user_id)
            user_used = int(user_row["turns_used"])
            user_reserved = int(user_row["turns_reserved"])
            global_used = int(global_row["turns_used"])
            global_reserved = int(global_row["turns_reserved"])

            if user_used + user_reserved >= caps.turns_per_user_per_day:
                self._flip_state_tx(tx, period, "user", user_id, "exhausted", now)
                blocked = self._blocked_decision(
                    period, caps, "user_turn_cap", user_row, global_row
                )
            elif user_reserved >= caps.turn_concurrency:
                blocked = self._blocked_decision(
                    period, caps, "user_concurrency", user_row, global_row
                )
            elif global_used + global_reserved >= caps.turns_global_per_day:
                self._flip_state_tx(tx, period, "global", "global", "exhausted", now)
                blocked = self._blocked_decision(
                    period, caps, "global_turn_cap", user_row, global_row
                )
            else:
                # The predicate IS the guard: a concurrent caller can never
                # push `turns_reserved` past either cap (rowcount 0 ⇒ denied).
                cur = tx.execute(
                    """
                    UPDATE personalized_quota
                    SET turns_reserved = turns_reserved + 1,
                        state = CASE
                            WHEN (? - turns_used - turns_reserved) <= CAST(? * ? AS INTEGER)
                            THEN 'warn' ELSE 'ok' END,
                        updated_at = ?
                    WHERE period = ? AND scope = 'user' AND scope_key = ?
                      AND turns_used + turns_reserved < ?
                      AND turns_reserved < ?
                    """,
                    (
                        caps.turns_per_user_per_day,
                        caps.turns_per_user_per_day,
                        caps.warn_remaining_ratio,
                        now,
                        period,
                        user_id,
                        caps.turns_per_user_per_day,
                        caps.turn_concurrency,
                    ),
                )
                if not self._rowcount(cur):
                    blocked = self._blocked_decision(
                        period, caps, "user_turn_cap", user_row, global_row
                    )
                else:
                    cur = tx.execute(
                        """
                        UPDATE personalized_quota
                        SET turns_reserved = turns_reserved + 1, updated_at = ?
                        WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                          AND turns_used + turns_reserved < ?
                        """,
                        (now, period, caps.turns_global_per_day),
                    )
                    if not self._rowcount(cur):
                        # Roll BOTH reservations back: the raise unwinds
                        # `engine.transaction`, undoing the user-side update.
                        raise _GlobalReservationLost()
                    updated_user = tx.fetchone(
                        """
                        SELECT period, scope, scope_key, turns_used, turns_reserved,
                               artifact_used, artifact_reserved, state
                        FROM personalized_quota WHERE period = ? AND scope = 'user' AND scope_key = ?
                        """,
                        (period, user_id),
                    )
                    assert updated_user is not None
                    decision = self._allowed_decision(
                        period,
                        caps,
                        updated_user,
                        global_row,
                        str(updated_user["state"]),
                    )
        if blocked is not None:
            self._log_blocked(blocked, "turn", period)
            return blocked
        assert decision is not None
        return decision

    def _log_blocked(self, decision: QuotaDecision, counter: str, period: str) -> None:
        """The blocked event, emitted AFTER the quota transaction closed."""
        log_event(
            "personalized.quota.blocked",
            {
                "scope": decision.reason.split("_", 1)[0],
                "counter": counter,
                "reason": decision.reason,
                "period": period,
            },
            error_class=ErrorClass.QUOTA_ERROR,
        )

    def commit_turn(
        self,
        user_id: str,
        *,
        period: str | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> None:
        """`turn.done`: the reservation actualizes into `turns_used` (both rows)."""
        caps = self.caps
        eff = period or ist_period(now_dt)
        now = _utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                UPDATE personalized_quota
                SET turns_used = turns_used + 1,
                    turns_reserved = CASE WHEN turns_reserved > 0
                        THEN turns_reserved - 1 ELSE 0 END,
                    state = CASE
                        WHEN (? - turns_used - 1) <= 0 THEN 'exhausted'
                        WHEN (? - turns_used - 1) <= CAST(? * ? AS INTEGER) THEN 'warn'
                        ELSE 'ok' END,
                    updated_at = ?
                WHERE period = ? AND scope = 'user' AND scope_key = ?
                """,
                (
                    caps.turns_per_user_per_day,
                    caps.turns_per_user_per_day,
                    caps.turns_per_user_per_day,
                    caps.warn_remaining_ratio,
                    now,
                    eff,
                    user_id,
                ),
            )
            tx.execute(
                """
                UPDATE personalized_quota
                SET turns_used = turns_used + 1,
                    turns_reserved = CASE WHEN turns_reserved > 0
                        THEN turns_reserved - 1 ELSE 0 END,
                    state = CASE
                        WHEN (? - turns_used - 1) <= 0 THEN 'exhausted'
                        WHEN (? - turns_used - 1) <= CAST(? * ? AS INTEGER) THEN 'warn'
                        ELSE 'ok' END,
                    updated_at = ?
                WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                """,
                (
                    caps.turns_global_per_day,
                    caps.turns_global_per_day,
                    caps.turns_global_per_day,
                    caps.warn_remaining_ratio,
                    now,
                    eff,
                ),
            )

    def release_turn(
        self,
        user_id: str,
        *,
        period: str | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> None:
        """`turn.error`: release the reservation (floor 0, recompute state)."""
        caps = self.caps
        eff = period or ist_period(now_dt)
        now = _utc_now_iso()
        with self.db.transaction() as tx:
            tx.execute(
                """
                UPDATE personalized_quota
                SET turns_reserved = CASE WHEN turns_reserved > 0
                        THEN turns_reserved - 1 ELSE 0 END,
                    state = CASE
                        WHEN (? - turns_used) <= 0 THEN 'exhausted'
                        WHEN (? - turns_used) <= CAST(? * ? AS INTEGER) THEN 'warn'
                        ELSE 'ok' END,
                    updated_at = ?
                WHERE period = ? AND scope = 'user' AND scope_key = ?
                """,
                (
                    caps.turns_per_user_per_day,
                    caps.turns_per_user_per_day,
                    caps.turns_per_user_per_day,
                    caps.warn_remaining_ratio,
                    now,
                    eff,
                    user_id,
                ),
            )
            tx.execute(
                """
                UPDATE personalized_quota
                SET turns_reserved = CASE WHEN turns_reserved > 0
                        THEN turns_reserved - 1 ELSE 0 END,
                    updated_at = ?
                WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                """,
                (now, eff),
            )

    # --- artifacts (C24 / D-PL-01: 12/day user, 300/day global) -------------

    def reserve_artifact(
        self,
        user_id: str,
        *,
        now_dt: datetime.datetime | None = None,
    ) -> QuotaDecision:
        """Reserve one artifact build on both rows (same one-transaction pair)."""
        caps = self.caps
        period = ist_period(now_dt)
        now = _utc_now_iso()
        blocked_artifact: QuotaDecision | None = None
        with self.db.transaction() as tx:
            user_row, global_row = self._ensure_rows_tx(tx, period, user_id)
            if (
                int(user_row["artifact_used"]) + int(user_row["artifact_reserved"])
                >= caps.artifacts_per_user_per_day
            ):
                self._flip_state_tx(tx, period, "user", user_id, "exhausted", now)
                blocked_artifact = QuotaDecision(
                    allowed=False,
                    reason="user_artifact_cap",
                    period=period,
                    user_state="exhausted",
                    global_state=str(global_row["state"]),
                    turns_remaining=0,
                    artifacts_remaining=0,
                )
            elif (
                int(global_row["artifact_used"]) + int(global_row["artifact_reserved"])
                >= caps.artifacts_global_per_day
            ):
                self._flip_state_tx(tx, period, "global", "global", "exhausted", now)
                blocked_artifact = QuotaDecision(
                    allowed=False,
                    reason="global_artifact_cap",
                    period=period,
                    user_state=str(user_row["state"]),
                    global_state="exhausted",
                    turns_remaining=0,
                    artifacts_remaining=0,
                )
        if blocked_artifact is not None:
            self._log_blocked(blocked_artifact, "artifact", period)
            return blocked_artifact
        decision_artifact: QuotaDecision | None = None
        with self.db.transaction() as tx:
            user_row, global_row = self._ensure_rows_tx(tx, period, user_id)
            cur = tx.execute(
                """
                UPDATE personalized_quota
                SET artifact_reserved = artifact_reserved + 1, updated_at = ?
                WHERE period = ? AND scope = 'user' AND scope_key = ?
                  AND artifact_used + artifact_reserved < ?
                """,
                (now, period, user_id, caps.artifacts_per_user_per_day),
            )
            if not self._rowcount(cur):
                decision_artifact = QuotaDecision(
                    allowed=False,
                    reason="user_artifact_cap",
                    period=period,
                    user_state=str(user_row["state"]),
                    global_state=str(global_row["state"]),
                    turns_remaining=0,
                    artifacts_remaining=0,
                )
            else:
                cur = tx.execute(
                    """
                    UPDATE personalized_quota
                    SET artifact_reserved = artifact_reserved + 1, updated_at = ?
                    WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                      AND artifact_used + artifact_reserved < ?
                    """,
                    (now, period, caps.artifacts_global_per_day),
                )
                if not self._rowcount(cur):
                    raise _GlobalReservationLost()
                updated_user = tx.fetchone(
                    """
                    SELECT period, scope, scope_key, turns_used, turns_reserved,
                           artifact_used, artifact_reserved, state
                    FROM personalized_quota WHERE period = ? AND scope = 'user' AND scope_key = ?
                    """,
                    (period, user_id),
                )
                assert updated_user is not None
                decision_artifact = QuotaDecision(
                    allowed=True,
                    reason="",
                    period=period,
                    user_state=str(updated_user["state"]),
                    global_state=str(global_row["state"]),
                    turns_remaining=max(
                        0,
                        caps.turns_per_user_per_day
                        - int(updated_user["turns_used"])
                        - int(updated_user["turns_reserved"]),
                    ),
                    artifacts_remaining=max(
                        0,
                        caps.artifacts_per_user_per_day
                        - int(updated_user["artifact_used"])
                        - int(updated_user["artifact_reserved"]),
                    ),
                )
        assert decision_artifact is not None
        return decision_artifact

    def commit_artifact(
        self,
        user_id: str,
        *,
        period: str | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> None:
        """The artifact build succeeded: actualize the reservation (both rows)."""
        eff = period or ist_period(now_dt)
        now = _utc_now_iso()
        with self.db.transaction() as tx:
            for scope, key, cap in (
                ("user", user_id, self.caps.artifacts_per_user_per_day),
                ("global", "global", self.caps.artifacts_global_per_day),
            ):
                tx.execute(
                    """
                    UPDATE personalized_quota
                    SET artifact_used = artifact_used + 1,
                        artifact_reserved = CASE WHEN artifact_reserved > 0
                            THEN artifact_reserved - 1 ELSE 0 END,
                        state = CASE WHEN (? - artifact_used - 1) <= 0
                            THEN 'exhausted' ELSE state END,
                        updated_at = ?
                    WHERE period = ? AND scope = ? AND scope_key = ?
                    """,
                    (cap, now, eff, scope, key),
                )

    def release_artifact(
        self,
        user_id: str,
        *,
        period: str | None = None,
        now_dt: datetime.datetime | None = None,
    ) -> None:
        """The build failed before any model work: release the reservation."""
        eff = period or ist_period(now_dt)
        now = _utc_now_iso()
        with self.db.transaction() as tx:
            for scope, key in (("user", user_id), ("global", "global")):
                tx.execute(
                    """
                    UPDATE personalized_quota
                    SET artifact_reserved = CASE WHEN artifact_reserved > 0
                        THEN artifact_reserved - 1 ELSE 0 END,
                        updated_at = ?
                    WHERE period = ? AND scope = ? AND scope_key = ?
                    """,
                    (now, eff, scope, key),
                )

    # --- day-scoped session count (D-PL-01: 5 sessions/user/day) ------------

    def sessions_created_today(
        self, user_id: str, *, now_dt: datetime.datetime | None = None
    ) -> int:
        """Count today's (IST) personalized sessions for the user."""
        day_start = _day_start_utc_iso(now_dt)
        row = self.db.fetchone(
            "SELECT COUNT(*) AS cnt FROM personalized_session "
            "WHERE user_id = ? AND created_at >= ?",
            (user_id, day_start),
        )
        return int(row["cnt"]) if row else 0

    # --- usage readout (API-PL-15) -------------------------------------------

    def get_usage(self, user_id: str, *, enabled: bool = True) -> dict[str, Any]:
        caps = self.caps
        period = ist_period()
        user = self._user_row(user_id, period)
        glob = self._global_row(period)
        turns_used = int(user["turns_used"]) if user else 0
        artifact_used = int(user["artifact_used"]) if user else 0
        return {
            "turns": {
                "used": turns_used,
                "cap": caps.turns_per_user_per_day,
                "remaining": max(0, caps.turns_per_user_per_day - turns_used),
                "state": str(user["state"]) if user else "ok",
            },
            "artifacts": {
                "used": artifact_used,
                "cap": caps.artifacts_per_user_per_day,
                "remaining": max(0, caps.artifacts_per_user_per_day - artifact_used),
            },
            "global": {"state": str(glob["state"]) if glob else "ok"},
            "reset_at": ist_reset_at(),
            "enabled": enabled,
        }

    # --- internals ------------------------------------------------------------

    def _flip_state_tx(
        self, tx: Any, period: str, scope: str, key: str, state: str, now: str
    ) -> None:
        tx.execute(
            """
            UPDATE personalized_quota SET state = ?, updated_at = ?
            WHERE period = ? AND scope = ? AND scope_key = ?
            """,
            (state, now, period, scope, key),
        )


class _GlobalReservationLost(RuntimeError):
    """Internal: the global row moved under us — the raise rolls back the
    transaction, so the pair commits together or not at all (§2.6)."""
