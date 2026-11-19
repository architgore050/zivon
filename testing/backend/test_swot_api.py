"""SWOT API and page contract (F8): `/v1/swot`, `/v1/swot/explain`, `/app/swot`.

Hermetic: SQLite in memory, no network, no keys, no model. Covers auth and
user scoping (a second account never sees the first one's cards), the empty
and not-enough-data states, quadrant placement over real events, speaking
attempts joined from the F6 table, the explain payload, the SSR page states,
the noindex/no-PII/no-lesson-device contracts, and the dashboard snapshot
additions (F3's own dashboard tests keep passing in `test_dashboard_pages.py`).
"""

from __future__ import annotations

import datetime
import json
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi.testclient import TestClient

from backend import BackendConfig, BackendConfigError, create_app
from backend.assessment.store import save_speaking_attempt

PASSWORD = "correct-horse-battery-staple"
CHAPTER_A = "class-9-describing-motion-around-us"
CHAPTER_B = "class-9-how-forces-affect-motion"
CHAPTER_C = "class-11-units-and-measurement"
CHAPTER_D = "class-11-motion-in-a-straight-line"
# The F0 fixture catalogue carries exactly these six chapters; the two Class 11
# chapters below are never touched by the fixtures and stay unrated.
UNRATED_TITLES = ("Motion in a Plane", "Laws of Motion")


def iso(days_ago: float) -> str:
    moment = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + (
        f"{moment.microsecond // 1000:03d}Z"
    )


class SwotApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            runs_dir=str(Path(self._tmp.name) / "runs"),
            cold_staging_dir=str(Path(self._tmp.name) / "cold"),
            auth_cookie_secure=True,
            auth_login_per_min=20,
            auth_register_per_min=20,
            rate_limit_api_per_min=200,
        )
        self.app = create_app(self.cfg)
        self.client = TestClient(self.app, base_url="https://testserver")
        self.db = self.app.state.db

    def tearDown(self) -> None:
        self._tmp.cleanup()

    # -- helpers ------------------------------------------------------------

    def register(self, email: str = "kid@example.com") -> dict[str, Any]:
        response = self.client.post(
            "/v1/auth/register",
            json={
                "email": email,
                "password": PASSWORD,
                "display_name": "Asha",
                "class_level": 9,
                "language": "en-IN",
            },
        )
        self.assertEqual(response.status_code, 201, response.text)
        return self.client.get("/v1/auth/session").json()

    def csrf(self) -> str:
        return str(self.client.get("/v1/auth/session").json()["csrf_token"])

    def post_events(self, events: list[dict[str, Any]]) -> None:
        response = self.client.post(
            "/v1/progress/events",
            json={"events": events},
            headers={"X-CSRF-Token": self.csrf()},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["accepted"], len(events))

    def answers(self, chapter_id: str, flags: list[bool], *, days: float = 1) -> None:
        self.post_events(
            [
                {
                    "kind": "practice_answer",
                    "chapter_id": chapter_id,
                    "payload": {"correct": flag, "hints_used": 0, "time_ms": 30000},
                    "occurred_at": iso(days),
                }
                for flag in flags
            ]
        )

    def lesson(self, chapter_id: str, *, seen: int, total: int) -> None:
        self.post_events(
            [
                {
                    "kind": "lesson_block_view",
                    "chapter_id": chapter_id,
                    "payload": {
                        "section_id": "sec-01",
                        "blocks_seen": seen,
                        "blocks_total": total,
                    },
                }
            ]
        )

    def seed_grid(self) -> None:
        """Three rated chapters with distinct profiles, one lesson-only."""
        self.lesson(CHAPTER_A, seen=6, total=9)
        self.lesson(CHAPTER_B, seen=5, total=9)
        self.lesson(CHAPTER_C, seen=3, total=9)
        self.answers(CHAPTER_A, [True] * 6)
        self.answers(CHAPTER_B, [False] * 6)
        self.answers(CHAPTER_C, [True] * 4)
        self.lesson(CHAPTER_D, seen=2, total=9)

    # -- auth and scope ------------------------------------------------------

    def test_guest_gets_401_on_both_endpoints(self) -> None:
        for path in ("/v1/swot", "/v1/swot/explain"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 401, path)
            self.assertEqual(response.json()["code"], "E-AUTH-REQUIRED", path)

    def test_new_user_gets_an_honest_empty_payload(self) -> None:
        self.register()
        response = self.client.get("/v1/swot")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["cache-control"], "no-store")
        payload = response.json()
        self.assertTrue(payload["is_new"])
        self.assertFalse(payload["enough_data"])
        self.assertEqual(payload["mode"], "relative")
        self.assertEqual(payload["rules"]["formula_version"], "swot-v1")
        for name in ("strength", "weakness", "opportunity", "threat"):
            self.assertEqual(payload["quadrants"][name], [])

    def test_payload_is_user_scoped_and_free_of_identifiers(self) -> None:
        session = self.register()
        self.seed_grid()
        other = TestClient(self.app, base_url="https://testserver")
        other.post(
            "/v1/auth/register",
            json={
                "email": "other@example.com",
                "password": PASSWORD,
                "class_level": 9,
                "language": "en-IN",
            },
        )
        mine = self.client.get("/v1/swot").json()
        theirs = other.get("/v1/swot").json()
        # The second account has its own (empty) view; no leakage either way.
        self.assertTrue(mine["enough_data"])
        self.assertFalse(theirs["enough_data"])
        self.assertTrue(theirs["is_new"])
        body = repr(theirs)
        self.assertNotIn(session["user"]["user_id"], body)
        self.assertNotIn("kid@example.com", body)
        # No social or parent surface anywhere in the contract.
        flat = repr(mine).lower()
        self.assertNotIn("leaderboard", flat)
        self.assertNotIn("share", flat)
        self.assertNotIn("parent", flat)
        self.assertNotIn("rank", flat)

    # -- computation over the real store -------------------------------------

    def test_quadrants_place_from_progress_events(self) -> None:
        self.register()
        self.seed_grid()
        payload = self.client.get("/v1/swot").json()
        self.assertTrue(payload["enough_data"])
        self.assertEqual(payload["rated_chapter_count"], 3)
        self.assertEqual(payload["quadrants"]["strength"][0]["chapter_id"], CHAPTER_A)
        self.assertEqual(payload["quadrants"]["weakness"][0]["chapter_id"], CHAPTER_B)
        self.assertEqual(
            payload["quadrants"]["opportunity"][0]["chapter_id"], CHAPTER_C
        )
        self.assertEqual(payload["quadrants"]["threat"], [])
        # Every chapter with no scored evidence waits in the unrated row — none
        # is forced into a box. The expected set is derived from the published
        # catalogue the backend reads, so a newly published chapter (the Class
        # 10 Light lesson) joins the row without a test edit.
        catalogue_path = (
            Path(__file__).resolve().parents[2] / "frontend" / "catalogue.json"
        )
        catalogue_ids = {
            str(topic["chapter_id"])
            for topic in json.loads(catalogue_path.read_text(encoding="utf-8"))[
                "topics"
            ]
        }
        self.assertEqual(
            {entry["chapter_id"] for entry in payload["unrated"]},
            catalogue_ids - {CHAPTER_A, CHAPTER_B, CHAPTER_C},
        )
        unrated_by_id = {entry["chapter_id"]: entry for entry in payload["unrated"]}
        self.assertIn(CHAPTER_D, unrated_by_id)
        self.assertIsNone(unrated_by_id[CHAPTER_D]["quadrant"])

    def test_speaking_attempts_reach_the_chapter_metrics(self) -> None:
        session = self.register()
        user_id = session["user"]["user_id"]
        self.db.execute(
            """
            INSERT INTO speaking_prompt (
                prompt_id, language, class_level, chapter_id, concept_ids,
                prompt, key_ideas, model_answer, model_answer_source, rubric,
                status, version, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "prompt-swot-1",
                "en",
                9,
                CHAPTER_A,
                "[]",
                "Explain acceleration.",
                "[]",
                "Acceleration is the rate of change of velocity.",
                "{}",
                "{}",
                "published",
                1,
                iso(1),
                iso(1),
            ),
        )
        save_speaking_attempt(
            self.db,
            user_id,
            prompt_id="prompt-swot-1",
            language="en",
            transcript=None,
            score=88.0,
        )
        self.seed_grid()
        payload = self.client.get("/v1/swot").json()
        cards = (
            payload["quadrants"]["strength"]
            + payload["quadrants"]["weakness"]
            + payload["quadrants"]["opportunity"]
            + payload["quadrants"]["threat"]
        )
        by_id = {card["chapter_id"]: card for card in cards}
        self.assertEqual(by_id[CHAPTER_A]["metrics"]["scored_items"], 7)
        self.assertEqual(by_id[CHAPTER_A]["metrics"]["speaking_score_pct"], 88.0)

    def test_coverage_counts_base_items_once_across_languages(self) -> None:
        """Regression (F8R review): coverage shares the denominator's basis.

        The bank is one row per (item, language) and the served denominator
        counts DISTINCT base items. A student who answers the same item in
        English and then in Hindi must add one item to the numerator, not two
        — otherwise coverage crosses 100 % (here 5/4 would read 125 %) and
        the median split misplaces the chapter.
        """
        session = self.register()
        user_id = session["user"]["user_id"]
        # Five served base items, each in two languages (the tri-lingual pack
        # shape of docs/content-factory/assessment.md A3).
        for item_no in range(5):
            for language in ("en", "hi"):
                self.db.execute(
                    """
                    INSERT INTO question_bank (
                        question_id, base_item_id, class_level, chapter_id,
                        concept_id, type, difficulty, marks, language,
                        source_type, prompt, options, answer, explanation,
                        expected_time_ms, status
                    ) VALUES (?, ?, 9, ?, 'swot-concept', 'mcq', 'easy', 1,
                              ?, 'generated', 'Pick one', '["a","b"]',
                              '{"index": 0}', 'Because.', 30000, 'published')
                    """,
                    (
                        f"swot-item-{item_no}-{language}",
                        f"swot-item-{item_no}",
                        CHAPTER_A,
                        language,
                    ),
                )

        def attempted_session(question_ids: list[str]) -> None:
            session_id = f"swot-session-{question_ids[0]}"
            self.db.execute(
                """
                INSERT INTO practice_session (session_id, user_id, mode,
                      chapter_id, question_ids, question_count, config)
                VALUES (?, ?, 'chapter', ?, ?, ?, '{}')
                """,
                (
                    session_id,
                    user_id,
                    CHAPTER_A,
                    json.dumps(question_ids),
                    len(question_ids),
                ),
            )
            for question_id in question_ids:
                self.db.execute(
                    """
                    INSERT INTO practice_attempt (attempt_id, session_id,
                          question_id, correct, time_ms, attempt_no)
                    VALUES (?, ?, ?, 1, 30000, 1)
                    """,
                    (f"{session_id}-{question_id}", session_id, question_id),
                )

        # English: items 0-2. Hindi: item 0 again (the same base item) and 3.
        attempted_session([f"swot-item-{n}-en" for n in range(3)])
        attempted_session(["swot-item-0-hi", "swot-item-3-hi"])
        # The event source (F5's first-attempt feed) counts item 4 once too.
        self.post_events(
            [
                {
                    "kind": "practice_answer",
                    "chapter_id": CHAPTER_A,
                    "question_id": "swot-item-4-hi",
                    "payload": {"correct": True, "hints_used": 0, "time_ms": 30000},
                }
            ]
        )
        # Five distinct base items attempted of five served → 100 %, never
        # the 120 % that raw per-language ids would produce.
        payload = self.client.get("/v1/swot/explain").json()
        entry = next(
            entry for entry in payload["chapters"] if entry["chapter_id"] == CHAPTER_A
        )
        self.assertEqual(entry["metrics"]["attempt_rate_pct"], 100.0)
        self.assertEqual(entry["metrics"]["coverage_pct"], 100.0)

    def test_explain_endpoint_carries_the_method_and_the_numbers(self) -> None:
        self.register()
        self.seed_grid()
        payload = self.client.get("/v1/swot/explain").json()
        self.assertGreaterEqual(len(payload["method"]), 5)
        self.assertEqual(len(payload["metric_definitions"]), 7)
        self.assertIsNotNone(payload["medians"])
        chapters = {entry["chapter_id"] for entry in payload["chapters"]}
        self.assertIn(CHAPTER_A, chapters)
        self.assertIn(CHAPTER_D, chapters)
        self.assertEqual(payload["rules"]["half_life_days"], 21)

    def test_absolute_mode_is_a_config_choice_not_a_parameter(self) -> None:
        self.register()
        cfg = BackendConfig(
            db_url="sqlite:///:memory:",
            env="test",
            swot_mode="absolute",
            runs_dir=str(Path(self._tmp.name) / "runs2"),
        )
        absolute_client = TestClient(create_app(cfg), base_url="https://testserver")
        absolute_client.post(
            "/v1/auth/register",
            json={
                "email": "abs@example.com",
                "password": PASSWORD,
                "class_level": 9,
                "language": "en-IN",
            },
        )
        csrf = absolute_client.get("/v1/auth/session").json()["csrf_token"]
        events = [
            {
                "kind": "practice_answer",
                "chapter_id": CHAPTER_A,
                "payload": {"correct": True, "hints_used": 0, "time_ms": 30000},
            }
            for _ in range(4)
        ] + [
            {
                "kind": "lesson_block_view",
                "chapter_id": CHAPTER_A,
                "payload": {
                    "section_id": "sec-01",
                    "blocks_seen": 8,
                    "blocks_total": 9,
                },
            }
        ]
        posted = absolute_client.post(
            "/v1/progress/events",
            json={"events": events},
            headers={"X-CSRF-Token": csrf},
        )
        self.assertEqual(posted.status_code, 200, posted.text)
        payload = absolute_client.get("/v1/swot").json()
        self.assertEqual(payload["mode"], "absolute")
        self.assertEqual(payload["quadrants"]["strength"][0]["chapter_id"], CHAPTER_A)

    def test_invalid_swot_mode_refuses_to_boot(self) -> None:
        with (
            mock.patch.dict("os.environ", {"ZIVON_SWOT_MODE": "median"}),
            self.assertRaises(BackendConfigError),
        ):
            BackendConfig.from_env()

    # -- pages ---------------------------------------------------------------

    def test_swot_page_states_and_shell_contracts(self) -> None:
        session = self.register()
        user_id = session["user"]["user_id"]
        # Empty state first.
        html = self.client.get("/app/swot").text
        self.assertIn("Not enough data yet.", html)
        self.assertIn("How this works", html)
        self.assertIn('href="/app/swot/how"', html)
        self.assertIn("noindex", self.client.get("/app/swot").headers["X-Robots-Tag"])
        # Guest is redirected to the login guard.
        guest = TestClient(
            self.app, base_url="https://testserver", follow_redirects=False
        )
        self.assertEqual(guest.get("/app/swot").status_code, 303)
        self.assertIn("/login", guest.get("/app/swot").headers["location"])
        # Rated grid: quadrants, evidence, one next action, unrated row.
        self.seed_grid()
        html = self.client.get("/app/swot").text
        for label in ("Strengths", "Weaknesses", "Opportunities", "Threats"):
            self.assertIn(label, html)
        self.assertIn("Not rated yet", html)
        self.assertIn("Motion in a Straight Line", html)
        self.assertIn("/app/practice?chapter=", html)
        self.assertNotIn(user_id, html)
        self.assertNotIn("kid@example.com", html)
        self.assertNotRegex(html, r"\bzn-[a-z0-9-]+")
        self.assertNotIn("zivon.css", html)
        self.assertIn("aria-labelledby=", html)
        self.assertIn('class="skip"', html)
        # The mode/threshold knobs never surface as a student setting.
        self.assertNotIn("SWOT_MODE", html)

    def test_swot_how_page_publishes_the_method_and_the_table(self) -> None:
        self.register()
        self.seed_grid()
        response = self.client.get("/app/swot/how")
        self.assertEqual(response.status_code, 200)
        html = response.text
        self.assertIn("How your SWOT is computed.", html)
        self.assertIn("Performance median", html)
        self.assertIn("weighted_accuracy_pct", html)
        self.assertIn("time_ratio", html)
        self.assertIn("<table", html)
        self.assertIn("Not rated", html)
        self.assertIn("21-day half-life", html)

    def test_nav_and_dashboard_carry_the_swot_entry(self) -> None:
        self.register()
        html = self.client.get("/app").text
        self.assertIn('href="/app/swot"', html)
        self.assertIn("SWOT snapshot", html)
        self.assertIn("Open your full SWOT", html)
        swot = self.client.get("/app/swot").text
        self.assertIn('href="/app/swot" aria-current="page"', swot)

    def test_dashboard_snapshot_shows_the_not_enough_data_copy(self) -> None:
        self.register()
        self.answers(CHAPTER_A, [True] * 4)
        self.lesson(CHAPTER_A, seen=6, total=9)
        html = self.client.get("/app").text
        self.assertIn("Not enough data yet", html)
        self.assertIn("Open your full SWOT", html)

    def test_dashboard_snapshot_survives_a_swot_failure(self) -> None:
        self.register()
        with mock.patch("web.swot_views.build_swot", side_effect=RuntimeError("boom")):
            response = self.client.get("/app")
        self.assertEqual(response.status_code, 200)
        self.assertIn("The SWOT snapshot is unavailable right now", response.text)
        # The rest of the dashboard is intact (F3 is not broken by F8).
        self.assertIn("Continue learning", response.text)

    def test_swot_page_survives_a_store_failure(self) -> None:
        self.register()
        with mock.patch(
            "backend.swot.store.read_learner_events", side_effect=RuntimeError("boom")
        ):
            response = self.client.get("/app/swot")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Your SWOT is unavailable right now.", response.text)
        self.assertIn("Open the progress map instead", response.text)


if __name__ == "__main__":
    unittest.main()
