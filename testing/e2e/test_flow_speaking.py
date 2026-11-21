"""Flow 5 (§17.1): speaking (explain-back) — capture, consent gate, prompts,
text-only persistence, history, and the honest 503.

The vendor seam is `app.state.speaking`: `pipeline_for(app)` returns whatever
is mounted there, so a `SpeakingPipelineDouble` stands in for Prisma STT and
the tutor brain — no network, no key, no vendor. The route under test is the
REAL one: consent re-check, quota, transient upload bounds, rubric mapping,
and text-only persistence all run unmodified.
"""

from __future__ import annotations

import uuid

from .support import MOTION, PROMPT_ID, E2EFlow


class SpeakingFlowTests(E2EFlow):
    """The explain-back loop end to end with the vendor seam doubled."""

    def setUp(self) -> None:
        super().setUp()
        self.double = self.attach_speaking_double()
        self.grant_consent()

    # -- capture -------------------------------------------------------------

    def test_capture_happy_path_saves_transcript_and_rubric(self) -> None:
        response = self.post_speaking_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertFalse(payload["mock"], "a real (doubled) pipeline is not demo mode")
        self.assertIsNone(payload["evaluation_error"])
        attempt = payload["attempt"]
        self.assertEqual(attempt["transcript"], self.double.transcript_text)
        self.assertEqual(attempt["prompt_id"], PROMPT_ID)
        self.assertEqual(int(attempt["duration_ms"]), 2000)
        evaluation = payload["evaluation"]
        self.assertEqual(evaluation["band"], "pass")
        self.assertEqual(evaluation["ideas_present"], 3)
        self.assertEqual(len(evaluation["key_ideas"]), 4)
        self.assertIn("what_went_well", evaluation)
        self.assertIn("next_step", evaluation)
        # The route consumed the double, not a vendor: both stages ran.
        self.assertEqual(
            [name for name, _ in self.double.calls],
            ["transcribe", "evaluate"],
        )
        saved = self.db.fetchone(
            "SELECT transcript FROM speaking_attempt WHERE attempt_id = ?",
            (str(attempt["attempt_id"]),),
        )
        self.assertIsNotNone(saved)
        assert saved is not None
        self.assertEqual(str(saved["transcript"]), self.double.transcript_text)

    def test_consent_gate_blocks_before_any_audio(self) -> None:
        stranger = str(uuid.uuid4())
        response = self.post_speaking_attempt(device=stranger)
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["code"], "E-CONSENT-REQUIRED")
        self.assertEqual(
            self.double.calls,
            [],
            "no frame moved before the device-scoped gate opened",
        )
        # Declining after a grant re-closes the gate for the SAME device.
        self.grant_consent(action="declined")
        declined = self.post_speaking_attempt()
        self.assertEqual(declined.status_code, 403, declined.text)
        self.assertEqual(declined.json()["code"], "E-CONSENT-REQUIRED")
        self.assertEqual(self.double.calls, [])

    def test_prompts_carry_no_answer_material(self) -> None:
        listing = self.client.get(
            "/v1/speaking/prompts", params={"chapter": MOTION, "language": "en"}
        )
        self.assertEqual(listing.status_code, 200, listing.text)
        payload = listing.json()
        self.assertGreater(payload["count"], 0)
        for item in payload["items"]:
            self.assertNotIn("key_ideas", item, "the answer material stays server-side")
            self.assertNotIn("model_answer", item)
            self.assertGreaterEqual(int(item["key_idea_count"]), 3)
            self.assertTrue(item["rubric"], "the student sees the rubric, not the key")

    def test_persistence_is_text_only(self) -> None:
        response = self.post_speaking_attempt()
        self.assertEqual(response.status_code, 200, response.text)
        attempt = response.json()["attempt"]
        # The privacy shape is structural: no audio column exists at all.
        columns = {
            str(row["name"])
            for row in self.db.fetchall("PRAGMA table_info(speaking_attempt)")
        }
        self.assertNotIn("audio", columns)
        self.assertNotIn("audio_blob", columns)
        self.assertNotIn("audio_path", columns)
        row = self.db.fetchone(
            "SELECT * FROM speaking_attempt WHERE attempt_id = ?",
            (str(attempt["attempt_id"]),),
        )
        self.assertIsNotNone(row)
        assert row is not None
        self.assertIn("transcript", row)
        self.assertTrue(str(row["feedback"] or "").strip(), "feedback kept as JSON")
        # Owner scope: a second account sees nothing of this attempt.
        other_browser = self.guest_client()
        other = self.register_api(
            f"other-{uuid.uuid4()}@example.com", client=other_browser
        )
        del other
        theirs = other_browser.get("/v1/speaking/attempts").json()
        self.assertEqual(theirs["count"], 0)
        foreign = other_browser.get(f"/v1/speaking/attempts/{attempt['attempt_id']}")
        self.assertEqual(foreign.status_code, 404, foreign.text)

    def test_history_pages_list_kept_attempts(self) -> None:
        self.post_speaking_attempt()
        self.post_speaking_attempt(prompt_id=self._second_prompt_id())
        listing = self.client.get("/v1/speaking/attempts").json()
        self.assertEqual(listing["count"], 2, "newest first, both kept")
        self.assertEqual(listing["items"][0]["prompt_id"], self._second_prompt_id())
        page = self.page("/app/speaking/history")
        self.assertIn("Every explanation you kept", page)
        self.assertIn("2 saved attempts", page)
        self.assertIn("The recordings were never stored", page)
        hub = self.page("/app/speaking")
        self.assertIn("Explain it back", hub)
        self.assertIn("Clear explanation", hub, "the hub shows the last band label")

    def test_unavailable_pipeline_answers_503_honestly(self) -> None:
        self.attach_speaking_double(available=False)
        before = self.db.fetchone("SELECT COUNT(*) AS n FROM speaking_attempt")
        assert before is not None
        response = self.post_speaking_attempt()
        self.assertEqual(response.status_code, 503, response.text)
        self.assertEqual(response.json()["code"], "E-SPEAKING-UNAVAILABLE")
        self.assertEqual(
            self.double.calls, [], "an unavailable pipeline is never called"
        )
        after = self.db.fetchone("SELECT COUNT(*) AS n FROM speaking_attempt")
        assert after is not None
        self.assertEqual(int(after["n"]), int(before["n"]), "nothing was saved")

    # -- helpers ---------------------------------------------------------------

    def _second_prompt_id(self) -> str:
        listing = self.client.get(
            "/v1/speaking/prompts", params={"chapter": MOTION, "language": "en"}
        ).json()
        ids = [item["prompt_id"] for item in listing["items"]]
        self.assertGreaterEqual(len(ids), 2, "the chapter serves two prompts")
        return str(ids[1])


__all__ = ["SpeakingFlowTests"]
