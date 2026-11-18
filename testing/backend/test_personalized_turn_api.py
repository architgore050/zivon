"""PL2 turn-endpoint tests (API-PL-10, data-and-api.md §4.6): the honest
unconfigured 503, the SSE event order, the JSON fallback, idempotent replay,
quota reservation/commit/release, tenant scoping, CSRF, and the in-flight
lock — fakes only at the model seam; store, quota, and state are the real
implementations on one harness database.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, ClassVar

from backend.personalized.agent import PersonalizedAgent, RetrievalPorts
from backend.personalized.bank import QuestionBank
from backend.personalized.quota import QuotaService
from backend.personalized.rag import FixtureEmbedder
from backend.personalized.store import PersonalizedStore
from testing.backend.personalized_support import (
    CHAPTER,
    CONCEPT_A,
    CONCEPT_B,
    FakeModelClient,
    build_fixture_index,
    default_bank,
)
from testing.backend.web_auth_support import PASSWORD, WebAuthSupport


def seed_chapters(db: Any) -> None:  # type: ignore[no-untyped-def]
    db.execute(
        "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, slug, title_en) "
        "VALUES (?, 10, 'physics', 10, 'light', 'Light - Reflection and Refraction')",
        (CHAPTER,),
    )
    for concept_id, slug, title, order in (
        (CONCEPT_A, "reflection", "Reflection of light", 0),
        (CONCEPT_B, "spherical-mirrors", "Spherical mirrors", 1),
    ):
        db.execute(
            "INSERT INTO concept (concept_id, chapter_id, slug, title_en, order_index) "
            "VALUES (?, ?, ?, ?, ?)",
            (concept_id, CHAPTER, slug, title, order),
        )


class TurnEndpointTest(WebAuthSupport):
    """One harness app; the engine seam carries the real agent over fakes."""

    config_overrides: ClassVar[dict[str, Any]] = {
        "rate_limit_personalized_create_per_hour": 50,
        "rate_limit_personalized_turn_per_min": 100,
        "rate_limit_personalized_read_per_min": 200,
    }

    def setUp(self) -> None:
        super().setUp()
        seed_chapters(self.db)
        self.register_via_api()
        self.csrf = self.session_csrf()
        self.store = PersonalizedStore(self.db)
        self.quota = QuotaService(self.db)
        ctx = self.service.resolve(self.client.cookies.get("zivon_session"))
        self.user_id = str(ctx.user["user_id"]) if ctx else "u-1"
        self._wire_agent()

    def _wire_agent(self, **model_kwargs: Any) -> FakeModelClient:  # type: ignore[no-untyped-def]
        model = FakeModelClient(**model_kwargs)
        index = build_fixture_index(Path(self._tmp.name))
        self.app.state.personalized_turn_engine = PersonalizedAgent(
            store=self.store,
            config=self.cfg,
            retrieval=RetrievalPorts(index=index, embedder=FixtureEmbedder()),
            model_client=model,
            bank=QuestionBank(self.db) if self._bank_rows else default_bank(),
        )
        return model

    _bank_rows: ClassVar[list[dict[str, Any]] | None] = None

    # -- helpers ---------------------------------------------------------------

    def _create_session(self) -> str:
        response = self.client.post(
            "/v1/personalized/sessions",
            json={"chapter_id": CHAPTER, "skip_diagnostic": True},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return str(response.json()["session_id"])

    def _post_turn(self, session_id: str, body: dict[str, Any], **headers: str):  # type: ignore[no-untyped-def]
        merged = {"X-CSRF-Token": self.csrf}
        merged.update(headers)
        return self.client.post(
            f"/v1/personalized/sessions/{session_id}/turns", json=body, headers=merged
        )

    # -- unconfigured / auth ------------------------------------------------

    def test_unconfigured_engine_answers_honest_503(self) -> None:
        self.app.state.personalized_turn_engine = None
        session_id = self._create_session()
        response = self._post_turn(
            session_id, {"client_turn_id": "c-1", "action": "continue"}
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "E-PL-MODEL-DOWN")

    def test_guest_is_401(self) -> None:
        session_id = self._create_session()
        self.client.cookies.clear()
        response = self.client.post(
            f"/v1/personalized/sessions/{session_id}/turns",
            json={"client_turn_id": "c-0", "action": "continue"},
        )
        self.assertEqual(response.status_code, 401)

    def test_csrf_missing_is_403_and_changes_nothing(self) -> None:
        session_id = self._create_session()
        self.engine_calls_before = len(self._engine_calls())
        response = self.client.post(
            f"/v1/personalized/sessions/{session_id}/turns",
            json={"client_turn_id": "c-0b", "action": "continue"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(self._engine_calls()), self.engine_calls_before)

    def _engine_calls(self) -> list[dict[str, Any]]:
        return getattr(self.app.state.personalized_turn_engine, "_recorded", [])

    def test_another_users_session_is_404_no_oracle(self) -> None:
        session_id = self._create_session()
        self.client.post(
            "/v1/auth/register",
            json={"email": "second-kid@example.com", "password": PASSWORD},
        )
        # The register logs the new user in; the session belongs to u-1.
        response = self.client.post(
            f"/v1/personalized/sessions/{session_id}/turns",
            json={"client_turn_id": "c-x", "action": "continue"},
            headers={"X-CSRF-Token": self.session_csrf()},
        )
        self.assertEqual(response.status_code, 404)

    # -- SSE ---------------------------------------------------------------

    def test_sse_event_order_and_headers(self) -> None:
        session_id = self._create_session()
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-1", "action": "continue"},
            Accept="text/event-stream",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("text/event-stream", response.headers["content-type"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(response.headers["x-accel-buffering"], "no")
        names = [
            line.split("event: ", 1)[1].split("\n", 1)[0]
            for line in response.text.split("\n\n")
            if line.startswith("event: ")
        ]
        self.assertEqual(
            names,
            [
                "turn.stage",
                "turn.teach.start",
                "turn.teach.delta",
                "turn.teach.delta",
                "turn.check",
                "turn.next",
                "turn.done",
            ],
        )

    def test_json_fallback_returns_the_assembled_turn(self) -> None:
        session_id = self._create_session()
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-2", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        names = [e["event"] for e in payload["events"]]
        self.assertEqual(
            names,
            [
                "turn.stage",
                "turn.teach.start",
                "turn.teach.delta",
                "turn.teach.delta",
                "turn.check",
                "turn.next",
                "turn.done",
            ],
        )
        self.assertTrue(payload["message_id"])
        self.assertIn("quota", payload)
        # The check payload carries no key.
        check = next(
            e["payload"] for e in payload["events"] if e["event"] == "turn.check"
        )
        self.assertNotIn("answer", json.dumps(check))
        self.assertEqual(check["source"]["kind"], "bank")

    def test_answer_reaches_the_engine_and_scores(self) -> None:
        session_id = self._create_session()
        first = self._post_turn(
            session_id,
            {"client_turn_id": "c-3", "action": "continue"},
            Accept="application/json",
        )
        check = next(
            e["payload"] for e in first.json()["events"] if e["event"] == "turn.check"
        )
        second = self._post_turn(
            session_id,
            {
                "client_turn_id": "c-4",
                "action": "answer",
                "check_id": check["check_id"],
                "answer": "A",  # the bank key is option A
            },
            Accept="application/json",
        )
        names = [e["event"] for e in second.json()["events"]]
        self.assertIn("turn.feedback", names)
        feedback = next(
            e["payload"]
            for e in second.json()["events"]
            if e["event"] == "turn.feedback"
        )
        self.assertTrue(feedback["correct"])
        self.assertEqual(feedback["expected"], "A")

    # -- admission ----------------------------------------------------------

    def test_open_check_blocks_a_new_teaching_action_409(self) -> None:
        session_id = self._create_session()
        self._post_turn(
            session_id,
            {"client_turn_id": "c-5", "action": "continue"},
            Accept="application/json",
        )
        session = self.store.get_session(self.user_id, session_id)
        assert session is not None
        state = session["state"]
        from backend.personalized import state as sm

        self.assertIsNotNone(sm.open_check(state))
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-6", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["code"], "E-PL-TURN-OPEN")

    def test_answer_without_open_check_is_409(self) -> None:
        session_id = self._create_session()
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-7", "action": "answer", "answer": "A"},
            Accept="application/json",
        )
        self.assertEqual(response.status_code, 409)

    def test_invalid_action_is_422(self) -> None:
        session_id = self._create_session()
        response = self._post_turn(
            session_id, {"client_turn_id": "c-8", "action": "hack"}
        )
        self.assertEqual(response.status_code, 422)

    def test_unknown_fields_refused(self) -> None:
        session_id = self._create_session()
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-9", "action": "continue", "surprise": True},
        )
        self.assertEqual(response.status_code, 422)

    # -- idempotency ----------------------------------------------------------

    def test_replayed_client_turn_id_returns_the_stored_result(self) -> None:
        session_id = self._create_session()
        model = self._wire_agent()
        first = self._post_turn(
            session_id,
            {"client_turn_id": "c-10", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(first.status_code, 200)
        self.assertEqual(len(model.teach_prompts), 1)
        second = self._post_turn(
            session_id,
            {"client_turn_id": "c-10", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertTrue(second.json().get("events"))
        # No second model call: the replay rebuilt the stream from the rows.
        self.assertEqual(len(model.teach_prompts), 1)

    # -- quota ------------------------------------------------------------------

    def test_quota_commit_on_done_and_release_on_failure(self) -> None:
        session_id = self._create_session()
        self._post_turn(
            session_id,
            {"client_turn_id": "c-11", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(self.quota.get_usage(self.user_id)["turns"]["used"], 1)

        # A teach-call failure releases the reservation (no tokens spent):
        # the failed turn uses a FRESH session (the first left a check open).
        self._wire_agent(stream_error=RuntimeError("socket dead"))
        other_session = self._create_session()
        response = self._post_turn(
            other_session,
            {"client_turn_id": "c-12", "action": "continue"},
            Accept="application/json",
        )
        names = [e["event"] for e in response.json()["events"]]
        self.assertEqual(names[-1], "turn.error")
        self.assertEqual(self.quota.get_usage(self.user_id)["turns"]["used"], 1)

    def test_decide_pending_commits_and_retry_does_not_double_charge(self) -> None:
        session_id = self._create_session()
        model = self._wire_agent(decide_error=RuntimeError("decide down"))
        first = self._post_turn(
            session_id,
            {"client_turn_id": "c-13", "action": "continue"},
            Accept="application/json",
        )
        names = [e["event"] for e in first.json()["events"]]
        self.assertIn("turn.error", names)
        self.assertEqual(self.quota.get_usage(self.user_id)["turns"]["used"], 1)

        # The retry reuses the id; only the decide call runs; no new charge.
        model2 = self._wire_agent()
        second = self._post_turn(
            session_id,
            {"client_turn_id": "c-13", "action": "retry_decide"},
            Accept="application/json",
        )
        self.assertEqual(second.status_code, 200)
        self.assertEqual(self.quota.get_usage(self.user_id)["turns"]["used"], 1)
        self.assertEqual(model2.teach_prompts, [])
        self.assertEqual(len(model2.decide_prompts), 1)
        del model

    def _exhaust_user_quota(self) -> None:
        """Seed both quota rows at the cap (commit_turn no-ops without rows;
        a fresh test DB has none, so a plain INSERT is exact)."""
        from backend.personalized.quota import ist_period

        period = ist_period()
        with self.db.transaction() as tx:
            tx.execute(
                "INSERT OR REPLACE INTO personalized_quota "
                "(period, scope, scope_key, turns_used, state, updated_at) "
                "VALUES (?, 'user', ?, 40, 'exhausted', '2026-01-01T00:00:00.000Z')",
                (period, self.user_id),
            )
            tx.execute(
                "INSERT OR REPLACE INTO personalized_quota "
                "(period, scope, scope_key, turns_used, state, updated_at) "
                "VALUES (?, 'global', 'global', 0, 'ok', '2026-01-01T00:00:00.000Z')",
                (period,),
            )

    def test_user_quota_exhausted_is_403(self) -> None:
        session_id = self._create_session()
        self._exhaust_user_quota()
        response = self._post_turn(
            session_id,
            {"client_turn_id": "c-q1", "action": "continue"},
            Accept="application/json",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["code"], "E-QUOTA-EXHAUSTED")

    def test_blocked_reservation_writes_a_usage_row(self) -> None:
        session_id = self._create_session()
        self._exhaust_user_quota()
        self._post_turn(
            session_id,
            {"client_turn_id": "c-qb", "action": "continue"},
        )
        rows = self.db.fetchall(
            "SELECT outcome FROM personalized_usage WHERE session_id = ?",
            (session_id,),
        )
        self.assertEqual([r["outcome"] for r in rows], ["quota_blocked"])


if __name__ == "__main__":
    unittest.main()
