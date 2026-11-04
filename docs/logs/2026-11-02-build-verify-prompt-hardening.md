# Session log — 2026-11-02 — build-and-verify prompt hardening (slice 3 review)

Judged the prompting of the build-and-verify slice (05-check, 06-interactive,
09-fixloop, 10-review; 07/08/11 are deterministic). 05 and 10 had been through
the previous prompt round; 06 and 09 had never been reviewed.

## The structural finding

The final page's physics was never fact-checked end-to-end: 05 fact-reviews
the DRAFT; 06 writes the actual physics (the draw loop) with no ground truth
at all; 09 rewrites page.js for fps with no preservation duty; 10 reviews
structure only. A simulation drawing physically wrong behaviour could pass
lint → perf → review → ship. Closed from three directions:

- **Prevent (06)**: the sim builder now receives "FACTS THE SIMULATION MUST
  OBEY" - the block's cited claims (exact statements + locators) plus every
  ground-truth equation - with a hard PHYSICS CONTRACT (control→on-screen
  relationships must match the equations and DEFAULT BEHAVIOUR) and a
  never-invent-physics system rule. Also a small-phone-canvas legibility line.
- **Guard (09)**: the page must still TEACH after a perf fix - sims keep
  their learning_goal / default_behaviour / controls; if the only way to pass
  is removing required behaviour, say so in analysis instead of doing it. The
  model also now sees PAGE SPECS, PREVIOUS ATTEMPTS (analysis + outcome per
  round, so failed fixes aren't repeated), the budgets, and the measurement
  context (throttled, core-pinned Chromium ≈ low-end Android).
- **Detect (10)**: CITED FACTS (all claims + equations) join the review
  context; checklist item 1 now reviews the simulation's DRAWN behaviour
  against spec + facts (physically wrong = fatal); the verdict rule the code
  enforces is stated (fail only with ≥1 fatal).

## Also done

- **05-check**: comprehension probe (every check's expected_understanding
  must be taught before it asks - untaught ask = major) and an uncertainty
  outlet expressible in CHECK_REPORT's schema (minor + "unverified:" prefix).
- **06 lint inside the retry loop**: hard-lint violations are fed back to
  the model via extra_validator (the machinery proven at 04-draft) instead of
  a post-call LintError killing the run; post-call lint stays as a backstop.
- stages.py threads 02-synth output into 06 and 10, and 04-draft blocks into
  09 (with resume-path artifact fallbacks).
- Tests: new test_interactive.py (cited claims in / uncited out, equations in,
  contract lines, lint-feedback wiring), new test_review.py (facts in the
  review context, behaviour-fidelity + verdict-rule lines, clean page
  passes), two new fixloop tests (specs+guard in the prompt, second round
  sees previous attempts), new 05 prompt test. Suite: 167 tests.
- Docs: architecture.md stage table + failure-semantics + traceability rules
  updated in the same PR.

## Not done / open

- All prompt effects are unmeasured until the first real-server runs: watch
  06 lint-retry rates in `runs/<run_id>/06-interactive/attempts/`, fix-loop
  round counts and 10-review fatal hits on physics.
- 10-review's behaviour-fidelity check is itself model judgement over code
  text; if Evon proves weak at reading draw loops, a stronger mechanical
  check (e.g. sampling sim state at set control values and asserting
  relationships) is a P2 candidate.

## Next

- Push done; open the PR → CI. First real-server run (Gate B) afterwards;
  measure the retry/fix-loop rates this session's changes are meant to move.
