"""Tests for Wave E2 frontend completion (EX5B-FRONT):
- Shell injection contract (`docs/specs/frontend/shell-injection.md` §3 & §5):
  1. Content-only fixture + narration manifest -> all surfaces mount once, idempotent on re-entry.
  2. Missing manifest -> zero read-aloud buttons rendered; other surfaces still mount.
  3. Consent declined -> dock never mounts; read-aloud/report remain; no re-nag after reload.
  4. JS error injection -> thrown injection step leaves lesson readable and sims/checks working.
  5. Doctrine gate -> if `doctrineReady` is false, dock stays hidden and no dock DOM is built.
- Voice dock (§10.12): containment (`hidden`/`collapsed`/`expanded`), `localStorage["zivon.dock"]`,
  all 18 client states + visuals, barge-in with "▍cut off" transcript mark, anchor chip block ring,
  identity line once per device, typed fallback, help chips, memory view, keyboard (Space/Esc/Enter),
  44 px minimum target sizes.
- Read-aloud (§10.13): 44 px "सुनो / Listen" button per speakable block in manifest, `preload="none"`,
  play->stop, one block at a time, 2 px progress rule, echo guard (dock mic press stops narration),
  zero browser `SpeechSynthesis`.
- Consent gate (§10.14) & Privacy page (`SCR-PRIV-01` `/privacy/` `EL-PRV-001..005`):
  guardian checkbox gates Continue, `PUT /v1/consent`, data-class table, "Clear my data"
  wired to `/v1/data/challenge` -> `DELETE /v1/data` + local storage wipe.
- Provenance report (`F-COR-PROV-01` `EL-LES-01-040/041`): `POST /v1/reports` success + error draft retention.
- Degraded & credit notices (`EL-LES-01-070/071/072`): `session.ready.credit_state` + `agent.state`
  without cutting an in-progress turn.
- Telemetry (`F-OPS-TEL-01`): `ZivonEvents.flush()` to `POST /api/v1/events` with batching, retry-once,
  and no-op fallback.
- Language switcher (`F-WRP-LAN-01`): disabled chip with honest title when bundle absent; enabled
  when `window.ZIVON_I18N` has locale; persists `zivon_locale`.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
PRIVACY_HTML = FRONTEND / "privacy" / "index.html"
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()

CONTENT_ONLY_LESSON_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    f"<link rel='stylesheet' href='{ZIVON_CSS_URI}'></head><body>"
    "<header class='zn-lang-bar'><div class='zn-lang-in'>"
    "<span class='zn-lang-lab'>Language</span>"
    "<div class='zn-lang-row' role='radiogroup' aria-label='Language'>"
    "<button type='button' class='zn-chip' role='radio' aria-checked='true'>English</button>"
    "<button type='button' class='zn-chip' role='radio' aria-checked='false'>हिन्दी</button>"
    "<button type='button' class='zn-chip' role='radio' aria-checked='false'>Hinglish</button>"
    "</div></div></header>"
    "<main class='zn-page' data-generated-at='2026-11-10T00:00:00Z'>"
    "<header class='zn-header'><p class='zn-kicker'>class-9-physics</p>"
    "<h1 class='zn-title'>Laws of Motion</h1>"
    "<p class='zn-objectives-label'>After this lesson you can:</p>"
    "<ul class='zn-objectives'><li>State Newton's first law.</li></ul></header>"
    "<section class='zn-text' id='b-01'>"
    "<p>An object continues in uniform motion unless acted upon by an unbalanced force.</p>"
    "</section>"
    "<section class='zn-example' id='b-02'><h3>Worked example</h3>"
    "<p class='zn-example-problem'>Find net force when 10 N right and 4 N left act.</p>"
    "<ol><li>F_net = 10 - 4 = 6 N</li></ol>"
    "<p class='zn-answer'><span class='zn-answer-label'>Answer:</span> 6 N</p>"
    "</section>"
    "<fieldset class='zn-check' id='b-03' data-format='mcq' data-answer-index='0'>"
    "<legend>What happens when net force is zero?</legend>"
    "<label class='zn-opt'><input type='radio' name='check-b-03' value='0'><span>Velocity is constant</span></label>"
    "<label class='zn-opt'><input type='radio' name='check-b-03' value='1'><span>Acceleration increases</span></label>"
    "<button type='button' class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "</fieldset>"
    "<footer class='zn-footer'><p class='zn-sources'>NCERT Grade 9 Science</p></footer>"
    "</main>"
    f"<script src='{ZIVON_JS_URI}'></script>"
    "</body></html>"
)


class TestWaveE2Complete(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory
    _serve_ctx: Any = None
    _serve_base: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-e2-")

    @classmethod
    def tearDownClass(cls) -> None:
        ctx = getattr(cls, "_serve_ctx", None)
        if ctx is not None:
            ctx.__exit__(None, None, None)
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    def _open_html(self, html: str, name: str = "e2.html") -> tuple[Page, list[str]]:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(
            """try {
              window.__usedBrowserSpeechSynthesis = false;
              if (window.speechSynthesis && window.speechSynthesis.speak) {
                var origSpeak = window.speechSynthesis.speak.bind(window.speechSynthesis);
                window.speechSynthesis.speak = function () {
                  window.__usedBrowserSpeechSynthesis = true;
                  return origSpeak.apply(null, arguments);
                };
              }
            } catch (e) {}"""
        )
        f = Path(self._tmp.name) / name
        f.write_text(html, encoding="utf-8")
        page.goto(f.resolve().as_uri())
        return page, errors

    def _open_html_served(
        self, html: str, name: str = "served.html", *, consent: bool = False
    ) -> tuple[Page, list[str]]:
        """Open a lesson page over HTTP (production path).

        Network-touching surfaces (report, telemetry flush, consent sync,
        privacy clear-my-data) only exercise their real wiring when the
        document can fetch; a file:// page deliberately stays offline. Returns
        the page with its error list already closed over the server lifetime,
        so the caller must finish assertions before the returned page is closed.
        """
        web = tempfile.mkdtemp(prefix="zivon-e2-served-")
        web_path = Path(web)
        (web_path / "assets").symlink_to(FRONTEND / "assets", target_is_directory=True)
        # The shell auto-fetches ./manifest.json on lesson pages; serve an empty
        # one so a 404 never pollutes the console-error assertion.
        (web_path / "manifest.json").write_text("{}", encoding="utf-8")
        (web_path / name).write_text(
            html.replace(ZIVON_JS_URI, "assets/zivon.js").replace(
                ZIVON_CSS_URI, "assets/zivon.css"
            ),
            encoding="utf-8",
        )
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        if consent:
            page.add_init_script(
                "try { localStorage.setItem('zivon.consent', 'granted'); } catch (e) {}"
            )
        # The server is kept alive by the test class so the page can keep
        # fetching for the duration of the assertions.
        if getattr(self.__class__, "_serve_ctx", None) is None:
            self.__class__._serve_ctx = serve_static(web_path)
            base_url = self.__class__._serve_ctx.__enter__()
            self.__class__._serve_base = base_url
        page.goto(f"{self.__class__._serve_base}/{name}")
        return page, errors

    # A browser-realistic capture seam: getUserMedia resolves a fake stream and
    # AudioContext exposes a ScriptProcessor whose audio callback the test can
    # fire. This proves the press-and-hold path actually captures and sends
    # frames — it is not a stub of the code under test.
    FAKE_CAPTURE_SCRIPT = """
      (() => {
        window.__captureProcessors = [];
        window.__micTracksStopped = 0;
        const track = {
          getSettings: () => ({ sampleRate: 48000, channelCount: 1 }),
          stop: () => { window.__micTracksStopped += 1; }
        };
        const stream = {
          getTracks: () => [track],
          getAudioTracks: () => [track]
        };
        Object.defineProperty(navigator, 'mediaDevices', {
          configurable: true,
          value: { getUserMedia: async () => stream }
        });
        class FakeGain {
          constructor() { this.gain = { value: 1 }; }
          connect() {}
          disconnect() {}
        }
        class FakeSource { connect() {} disconnect() {} }
        class FakeProcessor extends FakeSource {
          constructor() { super(); this.onaudioprocess = null; window.__captureProcessors.push(this); }
        }
        class FakeAudioContext {
          constructor() {
            this.state = 'running';
            this.sampleRate = 48000;
            this.currentTime = 0;
            this.destination = {};
          }
          resume() { this.state = 'running'; }
          close() { return Promise.resolve(); }
          createGain() { return new FakeGain(); }
          createMediaStreamSource() { return new FakeSource(); }
          createScriptProcessor() { return new FakeProcessor(); }
        }
        window.AudioContext = FakeAudioContext;
        window.webkitAudioContext = FakeAudioContext;
      })();
    """

    def test_mic_capture_sends_pcm16_frames_and_first_press_is_queued(self) -> None:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(self.FAKE_CAPTURE_SCRIPT)
        f = Path(self._tmp.name) / "capture.html"
        f.write_text(CONTENT_ONLY_LESSON_HTML, encoding="utf-8")
        page.goto(f.resolve().as_uri())
        try:
            res = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  // --- M2: a start while CONNECTING is queued, never offline.
                  const mockFirst = VC.createMockServer({});
                  const c = VC.create({
                    createWebSocket: mockFirst.createWebSocket,
                    session_token: 'tok-first'
                  });
                  const states = [];
                  c.onStateChange((s) => states.push(s));
                  c.connect();
                  c.startListening('doubt'); // socket is still CONNECTING
                  await new Promise((r) => setTimeout(r, 40));
                  const firstPressState = c.getState();
                  const firstPressTypes = mockFirst.getSentMessages().map((m) => m.type);

                  // --- B1: press the dock mic -> permission -> connect ->
                  // capture -> frames on the wire -> release -> audio.end.
                  localStorage.setItem('zivon.consent', 'granted');
                  const mock = VC.createMockServer({});
                  const mount = window.ZivonVoiceDock.lazyMount({
                    clientOptions: { createWebSocket: mock.createWebSocket, session_token: 'tok-mic' }
                  });
                  const mic = mount.region.querySelector('.zn-dock-mic-strip');
                  mic.click();
                  await new Promise((r) => setTimeout(r, 80));
                  const dockClient = window.ZivonVoiceDock._activeClient;
                  const stateWhileHeld = dockClient.getState();
                  const captureActive = dockClient.getCaptureStats().active;
                  const processor = window.__captureProcessors[0];
                  // One 2048-frame block at 48 kHz -> resampled 16 kHz -> two
                  // full 20 ms frames (320 samples / 640 payload bytes each).
                  processor.onaudioprocess({
                    inputBuffer: { getChannelData: () => new Float32Array(2048).fill(0.5) }
                  });
                  const frames = mock.getBinaryFrames();
                  const frameStats = frames.map((fr) => ({
                    valid: fr.valid,
                    seq: fr.seq,
                    payload: fr.payload.length
                  }));
                  mic.click(); // release / stop
                  await new Promise((r) => setTimeout(r, 40));
                  const sentTypes = mock.getSentMessages().map((m) => m.type);
                  return {
                    firstPressState,
                    firstPressTypes,
                    stateWhileHeld,
                    captureActive,
                    captureFramesSent: dockClient.getCaptureStats().frames_sent,
                    frameStats,
                    sentTypes,
                    tracksStopped: window.__micTracksStopped
                  };
                }"""
            )
            # M2: queued behind session.ready, never `offline`.
            self.assertEqual(res["firstPressState"], "listening")
            self.assertIn("session.start", res["firstPressTypes"])
            self.assertIn("audio.start", res["firstPressTypes"])
            # B1: the capture path was exercised for real.
            self.assertEqual(res["stateWhileHeld"], "listening")
            self.assertTrue(res["captureActive"])
            self.assertEqual(res["captureFramesSent"], 2)
            self.assertEqual(len(res["frameStats"]), 2)
            self.assertTrue(all(f["valid"] for f in res["frameStats"]))
            self.assertEqual([f["seq"] for f in res["frameStats"]], [0, 1])
            self.assertTrue(all(f["payload"] == 640 for f in res["frameStats"]))
            self.assertIn("audio.end", res["sentTypes"])
            self.assertGreaterEqual(res["tracksStopped"], 1)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_first_press_never_reports_offline(self) -> None:
        """M2 regression guard on its own (state history, not just end state)."""
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "first_press.html")
        try:
            res = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({});
                  const c = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'tok-first'
                  });
                  const states = [];
                  c.onStateChange((s) => states.push(s));
                  c.connect();
                  c.startListening('doubt');
                  await new Promise((r) => setTimeout(r, 40));
                  return { states, state: c.getState() };
                }"""
            )
            self.assertNotIn("offline", res["states"])
            self.assertEqual(res["state"], "listening")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_disabled_lang_chip_is_a_no_op_and_bundle_swap_works(self) -> None:
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "lang_chip.html")
        try:
            res = page.evaluate(
                """() => {
                  localStorage.clear();
                  window.ZivonShell.mount();
                  const chips = Array.prototype.slice.call(
                    document.querySelectorAll('.zn-lang-row .zn-chip')
                  );
                  const hi = chips[1];
                  const langBefore = document.documentElement.lang;
                  hi.click();
                  const afterDisabled = {
                    enChecked: chips[0].getAttribute('aria-checked'),
                    hiChecked: hi.getAttribute('aria-checked'),
                    stored: localStorage.getItem('zivon_locale'),
                    lang: document.documentElement.lang,
                    status: (document.querySelector('.zn-lang-status') || {}).textContent || ''
                  };
                  // Bundle appears -> the same chip now really switches.
                  window.ZIVON_I18N = { hi: { strings: {}, ui_strings: {}, fallback_blocks: [] } };
                  window.ZivonShell.mount({ manifest: {} });
                  hi.click();
                  return {
                    afterDisabled,
                    langBefore,
                    afterEnabled: {
                      enChecked: chips[0].getAttribute('aria-checked'),
                      hiChecked: hi.getAttribute('aria-checked'),
                      stored: localStorage.getItem('zivon_locale'),
                      lang: document.documentElement.lang
                    }
                  };
                }"""
            )
            dis = res["afterDisabled"]
            self.assertEqual(dis["enChecked"], "true")
            self.assertEqual(dis["hiChecked"], "false")
            self.assertIsNone(dis["stored"], "a disabled chip must never persist")
            self.assertEqual(dis["lang"], res["langBefore"])
            self.assertIn("Not translated yet", dis["status"])
            en = res["afterEnabled"]
            self.assertEqual(en["hiChecked"], "true")
            self.assertEqual(en["enChecked"], "false")
            self.assertEqual(en["stored"], "hi")
            self.assertEqual(en["lang"], "hi")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_space_does_not_hijack_controls_and_anchor_follows_viewport(self) -> None:
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "dock_keys.html")
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({});
                  const mount = window.ZivonVoiceDock.lazyMount({
                    clientOptions: { createWebSocket: mock.createWebSocket, session_token: 'tok-k' }
                  });
                  const region = mount.region;
                  const typed = region.querySelector('.zn-dock-typed-input');
                  const space = () => new KeyboardEvent('keydown', { key: ' ', bubbles: true });
                  typed.focus();
                  typed.dispatchEvent(space());
                  await new Promise((r) => setTimeout(r, 30));
                  const stateAfterInputSpace = window.ZivonVoiceDock._activeClient
                    ? window.ZivonVoiceDock._activeClient.getState()
                    : 'no-client';

                  // Context: the block nearest the viewport centre wins, and
                  // the tutor's highlight frame rings that block by its
                  // internal id — the dock itself never prints the id.
                  const b03 = document.getElementById('b-03');
                  b03.style.marginTop = '1600px';
                  b03.scrollIntoView({ block: 'center' });
                  await new Promise((r) => setTimeout(r, 250));
                  const snap = window.ZivonStateMatrix.buildContextSnapshot();
                  window.ZivonStateMatrix.highlightBlocks([snap.block_id]);
                  return {
                    stateAfterInputSpace,
                    snapBlock: snap.block_id,
                    snapTitle: snap.block_title,
                    snapText: snap.block_text,
                    ringed: b03.classList.contains('zn-tutor-highlight'),
                    dockText: region.innerText
                  };
                }"""
            )
            self.assertIn(
                res["stateAfterInputSpace"],
                {"idle", "no-client"},
                "Space inside the typed input must not start the microphone",
            )
            self.assertEqual(res["snapBlock"], "b-03")
            self.assertTrue(res["ringed"], "the highlight frame rings the block itself")
            self.assertNotIn("b-03", res["dockText"])
            self.assertNotIn("b-03", res["snapTitle"])
            self.assertNotRegex(res["snapTitle"], r"b-\d")
            self.assertTrue(res["snapText"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_shell_injection_content_only_fixture_and_missing_manifest(self) -> None:
        # 1. Missing manifest -> no read-aloud buttons, but report, consent, footer privacy link mount
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "no_manifest.html")
        try:
            res = page.evaluate(
                """() => {
                  localStorage.removeItem('zivon.consent');
                  const firstMount = window.ZivonShell.mount();
                  const secondMount = window.ZivonShell.mount();
                  return {
                    idempotentSecond: secondMount.idempotent,
                    readAloudCount: document.querySelectorAll('.zn-read-aloud-btn').length,
                    reportBtns: document.querySelectorAll('[data-element-id="EL-LES-01-040"]').length,
                    consentSheets: document.querySelectorAll('[data-element-id="EL-LES-01-057"]').length,
                    privacyLinks: document.querySelectorAll('.zn-footer-privacy-link').length,
                    dockHiddenBeforeConsent: document.querySelector('.zn-voice-dock-region').hidden,
                    speechSynthesisUsed: Boolean(window.__usedBrowserSpeechSynthesis)
                  };
                }"""
            )
            self.assertTrue(res["idempotentSecond"])
            self.assertEqual(
                res["readAloudCount"],
                0,
                "missing manifest must render zero read-aloud buttons",
            )
            self.assertEqual(res["reportBtns"], 1)
            self.assertEqual(res["consentSheets"], 1)
            self.assertEqual(res["privacyLinks"], 1)
            self.assertTrue(res["dockHiddenBeforeConsent"])
            self.assertFalse(res["speechSynthesisUsed"])
            self.assertEqual(errors, [])

            # 2. Inject narration manifest -> read-aloud buttons appear ONLY for available blocks,
            #    and pressing the dock mic stops narration (echo guard).
            nar_res = page.evaluate(
                """() => {
                  const manifest = {
                    course_id: 'class-9-physics',
                    narration: {
                      available: true,
                      lang: 'en',
                      blocks: {
                        'b-01': { available: true, path: '/audio/class-9-physics/b-01.en.abc12345.opus', duration_ms: 4000 },
                        'b-02': { available: false },
                        'b-03': { available: true, path: '/audio/class-9-physics/b-03.en.def67890.opus', duration_ms: 3000 }
                      }
                    }
                  };
                  window.ZivonShell.mount({ manifest });
                  // Idempotent re-entry must not duplicate chrome/listeners.
                  window.ZivonShell.mount({ manifest });
                  const btns = document.querySelectorAll('.zn-read-aloud-btn');
                  const preloadVals = Array.from(document.querySelectorAll('.zn-read-aloud-audio')).map(
                    (a) => a.getAttribute('preload')
                  );
                  // Click first read-aloud button -> playing state
                  btns[0].click();
                  const activeAfterClick = window.ZivonReadAloud.getActiveBlockId();
                  const pressedAttr = btns[0].getAttribute('aria-pressed');
                  // Click second read-aloud button -> stops first, plays second
                  btns[1].click();
                  const activeAfterSecond = window.ZivonReadAloud.getActiveBlockId();
                  const firstPressedAfterSecond = btns[0].getAttribute('aria-pressed');
                  // Unlock consent & press dock mic -> stops read-aloud (echo guard)
                  const cb = document.querySelector('[data-element-id="EL-LES-01-059"]');
                  cb.checked = true;
                  cb.dispatchEvent(new Event('change'));
                  document.querySelector('[data-element-id="EL-LES-01-060"]').click();
                  document.querySelector('.zn-dock-mic-strip').click();
                  const activeAfterMic = window.ZivonReadAloud.getActiveBlockId();
                  return {
                    btnCount: btns.length,
                    preloadVals,
                    activeAfterClick,
                    pressedAttr,
                    activeAfterSecond,
                    firstPressedAfterSecond,
                    activeAfterMic
                  };
                }"""
            )
            self.assertEqual(nar_res["btnCount"], 2)
            self.assertEqual(nar_res["preloadVals"], ["none", "none"])
            self.assertEqual(nar_res["activeAfterClick"], "b-01")
            self.assertEqual(nar_res["pressedAttr"], "true")
            self.assertEqual(nar_res["activeAfterSecond"], "b-03")
            self.assertEqual(nar_res["firstPressedAfterSecond"], "false")
            self.assertIsNone(
                nar_res["activeAfterMic"],
                "pressing dock mic must stop read-aloud narration (echo guard)",
            )
        finally:
            page.close()

    def test_consent_decline_no_renag_and_error_isolation_and_doctrine_gate(
        self,
    ) -> None:
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "consent_flow.html")
        try:
            res = page.evaluate(
                """() => {
                  localStorage.clear();
                  window.ZivonShell.mount();
                  const sheet = document.querySelector('[data-element-id="EL-LES-01-057"]');
                  const visibleInitially = !sheet.hidden;
                  // Decline consent
                  document.querySelector('[data-element-id="EL-LES-01-061"]').click();
                  const hiddenAfterDecline = sheet.hidden;
                  const dockMountedAfterDecline = document.querySelector('.zn-voice-dock-region').getAttribute('data-zn-dock-mounted');
                  // Simulate reload by re-running mount()
                  window.ZivonShell.mount();
                  const stillHiddenOnReload = sheet.hidden;

                  // Test error injection in ZivonShell.mount -> lesson stays readable & check works
                  const errMount = window.ZivonShell.mount({ throwAtStep: 'report' });
                  const titleReadable = document.querySelector('h1.zn-title').textContent;

                  // Test doctrineReady = false gate
                  localStorage.setItem('zivon.consent', 'granted');
                  window.ZivonVoiceDock.doctrineReady = false;
                  const gatedRes = window.ZivonVoiceDock.lazyMount();
                  window.ZivonVoiceDock.doctrineReady = true;

                  return {
                    visibleInitially,
                    hiddenAfterDecline,
                    dockMountedAfterDecline,
                    stillHiddenOnReload,
                    errStepCaptured: Boolean(errMount.steps.report.error),
                    titleReadable,
                    gatedMounted: gatedRes.mounted
                  };
                }"""
            )
            self.assertTrue(res["visibleInitially"])
            self.assertTrue(res["hiddenAfterDecline"])
            self.assertIsNone(res["dockMountedAfterDecline"])
            self.assertTrue(
                res["stillHiddenOnReload"], "declined consent must never re-nag"
            )
            self.assertTrue(res["errStepCaptured"])
            self.assertEqual(res["titleReadable"], "Laws of Motion")
            self.assertFalse(res["gatedMounted"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_dock_containment_states_bargein_and_a11y(self) -> None:
        page, errors = self._open_html(CONTENT_ONLY_LESSON_HTML, "dock_states.html")
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.clear();
                  localStorage.setItem('zivon.consent', 'granted');
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({ holdSpeaking: true });
                  const mountRes = window.ZivonVoiceDock.lazyMount({
                    clientOptions: { createWebSocket: mock.createWebSocket, session_token: 'tok-1' }
                  });
                  const region = mountRes.region;
                  const initialContainment = window.ZivonVoiceDock.getContainment();

                  // One icon-only panel control: the strip opens, the sheet
                  // header closes. No text, no second "Hide" row.
                  const stripToggle = region.querySelector('.zn-dock-panel-toggle-strip');
                  const sheetToggle = region.querySelector('.zn-dock-panel-toggle-sheet');
                  const stripRect = stripToggle.getBoundingClientRect();
                  stripToggle.click();
                  const sheetRect = sheetToggle.getBoundingClientRect();
                  const afterOpen = {
                    containment: window.ZivonVoiceDock.getContainment(),
                    stored: localStorage.getItem('zivon.dock'),
                    expanded: sheetToggle.getAttribute('aria-expanded'),
                    toggleText: sheetToggle.textContent.trim(),
                    hasSvg: Boolean(sheetToggle.querySelector('svg')),
                    width: sheetRect.width,
                    height: sheetRect.height
                  };
                  sheetToggle.click();
                  const afterClose = {
                    containment: window.ZivonVoiceDock.getContainment(),
                    stored: localStorage.getItem('zivon.dock'),
                    expanded: stripToggle.getAttribute('aria-expanded')
                  };
                  // The hidden tab remains reachable (stored state / older devices)
                  window.ZivonVoiceDock.setContainment('hidden', true);
                  const afterHide = {
                    containment: window.ZivonVoiceDock.getContainment(),
                    stored: localStorage.getItem('zivon.dock'),
                    tabVisible: !region.querySelector('.zn-dock-tab').hidden
                  };
                  region.querySelector('.zn-dock-tab').click();
                  const afterTabClick = window.ZivonVoiceDock.getContainment();

                  // All 18 client states share ONE conditional status line.
                  // Every state the client can emit (18 canonical + the
                  // reconnect + error variants the F-table adds).
                  const allStates = [
                    'idle', 'requesting-permission', 'connecting', 'ready',
                    'listening', 'endpointing', 'thinking', 'speaking',
                    'speaking_text', 'interrupted', 'reconnecting', 'offline',
                    'error:mic-denied', 'error:mic-in-use', 'error:mic-constraint',
                    'error:unsupported-browser', 'error:no-input',
                    'error:no-match', 'error:system-error', 'error:timeout',
                    'error:auth.invalid', 'error:version.mismatch',
                    'error:quota-exhausted', 'text_only'
                  ];
                  const statusCount = region.querySelectorAll('.zn-dock-status').length;
                  const stateChecks = {};
                  for (const st of allStates) {
                    window.ZivonVoiceDock.renderAgentState(st, {});
                    const statusEl = region.querySelector('.zn-dock-status');
                    stateChecks[st] = {
                      attr: region.getAttribute('data-agent-state'),
                      statusHidden: statusEl.hidden,
                      statusText: statusEl.innerText.replace(/\\s+/g, ' ').trim(),
                      micDisabled: region.querySelector('.zn-dock-mic-sheet').disabled,
                      micPressed: region.querySelector('.zn-dock-mic-sheet').getAttribute('aria-pressed'),
                      retryHidden: region.querySelector('.zn-dock-retry').hidden
                    };
                  }

                  // Barge-in: the mic is the single stop target.
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'tok-1',
                    min_frames_before_speaking: 1
                  });
                  window.ZivonVoiceDock.bindClient(client);
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  client.startListening('doubt');
                  client.endAudio();
                  const stateBeforeBarge = client.getState();
                  region.querySelector('.zn-dock-mic-sheet').click();
                  const stateAfterBarge = client.getState();
                  const cutOffRows = region.querySelectorAll('[data-cut-off="true"]').length;

                  // 44 px minimum targets on the controls that survived.
                  window.ZivonVoiceDock.renderAgentState('error:no-match', {});
                  const micRect = region.querySelector('.zn-dock-mic-sheet').getBoundingClientRect();
                  const sendRect = region.querySelector('.zn-dock-typed-send').getBoundingClientRect();
                  const retryRect = region.querySelector('.zn-dock-retry').getBoundingClientRect();
                  const langRect = region.querySelector('.zn-dock-lang-btn').getBoundingClientRect();

                  return {
                    initialContainment,
                    afterOpen,
                    afterClose,
                    afterHide,
                    afterTabClick,
                    statusCount,
                    stateChecks,
                    stateBeforeBarge,
                    stateAfterBarge,
                    cutOffRows,
                    stripHeight: stripRect.height,
                    micHeight: micRect.height,
                    sendHeight: sendRect.height,
                    retryHeight: retryRect.height,
                    langHeight: langRect.height,
                    dockText: region.innerText
                  };
                }"""
            )
            self.assertEqual(res["initialContainment"], "collapsed")
            self.assertEqual(res["afterOpen"]["containment"], "expanded")
            self.assertEqual(res["afterOpen"]["stored"], "expanded")
            self.assertEqual(res["afterOpen"]["expanded"], "true")
            self.assertEqual(res["afterOpen"]["toggleText"], "", "no text on the panel control")
            self.assertTrue(res["afterOpen"]["hasSvg"])
            self.assertGreaterEqual(res["afterOpen"]["width"], 44)
            self.assertGreaterEqual(res["afterOpen"]["height"], 44)
            self.assertEqual(res["afterClose"]["containment"], "collapsed")
            self.assertEqual(res["afterClose"]["stored"], "collapsed")
            self.assertEqual(res["afterClose"]["expanded"], "false")
            self.assertEqual(res["afterHide"]["containment"], "hidden")
            self.assertEqual(res["afterHide"]["stored"], "hidden")
            self.assertTrue(res["afterHide"]["tabVisible"])
            self.assertEqual(res["afterTabClick"], "collapsed")

            self.assertEqual(res["statusCount"], 1, "one status line, never a status row")
            sc = res["stateChecks"]
            self.assertEqual(len(sc), 24)
            self.assertEqual(
                sc["error:quota-exhausted"]["attr"],
                "text_only",
                "quota-exhausted is the same student-facing state as text_only",
            )
            for quiet in (
                "idle",
                "requesting-permission",
                "connecting",
                "ready",
                "endpointing",
                "speaking",
                "speaking_text",
                "interrupted",
            ):
                self.assertTrue(
                    sc[quiet]["statusHidden"],
                    f"{quiet} must not show a status line (nothing changes for the student)",
                )
            self.assertIn("Sun rahe hain", sc["listening"]["statusText"])
            self.assertEqual(sc["listening"]["micPressed"], "true")
            self.assertIn("Soch rahe hain", sc["thinking"]["statusText"])
            self.assertIn("type karo", sc["offline"]["statusText"])
            self.assertIn("jud", sc["reconnecting"]["statusText"])
            self.assertIn("30 credits/day", sc["text_only"]["statusText"])
            self.assertTrue(sc["text_only"]["micDisabled"])
            self.assertTrue(sc["error:mic-denied"]["micDisabled"])
            for err in (
                "error:mic-in-use", "error:mic-constraint", "error:unsupported-browser",
                "error:no-input", "error:no-match", "error:system-error",
                "error:timeout", "error:auth.invalid", "error:version.mismatch",
            ):
                self.assertFalse(
                    sc[err]["statusHidden"], f"{err} must explain itself in one line"
                )
                self.assertTrue(sc[err]["statusText"], f"{err} needs words, not a bare icon")
            self.assertIn("Saaf sunai nahi diya", sc["error:no-match"]["statusText"])
            self.assertFalse(sc["error:no-match"]["retryHidden"])
            self.assertTrue(sc["idle"]["retryHidden"])
            self.assertNotRegex(res["dockText"], r"b-0\d")

            self.assertEqual(res["stateBeforeBarge"], "speaking")
            self.assertEqual(res["stateAfterBarge"], "listening")
            self.assertGreaterEqual(res["cutOffRows"], 1)
            self.assertGreaterEqual(res["micHeight"], 44)
            self.assertGreaterEqual(res["sendHeight"], 44)
            self.assertGreaterEqual(res["retryHeight"], 44)
            self.assertGreaterEqual(res["langHeight"], 44)
            self.assertGreaterEqual(res["stripHeight"], 44)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_privacy_page_report_telemetry_credit_notices_and_locale_bar(self) -> None:
        # 1. Test SCR-PRIV-01 (/privacy/index.html)
        self.assertTrue(
            PRIVACY_HTML.is_file(), "frontend/privacy/index.html must exist"
        )
        priv_page = self._browser.new_page()
        try:
            # Served over HTTP like production: the privacy page's clear-my-data
            # flow really calls /v1/data/challenge + DELETE /v1/data, and a
            # file:// document has no server to answer (the client then stays
            # offline by design), so the wiring is only observable over HTTP.
            with serve_static(FRONTEND) as fe_url:
                priv_page.goto(f"{fe_url}/privacy/index.html")
                priv_res = priv_page.evaluate(
                    """async () => {
                      localStorage.setItem('zivon.consent', 'granted');
                      localStorage.setItem('zivon_locale', 'hi');
                      const pseudoBefore = window.ZivonLocale.getDevicePseudoId();
                      const calls = [];
                      let pseudoAtDelete = null;
                      window.fetch = async (url, opts) => {
                        calls.push({ url, method: (opts && opts.method) || 'GET' });
                        if (url === '/v1/data') {
                          // The pseudonym must still exist while the wipe is
                          // being confirmed; it is deleted only after the ack.
                          pseudoAtDelete = localStorage.getItem('zivon.device_pseudo_id');
                        }
                        return {
                          ok: true,
                          json: async () => ({ confirm_token: 'tok-confirm-123', deleted: { sessions: 1 } })
                        };
                      };
                      window.ZivonPrivacy.wirePrivacyPage();
                      const hasTable = Boolean(document.querySelector('[data-element-id="EL-PRV-002"]'));
                      const hasBack = Boolean(document.querySelector('[data-element-id="EL-PRV-005"]'));
                      document.getElementById('zn-privacy-clear-btn').click();
                      const dialogOpen = !document.getElementById('zn-privacy-clear-dialog').hidden;
                      document.getElementById('zn-privacy-confirm-btn').click();
                      await new Promise((r) => setTimeout(r, 40));
                      return {
                        hasTable,
                        hasBack,
                        dialogOpen,
                        calls,
                        pseudoBefore,
                        pseudoAtDelete,
                        pseudoAfter: localStorage.getItem('zivon.device_pseudo_id'),
                        consentAfter: localStorage.getItem('zivon.consent'),
                        localeAfter: localStorage.getItem('zivon_locale'),
                        statusText: document.getElementById('zn-privacy-clear-status').textContent
                      };
                    }"""
                )
            self.assertTrue(priv_res["hasTable"])
            self.assertTrue(priv_res["hasBack"])
            self.assertTrue(priv_res["dialogOpen"])
            self.assertIsNone(priv_res["consentAfter"])
            self.assertIsNone(priv_res["localeAfter"])
            self.assertEqual(len(priv_res["calls"]), 2)
            self.assertIn("/v1/data/challenge", priv_res["calls"][0]["url"])
            self.assertEqual(priv_res["calls"][1]["url"], "/v1/data")
            self.assertEqual(priv_res["calls"][1]["method"], "DELETE")
            self.assertIn("erased", priv_res["statusText"])
            self.assertIsNotNone(priv_res["pseudoBefore"])
            self.assertEqual(
                priv_res["pseudoAtDelete"],
                priv_res["pseudoBefore"],
                "the pseudonym must survive until the server confirms the wipe",
            )
            self.assertIsNone(
                priv_res["pseudoAfter"],
                "the pseudonym is deleted LAST, after the server ack",
            )
        finally:
            priv_page.close()

        # 2. Test Provenance Report, Telemetry Flush, Credit Notices, and Language Bar on Lesson Page
        page, errors = self._open_html_served(
            CONTENT_ONLY_LESSON_HTML, "surfaces.html", consent=True
        )
        try:
            res = page.evaluate(
                """async () => {
                  const calls = [];
                  let failNextReport = true;
                  window.fetch = async (url, opts) => {
                    calls.push({ url, method: (opts && opts.method) || 'GET', body: opts && opts.body });
                    if (url === '/v1/reports' && failNextReport) {
                      failNextReport = false;
                      return { ok: false, status: 503 };
                    }
                    return { ok: true, status: 200, json: async () => ({ report_id: 'rep-1', accepted: 5 }) };
                  };

                  // A. Language bar: without ZIVON_I18N bundle, Hindi/Hinglish chips are aria-disabled with honest title
                  const chips = document.querySelectorAll('.zn-lang-row .zn-chip');
                  const enDisabled = chips[0].getAttribute('aria-disabled');
                  const hiDisabled = chips[1].getAttribute('aria-disabled');
                  const hiTitle = chips[1].getAttribute('title') || '';

                  // B. Provenance report: first submit fails (draft kept), second succeeds
                  const repBtn = document.querySelector('[data-element-id="EL-LES-01-040"]');
                  const repPanel = document.querySelector('[data-element-id="EL-LES-01-041"]');
                  repBtn.click();
                  const txtArea = repPanel.querySelector('.zn-report-text');
                  txtArea.value = ' Typo in step 1 ';
                  repPanel.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                  await new Promise((r) => setTimeout(r, 25));
                  const stateAfterFail = repPanel.getAttribute('data-report-state');
                  const draftPreserved = txtArea.value;
                  repPanel.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
                  await new Promise((r) => setTimeout(r, 25));
                  const stateAfterSuccess = repPanel.getAttribute('data-report-state');

                  // C. Credit notices: warn + text_only via session.ready & agent.state (never cuts in-progress turn)
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({ holdSpeaking: true });
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'tok-credit',
                    min_frames_before_speaking: 1
                  });
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  const sock = mock.getSocket();
                  sock.serverEmitJson({ type: 'session.ready', session_id: 's1', credit_state: 'warn' });
                  const warnVisible = !document.getElementById('zn-lesson-status-warn').hidden;
                  // Start speaking turn, then push text_only mid-turn -> turn is NOT cut until turn.end
                  client.startListening('doubt');
                  client.endAudio();
                  const stateMidTurnBeforePush = client.getState();
                  sock.serverEmitJson({ type: 'agent.state', state: 'text_only', credit_state: 'text_only' });
                  const stateMidTurnAfterPush = client.getState();
                  sock.serverEmitJson({ type: 'turn.end', turn_id: 'turn-1', end_reason: 'done' });
                  const stateAfterTurnEnd = client.getState();
                  const exhaustedVisible = !document.getElementById('zn-lesson-status-exhausted').hidden;

                  // D. Telemetry flush to POST /api/v1/events
                  const qBefore = window.ZivonEvents.getQueue().length;
                  const flushRes = await window.ZivonEvents.flush();

                  return {
                    enDisabled,
                    hiDisabled,
                    hiTitle,
                    stateAfterFail,
                    draftPreserved,
                    stateAfterSuccess,
                    warnVisible,
                    stateMidTurnBeforePush,
                    stateMidTurnAfterPush,
                    stateAfterTurnEnd,
                    exhaustedVisible,
                    qBefore,
                    flushRes,
                    eventPostSent: calls.some((c) => c.url === '/api/v1/events' && c.method === 'POST')
                  };
                }"""
            )
            self.assertIsNone(res["enDisabled"])
            self.assertEqual(res["hiDisabled"], "true")
            self.assertIn("not generated yet", res["hiTitle"])
            self.assertEqual(res["stateAfterFail"], "error-offline")
            self.assertEqual(res["draftPreserved"], " Typo in step 1 ")
            self.assertEqual(res["stateAfterSuccess"], "sent")
            self.assertTrue(res["warnVisible"])
            self.assertEqual(res["stateMidTurnBeforePush"], "speaking")
            self.assertEqual(
                res["stateMidTurnAfterPush"],
                "speaking",
                "credit exhaustion must never cut an in-progress turn",
            )
            self.assertEqual(res["stateAfterTurnEnd"], "text_only")
            self.assertTrue(res["exhaustedVisible"])
            self.assertGreater(res["qBefore"], 0)
            self.assertTrue(res["flushRes"]["ok"])
            self.assertTrue(res["eventPostSent"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_privacy_wipe_failure_is_honest_and_keeps_pseudonym(self) -> None:
        """A wipe that cannot reach the server deletes NOTHING and says so.

        The old UI said "server wipe queued" with no queue and had already
        deleted the pseudonym, so the wipe could never be retried. The
        doctrine (§10.14) only promises that clearing data removes it — so a
        failed clear keeps consent, preferences and the retry key intact.
        """
        priv_page = self._browser.new_page()
        try:
            with serve_static(FRONTEND) as fe_url:
                priv_page.goto(f"{fe_url}/privacy/index.html")
                res = priv_page.evaluate(
                    """async () => {
                      localStorage.setItem('zivon.consent', 'granted');
                      localStorage.setItem('zivon_locale', 'hi');
                      const pseudoBefore = window.ZivonLocale.getDevicePseudoId();
                      // Server unreachable: challenge never answers.
                      window.fetch = async () => { throw new TypeError('Failed to fetch'); };
                      window.ZivonPrivacy.wirePrivacyPage();
                      document.getElementById('zn-privacy-clear-btn').click();
                      document.getElementById('zn-privacy-confirm-btn').click();
                      await new Promise((r) => setTimeout(r, 40));
                      return {
                        pseudoBefore,
                        pseudoAfter: localStorage.getItem('zivon.device_pseudo_id'),
                        consentAfter: localStorage.getItem('zivon.consent'),
                        localeAfter: localStorage.getItem('zivon_locale'),
                        dialogOpen: !document.getElementById('zn-privacy-clear-dialog').hidden,
                        statusText: document.getElementById('zn-privacy-clear-status').textContent
                      };
                    }"""
                )
            self.assertEqual(res["pseudoAfter"], res["pseudoBefore"])
            self.assertEqual(res["consentAfter"], "granted")
            self.assertEqual(res["localeAfter"], "hi")
            self.assertTrue(res["dialogOpen"], "the retry affordance stays open")
            self.assertIn("NOT deleted", res["statusText"])
            self.assertNotIn("queued", res["statusText"].lower())
        finally:
            priv_page.close()

    def test_privacy_page_csp_relaxation_is_scoped(self) -> None:
        nginx = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        privacy_block = re.search(
            r"location \^~ /privacy/ \{(.*?)\n    \}", nginx, re.DOTALL
        )
        assert privacy_block is not None, (
            "/privacy/ needs its own connect-src 'self' block"
        )
        block = privacy_block.group(1)
        self.assertIn("connect-src 'self'", block)
        self.assertNotIn("media-src", block)
        # Server default stays locked for every other non-lesson page.
        self.assertIn("connect-src 'none'; base-uri 'none'\" always;", nginx)
        html = PRIVACY_HTML.read_text(encoding="utf-8")
        meta = re.search(
            r'<meta http-equiv="Content-Security-Policy" content="([^"]+)"', html
        )
        assert meta is not None, "privacy page meta CSP must mirror the header"
        self.assertIn("connect-src 'self'", meta.group(1))

    def test_manifest_autofetch_over_http_mounts_read_aloud_for_available_blocks(
        self,
    ) -> None:
        """The production path: the shell fetches ./manifest.json itself.

        Legacy file:// pages skip the fetch (a file:// document cannot fetch);
        this test serves the page + a real manifest over HTTP, so the auto-fetch
        branch that every deployed lesson page takes is covered end to end.
        """
        with tempfile.TemporaryDirectory(prefix="zivon-e2-http-") as web:
            web_path = Path(web)
            # Serve the repo's real assets (fonts included) so the page makes no
            # 404 requests: the shell under test is the shipped one.
            (web_path / "assets").symlink_to(
                FRONTEND / "assets", target_is_directory=True
            )
            (web_path / "manifest.json").write_text(
                json.dumps(
                    {
                        "course_id": "class-9-physics",
                        "narration": {
                            "available": True,
                            "blocks": {
                                "b-01": {
                                    "available": True,
                                    "path": "audio/b-01.opus",
                                    "duration_ms": 1200,
                                },
                            },
                        },
                    }
                ),
                encoding="utf-8",
            )
            html = CONTENT_ONLY_LESSON_HTML.replace(
                ZIVON_JS_URI, "assets/zivon.js"
            ).replace(ZIVON_CSS_URI, "assets/zivon.css")
            (web_path / "index.html").write_text(html, encoding="utf-8")

            with serve_static(web_path) as base_url:
                page = self._browser.new_page()
                errors: list[str] = []
                page.on(
                    "console",
                    lambda m: errors.append(m.text) if m.type == "error" else None,
                )
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.goto(f"{base_url}/index.html")
                try:
                    res = page.evaluate(
                        """async () => {
                          await new Promise((r) => setTimeout(r, 150));
                          return {
                            mounted: typeof window.__ZIVON_MANIFEST__ === 'object',
                            readAloud: document.querySelectorAll('.zn-read-aloud-btn').length,
                            preloads: Array.prototype.map.call(
                              document.querySelectorAll('.zn-read-aloud-audio'),
                              (a) => a.getAttribute('preload')),
                            speechUsed: Boolean(window.__usedBrowserSpeechSynthesis)
                          };
                        }"""
                    )
                    self.assertTrue(
                        res["mounted"], "manifest.json must be auto-fetched over HTTP"
                    )
                    self.assertEqual(
                        res["readAloud"],
                        1,
                        "exactly the manifest-available block gets a read-aloud control",
                    )
                    self.assertEqual(
                        res["preloads"],
                        ["none"],
                        "narration is lazy: never preload the audio on mount",
                    )
                    self.assertFalse(
                        res["speechUsed"],
                        "browser SpeechSynthesis must never be used (§10.13)",
                    )
                    self.assertEqual(errors, [])
                finally:
                    page.close()


if __name__ == "__main__":
    unittest.main()
