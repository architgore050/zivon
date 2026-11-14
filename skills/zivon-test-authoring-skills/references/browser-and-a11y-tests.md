# Browser and accessibility tests

Browser tests are for behaviour that cannot be proved by reading bytes: runtime
DOM updates, console cleanliness, focus and keyboard operation, canvas
simulations, layout overflow, and performance under throttle. They are slow and
comparatively brittle, so use the smallest surface that can observe the break.

## 1. When a browser is the right tool

Use a browser test when the assertion needs one of these:

- JavaScript executed against the shipped `frontend/assets/zivon.js` or a
  generated `page.js`.
- A rendered DOM state after a click, keypress, or injected data.
- Console or page errors on load (the clean-load contract).
- Focus order, focus visibility, or activation by keyboard.
- Layout geometry at a viewport (for example, no horizontal overflow at 360 px).
- `prefers-reduced-motion` behaviour, canvas drawing, or a performance budget.

Do **not** use a browser for: static self-containment, links, CSP strings,
catalogue integrity, schema validity, or `data-i18n` presence. Those are
level-1 contract tests and must run without a browser.

### Static shell tests (no browser)

`testing/frontend/test_shell.py::TestShellContract` reads the shipped bytes and
asserts the shell/catalogue contract: self-containment, internal references,
font licensing, cache-busted asset paths, and `courses.js` entries resolving to
real pages. It runs without Playwright, so it is the first thing to run when a
frontend file moves or a path changes:

```bash
python -m unittest testing.frontend.test_shell.TestShellContract
```

The same module's browser classes cover the runtime. Do not move a static
assertion into the browser layer: it becomes slower and no more true.

## 2. The stack in this repo

- `playwright.sync_api` (synchronous API) inside `unittest`.
- `testing/frontend/__init__.py` fails loudly at import when Playwright is
  missing, with the install command. There is deliberately no Selenium or
  psutil fallback: a silent shim would test a different browser stack than CI.
- `serve_static(root)` starts a quiet `ThreadingHTTPServer` on an ephemeral
  port and shuts it down in `finally`. Use it for any test that asserts a clean
  console or a load budget; `file://` has an opaque origin and Chromium blocks
  font/preload fetches with CORS errors that do not occur in production.
- Synthetic pages are written to a `tempfile.TemporaryDirectory`; the real
  `zivon.js`/`zivon.css` are referenced by `Path.as_uri()`. The test never
  mutates a tracked page.

Setup once:

```bash
python -m playwright install chromium
python -m unittest discover -s testing/frontend -t .
```

CI installs Chromium in the `tests` job (`python -m playwright install --with-deps chromium`).
A missing Playwright install fails loudly with the install command (no silent
shim); the integration perf checks skip with a reason when Chromium is
unavailable. A skip is never a pass.

## 3. The page lifecycle

```python
import unittest
from pathlib import Path
from typing import Any

from playwright.sync_api import expect, sync_playwright

from testing.frontend import serve_static

REPO_ROOT = Path(__file__).resolve().parents[2]


class LandingPageTest(unittest.TestCase):
    _pw: Any
    _browser: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls._pw = sync_playwright().start()
        cls._browser = cls._pw.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._browser.close()
        cls._pw.stop()

    def test_catalogue_renders_from_injected_data(self) -> None:
        with serve_static(REPO_ROOT / "frontend") as base_url:
            context = self._browser.new_context()
            self.addCleanup(context.close)
            page = context.new_page()
            self.addCleanup(page.close)
            errors: list[str] = []
            page.on(
                "console",
                lambda msg: errors.append(msg.text) if msg.type == "error" else None,
            )
            page.on("pageerror", lambda exc: errors.append(str(exc)))
            fake = (
                "window.ZIVON_COURSES=[{course_id:'PHY9-MOTION',"
                "title:'Motion',chapter:'Motion and Force',"
                "href:'courses/motion/index.html'}];"
            )
            page.route(
                "**/courses.js",
                lambda route: route.fulfill(
                    status=200,
                    body=fake,
                    content_type="application/javascript",
                ),
            )
            page.goto(f"{base_url}/index.html")
            card = page.locator("#zn-courses a.zn-card")
            expect(card).to_have_count(1)
            expect(card).to_contain_text("Motion")
            self.assertEqual(errors, [])
```

Notes:

- Prefer `get_by_role`, `get_by_label`, `get_by_text`. Use CSS only for a
  stable contract id when no user-facing locator exists.
- Use `expect(locator)` (web-first assertion) so Playwright retries until the
  condition or the timeout. Do not assert `is_visible()` immediately.
- Collect `console` errors and `pageerror` on every page that claims a clean
  load; assert the list is empty at the end.
- One browser per class is fine; one **context** per test is the isolation
  boundary (storage, cookies, cache). Close pages in `finally` or `addCleanup`.
- For a test that must prove "no external requests", attach
  `page.on("request", ...)` and fail on a request whose URL is not same-origin.

## 4. Waiting without flakiness

| Do | Don't |
|---|---|
| `expect(locator).to_be_visible()` | `time.sleep(0.5)` |
| `page.wait_for_selector(sel, state="visible")` | `page.wait_for_timeout(1000)` |
| `page.wait_for_function("() => window.state.ready === true")` | Polling with `while` and no timeout |
| Drive the event: dispatch, resolve a promise, release a queue | Guess that 200 ms is enough |
| Assert the observable state, then the next action | Assert an internal call counter |

A fixed timeout is a **deadlock guard**, not a synchronisation mechanism. If a
test needs one to pass, the page is missing a deterministic ready signal; add
the signal or test the state directly.

## 5. State coverage

`docs/specs/frontend/state-matrix.md` defines ten canonical states per screen
row: **default, loading, empty, partial, error, offline, permission-denied,
reduced-motion, untranslated, over-credit-budget**. The matrix is the source of
truth for what each cell should show; a blank cell is a defect, and `n/a` is
valid only with a reason.

For a new browser test, walk the row and decide:

- Which states are reachable without a backend? (Most are.)
- Which need injected data or a route stub? (`window.ZIVON_COURSES`,
  `page.route` for a failed `fetch`, a localStorage flag for consent.)
- Which are genuinely not applicable, and why? Put the reason in the test
  docstring or the PR.

High-value states on this product:

- **Empty catalogue**: `ZIVON_COURSES = []` shows the honest empty message, not
  a blank page.
- **Broken simulation**: the on-canvas error painter shows "simulation error:"
  and the rest of the lesson stays readable; it never blanks the page.
- **Untranslated block**: a `.zn-untranslated-notice` appears; the page does not
  silently serve English as Hindi.
- **Offline**: cached content still reads; the offline chip appears; a network
  action is disabled with an explanatory title.
- **Reduced motion**: a registered simulation draws exactly once, no rAF loop.
- **Quota exhausted**: the voice dock switches to typed mode; an in-progress
  turn is never cut.

## 6. Accessibility

Automated tools catch a subset. WCAG 2.2 is a W3C Recommendation (12 December
2024) with success criteria that include judgement calls no scanner can settle;
axe-core is an automated rule engine for WCAG 2.0/2.1/2.2 A/AA/AAA plus best
practices. **Zero axe violations is evidence, not a compliance certificate.**

### Automated pass (when axe is present)

- Pin a specific axe-core build and vendor it under `testing/frontend/vendor/`
  (with its license) or install it as a test-only asset; never load it from a
  CDN. The repo does not vendor axe yet, so adding it is a dependency decision
  for the frontend owner, recorded in the PR.
- Run against the real surface, not a hand-written fragment, with the WCAG 2.2
  A/AA tags.
- Fail on `serious` and `critical`; report `moderate`/`minor` as findings.
- Keep the scan in the browser suite so it runs on every PR.

```python
from pathlib import Path

AXE = Path(__file__).resolve().parent / "vendor" / "axe.min.js"


def assert_no_serious_axe_violations(page) -> None:
    page.add_script_tag(path=str(AXE))
    result = page.evaluate(
        """async () => await axe.run(document, {
             runOnly: {type: "tag", values: ["wcag2a", "wcag2aa", "wcag22aa"]}
           })"""
    )
    serious = [
        violation
        for violation in result["violations"]
        if violation["impact"] in {"serious", "critical"}
    ]
    assert serious == [], serious
```

### Keyboard pass

Every interactive surface needs a keyboard walkthrough, automated where the
assertion is stable:

- Tab reaches every control in a sensible order; no keyboard trap.
- Enter/Space activate buttons; Escape closes a dialog; arrow keys move within
  a radiogroup (`role="radio"`, `aria-checked`).
- Focus is visible and not obscured by a sticky bar or the voice dock.
- `aria-disabled="true"` is used for a locale with no bundle, not a control
  that silently does nothing.
- Checks are `fieldset`/`legend` groups with `aria-live` feedback; a wrong
  answer offers retry, never a dead end.
- A canvas simulation has a text alternative and a populated `.zn-sim-read`
  mirror; the mirror is announced, not just painted.
- Target size is at least 44 px; no meaning is carried by colour alone; no
  interaction is timed.

### Human gates (do not automate away)

- Keyboard-only walkthrough per release.
- Screen-reader walkthrough of the check feedback and the sim mirror
  (TalkBack on the low-end Android target, VoiceOver for iOS).
- Whether alt text and explanations are *useful* for a Class 9–12 learner.
- Cognitive load and plain-language quality.

Record the date, device, and result in the PR or the release checklist. A
green axe run does not replace these.

## 7. Performance budgets

Use the existing harness rather than a stopwatch:

- `testing/frontend/test_perf_budget.py` covers the landing page, every
  published course page, simulation FPS under CPU throttle, RAM, LongTask/INP
  proxy, CLS, reduced-motion single draw, the sim read mirror, and the font
  payload.
- Profiles: `testing/content_factory/perf/profiles/weak-android.json` (shipping
  gate) and `mid-laptop.json`. Current weak-Android numbers: load 6.0 s, FCP
  3.5 s, RAM 750 MB, 24 fps floor, overflow at most 2 px. The frontend font
  budget is 300 KB.
- The harness re-export at `testing/content_factory/perf/harness.py` exists
  because the factory imports it at runtime; the canonical grader is
  `evals/checkers/perf_harness.py`.

Rules:

- Assert the budget from the named profile, not a magic number in the test.
- When the suite cannot launch Chromium, report it as skipped (if the suite
  provides a skip path) or fail loudly. Never fabricate FPS or load numbers and
  never silently pass.
- A budget change is a product decision. Update the profile/spec and say so in
  the PR; do not loosen the test to make a page pass.
- Do not add pixel or CSS screenshots. Font hinting and canvas anti-aliasing
  vary across containers; layout is asserted as DOM geometry instead.

## 8. CI and evidence

- `python -m unittest discover -s testing/frontend -t .` is the suite; CI's
  `tests` job installs Chromium and runs it.
- A skipped browser test is printed as skipped by unittest and must be reported
  as skipped in the PR, with the install command that would enable it.
- On failure, attach the Playwright trace (or the failing page HTML plus the
  console list) to the PR. A screenshot alone rarely explains a timing bug.
- Keep the browser version aligned with CI. A locally green test on a newer
  browser is not evidence for the pinned one.

## 9. Anti-patterns

| Pattern | Why it fails |
|---|---|
| `time.sleep` / `wait_for_timeout` | Hides the race, slows CI, fails on a slow runner |
| Asserting CSS pixels or a screenshot | Anti-aliasing and fonts differ across containers |
| Sharing one page across tests | Storage and DOM state leak; order dependence |
| Loading from `file://` while asserting a clean console | CORS font errors that production never sees |
| Testing only the happy state | Empty/error/offline/quota states are where the product breaks |
| `page.evaluate("document.querySelector(...).click()")` for everything | Bypasses actionability and user-visible locators |
| A green axe run claimed as WCAG compliance | Automated tools cover a subset; human gates remain |
| A skipped test reported as passed | False confidence; the suite lies |
