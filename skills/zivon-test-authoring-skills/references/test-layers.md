# Test layers

What each layer proves, what it cannot prove, where it lives, and the command
that runs it. The rule behind the table: **pick the cheapest layer that can
observe the break, then cross every real boundary at least once** with the real
implementation or a faithful fake. A suite made only of mocks proves the mocks
agree with the code, not that the code agrees with the world.

## 0. The layers in one table

| Layer | Primary question | Runs | Speed | Home | Command |
|---|---|---|---|---|---|
| Static / shell contract | Do the files, links, headers, and static structure satisfy the contract? | No browser, no imports of the app under test | ms | `testing/frontend/test_shell.py` (level 1), `testing/content_factory/unit/test_render.py` | `python -m unittest testing.frontend.test_shell.TestShellContract` |
| Unit | Does one pure mechanic compute the right observable? | One process, no network, no real clock | ms | `testing/*/unit/`, `testing/voice/`, `testing/backend/` | `python -m unittest discover -s testing/content_factory/unit -t .` |
| Contract / interface | Does the adapter map the documented wire shape correctly, and does the interface stay stable? | In-process fake transport, real serializer | ms–s | `testing/voice/test_*_client.py`, `testing/content_factory/unit/test_llm_manager*.py` | the owning suite |
| Integration | Do the stages, resume guards, catcher routing, and failure paths work together? | Real orchestrator subprocess + mock inference server + real Chromium | tens of seconds | `testing/content_factory/integration/test_end_to_end.py` | `python -m unittest testing.content_factory.integration.test_end_to_end` |
| Browser behaviour | Does the runtime DOM do what the student sees, with a clean console? | Headless Chromium | seconds | `testing/frontend/test_behaviour_layer.py`, `test_frontend_features.py` | `python -m unittest discover -s testing/frontend -t .` |
| Accessibility | Is the surface operable and announced, not just present? | Chromium + axe (when added) + keyboard walkthrough | seconds + human gate | browser tests + release checklist | Playwright + axe |
| Performance budget | Does the page meet the hardware budget? | Chromium with CPU/RAM throttling | tens of seconds | `testing/frontend/test_perf_budget.py`, `evals/checkers/perf_harness.py` | frontend suite |
| Eval | Is the model/prompt/reviewer output good enough? | Deterministic checkers, then a judge | minutes | `evals/` | `python -m evals run --suite smoke --mock` |

These map to the small / medium / large test sizes described in *Software
Engineering at Google*: small tests run in one process, medium tests may use
localhost, large tests may cross machines. The book's point matches this repo's
experience: **speed and determinism come from the size constraint**, so do not
reach for a larger test until the smaller one genuinely cannot see the bug.

## 1. Static / shell contract tests

**Proves:** the shipped files are internally consistent. On this repo that means
self-containment (no external `src`/`href`/`fetch`), every local reference
resolves, font licensing is present, `courses.js` entries resolve to a real
`index.html` and `manifest.json`, CSP strings are what the page needs, block ids
are stable, and localized routes carry the i18n attributes.

**Cannot prove:** that the page runs, that a simulation draws, that a check
grades, that focus is visible, or that a screen reader announces anything.

**Use when:** the contract is visible in bytes — HTML attributes, JSON keys,
relative paths, CSP directives, manifest fields. This is the first line of
defence because it is fast and hermetic.

**Repo examples:**

- `testing/frontend/test_shell.py` `TestShellContract` — no browser; scans the
  shell and the published snapshot. Run just this class when only the static
  contract is in scope: `python -m unittest testing.frontend.test_shell.TestShellContract`.
- `testing/content_factory/unit/test_render.py` — page HTML, CSP, manifest,
  staging layout, lint-gated render, `courses.js`.

**Guardrail:** do not re-implement the renderer's job in a test. If the contract
is "the renderer must emit `data-i18n`", assert the attribute on the rendered
output, not a regex over the renderer source.

## 2. Unit tests

**Proves:** one function, class, or pure module computes the observable the
contract names. Examples in this repo: config validation, schema validation,
lint rules, text normalization/chunking, retrieval with a fixture embedder,
chunker boundaries, credit meters, tag whitelists, state-machine transitions,
formula evaluation.

**Cannot prove:** that the composition root wired the module, that the wire
format is right, that SQL runs on Postgres, or that the page renders.

**Rules:**

- One behaviour per test; the test name states scenario and expectation.
- No subprocess, no HTTP, no real filesystem outside a temp directory, no
  wall clock, no random without a seed.
- A unit test may use SQLite in memory (see `db/engine.py`) when the behaviour
  is repository mechanics, but that is not proof of Postgres behaviour.
- If a unit test needs five mocks, the design is probably wrong: move the
  boundary or introduce a fake.

**Repo commands:**

```bash
python -m unittest discover -s testing/content_factory/unit -t .
python -m unittest discover -s testing/voice -t .
python -m unittest discover -s testing/backend -t .
python -m unittest discover -s testing/observability -t .
python -m unittest discover -s testing/narration -t .   # needs ffmpeg
python -m unittest discover -s testing/translation -t .
python -m unittest discover -s testing/evals -t .
python -m unittest discover -s testing/skills -t .
```

## 3. Contract / interface tests

**Proves:** the adapter speaks the documented shape. This is the layer that
catches a vendor changing `segment_end` to `complete`, an OpenAI-compatible
server returning a usage chunk in the wrong place, a WebSocket client expecting
a field the server stopped sending, or a database adapter using `?` where the
Postgres driver needs `%s`.

**Cannot prove:** that the real vendor behaves as documented. That needs a live
probe, recorded as evidence, or a contract fixture captured from the vendor and
dated. A contract test with a fake proves the adapter against the fixture, not
against the vendor's current deployment.

**What a good one asserts:**

- Required fields, types, and enums — not a full JSON snapshot.
- The public method signature and its error type.
- Streaming order: first frame before completion, final marker last, error
  closes cleanly.
- Failure mapping: vendor error code becomes this repo's typed error; the
  caller can degrade.
- Resource cleanup: socket closed, temp file removed, row count unchanged on
  failure.

**Repo examples:**

- `testing/voice/test_tts_client.py` — a `FakeTimbreTransport` implements the
  `TtsTransport` protocol; tests cover the real request payload, base64 audio,
  the `complete` marker, tag/char guards, and the F4 failure path.
- `testing/voice/test_brain_client.py` — mock SSE stream; first-event and
  inactivity deadlines, retry, abort.
- `testing/content_factory/unit/test_llm_manager.py` — streaming, usage,
  retries, deadline abort, bad-shape errors, validation rounds.
- `testing/content_factory/unit/test_llm_manager_service.py` — FastAPI
  `TestClient` against the node, no live upstream.
- `testing/backend/test_voice_mount.py` — the app factory registers
  `/voice/ws` and wires the `ZIVON_VOICE_*` family without opening a vendor
  connection.

**Guardrail:** do not assert the fake's internal call list unless the call *is*
the contract (for example, "the client must send exactly one synthesis request
per segment"). Prefer the outbound payload and the returned frames.

## 4. Integration tests

**Proves:** the composition works. The factory integration test runs the real
orchestrator as a subprocess against `testing/content_factory/mocks/openai_mock.py`,
with fixture PDFs, then exercises resume, fingerprint guards, catcher routing
(03→04, 09→10, bounded), observability assertions, and a loud-failure run
against a dead server. Browser integration loads real pages in Chromium.

**Cannot prove:** teaching quality, factual grounding, reviewer calibration, or
real hardware performance. Those are evals (or a manual gate).

**Rules:**

- Stage the world into a temp directory. `test_end_to_end._build_env()` copies
  fixtures and a frontend shell into `tmp`; the test never writes the repo.
- Use the mock server's one-shot failure injections (`__fail500`, `__fail400`,
  `__badshape`, `__slow`, `__stall`, `__midstream_close`, `__stream_error`) to
  prove recovery, not just the happy path.
- Assert the observable artefact: `output.json`, `status.json`,
  `run_report.json`, the linked page, the call ledger. Do not assert private
  function calls.
- Keep the run bounded. A pipeline integration test that can hang is a suite
  outage waiting to happen; use the orchestrator's own deadlines.

**Command:**

```bash
python -m unittest testing.content_factory.integration.test_end_to_end
```

## 5. Browser behaviour tests

**Proves:** the runtime surface. On this repo: a clean load with zero console
errors and zero page errors, the empty-catalogue contract, catalogue rendering
from injected `ZIVON_COURSES`, quiz correct/incorrect flows, the simulation
error boundary (loud painter, page still readable), keyboard navigation, and
reduced-motion behaviour.

**Cannot prove:** visual design quality, meaningful alt text, screen-reader
announcement quality, or real low-end device performance. Automated tools can
only approximate the first and last of those; the middle two are human gates.

**Rules and mechanics:** see
[browser-and-a11y-tests.md](browser-and-a11y-tests.md). The short version:
serve over HTTP, use role/label locators, use web-first assertions, collect
console/page errors, isolate browser contexts, never sleep.

**Command:**

```bash
python -m unittest discover -s testing/frontend -t .
```

## 6. Accessibility tests

**Proves (automated):** every `<img>` has an accessible name, every control has
a role/name, labels are associated, heading order is sane, ARIA attributes are
valid, contrast meets the configured rule set, and targets are large enough.
**Proves (keyboard):** every control is reachable in a sensible order, Enter and
Space activate, Escape closes, arrow keys work in a radiogroup, focus is
visible and not obscured.

**Cannot prove:** that the alt text is *useful*, that a screen-reader user can
complete the task, that the language is plain enough, or that cognitive load is
acceptable. WCAG requires human evaluation for those; axe-core covers only a
subset of success criteria and returns zero violations for its rules, not a
certificate.

**Repo acceptance criteria:** axe zero serious/critical per published page, a
keyboard-only walkthrough per release, a screen-reader walkthrough of the sim
mirror and check feedback, target size at least 44 px, no colour-only meaning,
and no timed interactions.

## 7. Performance budget tests

**Proves:** the page meets a named profile. The current weak-Android profile
carries load 6.0 s, FCP 3.5 s, RAM 750 MB, 24 fps floor, and overflow at most
2 px. The harness measures the browser process tree, canvas FPS under CPU
throttle, LongTask/INP proxy, CLS, font payload, and the sim read mirror.

**Cannot prove:** that a real low-end phone in a classroom behaves the same. It
is a budget, not a lab. A budget change is a product decision, not a test tweak.

**Honesty rule:** when Chromium is unavailable, the hardware budget is reported
as skipped. It is never replaced with fabricated FPS/load numbers. The
`testing/content_factory/perf/harness.py` re-export exists because the factory
imports it at runtime; the canonical grader is `evals/checkers/perf_harness.py`.

## 8. What is not a layer here

- **Pixel or CSS snapshots.** Explicitly rejected in `testing/README.md`: font
  hinting and canvas anti-aliasing vary across Linux containers and devices.
  Layout is asserted as DOM geometry (overflow ≤ 2 px, legend containment,
  read-mirror populated), not as a screenshot.
- **Framework-style component tests.** The shell is hand-maintained HTML/CSS/JS;
  contract plus behaviour coverage is the right weight.
- **Eval suites in `testing/`.** Model quality, prompt contracts, reviewer
  calibration, and generated-page quality live in `evals/`. See
  [evals-vs-tests.md](evals-vs-tests.md).
- **A live vendor smoke test in CI.** CI is key-free. Live probes are founder
  or infra-window work and their evidence is recorded.

## Choosing a layer: the short decision tree

```
Is the expected value computable from fixed input with no model?
├── yes → Is the assertion about one function/module's mechanics?
│         ├── yes → UNIT
│         └── no  → Does it cross a wire/DB/browser boundary?
│                   ├── wire/adapter → CONTRACT
│                   ├── DB query     → CONTRACT + a Postgres-gated test where dialect matters
│                   ├── stage graph  → INTEGRATION
│                   └── DOM/runtime  → BROWSER (add a11y when interactive)
└── no  → EVAL (checker first, judge only if a judgement is required)
```

If two layers can see the same break, write the cheaper one and add the larger
one only when the failure would otherwise be invisible (for example, a unit test
proves the parser; an integration test proves the stage actually calls it).
