"""Flow 6 (§17.1): test — start -> autosave -> resume -> submit -> score ->
review, over the real imported bank with server-side grading."""

from __future__ import annotations

from .support import MOTION, E2EFlow


class TestAttemptFlowTests(E2EFlow):
    """One custom paper through its whole lifecycle."""

    def setUp(self) -> None:
        super().setUp()
        created = self.client.post(
            "/v1/tests/custom",
            json={"chapter_ids": [MOTION], "count": 5, "duration_s": 600},
            headers=self.headers(),
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.test_id = created.json()["test"]["test_id"]
        started = self.client.post(
            f"/v1/tests/{self.test_id}/attempts", headers=self.headers()
        )
        self.assertEqual(started.status_code, 201, started.text)
        self.attempt_id = started.json()["attempt"]["attempt_id"]

    def state(self) -> dict:
        response = self.client.get(f"/v1/tests/attempts/{self.attempt_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def answer(self, question_id: str, *, correct: bool) -> None:
        response = self.client.patch(
            f"/v1/tests/attempts/{self.attempt_id}/answers",
            json={
                "question_id": question_id,
                "answer": self.correct_answer(question_id)
                if correct
                else self.wrong_answer(question_id),
                "time_ms": 1500,
            },
            headers=self.headers(),
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_autosave_never_grades_and_resume_keeps_the_attempt(self) -> None:
        questions = self.state()["questions"]
        first = questions[0]["question_id"]
        self.answer(first, correct=True)
        saved = self.state()["answers"][first]
        self.assertIsNone(saved["correct"], "autosave must not grade")
        resumed = self.client.post(
            f"/v1/tests/{self.test_id}/attempts", headers=self.headers()
        ).json()
        self.assertEqual(resumed["attempt"]["attempt_id"], self.attempt_id)
        self.assertTrue(resumed["resumed"])

    def test_review_is_withheld_until_submit(self) -> None:
        response = self.client.get(f"/v1/tests/attempts/{self.attempt_id}/review")
        self.assertEqual(response.status_code, 409, "the key stays withheld")
        page = self.client.get(
            f"/app/tests/{self.attempt_id}/review", follow_redirects=False
        )
        self.assertEqual(page.status_code, 303, "sent back to the player")

    def test_submit_scores_server_side_and_review_shows_keys(self) -> None:
        questions = self.state()["questions"]
        self.answer(questions[0]["question_id"], correct=True)
        self.answer(questions[1]["question_id"], correct=True)
        self.answer(questions[2]["question_id"], correct=False)
        submit = self.client.post(
            f"/v1/tests/attempts/{self.attempt_id}/submit", headers=self.headers()
        )
        self.assertEqual(submit.status_code, 200, submit.text)
        review = submit.json()["review"]
        self.assertEqual(review["summary"]["earned"], 2.0)
        self.assertEqual(review["summary"]["possible"], 5.0)
        self.assertEqual(review["summary"]["score"], 40.0)

        second = self.client.post(
            f"/v1/tests/attempts/{self.attempt_id}/submit", headers=self.headers()
        )
        self.assertEqual(second.status_code, 200, second.text)
        self.assertEqual(
            second.json()["review"]["summary"]["score"],
            40.0,
            "idempotent submit keeps the graded result",
        )

        page = self.page(f"/app/tests/{self.attempt_id}/review")
        self.assertIn("Every question, with the working", page)
        self.assertIn("Why", page)
        hub = self.page("/app/tests")
        self.assertIn("40%", hub, "the hub recent list shows the graded score")
