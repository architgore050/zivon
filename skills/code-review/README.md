# Code Review Skills

A small suite of eight skills that together review a codebase against the standards that actually matter. One entry point routes to seven specialist lenses; every lens reports findings in the same format, so results merge into one prioritized review.

| Skill | What it judges | Bundled references |
|---|---|---|
| `code-review` | **Entry point.** Triage, which lenses to run, evidence rules, severity scale, report template, AI-code failure modes | none |
| `review-security` | Attacker-controlled data reaching powerful sinks; OWASP Top 10:2025; secrets, supply chain, CI/CD, LLM/agent safety | `owasp-2025-checklist.md`, `agentic-and-llm.md` |
| `review-architecture` | Boundaries, dependency direction, abstraction cost, contract stability, reversibility, ADRs | none |
| `review-implementation` | Correctness, edge cases, error handling, concurrency, resources, readability, API misuse | none |
| `review-tests` | Would the tests catch a regression? Scored rubric, mutation thinking, flakiness, anti-patterns | none |
| `review-docs-sync` | README, AGENTS.md/CLAUDE.md, changelog, API docs, comments staying true to the code | `agents-md-rubric.md` |
| `review-production-readiness` | Observability, failure modes, migrations, rollout/rollback, performance, cost | none |
| `review-content-quality` | Generated learning content and content-pipeline PRs: lesson pages/blocks, questions, test series, translations, narration, catalogue/publish output | `content-quality-checklist.md`, `review-procedure.md`, `anti-patterns.md` |

## How they fit together

```
                         code-review
           (understand → triage → order → verify → report)
                              │
   ┌──────────┬───────────────┼───────────────┬──────────────┬───────────────┬─────────────────┐
 architecture  implementation  security        tests          docs-sync   production-readiness  content-quality
 (design)      (correctness)   (OWASP, agents) (would it      (is it       (can we ship,         (does it teach,
                                               catch bugs?)    still true?) observe, undo?)      and is it true?)
```

Review order is deliberate (design/content → correctness/security → tests → operability → docs → style), following the principle that design and content problems are the costliest to fix late and make line comments moot.

## Install

- **Claude Code**: copy the eight folders into `~/.claude/skills/` (personal) or `<repo>/.claude/skills/` (shared with the team).
- **Claude.ai / Cowork**: zip each skill folder (or use the provided `code-review-skills.zip`) and upload under Settings → Capabilities → Skills.
- Keep all eight together: `code-review` refers to the others by name.

Then just ask: *"review this PR"*, *"is this ready to merge?"*, *"are these tests any good?"*, *"does AGENTS.md need updating for this change?"*, *"audit this for security"*, *"is this lesson content correct?"*, *"review this question paper."*

## Design principles baked in

1. **Evidence over opinion.** Every finding carries a confidence label (confirmed / likely / suspected); hunches become questions, not accusations.
2. **Approve what improves code health.** Don't block on taste; don't wave through real defects.
3. **Spend attention where machines can't.** Skip what linters, types, and CI already enforce.
4. **Trace, don't pattern-match.** Security follows data from source to sink; tests are judged by whether mutations would be caught; docs are checked by running their commands.
5. **Calibrated severity** with one scale across all lenses, so blockers are never lost among nits.
6. **Built for AI-written code too**: hallucinated packages, bent tests, over-building, reinvention.

## Customizing

- Add your stack's specifics as new files in a lens's `references/` and mention them from its `SKILL.md` with a "read when…" hint (e.g. `references/django.md`, `references/react.md`).
- Encode team policy in the lens that owns it (e.g. your ADR threshold in `review-architecture`, coverage expectations in `review-tests`).
- Delete lenses you don't need and remove them from the routing table in `code-review`.

## Sources and influences

Synthesized, not copied; credit where it's due:
- Google Engineering Practices, *The Standard of Code Review* and *What to look for in a code review* (CC-BY 3.0): the "improves code health" standard and design-first review order.
- OWASP Top 10:2025 (including the new Software Supply Chain Failures and Mishandling of Exceptional Conditions categories), OWASP API Security Top 10, and OWASP's LLM/agentic AI guidance.
- Community and published evaluations on writing effective AGENTS.md files: short, non-discoverable, kept current in the same PR.
- Mutation-testing and test-smell literature for the test-quality rubric.
- Michael Nygard's ADR format and the expand/contract migration pattern.
- WCAG 2.2, the NIST AI Risk Management Framework, CheckList behavioural testing, LLM-as-judge bias research, and instructional-design research for the content-quality rubric (dates and links in the lens's `SKILL.md`).
