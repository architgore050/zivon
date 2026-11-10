"""Transactional two-dimension credit guard service (ADR-0015, NEED-009).

Enforces:
- Global daily tranche: 1,000 credits/day (`normal` and `demo`)
- Per-device daily cap: 30 credits/day (`normal`), 100 credits/day (`demo`)
- Warn threshold: 15% of daily tranche remaining (`A-06`)
- Hard total programme ceiling: 10,000 total credits with 40% (`4,000`) demo
  reserve (`normal` ceiling = 6,000; `demo` ceiling = 10,000) (`A-05`)
- Atomic SQL check-and-decrement inside a single transaction (zero TOCTOU race)
- State push callbacks for open WebSocket voice sessions (`<= 5 s`, NFR-14)
"""

from __future__ import annotations

import datetime
from collections.abc import Callable
from typing import Any

from backend.logging_shim import ErrorClass, Severity, log_event
from db.engine import DatabaseEngine
from db.uuid7 import uuid7_str

from .models import GuardDecision, GuardProfileConfig, GuardStatus


def _utc_now_iso() -> str:
    now = datetime.datetime.now(datetime.UTC)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _today_period() -> str:
    return datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")


def _compute_counter_state(
    used: float,
    cap: float,
    warn_pct: float,
    *,
    mode: str,
    ceiling_exhausted: bool = False,
) -> str:
    """Compute counter state (`ok` | `warn` | `exhausted` | `reserved_mode`)."""
    if ceiling_exhausted or cap <= 0 or used >= cap:
        return "exhausted"
    remaining = max(0.0, cap - used)
    remaining_pct = (remaining / cap) * 100.0
    if remaining_pct <= warn_pct:
        return "warn"
    if mode == "demo":
        return "reserved_mode"
    return "ok"


def _combine_states(global_state: str, device_state: str) -> str:
    if global_state == "exhausted" or device_state == "exhausted":
        return "exhausted"
    if global_state == "warn" or device_state == "warn":
        return "warn"
    if global_state == "reserved_mode" or device_state == "reserved_mode":
        return "reserved_mode"
    return "ok"


class CreditGuard:
    """Concurrency-safe credit guard backed by `guard_counter` and `guard_profile`."""

    def __init__(self, db: DatabaseEngine) -> None:
        self.db = db
        self._listeners: list[Callable[[GuardStatus], None]] = []

    def register_listener(self, callback: Callable[[GuardStatus], None]) -> None:
        """Register a listener notified whenever guard state or profile changes."""
        self._listeners.append(callback)

    def _notify_listeners(self, status: GuardStatus) -> None:
        for cb in list(self._listeners):
            try:
                cb(status)
            except Exception:  # noqa: BLE001, S112
                continue

    def _load_profile_tx(self, tx: Any) -> GuardProfileConfig:
        row = tx.fetchone("SELECT * FROM guard_profile WHERE id = 1")
        if row is None:
            return GuardProfileConfig()
        return GuardProfileConfig(
            mode=str(row.get("mode", "normal")),
            global_tranche=float(row.get("global_tranche", 1000.0)),
            per_user_cap=float(row.get("per_user_cap", 30.0)),
            demo_global_tranche=float(row.get("demo_global_tranche", 1000.0)),
            demo_per_user_cap=float(row.get("demo_per_user_cap", 100.0)),
            warn_threshold_pct=float(row.get("warn_threshold_pct", 15.0)),
            total_budget_credits=float(row.get("total_budget_credits", 10000.0)),
            demo_reserve_pct=float(row.get("demo_reserve_pct", 40.0)),
        )

    def _ensure_counter_row_tx(
        self, tx: Any, period: str, scope: str, scope_key: str, mode: str
    ) -> dict[str, Any]:
        initial_state = "reserved_mode" if mode == "demo" else "ok"
        tx.execute(
            """
            INSERT INTO guard_counter (counter_id, period, scope, scope_key, used_credits, state, updated_at)
            VALUES (?, ?, ?, ?, 0, ?, ?)
            ON CONFLICT (period, scope, scope_key) DO NOTHING
            """,
            (uuid7_str(), period, scope, scope_key, initial_state, _utc_now_iso()),
        )
        row = tx.fetchone(
            """
            SELECT counter_id, period, scope, scope_key, used_credits, state
            FROM guard_counter
            WHERE period = ? AND scope = ? AND scope_key = ?
            """,
            (period, scope, scope_key),
        )
        assert row is not None
        return row

    def _total_programme_used_tx(self, tx: Any, *, mode: str) -> float:
        """Compute total programme credits spent across periods."""
        global_rows = tx.fetchone(
            "SELECT COALESCE(SUM(used_credits), 0) AS total FROM guard_counter WHERE scope = 'global'"
        )
        counter_total = float(global_rows["total"]) if global_rows else 0.0
        if mode == "normal":
            ledger_rows = tx.fetchone(
                "SELECT COALESCE(SUM(COALESCE(cost_credits, 0)), 0) AS total FROM credit_ledger WHERE bucket = 'daily'"
            )
        else:
            ledger_rows = tx.fetchone(
                "SELECT COALESCE(SUM(COALESCE(cost_credits, 0)), 0) AS total FROM credit_ledger"
            )
        ledger_total = float(ledger_rows["total"]) if ledger_rows else 0.0
        return max(counter_total, ledger_total)

    def get_status(
        self,
        *,
        device_pseudo_id: str | None = None,
        period: str | None = None,
    ) -> GuardStatus:
        """Return current guard status for global tranche and optional device."""
        eff_period = period or _today_period()
        with self.db.transaction() as tx:
            profile = self._load_profile_tx(tx)
            g_row = self._ensure_counter_row_tx(
                tx, eff_period, "global", "global", profile.mode
            )
            g_used = float(g_row["used_credits"])
            g_cap = profile.active_global_cap

            total_used = self._total_programme_used_tx(tx, mode=profile.mode)
            total_ceiling = (
                profile.total_budget_credits
                if profile.mode == "demo"
                else profile.normal_ceiling_credits
            )
            ceiling_exhausted = total_used >= total_ceiling

            g_state = _compute_counter_state(
                g_used,
                g_cap,
                profile.warn_threshold_pct,
                mode=profile.mode,
                ceiling_exhausted=ceiling_exhausted,
            )

            d_used = 0.0
            d_cap = profile.active_device_cap
            d_state = "reserved_mode" if profile.mode == "demo" else "ok"
            if device_pseudo_id:
                d_row = self._ensure_counter_row_tx(
                    tx, eff_period, "device", device_pseudo_id, profile.mode
                )
                d_used = float(d_row["used_credits"])
                d_state = _compute_counter_state(
                    d_used,
                    d_cap,
                    profile.warn_threshold_pct,
                    mode=profile.mode,
                    ceiling_exhausted=ceiling_exhausted,
                )

            eff_state = _combine_states(g_state, d_state)
            ceiling_rem = max(0.0, total_ceiling - total_used)
            g_rem = min(max(0.0, g_cap - g_used), ceiling_rem)
            d_rem = min(max(0.0, d_cap - d_used), g_rem)

            return GuardStatus(
                period=eff_period,
                mode=profile.mode,
                global_state=g_state,
                device_state=d_state,
                effective_state=eff_state,
                global_used=g_used,
                global_cap=g_cap,
                global_remaining=g_rem,
                device_used=d_used,
                device_cap=d_cap,
                device_remaining=d_rem,
                total_programme_used=total_used,
                total_programme_ceiling=total_ceiling,
                warn_threshold_pct=profile.warn_threshold_pct,
            )

    def check_and_reserve(
        self,
        device_pseudo_id: str,
        cost_credits: float,
        *,
        session_id: str | None = None,
        period: str | None = None,
    ) -> GuardDecision:
        """Atomically check and decrement both global and device budgets (ADR-0015).

        Executes inside one serialized DB transaction using conditional SQL
        predicates `WHERE (used_credits + :cost) <= :cap` so concurrent callers
        can never overspend either dimension.
        """
        if cost_credits < 0:
            raise ValueError("cost_credits must be >= 0")

        eff_period = period or _today_period()
        now = _utc_now_iso()
        prev_eff_state = "ok"

        with self.db.transaction() as tx:
            profile = self._load_profile_tx(tx)
            g_row = self._ensure_counter_row_tx(
                tx, eff_period, "global", "global", profile.mode
            )
            d_row = self._ensure_counter_row_tx(
                tx, eff_period, "device", device_pseudo_id, profile.mode
            )
            prev_eff_state = _combine_states(str(g_row["state"]), str(d_row["state"]))

            g_cap = profile.active_global_cap
            d_cap = profile.active_device_cap
            total_used = self._total_programme_used_tx(tx, mode=profile.mode)
            total_ceiling = (
                profile.total_budget_credits
                if profile.mode == "demo"
                else profile.normal_ceiling_credits
            )

            # 1. Check hard total-remaining ceiling (A-05)
            if total_used + cost_credits > total_ceiling:
                tx.execute(
                    "UPDATE guard_counter SET state = 'exhausted', updated_at = ? WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
                    (now, eff_period),
                )
                status = self._build_status_from_rows(
                    eff_period,
                    profile,
                    float(g_row["used_credits"]),
                    float(d_row["used_credits"]),
                    total_used,
                    total_ceiling,
                    force_global_exhausted=True,
                )
                decision = GuardDecision(
                    allowed=False,
                    reason="total_ceiling_exhausted",
                    status=status,
                    reserved_credits=0.0,
                )
            else:
                # 2. Atomic conditional update on global counter
                cur_g = tx.execute(
                    """
                    UPDATE guard_counter
                    SET used_credits = used_credits + ?, updated_at = ?
                    WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                      AND (used_credits + ?) <= ?
                    """,
                    (cost_credits, now, eff_period, cost_credits, g_cap),
                )
                if cur_g.rowcount == 0:
                    tx.execute(
                        "UPDATE guard_counter SET state = 'exhausted', updated_at = ? WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
                        (now, eff_period),
                    )
                    status = self._build_status_from_rows(
                        eff_period,
                        profile,
                        float(g_row["used_credits"]),
                        float(d_row["used_credits"]),
                        total_used,
                        total_ceiling,
                        force_global_exhausted=True,
                    )
                    decision = GuardDecision(
                        allowed=False,
                        reason="global_tranche_exhausted",
                        status=status,
                        reserved_credits=0.0,
                    )
                else:
                    # 3. Atomic conditional update on per-device counter
                    cur_d = tx.execute(
                        """
                        UPDATE guard_counter
                        SET used_credits = used_credits + ?, updated_at = ?
                        WHERE period = ? AND scope = 'device' AND scope_key = ?
                          AND (used_credits + ?) <= ?
                        """,
                        (
                            cost_credits,
                            now,
                            eff_period,
                            device_pseudo_id,
                            cost_credits,
                            d_cap,
                        ),
                    )
                    if cur_d.rowcount == 0:
                        # Roll back the global increment within the same transaction
                        tx.execute(
                            """
                            UPDATE guard_counter
                            SET used_credits = used_credits - ?, updated_at = ?
                            WHERE period = ? AND scope = 'global' AND scope_key = 'global'
                            """,
                            (cost_credits, now, eff_period),
                        )
                        tx.execute(
                            "UPDATE guard_counter SET state = 'exhausted', updated_at = ? WHERE period = ? AND scope = 'device' AND scope_key = ?",
                            (now, eff_period, device_pseudo_id),
                        )
                        status = self._build_status_from_rows(
                            eff_period,
                            profile,
                            float(g_row["used_credits"]),
                            float(d_row["used_credits"]),
                            total_used,
                            total_ceiling,
                            force_device_exhausted=True,
                        )
                        decision = GuardDecision(
                            allowed=False,
                            reason="device_cap_exhausted",
                            status=status,
                            reserved_credits=0.0,
                        )
                    else:
                        new_g_used = float(g_row["used_credits"]) + cost_credits
                        new_d_used = float(d_row["used_credits"]) + cost_credits
                        new_total_used = total_used + cost_credits
                        g_state = _compute_counter_state(
                            new_g_used,
                            g_cap,
                            profile.warn_threshold_pct,
                            mode=profile.mode,
                            ceiling_exhausted=(new_total_used >= total_ceiling),
                        )
                        d_state = _compute_counter_state(
                            new_d_used,
                            d_cap,
                            profile.warn_threshold_pct,
                            mode=profile.mode,
                            ceiling_exhausted=(new_total_used >= total_ceiling),
                        )
                        tx.execute(
                            "UPDATE guard_counter SET state = ? WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
                            (g_state, eff_period),
                        )
                        tx.execute(
                            "UPDATE guard_counter SET state = ? WHERE period = ? AND scope = 'device' AND scope_key = ?",
                            (d_state, eff_period, device_pseudo_id),
                        )
                        status = self._build_status_from_rows(
                            eff_period,
                            profile,
                            new_g_used,
                            new_d_used,
                            new_total_used,
                            total_ceiling,
                        )
                        decision = GuardDecision(
                            allowed=True,
                            reason="ok",
                            status=status,
                            reserved_credits=cost_credits,
                        )

        if decision.allowed:
            log_event(
                "credit.counter_update",
                {
                    "profile": decision.status.mode,
                    "used": decision.status.global_used,
                    "cap": decision.status.global_cap,
                    "remaining": decision.status.global_remaining,
                },
                severity=Severity.INFO,
                session_id=session_id,
            )
        else:
            log_event(
                "credit.guard_blocked",
                {
                    "profile": decision.status.mode,
                    "requested": cost_credits,
                    "remaining": decision.status.global_remaining,
                    "reason": decision.reason,
                },
                severity=Severity.CRITICAL,
                error_class=ErrorClass.QUOTA_ERROR,
                session_id=session_id,
            )

        if decision.status.effective_state != prev_eff_state:
            self._notify_listeners(decision.status)

        return decision

    def _build_status_from_rows(
        self,
        period: str,
        profile: GuardProfileConfig,
        g_used: float,
        d_used: float,
        total_used: float,
        total_ceiling: float,
        *,
        force_global_exhausted: bool = False,
        force_device_exhausted: bool = False,
    ) -> GuardStatus:
        g_cap = profile.active_global_cap
        d_cap = profile.active_device_cap
        ceiling_exhausted = total_used >= total_ceiling
        g_state = (
            "exhausted"
            if force_global_exhausted
            else _compute_counter_state(
                g_used,
                g_cap,
                profile.warn_threshold_pct,
                mode=profile.mode,
                ceiling_exhausted=ceiling_exhausted,
            )
        )
        d_state = (
            "exhausted"
            if force_device_exhausted
            else _compute_counter_state(
                d_used,
                d_cap,
                profile.warn_threshold_pct,
                mode=profile.mode,
                ceiling_exhausted=ceiling_exhausted,
            )
        )
        eff_state = _combine_states(g_state, d_state)
        ceiling_rem = max(0.0, total_ceiling - total_used)
        g_rem = min(max(0.0, g_cap - g_used), ceiling_rem)
        d_rem = min(max(0.0, d_cap - d_used), g_rem)
        return GuardStatus(
            period=period,
            mode=profile.mode,
            global_state=g_state,
            device_state=d_state,
            effective_state=eff_state,
            global_used=g_used,
            global_cap=g_cap,
            global_remaining=g_rem,
            device_used=d_used,
            device_cap=d_cap,
            device_remaining=d_rem,
            total_programme_used=total_used,
            total_programme_ceiling=total_ceiling,
            warn_threshold_pct=profile.warn_threshold_pct,
        )

    def record_ledger_entry(
        self,
        *,
        device_pseudo_id: str,
        model: str,
        units: str,
        amount: float,
        cost_credits: float | None = None,
        session_id: str | None = None,
        bucket: str | None = None,
        created_at: str | None = None,
    ) -> str:
        """Append a metered call row to `credit_ledger` (counts only, never content)."""
        if model not in ("prisma", "timbre", "gemma_gpu"):
            raise ValueError(f"Unsupported metered model '{model}'")
        if units not in ("seconds", "chars", "tokens"):
            raise ValueError(f"Unsupported units '{units}'")
        if amount < 0:
            raise ValueError("amount must be >= 0")

        entry_id = uuid7_str()
        ts = created_at or _utc_now_iso()
        with self.db.transaction() as tx:
            profile = self._load_profile_tx(tx)
            eff_bucket = bucket or ("reserved" if profile.mode == "demo" else "daily")
            tx.execute(
                """
                INSERT INTO credit_ledger (
                    entry_id, session_id, device_pseudo_id, model,
                    units, amount, bucket, cost_credits, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry_id,
                    session_id,
                    device_pseudo_id,
                    model,
                    units,
                    amount,
                    eff_bucket,
                    cost_credits,
                    ts,
                ),
            )

        log_event(
            "credit.call_counted",
            {
                "profile": profile.mode,
                "model": model,
                "units": amount,
            },
            severity=Severity.INFO,
            session_id=session_id,
        )
        return entry_id

    def set_profile_mode(self, mode: str, *, actor: str = "admin") -> GuardStatus:
        """Toggle `guard_profile.mode` (`normal` <-> `demo`), audit, and push state."""
        if mode not in ("normal", "demo"):
            raise ValueError(f"Invalid guard profile mode '{mode}'")

        now = _utc_now_iso()
        period = _today_period()
        with self.db.transaction() as tx:
            prev = self._load_profile_tx(tx)
            tx.execute(
                """
                UPDATE guard_profile
                SET mode = ?, updated_at = ?, updated_by = ?
                WHERE id = 1
                """,
                (mode, now, actor),
            )
            tx.execute(
                """
                INSERT INTO audit_log (audit_id, actor, action, target, before_hash, after_hash, at)
                VALUES (?, ?, 'guard_profile.flip', 'guard_profile', ?, ?, ?)
                """,
                (uuid7_str(), actor, prev.mode, mode, now),
            )
            # Re-evaluate global counter state under the new profile
            profile = self._load_profile_tx(tx)
            g_row = self._ensure_counter_row_tx(
                tx, period, "global", "global", profile.mode
            )
            total_used = self._total_programme_used_tx(tx, mode=profile.mode)
            total_ceiling = (
                profile.total_budget_credits
                if profile.mode == "demo"
                else profile.normal_ceiling_credits
            )
            new_g_state = _compute_counter_state(
                float(g_row["used_credits"]),
                profile.active_global_cap,
                profile.warn_threshold_pct,
                mode=profile.mode,
                ceiling_exhausted=(total_used >= total_ceiling),
            )
            tx.execute(
                "UPDATE guard_counter SET state = ?, updated_at = ? WHERE period = ? AND scope = 'global' AND scope_key = 'global'",
                (new_g_state, now, period),
            )

        status = self.get_status(period=period)
        self._notify_listeners(status)
        return status

    def get_reconciliation_report(self, *, period: str | None = None) -> dict[str, Any]:
        """Compare hot counter total vs `credit_ledger` sum (NFR-25 <= 2% drift)."""
        eff_period = period or _today_period()
        with self.db.transaction() as tx:
            profile = self._load_profile_tx(tx)
            g_row = self._ensure_counter_row_tx(
                tx, eff_period, "global", "global", profile.mode
            )
            ledger_row = tx.fetchone(
                """
                SELECT COALESCE(SUM(COALESCE(cost_credits, 0)), 0) AS total
                FROM credit_ledger
                WHERE substr(created_at, 1, 10) = ?
                """,
                (eff_period,),
            )
            counter_used = float(g_row["used_credits"])
            ledger_used = float(ledger_row["total"]) if ledger_row else 0.0
            if counter_used == 0.0 and ledger_used == 0.0:
                drift_pct = 0.0
            else:
                denom = max(counter_used, ledger_used, 1.0)
                drift_pct = round(abs(counter_used - ledger_used) / denom * 100.0, 2)

            return {
                "period": eff_period,
                "counter_used_credits": counter_used,
                "ledger_used_credits": ledger_used,
                "drift_pct": drift_pct,
                "drift_within_slo": drift_pct <= 2.0,
                "profile": {
                    "mode": profile.mode,
                    "global_tranche": profile.global_tranche,
                    "per_user_cap": profile.per_user_cap,
                    "demo_global_tranche": profile.demo_global_tranche,
                    "demo_per_user_cap": profile.demo_per_user_cap,
                    "warn_threshold_pct": profile.warn_threshold_pct,
                    "total_budget_credits": profile.total_budget_credits,
                    "demo_reserve_pct": profile.demo_reserve_pct,
                },
            }
