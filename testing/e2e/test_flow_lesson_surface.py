"""Flow 3 (§17.1): the lesson surface — read, sim, check, bookmark, doubt,
read-aloud, language switch.

The lesson page is a generated static artifact (nginx serves it; the repo's
committed `frontend/courses/` snapshot is the same file). This module asserts
the artifact's interactive contract and drives every backend seam the lesson
shell uses: progress events, bookmarks, the consent gate, and the voice WS
route — with the honest degraded states reachable key-free.
"""

from __future__ import annotations

import json

from .support import DEV_DEVICE_ID, FRONTEND_DIR, MOTION, E2EFlow

LESSON_DIR = (
    FRONTEND_DIR / "courses" / "class-9-physics" / "describing-motion-around-us"
)


class LessonSurfaceTests(E2EFlow):
    """Read/sim/check on the published artifact; bookmark/doubt through the API."""

    # -- read + sim + check (the published artifact) --------------------------

    def test_lesson_carries_sims_checks_and_the_kit_contract(self) -> None:
        html = (LESSON_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn("zn-sim", html)
        self.assertIn("canvas", html, "sims draw on canvas")
        self.assertIn("zn-check", html)
        self.assertIn('aria-live="polite"', html, "check feedback is announced")
        page_js = (LESSON_DIR / "page.js").read_text(encoding="utf-8")
        self.assertIn("ZivonSim.register", page_js, "sims register with the kit")
        self.assertNotIn("fetch(", page_js, "generated pages make zero calls")
        self.assertNotIn("XMLHttpRequest", page_js)

    def test_lesson_manifest_sections_drive_the_drawer(self) -> None:
        manifest = json.loads((LESSON_DIR / "manifest.json").read_text("utf-8"))
        self.assertGreaterEqual(len(manifest.get("sections", [])), 1)
        self.assertEqual(manifest["course_id"], "class-9-physics")
        self.assertTrue(manifest.get("title"))

    # -- read: the progress seam ----------------------------------------------

    def test_reading_records_progress_and_the_map_shows_it(self) -> None:
        csrf = self.csrf
        for block in range(1, 4):
            self.merge_events(
                [
                    {
                        "kind": "lesson_block_view",
                        "chapter_id": MOTION,
                        "payload": {
                            "blocks_seen": block,
                            "blocks_total": 12,
                            "section_id": f"sec-{block}",
                            "source": "lesson_shell",
                        },
                    }
                ],
                csrf=csrf,
            )
        complete = self.merge_events(
            [
                {
                    "kind": "lesson_complete",
                    "chapter_id": MOTION,
                    "payload": {
                        "sections_seen": 12,
                        "sections_total": 12,
                        "source": "lesson_shell",
                    },
                }
            ],
            csrf=csrf,
        )
        self.assertEqual(complete["accepted"], 1)
        progress = self.client.get("/app/progress")
        self.assertEqual(progress.status_code, 200)
        self.assertIn("Describing Motion Around Us", progress.text)
        summary = self.client.get("/v1/progress/summary").json()
        counts = summary["counts"]
        self.assertEqual(counts["chapters_completed"], 1)

    # -- check: lesson checks are client-side, honest by construction ---------

    def test_lesson_check_is_self_contained_with_retry(self) -> None:
        """The lesson quiz ships the whole contract in HTML: no answer submitted
        to a server, feedback announced, retry allowed (learning, not testing)."""
        html = (LESSON_DIR / "index.html").read_text(encoding="utf-8")
        self.assertIn('type="radio"', html)
        self.assertIn("data-answer", html, "numeric checks compare on-device")
        self.assertNotIn("/v1/", html, "the static core page calls no API")

    # -- bookmark -------------------------------------------------------------

    def test_bookmark_save_show_and_remove(self) -> None:
        csrf = self.csrf
        added = self.merge_bookmarks(
            [{"target_type": "chapter", "target_id": MOTION}], csrf=csrf
        )
        self.assertEqual(added["created"], 1)
        page = self.client.get("/app/bookmarks")
        self.assertIn("Describing Motion Around Us", page.text)
        removed = self.client.delete(
            "/v1/bookmarks",
            params={"target_type": "chapter", "target_id": MOTION},
            headers=self.headers(csrf),
        )
        self.assertEqual(removed.status_code, 200, removed.text)
        page = self.client.get("/app/bookmarks")
        self.assertIn("Nothing saved yet", page.text, "honest empty state")

    def test_bookmark_target_is_validated(self) -> None:
        response = self.merge_bookmarks(
            [{"target_type": "neighbour/roof", "target_id": "x"}],
            expect=422,
        )
        self.assertEqual(response["code"], "E-VALIDATION")

    # -- doubt: consent gate + the voice seam ---------------------------------

    def test_consent_gate_governs_the_doubt_seam(self) -> None:
        session = self.client.post(
            "/v1/session", json={"device_pseudo_id": DEV_DEVICE_ID}
        )
        self.assertEqual(session.status_code, 200, session.text)
        payload = session.json()
        self.assertTrue(payload.get("consent_required"), payload)

        granted = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": DEV_DEVICE_ID,
                "consent_version": "v1",
                "guardian_flag": True,
                "action": "granted",
            },
        )
        self.assertEqual(granted.status_code, 200, granted.text)
        after = self.client.post(
            "/v1/session", json={"device_pseudo_id": DEV_DEVICE_ID}
        ).json()
        self.assertFalse(after.get("consent_required"), after)

        declined = self.client.put(
            "/v1/consent",
            json={
                "device_pseudo_id": DEV_DEVICE_ID,
                "consent_version": "v1",
                "guardian_flag": False,
                "action": "declined",
            },
        )
        self.assertEqual(declined.status_code, 200)
        gate = self.client.post(
            "/v1/session", json={"device_pseudo_id": DEV_DEVICE_ID}
        ).json()
        self.assertTrue(gate.get("consent_required"), "decline re-opens the gate")

    def test_voice_ws_route_is_mounted_for_the_dock(self) -> None:
        paths = {getattr(route, "path", "") for route in self.app.routes}
        self.assertIn("/voice/ws", paths, "ADR-0020: the dock's WS route")

    # -- read-aloud -----------------------------------------------------------

    def test_read_aloud_narration_assets_exist_for_served_blocks(self) -> None:
        narration = json.loads(
            (LESSON_DIR / "narration-manifest.json").read_text("utf-8")
        )
        blocks = narration.get("blocks") or []
        self.assertGreater(len(blocks), 0, "the lesson is narrated")
        for block in blocks[:5]:
            asset = FRONTEND_DIR / block["path"]
            self.assertTrue(
                asset.is_file(), f"narration asset missing: {block['path']}"
            )
            self.assertEqual(block["lang"], narration.get("lang", block["lang"]))

    def test_read_aloud_is_absent_when_no_narration_manifest(self) -> None:
        """The honesty rule: a lesson without narration ships no dead control.

        The kit renders the button per manifest block; the contract here is
        that the manifest is the single source — a missing manifest cannot
        produce a broken button because the page never references audio."""
        page_js = (LESSON_DIR / "page.js").read_text(encoding="utf-8")
        html = (LESSON_DIR / "index.html").read_text(encoding="utf-8")
        self.assertNotIn(".opus", html, "audio URLs come from the manifest only")
        self.assertNotIn(".opus", page_js)

    # -- language switch ------------------------------------------------------

    def test_language_switch_targets_are_published(self) -> None:
        for locale in ("hi", "hi-Latn"):
            tree = LESSON_DIR / locale / "index.html"
            self.assertTrue(tree.is_file(), f"localized lesson missing: {locale}")
            localized = tree.read_text(encoding="utf-8")
            self.assertIn("<html lang=", localized)
        bundle = json.loads((LESSON_DIR / "i18n" / "hi.json").read_text("utf-8"))
        self.assertTrue(bundle, "the hi chrome bundle exists")

    def test_english_canonical_is_the_default_language(self) -> None:
        html = (LESSON_DIR / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'<html lang="en')
        # The doctrine bar: one label + three chips, English preselected.
        self.assertEqual(html.count("zn-chip"), 3, "English, हिन्दी, Hinglish")
