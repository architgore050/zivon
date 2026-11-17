"""Dashboard, progress map, and bookmarks pages (F3, REQUIREMENTS §10.5/§10.17/§10.20).

Hermetic: SQLite in memory, the dev email sink, no browser. Asserts the
server-rendered state (new user, partial catalogue, panel error), the five
progress states as visible text, honest empty/not-live copy, the sync panel's
existence, bookmark rendering, and the no-PII/no-lesson-device contracts.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

from fastapi.testclient import TestClient

from backend import BackendConfig, create_app
from backend.progress import CatalogueSnapshot, ChapterMeta

PASSWORD = "correct-horse-battery-staple"
CHAPTER = "class-9-describing-motion-around-us"
CONCEPT = "class-9-describing-motion-around-us-sec-01"
CHAPTER_B = "class-9-how-forces-affect-motion"
REPO_ROOT = Path(__file__).resolve().parents[2]


class DashboardPagesTests(unittest.TestCase):
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
        self.session = self.register()
        self.csrf = self._csrf()

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

    def _csrf(self) -> str:
        return str(self.session["csrf_token"])

    def post_events(self, events: list[dict[str, Any]]) -> None:
        response = self.client.post(
            "/v1/progress/events",
            json={"events": events},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["accepted"], len(events))

    def add_lesson(
        self,
        *,
        chapter_id: str = CHAPTER,
        concept_id: str | None = CONCEPT,
        blocks_seen: int | None = None,
        blocks_total: int | None = None,
    ) -> None:
        payload: dict[str, Any] = {"section_id": "sec-01", "source": "merge"}
        if blocks_seen is not None:
            payload["blocks_seen"] = blocks_seen
        if blocks_total is not None:
            payload["blocks_total"] = blocks_total
        self.post_events(
            [
                {
                    "kind": "lesson_block_view",
                    "chapter_id": chapter_id,
                    "concept_id": concept_id,
                    "payload": payload,
                }
            ]
        )

    def add_answers(self, flags: list[bool], *, chapter_id: str = CHAPTER) -> None:
        self.post_events(
            [
                {
                    "kind": "practice_answer",
                    "chapter_id": chapter_id,
                    "concept_id": None,
                    "payload": {"correct": flag, "source": "merge"},
                }
                for flag in flags
            ]
        )

    def page(self, path: str = "/app") -> str:
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("text/html", response.headers["content-type"])
        return response.text

    # -- dashboard states ---------------------------------------------------

    def test_new_user_dashboard_is_an_honest_empty_state(self) -> None:
        html = self.page("/app")
        self.assertRegex(html, r"Good (morning|afternoon|evening), Asha\.")
        self.assertIn("Nothing here yet — that is honest.", html)
        self.assertIn("Start with Describing Motion Around Us", html)
        self.assertIn("Nothing yet. Read a section and it will appear here.", html)
        self.assertIn("0 of the last 7 days", html)
        self.assertIn("Goal: 4 days a week.", html)
        self.assertIn("A rhythm, not a streak", html)
        self.assertIn("Not started", html)
        self.assertIn("One step is not live yet.", html)
        self.assertIn("not live yet", html)
        # Practice is live (F5): it is a quick action and its nav entry exists;
        # quick actions never link to a route that does not exist.
        self.assertIn('href="/app/practice"', html)
        self.assertNotIn(
            '<span class="action-soon">Practice</span>',
            html,
            "practice is live, so the quick action is a link, not a soon marker",
        )
        # `/app/speaking` (F6) and `/app/tests` (F7) are live routes, so neither
        # belongs in the dead-link list; F3's dashboard quick-action copy still
        # labels Tests "not live yet" (known debt, fixed by the F7 review pass).
        for dead in ("/app/swot",):
            self.assertNotIn(f'href="{dead}"', html)
        # The sync offer is server-rendered hidden and armed by the island.
        self.assertIn("data-progress-sync", html)
        self.assertIn("/assets/app-progress.js", html)
        self.assertIn("/assets/app.css", html)

    def test_dashboard_continue_card_uses_real_progress(self) -> None:
        self.add_lesson()
        html = self.page("/app")
        self.assertIn("Continue learning", html)
        self.assertIn("Continue the chapter", html)
        self.assertIn(
            'href="/courses/class-9-physics/describing-motion-around-us/"', html
        )
        self.assertIn("Chapters started", html)
        self.assertRegex(html, r"<dd>1</dd>")
        self.assertIn("Read a section", html)
        self.assertIn("Learning", html)

    def test_continue_card_reports_sections_read(self) -> None:
        # The continue card speaks the API's `sections_*` names; the shared
        # macro renders `blocks_*`. Without the alias it said "No sections
        # read yet" next to a map row that said "2 of 9 sections read".
        self.add_lesson(blocks_seen=2, blocks_total=9)
        html = self.page("/app")
        continue_panel = html.split('aria-labelledby="continue-title"', 1)[1]
        continue_panel = continue_panel.split("</section>", 1)[0]
        self.assertIn("2 of 9 sections read", continue_panel)
        self.assertNotIn("No sections read yet", continue_panel)

    def test_dashboard_without_a_published_class_is_still_honest(self) -> None:
        snapshot = CatalogueSnapshot(
            classes=((9, ()), (10, ()), (11, ()), (12, ())),
            chapters={},
            source="published",
        )
        with mock.patch("web.progress_views.catalogue_snapshot", return_value=snapshot):
            html = self.page("/app")
        self.assertIn("No Class 9 chapter is published yet", html)
        self.assertNotIn("Start with", html)

    def test_panel_error_keeps_the_greeting_and_hides_invented_data(self) -> None:
        with mock.patch(
            "web.progress_views.catalogue_snapshot",
            side_effect=RuntimeError("store down"),
        ):
            html = self.page("/app")
            progress = self.page("/app/progress")
            bookmarks = self.page("/app/bookmarks")
        self.assertRegex(html, r"Good (morning|afternoon|evening), Asha\.")
        self.assertIn("Your study log is unavailable right now.", html)
        self.assertIn('role="alert"', html)
        self.assertIn("Open the catalogue", html)
        self.assertNotIn("Nothing here yet — that is honest.", html)
        self.assertIn("Your progress map is unavailable right now.", progress)
        self.assertIn("Your saved sections are unavailable right now.", bookmarks)

    # -- progress map -------------------------------------------------------

    def test_progress_page_publishes_the_rules_and_states(self) -> None:
        self.add_lesson()
        self.add_answers([True] * 5)
        html = self.page("/app/progress")
        self.assertIn("Where you are, chapter by chapter.", html)
        self.assertIn("How these states work", html)
        self.assertIn("5 or more practice answers", html)
        self.assertIn("80% or more correct", html)
        self.assertIn("3 or more practice answers", html)
        self.assertIn("under 50% correct", html)
        self.assertIn("Confident", html)
        self.assertIn("Learning", html)
        self.assertIn("Not started", html)
        self.assertIn("Describing position in a straight line", html)
        self.assertIn("Concepts", html)
        # No opaque score, no social surface, no parent view.
        self.assertNotIn("leaderboard", html.lower())
        self.assertNotIn("/share", html)
        self.assertNotIn("parent access", html.lower())
        self.assertIn("no parent view", html.lower())

    def test_progress_page_shows_needs_revision(self) -> None:
        self.add_answers([False, False, False], chapter_id=CHAPTER_B)
        html = self.page("/app/progress")
        self.assertIn("Needs revision", html)
        self.assertIn("Re-read the sections and retry the checks", html)

    def test_progress_page_partial_state_without_concepts(self) -> None:
        chapter = ChapterMeta(
            chapter_id=CHAPTER,
            class_level=9,
            chapter_no=4,
            slug="describing-motion-around-us",
            title="Describing Motion Around Us",
            lesson_url="/courses/class-9-physics/describing-motion-around-us/",
            concepts=(),
        )
        snapshot = CatalogueSnapshot(
            classes=((9, (chapter,)),), chapters={CHAPTER: chapter}, source="fixture"
        )
        with mock.patch("web.progress_views.catalogue_snapshot", return_value=snapshot):
            html = self.page("/app/progress")
        self.assertIn("Concept detail is not available for this chapter yet.", html)
        self.assertIn("Not started", html)

    # -- bookmarks ----------------------------------------------------------

    def test_bookmarks_page_renders_the_empty_then_saved_state(self) -> None:
        empty = self.page("/app/bookmarks")
        self.assertIn("Nothing saved yet.", empty)
        self.assertIn("0 saved items", empty)

        created = self.client.post(
            "/v1/bookmarks",
            json={"target_type": "block", "target_id": f"{CHAPTER}:sec-03"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertEqual(created.status_code, 201, created.text)
        html = self.page("/app/bookmarks")
        self.assertIn("1 saved item", html)
        self.assertIn("Describing Motion Around Us", html)
        self.assertIn("Section sec-03", html)
        self.assertIn("data-bookmark-remove", html)
        self.assertIn(f'data-target-id="{CHAPTER}:sec-03"', html)
        self.assertIn("Remove", html)

        self.client.delete(
            "/v1/bookmarks",
            params={"target_type": "block", "target_id": f"{CHAPTER}:sec-03"},
            headers={"X-CSRF-Token": self.csrf},
        )
        self.assertIn("Nothing saved yet.", self.page("/app/bookmarks"))

    # -- privacy, a11y, and shell rules ------------------------------------

    def test_shell_and_backend_import_in_either_order(self) -> None:
        # `web.progress_views` reads `backend.progress`; `backend.app` mounts
        # the web shell. Importing the shell first must not deadlock on a
        # cycle (it did while `backend/__init__` imported `.app` eagerly).
        script = (
            "import web; assert web.mount_web;"
            "from backend import create_app; assert create_app;"
            "from backend.progress import build_summary; assert build_summary"
        )
        result = subprocess.run(
            [sys.executable, "-c", script],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr[-2000:])

    def test_pages_never_render_account_secrets_or_lesson_devices(self) -> None:
        self.add_lesson()
        user_id = self.session["user"]["user_id"]
        for path in ("/app", "/app/progress", "/app/bookmarks"):
            html = self.page(path)
            self.assertNotIn("kid@example.com", html, path)
            self.assertNotIn(user_id, html, path)
            self.assertNotIn("zivon.css", html, path)
            self.assertNotRegex(html, r"\bzn-[a-z0-9-]+", path)

    def test_pages_carry_a11y_and_viewport_contracts(self) -> None:
        for path in ("/app", "/app/progress", "/app/bookmarks"):
            html = self.page(path)
            self.assertIn('name="viewport"', html, path)
            self.assertIn("aria-labelledby=", html, path)
            self.assertIn('class="skip"', html, path)
        progress = self.page("/app/progress")
        self.assertIsNotNone(
            re.search(r'<span class="state state--[a-z_]+">[A-Za-z ]+</span>', progress)
        )
        css = (REPO_ROOT / "frontend" / "assets" / "app.css").read_text(
            encoding="utf-8"
        )
        self.assertIn("@media (max-width: 480px)", css)
        self.assertIn(".progress-chapter-head", css)
        self.assertNotIn("min-width: 640px", css)


if __name__ == "__main__":
    unittest.main()
