# Browser test checklist

Use for a new Playwright test, an accessibility pass, or a performance-budget
change. Delete rows marked n/a with a reason; a blank row is a defect.

## 1. Preflight

- [ ] The behaviour genuinely needs a browser (runtime DOM, focus, canvas,
      console, layout, perf). A static contract test would not be cheaper and
      sufficient.
- [ ] `python -m playwright install chromium` has been run.
- [ ] The suite imports `testing.frontend`, which fails loudly if Playwright is
      missing.
- [ ] The page is served over HTTP (`serve_static`) when the test asserts a
      clean console or a load budget. `file://` is used only for a font-free
      synthetic fragment where CORS is irrelevant.
- [ ] Synthetic pages live in a `tempfile.TemporaryDirectory`; tracked pages
      are never mutated.
- [ ] The real `frontend/assets/zivon.js` / `zivon.css` are referenced, not a
      copy.

## 2. Page lifecycle

- [ ] One browser per class (`setUpClass` / `tearDownClass`); one context per
      test.
- [ ] `page.on("console", ...)` collects `type == "error"` messages.
- [ ] `page.on("pageerror", ...)` collects uncaught exceptions.
- [ ] The test asserts the collected error list is empty at the end.
- [ ] Pages close in `finally` or `addCleanup`; contexts close.
- [ ] External requests are blocked or asserted absent
      (`page.on("request", ...)`), matching the CSP/self-containment rule.

## 3. States

The ten canonical states from `docs/specs/frontend/state-matrix.md`:

| State | Covered? | How | n/a reason |
|---|---|---|---|
| default | `<yes>` | `<load with data>` | |
| loading | | | |
| empty | | | |
| partial | | | |
| error | | | |
| offline | | | |
| permission-denied | | | |
| reduced-motion | | | |
| untranslated | | | |
| over-credit-budget | | | |

High-value: empty catalogue, broken simulation error painter, untranslated
notice, offline chip, reduced-motion single draw, quota-exhausted typed mode.

## 4. Locators and waits

- [ ] Locators use role/label/text before CSS.
- [ ] Assertions are web-first (`expect(locator).to_be_visible()`), not
      immediate `is_visible()` checks.
- [ ] No `time.sleep` or `page.wait_for_timeout`; waits target an observable
      condition or a driven event.
- [ ] Any `asyncio.wait_for`/timeout is a deadlock guard, not a latency
      assertion.
- [ ] The test passes alone, repeated, and in a different order.
- [ ] Storage/localStorage is isolated per context.

## 5. Accessibility

- [ ] Every interactive control is reachable by Tab, in a sensible order.
- [ ] Enter/Space activate; Escape closes; arrow keys move within a radiogroup.
- [ ] Focus is visible and not obscured by a sticky bar or dock.
- [ ] Checks use `fieldset`/`legend` and `aria-live` feedback; retry is allowed.
- [ ] `aria-disabled` is used for a locale with no bundle, not a silent no-op.
- [ ] Canvas simulation has a text alternative and a populated `.zn-sim-read`.
- [ ] Targets are at least 44 px; no colour-only meaning; no timed interaction.
- [ ] If axe is present: zero `serious`/`critical` WCAG 2.2 A/AA violations; the
      script is served locally (no CDN).
- [ ] Manual gates recorded: keyboard-only walkthrough, screen-reader
      walkthrough (TalkBack/VoiceOver), alt-text usefulness.

## 6. Performance

- [ ] The budget comes from the named profile
      (`testing/content_factory/perf/profiles/weak-android.json`), not a magic
      number.
- [ ] The test asserts load, FCP, RAM, FPS, overflow, and the sim read mirror
      as applicable.
- [ ] Layout is asserted as DOM geometry, not a pixel screenshot.
- [ ] When Chromium is unavailable, the test skips with the reason; no
      fabricated numbers.

## 7. Evidence and PR

- [ ] Command: `python -m unittest discover -s testing/frontend -t .`
- [ ] Result: `<N/N OK, M skipped>`; each skip has a reason.
- [ ] On failure: Playwright trace or the failing page HTML plus console list.
- [ ] Browser version matches CI.
- [ ] No visual regression snapshot was added.

## 8. Review

- [ ] One behaviour per test.
- [ ] The test would fail if the runtime behaviour broke (name the mutation).
- [ ] It would stay green through a safe refactor of private helpers.
- [ ] The failure message identifies the surface and the wrong state.
- [ ] The test adds seconds, not minutes, to the suite.
