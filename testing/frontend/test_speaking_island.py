"""Explain-back recorder island (`/assets/app-speaking.js`).

Hermetic browser test: a fixture page carries the recorder DOM and the real
asset; `/v1/speaking/attempts` and `/v1/consent` are fulfilled by Playwright
routes. Chromium's fake audio device supplies the microphone, so the real
capture path runs (getUserMedia -> ScriptProcessor -> 16 kHz PCM -> WAV) with
no device, no backend, and no key. Asserts the consent gate, the one upload's
shape and headers, the rendered result, delete, and the quota state.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard
from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
ASSET = REPO_ROOT / "frontend" / "assets" / "app-speaking.js"

RESULT = {
    "mock": False,
    "attempt": {
        "attempt_id": "attempt-test-1",
        "prompt_id": "spk-c9-motion-001",
        "language": "en",
        "transcript": "Distance is the whole path. Displacement is the net change.",
        "rubric_scores": {"band": "pass", "ideas_present": 2, "ideas_total": 4},
        "feedback": {"band": "pass", "label": "AI feedback"},
        "self_check": {},
        "score": 50.0,
        "duration_ms": 1200,
        "created_at": "2026-11-17T10:00:00.000Z",
    },
    "prompt": {
        "prompt_id": "spk-c9-motion-001",
        "prompt": "Explain the difference between distance and displacement.",
        "key_ideas": [],
        "model_answer": "Distance counts every metre you travel.",
        "model_answer_source": {"book_id": "ncert-science-9", "section": "4.1.2"},
    },
    "evaluation": {
        "band": "pass",
        "band_label": "Clear explanation",
        "band_note": "You covered the main ideas.",
        "ideas_present": 2,
        "ideas_total": 4,
        "ratio": 0.5,
        "key_ideas": [
            {
                "idea_id": "i1",
                "text": "Distance is the total path.",
                "present": True,
                "evidence": "whole path",
            },
            {
                "idea_id": "i2",
                "text": "Displacement is the net change.",
                "present": True,
                "evidence": "net change",
            },
            {
                "idea_id": "i3",
                "text": "A round trip has zero displacement.",
                "present": False,
                "evidence": "",
            },
            {
                "idea_id": "i4",
                "text": "Displacement is never larger than distance.",
                "present": False,
                "evidence": "",
            },
        ],
        "what_went_well": "You named distance and displacement.",
        "next_step": "Add the round-trip example.",
        "mock": False,
    },
    "evaluation_error": None,
    "notice": None,
}

PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="csrf-token" content="test-csrf">
<title>Recorder fixture</title>
<link rel="stylesheet" href="/assets/app-speaking.css">
</head>
<body><main class="wrap">
<section data-speaking-recorder data-prompt-id="spk-c9-motion-001"
  data-language="en" data-max-seconds="45" data-speech-available="true"
  data-mock="false" data-consent-notice-version="zivon-voice-notice-v1"
  data-consent-version="v1">
  <section data-speaking-consent hidden>
    <h2>Voice tutor: before we start</h2>
    <label><input type="checkbox" data-consent-guardian> I have permission.</label>
    <button type="button" data-consent-continue disabled>Continue with voice</button>
    <button type="button" data-consent-decline>Decline</button>
  </section>
  <div data-speaking-consent-off hidden>
    <button type="button" data-speaking-consent-review>Review the voice notice</button>
  </div>
  <button type="button" data-speaking-mic aria-pressed="false" disabled>
    <span data-speaking-mic-label>Start recording</span>
  </button>
  <p><span data-speaking-timer>00:45</span></p>
  <p data-speaking-time-status role="status" aria-live="polite"></p>
  <canvas data-speaking-wave width="640" height="96"></canvas>
  <p data-speaking-status role="status" aria-live="polite"></p>
  <section data-speaking-result-region>
    <p data-speaking-result-placeholder>Your feedback appears here.</p>
  </section>
</section>
<template data-speaking-result-template>
  <article data-speaking-result-card tabindex="-1">
    <p class="kicker" data-field="when"></p>
    <h2 data-field="title">Feedback on your explanation</h2>
    <div data-field="mock-notice" hidden>Demo mode.</div>
    <div data-field="evaluation">
      <p><span data-field="band"></span> <span data-field="count"></span></p>
      <p>AI feedback</p>
      <ul data-field="ideas"></ul>
      <p><span data-field="went-well"></span></p>
      <p><span data-field="next-step"></span></p>
    </div>
    <div data-field="unavailable" hidden>Feedback unavailable.</div>
    <p data-field="transcript"></p>
    <details data-field="model" hidden>
      <summary>Model answer</summary>
      <p data-field="model-answer"></p>
      <p data-field="model-source"></p>
    </details>
    <fieldset>
      <label><input type="radio" value="explained_fully" data-self-check> I explained it fully</label>
      <label><input type="radio" value="missed_a_part" data-self-check> I missed a part</label>
      <label><input type="radio" value="practise_again" data-self-check> I need to practise again</label>
      <button type="button" data-speaking-self-check-save>Save how it felt</button>
    </fieldset>
    <button type="button" data-speaking-delete>Delete this attempt</button>
    <p data-speaking-result-status role="status" aria-live="polite"></p>
  </article>
</template>
</main>
<script src="/assets/app-speaking.js"></script>
</body></html>
"""


class SpeakingIslandTests(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _server: Any
    _base_url: str

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch(
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-speaking-")
        root = Path(cls._tmp.name)
        (root / "index.html").write_text(PAGE, encoding="utf-8")
        cls._server = serve_static(root)
        cls._base_url = cls._server.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    def _page(
        self,
        *,
        consent: str | None = None,
        error: dict[str, Any] | None = None,
    ) -> tuple[Page, list[dict[str, Any]], list[dict[str, Any]]]:
        context = self._browser.new_context(permissions=["microphone"])
        context.route(
            "**/favicon.ico", lambda route: route.fulfill(status=204, body="")
        )
        context.route(
            "**/assets/app-speaking.js",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body=ASSET.read_text(encoding="utf-8"),
            ),
        )
        consent_calls: list[dict[str, Any]] = []
        attempt_calls: list[dict[str, Any]] = []

        def handle_consent(route: Any) -> None:
            consent_calls.append(route.request.post_data_json)
            route.fulfill(status=200, json={"ok": True, "consent_id": "c-1"})

        def handle_attempt(route: Any) -> None:
            request = route.request
            attempt_calls.append(
                {
                    "url": request.url,
                    "method": request.method,
                    "headers": request.headers,
                    "body": request.post_data_buffer,
                }
            )
            if error is not None:
                route.fulfill(status=error.pop("status", 429), json=error)
                return
            route.fulfill(status=200, json=RESULT)

        context.route(re.compile(r".*/v1/consent$"), handle_consent)
        context.route(re.compile(r".*/v1/speaking/attempts.*"), handle_attempt)
        if consent is not None:
            context.add_init_script(
                f"localStorage.setItem('zivon.consent', {json.dumps(consent)});"
            )
        page = context.new_page()
        page.goto(self._base_url + "/index.html")
        return page, consent_calls, attempt_calls

    def _record(self, page: Page) -> None:
        page.click("[data-speaking-mic]")
        page.wait_for_function(
            "document.querySelector('[data-speaking-status]').textContent.indexOf('Recording') >= 0",
            timeout=10_000,
        )
        page.wait_for_timeout(900)
        page.click("[data-speaking-mic]")

    def test_consent_gate_blocks_the_mic_then_unlocks_it(self) -> None:
        page, consent_calls, attempt_calls = self._page()
        try:
            self.assertTrue(page.is_visible("[data-speaking-consent]"))
            self.assertTrue(page.is_disabled("[data-speaking-mic]"))
            page.check("[data-consent-guardian]")
            page.click("[data-consent-continue]")
            page.wait_for_function(
                "window.ZivonSpeaking.getConsentState() === 'granted'"
            )
            self.assertFalse(page.is_visible("[data-speaking-consent]"))
            self.assertTrue(page.is_enabled("[data-speaking-mic]"))
            self.assertEqual(consent_calls[0]["action"], "granted")
            self.assertEqual(
                consent_calls[0]["notice_version"], "zivon-voice-notice-v1"
            )
            self.assertEqual(attempt_calls, [])
        finally:
            page.context.close()

    def test_record_uploads_one_wav_and_renders_the_feedback(self) -> None:
        page, _, attempt_calls = self._page(consent="granted")
        try:
            page.wait_for_selector("[data-speaking-mic]:not([disabled])")
            self._record(page)
            page.wait_for_selector("[data-speaking-result-card]", timeout=15_000)
            card = page.locator("[data-speaking-result-card]").inner_text()
            self.assertIn("Clear explanation", card)
            self.assertIn("2 of 4 key ideas covered", card)
            self.assertIn("Distance is the whole path.", card)
            self.assertIn("AI feedback", card)
            self.assertIn("Covered", card)
            self.assertIn("Missing", card)
            self.assertIn(
                "Distance counts every metre you travel.",
                page.locator('[data-field="model-answer"]').text_content() or "",
            )
            self.assertIn(
                "NCERT Science Class 9",
                page.locator('[data-field="model-source"]').text_content() or "",
            )
            self.assertEqual(len(attempt_calls), 1)
            call = attempt_calls[0]
            self.assertEqual(call["method"], "POST")
            self.assertIn("prompt_id=spk-c9-motion-001", call["url"])
            self.assertEqual(call["headers"].get("content-type"), "audio/wav")
            self.assertEqual(call["headers"].get("x-csrf-token"), "test-csrf")
            self.assertRegex(
                call["headers"].get("x-device-id", ""),
                r"^[0-9a-f-]{36}$",
            )
            body = call["body"]
            assert body is not None
            self.assertEqual(body[:4], b"RIFF")
            self.assertEqual(body[8:12], b"WAVE")
            self.assertGreater(len(body), 44)
            # The mic control returns to a clean start state.
            self.assertEqual(
                page.get_attribute("[data-speaking-mic]", "aria-pressed"), "false"
            )
        finally:
            page.context.close()

    def test_quota_error_is_an_honest_status_and_no_result(self) -> None:
        page, _, attempt_calls = self._page(
            consent="granted", error={"status": 429, "code": "E-QUOTA-EXHAUSTED"}
        )
        try:
            page.wait_for_selector("[data-speaking-mic]:not([disabled])")
            self._record(page)
            page.wait_for_function(
                "document.querySelector('[data-speaking-status]').textContent.indexOf('resting') >= 0",
                timeout=15_000,
            )
            self.assertEqual(page.locator("[data-speaking-result-card]").count(), 0)
            self.assertEqual(len(attempt_calls), 1)
        finally:
            page.context.close()

    def test_delete_removes_the_attempt_card(self) -> None:
        page, _, _ = self._page(consent="granted")
        try:
            page.wait_for_selector("[data-speaking-mic]:not([disabled])")
            self._record(page)
            page.wait_for_selector("[data-speaking-result-card]", timeout=15_000)
            page.on("dialog", lambda dialog: dialog.accept())
            page.click("[data-speaking-delete]")
            page.wait_for_function(
                "document.querySelectorAll('[data-speaking-result-card]').length === 0",
                timeout=10_000,
            )
            self.assertTrue(page.is_visible("[data-speaking-result-placeholder]"))
        finally:
            page.context.close()


__all__ = ["SpeakingIslandTests"]
