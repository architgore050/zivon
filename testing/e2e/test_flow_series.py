"""Flow 7 (§17.1): series — choose -> language rules -> results feed SWOT.

The series data is seeded through the REAL E4 importer
(`scripts/import_series_packs.py`) over the synthetic Class-10 pack fixture,
after the REAL assessment importer seeds the bank — the production order.
"""

from __future__ import annotations

from .support import SERIES_FIXTURE_DIR, E2EFlow, load_script


class SeriesFlowTests(E2EFlow):
    """The six-series catalogue with one imported live paper."""

    series_importer = None

    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        cls.series_importer = load_script(
            "import_series_packs_e2e", "import_series_packs.py"
        )
        cls.series_importer.import_packs(cls.db, SERIES_FIXTURE_DIR)

    def setUp(self) -> None:
        super().setUp()
        # A class-10 account sees live/pending cards; the class-9 default does not.
        patch = self.client.patch(
            "/v1/me",
            json={"class_level": 10},
            headers=self.headers(),
        )
        self.assertEqual(patch.status_code, 200, patch.text)
        self.session = self.client.get("/v1/auth/session").json()
        self.csrf = str(self.session["csrf_token"])

    def test_series_cards_are_honest_about_live_pending_dark(self) -> None:
        response = self.client.get("/v1/series")
        self.assertEqual(response.status_code, 200, response.text)
        cards = {card["kind"]: card for card in response.json()["cards"]}
        self.assertEqual(len(cards), 6)
        self.assertEqual(cards["exact_pyq"]["status"], "disabled", "DEC-COMP-001")
        self.assertIn(
            cards["board_practice"]["status"],
            ("live", "pending"),
            "the imported fixture paper decides",
        )
        page = self.page("/app/series")
        self.assertIn("The six series", page)

    def test_language_rules_offer_each_pack_language(self) -> None:
        detail = self.client.get("/v1/series/board-practice")
        self.assertEqual(detail.status_code, 200, detail.text)
        payload = detail.json()
        self.assertEqual(payload["definition"]["kind"], "board_practice")
        for paper in payload["papers"]:
            self.assertIn(paper["language"], ("en", "hi", "hi-Latn"))

    def test_choose_start_submit_records_graded_results(self) -> None:
        detail = self.client.get("/v1/series/board-practice").json()
        papers = [p for p in detail["papers"] if p["language"] == "en"]
        self.assertTrue(papers, "an English paper is offered")
        test_id = papers[0]["test_id"]
        started = self.client.post(
            f"/v1/tests/{test_id}/attempts", headers=self.headers()
        )
        self.assertEqual(started.status_code, 201, started.text)
        attempt_id = started.json()["attempt"]["attempt_id"]
        state = self.client.get(f"/v1/tests/attempts/{attempt_id}").json()
        self.assertEqual(state["series"]["kind"], "board_practice")
        for question in state["questions"]:
            self.client.patch(
                f"/v1/tests/attempts/{attempt_id}/answers",
                json={
                    "question_id": question["question_id"],
                    "answer": self.correct_answer(question["question_id"]),
                    "time_ms": 2000,
                },
                headers=self.headers(),
            )
        submit = self.client.post(
            f"/v1/tests/attempts/{attempt_id}/submit", headers=self.headers()
        )
        self.assertEqual(submit.status_code, 200, submit.text)
        review_page = self.page(f"/app/tests/{attempt_id}/review")
        self.assertIn("Every question, with the working", review_page)
        rows = self.db.fetchall(
            "SELECT kind FROM progress_event WHERE user_id = ? AND kind = 'test_submit'",
            (self.session["user"]["user_id"],),
        )
        self.assertTrue(rows, "the graded submit feeds F3 progress")
