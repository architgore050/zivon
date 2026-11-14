---
name: zivon-test-authoring-skills
description: Writes and reviews deterministic tests for Zivon across unit, integration, contract, browser, accessibility, performance, and static-shell layers; keeps fixtures and goldens hermetic; mocks Prisma, Gemini, Timbre, llm_manager, and database seams; and decides whether a check belongs in testing/ or in an evals/ card. Use when adding or changing tests, when a change needs coverage, when a bug fix needs a regression test, when tests are flaky, over-mocked, or tautological, when wiring test discovery or CI path guards, or when asked "what tests should I write", "is this tested", "does this need an eval", or "why is CI not running this suite".
license: MIT
compatibility: Python 3.12+ for the unittest suites. Browser and performance layers need Playwright Chromium (python -m playwright install chromium); narration needs ffmpeg. All deterministic suites run key-free and offline.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-14"
---

# Zivon Test Authoring

Write the smallest test that would fail for the right reason if this change
broke, at the cheapest layer that can observe the break. Zivon's merge gate is
key-free, offline, and deterministic; a test that needs a model, a vendor
socket, or a developer's clock is not a test here.

## When to use this

Use it when any of these is true:

- You are adding or changing behaviour and need to decide what to test and at
  which layer.
- A bug fix needs a regression test that fails without the fix.
- You are adding an adapter, a WebSocket message, an HTTP route, a database
  query, or a vendor seam and need a contract test.
- A browser surface, accessibility guarantee, or performance budget changed.
- Tests are flaky, slow, over-mocked, tautological, or order-dependent.
- CI is not discovering a suite, or a new suite needs a path guard.
- A change affects model output, prompt quality, reviewer calibration, or
  generated-page quality, and you need to know whether it belongs in
  `testing/` or `evals/`.

Do not use it to review a PR as a whole — use `skills/code-review/` and its
`review-tests` lens. This bundle writes the tests; that lens judges them.

## The first fork: test or eval

This is a binary rule in this repo, not a preference. The full decision table
is in [references/evals-vs-tests.md](references/evals-vs-tests.md).

| Question the check answers | Home | Why |
|---|---|---|
| "Does this code execute its deterministic contract?" | `testing/` | Code mechanics, expected value computable without a model |
| "Does this prompt/model/reviewer produce good output?" | `evals/` | Judgment needs a judge or a calibrated corpus |
| "Does this generated page teach, ground claims, or meet a hardware budget?" | `evals/` | Quality of model output, not code mechanics |
| "Is this transport payload shaped correctly?" | `testing/` | Contract test at the adapter/seam |
| "Can a checker decide it with zero model calls?" | `evals/checkers/`, exercised by `testing/evals/` | Deterministic-first funnel |

The operational test: if the assertion needs a live or mocked model to decide
pass/fail and the expected answer is a judgement, it is an eval. If a fixed
input deterministically yields a fixed observable, it is a test. A test that
needs a model belongs in neither place as a unit test.

## Test-selection workflow

1. **Name the behaviour and the failure.** Write one sentence: "If `<change>`
   breaks, `<student/operator>` sees `<observable wrong result>`." If you
   cannot name the observable, you are not ready to write the test.
2. **Find the seam.** Locate the boundary the behaviour crosses: pure function,
   adapter, SQL query, WebSocket message, browser DOM, vendor stream. The seam
   decides the double and the layer.
3. **Pick the cheapest layer that can see the break.** Prefer a unit test.
   Cross each boundary at least once with the real implementation or a faithful
   fake. Use [references/test-layers.md](references/test-layers.md) for the
   layer table and commands.
4. **Choose the double at the seam you own.** Reuse `testing/voice/mocks/`,
   `testing/content_factory/mocks/`, and the FastAPI test client before writing
   a new one. Never mock the thing under test. Read
   [references/mocking-vendor-seams.md](references/mocking-vendor-seams.md).
5. **Build the fixture deterministically.** Checked-in input, temp directory for
   output, no network, no key, no wall clock, no sleep. For goldens and seeded
   defects, read [references/fixtures-and-goldens.md](references/fixtures-and-goldens.md).
6. **Write one behaviour per test.** Arrange–act–assert visible; the test name
   states scenario and expectation; the assertion message names the contract.
   Copy [templates/test-case.md](templates/test-case.md) when a blank page is
   the problem.
7. **Prove it can fail.** Flip the production condition, buffer the stream,
   drop the field, or return a constant; watch the new test go red. Restore and
   watch it go green. For a bug fix, run it against the base commit first.
8. **Run the touched suite, then lint and types.** The exact commands are in
   [references/ci-and-path-guards.md](references/ci-and-path-guards.md).
9. **Judge it before review.** Run
   [references/test-review-checklist.md](references/test-review-checklist.md)
   against your own diff.

## Layer map at a glance

| Layer | What it proves | Typical home | Run |
|---|---|---|---|
| Static / shell contract | Files, links, CSP, self-containment, catalogue integrity — no browser | `testing/frontend/test_shell.py`, `testing/content_factory/unit/test_render.py` | `python -m unittest discover -s testing/frontend -t .` |
| Unit | One pure mechanic: parser, schema, config, chunker, meter, state machine | `testing/<area>/unit/`, `testing/voice/*` | `python -m unittest discover -s testing/content_factory/unit -t .` |
| Contract / interface | Wire shape and protocol at an adapter seam | `testing/voice/test_tts_client.py`, `testing/backend/test_voice_mount.py`, `testing/content_factory/unit/test_llm_manager.py` | the owning suite |
| Integration | Real orchestrator, mock vendor, stage wiring, resume, failure injection | `testing/content_factory/integration/test_end_to_end.py` | `python -m unittest testing.content_factory.integration.test_end_to_end` |
| Browser behaviour | Runtime DOM, console cleanliness, state rendering, keyboard | `testing/frontend/test_behaviour_layer.py`, `test_frontend_features.py` | `python -m unittest discover -s testing/frontend -t .` |
| Accessibility | Automated rule subset plus keyboard/semantics walkthrough | browser tests plus manual gate | Playwright + axe |
| Performance budget | Load/FCP/FPS/RSS/overflow on a hardware profile | `testing/frontend/test_perf_budget.py`, `evals/checkers/perf_harness.py` | the frontend suite |

Read [references/test-layers.md](references/test-layers.md) before choosing a
layer; read [references/browser-and-a11y-tests.md](references/browser-and-a11y-tests.md)
before the first browser or accessibility test.

## Where tests live and how they run

- Tests live under `testing/<area>/` as Python packages (`__init__.py`) with
  `test_*.py` modules. Folder names use underscores; docs may call them by the
  hyphenated product name.
- Discovery is always from the repo root:
  `python -m unittest discover -s testing/<area> -t .`.
- Every deterministic suite must pass with no API key, no network, no running
  vendor service. The only database credential in CI is a throwaway Postgres
  service for backend and migration tests.
- Browser tests need Chromium once:
  `python -m playwright install chromium`. The frontend suite fails loudly when
  Playwright is missing (there is no silent shim); the integration perf checks
  skip with a reason when Chromium is unavailable. A skip is never reported as
  a pass.
- CI runs the factory unit set, the integration test, the frontend suite, each
  Wave-E suite that exists, the deterministic eval smoke, lint, format, and
  types. The deterministic eval gate is
  `python -m evals run --suite smoke --mock`; the full/calibration suites run in
  an infra window, not in CI. Path guards keep reserved jobs green until their
  service lands; do not add a duplicate job for a suite that discovery already
  covers. See [references/ci-and-path-guards.md](references/ci-and-path-guards.md).

## Non-negotiables

1. **Hermetic by construction.** No live network, no API key, no model call, no
   paid vendor, no wall-clock dependency. Vendors are replaced at the seam.
2. **Assert observable outcomes.** Returned values, persisted rows, emitted
   messages, rendered DOM, streamed frames. Assert a mock interaction only when
   the interaction is the product behaviour.
3. **One reason to fail.** One behaviour per test; a failure message alone says
   what contract broke.
4. **A regression test must fail without the fix.** Verify on the base commit or
   with the fix reverted; do not assume.
5. **Fixtures and goldens are tracked and purposeful.** Never invent a golden,
   never edit a seeded defect to make a reviewer pass, never mutate a tracked
   fixture in place.
6. **Honest skips.** A test that cannot run (browser, ffmpeg, Postgres) skips
   with the reason or fails loudly according to its suite's contract; it is
   never converted into a pass and never replaced with fabricated numbers.
7. **Do not weaken a test to make a change pass.** If the contract changed,
   change the test and the doc deliberately in the same PR, and say why.
8. **No secrets or learner data.** No keys, DSNs, tokens, transcripts, raw
   audio, names, emails, phone numbers, or school names in fixtures, goldens, or
   failure messages.

## Worked example

A streaming contract for the voice TTS client: prove that
`TtsClient.speak()` yields the first audio frame as it arrives, not after the
segment completes. The test uses a gated `TtsTransport` fake, an injected
clock, and `asyncio.wait_for` only as a deadlock guard — then a mutation that
buffers frames is shown to turn it red. The full walkthrough, including what the
test deliberately does not prove, is in
[references/worked-example-voice-contract.md](references/worked-example-voice-contract.md).

## Quality gate

Before calling a test done, every row must be yes.

| Check | Test |
|---|---|
| Right layer | The cheapest layer that can observe the break is used; each boundary is crossed at least once |
| Seam | The double is at a seam the repo owns; the thing under test is real |
| Determinism | No network, key, sleep, wall clock, order dependence, or shared mutable state |
| Fault detection | A named mutation of the production code turns the test red |
| Regression | A bug-fix test fails on the base commit |
| Refactor resilience | Assertions target observable behaviour, not private structure or call order |
| Failure clarity | The test name and assertion message identify the contract |
| Hygiene | Fixture is minimal and tracked; output goes to a temp dir; cleanup runs |
| Docs | The suite README, `testing/README.md`, or the owning spec is updated when the contract changed |

## Reference map

| Read this | When |
|---|---|
| [references/test-layers.md](references/test-layers.md) | Choosing between unit, contract, integration, browser, a11y, and perf; you need the exact command and what each layer cannot prove |
| [references/fixtures-and-goldens.md](references/fixtures-and-goldens.md) | Creating or changing a fixture, golden topic, seeded defect, recorded artifact, or fixture manifest |
| [references/mocking-vendor-seams.md](references/mocking-vendor-seams.md) | Writing a Prisma, Timbre, Gemini/brain, llm_manager HTTP, database, or clock double; SQLite/Postgres parity |
| [references/browser-and-a11y-tests.md](references/browser-and-a11y-tests.md) | Writing Playwright, state-coverage, axe, keyboard, or perf-budget tests; fixing a flaky wait |
| [references/evals-vs-tests.md](references/evals-vs-tests.md) | The boundary is unclear, or you are adding an eval card, checker, golden, or calibration run |
| [references/ci-and-path-guards.md](references/ci-and-path-guards.md) | Wiring a suite into CI, adding a path guard, or running the merge gate locally |
| [references/test-review-checklist.md](references/test-review-checklist.md) | Before opening a PR, or when judging whether a suite would catch a regression |
| [references/worked-example-voice-contract.md](references/worked-example-voice-contract.md) | You want a complete example of the workflow, including the mutation that proves the test |

## Templates

Copy one when the artifact, not the test body, is the hard part.

| Template | Use when |
|---|---|
| [templates/test-plan.md](templates/test-plan.md) | A change spans several behaviours or layers and needs a coverage plan before coding |
| [templates/test-case.md](templates/test-case.md) | Writing a new test module or converting a vague test into one behaviour |
| [templates/fixture-manifest.md](templates/fixture-manifest.md) | Adding a non-obvious fixture, golden, recorded artifact, or seeded defect |
| [templates/browser-test-checklist.md](templates/browser-test-checklist.md) | Adding or reviewing a Playwright, accessibility, or perf-budget test |

## Anti-patterns

- **Mock tautology:** the mock returns what the code expects, and the test
  asserts the mock was called. It proves the test setup, not the product.
- **Buffered-stream test:** a streaming test that only inspects the final list,
  so a regression that destroys first-token latency still passes.
- **Sleep-based waiting:** `time.sleep` or a fixed browser timeout hides a race
  and slows the suite; use an injected clock, an event, or a web-first
  assertion.
- **Snapshot churn:** a large golden updated without reading the diff. If the
  expected value changes, say why in the PR.
- **Order dependence:** one test leaves rows, files, or module state behind and
  the next test only passes in file order.
- **Coverage theatre:** executing lines without asserting outcomes.
- **Eval in disguise:** a "unit test" that calls a real model or judges
  teaching quality. Move it to `evals/`.
- **Weakened assertion:** the test changed in the same PR as the behaviour and
  the diff only relaxes the expectation. Justify or reject it.

The full list, with fixes, is in
[references/test-review-checklist.md](references/test-review-checklist.md).

## Sources and maintenance

Repo contracts are the primary authority: `AGENTS.md`, `testing/README.md`,
`docs/specs/evals/`, `docs/specs/voice-agent/spec.md` §13,
`docs/specs/observability/`, `docs/deployment/cicd.md`, and the tests
themselves. Five external sources are used for method vocabulary only, with
URLs and access dates in [README.md](README.md). Evidence date: **2026-11-14**.
Re-check the perishable rows (CI job names, Playwright commands, eval CLI
flags) before quoting them in a new document.
