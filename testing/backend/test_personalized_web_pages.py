"""PL4 web-page tests: the personalized hub, session screen, and the settings
instructions section (`web/routes/personalized.py`, `web/personalized_views.py`).

Hermetic: SQLite in memory through the real app factory, the F0C guard/CSRF
contract, the PL1 store as the data seam, and the RAG catalog injected as the
`app.state.personalized_index_catalog` callable (the same seam the JSON API
reads). No key, no network, no model call. The teaching turn itself stays the
PL2 API and is covered by `test_personalized_turn_api.py`; these tests pin the
pages: the guard, CSRF, the honest states, the 404-for-other-owner rule, the
no-answer-key rule, and the no-student-text-in-logs rule.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, ClassVar
from unittest import mock

from backend.personalized.store import PersonalizedStore

from .web_auth_support import WebAuthSupport

CHAPTER = "class-10-light-reflection-and-refraction"
CONCEPT_A = f"{CHAPTER}-reflection-of-light"
PASSWORD = "correct-horse-battery-staple"


def _catalog():
    """The API-PL-04 payload shape the pages consume (one chapter, source tier)."""
    return {
        "index_version": "fixture-v1",
        "chapters": [
            {
                "chapter_id": CHAPTER,
                "class_level": 10,
                "concepts": [CONCEPT_A],
                "tier": "source",
            }
        ],
    }


class PersonalizedPageSupport(WebAuthSupport):
    """App + client + a seeded chapter/concept pair."""

    def setUp(self) -> None:
        super().setUp()
        # Point the logging fallback at this test's temp dir so the log-scan
        # tests are hermetic and the repo tree never gains a runs/ folder.
        os.environ["ZIVON_RUNS_DIR"] = str(Path(self._tmp.name) / "runs")
        from logging_manager import sink as logging_sink

        logging_sink._jsonl_sink = None  # re-resolve the dir for this test
        self.addCleanup(logging_sink._set_jsonl_sink, None) if hasattr(
            logging_sink, "_set_jsonl_sink"
        ) else None
        self.addCleanup(os.environ.pop, "ZIVON_RUNS_DIR", None)
        self.register_via_api(class_level=10, language="en-IN")
        self.app.state.personalized_index_catalog = _catalog
        self.db.execute(
            "INSERT INTO syllabus_chapter (chapter_id, class_level, subject, chapter_no, "
            "slug, title_en) VALUES (?, 10, 'physics', 10, 'light', "
            "'Light - Reflection and Refraction')",
            (CHAPTER,),
        )
        self.db.execute(
            "INSERT INTO concept (concept_id, chapter_id, slug, title_en, description, "
            "prerequisites, order_index) VALUES (?, ?, 'reflection', 'Reflection of light', "
            "'The two laws of reflection.', '[]', 0)",
            (CONCEPT_A, CHAPTER),
        )
        self.store = PersonalizedStore(self.db)
        self.csrf = self.session_csrf_from_page("/app/personalized")

    def user_id(self) -> str:
        row = self.db.fetchone(
            "SELECT user_id FROM users WHERE email = 'kid@example.com'"
        )
        assert row is not None, "the default registered user must exist"
        return str(row["user_id"])

    def other_client(self):
        """A second signed-in account, for the no-existence-oracle tests."""
        from fastapi.testclient import TestClient

        client = TestClient(self.app, base_url="https://testserver")
        response = client.post(
            "/v1/auth/register",
            json={"email": "other@example.com", "password": PASSWORD},
        )
        self.assertEqual(response.status_code, 201, response.text)
        return client

    def seed_session(self) -> str:
        session = self.store.create_session(
            user_id=self.user_id(),
            chapter_id=CHAPTER,
            class_level=10,
            title="Light - Reflection and Refraction · Reflection of light",
            concept_ids=[CONCEPT_A],
            weakness_text=None,
            skip_diagnostic=True,
        )
        return str(session["session_id"])

    def start(self, **overrides: str):
        """POST the hub start form as the signed-in student (CSRF included)."""
        data = {"csrf_token": self.csrf, "chapter_id": CHAPTER, "mode": "beginning"}
        data.update(overrides)
        return self.client.post(
            "/app/personalized/start", data=data, follow_redirects=False
        )


class HubAccessTests(PersonalizedPageSupport):
    def test_guest_is_sent_to_login_with_the_path_preserved(self) -> None:
        from fastapi.testclient import TestClient

        guest = TestClient(self.app, base_url="https://testserver")
        response = guest.get("/app/personalized", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/login?next=/app/personalized",
        )

    def test_guest_post_to_start_is_guarded_too(self) -> None:
        from fastapi.testclient import TestClient

        guest = TestClient(self.app, base_url="https://testserver")
        response = guest.post(
            "/app/personalized/start",
            data={"chapter_id": CHAPTER},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))

    def test_signed_in_hub_renders_picker_quota_and_empty_state(self) -> None:
        response = self.client.get("/app/personalized")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Learn what's weak", response.text)
        self.assertIn("turns left today", response.text)
        self.assertIn("No sessions yet", response.text)
        self.assertIn(f'value="{CHAPTER}"', response.text)
        self.assertIn("(source only)", response.text)
        self.assertNotIn("zn-", response.text)  # no §10 lesson device

    def test_hub_start_button_is_disabled_without_index_coverage(self) -> None:
        self.app.state.personalized_index_catalog = None
        response = self.client.get("/app/personalized")
        self.assertEqual(response.status_code, 200)
        self.assertIn("study index", response.text)
        disabled = re.findall(
            r"<button[^>]*disabled[^>]*>Start</button>", response.text
        )
        self.assertTrue(disabled, "Start must be disabled without the catalog")

    def test_nav_carries_the_learn_entry(self) -> None:
        response = self.client.get("/app/personalized")
        self.assertIn('href="/app/personalized"', response.text)
        self.assertIn("aria-current", response.text)


class HubSessionsQuotaTests(PersonalizedPageSupport):
    """The daily new-session allowance is spent (cap 0 in the test config)."""

    config_overrides: ClassVar[dict[str, Any]] = {
        "personalized_sessions_per_user_per_day": 0
    }

    def test_exhausted_quota_disables_start_but_keeps_the_form(self) -> None:
        response = self.client.get("/app/personalized")
        self.assertEqual(response.status_code, 200)
        # The sessions allowance (not the turns strip) gates Start, with the
        # honest copy; resume/export/delete of saved sessions stay reachable.
        self.assertIn("new-session allowance", response.text)
        self.assertIn("disabled", response.text)

    def test_start_is_blocked_at_the_allowance_with_honest_copy(self) -> None:
        response = self.client.post(
            "/app/personalized/start",
            data={"csrf_token": self.csrf, "chapter_id": CHAPTER, "mode": "beginning"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("new-session allowance", response.text)
        row = self.db.fetchone(
            "SELECT COUNT(*) AS n FROM personalized_session WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertEqual(int(row["n"]), 0)


class HubKillSwitchTests(PersonalizedPageSupport):
    """`ZIVON_PERSONALIZED_ENABLED=false` is the read-only kill switch."""

    config_overrides: ClassVar[dict[str, Any]] = {"personalized_enabled": False}

    def test_kill_switch_is_a_read_only_history_view(self) -> None:
        response = self.client.get("/app/personalized")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Personalized learning is paused", response.text)
        self.assertIn("No sessions yet", response.text)
        disabled = re.findall(
            r"<button[^>]*disabled[^>]*>Start</button>", response.text
        )
        self.assertTrue(disabled)
        response = self.client.post(
            "/app/personalized/start",
            data={"csrf_token": self.csrf, "chapter_id": CHAPTER, "mode": "beginning"},
        )
        self.assertEqual(response.status_code, 503)


class StartSessionTests(PersonalizedPageSupport):
    def test_start_creates_the_session_and_redirects_to_it(self) -> None:
        response = self.start()
        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        self.assertTrue(location.startswith("/app/personalized/"))
        session_id = location.rsplit("/", 1)[-1]
        session = self.store.get_session(self.user_id(), session_id)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertEqual(session["stage"], "teach")  # skip_diagnostic

    def test_weakness_only_start_uses_the_deterministic_match(self) -> None:
        response = self.start(chapter_id="", weakness="Light reflection basics")
        self.assertEqual(response.status_code, 303)
        location = response.headers["location"]
        session_id = location.rsplit("/", 1)[-1]
        session = self.store.get_session(self.user_id(), session_id)
        assert session is not None
        self.assertEqual(session["chapter_id"], CHAPTER)
        self.assertEqual(session["weakness_text"], "Light reflection basics")

    def test_ambiguous_weakness_is_never_guessed(self) -> None:
        response = self.start(
            chapter_id="", weakness="completely unmatched physics words xyzzy"
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("guess the chapter", response.text)

    def test_missing_input_is_a_field_error(self) -> None:
        response = self.start(chapter_id="", weakness="")
        self.assertEqual(response.status_code, 422)
        self.assertIn("Choose a chapter, or describe what", response.text)

    def test_over_long_weakness_is_rejected(self) -> None:
        response = self.start(weakness="x" * 501)
        self.assertEqual(response.status_code, 422)
        self.assertIn("500 characters", response.text)

    def test_unknown_chapter_is_honest(self) -> None:
        response = self.start(chapter_id="class-10-not-there")
        self.assertEqual(response.status_code, 422)
        self.assertIn("available for teaching yet", response.text)

    def test_concept_from_another_chapter_is_rejected(self) -> None:
        response = self.start(concept_id="class-9-some-concept")
        self.assertEqual(response.status_code, 422)
        self.assertIn("belong to the chosen chapter", response.text)

    def test_csrf_rejection_changes_nothing(self) -> None:
        response = self.start(csrf_token="forged-token")
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)
        row = self.db.fetchone(
            "SELECT COUNT(*) AS n FROM personalized_session WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertEqual(int(row["n"]), 0)


class SessionPageTests(PersonalizedPageSupport):
    def setUp(self) -> None:
        super().setUp()
        self.session_id = self.seed_session()
        store = self.store
        store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="text",
            text=(
                "A concave mirror curves inward. Parallel rays meet at the focus [S1]."
            ),
            payload={
                "schema_version": 1,
                "teaching": {
                    "paragraphs": ["A concave mirror curves inward."],
                    "key_statement": "Parallel rays meet at the focus.",
                },
                "citations": [
                    {"label": "NCERT Class 10 Science, Ch. 10", "locator": "p. 148"}
                ],
                "ungrounded": False,
            },
            client_turn_id="c-teach-1",
        )
        self.check_payload = {
            "check_id": "chk-1",
            "kind": "mcq",
            "question": "Where do parallel rays meet in a concave mirror?",
            "options": [
                {"id": "A", "text": "The centre of curvature"},
                {"id": "B", "text": "The principal focus"},
            ],
            "level": 1,
            "concept_id": CONCEPT_A,
            "source": {"kind": "generated", "item_id": None},
        }
        store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="check",
            payload=self.check_payload,
            answer_key=json.dumps(
                {"kind": "mcq", "option": "B", "explanation": "Focus."}
            ),
            client_turn_id="c-check-1",
        )
        store.append_message(
            session_id=self.session_id,
            role="system_event",
            kind="stage_change",
            payload={
                "from": "teach",
                "to": "check",
                "concept_id": CONCEPT_A,
                "level": 1,
            },
        )

    def test_session_renders_transcript_stage_and_quota(self) -> None:
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("A concave mirror curves inward", response.text)
        self.assertIn(
            "Parallel rays meet at the focus.", response.text
        )  # key statement
        self.assertIn("NCERT Class 10 Science, Ch. 10", response.text)  # citation chip
        self.assertIn("Where do parallel rays meet", response.text)
        self.assertIn("AI-generated practice", response.text)  # §9 meta line
        self.assertIn("turns left today", response.text)
        self.assertIn('name="csrf-token"', response.text)
        self.assertIn("/assets/personalized.js", response.text)
        self.assertIn("/assets/personalized-artifact.js", response.text)

    def test_answer_key_never_reaches_the_page(self) -> None:
        response = self.client.get(f"/app/personalized/{self.session_id}")
        # The stored key (option letter + explanation) is server-only; the
        # option ids themselves are the student's choices, not the key.
        self.assertNotIn("answer_key", response.text)
        self.assertNotIn("Focus.", response.text)

    def test_open_check_disables_teach_actions_with_the_reason(self) -> None:
        response = self.client.get(f"/app/personalized/{self.session_id}")
        # An open check exists: the contract rejects teach-side actions
        # (data-and-api.md §4.6), so the SSR buttons carry the honest reason.
        self.assertIn('data-pl-action="explain_directly"', response.text)
        self.assertIn("Submit the open check first", response.text)
        self.assertIn("data-pl-check-submit", response.text)

    def test_feedback_attaches_to_its_check_card(self) -> None:
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="check_result",
            payload={
                "check_id": "chk-1",
                "correct": False,
                "expected": "B",
                "explanation": "Parallel rays converge at the principal focus.",
                "misconception": "Angle measured from the surface.",
            },
            client_turn_id="c-result-1",
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn("Not yet", response.text)
        self.assertIn("principal focus", response.text)
        self.assertIn('data-check-answered="true"', response.text)

    def test_artifact_ready_card_carries_the_server_issued_src(self) -> None:
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="artifact_ref",
            payload={
                "artifact_id": "abc123def4567890",
                "status": "ready",
                "title": "Concave mirror: move the object",
                "kind": "simulation",
                "src": "/v1/personalized/artifacts/abc123def4567890",
            },
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn("data-artifact-viewer", response.text)
        self.assertIn(
            'data-artifact-src="/v1/personalized/artifacts/abc123def4567890"',
            response.text,
        )
        self.assertIn("Runs isolated", response.text)

    def test_artifact_pending_card_polls_and_never_has_a_src(self) -> None:
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="artifact_ref",
            payload={
                "artifact_id": "pend0000pend0000",
                "status": "pending",
                "title": "Diagram",
            },
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn("Building a visual", response.text)
        pending = response.text.split('data-artifact-id="pend0000pend0000"')[1][:400]
        self.assertIn('data-artifact-src=""', pending)

    def test_artifact_failed_card_shows_the_fallback_note(self) -> None:
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="artifact_ref",
            payload={
                "artifact_id": "fail0000fail0000",
                "status": "failed",
                "title": "Diagram",
                "fallback": {"kind": "text"},
            },
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn(
            "The visual didn't build. Here's the diagram instead.", response.text
        )

    def test_summary_card_renders_mastery_evidence(self) -> None:
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="summary",
            payload={
                "mastery": [
                    {
                        "concept_id": CONCEPT_A,
                        "status": "practising",
                        "attempts": 4,
                        "first_try_correct": 1,
                        "levels_passed": [1, 2],
                    }
                ],
                "turn_count": 9,
            },
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn("Mastery summary", response.text)
        self.assertIn("Practising", response.text)
        self.assertIn("first-try correct 1", response.text)

    def test_other_users_session_is_a_404_not_a_403(self) -> None:
        other = self.other_client()
        response = other.get(f"/app/personalized/{self.session_id}")
        self.assertEqual(response.status_code, 404)
        self.assertIn("Session not found", response.text)

    def test_unknown_session_id_is_a_404(self) -> None:
        response = self.client.get("/app/personalized/does-not-exist")
        self.assertEqual(response.status_code, 404)

    def test_end_session_completes_and_is_reversible_to_read_only(self) -> None:
        response = self.client.post(
            f"/app/personalized/{self.session_id}/end",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("ended=1", response.headers["location"])
        session = self.store.get_session(self.user_id(), self.session_id)
        assert session is not None
        self.assertEqual(session["status"], "completed")
        page = self.client.get(f"/app/personalized/{self.session_id}?ended=1")
        self.assertIn("This session is finished", page.text)
        self.assertNotIn("data-pl-composer", page.text)

    def test_end_without_csrf_changes_nothing(self) -> None:
        response = self.client.post(
            f"/app/personalized/{self.session_id}/end", data={"csrf_token": "bad"}
        )
        self.assertEqual(response.status_code, 403)
        session = self.store.get_session(self.user_id(), self.session_id)
        assert session is not None
        self.assertEqual(session["status"], "active")

    def test_at_cap_session_offers_the_linked_continue(self) -> None:
        self.db.execute(
            "UPDATE personalized_session SET turn_count = 60 WHERE session_id = ?",
            (self.session_id,),
        )
        response = self.client.get(f"/app/personalized/{self.session_id}")
        self.assertIn("Continue in a new session", response.text)
        self.assertIn(
            f'name="parent_session_id" value="{self.session_id}"', response.text
        )
        # Starting from the cap form links the new session (display-only).
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
        assert match is not None
        csrf = match.group(1)
        start = self.client.post(
            "/app/personalized/start",
            data={
                "csrf_token": csrf,
                "parent_session_id": self.session_id,
                "chapter_id": CHAPTER,
                "mode": "beginning",
            },
            follow_redirects=False,
        )
        self.assertEqual(start.status_code, 303)
        new_id = start.headers["location"].rsplit("/", 1)[-1]
        new_session = self.store.get_session(self.user_id(), new_id)
        assert new_session is not None
        self.assertEqual(new_session["parent_session_id"], self.session_id)
        # ...and nothing carried over (the link is display-only, §2.6).
        self.assertEqual(int(new_session["turn_count"]), 0)
        self.assertEqual(new_session["stage"], "teach")

    def test_delete_removes_the_session_and_messages(self) -> None:
        response = self.client.post(
            f"/app/personalized/{self.session_id}/delete",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("saved=deleted", response.headers["location"])
        self.assertIsNone(self.store.get_session(self.user_id(), self.session_id))
        row = self.db.fetchone(
            "SELECT COUNT(*) AS n FROM personalized_message WHERE session_id = ?",
            (self.session_id,),
        )
        assert row is not None
        self.assertEqual(int(row["n"]), 0)

    def test_delete_of_another_users_session_is_a_404(self) -> None:
        other = self.other_client()
        match = re.search(
            r'name="csrf_token" value="([^"]+)"',
            other.get("/app/personalized").text,
        )
        assert match is not None
        other_csrf = match.group(1)
        response = other.post(
            f"/app/personalized/{self.session_id}/delete",
            data={"csrf_token": other_csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 404)
        # The owner's session is untouched.
        self.assertIsNotNone(self.store.get_session(self.user_id(), self.session_id))

    def test_history_rows_carry_continue_export_delete(self) -> None:
        response = self.client.get("/app/personalized")
        self.assertIn(f'href="/app/personalized/{self.session_id}"', response.text)
        self.assertIn(
            f'href="/v1/personalized/sessions/{self.session_id}/export"', response.text
        )
        self.assertIn(
            f'action="/app/personalized/{self.session_id}/delete"', response.text
        )

    def test_delete_soon_warning_at_83_days(self) -> None:
        # 83 days old → inside the 7-day warning window (D-PL-05).
        import datetime

        stamp = (
            datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=83)
        ).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        self.db.execute(
            "UPDATE personalized_session SET last_turn_at = ? WHERE session_id = ?",
            (stamp, self.session_id),
        )
        response = self.client.get("/app/personalized")
        self.assertIn("Deletes in 7 days", response.text)


class ResumeWebTests(PersonalizedPageSupport):
    """The hub's real Resume action and the cap-exhausted honest state
    (API-PL-16 through the HTML route; `docs/specs/frontend/personalized.md`
    §2/§3/§6)."""

    def setUp(self) -> None:
        super().setUp()
        self.session_id = self.seed_session()
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="text",
            text=(
                "A concave mirror curves inward. Parallel rays meet at the focus [S1]."
            ),
            payload={
                "schema_version": 1,
                "teaching": {
                    "paragraphs": ["A concave mirror curves inward."],
                    "key_statement": "Parallel rays meet at the focus.",
                },
                "citations": [
                    {"label": "NCERT Class 10 Science, Ch. 10", "locator": "p. 148"}
                ],
                "ungrounded": False,
            },
            client_turn_id="c-teach-1",
        )
        self.store.append_message(
            session_id=self.session_id,
            role="tutor",
            kind="check",
            payload={
                "check_id": "chk-1",
                "kind": "mcq",
                "question": "Where do parallel rays meet in a concave mirror?",
                "options": [
                    {"id": "A", "text": "The centre of curvature"},
                    {"id": "B", "text": "The principal focus"},
                ],
                "level": 1,
                "concept_id": CONCEPT_A,
                "source": {"kind": "generated", "item_id": None},
            },
            answer_key='{"kind": "mcq", "option": "B"}',
            client_turn_id="c-check-1",
        )

    def _completed_session(self) -> str:
        self.store.end_session(self.user_id(), self.session_id)
        return self.session_id

    def _cap_exhausted_session(self) -> str:
        self._completed_session()
        # The runtime path: the turn engine persists the count inside state.
        self.db.execute(
            "UPDATE personalized_session SET state = ? WHERE session_id = ?",
            ('{"schema_version": 1, "turn_count": 60}', self.session_id),
        )
        return self.session_id

    def test_hub_completed_row_offers_a_real_resume_form(self) -> None:
        session_id = self._completed_session()
        html = self.client.get("/app/personalized").text
        self.assertIn(f'action="/app/personalized/{session_id}/resume"', html)
        self.assertIn(">Resume</button>", html)
        self.assertNotIn("Continue</a>", html.split("pl-session-actions")[1])

    def test_hub_resume_post_reopens_and_lands_on_the_session(self) -> None:
        session_id = self._completed_session()
        response = self.client.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"], f"/app/personalized/{session_id}?resumed=1"
        )
        session = self.store.get_session(self.user_id(), session_id)
        assert session is not None
        self.assertEqual(session["status"], "active")
        self.assertIsNone(session["completed_at"])

    def test_session_page_after_resume_shows_the_truthful_flash(self) -> None:
        session_id = self._completed_session()
        self.client.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": self.csrf},
        )
        page = self.client.get(f"/app/personalized/{session_id}?resumed=1")
        self.assertIn("Session reopened. Pick up where you left off.", page.text)
        self.assertIn("data-pl-composer", page.text)

    def test_finished_session_notice_offers_resume(self) -> None:
        session_id = self._completed_session()
        page = self.client.get(f"/app/personalized/{session_id}")
        self.assertIn("This session is finished", page.text)
        self.assertIn(f'action="/app/personalized/{session_id}/resume"', page.text)
        self.assertIn("Resume session", page.text)
        self.assertNotIn("data-pl-composer", page.text)

    def test_web_resume_without_csrf_changes_nothing(self) -> None:
        session_id = self._completed_session()
        response = self.client.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": "forged"},
        )
        self.assertEqual(response.status_code, 403)
        self.assertIn("This form expired", response.text)
        session = self.store.get_session(self.user_id(), session_id)
        assert session is not None
        self.assertEqual(session["status"], "completed")

    def test_web_resume_guest_is_guarded_and_other_owner_is_404(self) -> None:
        session_id = self._completed_session()
        guest = self.other_client()
        # The other account's own CSRF token, extracted from its own hub page:
        other_page = guest.get("/app/personalized").text
        other_csrf = re.search(r'name="csrf_token" value="([^"]+)"', other_page)
        assert other_csrf is not None
        response = guest.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": other_csrf.group(1)},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 404)
        self.assertIn("Session not found", response.text)
        from fastapi.testclient import TestClient

        stranger = TestClient(self.app, base_url="https://testserver")
        guarded = stranger.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": "x"},
            follow_redirects=False,
        )
        self.assertEqual(guarded.status_code, 303)
        self.assertTrue(guarded.headers["location"].startswith("/login?next="))

    def test_web_resume_of_an_active_session_shows_it_without_false_flash(self) -> None:
        session_id = self.seed_session()  # active
        response = self.client.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"], f"/app/personalized/{session_id}"
        )

    def test_cap_exhausted_hub_row_explains_start_new_instead_of_resume(self) -> None:
        session_id = self._cap_exhausted_session()
        html = self.client.get("/app/personalized").text
        self.assertIn("Used all 60 turns", html)
        self.assertIn("Continue in a new session", html)
        self.assertIn(f'name="parent_session_id" value="{session_id}"', html)
        self.assertNotIn(">Resume</button>", html)
        # The linked start-new path works from the hub (display-only link).
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        assert match is not None
        start = self.client.post(
            "/app/personalized/start",
            data={
                "csrf_token": match.group(1),
                "parent_session_id": session_id,
                "chapter_id": CHAPTER,
                "mode": "beginning",
            },
            follow_redirects=False,
        )
        self.assertEqual(start.status_code, 303)

    def test_cap_exhausted_session_page_shows_start_new_no_composer(self) -> None:
        session_id = self._cap_exhausted_session()
        page = self.client.get(f"/app/personalized/{session_id}")
        self.assertIn("used all 60 turns", page.text)
        self.assertIn("Continue in a new session", page.text)
        self.assertNotIn("data-pl-composer", page.text)
        self.assertNotIn('/resume"', page.text)
        # The transcript (and the mastery summary when present) stays readable.
        self.assertIn("A concave mirror curves inward", page.text)

    def test_hub_cap_flash_after_a_refused_resume_is_truthful(self) -> None:
        self._cap_exhausted_session()
        response = self.client.post(
            "/app/personalized/whatever/resume",
            data={"csrf_token": self.csrf},
            follow_redirects=False,
        )
        # A non-owned id is a 404 before any cap logic runs.
        self.assertEqual(response.status_code, 404)
        hub = self.client.get("/app/personalized?resume=cap")
        self.assertIn("That session used all 60 turns", hub.text)
        self.assertIn("Start a new session", hub.text)

    def test_resume_keeps_the_transcript_readable_after_reopen(self) -> None:
        session_id = self._completed_session()
        self.client.post(
            f"/app/personalized/{session_id}/resume",
            data={"csrf_token": self.csrf},
        )
        page = self.client.get(f"/app/personalized/{session_id}")
        self.assertIn("A concave mirror curves inward", page.text)
        self.assertIn("Where do parallel rays meet", page.text)
        self.assertIn("Session", page.text)  # the stage tag renders


class SettingsInstructionsTests(PersonalizedPageSupport):
    def section(self) -> str:
        return self.client.get("/app/settings").text

    def test_settings_renders_the_instructions_section(self) -> None:
        html = self.section()
        self.assertIn("How I like to learn", html)
        self.assertIn('id="pl-instructions"', html)
        self.assertIn('name="personal_instructions"', html)
        self.assertIn('maxlength="500"', html)
        self.assertIn("/500 characters", html)
        self.assertIn("What this can't do", html)
        self.assertIn('action="/app/settings/instructions"', html)
        self.assertIn("No preferences yet", html)
        # label/for pairing for the field (identity-settings.md §7 rule)
        self.assertIn('<label for="pl-instructions">', html)

    def test_save_persists_and_shows_the_status_line(self) -> None:
        response = self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "Explain step by step. Use Hinglish.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "Saved. Zivon will use this from your next question.", response.text
        )
        self.assertIn("Explain step by step. Use Hinglish.", response.text)
        row = self.db.fetchone(
            "SELECT personal_instructions, instructions_version FROM user_preferences "
            "WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertEqual(
            row["personal_instructions"], "Explain step by step. Use Hinglish."
        )
        self.assertEqual(int(row["instructions_version"]), 1)

    def test_save_over_the_limit_rejects_and_keeps_the_old_value(self) -> None:
        self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "first value",
            },
        )
        response = self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "x" * 501,
            },
            follow_redirects=True,
        )
        self.assertIn("nothing was saved", response.text)
        row = self.db.fetchone(
            "SELECT personal_instructions FROM user_preferences WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertEqual(row["personal_instructions"], "first value")

    def test_contact_details_are_rejected_with_the_honest_copy(self) -> None:
        response = self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "call me on 98765 43210",
            },
            follow_redirects=True,
        )
        self.assertIn("That looks like a personal detail", response.text)
        row = self.db.fetchone(
            "SELECT personal_instructions FROM user_preferences WHERE user_id = ?",
            (self.user_id(),),
        )
        # A first save that is rejected leaves no row at all: nothing written.
        self.assertIsNone(row)

    def test_clear_empties_the_field_and_reports_it(self) -> None:
        self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "keep it short",
            },
        )
        response = self.client.post(
            "/app/settings/instructions",
            data={"csrf_token": self.csrf, "intent": "clear"},
            follow_redirects=True,
        )
        self.assertIn("Cleared. Lessons use the default style again.", response.text)
        self.assertIn("No preferences yet", response.text)
        row = self.db.fetchone(
            "SELECT personal_instructions, instructions_version FROM user_preferences "
            "WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertIsNone(row["personal_instructions"])
        self.assertEqual(int(row["instructions_version"]), 2)

    def test_csrf_rejection_changes_nothing(self) -> None:
        self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "before",
            },
        )
        response = self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": "forged",
                "intent": "save",
                "personal_instructions": "after",
            },
        )
        self.assertEqual(response.status_code, 403)
        row = self.db.fetchone(
            "SELECT personal_instructions FROM user_preferences WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        self.assertEqual(row["personal_instructions"], "before")

    def test_guest_post_is_guarded(self) -> None:
        from fastapi.testclient import TestClient

        guest = TestClient(self.app, base_url="https://testserver")
        response = guest.post(
            "/app/settings/instructions",
            data={"intent": "save", "personal_instructions": "x"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers["location"].startswith("/login?next="))


class StartTitleTests(PersonalizedPageSupport):
    """The hub-generated title is honest chapter/concept wording
    (data-and-api.md §4.4's example shape), never a raw id."""

    def test_title_uses_the_concept_title_not_the_raw_id(self) -> None:
        response = self.start(concept_id=CONCEPT_A)
        self.assertEqual(response.status_code, 303)
        session_id = response.headers["location"].rsplit("/", 1)[-1]
        session = self.store.get_session(self.user_id(), session_id)
        assert session is not None
        self.assertEqual(
            session["title"],
            "Light - Reflection and Refraction · Reflection of light",
        )
        self.assertNotIn(CONCEPT_A, session["title"])

    def test_title_without_a_concept_is_the_chapter_title(self) -> None:
        response = self.start()
        self.assertEqual(response.status_code, 303)
        session_id = response.headers["location"].rsplit("/", 1)[-1]
        session = self.store.get_session(self.user_id(), session_id)
        assert session is not None
        self.assertEqual(session["title"], "Light - Reflection and Refraction")


class StorageFailureTests(PersonalizedPageSupport):
    """A storage failure on an HTML write route degrades to the honest HTML
    state — the 503 page or the `instructions_error=unavailable` redirect —
    never the JSON 500 envelope (docs/specs/frontend/personalized.md §1 and
    the §6.4 error row)."""

    def test_start_store_failure_is_the_503_page(self) -> None:
        with mock.patch("web.routes.personalized.PersonalizedStore") as failing:
            failing.return_value.match_chapter_by_weakness.side_effect = RuntimeError(
                "store down"
            )
            response = self.start(chapter_id="", weakness="Light reflection basics")
        self.assertEqual(response.status_code, 503)
        self.assertIn("Personalized learning is unavailable right now", response.text)

    def test_start_create_failure_is_the_503_page(self) -> None:
        with mock.patch("web.routes.personalized.PersonalizedStore") as failing:
            failing.return_value.create_session.side_effect = RuntimeError("store down")
            response = self.start()
        self.assertEqual(response.status_code, 503)
        self.assertIn("Personalized learning is unavailable right now", response.text)

    def test_delete_store_failure_is_the_503_page(self) -> None:
        session_id = self.seed_session()
        with mock.patch("web.routes.personalized.PersonalizedStore") as failing:
            failing.return_value.delete_session.side_effect = RuntimeError("store down")
            response = self.client.post(
                f"/app/personalized/{session_id}/delete",
                data={"csrf_token": self.csrf},
                follow_redirects=False,
            )
        self.assertEqual(response.status_code, 503)
        # The failed delete changed nothing: the session still exists.
        self.assertIsNotNone(self.store.get_session(self.user_id(), session_id))

    def test_instructions_save_store_failure_redirects_unavailable(self) -> None:
        with mock.patch(
            "web.routes.personalized.save_preferences",
            side_effect=RuntimeError("store down"),
        ):
            response = self.client.post(
                "/app/settings/instructions",
                data={
                    "csrf_token": self.csrf,
                    "intent": "save",
                    "personal_instructions": "explain slowly",
                },
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("your learning preferences are unchanged", response.text)

    def test_instructions_clear_store_failure_redirects_unavailable(self) -> None:
        self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": "keep it short",
            },
        )
        with mock.patch(
            "web.routes.personalized.clear_preferences",
            side_effect=RuntimeError("store down"),
        ):
            response = self.client.post(
                "/app/settings/instructions",
                data={"csrf_token": self.csrf, "intent": "clear"},
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("your learning preferences are unchanged", response.text)
        row = self.db.fetchone(
            "SELECT personal_instructions FROM user_preferences WHERE user_id = ?",
            (self.user_id(),),
        )
        assert row is not None
        # The failed clear changed nothing.
        self.assertEqual(row["personal_instructions"], "keep it short")


class PrivacyLogTests(PersonalizedPageSupport):
    def test_student_text_never_enters_the_log_sink(self) -> None:
        """The C22/C23 redaction rule (data-and-api.md §1): saving preferences
        and starting a session writes counts-only events — the student's words
        appear in no log line."""
        marker = "QUOKKA-SECRET-BAKERY-42"
        self.client.post(
            "/app/settings/instructions",
            data={
                "csrf_token": self.csrf,
                "intent": "save",
                "personal_instructions": f"explain slowly please {marker}",
            },
        )
        self.client.post(
            "/app/personalized/start",
            data={
                "csrf_token": self.csrf,
                "chapter_id": CHAPTER,
                "weakness": f"why is {marker} blurry",
            },
            follow_redirects=False,
        )
        logs_dir = Path(self.cfg.runs_dir) / "logs"
        seen_events: set[str] = set()
        for path in logs_dir.glob("*.jsonl"):
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                seen_events.add(str(entry.get("event")))
                blob = json.dumps(entry)
                self.assertNotIn(marker, blob, f"student text leaked into {path.name}")
        self.assertIn("personalized.prefs.saved", seen_events)
        self.assertIn("personalized.session.created", seen_events)


class AccessibilityTests(PersonalizedPageSupport):
    def test_each_page_has_exactly_one_h1(self) -> None:
        for path in ("/app/personalized", "/app/settings"):
            html = self.client.get(path).text
            self.assertEqual(len(re.findall(r"<h1", html)), 1, path)

    def test_session_page_has_one_h1_and_the_live_region(self) -> None:
        session_id = self.seed_session()
        html = self.client.get(f"/app/personalized/{session_id}").text
        self.assertEqual(len(re.findall(r"<h1", html)), 1)
        self.assertIn("data-pl-live", html)
        self.assertIn('aria-live="polite"', html)
        self.assertIn('role="status"', html)

    def test_hub_inputs_have_labels(self) -> None:
        html = self.client.get("/app/personalized").text
        for input_id in ("pl-chapter", "pl-concept", "pl-weakness"):
            self.assertIn(f'<label for="{input_id}"', html)
            self.assertIn(f'id="{input_id}"', html)

    def test_session_page_has_no_inline_script_or_lesson_device(self) -> None:
        session_id = self.seed_session()
        html = self.client.get(f"/app/personalized/{session_id}").text
        self.assertNotIn("<script>", html)
        self.assertNotIn("zn-lang-bar", html)
        self.assertNotIn("zn-sim-", html)

    def test_templates_extend_the_shell_and_partials_do_not(self) -> None:
        hub = (Path("web/templates/app/personalized_hub.html")).read_text(
            encoding="utf-8"
        )
        session = (Path("web/templates/app/personalized_session.html")).read_text(
            encoding="utf-8"
        )
        partial = (
            Path("web/templates/app/partials/personal_instructions.html")
        ).read_text(encoding="utf-8")
        self.assertIn('{% extends "base.html" %}', hub)
        self.assertIn('{% extends "base.html" %}', session)
        self.assertNotIn("{% extends", partial)
