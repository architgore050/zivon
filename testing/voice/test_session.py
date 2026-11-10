"""Unit tests for voice.session (spec.md §13 test table).

Covers: voice_turn rows written; 7-day TTL purge deletes only expired;
credit guard H1–H4 paths incl. the demo profile; the no-raw-audio schema
assertion (ADR-0008); session_token validation (GAP-003); rate limits.
"""

from __future__ import annotations

import unittest

from voice.config import VoiceSettings
from voice.session import (
    CreditGuard,
    InMemoryTurnRepository,
    IpRateLimiter,
    SessionIdentity,
    SessionStore,
    TokenValidator,
    TurnRecord,
    credit_points,
    issue_session_token,
    turn_estimate,
)

_KEY = "test-session-key"


class SessionTokenTest(unittest.TestCase):
    def test_round_trip_and_expiry(self) -> None:
        validator = TokenValidator(_KEY)
        token = issue_session_token("s-1", "dev-1", _KEY, now=1000.0)
        identity = validator.validate(token, now=1000.0)
        assert identity is not None
        self.assertEqual(identity.session_id, "s-1")
        self.assertEqual(identity.device_pseudo_id, "dev-1")
        # expired (12 h TTL)
        self.assertIsNone(validator.validate(token, now=1000.0 + 12 * 3600 + 1))

    def test_garbage_and_wrong_key_rejected(self) -> None:
        validator = TokenValidator(_KEY)
        self.assertIsNone(validator.validate(""))
        self.assertIsNone(validator.validate("garbage"))
        self.assertIsNone(validator.validate("a.b"))
        other = issue_session_token("s", "d", "other-key")
        self.assertIsNone(validator.validate(other))
        tampered = issue_session_token("s-1", "dev-1", _KEY)[:-1] + (
            "0" if issue_session_token("s-1", "dev-1", _KEY)[-1] != "0" else "1"
        )
        self.assertIsNone(validator.validate(tampered))

    def test_unconfigured_key_fails_closed(self) -> None:
        validator = TokenValidator("")
        token = issue_session_token("s", "d", "anything")
        self.assertIsNone(validator.validate(token))


class IpRateLimiterTest(unittest.TestCase):
    def test_connect_window_and_bucket_expiry(self) -> None:
        now = [1000.0]
        settings = VoiceSettings(ip_hash_salt="salt", ws_connects_per_min=3)
        limiter = IpRateLimiter(settings, clock=lambda: now[0])
        for _ in range(3):
            self.assertTrue(limiter.allow_connect("203.0.113.9"))
        self.assertFalse(limiter.allow_connect("203.0.113.9"))  # window full
        now[0] += 61.0
        self.assertTrue(limiter.allow_connect("203.0.113.9"))  # new window

    def test_hash_rotates_daily_and_never_stores_raw_ip(self) -> None:
        settings = VoiceSettings(ip_hash_salt="salt")
        limiter = IpRateLimiter(settings)
        hash_a = limiter.hash_ip("203.0.113.9")
        self.assertNotIn("203.0.113.9", str(limiter._windows))
        self.assertEqual(len(hash_a), 16)
        self.assertNotEqual(hash_a, limiter.hash_ip("203.0.113.10"))

    def test_unsalted_fails_open_with_warning(self) -> None:
        limiter = IpRateLimiter(VoiceSettings(ip_hash_salt=""))
        self.assertTrue(limiter.allow_connect("1.2.3.4"))

    def test_hash_uses_injected_clock_for_daily_rotation(self) -> None:
        # hash_ip must follow the injected clock, not wall time — otherwise
        # the daily rotation is untestable and a frozen clock still rotates.
        now = [0.0]
        settings = VoiceSettings(ip_hash_salt="salt")
        limiter = IpRateLimiter(settings, clock=lambda: now[0])
        first = limiter.hash_ip("203.0.113.9")
        now[0] += 60.0
        self.assertEqual(limiter.hash_ip("203.0.113.9"), first)  # same IST day
        now[0] += 86400.0 * 2
        self.assertNotEqual(limiter.hash_ip("203.0.113.9"), first)  # rotated

    def test_device_bucket_is_secondary_rate_limit(self) -> None:
        # Behind an ingress every peer is the proxy: the device bucket keeps
        # the per-client limit meaningful and is independent of the IP bucket.
        settings = VoiceSettings(ip_hash_salt="salt", ws_connects_per_min=2)
        limiter = IpRateLimiter(settings)
        self.assertTrue(limiter.allow_device("device-a"))
        self.assertTrue(limiter.allow_device("device-a"))
        self.assertFalse(limiter.allow_device("device-a"))
        self.assertTrue(limiter.allow_device("device-b"))
        self.assertTrue(limiter.allow_connect("203.0.113.9"))  # separate bucket


class CreditGuardTest(unittest.TestCase):
    def _settings(self, **kw: int) -> VoiceSettings:
        params: dict[str, int] = {
            "credit_daily_tranche": 100,
            "credit_per_user_cap": 30,
            "credit_demo_tranche": 100,
            "credit_demo_session_cap": 20,
        }
        params.update(kw)
        return VoiceSettings(**params)  # type: ignore[arg-type]

    def test_h1_ok_then_exhausted(self) -> None:
        guard = CreditGuard(
            self._settings(credit_per_user_cap=100, credit_daily_tranche=100)
        )
        self.assertTrue(guard.check_start("normal", "u1").allowed)
        decision = guard.check_turn("normal", "u1", "s1", estimate=100)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reserved, 100)
        self.assertFalse(guard.check_start("normal", "u2").allowed)  # global out

    def test_h2_reserves_both_dimensions(self) -> None:
        guard = CreditGuard(self._settings())
        ok = guard.check_turn("normal", "u1", "s1", estimate=25)
        self.assertTrue(ok.allowed)
        self.assertEqual(ok.reserved, 25)
        # per-user cap 30: only 5 left → next 25-estimate is refused
        denied = guard.check_turn("normal", "u1", "s2", estimate=25)
        self.assertFalse(denied.allowed)
        self.assertEqual(denied.reason_code, "credit.over_daily")
        # another user still fits within the global tranche
        self.assertTrue(guard.check_turn("normal", "u2", "s3", estimate=25).allowed)

    def test_h4_commit_replaces_estimate_with_actual(self) -> None:
        guard = CreditGuard(self._settings())
        guard.check_turn("normal", "u1", "s1", estimate=25)
        guard.commit_turn("normal", "u1", "s1", estimate=25, actual=10)
        self.assertEqual(guard.remaining("normal", "u1"), 20)  # 30 cap - 10 actual

    def test_demo_profile_uses_session_cap(self) -> None:
        guard = CreditGuard(self._settings())
        self.assertTrue(guard.check_turn("demo", "u1", "s1", estimate=15).allowed)
        # demo cap is per-SESSION: another session of the same user still fits
        self.assertTrue(guard.check_turn("demo", "u1", "s2", estimate=15).allowed)
        # but session s1 is done: 15 + 15 > 20
        self.assertFalse(guard.check_turn("demo", "u1", "s1", estimate=15).allowed)

    def test_daily_reset_ist(self) -> None:
        guard = CreditGuard(self._settings())
        guard.check_turn("normal", "u1", "s1", estimate=30)
        # next IST day: a fresh period (00:00 IST reset)
        self.assertEqual(guard.remaining("normal", "u1", now=86400 * 400 + 100), 30)

    def test_warn_state_at_15_percent(self) -> None:
        guard = CreditGuard(
            VoiceSettings(
                credit_daily_tranche=100,
                credit_per_user_cap=1000,
                credit_demo_tranche=100,
                credit_demo_session_cap=1000,
            )
        )
        guard.check_turn("normal", "u1", "s1", estimate=90)
        decision = guard.check_turn("normal", "u2", "s2", estimate=1)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "warn")  # ≤ 15 % of the tranche left

    def test_credit_points_conversion_is_coherent(self) -> None:
        s = VoiceSettings(
            credit_stt_seconds_per_point=30, credit_tts_chars_per_point=300
        )
        self.assertEqual(credit_points(s, stt_seconds=15, tts_chars=600), 3)
        self.assertEqual(credit_points(s, stt_seconds=0.2, tts_chars=33), 2)
        self.assertEqual(credit_points(s), 0)
        # a whole normal day fits the 30-point cap: ~10 voice turns
        self.assertLessEqual(turn_estimate(s) * 10, s.credit_per_user_cap)
        self.assertGreater(turn_estimate(s) * 11, s.credit_per_user_cap)

    def test_estimate_uses_a07_figures_in_points(self) -> None:
        # A-07 physical estimate (≈ 15 s STT + 600 TTS chars) converted to
        # credit points: ceil(15/30) + ceil(600/300) = 3 points per voice turn.
        self.assertEqual(turn_estimate(VoiceSettings()), 3)
        # A typed turn spends no STT: 2 points (it still speaks).
        self.assertEqual(turn_estimate(VoiceSettings(), typed=True), 2)

    def test_demo_remaining_uses_session_dimension(self) -> None:
        # spec.md §8: demo cap is per-SESSION — another session of the same
        # user starts with its own budget, and H1 sees that too.
        guard = CreditGuard(self._settings())
        guard.check_turn("demo", "u1", "s1", estimate=15)
        self.assertEqual(guard.remaining("demo", "u1", session_id="s1"), 5)
        self.assertEqual(guard.remaining("demo", "u1", session_id="s2"), 20)
        # without a session id the cap falls back to the user dimension
        self.assertEqual(guard.remaining("demo", "u1"), 20)

    def test_normal_remaining_uses_user_dimension(self) -> None:
        guard = CreditGuard(self._settings())
        guard.check_turn("normal", "u1", "s1", estimate=10)
        self.assertEqual(guard.remaining("normal", "u1"), 20)


class TurnRepositoryTest(unittest.IsolatedAsyncioTestCase):
    async def test_rows_written_and_recent_window(self) -> None:
        repo = InMemoryTurnRepository()
        for idx in range(8):
            await repo.append_turn(
                TurnRecord(
                    id=f"t{idx}",
                    session_id="s1",
                    turn_idx=idx,
                    role="student",
                    text=f"doubt {idx}",
                )
            )
        recent = await repo.recent_turns("s1", limit=6)
        self.assertEqual(len(recent), 6)
        self.assertEqual(recent[0].turn_idx, 2)  # last ≤ 6 turns (spec.md §6)

    async def test_ttl_purge_deletes_only_expired(self) -> None:
        t0 = 1_000_000.0
        now = [t0]
        repo = InMemoryTurnRepository(clock=lambda: now[0])
        await repo.append_turn(
            TurnRecord(
                id="old",
                session_id="s",
                turn_idx=0,
                role="student",
                text="x",
                created_at=t0,
            )
        )
        now[0] += 6 * 86400
        await repo.append_turn(
            TurnRecord(
                id="new",
                session_id="s",
                turn_idx=1,
                role="student",
                text="y",
                created_at=now[0],
            )
        )
        now[0] += 2 * 86400  # old row is now 8 days old, new row 2 days
        deleted = await repo.purge_expired(now[0])
        self.assertEqual(deleted, 1)  # only the > 7-day row
        rows = await repo.recent_turns("s", limit=10)
        self.assertEqual([r.id for r in rows], ["new"])

    async def test_no_audio_field_anywhere_on_turn_record(self) -> None:
        # ADR-0008: schema-enforced non-storage — if anyone adds an audio
        # field to the row, this fails before it can ever be persisted.
        record = TurnRecord(
            id="x", session_id="s", turn_idx=0, role="student", text="t"
        )
        dataclass_fields = {f.name for f in type(record).__dataclass_fields__.values()}
        forbidden = {"audio", "audio_bytes", "pcm", "wav", "audio_path", "audio_url"}
        self.assertEqual(dataclass_fields & forbidden, set())
        # also: no attribute smuggles audio bytes
        self.assertFalse(any("audio" in name.lower() for name in dataclass_fields))
        self.assertEqual(record.credit_cost, 0.0)
        self.assertEqual(record.block_ids_ref, ())


class SessionStoreTest(unittest.TestCase):
    def test_channel_concurrency_caps(self) -> None:
        settings = VoiceSettings(ws_max_concurrent_sessions=2)
        store = SessionStore(settings)
        for n in ("a", "b"):
            store.create(SessionIdentity(n, f"d{n}"), "normal", "hi-en")
        self.assertTrue(store.acquire_channel("a"))
        self.assertTrue(store.acquire_channel("b"))
        self.assertFalse(store.acquire_channel("c"))  # global ceiling
        self.assertFalse(store.acquire_channel("a"))  # 1 channel per session
        store.release_channel("a")
        self.assertTrue(store.acquire_channel("c"))

    def test_registry_bounded_evicts_oldest(self) -> None:
        store = SessionStore(VoiceSettings(ws_max_concurrent_sessions=2))
        store.MAX_SESSIONS = 3
        for n in range(3):
            store.create(SessionIdentity(f"s{n}", f"d{n}"), "normal", "hi-en")
        store.create(SessionIdentity("s3", "d3"), "normal", "hi-en")
        self.assertEqual(len(store._sessions), 3)
        self.assertIsNone(store.get("s0"))  # oldest evicted
        self.assertIsNotNone(store.get("s3"))

    def test_registry_never_evicts_live_channel(self) -> None:
        store = SessionStore(VoiceSettings(ws_max_concurrent_sessions=2))
        store.MAX_SESSIONS = 1
        store.create(SessionIdentity("live", "d0"), "normal", "hi-en")
        self.assertTrue(store.acquire_channel("live"))
        store.create(SessionIdentity("new", "d1"), "normal", "hi-en")
        self.assertIsNotNone(store.get("live"))  # live channel survives
        self.assertIsNotNone(store.get("new"))

    def test_replay_window_60s(self) -> None:
        now = [10_000.0]
        store = SessionStore(VoiceSettings(), clock=lambda: now[0])
        session = store.create(SessionIdentity("s", "d"), "normal", "hi-en")
        session.last_turn_end = {"turn_id": "t"}
        session.last_turn_end_at = now[0]
        self.assertTrue(store.replay_window_alive(session))
        now[0] += 61.0
        self.assertFalse(store.replay_window_alive(session))


if __name__ == "__main__":
    unittest.main()
