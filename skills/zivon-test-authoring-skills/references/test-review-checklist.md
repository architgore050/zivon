# Test review checklist

A test earns its keep by failing when behaviour breaks and staying green when
behaviour does not change. This checklist judges that property, not the test
count and not the coverage percentage. It mirrors the `review-tests` lens in
`skills/code-review/`, but here the audience is the author before the PR.

## 1. The two questions

For every test in the diff, answer both:

1. **Would it fail if the behaviour broke?** Name the mutation that would make
   it red. If you cannot name one, the test is decorative.
2. **Would it stay green if the behaviour did not change?** Name the refactor
   that should not break it. If a rename or a private-method move breaks it,
   the test is coupled to structure.

If a test passes both, it is useful. If it fails either, fix the test before
review.

## 2. Mutation thinking

You do not need a mutation tool to do the important part. For the production
lines the test claims to protect, ask what would happen if you:

| Mutation | What it exposes |
|---|---|
| Flip a boolean condition | A test that only exercises the happy path |
| Change `<` to `<=` or `>` to `>=` | A boundary test that never touches the boundary |
| Return a constant | A test that checks the call, not the result |
| Delete a statement | A test that only checks "does not raise" |
| Swallow an exception | A test that never asserts the error type or message |
| Change a default value | A test that never checks the unconfigured path |
| Reorder two emitted messages | A test that only checks the final set, not the order |
| Replace a computed value with a plausible wrong one | A test that compares against the same computation |

Do it manually on a scratch copy, or with `git stash` / `git checkout` and
restore afterwards. Run the targeted test after each mutation. Record which
mutations survived; a survivor on core logic is a gap.

If the repo adopts a mutation tool (mutmut or Cosmic Ray for Python, Stryker
for JavaScript), scope it to the changed files and report surviving mutants as
evidence. A full-repo mutation run is too slow for a PR gate.

## 3. Regression protocol for a bug fix

1. Write the test against the **unfixed** code. It must fail for the reason the
   bug describes, not for an import error or a missing fixture.
2. Apply the fix. The same test must pass.
3. Run the rest of the suite. A fix that breaks a neighbour is not done.
4. Put the base commit or the red output in the PR evidence. "I added a test"
   is not proof that the test would have caught the bug.

If the test passes on the unfixed code, it is not a regression test. Either the
bug is elsewhere or the test observes the wrong thing.

## 4. Rubric (0–3 per dimension)

Use this for a self-review or a review finding. One sentence of evidence per
score; do not average away a zero.

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Behaviour coverage** | Core behaviour untested | Happy path only | Main plus some edge/error paths | Boundaries, errors, and regressions covered |
| **Fault detection** | Passes with broken code | Catches blatant breaks | Catches most mutations | Named mutations/known bugs reliably caught |
| **Refactor resilience** | Breaks on any internal change | Coupled to private structure in places | Mostly observable behaviour | Pure behaviour; internals free to change |
| **Determinism and speed** | Flaky or order-dependent | Occasional timing/sleep reliance | Stable, reasonably fast | Hermetic, parallel-safe, fast |
| **Clarity** | Unreadable, mystery setup | Intent needs digging | Clear names and AAA | Failure message alone identifies the broken contract |

The single change that would raise the lowest score is usually the right next
action.

## 5. Anti-patterns and fixes

| Anti-pattern | Why it is a problem | Fix |
|---|---|---|
| **Tautological mock** | The test asserts the mock returned what the test told it to | Assert the product outcome; use a fake that implements the real interface |
| **Assertion on the mock only** | Proves the test setup, not behaviour | Assert the returned value, persisted row, emitted frame, or rendered DOM |
| **`assert True` / "does not throw"** | Executes code, verifies nothing | Assert the observable result and its type |
| **Snapshot churn** | A large golden is updated without reading the diff | Assert invariants; review every snapshot diff; explain a baseline change |
| **Sleep-based wait** | Hides a race and slows the suite | Inject a clock, drive the event, or use a web-first assertion |
| **Order dependence** | Passes only in file order; fails in isolation | Fresh state per test; temp dirs; no shared global/DB rows |
| **Logic in tests** | The test needs its own tests | Use literal expected values; one branch per test |
| **Private-method assertion** | Breaks on refactor, catches no user-visible bug | Assert the public seam |
| **Over-broad `except`** | Swallows assertion errors and failures | Let failures propagate; catch only the expected type |
| **Coverage chasing** | Executes lines without asserting outcomes | Branch coverage on changed lines, with assertions |
| **Giant test** | Many behaviours, opaque failure | Split by behaviour; one reason to fail |
| **Testing the framework** | Asserts that Python's `dict` works | Test your code, not the standard library or the vendor |
| **Fixture generated by the code under test** | The code is compared with itself | Hand-write or capture the fixture independently |
| **Editing a seeded defect / golden to pass** | Destroys the calibration or regression baseline | Fix the code or record a deliberate baseline change |
| **Silent skip** | A missing dependency looks like coverage | `skipUnless`/`skipTest` with a reason; report skipped in the PR |
| **Weakened assertion in the same PR** | Hides a regression the change introduced | Compare the test diff to the source diff; justify or reject |
| **Time-dependent assertion** | Fails on a slow runner or at midnight | Inject a clock or assert a range/budget, not a wall-clock instant |
| **Locale/timezone-dependent assertion** | Passes in one environment only | Pin locale/timezone or assert a stable formatted shape |

## 6. Determinism checklist

- [ ] No `time.sleep`, `page.wait_for_timeout`, or polling without a timeout.
- [ ] No real network, API key, vendor socket, or model call.
- [ ] No dependency on the current date, timezone, locale, or hostname.
- [ ] Randomness is seeded, or the random source is injected.
- [ ] Temp files use a unique temp dir; cleanup runs even on failure.
- [ ] Database rows are in-memory or in a temp DB; no shared Postgres state.
- [ ] Tests pass alone, in reverse order, and repeated (where the runner allows).
- [ ] Browser contexts/pages close; servers shut down; subprocesses terminate.
- [ ] Environment variables are restored (`mock.patch.dict` with cleanup).
- [ ] No test depends on another test's side effects.

## 7. Naming and structure

- Name: `test_<scenario>_<expected>` —
  `test_char_cap_truncates_with_closing_line`, not `test_tts_2`.
- Arrange–act–assert visible; a reader should see the setup, the one action,
  and the observable.
- One behaviour per test. If the name needs "and", split it.
- Assertion message: name the contract and the actual value, e.g.
  `"first audio frame must arrive before segment_end"`.
- Avoid magic values in the body; name the fixture or constant.
- Docstring only when the contract or the fixture provenance is non-obvious;
  do not narrate the code.

## 8. Coverage: use it correctly

Coverage tells you what is **definitely untested**. It never tells you what is
well tested.

- Look at **branch coverage on the changed lines**, not the global percentage.
- An uncovered changed branch is a finding. A high percentage is not praise.
- Do not add a coverage threshold as a goal; it rewards execution without
  assertions.
- A risky path (money, auth, data integrity, concurrency, parsing, vendor
  failure) with no test is a major gap even if the global number is high.

## 9. Flaky-test triage

If a test is flaky:

1. Reproduce with repetition and random order; run it alone.
2. Look for time, randomness, ordering, shared state, async races, external
   services, and browser timing.
3. Fix the cause. Retries and sleeps hide it.
4. If it must be quarantined, give it an owner and a ticket; never leave a
   silent `skip`.

A flaky test erodes trust in the whole suite; a suite people ignore is worse
than a smaller suite they believe.

## 10. When not to add a test

- Trivial glue that only forwards a value and has no branch.
- Framework or standard-library behaviour.
- Generated code already covered by a golden/eval contract.
- Pure visual styling with no behaviour (and no pixel tests by policy).
- Something lint, types, or a schema validator already enforces.

Spend the effort on the risky, non-obvious behaviour instead.

## 11. Pre-PR checklist

```text
[ ] The behaviour and the failure are named in one sentence.
[ ] The test is at the cheapest layer that can see the break.
[ ] The double is at a seam; the thing under test is real.
[ ] The fixture is minimal, tracked, and has provenance if non-obvious.
[ ] The test fails under a named mutation; the bug-fix test fails on base.
[ ] No sleep, network, key, wall clock, order dependence, or shared state.
[ ] The name and assertion message identify the contract.
[ ] The touched suite passes alone and in the folder.
[ ] ruff check . and ruff format --check . are clean.
[ ] mypy is clean on the touched package.
[ ] testing/README.md or the owning spec is updated if the contract changed.
[ ] The PR evidence includes the command and the result.
```
