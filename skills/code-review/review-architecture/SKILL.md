---
name: review-architecture
description: Architecture and design lens for code review. Use when a change adds a module, package, service, or dependency; changes a public API, schema, event, or data model; moves files or reshapes boundaries; introduces a new pattern, abstraction, framework, or datastore; or when the user asks "is this the right design", "does this fit our architecture", "do we need an ADR", "is this over-engineered", or "review the structure". Judges boundaries, coupling, dependency direction, reversibility, contract stability, and whether significant decisions are recorded.
---

# Architecture & Design Review

Design flaws are the most expensive defects: they're hard to see in a diff, compound with every later change, and are costly to reverse. Review design **first**, before line details. The question is not "is this how I'd do it?" but **"will this make the next ten changes easier or harder, and what does it cost to undo?"**

Findings use the shared format and severity scale from `code-review`.

## 1. Establish context before judging

- Read the PR description and any linked issue/ADR. What problem is being solved, and what constraints (deadline, compatibility, scale) apply?
- Learn the existing architecture from the repo: top-level layout, `docs/`, `ARCHITECTURE.md`, `docs/adr/`, `AGENTS.md`, module boundaries, and how neighbors solve the same problem. **The existing pattern is the default; a deviation needs a reason.**
- Find the real dependency graph with grep or tooling (imports, build graph), not just what directories suggest.

## 2. The questions

**Placement and boundaries**
- Does this code live where a maintainer would look for it? Does the module have a single, nameable responsibility?
- Does dependency direction follow the project's layering (e.g. domain doesn't import infrastructure; UI doesn't reach into persistence; leaf packages don't import apps)? New import edges that point "upward" or sideways across a boundary are the strongest early signal of decay.
- Any new cycles? Any new reach into another module's internals instead of its public interface?

**Abstraction and simplicity**
- Does each new abstraction, interface, config option, or layer serve a *current* requirement? Speculative generality ("we might need it later") is a cost paid now for a benefit that usually never arrives. Solve the problem in front of you; make the next step easy, not pre-built.
- Conversely, is there copy-paste of non-trivial logic that should be one thing? Duplication is cheaper than the *wrong* abstraction, but three copies of the same business rule is a bug waiting to diverge.
- Is the complexity proportional to the problem? Could a simpler design meet the stated requirements? If you can propose one, sketch it in two sentences.

**Cohesion, coupling, and state**
- Does one change force edits in many unrelated places (shotgun surgery)? Does one class/module know too much about others (feature envy, god object, leaky abstraction)?
- Who owns each piece of state? Is there a single source of truth, or are copies synchronized by hope? Shared mutable state and hidden global/singleton dependencies are majors when they cross module boundaries.
- Are temporal couplings (must call A before B) encoded in the API or only in comments?
- Is behavior configurable by stringly-typed flags where types or separate functions would make invalid states unrepresentable?

**Contracts and compatibility**
- Does the change alter a public API, CLI, wire format, event schema, file format, DB schema, or config surface? Who consumes it (other services, clients, plugins, users' scripts)?
- Is it backward compatible? If not: is there a versioning/deprecation/migration path, and is it documented? Breaking a contract silently is a **blocker**.
- Are errors, nullability, ordering, idempotency, and pagination part of the contract and consistent with neighboring APIs?
- Data model: are constraints (uniqueness, foreign keys, not-null) enforced by the database rather than only by code? Are new columns/tables shaped for how they'll be queried?

**Failure and scale at the design level**
- What happens when a dependency is slow, down, or returns garbage? Is the failure boundary where you'd want it (does one tenant/job/request take down others)?
- Synchronous where it should be async (or vice versa)? Operations that must be idempotent because they're retried or duplicated?
- Will it work at 10× current load/data without redesign? Only flag with a concrete reason, not generic "won't scale".

**Reversibility**
- Classify the decision: **two-way door** (easily undone: internal function, private module) or **one-way door** (public API, data format, datastore choice, vendor lock-in, deleted data). Scrutiny should scale with irreversibility. Cheap-to-reverse choices should be approved quickly even if imperfect.

**Dependencies and technology choices**
- New dependency or framework: why this one, what does it replace, what's the maintenance, license, security, and bundle/footprint cost, and is the gain worth the lock-in? Could the standard library or an existing dependency do it?
- New datastore/queue/service: operational burden is a design cost; has it been acknowledged?

## 3. Does this need an ADR?

Recommend an Architecture Decision Record when the change does any of: introduces a new framework, language, datastore, or service boundary; changes a public contract or the security/auth model; establishes a cross-cutting pattern others are expected to follow; or reverses an earlier decision. Check whether an ADR exists (`docs/adr`, `docs/decisions`, `decisions/`) and whether the code **still matches it**. A violated or silently superseded ADR is a **major** finding: either the code or the record must change.

A good ADR is short and answers: **Context** (forces and constraints), **Options considered** (at least two real ones, including "do nothing"), **Decision** (and why), **Consequences** (good, bad, and what becomes harder), **Status** (proposed/accepted/superseded). Judge ADRs on whether the rejected alternatives and the downsides are honestly stated; an ADR with only upsides is advocacy.

## 4. Writing architecture findings

- Cite concrete evidence: the import edge, the duplicated block, the consumer you found with grep, the second caller that will break.
- Describe the consequence in terms of future change or failure, not abstract purity: "Any new payment provider will require editing `OrderService` and four call sites" lands better than "violates OCP".
- Offer an alternative with its tradeoff, and say when the author's approach is acceptable *for now*. For design disagreements without clear technical grounds, defer to the author and note the concern as a `question`.
- Don't demand redesigns of working code outside the change's scope; log them as follow-ups.

## Severity guidance

| Situation | Typical level |
|---|---|
| Undocumented breaking change to a public contract or schema with live consumers | blocker |
| Layer/boundary violation that will spread; new cycle; second source of truth for the same data; one-way-door decision with no ADR or rollback | major |
| Speculative abstraction, needless config surface, misplaced but harmless code | minor |
| Naming of modules, taste in patterns with no concrete cost | nit/question |
