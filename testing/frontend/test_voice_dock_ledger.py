"""Voice dock — Direction B (Ledger), founder review 2026-11-11.

Covers the dock contract that the ledger redesign changed:
- one language dropdown: tapping the label only opens the menu, choosing an
  option switches/persists the locale, unavailable bundles are disabled;
- retry is a single icon control on the newest answer (44 px, labelled);
- no block ids, no block-type words, no anchor chip in the user-visible dock,
  while the tutor highlight frame still rings the block by internal id;
- one icon-only panel open/close control;
- append-only transcript (a state tick never rebuilds rows);
- at most one conditional status line;
- the mic is a toggle (pressed + level bars), never hold-to-talk.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import Page, sync_playwright

from testing.frontend import serve_static  # noqa: F401 - Playwright import guard

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend"
ZIVON_JS_URI = (FRONTEND / "assets" / "zivon.js").resolve().as_uri()
ZIVON_CSS_URI = (FRONTEND / "assets" / "zivon.css").resolve().as_uri()

LESSON_HTML = (
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
    "<h1 class='zn-title'>Laws of Motion</h1></header>"
    "<section class='zn-text' id='b-01'>"
    "<p>An object continues in uniform motion unless acted upon by an unbalanced force.</p>"
    "</section>"
    "<section class='zn-example' id='b-02'><h3>Worked example: impulse</h3>"
    "<p class='zn-example-problem'>A bat applies 400 N for 0.15 s.</p>"
    "<p class='zn-answer'>Impulse = 60 N s.</p></section>"
    "<fieldset class='zn-check' id='b-03' data-format='mcq' data-answer-index='0'>"
    "<legend>What happens when net force is zero?</legend>"
    "<label class='zn-opt'><input type='radio' name='check-b-03' value='0'>"
    "<span>Velocity is constant</span></label>"
    "<button type='button' class='zn-check-btn'>Check</button>"
    "<p class='zn-check-feedback' aria-live='polite'></p>"
    "</fieldset>"
    "</main>"
    f"<script src='{ZIVON_JS_URI}'></script>"
    "</body></html>"
)


class TestVoiceDockLedger(unittest.TestCase):
    _pw: Any
    _browser: Any
    _tmp: tempfile.TemporaryDirectory

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()
        cls._tmp = tempfile.TemporaryDirectory(prefix="zivon-ledger-")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()
        cls._tmp.cleanup()

    def _open(self, *, consent: bool = True) -> tuple[Page, list[str]]:
        page = self._browser.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        if consent:
            page.add_init_script(
                "try { localStorage.setItem('zivon.consent', 'granted'); } catch (e) {}"
            )
        f = Path(self._tmp.name) / "lesson.html"
        if not f.exists():
            f.write_text(LESSON_HTML, encoding="utf-8")
        page.goto(f.resolve().as_uri())
        return page, errors

    # ---------------------------------------------------------------- helpers
    MOUNT_AND_SEED = """
      (async () => {
        window.ZivonShell.mount();
        const VC = window.ZivonVoiceClient;
        const mock = VC.createMockServer({ holdSpeaking: true });
        const mount = window.ZivonVoiceDock.lazyMount({
          clientOptions: { createWebSocket: mock.createWebSocket, session_token: 'tok' }
        });
        const client = VC.create({
          createWebSocket: mock.createWebSocket,
          session_token: 'tok',
          min_frames_before_speaking: 1
        });
        window.ZivonVoiceDock.bindClient(client);
        window.__mock = mock;
        window.__client = client;
        client.connect();
        await new Promise((r) => setTimeout(r, 30));
        client.sendTypedDoubt('Sir, impulse kya hai?');
        await new Promise((r) => setTimeout(r, 20));
        const sock = mock.getSocket();
        sock.serverEmitJson({ type: 'agent.state', state: 'speaking' });
        sock.serverEmitJson({ type: 'tutor.text', turn_id: 'turn-1', text: 'Impulse = force x time. ' });
        sock.serverEmitJson({ type: 'tutor.text', turn_id: 'turn-1', text: 'Yahi momentum ka change hai.' });
        await new Promise((r) => setTimeout(r, 20));
        window.ZivonVoiceDock.setContainment('expanded', false);
        return { mounted: mount.mounted, region: Boolean(mount.region) };
      })()
    """

    # ------------------------------------------------------- language control
    def test_language_dropdown_label_opens_the_menu_but_never_switches(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.removeItem('zivon_locale');
                  localStorage.setItem('zivon.consent', 'granted');
                  window.ZivonShell.mount();
                  window.ZivonVoiceDock.lazyMount();
                  window.ZivonVoiceDock.setContainment('expanded', false);
                  const region = document.querySelector('.zn-voice-dock-region');
                  const label = region.querySelector('.zn-dock-lang-label');
                  const btn = region.querySelector('.zn-dock-lang-btn');
                  const menu = region.querySelector('.zn-dock-lang-menu');
                  const before = {
                    label: label.textContent,
                    locale: localStorage.getItem('zivon_locale'),
                    lang: document.documentElement.lang,
                    checked: document.querySelectorAll('.zn-chip')[0].getAttribute('aria-checked')
                  };
                  // Tapping the label alone only OPENS the menu.
                  label.click();
                  await new Promise((r) => setTimeout(r, 10));
                  const afterLabelTap = {
                    menuOpen: !menu.hidden,
                    expanded: btn.getAttribute('aria-expanded'),
                    label: label.textContent,
                    locale: localStorage.getItem('zivon_locale'),
                    lang: document.documentElement.lang,
                    checked: document.querySelectorAll('.zn-chip')[0].getAttribute('aria-checked')
                  };
                  // Choosing an option with no bundle must be a no-op (disabled).
                  const hi = region.querySelector('.zn-dock-lang-option[data-locale="hi"]');
                  const hiDisabled = hi.getAttribute('aria-disabled');
                  hi.click();
                  await new Promise((r) => setTimeout(r, 10));
                  const afterDisabledPick = {
                    label: label.textContent,
                    locale: localStorage.getItem('zivon_locale')
                  };
                  // Bundle appears -> the same option really switches.
                  window.ZIVON_I18N = { hi: { strings: {}, ui_strings: {}, fallback_blocks: [] } };
                  region.querySelector('.zn-dock-lang-btn').click();  // close
                  region.querySelector('.zn-dock-lang-btn').click();  // reopen -> refresh
                  const hi2 = region.querySelector('.zn-dock-lang-option[data-locale="hi"]');
                  const hiEnabled = hi2.getAttribute('aria-disabled');
                  hi2.click();
                  await new Promise((r) => setTimeout(r, 10));
                  const afterPick = {
                    label: label.textContent,
                    locale: localStorage.getItem('zivon_locale'),
                    lang: document.documentElement.lang,
                    menuOpen: !menu.hidden,
                    chipChecked: document.querySelectorAll('.zn-chip')[1].getAttribute('aria-checked'),
                    enChecked: document.querySelectorAll('.zn-chip')[0].getAttribute('aria-checked')
                  };
                  return { before, afterLabelTap, hiDisabled, afterDisabledPick, hiEnabled, afterPick };
                }"""
            )
            self.assertEqual(res["before"]["label"], "English")
            self.assertIsNone(res["before"]["locale"])
            self.assertTrue(res["afterLabelTap"]["menuOpen"], "the label tap opens the menu")
            self.assertEqual(res["afterLabelTap"]["expanded"], "true")
            self.assertEqual(res["afterLabelTap"]["label"], "English")
            self.assertIsNone(
                res["afterLabelTap"]["locale"],
                "tapping the label must never switch or persist a language",
            )
            self.assertEqual(res["afterLabelTap"]["lang"], res["before"]["lang"])
            self.assertEqual(res["afterLabelTap"]["checked"], "true")
            self.assertEqual(res["hiDisabled"], "true")
            self.assertIsNone(res["afterDisabledPick"]["locale"])
            self.assertEqual(res["hiEnabled"], "false")
            self.assertEqual(res["afterPick"]["label"], "हिन्दी")
            self.assertEqual(res["afterPick"]["locale"], "hi")
            self.assertEqual(res["afterPick"]["lang"], "hi")
            self.assertTrue(res["afterPick"]["menuOpen"] is False)
            self.assertEqual(res["afterPick"]["chipChecked"], "true")
            self.assertEqual(res["afterPick"]["enChecked"], "false")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_language_detected_event_reflects_without_navigating(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.removeItem('zivon_locale');
                  localStorage.setItem('zivon.consent', 'granted');
                  window.__noReload = true;
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const sock = window.__mock.getSocket();
                  sock.serverEmitJson({ type: 'language.detected', locale: 'hi-Latn', confidence: 0.86 });
                  await new Promise((r) => setTimeout(r, 20));
                  const region = document.querySelector('.zn-voice-dock-region');
                  return {
                    seed,
                    sentinel: window.__noReload === true,
                    label: region.querySelector('.zn-dock-lang-label').textContent,
                    locale: localStorage.getItem('zivon_locale'),
                    lang: document.documentElement.lang,
                    selected: region.querySelector('.zn-dock-lang-option[data-locale="hi-Latn"]')
                      .getAttribute('aria-selected')
                  };
                }"""
            )
            self.assertTrue(res["seed"]["mounted"])
            self.assertTrue(res["sentinel"], "detection must not hard-navigate")
            self.assertEqual(res["label"], "Hinglish")
            self.assertEqual(res["locale"], "hi-Latn")
            self.assertEqual(res["lang"], "hi-Latn")
            self.assertEqual(res["selected"], "true")
            self.assertEqual(errors, [])
        finally:
            page.close()

    # -------------------------------------------------------------- retry icon
    def test_retry_is_one_icon_on_the_newest_answer(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  const btn = region.querySelector('.zn-dock-retry');
                  const visibleWhileSpeaking = !btn.hidden;
                  window.ZivonVoiceDock.renderAgentState('error:no-match', {});
                  const rows = region.querySelectorAll('.zn-dock-row');
                  const newest = rows[rows.length - 1];
                  const rect = btn.getBoundingClientRect();
                  const visibleInError = !btn.hidden;
                  const inNewestRow = btn.parentNode === newest.querySelector('.zn-dock-said');
                  let retried = false;
                  window.ZivonVoiceDock._activeClient.reconnect = function () { retried = true; };
                  btn.click();
                  window.ZivonVoiceDock.renderAgentState('ready', {});
                  return {
                    seed,
                    visibleWhileSpeaking,
                    visibleInError,
                    inNewestRow,
                    label: btn.getAttribute('aria-label'),
                    title: btn.getAttribute('title'),
                    text: btn.textContent.trim(),
                    hasSvg: Boolean(btn.querySelector('svg')),
                    width: rect.width,
                    height: rect.height,
                    retried,
                    hiddenInReady: btn.hidden
                  };
                }"""
            )
            self.assertTrue(res["seed"]["mounted"])
            self.assertFalse(res["visibleWhileSpeaking"], "retry only exists when the turn failed")
            self.assertTrue(res["visibleInError"])
            self.assertTrue(res["inNewestRow"], "retry belongs to the newest answer")
            self.assertTrue(res["label"])
            self.assertEqual(res["title"], res["label"])
            self.assertEqual(res["text"], "", "the retry control is an icon, not a word")
            self.assertTrue(res["hasSvg"])
            self.assertGreaterEqual(res["width"], 44)
            self.assertGreaterEqual(res["height"], 44)
            self.assertTrue(res["retried"])
            self.assertTrue(res["hiddenInReady"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    # ------------------------------------------------------- no ids / no types
    def test_dock_shows_no_block_ids_types_or_anchor_chip(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  window.__mock.getSocket().serverEmitJson({
                    type: 'highlight', turn_id: 'turn-1', block_ids: ['b-02']
                  });
                  await new Promise((r) => setTimeout(r, 20));
                  const snap = window.ZivonStateMatrix.buildContextSnapshot();
                  // every state + the open menu, so no state can leak the id
                  const texts = [region.innerText];
                  ['listening', 'thinking', 'error:no-match', 'error:mic-denied', 'text_only', 'offline']
                    .forEach((st) => {
                      window.ZivonVoiceDock.renderAgentState(st, {});
                      texts.push(region.innerText);
                    });
                  region.querySelector('.zn-dock-lang-btn').click();
                  texts.push(region.innerText);
                  const all = texts.join('\\n');
                  return {
                    seed,
                    hasIdText: /(^|[^a-z0-9])b-\\d+/i.test(all),
                    hasTypeText: /worked[_ ]example|block[_ ]type|block id/i.test(all),
                    hasAnchorChip: Boolean(region.querySelector('.zn-dock-anchor-chip')),
                    highlighted: document.getElementById('b-02').classList.contains('zn-tutor-highlight'),
                    blockId: snap.block_id,
                    blockType: snap.block_type,
                    blockTitle: snap.block_title,
                    blockText: snap.block_text,
                    visibleTitles: snap.visible_blocks.map((b) => b.title),
                    visibleHasIdTitle: snap.visible_blocks.some(
                      (b) => /(^|[^a-z0-9])b-\\d+/i.test(b.title)
                    )
                  };
                }"""
            )
            self.assertTrue(res["seed"]["mounted"])
            self.assertFalse(res["hasIdText"], "the dock must never render a block id")
            self.assertFalse(res["hasTypeText"])
            self.assertFalse(res["hasAnchorChip"])
            self.assertTrue(res["highlighted"], "the highlight frame still rings the block itself")
            self.assertRegex(res["blockId"], r"^b-0\d$")
            self.assertNotRegex(res["blockTitle"], r"b-\d")
            self.assertRegex(res["blockTitle"], r"Worked example")
            self.assertTrue(res["blockText"])
            self.assertNotRegex(res["blockText"], r"b-\d")
            self.assertFalse(res["visibleHasIdTitle"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    # ----------------------------------------------------------- panel toggle
    def test_one_icon_panel_toggle_opens_and_closes(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  localStorage.removeItem('zivon.dock');
                  window.ZivonShell.mount();
                  const mount = window.ZivonVoiceDock.lazyMount();
                  const region = document.querySelector('.zn-voice-dock-region');
                  const stripToggle = region.querySelector('.zn-dock-panel-toggle-strip');
                  const sheetToggle = region.querySelector('.zn-dock-panel-toggle-sheet');
                  const start = window.ZivonVoiceDock.getContainment();
                  const stripRect = stripToggle.getBoundingClientRect();
                  stripToggle.click();
                  const sheetRect = sheetToggle.getBoundingClientRect();
                  const opened = {
                    containment: window.ZivonVoiceDock.getContainment(),
                    stored: localStorage.getItem('zivon.dock'),
                    sheetExpanded: sheetToggle.getAttribute('aria-expanded'),
                    sheetVisible: !region.querySelector('.zn-dock-sheet').hidden
                  };
                  sheetToggle.click();
                  const closed = {
                    containment: window.ZivonVoiceDock.getContainment(),
                    stored: localStorage.getItem('zivon.dock'),
                    stripExpanded: stripToggle.getAttribute('aria-expanded'),
                    stripVisible: !region.querySelector('.zn-dock-strip').hidden
                  };
                  region.querySelector('.zn-dock-tab').click();
                  return {
                    mounted: mount.mounted,
                    start,
                    opened,
                    closed,
                    tabHidden: region.querySelector('.zn-dock-tab').hidden,
                    stripText: stripToggle.textContent.trim(),
                    sheetText: sheetToggle.textContent.trim(),
                    hasSvg: Boolean(stripToggle.querySelector('svg') && sheetToggle.querySelector('svg')),
                    stripSize: [stripRect.width, stripRect.height],
                    sheetSize: [sheetRect.width, sheetRect.height]
                  };
                }"""
            )
            self.assertTrue(res["mounted"])
            self.assertEqual(res["start"], "collapsed")
            self.assertEqual(res["opened"]["containment"], "expanded")
            self.assertEqual(res["opened"]["stored"], "expanded")
            self.assertEqual(res["opened"]["sheetExpanded"], "true")
            self.assertTrue(res["opened"]["sheetVisible"])
            self.assertEqual(res["closed"]["containment"], "collapsed")
            self.assertEqual(res["closed"]["stored"], "collapsed")
            self.assertEqual(res["closed"]["stripExpanded"], "false")
            self.assertTrue(res["closed"]["stripVisible"])
            self.assertEqual(res["stripText"], "", "the panel control carries no text")
            self.assertEqual(res["sheetText"], "")
            self.assertTrue(res["hasSvg"])
            for size in (res["stripSize"], res["sheetSize"]):
                self.assertGreaterEqual(size[0], 44)
                self.assertGreaterEqual(size[1], 44)
            self.assertEqual(errors, [])
        finally:
            page.close()

    # -------------------------------------------------------- append-only log
    def test_transcript_is_append_only_across_state_ticks(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  const rowsBefore = Array.from(region.querySelectorAll('.zn-dock-row'));
                  rowsBefore.forEach((r, i) => { r.setAttribute('data-probe', 'row-' + i); });
                  const scrollBefore = region.querySelector('.zn-dock-transcript').scrollTop;
                  ['listening', 'thinking', 'speaking', 'ready', 'error:no-match', 'offline']
                    .forEach((st) => window.ZivonVoiceDock.renderAgentState(st, {}));
                  const rowsAfter = Array.from(region.querySelectorAll('.zn-dock-row'));
                  const sameNodes = rowsAfter.length === rowsBefore.length &&
                    rowsBefore.every((r, i) => r === rowsAfter[i] && r.isConnected);
                  // A new turn appends; the earlier rows keep their identity.
                  const sock = window.__mock.getSocket();
                  window.__client.sendTypedDoubt('Aur ek sawaal?');
                  await new Promise((r) => setTimeout(r, 15));
                  sock.serverEmitJson({ type: 'agent.state', state: 'thinking' });
                  sock.serverEmitJson({ type: 'tutor.text', turn_id: 'turn-2', text: 'Haan, poochho.' });
                  await new Promise((r) => setTimeout(r, 20));
                  const rowsFinal = Array.from(region.querySelectorAll('.zn-dock-row'));
                  return {
                    seed,
                    rowCountBefore: rowsBefore.length,
                    sameNodes,
                    firstStillFirst: rowsFinal[0] === rowsBefore[0],
                    grew: rowsFinal.length > rowsBefore.length,
                    scrollKept: region.querySelector('.zn-dock-transcript').scrollTop >= 0,
                    probeSurvived: rowsFinal[0].getAttribute('data-probe') === 'row-0',
                    scrollBefore
                  };
                }"""
            )
            self.assertTrue(res["seed"]["mounted"])
            self.assertEqual(res["rowCountBefore"], 2)
            self.assertTrue(res["sameNodes"], "state ticks must not rebuild transcript rows")
            self.assertTrue(res["firstStillFirst"])
            self.assertTrue(res["probeSurvived"])
            self.assertTrue(res["grew"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    # ------------------------------------------------------- one status line
    def test_at_most_one_conditional_status_line(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  const statuses = region.querySelectorAll('.zn-dock-status');
                  const out = {};
                  ['idle', 'ready', 'connecting', 'requesting-permission', 'endpointing',
                   'speaking', 'speaking_text', 'interrupted', 'listening', 'thinking',
                   'reconnecting', 'offline', 'error:mic-denied', 'text_only',
                   'error:no-match'].forEach((st) => {
                    window.ZivonVoiceDock.renderAgentState(st, {});
                    const el = region.querySelector('.zn-dock-status');
                    out[st] = {
                      hidden: el.hidden,
                      text: el.innerText.replace(/\\s+/g, ' ').trim(),
                      stamp: !region.querySelector('.zn-dock-stamp').hidden
                    };
                  });
                  return { seed, count: statuses.length, out };
                }"""
            )
            self.assertEqual(res["count"], 1, "there is exactly one status line, not a row")
            out = res["out"]
            for quiet in (
                "idle",
                "ready",
                "connecting",
                "requesting-permission",
                "endpointing",
                "speaking",
                "speaking_text",
                "interrupted",
            ):
                self.assertTrue(out[quiet]["hidden"], f"{quiet} must not show a status line")
            self.assertIn("Sun rahe hain", out["listening"]["text"])
            self.assertIn("Soch rahe hain", out["thinking"]["text"])
            self.assertIn("jud", out["reconnecting"]["text"])
            self.assertIn("type karo", out["offline"]["text"])
            self.assertIn("30 credits/day", out["text_only"]["text"])
            self.assertTrue(out["error:mic-denied"]["stamp"])
            self.assertIn("type karke poochho", out["error:mic-denied"]["text"])
            self.assertIn("Saaf sunai nahi diya", out["error:no-match"]["text"])
            # The mic is still disabled where voice cannot work.
            mic = page.evaluate(
                """() => {
                  const region = document.querySelector('.zn-voice-dock-region');
                  region.querySelector('.zn-dock-mic-sheet');
                  window.ZivonVoiceDock.renderAgentState('text_only', {});
                  return { disabled: region.querySelector('.zn-dock-mic-sheet').disabled };
                }"""
            )
            # (page.evaluate above is a second call; keep the assertion local)
            self.assertTrue(mic["disabled"])
            self.assertEqual(errors, [])
        finally:
            page.close()

    # ------------------------------------------------------------- mic toggle
    def test_mic_is_a_toggle_with_bars_while_listening(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  const mic = region.querySelector('.zn-dock-mic-sheet');
                  const bars = mic.querySelector('.zn-dock-bars');
                  const glyph = mic.querySelector('svg');
                  const idle = {
                    pressed: mic.getAttribute('aria-pressed'),
                    barsShown: getComputedStyle(bars).display !== 'none',
                    glyphShown: getComputedStyle(glyph).display !== 'none'
                  };
                  window.ZivonVoiceDock.renderAgentState('listening', {});
                  const listening = {
                    pressed: mic.getAttribute('aria-pressed'),
                    label: mic.getAttribute('aria-label'),
                    barsShown: getComputedStyle(bars).display !== 'none',
                    glyphShown: getComputedStyle(glyph).display !== 'none',
                    focused: document.activeElement === mic
                  };
                  window.ZivonVoiceDock.renderAgentState('ready', {});
                  return { seed, idle, listening, afterLabel: mic.getAttribute('aria-label') };
                }"""
            )
            self.assertEqual(res["idle"]["pressed"], "false")
            self.assertFalse(res["idle"]["barsShown"])
            self.assertTrue(res["idle"]["glyphShown"])
            self.assertEqual(res["listening"]["pressed"], "true")
            self.assertEqual(res["listening"]["label"], "Stop listening")
            self.assertTrue(res["listening"]["barsShown"])
            self.assertFalse(res["listening"]["glyphShown"])
            self.assertEqual(res["afterLabel"], "Start listening")
            self.assertEqual(errors, [])
        finally:
            page.close()

    # --------------------------------------------------------------- geometry
    def test_single_tape_is_clipped_to_the_sheet_top_edge(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  const tapes = region.querySelectorAll('.zn-dock-tape');
                  const tape = tapes[0];
                  const clip = tape.parentNode;
                  const sheet = region.querySelector('.zn-dock-sheet');
                  const sr = sheet.getBoundingClientRect();
                  const cr = clip.getBoundingClientRect();
                  const tr = tape.getBoundingClientRect();
                  const cs = getComputedStyle(tape);
                  const tapeTransform = cs.transform;
                  const tapeOverflow = getComputedStyle(clip).overflow;
                  const head = region.querySelector('.zn-dock-head');
                  const headContentTop = head.getBoundingClientRect().top +
                    parseFloat(getComputedStyle(head).paddingTop);
                  const grip = region.querySelector('.zn-dock-grip');
                  const gripInSheet = Boolean(sheet.querySelector('.zn-dock-grip'));
                  const stripHasGrab = Boolean(region.querySelector('.zn-dock-strip .zn-dock-grab'));
                  // Hidden state: no sheet edge, so no tape is painted.
                  window.ZivonVoiceDock.setContainment('hidden', true);
                  const hiddenSheet = region.querySelector('.zn-dock-sheet').hidden;
                  return {
                    seed,
                    tapeCount: tapes.length,
                    transform: tapeTransform,
                    clipClipsOverflow: tapeOverflow,
                    clipTop: cr.top,
                    sheetTop: sr.top,
                    tapeCentreX: tr.left + tr.width / 2,
                    sheetCentreX: sr.left + sr.width / 2,
                    tapeAboveSheet: tr.top < sr.top,
                    visibleBand: tr.bottom - sr.top,
                    tapeWidth: tr.width,
                    headClearance: headContentTop - sr.top,
                    gripCount: region.querySelectorAll('.zn-dock-grip').length,
                    gripInSheet,
                    stripHasGrab,
                    hiddenSheet
                  };
                }"""
            )
            self.assertEqual(res["tapeCount"], 1, "one tape, not one per element")
            self.assertIn("-0.05", res["transform"])  # rotate(-3deg)
            self.assertLessEqual(abs(res["tapeCentreX"] - res["sheetCentreX"]), 1.5)
            self.assertTrue(res["tapeAboveSheet"], "the tape straddles the sheet edge")
            self.assertGreater(res["visibleBand"], 10)
            self.assertLess(res["visibleBand"], 20)
            self.assertGreaterEqual(res["tapeWidth"], 90)
            self.assertLessEqual(res["tapeWidth"], 97)
            self.assertEqual(res["clipClipsOverflow"], "visible", "the whole torn tape must stay visible, not cut in half")
            self.assertGreaterEqual(res["headClearance"], 22, "tape band never covers the header")
            self.assertEqual(res["gripCount"], 1)
            self.assertTrue(res["gripInSheet"], "the grip rule exists only in the sheet")
            self.assertFalse(res["stripHasGrab"], "no grab band in the collapsed strip")
            self.assertTrue(res["hiddenSheet"], "the hidden tab carries no tape")
            self.assertEqual(errors, [])
        finally:
            page.close()

    def test_idle_dock_stays_inside_the_dom_budget(self) -> None:
        page, errors = self._open()
        try:
            res = page.evaluate(
                """async () => {
                  localStorage.setItem('zivon.consent', 'granted');
                  const seed = await """ + self.MOUNT_AND_SEED + """;
                  const region = document.querySelector('.zn-voice-dock-region');
                  return { seed, nodes: region.querySelectorAll('*').length };
                }"""
            )
            self.assertLessEqual(res["nodes"], 96, "dock DOM budget at rest incl. the reading key (§10.12 ~90)")
            self.assertEqual(errors, [])
        finally:
            page.close()


if __name__ == "__main__":
    unittest.main()
