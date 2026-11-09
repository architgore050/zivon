---
name: review-tests
description: "Test-quality lens for code review. Use to judge how good a test suite or a change's tests actually are: whether they would catch a regression, whether coverage is meaningful, whether they are flaky, over-mocked, brittle, or tautological, and whether bug fixes have regression tests. Use when reviewing a PR with or without tests, when the user asks \"are these tests good\", \"is this well tested\", \"what's missing\", \"why are tests flaky\", \"grade my tests\", or when AI-written code ships with suspiciously easy-passing tests. Produces a scored rubric plus concrete gaps."
---

# Test Quality Review

A test is valuable to the degree that it **fails when behavior breaks** and **stays green when behavior doesn't change**. Coverage numbers and test counts measure neither. This lens judges tests by those two properties.

Findings use the shared format and severity scale from `code-review`.

## 1. Map behavior to tests

List the behaviors the change introduces or alters: new branches, bug fixes, error paths, boundaries, permission checks, state transitions. For each, find the test that would fail if that behavior were wrong. A behavior with no such test is a gap. Missing tests for risky logic (money, auth, data integrity, concurrency, parsing) are **major**; for trivial glue they're **minor**.

- **Bug fixes must ship with a regression test that fails without the fix.** Verify this when you can: run the new test against the base commit (or stash the fix) and confirm red, then green.
- **Negative and boundary paths** are where bugs live: invalid input, empty/max values, permission denied, timeouts, dependency failures, concurrent calls. A suite of only happy paths is weak.
- Security-relevant behavior (authz denied, input rejected) needs tests too: "user A cannot read user B's record".

## 2. Mutation thinking: would it actually notice?

For the key lines of the change, ask: *if I flipped this condition, changed `<` to `<=`, returned a constant, deleted this statement, or swallowed this exception, would any test fail?* If not, the tests are decorative for that line.

- If the repo has a mutation tool (mutmut, Cosmic Ray, Stryker, PIT, cargo-mutants, Infection), run it scoped to changed files and report surviving mutants as evidence.
- Otherwise do **manual mutations** on a scratch copy or with `git stash`/`git checkout` afterward: break two or three critical lines and run the tests. Always restore the code. Report which mutations survived.
- Executing code only (high line coverage) while asserting nothing about the result is the most common way tests lie.

## 3. Rubric: score each dimension 0–3

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Behavior coverage** | Core behavior untested | Happy path only | Main + some edge/error paths | Boundaries, errors, and regressions covered |
| **Fault detection** | Passes with broken code | Catches blatant breaks | Catches most mutations | Mutations/known bugs reliably caught |
| **Refactor resilience** | Breaks on any internal change | Coupled to private structure in places | Mostly asserts observable behavior | Pure behavior; internals free to change |
| **Determinism & speed** | Flaky or order-dependent | Occasional timing/sleep reliance | Stable, reasonably fast | Hermetic, parallel-safe, fast |
| **Clarity** | Unreadable, mystery setup | Intent needs digging | Clear names and AAA structure | Failure message alone tells you what broke |

Report the scores with one sentence of evidence each and the single change that would raise the lowest score the most. Don't pad: if there's no change in tests and none is needed, say so.

## 4. What good looks like

- **Assert outcomes, not implementation.** Check returned values, persisted state, emitted events, and externally visible effects. Assert interactions with a mock only when the interaction *is* the behavior (e.g. "an email is sent").
- **Right level of test.** Pure logic → fast unit tests. Anything crossing a boundary (DB queries, HTTP, serialization, framework wiring) → at least one integration test against the real thing or a faithful fake. Few end-to-end tests for critical journeys. Mocked databases that return what the code expects prove nothing about the SQL.
- **Mock what you own at the seam; don't mock what you're testing.** Prefer fakes and real in-memory implementations over deep mock chains. If a test needs five mocks, the design may need work (hand off to `review-architecture`).
- **One reason to fail**: each test focuses on one behavior; name states the scenario and expectation (`rejects_expired_token`, not `test_token_2`).
- **Arrange–Act–Assert** visible; minimal setup; builders/fixtures that make the *relevant* data obvious and the rest default.
- **Deterministic by construction**: injected clocks, seeded randomness, no real network, no `sleep` waits (poll with timeout or use fakes), isolated state, no dependence on test order, unique temp resources.
- **Useful failures**: assertion messages/diffs that identify the broken thing.
- **Property-based or fuzz tests** for parsers, serializers, encoders, and algorithms with invariants (round-trip, idempotence, ordering).
- **Contract tests** where services or clients depend on a shared schema.

## 5. Anti-patterns to flag

| Pattern | Why it's a problem |
|---|---|
| Test changed to match new (possibly wrong) output; weakened or removed assertions; test deleted/`skip`ped/`xfail`ed in the same PR as the code change | Hides regressions; always compare test diff to source diff and ask why |
| Asserting on the mock (`expect(mock).toHaveBeenCalled()` as the only check) | Tests the test setup, not behavior |
| Tautologies: expected value computed by the same logic as the code under test; `assert x == x` | Can never fail |
| No assertions / `assert True` / "does not throw" as sole check | Executes code, verifies nothing |
| Snapshot tests of large blobs rubber-stamped on update | Failures get approved without reading |
| Logic (loops, conditionals) in tests | Tests need their own tests |
| Asserting private methods or internal call order | Breaks on refactor, doesn't catch bugs |
| `sleep(…)`, real clock/network, shared global/DB state, order dependence | Flakiness; a flaky test erodes trust in all tests |
| Giant tests covering many behaviors; copy-paste test bodies | Opaque failures; hard to maintain |
| Over-broad `except`/`catch` inside tests, or `try/except` that hides assertion errors | Swallows failures |
| Coverage-chasing tests that exercise lines without checking results | Inflates metrics, adds maintenance |
| Tests only exist for code that's easy to test; hard, risky parts untested | Coverage inversely correlated with risk |

## 6. Coverage: use it correctly

Coverage tells you what is **definitely untested**, never what is well tested. Look at **branch coverage on the changed lines**, not the global percentage. Uncovered changed branches are findings; high percentages are not praise on their own. Do not recommend coverage thresholds as a goal.

## 7. Flaky or slow suites

If asked to diagnose flakiness: run the test repeatedly and in random order/parallel to reproduce; look for time, randomness, ordering, shared state, async races, and external services. Fix the cause; retries and `sleep` only hide it. Quarantine with an owner and ticket, never silently.

## Severity guidance

| Situation | Typical level |
|---|---|
| Bug fix without a regression test; tests deleted or weakened to pass; critical path (money/auth/data) untested | major (blocker if the change is itself risky and tests were removed to hide a failure) |
| Surviving mutants on core logic; over-mocked integration seam; flaky test introduced | major–minor |
| Poor names, minor duplication, missing edge case on low-risk code | minor/nit |
