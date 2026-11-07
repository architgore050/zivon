---
name: code-review
description: Entry point for reviewing any code change. Use whenever the user asks to review a PR, diff, branch, commit, patch, or set of files; says "look over my changes", "is this ready to merge", "audit this", "sanity check this", or "self-review before I open a PR"; or wants AI-written code checked. Triages the change, routes it to the specialist lenses (review-security, review-architecture, review-implementation, review-tests, review-docs-sync, review-production-readiness), and merges the results into one prioritized report with a clear verdict. Use this skill first even if the user only names one concern, because it decides which lenses matter.
---

# Code Review (orchestrator)

This skill decides *what* to review, *in what order*, and *how to report*. The specialist lenses hold the depth; this one keeps the review proportionate, evidence-based, and useful rather than noisy.

## The standard

A change should be approved when it **improves the overall health of the codebase**, even if it isn't how you'd have written it. Perfect code doesn't exist; the goal is a steady upward trend. That gives four working rules:

- **Technical facts and data beat opinions.** If you can't state a concrete consequence (a bug, a risk, a maintenance cost, a violated documented rule), it's a preference, so label it `nit` or drop it.
- **The project's style guide and existing conventions are the authority** on style. Consistency with the surrounding code beats personal taste, unless the existing pattern is actively harmful.
- **Where several designs are valid, the author's choice stands.** Only push back on a design when it has a demonstrable cost.
- **Don't block on perfection, but don't wave through real problems.** A reviewer who approves a known correctness or security defect has failed; so has one who blocks on naming.

## Step 1: Understand the change before judging it

1. Get the diff (`git diff <base>...HEAD`, the PR, or the files the user pointed at) plus the PR description, commit messages, and any linked issue. If intent is unclear, state your assumption in one line and proceed; ask only if the answer would change the verdict.
2. Read **whole files and the callers**, not just hunks. Most serious defects live in the interaction between changed and unchanged code. Use grep/LSP to find usages of anything whose signature or behavior changed.
3. Check what CI already covers (tests, lint, types, SAST). Don't spend review attention duplicating machines; spend it on what machines can't judge: design, intent, missing tests, security logic, docs truth.
4. Note the size. If a diff mixes unrelated concerns or is much bigger than a reviewer can hold in their head (roughly 400+ changed lines of logic), say so and suggest a split. Review quality collapses on oversized changes.

## Step 2: Triage to lenses

Read the matching lens's `SKILL.md` before applying it. Not every change needs every lens; a typo fix needs a glance, not six passes.

| Signal in the change | Lens |
|---|---|
| Always | `review-implementation`, `review-tests` |
| Auth, permissions, user input, SQL/shell/HTML/path/URL handling, crypto, secrets, dependencies, CI config, LLM/tool/agent code | `review-security` |
| New module/package/service, new dependency or framework, public API/schema/contract change, moved files, new cross-cutting pattern | `review-architecture` |
| Changed commands, config/env vars, public API, setup steps, directory layout, conventions, runtime versions | `review-docs-sync` |
| Migrations, queries, network calls, background jobs, flags/config, deploy or infra changes, hot paths | `review-production-readiness` |

Scale depth to risk. Auth, payments, data migrations, concurrency, and anything irreversible get a deep pass; docs-only or test-only changes get a light one.

## Step 3: Review in priority order

Design problems are expensive to fix late and make line-level comments moot, so go top-down:

1. **Design / architecture**: is this the right change in the right place?
2. **Correctness & security**: does it do what it should, safely, on the unhappy paths?
3. **Tests**: would they catch a regression?
4. **Operability**: can it be deployed, observed, and rolled back?
5. **Docs**: is what the repo tells people still true?
6. **Readability & style**: naming, comments, polish.

If you find a fundamental design problem in pass 1, report it immediately and say you stopped there; reviewing line details of code that should be restructured wastes everyone's time.

## Step 4: Verify before you report

Confidence is earned by evidence. Prefer, in order: running it (tests, repro, typecheck), tracing it (follow the data/call path and cite lines), grepping for it (callers, duplicates, config). Label each finding:

- **confirmed**: you ran or traced it
- **likely**: strong reading of the code, not executed
- **suspected**: a hunch; put it under *Questions*, phrased as a question, never as an accusation

A false positive costs trust; after a few, the author stops reading. Silence beats a guess.

## Reviewing AI-written code

Agent-authored diffs fail differently from human ones. Look specifically for:

- **Hallucinated APIs or packages**: functions, flags, or dependencies that don't exist (a real supply-chain risk). Verify imports and new package names actually resolve and are the intended packages.
- **Plausible but wrong**: code that reads fluently but mishandles an edge. Trace it; don't skim.
- **Tests bent to pass**: deleted, skipped, or weakened assertions; mocks asserting on themselves; snapshot churn. Compare test diffs against the source diff.
- **Over-building**: speculative abstractions, config knobs, and layers nobody asked for. Ask what requirement each one serves.
- **Reinvention**: new helpers duplicating ones that already exist. Grep before accepting.
- **Scope creep**: unrelated refactors or reformatting hidden in the diff.
- **Swallowed errors and silent fallbacks** that make failures look like success.
- **Narrating comments** that restate the code, and stale comments that now lie.

## Noise discipline

- Skip anything a formatter, linter, or typechecker in this repo already enforces.
- Group repeats: one finding saying "same issue in 6 places (list)" beats six comments.
- Cap nits (about five). If there are more, say "several naming nits, pattern: X" once.
- Lead with the findings that matter. A reader should know the verdict and the top issue within ten seconds.
- Mention what's done well when something is; it calibrates the reader and tells the author what to repeat.

## Severity

| Level | Meaning | Blocks merge? |
|---|---|---|
| **blocker** | Exploitable vulnerability, data loss/corruption, definite correctness bug on a main path, breaking change with no migration path, secrets committed | Yes |
| **major** | Likely bug on a realistic edge, missing tests for risky behavior, design choice that will be costly to undo, stale docs that will mislead | Usually; justify if not |
| **minor** | Real but low-impact improvement to maintainability, clarity, or robustness | No |
| **nit** | Taste or polish; prefix with `nit:` | No |
| **question** | You lack context or have a suspicion; asks rather than asserts | No |
| **praise** | Something worth repeating | No |

## Finding format (all lenses use this)

```
[severity][lens][confidence] path/to/file.ext:LINE: Issue in one sentence.
Why it matters: the concrete scenario or consequence.
Fix: the specific change, with a short snippet if it helps.
```

## Report template

```
## Review: <branch / PR title>
**Verdict:** Approve | Approve with comments | Request changes
**Summary:** 2–3 sentences: what the change does, its overall health, the single most important issue.
**Lenses applied:** implementation, tests, security …  (skipped: <lens>: <reason>)

### Blockers
### Major
### Minor and nits
### Questions
### What's good
### Not reviewed / assumptions
```

Verdict rule: any **blocker** → *Request changes*. Majors only → *Request changes* unless the author can plausibly address them as follow-ups you've named explicitly. Otherwise → *Approve* (with comments if there are minors worth reading). Always state what you did **not** review (generated code, vendored files, areas you couldn't verify) so approval isn't read as broader than it is.

If the user wants fixes applied rather than a report, make the changes for blockers and majors, keep them minimal, re-run the relevant tests, and list what you changed.
