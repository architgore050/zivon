"""PL4 session-island behaviour tests (headless Chromium, no network).

Drives the REAL `frontend/assets/personalized.js` against a static fixture
page (the session screen's island contract) with `window.fetch` stubbed to a
recorded SSE stream — the same transport shape `API-PL-10` returns. Asserts:

- the teach stream renders into one card and the live region announces the
  writing state, never per token;
- the check card is answered with the CSRF header and the §3.2 body shape;
- `turn.feedback` disables the answered card (shape + words, controls off);
- `turn.done` updates the honest quota strip;
- `turn.error` renders an honest error card whose Retry replays the SAME
  `client_turn_id` (§3.4 idempotency);
- the offline event disables the composer with a reconnect message;
- a `turn.artifact` event builds the PL3 viewer card and hands it to the
  existing bridge (`window.ZivonArtifactViewer.mount`), never creating an
  iframe itself;
- the settings instructions counter updates and gates Save (spec.md §1.3).

Needs a Playwright browser once:  python -m playwright install chromium
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from playwright.sync_api import sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
ISLAND_JS = (REPO_ROOT / "frontend" / "assets" / "personalized.js").resolve()
ISLAND_URI = ISLAND_JS.as_uri()

SSE = (
    'event: turn.stage\ndata: {"stage": "teach"}\n\n'
    'event: turn.teach.start\ndata: {"message_id": "m1"}\n\n'
    'event: turn.teach.delta\ndata: {"text": "A concave mirror curves inward. "}\n\n'
    'event: turn.teach.delta\ndata: {"text": "Parallel rays meet at the focus."}\n\n'
    'event: turn.check\ndata: {"check_id": "chk-9", "kind": "mcq", "question": "Where do parallel rays meet?", "options": [{"id": "A", "text": "Centre"}, {"id": "B", "text": "Focus"}]}\n\n'
    'event: turn.done\ndata: {"message_id": "m1", "quota": {"remaining": 36, "reset_at": "2026-11-20T18:30:00.000Z"}}\n\n'
)

SSE_ANSWERED = (
    'event: turn.stage\ndata: {"stage": "adapt"}\n\n'
    'event: turn.feedback\ndata: {"check_id": "chk-9", "correct": false, "expected": "B", "explanation": "Rays converge at the principal focus."}\n\n'
    'event: turn.done\ndata: {"message_id": null, "quota": {"remaining": 35, "reset_at": "2026-11-20T18:30:00.000Z"}}\n\n'
)

SSE_TEACH_ONLY = (
    'event: turn.stage\ndata: {"stage": "teach"}\n\n'
    'event: turn.teach.start\ndata: {"message_id": "m1"}\n\n'
    'event: turn.teach.delta\ndata: {"text": "A concave mirror curves inward. "}\n\n'
    'event: turn.teach.delta\ndata: {"text": "Parallel rays meet at the focus, the point '
    'where every ray converges after reflecting."}\n\n'
)

SSE_ERROR = 'event: turn.error\ndata: {"code": "E-PL-MODEL-DOWN", "message_key": "error.pl.model_down", "retryable": true}\n\n'

SSE_ARTIFACT = (
    'event: turn.artifact\ndata: {"artifact_id": "art42", "status": "pending", "title": "Mirror sim", "kind": "simulation"}\n\n'
    'event: turn.done\ndata: {"message_id": null, "quota": {"remaining": 34, "reset_at": "2026-11-20T18:30:00.000Z"}}\n\n'
)


def session_fixture() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='csrf-token' content='test-csrf-token'></head><body>
<div data-pl-session data-session-id='sess-1' data-session-status='active'
     data-can-send='true' data-report-course='personalized/class-10-light'>
  <span class='tag' data-pl-stage>Teaching</span>
  <span data-pl-quota>40 turns left today</span>
  <section aria-label='Session transcript'>
    <ol data-pl-transcript></ol>
    <p data-pl-live aria-live='polite' role='status'></p>
  </section>
  <section data-pl-composer aria-label='Ask Zivon'>
    <button type='button' data-pl-action='explain_directly'>Explain directly</button>
    <button type='button' data-pl-action='hint'>I'm stuck</button>
    <input data-pl-message type='text' value=''>
    <button type='button' data-pl-send>Send</button>
    <p data-pl-error role='alert' hidden></p>
  </section>
</div>
<script src='{ISLAND_URI}'></script>
</body></html>"""


def instructions_fixture() -> str:
    return f"""<!doctype html><html><head><meta charset='utf-8'></head><body>
<section data-pl-instructions>
  <textarea data-pl-instructions-field>saved value</textarea>
  <span data-pl-instructions-count>11</span>
  <button type='button' data-pl-instructions-save>Save</button>
</section>
<script src='{ISLAND_URI}'></script>
</body></html>"""


def fetch_stub(streams: list[str]) -> str:
    """Replace window.fetch with a recorder serving one SSE stream per call
    (the last stream repeats when the calls exceed the list)."""
    return f"""
window.__plCaptures = [];
window.__plStreams = {json.dumps(streams)};
window.fetch = function (url, options) {{
  var body = window.__plStreams.length > 1
    ? window.__plStreams.shift()
    : window.__plStreams[0];
  window.__plCaptures.push({{
    url: String(url),
    method: (options && options.method) || 'GET',
    csrf: options && options.headers ? options.headers['X-CSRF-Token'] : null,
    body: options && options.body ? String(options.body) : null
  }});
  var sse = new TextEncoder().encode(body);
  return Promise.resolve(new Response(new ReadableStream({{
    start: function (controller) {{
      controller.enqueue(sse);
      controller.close();
    }}
  }}), {{ status: 200, headers: {{ 'Content-Type': 'text/event-stream' }} }}));
}};
"""


class IslandSupport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self._pw = sync_playwright().start()
        self.browser = self._pw.chromium.launch()

    def tearDown(self) -> None:
        self.browser.close()
        self._pw.stop()
        self._tmp.cleanup()

    def open_page(self, html: str, stub: str | None = None) -> "object":  # noqa: UP037
        page_path = self.tmp_path / "fixture.html"
        page_path.write_text(html, encoding="utf-8")
        page = self.browser.new_page()
        if stub:
            page.add_init_script(stub)
        page.goto(page_path.as_uri())
        return page


class TeachStreamTests(IslandSupport):
    def test_stream_renders_teach_check_and_quota(self) -> None:
        page = self.open_page(session_fixture(), fetch_stub([SSE]))
        page.click("[data-pl-send]") if False else None
        page.evaluate(
            "window.ZivonPersonalized.mount();"
            "document.querySelector('[data-pl-session]')._plStart = true;"
        )
        # Drive a turn through the island's own click path: the composer send
        # needs text; use the explain action instead.
        page.click("[data-pl-action='explain_directly']")
        page.wait_for_selector(
            "[data-pl-card-teach], .pl-card--teach", state="attached"
        )
        card_text = page.inner_text(".pl-card--teach")
        self.assertIn("A concave mirror curves inward", card_text)
        check = page.wait_for_selector("[data-pl-check]")
        self.assertEqual(check.get_attribute("data-check-id"), "chk-9")
        options = page.inner_text(".pl-options")
        self.assertIn("Focus", options)
        self.assertIn("36 turns left today", page.inner_text("[data-pl-quota]"))
        stage = page.inner_text("[data-pl-stage]")
        self.assertEqual(stage, "Teaching")

    def test_first_line_is_announced_not_every_token(self) -> None:
        # A stream that never reaches turn.done leaves the first-line
        # announcement visible: one update, not one per delta (spec §6.2).
        page = self.open_page(session_fixture(), fetch_stub([SSE_TEACH_ONLY]))
        page.click("[data-pl-action='explain_directly']")
        page.wait_for_selector(".pl-card--teach", state="attached")
        live = page.inner_text("[data-pl-live]")
        self.assertTrue(
            live.startswith("A concave mirror"),
            f"the first line must be announced, got: {live!r}",
        )
        self.assertLessEqual(
            len(live),
            80,
            "one announcement per turn, never the whole stream",
        )
        self.assertNotIn("converges after reflecting", live)

    def test_answer_posts_the_csrf_header_and_contract_body(self) -> None:
        # First call arms the check (the teach stream), the second returns
        # the feedback for the submitted answer.
        page = self.open_page(session_fixture(), fetch_stub([SSE, SSE_ANSWERED]))
        page.click("[data-pl-action='explain_directly']")
        page.wait_for_selector("[data-pl-check]", state="attached")
        page.check("input[value='A']")
        page.click("[data-pl-check-submit]")
        captures = page.evaluate("window.__plCaptures")
        self.assertTrue(captures, "the answer must cross the API seam")
        first = captures[-1]
        self.assertIn("/v1/personalized/sessions/sess-1/turns", first["url"])
        self.assertEqual(first["csrf"], "test-csrf-token")
        body = json.loads(first["body"])
        self.assertEqual(body["action"], "answer")
        self.assertEqual(body["check_id"], "chk-9")
        self.assertEqual(body["answer"], "A")
        # feedback applied: card answered, controls disabled, words not hue
        page.wait_for_selector("[data-pl-check][data-check-answered='true']")
        disabled = page.evaluate(
            "Array.from(document.querySelectorAll('[data-pl-answer]'))"
            ".every(function (n) { return n.disabled; })"
        )
        self.assertTrue(disabled)
        self.assertIn("Not yet", page.inner_text("[data-pl-check]"))
        self.assertIn("35 turns left today", page.inner_text("[data-pl-quota]"))
        stage = page.inner_text("[data-pl-stage]")
        self.assertEqual(stage, "Explaining another way")

    def test_not_sure_submits_without_a_selection(self) -> None:
        page = self.open_page(session_fixture(), fetch_stub([SSE, SSE_ANSWERED]))
        page.click("[data-pl-action='explain_directly']")
        page.wait_for_selector("[data-pl-check]", state="attached")
        page.click("[data-pl-not-sure]")
        captures = page.evaluate("window.__plCaptures")
        body = json.loads(captures[-1]["body"])
        self.assertEqual(body["action"], "answer")
        self.assertEqual(body["answer"], "not sure")


class ErrorAndOfflineTests(IslandSupport):
    def test_turn_error_shows_the_honest_card_with_retry(self) -> None:
        page = self.open_page(session_fixture(), fetch_stub([SSE_ERROR]))
        page.click("[data-pl-action='explain_directly']")
        retry = page.wait_for_selector("[data-pl-retry]", state="attached")
        error_card = page.inner_text(".pl-card--error")
        self.assertIn("can't think right now", error_card)
        # The retry replays the SAME client_turn_id (idempotency, §3.4).
        captures_before = page.evaluate("window.__plCaptures.length")
        retry.click()
        page.wait_for_function(f"window.__plCaptures.length > {captures_before}")
        captures = page.evaluate("window.__plCaptures")
        first_body = json.loads(captures[captures_before - 1]["body"])
        retry_body = json.loads(captures[captures_before]["body"])
        self.assertEqual(first_body["client_turn_id"], retry_body["client_turn_id"])
        self.assertEqual(retry_body["action"], "continue")

    def test_offline_event_disables_the_composer_with_a_reason(self) -> None:
        page = self.open_page(session_fixture(), fetch_stub([SSE]))
        page.evaluate("window.dispatchEvent(new Event('offline'))")
        page.wait_for_function(
            "document.querySelector('[data-pl-message]').disabled === true"
        )
        error_text = page.inner_text("[data-pl-error]")
        self.assertIn("offline", error_text.lower())
        page.evaluate("window.dispatchEvent(new Event('online'))")
        page.wait_for_function(
            "document.querySelector('[data-pl-message]').disabled === false"
        )


class ArtifactBridgeTests(IslandSupport):
    def test_artifact_event_builds_the_viewer_card_and_delegates_mount(self) -> None:
        page = self.open_page(session_fixture(), fetch_stub([SSE_ARTIFACT]))
        page.evaluate(
            "window.__artMounts = [];"
            "window.ZivonArtifactViewer = { mount: function (root) {"
            "  window.__artMounts.push(root ? root.nodeType : 0); } };"
        )
        page.click("[data-pl-action='explain_directly']")
        viewer = page.wait_for_selector(
            "[data-artifact-viewer][data-artifact-id='art42']", state="attached"
        )
        self.assertEqual(viewer.get_attribute("data-artifact-status"), "pending")
        self.assertEqual(viewer.get_attribute("data-artifact-src"), "")
        self.assertIn("/v1/personalized/artifacts/art42/status", page.content())
        # No iframe is created by the island — the bridge owns it.
        self.assertEqual(page.eval_on_selector_all("iframe", "els => els.length"), 0)
        mounts = page.evaluate("window.__artMounts.length")
        self.assertGreaterEqual(mounts, 1)


class InstructionsCounterTests(IslandSupport):
    def test_counter_updates_and_save_gates_on_change(self) -> None:
        page = self.open_page(instructions_fixture())
        save_disabled = page.evaluate(
            "document.querySelector('[data-pl-instructions-save]').disabled"
        )
        self.assertTrue(save_disabled, "Save is disabled while unchanged")
        page.fill("[data-pl-instructions-field]", "Explain step by step. Use Hinglish.")
        count = page.inner_text("[data-pl-instructions-count]")
        self.assertEqual(count, "35")
        save_disabled = page.evaluate(
            "document.querySelector('[data-pl-instructions-save]').disabled"
        )
        self.assertFalse(save_disabled)


if __name__ == "__main__":
    unittest.main()
