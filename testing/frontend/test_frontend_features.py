"""Tests for the frontend execution wave (EX5-FRONT):
- Routing + localized-route hook (DCR-001) + branded 404 page (SCR-404-01)
- Screen-state matrix walk-through across all 10 canonical states
- Locale switcher persistence (`localStorage["zivon.lang"]`), radiogroup a11y,
  untranslated notice (`INF-087`), and ADR-0007 `device_pseudo_id` UUIDv4
- Event instrumentation (`ZivonEvents` queue, SP3 `EVT-F01..F12` mapping,
  privacy redaction/bucketing/hashing)
- Voice loop WS client state machine (`ZivonVoiceClient`) + mock WS server +
  binary framing (ADR-0020) + ducking (ADR-0010) + barge-in + degraded text
  fallback + DCR-002 standing guard verification
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

import testing.frontend  # noqa: F401 - ensures Playwright/Chromium shim if needed
from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
INDEX = FRONTEND / "index.html"
NOT_FOUND = FRONTEND / "404.html"
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()


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
    "<button type='button' class='zn-chip' role='radio' aria-checked='true'>English</button>"
    "<button type='button' class='zn-chip' role='radio' aria-checked='false'>हिन्दी</button>"
    "<button type='button' class='zn-chip' role='radio' aria-checked='false'>Hinglish</button>"
    "</div></div></header>"
    "<main class='zn-page' data-generated-at='2026-11-09T00:00:00Z'>"
    "<header class='zn-header'><p class='zn-kicker'>class-9-physics</p>"
    "<h1 class='zn-title'>Motion</h1>"
    "<p class='zn-objectives-label'>After this lesson you can:</p>"
    "<ul class='zn-objectives'><li>Define displacement and velocity.</li></ul></header>"
    "<section class='zn-text' id='b-01'><p>Velocity is displacement divided by time interval.</p></section>"
    "<section class='zn-example' id='b-02'><h3>Worked example</h3>"
    "<p class='zn-example-problem'>Find velocity for 20 m in 4 s.</p>"
    "<ol><li>v = 20 / 4</li></ol><p class='zn-answer'><span class='zn-answer-label'>Answer:</span> 5 m/s</p></section>"
    "<section class='zn-reveal' id='b-03'><h3>Derivation steps</h3>"
    "<details class='zn-reveal-step'><summary>Step 1</summary><p>Write delta x / delta t.</p></details></section>"
    "<figure class='zn-diagram' id='b-04'>"
    "<div class='zn-diagram-svg'><svg viewBox='0 0 280 180' aria-label='Displacement arrow'><line x1='20' y1='90' x2='260' y2='90' stroke='#1C1B18' stroke-width='3'/></svg></div>"
    "<figcaption>Scale: 1 cm = 2 m.</figcaption></figure>"
    "<section class='zn-sim zn-sim-b-05' id='b-05' data-sim-id='b-05'>"
    "<h3>Constant velocity</h3>"
    "<div class='zn-sim-controls'>"
    "<label class='zn-sim-control'><span>Velocity v (m/s)</span>"
    "<input type='range' data-control='v' min='0' max='10' step='1' value='5'><output>5</output></label>"
    "<button type='button' class='zn-sim-reset'>Reset</button>"
    "</div>"
    "<div class='zn-sim-canvas-wrap'><canvas class='zn-sim-canvas' width='480' height='320'></canvas></div>"
    "<p class='zn-sim-read' aria-live='polite'></p>"
    "<p class='zn-sim-desc'>Adjust v to see position change.</p></section>"
    "<fieldset class='zn-check' id='b-06' data-format='mcq' data-answer-index='0'>"
    "<legend>Which quantity has direction?</legend>"
    "<label class='zn-opt'><input type='radio' name='check-b-06' value='0'><span>Velocity</span></label>"
    "<label class='zn-opt'><input type='radio' name='check-b-06' value='1'><span>Speed</span></label>"
    "<button type='button' class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "<details class='zn-check-why'><summary>Why?</summary><p>Velocity is a vector.</p></details></fieldset>"
    "<footer class='zn-footer'><p class='zn-sources'>NCERT Grade 9 Science</p></footer>"
    "</main>"
    f"<script src='{ZIVON_JS_URI}'></script>"
    "<script>"
    "window.ZivonSim.register('b-05', {"
    "  init: function (ctx) {},"
    "  draw: function (ctx) { ctx.g.fillStyle = '#F6F0CF'; ctx.g.fillRect(0, 0, ctx.width, ctx.height); }"
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
            self.assertIsNotNone(page.query_selector('[data-element-id="EL-404-01-001"]'))
            self.assertIsNotNone(page.query_selector('[data-element-id="EL-404-01-002"]'))
            back = page.query_selector('[data-element-id="EL-404-01-003"]')
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
                  return {
                    home: R.parseRoute('/'),
                    lessonEn: R.parseRoute('/courses/class-9-physics/motion/index.html'),
                    lessonHi: R.parseRoute('/hi/courses/class-9-physics/motion/'),
                    lessonHinglish: R.parseRoute('/hi-Latn/courses/class-11-physics/kinematics/'),
                    missing: R.parseRoute('/unknown/path'),
                    builtHi: R.buildLocalizedHref('/courses/class-9-physics/motion/', 'hi'),
                    builtHinglish: R.buildLocalizedHref('/courses/class-9-physics/motion/', 'hinglish'),
                    builtEn: R.buildLocalizedHref('/hi/courses/class-9-physics/motion/', 'en'),
                  };
                }"""
            )
            self.assertEqual(res["home"]["screen"], "SCR-HOME-01")
            self.assertEqual(res["lessonEn"]["screen"], "SCR-LES-01")
            self.assertEqual(res["lessonEn"]["course_id"], "class-9-physics")
            self.assertEqual(res["lessonEn"]["topic_slug"], "motion")
            self.assertEqual(res["lessonHi"]["locale"], "hi")
            self.assertEqual(res["lessonHi"]["canonical_path"], "/courses/class-9-physics/motion/")
            self.assertEqual(res["lessonHinglish"]["locale"], "hi-Latn")
            self.assertEqual(res["missing"]["screen"], "SCR-404-01")
            self.assertEqual(res["builtHi"], "/hi/courses/class-9-physics/motion/")
            self.assertEqual(res["builtHinglish"], "/hi-Latn/courses/class-9-physics/motion/")
            self.assertEqual(res["builtEn"], "/courses/class-9-physics/motion/")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_locale_switcher_persistence_and_device_pseudonym(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "locale.html")
        try:
            initial = page.evaluate(
                """() => {
                  localStorage.removeItem('zivon.lang');
                  localStorage.removeItem('zivon.device_pseudo_id');
                  const devId = window.ZivonLocale.getDevicePseudoId();
                  return {
                    devId: devId,
                    savedLang: window.ZivonLocale.getSavedLang(),
                    docLang: document.documentElement.lang
                  };
                }"""
            )
            self.assertRegex(
                initial["devId"],
                r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
            )
            self.assertEqual(initial["savedLang"], "en")

            # Click Hindi chip -> aria-checked updates, localStorage['zivon.lang'] = 'hi',
            # documentElement.lang stays 'en' (v1 honest stub per spec.md §3.2/§8)
            chips = page.query_selector_all(".zn-lang-row .zn-chip")
            self.assertEqual(len(chips), 3)
            chips[1].click()
            after_click = page.evaluate(
                """() => ({
                  stored: localStorage.getItem('zivon.lang'),
                  c0: document.querySelectorAll('.zn-chip')[0].getAttribute('aria-checked'),
                  c1: document.querySelectorAll('.zn-chip')[1].getAttribute('aria-checked'),
                  docLang: document.documentElement.lang
                })"""
            )
            self.assertEqual(after_click["stored"], "hi")
            self.assertEqual(after_click["c0"], "false")
            self.assertEqual(after_click["c1"], "true")
            self.assertEqual(after_click["docLang"], "en")

            # Reload page -> Hindi chip is preselected from localStorage['zivon.lang']
            page.goto((Path(self._tmp.name) / "locale.html").resolve().as_uri())
            preselected = page.evaluate(
                "document.querySelectorAll('.zn-chip')[1].getAttribute('aria-checked')"
            )
            self.assertEqual(preselected, "true")

            # Test keyboard ArrowRight navigation on radiogroup
            page.evaluate(
                """() => {
                  const chip1 = document.querySelectorAll('.zn-chip')[1];
                  chip1.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true}));
                }"""
            )
            after_key = page.evaluate(
                """() => ({
                  stored: localStorage.getItem('zivon.lang'),
                  c2: document.querySelectorAll('.zn-chip')[2].getAttribute('aria-checked')
                })"""
            )
            self.assertEqual(after_key["stored"], "hi-Latn")
            self.assertEqual(after_key["c2"], "true")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_events_instrumentation_and_privacy_rules(self) -> None:
        page, errors = self._open_html(LESSON_SYNTHETIC_HTML, "events.html")
        try:
            # Verify initial boot emitted EVT-lesson_viewed (EVT-F01) and EVT-sim_opened (EVT-F03)
            boot_evts = page.evaluate("window.ZivonEvents.getQueue()")
            evt_names = [e["evt"] for e in boot_evts]
            self.assertIn("EVT-lesson_viewed", evt_names)
            self.assertIn("EVT-sim_opened", evt_names)

            # Interact with slider, check (wrong then right), reveal, and language chip
            page.evaluate(
                """() => {
                  const inp = document.querySelector('[data-control="v"]');
                  inp.value = '8';
                  inp.dispatchEvent(new Event('input', {bubbles: true}));
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
            self.assertIn("EVT-sim_control_changed", by_evt)
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
                  const offlineBanner = document.getElementById('zn-lesson-status-offline');
                  const offlineVisible = offlineBanner && !offlineBanner.hidden;

                  window.ZivonStateMatrix.applyState('over-credit-budget');
                  const quotaBanner = document.getElementById('zn-lesson-status-exhausted');
                  const quotaVisible = quotaBanner && !quotaBanner.hidden;

                  window.ZivonStateMatrix.applyState('untranslated');
                  const untranslatedCount = document.querySelectorAll('.zn-untranslated-notice').length;

                  const snap = window.ZivonStateMatrix.buildContextSnapshot('b-05');
                  return {
                    dockStatus,
                    statesCount: states.length,
                    offlineVisible,
                    quotaVisible,
                    untranslatedCount,
                    snapSize: JSON.stringify(snap).length,
                    snapSimId: snap.sim_id
                  };
                }"""
            )
            # DCR-002 standing guard: doctrine §10.12 absent -> dock does not render UI
            self.assertFalse(res["dockStatus"]["mounted"])
            self.assertIn("DCR-002", res["dockStatus"]["reason"])
            self.assertEqual(res["statesCount"], 10)
            self.assertTrue(res["offlineVisible"])
            self.assertTrue(res["quotaVisible"])
            self.assertGreaterEqual(res["untranslatedCount"], 2)
            self.assertLessEqual(res["snapSize"], 4096)
            self.assertEqual(res["snapSimId"], "b-05")
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
                  const fakeNav = {
                    mediaDevices: {
                      getUserMedia: async () => ({
                        getAudioTracks: () => [{ getSettings: () => ({ sampleRate: 16000, channelCount: 1 }) }]
                      })
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
                  const highlighted = document.getElementById('b-05').classList.contains('zn-tutor-highlight');

                  // Test barge-in while speaking
                  const mockHold = VC.createMockServer({ holdSpeaking: true });
                  const c2 = VC.create({ createWebSocket: mockHold.createWebSocket, navigator: fakeNav, min_buffer_frames: 2 });
                  c2.connect();
                  await new Promise((r) => setTimeout(r, 20));
                  c2.startListening();
                  c2.endAudio();
                  const speakingState = c2.getState();
                  const speakingGain = c2.getGainValues();
                  c2.bargeIn('user_speech');
                  const afterBargeIn = c2.getState();

                  // Test mic-denied + degraded typed fallback + offline queue
                  const deniedNav = {
                    mediaDevices: {
                      getUserMedia: async () => { throw new Error('NotAllowedError'); }
                    }
                  };
                  const c3 = VC.create({ createWebSocket: mock.createWebSocket, navigator: deniedNav });
                  await c3.requestMicPermission();
                  const deniedState = c3.getState();
                  // While WS not connected, typed doubt queues in memory and sets offline
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
            self.assertEqual(result["afterBargeIn"], "listening")
            self.assertEqual(result["deniedState"], "error:mic-denied")
            self.assertEqual(result["offlineState"], "offline")
            self.assertEqual(result["queuedCount"], 1)
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

        # Validate robots.txt
        robots_txt = robots_path.read_text(encoding="utf-8")
        self.assertIn("User-agent: *", robots_txt)
        self.assertIn("Disallow: /healthz", robots_txt)
        self.assertIn("Sitemap: https://zivon.local/sitemap.xml", robots_txt)

        # Validate sitemap.xml parses as valid XML and contains landing + published courses
        root = ET.fromstring(sitemap_path.read_text(encoding="utf-8"))
        locs = [
            el.text
            for el in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
        ]
        self.assertIn("https://zivon.local/", locs)
        self.assertIn(
            "https://zivon.local/courses/class-9-physics/how-forces-affect-motion/",
            locs,
        )
        self.assertIn(
            "https://zivon.local/courses/class-11-physics/motion-in-a-straight-line/",
            locs,
        )

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
