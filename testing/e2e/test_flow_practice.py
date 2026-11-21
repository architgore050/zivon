"""Flow 4 (§17.1): practice — attempt -> submit -> review, honest key
withholding, the no-JS web-form path, idempotent completion, and the
progress/dashboard update after submit.

The bank is the REAL imported assessment pack; grading happens server-side
from the stored key (`Question.public()` withholds it until the student
commits), and the JSON API and the no-JS web form run the same domain
functions — there is no second grading path.
"""

from __future__ import annotations

import re
from typing import Any

from db.uuid7 import uuid7_str

from .support import MOTION, E2EFlow


class PracticeFlowTests(E2EFlow):
    """One chapter drill through its whole lifecycle, API and web form."""

    def setUp(self) -> None:
        super().setUp()
        created = self.client.post(
            "/v1/practice/sessions",
            json={"mode": "chapter", "chapter_id": MOTION},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.practice_id = str(created.json()["session"]["session_id"])

    def state(self) -> dict[str, Any]:
        response = self.client.get(f"/v1/practice/sessions/{self.practice_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer_current(self, *, correct: bool) -> dict[str, Any]:
        state = self.state()
        question = state["question"]
        self.assertTrue(question, "the player holds an unanswered question")
        response = self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/answers",
            json={
                "question_id": question["question_id"],
                "answer": self.correct_answer(question["question_id"])
                if correct
                else self.wrong_answer(question["question_id"]),
                "time_ms": 4_000,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer_everything(self, *, correct_every: int) -> list[dict[str, Any]]:
        """Answer the whole set in order; the first `correct_every` are right."""
        results: list[dict[str, Any]] = []
        for index in range(self.state()["question_count"]):
            results.append(self.answer_current(correct=index < correct_every))
        return results

    # -- the chain -------------------------------------------------------------

    def test_attempt_submit_review_shows_the_working(self) -> None:
        results = self.answer_everything(correct_every=7)
        self.assertTrue(results[0]["feedback"]["correct"], "a keyed answer grades 1")
        self.assertFalse(results[-1]["feedback"]["correct"], "a wrong answer grades 0")
        self.assertIn("answer", results[0]["feedback"], "the key unlocks after commit")
        self.assertTrue(
            results[0]["feedback"]["explanation"], "the working ships with the key"
        )
        complete = self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/complete",
            headers=self.headers(),
        )
        self.assertEqual(complete.status_code, 200, complete.text)
        summary = complete.json()["summary"]
        self.assertEqual(summary["answered_count"], 10)
        self.assertEqual(summary["correct_count"], 7)
        self.assertEqual(summary["accuracy_pct"], 70.0)
        page = self.page(f"/app/practice/{self.practice_id}/summary")
        self.assertIn("You answered 7 of 10 correctly", page)
        self.assertIn("Where the marks came from", page)

    def test_key_is_withheld_until_commit(self) -> None:
        state = self.state()
        question = state["question"]
        self.assertNotIn("answer", question, "the key never leaves the server first")
        self.assertNotIn("explanation", question)
        self.assertNotIn("misconception", question)
        answered = self.answer_current(correct=True)
        self.assertIn("answer", answered["feedback"])
        self.assertIn("explanation", answered["feedback"])
        after = self.state()
        self.assertEqual(after["answered_count"], 1)
        # The web player is the review surface: `?answered=` re-renders the
        # committed question WITH the key, while the next one withholds again.
        review = self.client.get(
            f"/app/practice/{self.practice_id}?answered={question['question_id']}"
        )
        self.assertEqual(review.status_code, 200, review.text[:300])
        self.assertIn("The answer is", review.text, "the key is on the review")
        current = self.state()["question"]
        self.assertNotIn("answer", current, "the NEXT question withholds the key again")

    # -- the no-JS path ---------------------------------------------------------

    def test_no_js_web_form_path(self) -> None:
        browser = self.guest_client()
        self.signup_via_web(f"web-{uuid7_str()}@example.com", client=browser)
        hub = browser.get("/app/practice")
        self.assertEqual(hub.status_code, 200, hub.text)
        token = self.csrf_from_page("/app/practice", client=browser)
        started = browser.post(
            "/app/practice/start",
            data={"csrf_token": token, "mode": "chapter", "chapter_id": MOTION},
            follow_redirects=False,
        )
        self.assertEqual(started.status_code, 303, started.text)
        self.assertRegex(started.headers["location"], r"^/app/practice/[0-9a-f-]+$")
        player_id = started.headers["location"].rsplit("/", 1)[1]

        player = browser.get(f"/app/practice/{player_id}")
        self.assertEqual(player.status_code, 200, player.text)
        question_id = re.search(r'name="question_id" value="([^"]+)"', player.text)
        self.assertIsNotNone(question_id, "the form carries the question id")
        assert question_id is not None
        form_token = self.csrf_from_page(f"/app/practice/{player_id}", client=browser)
        qid = question_id.group(1)
        with_answer = self.correct_answer(qid)
        answer_value = (
            str(with_answer["index"])
            if "index" in with_answer
            else str(with_answer["value"])
        )
        field = "answer_index" if "index" in with_answer else "answer_value"
        checked = browser.post(
            f"/app/practice/{player_id}/answer",
            data={
                "csrf_token": form_token,
                "question_id": qid,
                field: answer_value,
            },
            follow_redirects=False,
        )
        self.assertEqual(checked.status_code, 303, checked.text)
        self.assertIn(f"answered={qid}", checked.headers["location"])
        review = browser.get(f"/app/practice/{player_id}?answered={qid}")
        self.assertEqual(review.status_code, 200, review.text)
        self.assertIn("Correct.", review.text, "the graded verdict is on the page")
        complete_token = self.csrf_from_page(
            f"/app/practice/{player_id}", client=browser
        )
        done = browser.post(
            f"/app/practice/{player_id}/complete",
            data={"csrf_token": complete_token},
            follow_redirects=False,
        )
        self.assertEqual(done.status_code, 303, done.text)
        summary = browser.get(f"/app/practice/{player_id}/summary")
        self.assertIn("You answered 1 of", summary.text)

    # -- completion ---------------------------------------------------------------

    def test_complete_is_idempotent(self) -> None:
        results = self.answer_everything(correct_every=10)
        last_question = str(results[-1]["feedback"]["question_id"])
        first = self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/complete",
            headers=self.headers(),
        )
        self.assertEqual(first.status_code, 200, first.text)
        second = self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/complete",
            headers=self.headers(),
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(
            first.json()["summary"]["score"],
            second.json()["summary"]["score"],
            "completing twice keeps one graded result",
        )
        self.assertEqual(second.json()["summary"]["accuracy_pct"], 100.0)
        closed = self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/answers",
            json={
                "question_id": last_question,
                "answer": {"index": 0},
                "time_ms": 1_000,
            },
            headers=self.headers(),
        )
        self.assertEqual(closed.status_code, 409, closed.text)
        self.assertEqual(closed.json()["code"], "E-CONFLICT")

    def test_progress_and_history_update_after_submit(self) -> None:
        self.answer_everything(correct_every=10)
        self.client.post(
            f"/v1/practice/sessions/{self.practice_id}/complete",
            headers=self.headers(),
        )
        summary = self.client.get("/v1/progress/summary").json()
        self.assertGreaterEqual(
            int(summary["counts"]["practice_answers_7d"]),
            10,
            "every first attempt feeds F3 progress",
        )
        history = self.client.get("/v1/practice/history").json()
        self.assertEqual(history["count"], 1)
        entry = history["items"][0]
        self.assertEqual(entry["mode"], "chapter")
        self.assertEqual(float(entry["score"]), 100.0)
        self.assertTrue(entry["completed_at"], "the set is closed")
        page = self.page("/app/practice/history")
        self.assertIn("Chapter drill", page)
        self.assertIn("100%", page)
        # The dashboard greeting page reads the same evidence: no invented
        # activity, but the real practice rows are not hidden either.
        dashboard = self.page("/app")
        self.assertIn("Practice", dashboard)


__all__ = ["PracticeFlowTests"]
