# Zivon test authoring skills (bundle)

How to write the right test for Zivon: the smallest deterministic check that
would fail for the right reason, at the cheapest layer that can observe the
break — and the discipline to know when the check is an eval instead.

This bundle is for **authors**, not reviewers. `skills/code-review/review-tests/`
judges a suite; this bundle tells you how to build one that survives that
judgement.

## Read order

1. This README for layout, scope, and provenance (2 minutes).
2. [`SKILL.md`](SKILL.md) — the method, the test/eval fork, the workflow, the
   quality gate. **Always.**
3. Open a `references/*` file only when the reference map says the current task
   needs it.
4. Copy a `templates/*` file when the artifact (plan, case, fixture manifest,
   browser checklist) is the hard part.
5. Run the validator and the bundle's own test before calling a change done.

## Layout

```
zivon-test-authoring-skills/
├── README.md
├── SKILL.md                          entry point: test/eval fork, workflow, gate
├── references/
│   ├── test-layers.md                unit / contract / integration / browser / a11y / perf
│   ├── fixtures-and-goldens.md       fixtures, goldens, seeded defects, cleanup
│   ├── mocking-vendor-seams.md       Prisma, Gemini, Timbre, llm_manager HTTP, DB, clocks
│   ├── browser-and-a11y-tests.md     Playwright, state coverage, axe, keyboard, perf
│   ├── evals-vs-tests.md             testing/ vs evals/, cards, checkers, judges, persistence
│   ├── ci-and-path-guards.md         discovery, jobs, path guards, lint/types, key-free
│   ├── test-review-checklist.md      mutation thinking, anti-patterns, flake triage
│   └── worked-example-voice-contract.md  full TTS streaming-contract walkthrough
└── templates/
    ├── test-plan.md                  multi-layer coverage plan
    ├── test-case.md                  one behaviour, AAA skeleton, failure proof
    ├── fixture-manifest.md           provenance, PII, refresh, cleanup
    └── browser-test-checklist.md     states, waits, a11y, perf, evidence
```

## Scope

**In scope:** deterministic unit, contract, integration, browser, accessibility,
performance, and static-shell tests; fixtures and goldens; vendor mocks at the
documented seams; key-free CI; test discovery and path guards; the
`testing/` versus `evals/` boundary; and the review checklist an author runs
before a PR.

**Out of scope:** judging a whole PR (`skills/code-review/`), designing a
feature or screen (`skills/zivon-product-design-skills/`), choosing visual style
(`docs/frontend/design-doctrine.md`), writing agent prompts
(`skills/prompting-and-agent-design/`), and discovering or installing
third-party skills (`skills/skill-creation/`).

## Quick start

```bash
# 1. validate this bundle (strict: frontmatter, links, secrets, placeholders)
python3 scripts/check_skills.py --strict --bundle skills/zivon-test-authoring-skills

# 2. the bundle's own contract test
python -m unittest discover -s testing/skills -t .

# 3. the layer you are working in
python -m unittest discover -s testing/content_factory/unit -t .
python -m unittest discover -s testing/voice -t .
python -m unittest discover -s testing/frontend -t .   # needs Chromium
python -m evals run --suite smoke --mock

# 4. the merge gate locally
ruff check . && ruff format --check .
mypy --ignore-missing-imports factory docker pipeline.py testing voice \
  logging_manager dashboard evals backend db guard
```

A browser test needs Chromium; a missing Playwright install fails loudly with
the install command, and the integration perf checks skip with a reason when
Chromium is unavailable. A skip is never a pass. The full command list and the
CI job map are in
[`references/ci-and-path-guards.md`](references/ci-and-path-guards.md).

## The method in one paragraph

Name the behaviour and the user-visible failure. Find the seam it crosses. Pick
the cheapest layer that can see the break. Replace the collaborator with a
double that implements the real interface, not the thing under test. Make the
fixture deterministic and hermetic. Write one behaviour per test with an
observable assertion. Prove it can fail by mutating the production line (or, for
a bug fix, by running it on the base commit). Run the suite, lint, and types.
If the question is a judgement about model output or teaching quality, stop:
that is an eval card, not a unit test. The full version is
[`SKILL.md`](SKILL.md).

## The test/eval boundary, in one table

| The check is about | Home | First command |
|---|---|---|
| Code mechanics with a deterministic expected value | `testing/` | `python -m unittest discover -s testing/<area> -t .` |
| A wire shape, protocol, or adapter contract | `testing/` (contract layer) | the owning suite |
| Teaching quality, prompt quality, reviewer calibration, generated-page quality | `evals/` | `python -m evals run --suite smoke --mock` |
| A hardware budget on a generated page | `evals/` (`EV-PERF-001`) | `python -m evals run --card EV-PERF-001` |
| A model-free invariant used by an eval | `evals/checkers/`, tested in `testing/evals/` | `python -m unittest discover -s testing/evals -t .` |

Read [`references/evals-vs-tests.md`](references/evals-vs-tests.md) before adding
a card, checker, golden, or judge.

## Provenance and evidence

**Primary authority is this repo.** The bundle is synthesized from:

- `AGENTS.md`, `testing/README.md`, `testing/content_factory/README.md`,
  `testing/observability/README.md`.
- `docs/specs/evals/{README,spec,card-template,golden-sets}.md` and
  `docs/backend/adr/0027`, `0028`.
- `docs/specs/voice-agent/{spec,ws-contract,latency-budget}.md` (especially
  spec §13, the test table).
- `docs/specs/frontend/{state-matrix,perf-budget-tests}.md`.
- `docs/specs/observability/` (logging contract, redaction, instrumentation map).
- `docs/deployment/cicd.md`, `.github/workflows/ci.yml`.
- The suites themselves: `testing/**`, `evals/checkers/**`,
  `evals/goldens/**`.

**Five external sources** were consulted for method vocabulary only, all
accessed **2026-11-14**. No third-party text is copied.

| # | Source | URL | Used for |
|---|---|---|---|
| 1 | Martin Fowler, "Test Double" (2006), summarizing Gerard Meszaros' xUnit Patterns vocabulary | https://martinfowler.com/bliki/TestDouble.html | Dummy / fake / stub / spy / mock distinctions; prefer fakes at seams |
| 2 | Microsoft Playwright, "Best Practices" | https://playwright.dev/docs/best-practices | User-visible locators, test isolation, web-first assertions, traces on CI |
| 3 | W3C, "Web Content Accessibility Guidelines (WCAG) 2.2", Recommendation 12 December 2024; Deque Labs, "axe-core" README | https://www.w3.org/TR/WCAG22/ and https://github.com/dequelabs/axe-core | Accessibility baseline; automated rules cover a subset, not a compliance certificate |
| 4 | Stryker Mutator documentation | https://stryker-mutator.io/docs/ | Mutation-testing concept: change code, see whether a test fails |
| 5 | Google, *Software Engineering at Google*, Chapter 11 "Testing Overview" | https://abseil.io/resources/swe-book/html/ch11.html | Small / medium / large test sizes; speed and determinism come from constraints |

The canonical xUnit Patterns site was unreachable from the authoring
environment on the access date; the test-double vocabulary was taken from
Fowler's summary, which credits Meszaros. Treat that as a secondary citation,
not a substitute for the book.

**Evidence date:** 2026-11-14. Perishable facts — CI job names, Playwright and
ruff versions, eval CLI flags, profile budgets, and the instrumentation-map gap
for the `EVT-EVAL-*` events (checked on that date) — are dated in the text.
Re-check them before quoting this bundle in a new document.

## Maintenance

- **Owner:** zivon. **Version:** 1.0. **Review cadence:** quarterly, plus a
  mandatory re-read when `.github/workflows/ci.yml`, `evals/cli.py`,
  `testing/README.md`, or `docs/specs/evals/` changes.
- **Staleness triggers:** a new vendor seam; a Playwright or ruff major; a WCAG
  update; a change to the eval card schema or result store; a new test layer.
- **Extension:** add a reference or template, mention it from `SKILL.md` with a
  load condition, and add it to the required-files test in
  `testing/skills/test_test_authoring_bundle.py`.
- **Validation:** `python3 scripts/check_skills.py --strict --bundle
  skills/zivon-test-authoring-skills` and
  `python -m unittest discover -s testing/skills -t .`.

## License

Original text in this bundle is MIT, matching the other Zivon skill bundles.
Third-party sources are cited, not vendored; their licenses remain their own.
