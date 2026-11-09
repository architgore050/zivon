# AGENTS.md / CLAUDE.md rubric

Contents: purpose · inclusion test · what to keep · what to cut · structure · scale and layout · keeping it current · scoring · common findings

## Purpose

AGENTS.md (and tool-specific equivalents like CLAUDE.md) is the operating manual a coding agent reads at the start of every task. Because it is loaded every time, **each line has a recurring cost** in attention and tokens, and an instruction the agent follows faithfully is a cost even when it wasn't needed. Reported evaluations of context files have found that padded or auto-generated files add cost and can make tasks harder, while specific, non-obvious guidance (like which tool to use) gets followed reliably and helps. So the standard is *short, specific, true*.

## The inclusion test (apply to every line)

1. **Can the agent discover this by reading the repo** (code, config, README, scripts, directory tree, lint rules)? If yes → cut it, or replace with a pointer.
2. If not, **does it materially affect task success, cost, or safety**, and would a capable agent likely get it wrong without being told? If yes → keep it.
3. If you aren't sure the line earns its place → cut it. Re-add it when the agent actually makes that mistake. Good files grow from observed failures, not upfront planning.

## What to keep

- **Exact commands** to build, test (including single-test invocation), lint, typecheck, format, run locally, using the repo's stable wrappers (`make test`, `pnpm test`, `just check`) rather than long one-off flag strings.
- **Non-obvious tooling**: "use `uv`, not `pip`", "use `bun`", required Node/Python version, monorepo filter syntax, codegen steps that must run after schema changes.
- **Gotchas that burned people**: ordering constraints, files that are generated and must not be edited, tests that need a service running, flaky areas, known traps ("adding an enum value requires updating X or tests fail").
- **Boundaries and permissions**: what the agent must never touch (secrets, generated code, vendored dirs, prod configs), what needs confirmation (migrations, dependency additions, destructive commands), what's always fine.
- **Conventions that deviate from the default** or aren't enforced by tooling: error-handling pattern, where new modules go, commit/PR format, naming rules specific to this codebase.
- **Definition of done**: what to run before declaring the task finished.
- **Pointers** to deeper docs with a one-line description of when to read each (`docs/db-schema.md: read before changing models`), so detail loads only when relevant.

## What to cut

| Content | Why |
|---|---|
| Directory tree dumps; "src/ contains the source code" | Discoverable; goes stale on every move |
| Architecture prose an agent can learn from reading the code | Redundant and drifts |
| Generic advice ("write clean code", "follow SOLID", "write tests", "be careful") | Doesn't change behavior; costs attention |
| Rules already enforced by linter/formatter/typechecker/CI | Tooling enforces them; the agent sees failures directly |
| Long style guides pasted inline | Link to them or enforce in tooling |
| Aspirational practices the repo doesn't actually follow | Actively misleading |
| Personal preferences | Belong in a local, untracked file |
| Secrets, tokens, internal URLs that shouldn't be in git | Security |
| Persona fluff ("You are a world-class engineer") | No effect on repo-specific success |
| Duplicates of README content | Two sources of truth that will diverge |
| Task-specific or one-off instructions | Put in the prompt or issue instead |

## Structure

- Imperative and concrete: "Run `pnpm test --filter api`" beats "Tests should be run."
- Commands in a code block or table; one line per rule where possible.
- Group by what the agent is doing: Setup/Commands · Testing · Conventions · Boundaries · Gotchas · Pointers.
- Specific beats vague: show the preferred pattern with a short example when a convention is subtle.
- Put the most failure-prone items first.

## Scale and layout

- Root file: aim for roughly 50–150 lines; treat ~300 as a ceiling that needs justification. Under 60 is great when the repo allows.
- Use **nested files** (`packages/api/AGENTS.md`) for package-specific rules; keep the root general. Nearest file wins; avoid contradicting parents.
- Move long reference material into separate docs (`docs/agents/*.md`) linked from the root with when-to-read hints, so it's loaded on demand.
- **One canonical file.** If multiple tools need instructions, keep AGENTS.md canonical and have `CLAUDE.md` and others import it or symlink to it rather than copy.

## Keeping it current

- Treat it as code: **update it in the same PR** that changes the commands, tooling, structure, or conventions it describes. Reviewers should check it as they check tests.
- When an agent repeats a mistake, add the minimal rule (or fix the unclear one); when a rule no longer changes behavior, delete it.
- Periodic audit: run every documented command; confirm paths and tool names exist; remove stale entries; look for contradictions with README, CONTRIBUTING, CI config, and nested files.
- Don't auto-generate it wholesale from templates or by asking a model to summarize the repo; generated files tend to restate what's discoverable. Draft by hand from real pain points, and use generation only for suggestions you then prune.

## Scoring (0–2 each; total /12)

| Criterion | 0 | 1 | 2 |
|---|---|---|---|
| **Accuracy**: commands/paths/versions verified working | Stale or broken items | Mostly right | All verified |
| **Signal density**: lines pass the inclusion test | Mostly generic/discoverable | Mixed | Nearly every line earns its place |
| **Actionability**: exact commands, concrete rules | Vague | Partly concrete | Executable and specific |
| **Boundaries & gotchas**: safety limits and known traps stated | Absent | Some | Clear and complete for the repo's risks |
| **Size & layout**: concise, progressive disclosure, nested where useful | Bloated or monolithic | Acceptable | Lean with on-demand depth |
| **Consistency**: no contradictions/duplication across README, CLAUDE.md, nested files, CI | Conflicts | Minor overlap | Single source of truth |

Interpretation: 10–12 healthy · 7–9 needs pruning and verification · ≤6 likely hurting more than helping; rewrite from observed failures.

## Common findings

- **major**: documented build/test command fails or no longer exists; instruction contradicts CI or README; file instructs agents to do something unsafe (commit secrets, skip tests, bypass hooks).
- **major**: code change altered tooling/structure/conventions but AGENTS.md wasn't updated in the same PR.
- **minor**: directory tree or architecture summary that duplicates discoverable info; generic best-practice lists; files over ~300 lines; duplicated content across AGENTS.md and CLAUDE.md.
- **nit**: formatting and ordering.
