# Frontend testing

The frontend is tested twice: **deterministic code tests** in `testing/frontend/`
(markup, behaviour, states, a11y, perf), and **judged quality evals** in
`evals/` only when the change affects content quality. UI chrome does not need
an eval; it needs a test.

All tests are key-free and offline. No live model, no TTS, no network, no
secrets. If a test needs a browser, install Chromium; if it needs a server,
use a local static server. Do not skip the test and call it green.

Run:

```bash
python -m playwright install chromium          # once
python -m unittest discover -s testing/frontend -t .
python -m unittest discover -s testing/skills -t .
ruff check . && ruff format --check .
```

## 1. The existing test layout

| File | What it protects |
|---|---|
| `testing/frontend/test_shell.py` | Self-contained shell: no external refs, internal links resolve, cache-busted asset refs resolve, published catalogue entries resolve, fonts shipped with licence, landing loads clean with a11y basics, empty catalogue contract, catalogue renders from `courses.js` |
| `testing/frontend/test_behaviour_layer.py` | Quiz correct/retry feedback, numeric tolerance, broken simulation fails loudly, a long question stays inside the card |
| `testing/frontend/test_frontend_features.py` | Branded 404 + nginx contract, router/localized hook, locale persistence, untranslated notice, telemetry privacy, state-matrix walkthrough + DCR-002 guard, voice WS state machine and mock server, reconnect/backoff/stale socket, offline detection, typed doubt survives reconnect, exhausted retries, connect timeout, keepalive, pagehide cleanup, ducking, PCM playback/jitter/barge-in, frame gaps, offline chip, SEO sitemap/robots/JSON-LD |
| `testing/frontend/test_perf_budget.py` | Landing and published-snapshot load, sim fps under throttle, RAM, long tasks, CLS, reduced-motion single draw, sim read mirror, font payload |
| `testing/frontend/test_voice_dock_ledger.py` | Dock detail: language menu never switches, detected-language event, one retry icon, no block IDs in the dock, one panel toggle, append-only transcript, at most one status line, mic toggle + bars, single tape, DOM budget |
| `testing/frontend/test_wave_e2_complete.py` | Mic capture PCM16, first press never says offline, disabled lang chip no-op, Space does not hijack controls, shell injection fixture + missing manifest, consent decline/no re-nag/error isolation/doctrine gate, dock containment/barge-in/a11y, privacy/report/telemetry/credit/locale bar, wipe failure honesty, scoped CSP, read-aloud autofetch, localized manifest |

The module names are the contract. Add a test to the file that owns the
behaviour; do not create a parallel suite with the same job.

## 2. What to test for a new screen

### Static markup and delivery

- The route returns 200, the right content type, and the expected headers.
- No external URL in the HTML, CSS, or JS (`http://`, `https://`, `//host`).
- No inline `<script>` or inline event handler; no `eval`/`Function`.
- The canonical URL, title, description, OG tags, and JSON-LD are present (or
  `noindex` is present on a private page).
- Internal links resolve to files; no dead `href="#"`.
- The page loads with JavaScript disabled: text, examples, diagrams, checks,
  and sources are readable.
- The 404 is branded; a missing route returns it.
- The nginx contract: CSP, `nosniff`, `no-referrer`, cache rules, scoped
  `connect-src` for `/courses/` and `/privacy/`.

### Behaviour

- One behaviour per test. A failing assertion names the contract, not “it
  works”.
- Quiz: unanswered, correct, wrong, retry, numeric tolerance, numeric parse
  failure.
- Simulation: registration, draw, slider input, error painter, live mirror,
  reduced-motion single draw, no rAF loop.
- Dock: every state transition, barge-in, typed fallback, reconnect, pagehide
  release, consent gate, no re-nag.
- Lesson shell injection: content-only fixture, no manifest, consent declined,
  a thrown step leaves the page readable, no double mount.
- Locale: chip selection, persistence, disabled chip no-op, untranslated
  notice, language bundle swap, `lang` attribute.
- Forms: validation, error association, submitting state, double-submit guard,
  delete confirmation.
- Tests: autosave, resume, timer warning, expiry auto-submit, review.
- Privacy: challenge → delete, failed wipe honesty, local keys after ack.

### State coverage

- Walk every row of the state matrix. Each state gets a DOM assertion or an
  explicit `n/a` reason in the spec.
- Test the failure first: error, offline, permission, quota, consent. The happy
  path is the easy one.
- Test the 360 px frame for overflow; use the harness's overflow gate.
- Test reduced motion by emulating `prefers-reduced-motion: reduce`.
- Test the untranslated fallback: English string + visible marker, never a
  silent mix.

### Accessibility

- Zero serious/critical axe findings on each changed public/app screen, if the
  repo's axe integration is available; otherwise run the keyboard and
  screen-reader checklist and record it.
- Keyboard-only walkthrough: every action reachable, focus visible, modal focus
  returned, no trap.
- 44 px target check on the primary controls.
- Heading order, landmarks, one `<h1>`.
- `aria-live` feedback is announced once, not on every tick.
- Canvas mirror is non-empty; diagram has an accessible name.
- Colour-only check: remove hue and the meaning survives.

### Performance

- `test_perf_budget.py` with the weak-Android profile: load, FCP, fps, RAM,
  long tasks, CLS.
- JS and font byte budgets.
- No external request during load.
- No layout thrash in the timer/palette.
- The sim draws once under reduced motion.

## 3. Fixtures and the no-network rule

- Use the real shell files (`zivon.css`, `zivon.js`) from the repo; do not
  copy them into a fixture that can drift.
- A synthetic page in a temp directory is fine for a component test; drive it
  with a local `http.server` or `file://` as the existing tests do.
- Mock at the seam: a fake WebSocket server for the dock, a fake `fetch` for an
  API, a fake `AudioContext` for playback. Never hit a real vendor.
- Mock data must be synthetic: no real student name, email, transcript, or
  audio. Use `Class 9`, `Chapter 3`, `12 N`, `2026-11-14`.
- A test that needs a key is not a frontend test. Move it to the owning
  backend/evals suite.
- Keep fixtures small; a giant golden HTML blob hides the contract it tests.

## 4. Regression and review

- Every bug fix gets a test that fails before and passes after.
- A test must not be bent to pass; if the contract is wrong, change the
  contract and the test together, with a reason.
- Do not skip a test without a reason string.
- Do not add a snapshot-only test; assert the behaviour or the contract.
- The PR body lists the tests run and the states covered.
- A frontend PR that changes a screen without a state matrix or a11y/perf
  evidence is incomplete.

## 5. CI truth

- The `tests` job runs `python -m unittest discover -s testing/frontend -t .`
  with headless Chromium; a new file under `testing/frontend/` is picked up
  automatically.
- The `frontend-image` job builds the nginx image, seeds the shell into a
  writable root, serves it, and checks `/healthz`, the landing page, assets,
  CSP/nosniff/no-store headers.
- The `quality` job runs `ruff check` and `ruff format --check`.
- The perf suite needs no new CI job; it lives under `testing/frontend/`.
- The in-cluster `test-suite` CronJob runs the same suite on a schedule; the
  manual button is `scripts/trigger-tests.sh`.
- Evals are separate: `python -m evals run --suite smoke --mock` for judged
  content quality. Do not put a model judge in a frontend unit test.

## 6. Test-writing checklist

- [ ] The test is deterministic, key-free, offline.
- [ ] It names the contract in the assertion message.
- [ ] It covers a failure state, not just the default.
- [ ] It uses the real kit files, not a copy.
- [ ] It has no real student data, audio, or secret.
- [ ] It runs under `unittest discover` from the repo root.
- [ ] It does not depend on a published page that may be absent; skip with a
      reason when the snapshot is missing.
- [ ] The PR lists the command and the result.
