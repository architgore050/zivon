---
name: review-implementation
description: "Implementation-quality lens for code review. Use for any line-level review of logic: correctness, edge cases, error handling, concurrency and async bugs, resource leaks, performance pitfalls, complexity, readability, naming, comments, type safety, duplication of existing helpers, and misuse of library APIs. Use whenever the user asks \"is this correct\", \"any bugs\", \"review my function/PR\", \"is this clean\", \"can this be simplified\", or hands over a diff for a general review, even if they don't say \"implementation\"."
---

# Implementation Review

This lens answers: **does the code do what it claims, on every path that can actually happen, in a way the next engineer can understand and safely change?** Correctness comes first, then robustness, then clarity.

Findings use the shared format and severity scale from `code-review`.

## 1. Know the intent, then trace it

State what the code is supposed to do in one sentence (from the PR, issue, or function name). Then **execute it in your head** on a concrete input, not just read it. Walk the happy path, then deliberately walk each boundary below. Prefer actually running the code or its tests when you can; a repro is the strongest evidence.

## 2. Correctness checklist

**Inputs and boundaries**
- Empty, null/None/undefined, zero, one, many, maximum; duplicate items; unsorted input where order was assumed.
- Off-by-one in loops, slices, pagination, ranges (inclusive vs exclusive), and index math.
- Numeric hazards: integer overflow/truncation, floating-point for money, division by zero, rounding mode, unit mismatches (ms vs s, bytes vs bits).
- Text hazards: Unicode normalization, byte vs character length, case folding, locale, line endings, trailing whitespace.
- Time hazards: timezones, DST, clock skew, naive vs aware datetimes, `now()` called twice, expiry comparisons using `<` vs `<=`.

**Control flow and state**
- Every branch handled (`switch` without default, enum values added but not handled, `if` without `else` where the else matters).
- Early returns that skip cleanup; flags that can end in contradictory combinations; mutation of arguments or shared defaults (e.g. mutable default arguments).
- Conditions inverted, `and`/`or` precedence, truthiness bugs (`0`, `""`, `[]` treated as missing), `==` vs `===`, identity vs equality.
- Idempotency: if this runs twice (retry, duplicate event, double click), is the result still correct?

**Error handling**
- No swallowed errors: empty `catch`, `except: pass`, ignored return codes / unchecked `err`. Failures should be handled, propagated, or logged with context, never silently converted to success.
- Catch the narrowest error you can meaningfully handle; don't catch-all then continue as if nothing happened.
- Error messages carry the context needed to debug (what was attempted, with which identifiers) without leaking secrets.
- Cleanup on every exit path: `finally`/`defer`/context managers/RAII for files, locks, transactions, sockets, temp files.
- Partial failure: in a multi-step operation, what state remains if step 3 of 5 fails? Is there rollback, compensation, or at least detection?
- Retries have a cap, backoff, jitter, and only wrap idempotent operations. Every network/IPC/DB call has a timeout.

**Concurrency and async**
- Shared mutable state accessed from multiple threads/tasks without synchronization; check-then-act races (TOCTOU), lost updates, read-modify-write without atomicity or transaction.
- Async pitfalls: missing `await`, fire-and-forget tasks with unobserved exceptions, blocking calls inside an event loop, unbounded task fan-out, cancellation not handled.
- Lock ordering and holding locks across I/O or callbacks; deadlock risk; locks never released on error.
- Transaction scope: does the transaction wrap exactly the operations that must be atomic? Reads that inform writes should be inside it or use proper isolation/locking.

**Resources and performance (flag only with a concrete reason)**
- Leaks: unclosed handles, listeners never removed, caches/maps that grow without bound, goroutines/threads that never exit.
- Data-size blowups: loading entire tables/files into memory, unbounded pagination, quadratic work on user-sized input, nested loops over collections, N+1 queries or per-item network calls in a loop, repeated work that belongs outside the loop.
- Don't micro-optimize. "Faster" claims need a hot path or a measurement; otherwise prefer the clearer code. But do flag algorithmic mistakes that will bite at realistic scale.

**API and library use**
- Does every function, method, flag, and package actually exist in the version in use? (Especially for AI-written code; check, don't assume.) Are deprecated/removed APIs avoided?
- Are return values and error semantics used as documented (e.g. functions that return `None`/`-1`/`false` on failure; iterators consumed twice; lazily evaluated generators)?
- Is there already a helper in the codebase or standard library doing this? Grep before accepting a new utility.

## 3. Clarity and maintainability

Judge from the viewpoint of a competent engineer reading this cold in six months.

- **Complexity**: can the main logic be understood in one pass? Deep nesting (3+ levels), long functions doing several jobs, flag parameters that switch behavior, and clever one-liners are smells. Suggest early returns, extraction with a good name, or a table/lookup instead of branching chains, only if it genuinely simplifies.
- **Naming**: names reveal intent and units (`timeout_ms`, `is_expired`), don't lie (`getUser` that creates one), and match the project's vocabulary. Vague names (`data`, `handle`, `process`, `util`) hide design problems.
- **Comments**: should explain *why* (constraints, tradeoffs, links to bugs/specs), not narrate *what*. Flag comments that contradict the code (worse than none), commented-out code, and TODOs without owner or issue.
- **Types and invariants**: avoid `any`/untyped escape hatches, unchecked casts, and stringly-typed values where an enum/type would prevent invalid states. Validate at boundaries; trust internal types after that.
- **Dead and duplicated code**: unused params/branches/imports, code that can never run, copy-pasted blocks that will diverge.
- **Magic values**: unexplained numbers/strings that should be named constants or config.
- **Consistency**: follows the surrounding file's idioms and the project's style guide; defer to formatter/linter output on mechanics and don't comment on what tooling enforces.
- **Logging**: useful level and context; not noisy in hot paths; no secrets or PII; not a substitute for returning errors.

## 4. Calibration

- A correctness bug on a realistic path is **major** or **blocker** depending on blast radius (data loss, wrong money, wrong permissions, crash on main flow = blocker).
- Readability issues are **minor** unless they hide a bug or will clearly cause one; if you can't say what could go wrong, it's a `nit`.
- When multiple approaches are fine, don't comment. When you suggest a rewrite, show it in a few lines so the author can judge the tradeoff.
- If you can't tell whether something is a bug, say what you'd need to know as a `question`, with the specific input that worries you.
- Review what the change *does*, including what it removes: deleted validation, removed checks, dropped error handling, and removed tests deserve extra scrutiny.
