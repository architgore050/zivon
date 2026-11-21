"""Flow 1 (§17.1): guest lesson -> check -> practice -> signup -> progress
merge -> dashboard.

The guest reads the real published lesson page (the same artifact nginx
serves), hits the honest practice guard, signs up through the real web form,
and the device-merge island's exact API contract replays the device-local
data through `/v1/progress/events` + `/v1/bookmarks` — after which the
dashboard shows the merged chapter instead of the honest empty state.
"""

from __future__ import annotations

import json
import re

from db.uuid7 import uuid7_str

from .support import FRONTEND_DIR, MOTION, E2EFlow

LESSON_DIR = (
    FRONTEND_DIR / "courses" / "class-9-physics" / "describing-motion-around-us"
)


class GuestLessonToDashboardTests(E2EFlow):
    """The §17.1 flow 1 chain, guest to signed-in dashboard."""

    # -- the guest lesson ----------------------------------------------------

    def test_guest_lesson_page_is_the_published_artifact(self) -> None:
        """The lesson a guest opens is the real generated page: title, checks,
        sims, language bar — the static artifact nginx serves, integrity
        asserted here so the flow cannot pass on a missing page."""
        html = (LESSON_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("Describing Motion Around Us", html)
        self.assertIn("zn-check", html, "the lesson carries comprehension checks")
        self.assertIn("zn-sim", html, "the lesson carries interactive simulations")
        self.assertIn("zn-lang-bar", html, "the doctrine language bar")
        manifest = json.loads((LESSON_DIR / "manifest.json").read_text("utf-8"))
        self.assertEqual(manifest["course_id"], "class-9-physics")
        self.assertTrue(manifest.get("sections"), "chapter drawer sections exist")

    def test_guest_session_bootstrap_answers(self) -> None:
        """NEED-003: the guest lesson shell POSTs /v1/session before anything
        else; the bootstrap answers key-free."""
        response = self.client.post(
            "/v1/session",
            json={"device_pseudo_id": self.device_id},
        )
        self.assertEqual(response.status_code, 200, response.text)
        payload = response.json()
        self.assertIn("session_id", payload)

    # -- the honest guard ----------------------------------------------------

    def test_guest_practice_is_a_login_guard_not_an_error(self) -> None:
        guest = self.guest_client()
        response = guest.get("/app/practice", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login?next=/app/practice")
        login = guest.get("/login?next=/app/practice")
        self.assertEqual(login.status_code, 200)
        self.assertIn("Sign in", login.text)

    # -- signup through the real web form ------------------------------------
    # (`signup_via_web` lives on the E2EFlow base: the same real form path
    # every flow reuses, asserted to land on /onboarding.)

    def test_signup_then_onboarding_sets_class_and_language(self) -> None:
        browser = self.guest_client()
        self.signup_via_web(f"web-{uuid7_str()}@example.com", client=browser)
        onboarding = browser.get("/onboarding")
        self.assertIn("Set up your class", onboarding.text)
        token = self.csrf_from_page("/onboarding", client=browser)
        done = browser.post(
            "/onboarding",
            data={
                "csrf_token": token,
                "class_level": "9",
                "board": "CBSE",
                "language": "en-IN",
                "goal": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(done.status_code, 303, done.text)
        session = browser.get("/v1/auth/session").json()
        self.assertTrue(session["authenticated"])
        self.assertEqual(int(session["user"]["class_level"]), 9)

    # -- the progress merge --------------------------------------------------

    def lesson_events(self, *, source: str, blocks_seen: int) -> list[dict]:
        return [
            {
                "kind": "lesson_block_view",
                "chapter_id": MOTION,
                "payload": {
                    "blocks_seen": blocks_seen,
                    "section_id": f"section-{blocks_seen}",
                    "source": source,
                },
            }
        ]

    def test_merge_replays_device_data_and_dashboard_shows_it(self) -> None:
        browser = self.guest_client()
        self.signup_via_web(f"merge-{uuid7_str()}@example.com", client=browser)
        token = self.csrf_from_page("/onboarding", client=browser)
        browser.post(
            "/onboarding",
            data={
                "csrf_token": token,
                "class_level": "9",
                "board": "CBSE",
                "language": "en-IN",
                "goal": "",
            },
            follow_redirects=False,
        )
        csrf = str(browser.get("/v1/auth/session").json()["csrf_token"])

        accepted = self.merge_events(
            self.lesson_events(source="merge", blocks_seen=7),
            csrf=csrf,
            client=browser,
        )
        self.assertEqual(accepted["accepted"], 1, accepted)

        merged = self.merge_bookmarks(
            [{"target_type": "chapter", "target_id": MOTION}],
            csrf=csrf,
            client=browser,
        )
        self.assertTrue(merged.get("ok", True), merged)

        dashboard = browser.get("/app")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("Describing Motion", dashboard.text, "Continue card")
        bookmarks = browser.get("/app/bookmarks")
        self.assertIn("Describing Motion Around Us", bookmarks.text)
        summary = browser.get("/v1/progress/summary").json()
        chapters = [
            chapter
            for group in summary.get("classes", [])
            for chapter in group.get("chapters", [])
        ]
        merged_chapter = next((c for c in chapters if c["chapter_id"] == MOTION), None)
        self.assertIsNotNone(merged_chapter, "the merged chapter is on the map")
        assert merged_chapter is not None
        self.assertEqual(int(merged_chapter["blocks_seen"]), 7)
        self.assertEqual(summary["counts"]["bookmarks"], 1)

    def test_stale_merge_never_regresses_progress(self) -> None:
        csrf = self.csrf
        self.merge_events(self.lesson_events(source="merge", blocks_seen=9), csrf=csrf)
        self.merge_events(self.lesson_events(source="merge", blocks_seen=3), csrf=csrf)
        stored = self.db.fetchone(
            "SELECT blocks_seen FROM lesson_progress WHERE user_id = ? AND chapter_id = ?",
            (self.session["user"]["user_id"], MOTION),
        )
        self.assertIsNotNone(stored)
        assert stored is not None
        self.assertEqual(
            int(stored["blocks_seen"]),
            9,
            "a later stale merge keeps the maximum sections read",
        )

    def test_unauthenticated_merge_is_rejected(self) -> None:
        guest = self.guest_client()
        response = guest.post(
            "/v1/progress/events",
            json={"events": self.lesson_events(source="merge", blocks_seen=1)},
        )
        self.assertEqual(response.status_code, 401, response.text)

    def test_malformed_merge_event_is_rejected_individually(self) -> None:
        response = self.merge_events(
            [
                {"kind": "lesson_block_view", "chapter_id": MOTION, "payload": {}},
                {
                    "kind": "lesson_block_view",
                    "chapter_id": MOTION,
                    "payload": {"sections_seen": 4, "source": "merge"},
                },
            ]
        )
        self.assertEqual(response["accepted"], 1)
        self.assertEqual(len(response["rejected"]), 1)
        self.assertEqual(response["rejected"][0]["code"], "E-EVT-SCHEMA")

    def test_dashboard_empty_state_stays_honest_before_merge(self) -> None:
        """A fresh account shows the honest empty dashboard, no invented data."""
        browser = self.guest_client()
        self.signup_via_web(f"empty-{uuid7_str()}@example.com", client=browser)
        dashboard = browser.get("/app")
        self.assertEqual(dashboard.status_code, 200)
        self.assertRegex(
            dashboard.text,
            re.compile("Nothing here yet", re.IGNORECASE),
            "the honest empty state",
        )
        self.assertNotIn("Describing Motion", dashboard.text)
