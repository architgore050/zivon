"""Tests for the frontend execution wave (EX5-FRONT):
- Routing + localized-route hook (DCR-001) + branded 404 page (SCR-404-01)
- Screen-state matrix walk-through across all 10 canonical states
- Locale switcher persistence (`localStorage["zivon_locale"]`), radiogroup a11y,
  untranslated notice (`INF-087`), and ADR-0007 `device_pseudo_id` UUIDv4
- Event instrumentation (`ZivonEvents` queue, SP3 `EVT-F01..F12` mapping,
  privacy redaction/bucketing/hashing)
- Voice loop WS client state machine (`ZivonVoiceClient`) + mock WS server +
  binary framing (ADR-0020) + gain-value ducking bookkeeping (ADR-0010) +
  reconnect/backoff + barge-in + degraded text fallback + teardown cleanup +
  DCR-002 standing guard verification. NOTE: this is a protocol/state-machine
  harness — no Opus decode or AudioContext playback is implemented or claimed.
- Static multilingual SEO (`scripts/gen-seo-files.py`: `sitemap.xml`,
  `robots.txt`, JSON-LD `LearningResource`/`Course`, hreflang gating, landing
  OG/canonical metadata)
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

import testing.frontend  # noqa: F401 - loud Playwright import guard

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
INDEX = FRONTEND / "index.html"
NOT_FOUND = FRONTEND / "404.html"
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()
SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def _load_seo_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "gen_seo_files", REPO_ROOT / "scripts" / "gen-seo-files.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


LESSON_SYNTHETIC_HTML = (
    "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
    "<meta name='viewport' content='width=device-width, initial-scale=1'>"
    f"<link rel='stylesheet' href='{ZIVON_CSS_URI}'></head><body>"
    "<header class='zn-lang-bar'><div class='zn-lang-in'>"
    "<span class='zn-lang-lab'>Language</span>"
    "<div class='zn-lang-row' role='radiogroup' aria-label='Language'>"
    "<button type='button' class='zn-chip' role='radio' "
    "aria-checked='true'>English</button>"
    "<button type='button' class='zn-chip' role='radio' "
    "aria-checked='false'>हिन्दी</button>"
    "<button type='button' class='zn-chip' role='radio' "
    "aria-checked='false'>Hinglish</button>"
    "</div></div></header>"
    "<main class='zn-page' data-generated-at='2026-11-09T00:00:00Z'>"
    "<header class='zn-header'><p class='zn-kicker'>class-9-physics</p>"
    "<h1 class='zn-title'>Motion</h1>"
    "<p class='zn-objectives-label'>After this lesson you can:</p>"
    "<ul class='zn-objectives'><li>Define displacement and velocity.</li></ul></header>"
    "<section class='zn-text' id='b-01'>"
    "<p>Velocity is displacement divided by time interval.</p></section>"
    "<section class='zn-example' id='b-02'><h3>Worked example</h3>"
    "<p class='zn-example-problem'>Find velocity for 20 m in 4 s.</p>"
    "<ol><li>v = 20 / 4</li></ol>"
    "<p class='zn-answer'><span class='zn-answer-label'>Answer:</span> 5 m/s</p>"
    "</section>"
    "<section class='zn-reveal' id='b-03'><h3>Derivation steps</h3>"
    "<details class='zn-reveal-step'><summary>Step 1</summary>"
    "<p>Write delta x / delta t.</p></details></section>"
    "<figure class='zn-diagram' id='b-04'>"
    "<div class='zn-diagram-svg'>"
    "<svg id='b-ig-04' viewBox='0 0 280 180' aria-label='Displacement arrow'>"
    "<line x1='20' y1='90' x2='260' y2='90' stroke='#1C1B18' stroke-width='3'/>"
    "</svg></div>"
    "<figcaption>Scale: 1 cm = 2 m.</figcaption></figure>"
    "<section class='zn-sim zn-sim-b-05' id='b-05' data-sim-id='b-05'>"
    "<h3>Constant velocity</h3>"
    "<div class='zn-sim-controls'>"
    "<label class='zn-sim-control'><span>Velocity v (m/s)</span>"
    "<input type='range' data-control='v' min='0' max='10' step='1' value='5'>"
    "<output>5</output></label>"
    "<button type='button' class='zn-sim-reset'>Reset</button>"
    "</div>"
    "<div class='zn-sim-canvas-wrap'>"
    "<canvas class='zn-sim-canvas' width='480' height='320'></canvas></div>"
    "<p class='zn-sim-read' aria-live='polite'></p>"
    "<p class='zn-sim-desc'>Adjust v to see position change.</p></section>"
    "<fieldset class='zn-check' id='b-06' data-format='mcq' data-answer-index='0'>"
    "<legend>Which quantity has direction?</legend>"
    "<label class='zn-opt'><input type='radio' name='check-b-06' value='0'>"
    "<span>Velocity</span></label>"
    "<label class='zn-opt'><input type='radio' name='check-b-06' value='1'>"
    "<span>Speed</span></label>"
    "<button type='button' class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "<details class='zn-check-why'><summary>Why?</summary>"
    "<p>Velocity is a vector.</p></details></fieldset>"
    "<div id='zn-class-sections'></div>"
    "<p id='zn-offline-chip' hidden>Offline - this page keeps working while offline; the voice tutor needs a connection.</p>"
    "<footer class='zn-footer'><p class='zn-sources'>NCERT Grade 9 Science</p></footer>"
    "</main>"
    f"<script src='{ZIVON_JS_URI}'></script>"
    "<script>"
    "window.ZivonSim.register('b-05', {"
    "  init: function (ctx) {},"
    "  draw: function (ctx) {"
    "    ctx.g.fillStyle = '#F6F0CF';"
    "    ctx.g.fillRect(0, 0, ctx.width, ctx.height);"
    "  }"
    "});"
    "</script></body></html>"
)


class TestFrontendFeatures(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-feat-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    def _open_html(self, html: str, name: str = "test.html") -> tuple[Page, list[str]]:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on(
            "console", lambda m: errors.append(m.text) if m.type == "error" else None
        )
        page.on("pageerror", lambda e: errors.append(str(e)))
        f = Path(self._tmp.name) / name
        f.write_text(html, encoding="utf-8")
        page.goto(f.resolve().as_uri())
        return page, errors

    def test_branded_404_page_and_nginx_contract(self) -> None:
        self.assertTrue(NOT_FOUND.is_file(), "frontend/404.html must exist (spec C1)")
        nginx_conf = (REPO_ROOT / "docker" / "nginx.conf").read_text(encoding="utf-8")
        self.assertIn("error_page 404 /404.html;", nginx_conf)
        dockerfile_fe = (REPO_ROOT / "Dockerfile.frontend").read_text(encoding="utf-8")
        self.assertIn("COPY frontend/404.html /opt/zivon-shell/404.html", dockerfile_fe)

        page = self._browser.new_page()
        try:
            page.goto(NOT_FOUND.resolve().as_uri())
            self.assertIn("Page not found", page.title())
            el_title = page.query_selector('[data-element-id="EL-404-01-001"]')
            el_body = page.query_selector('[data-element-id="EL-404-01-002"]')
            back = page.query_selector('[data-element-id="EL-404-01-003"]')
            self.assertIsNotNone(el_title)
            self.assertIsNotNone(el_body)
            self.assertIsNotNone(back)
            assert back is not None
            self.assertEqual(back.get_attribute("href"), "/")
            # §0 scope guard: 404 shell page must not contain lesson-only language bar
            self.assertIsNone(page.query_selector(".zn-lang-bar"))
        finally:
            page.close()

    def test_router_and_localized_route_hook(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "router.html")
        try:
            res = page.evaluate(
                """() => {
                  const R = window.ZivonRouter;
                  const p = '/courses/class-9-physics/motion/';
                  return {
                    home: R.parseRoute('/'),
                    lessonEn: R.parseRoute(p + 'index.html'),
                    lessonHi: R.parseRoute('/hi' + p),
                    lessonHinglish: R.parseRoute('/hi-Latn' + p),
                    missing: R.parseRoute('/unknown/path'),
                    builtHi: R.buildLocalizedHref(p, 'hi'),
                    builtHinglish: R.buildLocalizedHref(p, 'hinglish'),
                    builtEn: R.buildLocalizedHref('/hi' + p, 'en'),
                  };
                }"""
            )
            canon = "/courses/class-9-physics/motion/"
            self.assertEqual(res["home"]["screen"], "SCR-HOME-01")
            self.assertEqual(res["lessonEn"]["screen"], "SCR-LES-01")
            self.assertEqual(res["lessonEn"]["course_id"], "class-9-physics")
            self.assertEqual(res["lessonEn"]["topic_slug"], "motion")
            self.assertEqual(res["lessonHi"]["locale"], "hi")
            self.assertEqual(res["lessonHi"]["canonical_path"], canon)
            self.assertEqual(res["lessonHinglish"]["locale"], "hi-Latn")
            self.assertEqual(res["missing"]["screen"], "SCR-404-01")
            self.assertEqual(res["builtHi"], "/hi" + canon)
            self.assertEqual(res["builtHinglish"], "/hi-Latn" + canon)
            self.assertEqual(res["builtEn"], canon)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_locale_switcher_persistence_and_device_pseudonym(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "locale.html")
        try:
            initial = page.evaluate(
                """() => {
                  localStorage.removeItem('zivon_locale');
                  localStorage.removeItem('zivon.device_pseudo_id');
                  const devId = window.ZivonLocale.getDevicePseudoId();
                  return {
                    devId: devId,
                    savedLang: window.ZivonLocale.getSavedLang(),
                    docLang: document.documentElement.lang
                  };
                }"""
            )
            uuid_re = (
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
                r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
            )
            self.assertRegex(initial["devId"], uuid_re)
            self.assertEqual(initial["savedLang"], "en")

            # Honest chip contract (EX5B): a locale with no generated bundle is
            # aria-disabled and not clickable; injecting the bundle enables it.
            chips = page.query_selector_all(".zn-lang-row .zn-chip")
            self.assertEqual(len(chips), 3)
            self.assertEqual(
                chips[1].get_attribute("aria-disabled"),
                "true",
                "a locale with no bundle must be aria-disabled, never silently accepted",
            )
            page.evaluate(
                """() => {
                  window.ZIVON_I18N = window.ZIVON_I18N || {};
                  window.ZIVON_I18N.hi = { strings: {}, ui_strings: {} };
                  const chip = document.querySelectorAll('.zn-lang-row .zn-chip')[1];
                  chip.removeAttribute('aria-disabled');
                  chip.removeAttribute('title');
                }"""
            )
            chips[1].click()
            after_click = page.evaluate(
                """() => {
                  const cs = document.querySelectorAll('.zn-chip');
                  return {
                    stored: localStorage.getItem('zivon_locale'),
                    c0: cs[0].getAttribute('aria-checked'),
                    c1: cs[1].getAttribute('aria-checked'),
                    docLang: document.documentElement.lang
                  };
                }"""
            )
            self.assertEqual(after_click["stored"], "hi")
            self.assertEqual(after_click["c0"], "false")
            self.assertEqual(after_click["c1"], "true")
            # With a bundle present the swap is real (EX5B): documentElement.lang
            # follows the selected locale. Without a bundle the chip is
            # aria-disabled and the page keeps reviewed English (asserted above).
            self.assertEqual(after_click["docLang"], "hi")

            # Reload page -> Hindi chip is preselected from localStorage['zivon_locale']
            page.goto((Path(self._tmp.name) / "locale.html").resolve().as_uri())
            preselected = page.evaluate(
                "document.querySelectorAll('.zn-chip')[1].getAttribute('aria-checked')"
            )
            self.assertEqual(preselected, "true")

            # Q11 migration: the legacy key alone still preselects a chip, and
            # the next explicit activation writes ONLY the owner key.
            page.evaluate(
                """() => {
                  localStorage.removeItem('zivon_locale');
                  localStorage.setItem('zivon.lang', 'hi-Latn');
                }"""
            )
            page.goto((Path(self._tmp.name) / "locale.html").resolve().as_uri())
            legacy = page.evaluate(
                """() => ({
                  hinglish: document.querySelectorAll('.zn-chip')[2].getAttribute('aria-checked'),
                  ownerKey: localStorage.getItem('zivon_locale')
                })"""
            )
            self.assertEqual(legacy["hinglish"], "true")
            self.assertIsNone(legacy["ownerKey"])
            page.query_selector_all(".zn-lang-row .zn-chip")[0].click()
            rewritten = page.evaluate(
                """() => ({
                  owner: localStorage.getItem('zivon_locale'),
                  legacy: localStorage.getItem('zivon.lang')
                })"""
            )
            self.assertEqual(rewritten["owner"], "en")
            self.assertEqual(rewritten["legacy"], "hi-Latn")

            # Test keyboard ArrowRight navigation on radiogroup
            page.evaluate(
                """() => {
                  const chip1 = document.querySelectorAll('.zn-chip')[1];
                  const ev = new KeyboardEvent('keydown', {
                    key: 'ArrowRight',
                    bubbles: true
                  });
                  chip1.dispatchEvent(ev);
                }"""
            )
            after_key = page.evaluate(
                """() => {
                  const cs = document.querySelectorAll('.zn-chip');
                  return {
                    stored: localStorage.getItem('zivon_locale'),
                    c2: cs[2].getAttribute('aria-checked')
                  };
                }"""
            )
            self.assertEqual(after_key["stored"], "hi-Latn")
            self.assertEqual(after_key["c2"], "true")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_untranslated_notice_reads_real_i18n_shape(self) -> None:
        # INF-087: the notice must read the shape factory/render.py actually
        # emits — window.ZIVON_I18N[locale].fallback_blocks — not the invented
        # window.ZIVON_I18N_BUNDLE key map. Only fallback blocks get a notice.
        bundle = (
            "<script>window.ZIVON_I18N={"
            "'hi':{strings:{'b-01':'x'},ui_strings:{},fallback_blocks:['b-02']},"
            "'en':{strings:{},ui_strings:{},fallback_blocks:[]}};</script>"
        )
        html = LESSON_SYNTHETIC_HTML.replace(
            f"<script src='{ZIVON_JS_URI}'></script>",
            bundle + f"<script src='{ZIVON_JS_URI}'></script>",
        )
        page, errors = self._open_html(html, "i18n.html")
        try:
            page.query_selector_all(".zn-lang-row .zn-chip")[1].click()
            hi = page.evaluate(
                """() => ({
                  b01: Boolean(document.querySelector('#b-01 .zn-untranslated-notice')),
                  b02: Boolean(document.querySelector('#b-02 .zn-untranslated-notice')),
                  total: document.querySelectorAll('.zn-untranslated-notice').length
                })"""
            )
            self.assertFalse(hi["b01"], "b-01 is translated: no notice")
            self.assertTrue(hi["b02"], "b-02 is in fallback_blocks: notice required")
            self.assertEqual(hi["total"], 1)
            page.query_selector_all(".zn-lang-row .zn-chip")[0].click()
            self.assertEqual(
                page.evaluate(
                    "document.querySelectorAll('.zn-untranslated-notice').length"
                ),
                0,
            )
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_events_instrumentation_and_privacy_rules(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "events.html")
        try:
            # EVT-F03 fires on VIEW, not load: bring the sim into the viewport
            # and let the IntersectionObserver deliver before asserting.
            page.evaluate(
                "document.getElementById('b-05').scrollIntoView({block: 'center'})"
            )
            page.wait_for_timeout(300)
            # Verify initial boot emitted EVT-lesson_viewed and (on view) EVT-sim_opened
            boot_evts = page.evaluate("window.ZivonEvents.getQueue()")
            evt_names = [e["evt"] for e in boot_evts]
            self.assertIn("EVT-lesson_viewed", evt_names)
            self.assertIn("EVT-sim_opened", evt_names)

            # Interact with slider (three rapid inputs), check (wrong then right),
            # reveal, and language chip
            page.evaluate(
                """() => {
                  const inp = document.querySelector('[data-control="v"]');
                  for (const v of ['6', '7', '8']) {
                    inp.value = v;
                    inp.dispatchEvent(new Event('input', {bubbles: true}));
                  }
                }"""
            )
            page.click("input[value='1']")
            page.click(".zn-check-btn")
            page.click("input[value='0']")
            page.click(".zn-check-btn")
            page.evaluate(
                """() => {
                  const det = document.querySelector('.zn-reveal-step');
                  det.open = true;
                  det.dispatchEvent(new Event('toggle'));
                }"""
            )
            q = page.evaluate("window.ZivonEvents.getQueue()")
            by_evt = {e["evt"]: e for e in q}
            sim_events = [e for e in q if e["evt"] == "EVT-sim_control_changed"]
            self.assertEqual(
                len(sim_events),
                1,
                "EVT-F04 must throttle to one event per 5 s (interactions still counted)",
            )
            self.assertIn("EVT-sim_control_changed", by_evt)
            self.assertEqual(
                by_evt["EVT-sim_control_changed"]["props"]["interactions"], 1
            )
            self.assertEqual(by_evt["EVT-sim_control_changed"]["evt_id"], "EVT-F04")
            self.assertEqual(
                by_evt["EVT-sim_control_changed"]["event"], "frontend.sim_interact"
            )
            self.assertIn(
                by_evt["EVT-sim_control_changed"]["props"]["value_bucket"],
                {"q1", "q2", "q3", "q4"},
            )

            self.assertIn("EVT-check_answered", by_evt)
            self.assertEqual(by_evt["EVT-check_answered"]["evt_id"], "EVT-F05")
            self.assertNotIn("option_text", by_evt["EVT-check_answered"]["props"])
            self.assertIn("EVT-check_retried", by_evt)
            self.assertEqual(by_evt["EVT-check_retried"]["props"]["attempt_no"], 2)

            self.assertIn("EVT-reveal_opened", by_evt)
            self.assertEqual(by_evt["EVT-reveal_opened"]["evt_id"], "EVT-F02")
            self.assertNotIn(
                "dwell_bucket",
                by_evt["EVT-reveal_opened"]["props"],
                "dwell must be measured, never fabricated",
            )
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_state_matrix_walkthrough_and_dcr002_guard(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "states.html")
        try:
            res = page.evaluate(
                """() => {
                  const dockStatus = window.ZivonVoiceDock.lazyMount();
                  const states = window.ZivonStateMatrix.CANONICAL_STATES;
                  window.ZivonStateMatrix.applyState('offline');
                  const offEl = document.getElementById('zn-lesson-status-offline');
                  const offlineVisible = Boolean(offEl && !offEl.hidden);

                  window.ZivonStateMatrix.applyState('over-credit-budget');
                  const qEl = document.getElementById('zn-lesson-status-exhausted');
                  const quotaVisible = Boolean(qEl && !qEl.hidden);

                  window.ZivonStateMatrix.applyState('untranslated');
                  const notices = document.querySelectorAll('.zn-untranslated-notice');
                  const untranslatedCount = notices.length;

                  const snap = window.ZivonStateMatrix.buildContextSnapshot('b-05');
                  // Empty state must clear the class-grouped sections too.
                  document.getElementById('zn-class-sections').innerHTML =
                    '<section class="zn-class-section">stale</section>';
                  window.ZivonStateMatrix.applyState('empty');
                  const sectionsLeft =
                    document.querySelectorAll('#zn-class-sections > *').length;
                  return {
                    dockStatus,
                    statesCount: states.length,
                    offlineVisible,
                    quotaVisible,
                    untranslatedCount,
                    snapSize: JSON.stringify(snap).length,
                    snapSimId: snap.sim_id,
                    snapHasSvgId: snap.visible_blocks.some((b) => b.id === 'b-ig-04'),
                    sectionsLeft
                  };
                }"""
            )
            # DCR-002 is now closed (doctrineReady = true); before consent is granted,
            # lazyMount() gates on consent_required (§10.14), and with consent granted
            # it mounts the §10.12 bottom sheet.
            self.assertTrue(page.evaluate("window.ZivonVoiceDock.doctrineReady"))
            self.assertFalse(res["dockStatus"]["mounted"])
            self.assertEqual(res["dockStatus"]["reason"], "consent_required")
            mounted_after = page.evaluate(
                "(() => { localStorage.setItem('zivon.consent', 'granted'); return window.ZivonVoiceDock.lazyMount().mounted; })()"
            )
            self.assertTrue(mounted_after)
            self.assertEqual(res["statesCount"], 10)
            self.assertTrue(res["offlineVisible"])
            self.assertTrue(res["quotaVisible"])
            self.assertGreaterEqual(res["untranslatedCount"], 2)
            self.assertLessEqual(res["snapSize"], 4096)
            self.assertEqual(res["snapSimId"], "b-05")
            # SVGAnimatedString className must not throw; the id'd svg is listed.
            self.assertTrue(res["snapHasSvgId"])
            self.assertEqual(res["sectionsLeft"], 0)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_ws_client_state_machine_and_mock_server(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "voice.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({ highlightBlocks: ['b-05'] });
                  const history = [];
                  const track = {
                    getSettings: () => ({ sampleRate: 16000, channelCount: 1 })
                  };
                  const fakeNav = {
                    mediaDevices: {
                      getUserMedia: async () => ({ getAudioTracks: () => [track] })
                    }
                  };
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    navigator: fakeNav,
                    min_buffer_frames: 2
                  });
                  client.onStateChange((next) => history.push(next));

                  const perm = await client.requestMicPermission();
                  client.connect();
                  await new Promise((r) => setTimeout(r, 20));
                  const stateAfterConnect = client.getState();

                  client.startListening('doubt');
                  client.sendAudioChunk(new Uint8Array(320), false);
                  client.sendAudioChunk(new Uint8Array(320), true);
                  client.endAudio();
                  const stateAfterTurn = client.getState();
                  const metrics = client.getLastTurnMetrics();
                  const b05 = document.getElementById('b-05');
                  const highlighted = b05.classList.contains('zn-tutor-highlight');

                  // Test barge-in while speaking
                  const mockHold = VC.createMockServer({ holdSpeaking: true });
                  const c2 = VC.create({
                    createWebSocket: mockHold.createWebSocket,
                    navigator: fakeNav,
                    min_buffer_frames: 2
                  });
                  c2.connect();
                  await new Promise((r) => setTimeout(r, 20));
                  c2.startListening();
                  c2.endAudio();
                  const speakingState = c2.getState();
                  const speakingGain = c2.getGainValues();
                  c2.bargeIn('user_speech');
                  const afterBargeIn = c2.getState();
                  const afterBargeInGain = c2.getGainValues();

                  // Test mic-denied + degraded typed fallback + offline queue
                  const deniedNav = {
                    mediaDevices: {
                      getUserMedia: async () => { throw new Error('NotAllowedError'); }
                    }
                  };
                  const c3 = VC.create({
                    createWebSocket: mock.createWebSocket,
                    navigator: deniedNav
                  });
                  await c3.requestMicPermission();
                  const deniedState = c3.getState();
                  // While WS not connected, typed doubt queues in memory & sets offline
                  c3.sendTypedDoubt('Why is acceleration constant in free fall?');
                  const offlineState = c3.getState();
                  const queuedCount = c3.getQueuedTypedDoubts().length;

                  return {
                    permOk: perm.ok,
                    stateAfterConnect,
                    stateAfterTurn,
                    history,
                    binaryFramesSent: mock.getBinaryFrames().length,
                    firstFrameValid: mock.getBinaryFrames()[0].valid,
                    metricsPresent: Boolean(metrics && metrics.turn_id),
                    highlighted,
                    speakingState,
                    speakingGain,
                    afterBargeIn,
                    afterBargeInGain,
                    deniedState,
                    offlineState,
                    queuedCount
                  };
                }"""
            )
            self.assertTrue(result["permOk"])
            self.assertEqual(result["stateAfterConnect"], "ready")
            self.assertEqual(result["stateAfterTurn"], "ready")
            self.assertIn("requesting-permission", result["history"])
            self.assertIn("connecting", result["history"])
            self.assertIn("listening", result["history"])
            self.assertIn("endpointing", result["history"])
            self.assertIn("thinking", result["history"])
            self.assertIn("speaking", result["history"])
            self.assertEqual(result["binaryFramesSent"], 2)
            self.assertTrue(result["firstFrameValid"])
            self.assertTrue(result["metricsPresent"])
            self.assertTrue(result["highlighted"])
            self.assertEqual(result["speakingState"], "speaking")
            self.assertAlmostEqual(
                result["speakingGain"]["mic"],
                0.2,
                msg="agent playback must duck the mic gain bookkeeping value",
            )
            self.assertEqual(result["speakingGain"]["agent"], 1.0)
            self.assertEqual(result["afterBargeIn"], "listening")
            self.assertEqual(result["afterBargeInGain"]["mic"], 1.0)
            self.assertEqual(result["afterBargeInGain"]["agent"], 1.0)
            self.assertEqual(result["deniedState"], "error:mic-denied")
            self.assertEqual(result["offlineState"], "offline")
            self.assertEqual(result["queuedCount"], 1)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_reconnect_backoff_and_stale_socket(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "reconnect.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({});
                  const sockets = [];
                  const factory = (url) => {
                    const s = mock.createWebSocket(url);
                    sockets.push(s);
                    return s;
                  };
                  const history = [];
                  const client = VC.create({
                    createWebSocket: factory,
                    session_token: 'test-token',
                    reconnect_base_ms: 10,
                    reconnect_max_ms: 40
                  });
                  client.onStateChange((s) => history.push(s));
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));

                  // 1. A stale socket replaced by connect() must not mark the
                  //    live connection offline when it closes.
                  const stale = sockets[0];
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  stale.simulateDrop();
                  const stateAfterStaleClose = client.getState();

                  // 2. An unexpected drop recovers through capped backoff.
                  mock.getSocket().simulateDrop();
                  const offlineAt = client.getState();
                  await new Promise((r) => setTimeout(r, 500));
                  return {
                    connections: sockets.length,
                    stateAfterStaleClose,
                    offlineAt,
                    finalState: client.getState(),
                    history
                  };
                }"""
            )
            self.assertEqual(
                result["stateAfterStaleClose"],
                "ready",
                "a replaced socket's close must not mark the live link offline",
            )
            self.assertEqual(result["offlineAt"], "offline")
            self.assertGreaterEqual(result["connections"], 3)
            self.assertEqual(result["finalState"], "ready")
            self.assertIn("offline", result["history"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_keepalive_pong_timeout_closes_socket(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "keepalive.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({});
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'test-token',
                    max_reconnect_attempts: 0
                  });
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  const stillOpen = client.checkKeepalive(Date.now());
                  const timedOut = client.checkKeepalive(Date.now() + 31000);
                  return {
                    stillOpen,
                    timedOut,
                    state: client.getState(),
                    socketState: mock.getSocket().readyState
                  };
                }"""
            )
            self.assertTrue(result["stillOpen"])
            self.assertFalse(result["timedOut"])
            self.assertEqual(result["state"], "offline")
            self.assertEqual(
                result["socketState"],
                3,
                "pong timeout must CLOSE the stale socket before going offline",
            )
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_disconnect_and_pagehide_release_microphone(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "cleanup.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({});
                  const makeStream = (sink, tag) => {
                    const track = { stop: () => sink.push(tag) };
                    return {
                      getTracks: () => [track],
                      getAudioTracks: () => [track]
                    };
                  };
                  const makeCtx = (sink, tag) => ({
                    state: 'running',
                    createGain: () => ({ gain: { value: 1 } }),
                    close: () => { sink.push(tag); }
                  });
                  const stops = [];
                  const stream = makeStream(stops, 'disconnect-track');
                  const ctx = makeCtx(stops, 'disconnect-ctx');
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    navigator: { mediaDevices: { getUserMedia: async () => stream } },
                    audioContext: ctx,
                    session_token: 'test-token'
                  });
                  await client.requestMicPermission();
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  client.disconnect();
                  const afterDisconnect = {
                    state: client.getState(),
                    stops: stops.slice(),
                    socketState: mock.getSocket().readyState
                  };

                  // pagehide uses the module-scope registry, not a per-client
                  // listener left behind after teardown.
                  const phStops = [];
                  const phStream = makeStream(phStops, 'pagehide-track');
                  const phCtx = makeCtx(phStops, 'pagehide-ctx');
                  const client2 = VC.create({
                    createWebSocket: mock.createWebSocket,
                    navigator: { mediaDevices: { getUserMedia: async () => phStream } },
                    audioContext: phCtx,
                    session_token: 'test-token'
                  });
                  await client2.requestMicPermission();
                  window.dispatchEvent(new Event('pagehide'));
                  return { afterDisconnect, phStops };
                }"""
            )
            self.assertEqual(result["afterDisconnect"]["state"], "idle")
            self.assertIn("disconnect-track", result["afterDisconnect"]["stops"])
            self.assertIn("disconnect-ctx", result["afterDisconnect"]["stops"])
            self.assertEqual(result["afterDisconnect"]["socketState"], 3)
            self.assertIn("pagehide-track", result["phStops"])
            self.assertIn("pagehide-ctx", result["phStops"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_ducking_restores_on_error_and_turn_end(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "ducking.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({ autoReply: false });
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'test-token',
                    min_frames_before_speaking: 1
                  });
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  const sock = mock.getSocket();
                  sock.serverEmitAudio(1, 0, false, 80);
                  const speaking = client.getGainValues();
                  sock.serverEmitJson({ type: 'error', code: 'system-error', message: 'x' });
                  const afterError = { state: client.getState(), gains: client.getGainValues() };

                  sock.serverEmitJson({ type: 'tts.start' });
                  const speaking2 = client.getGainValues();
                  sock.serverEmitJson({ type: 'turn.end', turn_id: 't1', end_reason: 'done' });
                  const afterEnd = { state: client.getState(), gains: client.getGainValues() };
                  return { speaking, afterError, speaking2, afterEnd };
                }"""
            )
            self.assertAlmostEqual(result["speaking"]["mic"], 0.2)
            self.assertEqual(result["afterError"]["state"], "error:system-error")
            self.assertEqual(result["afterError"]["gains"], {"mic": 1.0, "agent": 1.0})
            self.assertAlmostEqual(result["speaking2"]["mic"], 0.2)
            self.assertEqual(result["afterEnd"]["state"], "ready")
            self.assertEqual(result["afterEnd"]["gains"], {"mic": 1.0, "agent": 1.0})
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_pcm16_playback_jitter_buffer_and_barge_in_stop(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "pcm_playback.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  // 1. Verify little-endian PCM16 -> Float32 decoding
                  const pcmBytes = new Uint8Array([0x00, 0x00, 0xFF, 0x7F, 0x00, 0x80]);
                  const floats = VC.decodePcm16ToFloat32(pcmBytes);

                  // 2. Verify Web Audio scheduling + 150ms minimum lead + barge-in stop
                  const scheduled = [];
                  const stopped = [];
                  const fakeGain = {
                    gain: {
                      value: 1.0,
                      cancelScheduledValues: () => {},
                      setValueAtTime: () => {},
                      linearRampToValueAtTime: (v) => { fakeGain.gain.value = v; }
                    },
                    connect: () => {}
                  };
                  const fakeCtx = {
                    state: 'suspended',
                    currentTime: 10.0,
                    destination: {},
                    resumeCalled: 0,
                    resume: function () { this.resumeCalled += 1; this.state = 'running'; return Promise.resolve(); },
                    createGain: () => fakeGain,
                    createBuffer: (ch, len, sr) => ({
                      length: len,
                      sampleRate: sr,
                      copyToChannel: () => {}
                    }),
                    createBufferSource: () => {
                      const src = {
                        buffer: null,
                        onended: null,
                        connect: () => {},
                        start: (when) => scheduled.push(when),
                        stop: () => stopped.push(true),
                        disconnect: () => {}
                      };
                      return src;
                    },
                    close: () => Promise.resolve()
                  };
                  const mock = VC.createMockServer({ holdSpeaking: true });
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    audioContext: fakeCtx,
                    session_token: 'test-token',
                    min_frames_before_speaking: 2
                  });
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  client.startListening();
                  client.endAudio();
                  const statsWhileSpeaking = client.getPlaybackStats();
                  const firstScheduledAt = scheduled[0] || 0;
                  client.bargeIn('user_ptt');
                  const statsAfterBargeIn = client.getPlaybackStats();
                  return {
                    floats: Array.from(floats),
                    resumeCalled: fakeCtx.resumeCalled,
                    scheduledCount: scheduled.length,
                    firstLeadMs: Math.round((firstScheduledAt - 10.0) * 1000),
                    stoppedCount: stopped.length,
                    statsWhileSpeaking,
                    statsAfterBargeIn
                  };
                }"""
            )
            self.assertEqual(len(result["floats"]), 3)
            self.assertAlmostEqual(result["floats"][0], 0.0, places=4)
            self.assertAlmostEqual(result["floats"][1], 1.0, places=4)
            self.assertAlmostEqual(result["floats"][2], -1.0, places=4)
            self.assertGreaterEqual(result["resumeCalled"], 1)
            self.assertEqual(result["scheduledCount"], 3)
            self.assertGreaterEqual(
                result["firstLeadMs"],
                150,
                "jitter buffer must never hard-schedule < 150 ms ahead",
            )
            self.assertEqual(result["stoppedCount"], 3)
            self.assertEqual(result["statsAfterBargeIn"]["active_sources"], 0)
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_voice_frame_sequence_gap_and_duplicates_are_counted(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "frames.html")
        try:
            result = page.evaluate(
                """async () => {
                  const VC = window.ZivonVoiceClient;
                  const mock = VC.createMockServer({ autoReply: false });
                  const client = VC.create({
                    createWebSocket: mock.createWebSocket,
                    session_token: 'test-token',
                    min_frames_before_speaking: 3
                  });
                  client.connect();
                  await new Promise((r) => setTimeout(r, 25));
                  const sock = mock.getSocket();
                  // Out-of-order + duplicate sequence numbers must not throw.
                  sock.serverEmitAudio(1, 5, false, 80);
                  sock.serverEmitAudio(1, 3, false, 80);
                  sock.serverEmitAudio(1, 3, false, 80);
                  return {
                    frames: client.getPendingFrames().length,
                    state: client.getState(),
                    metrics: client.getLastTurnMetrics()
                  };
                }"""
            )
            self.assertEqual(result["frames"], 3)
            self.assertEqual(result["state"], "speaking")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_offline_chip_toggles(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "offline.html")
        try:
            res = page.evaluate(
                """() => {
                  const chip = document.getElementById('zn-offline-chip');
                  const initial = chip.hidden;
                  Object.defineProperty(navigator, 'onLine', {
                    get: () => false, configurable: true
                  });
                  window.dispatchEvent(new Event('offline'));
                  const offline = chip.hidden;
                  Object.defineProperty(navigator, 'onLine', {
                    get: () => true, configurable: true
                  });
                  window.dispatchEvent(new Event('online'));
                  return { initial, offline, online: chip.hidden, copy: chip.textContent };
                }"""
            )
            self.assertTrue(res["initial"])
            self.assertFalse(res["offline"])
            self.assertTrue(res["online"])
            self.assertIn("keeps working while offline", res["copy"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_seo_sitemap_robots_and_json_ld(self) -> None:
        seo = _load_seo_module()
        sitemap_path = FRONTEND / "sitemap.xml"
        robots_path = FRONTEND / "robots.txt"
        self.assertTrue(sitemap_path.is_file(), "frontend/sitemap.xml must exist")
        self.assertTrue(robots_path.is_file(), "frontend/robots.txt must exist")
        self.assertTrue(
            (FRONTEND / "assets" / "og-card.png").is_file(),
            "frontend/assets/og-card.png must exist",
        )

        # Validate robots.txt (committed output is clearly marked as placeholder)
        robots_txt = robots_path.read_text(encoding="utf-8")
        self.assertIn("Generated by scripts/gen-seo-files.py", robots_txt)
        self.assertIn("PLACEHOLDER", robots_txt)
        self.assertIn("User-agent: *", robots_txt)
        self.assertIn("Disallow: /healthz", robots_txt)
        self.assertIn("Sitemap: https://zivon.local/sitemap.xml", robots_txt)

        # Validate sitemap.xml parses as valid XML and contains landing + courses
        sitemap_text = sitemap_path.read_text(encoding="utf-8")
        self.assertIn("PLACEHOLDER", sitemap_text)
        root = ET.fromstring(sitemap_text)
        locs = [el.text for el in root.findall(f"{SITEMAP_NS}url/{SITEMAP_NS}loc")]
        self.assertIn("https://zivon.local/", locs)
        self.assertIn(
            "https://zivon.local/courses/class-9-physics/how-forces-affect-motion/",
            locs,
        )
        self.assertIn(
            "https://zivon.local/courses/class-11-physics/motion-in-a-straight-line/",
            locs,
        )

        # Generator correctness on an explicit base URL + ABSOLUTE href handling:
        # absolute courses.js hrefs must resolve to the same on-disk tree, and a
        # missing manifest must skip loudly instead of fabricating a URL.
        import shutil

        with tempfile.TemporaryDirectory(prefix="zivon-seo-") as tmp:
            site = Path(tmp) / "frontend"
            shutil.copytree(FRONTEND, site, ignore=shutil.ignore_patterns("fonts"))
            courses_js = site / "courses.js"
            courses_js.write_text(
                courses_js.read_text(encoding="utf-8").replace(
                    '"href": "courses/', '"href": "https://zivon.example/courses/'
                ),
                encoding="utf-8",
            )
            generated = seo.generate_sitemap_xml(site, base_url="https://zivon.example")
            self.assertNotIn("PLACEHOLDER", generated)
            self.assertIn(
                "https://zivon.example/courses/class-11-physics/"
                "motion-in-a-straight-line/",
                generated,
            )
            seo.write_seo_files(site, base_url="https://zivon.example")
            index_html = (site / "index.html").read_text(encoding="utf-8")
            self.assertIn(
                'content="https://zivon.example/assets/og-card.png"', index_html
            )
            self.assertIn('property="og:url"', index_html)
            self.assertIn('content="https://zivon.example/"', index_html)
            robots = (site / "robots.txt").read_text(encoding="utf-8")
            self.assertIn("Sitemap: https://zivon.example/sitemap.xml", robots)

        # The committed og:image/twitter:image must be absolute, not relative.
        index_html = (FRONTEND / "index.html").read_text(encoding="utf-8")
        self.assertRegex(index_html, r'property="og:image"\s+content="https?://[^"]+"')
        self.assertRegex(index_html, r'name="twitter:image"\s+content="https?://[^"]+"')

        # Validate JSON-LD generator against a real published manifest.json
        manifest_path = (
            FRONTEND
            / "courses"
            / "class-11-physics"
            / "motion-in-a-straight-line"
            / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        jld = seo.build_json_ld(manifest, base_url="https://zivon.example")
        self.assertEqual(jld["@context"], "https://schema.org")
        self.assertIn("LearningResource", jld["@type"])
        self.assertIn("Course", jld["@type"])
        self.assertEqual(jld["name"], "Motion in a Straight Line")
        self.assertEqual(jld["educationalLevel"], "Class 11")
        self.assertTrue(jld["isBasedOn"])
        self.assertEqual(
            jld["url"],
            "https://zivon.example/courses/class-11-physics/motion-in-a-straight-line/",
        )


if __name__ == "__main__":
    unittest.main()
