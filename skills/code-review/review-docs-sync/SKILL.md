---
name: review-docs-sync
description: "Documentation-freshness lens for code review. Use whenever a change might make written docs untrue, and when auditing docs: README, AGENTS.md, CLAUDE.md, CONTRIBUTING, CHANGELOG, API/OpenAPI docs, docstrings, ADRs, runbooks, .env.example, and setup instructions. Use when commands, scripts, config or env vars, public APIs, dependencies or runtime versions, directory layout, or conventions change; when the user asks \"are the docs up to date\", \"does AGENTS.md need updating\", \"review my README\", \"write/trim AGENTS.md\", or \"what docs does this PR affect\". Detects drift by checking claims against the code instead of eyeballing prose."
---

# Docs Sync Review

Docs are a promise about the code. A stale doc is worse than a missing one: it sends people (and coding agents) confidently in the wrong direction. This lens finds where the repo's written claims no longer match reality, and judges whether the docs that exist earn their place.

Findings use the shared format and severity scale from `code-review`. For AGENTS.md/CLAUDE.md specifically, read `references/agents-md-rubric.md`.

## 1. Derive the doc impact of the change

From the diff, list what changed in anything a reader could depend on:

| Changed in code | Docs that may now be wrong |
|---|---|
| Commands, scripts, Makefile/justfile targets, package.json scripts, CLI flags | README quickstart, CONTRIBUTING, AGENTS.md commands, CI docs |
| Env vars, config keys, defaults, feature flags | `.env.example`, config reference, deployment docs, runbooks |
| Public function/endpoint/schema/event signatures or behavior | API docs, OpenAPI/GraphQL schema, docstrings, examples, SDK docs |
| Dependencies, runtime/tool versions, supported platforms | README requirements, install docs, Dockerfile comments, CI matrix notes |
| Directory layout, module names, moved/renamed/deleted files | Architecture docs, AGENTS.md pointers, relative links, import examples |
| Conventions, workflow, test or lint tooling, branch/PR rules | AGENTS.md, CONTRIBUTING, PR template |
| Architectural decisions | ADRs (add, supersede, or mark stale) |
| User-visible behavior, breaking changes, deprecations | CHANGELOG / release notes, migration guide |

For each changed item, **grep the docs** for its old name, value, path, or command (`rg -n "old_name|OLD_ENV|path/to/moved"` across `*.md`, `docs/`, examples, templates, comments). Every hit that is now false is a finding. Absence of any hit for something that *should* be documented (a new required env var) is also a finding.

## 2. Verify claims, don't just read them

- **Run the documented commands** (build, test, lint, quickstart) or at least confirm each script/target exists and flags are valid. A quickstart that fails on a clean checkout is a **major**.
- Check that referenced **paths, files, links, and anchors exist**; that code snippets still compile/run against current APIs; that version numbers match manifests and CI.
- Compare documented defaults and behavior to the code and config.
- Check that examples in docstrings and docs reflect the current signature (parameter names, order, return shape, errors raised).

## 3. Judge each doc type

**README**: could a newcomer go from clone to working in about ten minutes? It should cover what it is and why, requirements, install, a *verified* quickstart, basic usage, configuration pointers, how to run tests, how to contribute, license. Prefer links to deeper docs over duplicating them. Flag: marketing without instructions, setup steps that assume hidden knowledge, badges pointing at dead CI.

**AGENTS.md / CLAUDE.md** (instructions for coding agents; see the rubric reference): keep short, contain only what an agent *cannot* discover from the repo and that materially affects task success or safety, stay accurate, and update **in the same PR** as the change that invalidates them. Padding, generic advice, and stale commands are real costs because every line is read on every task.

**CHANGELOG / release notes**: user-facing changes recorded under the right category; breaking changes and migration steps called out; entry matches what the diff actually does. Skip if the project generates notes automatically.

**API and reference docs**: parameters, types, defaults, errors, auth requirements, examples; deprecations marked with the replacement and removal timeline.

**Code comments and docstrings**: explain *why* and non-obvious contracts; flag comments that now contradict the code (worse than none), commented-out code, and TODOs without owner or issue. Don't demand docstrings on self-evident code.

**ADRs**: significant decisions have a record (context, options, decision, consequences); superseded ones are marked; code that contradicts an accepted ADR is flagged (hand off to `review-architecture`).

**Runbooks and operational docs**: alerts, dashboards, rollback steps, and on-call procedures updated when behavior or infra changes (see `review-production-readiness`).

## 4. Anti-drift hygiene (suggest, don't preach)

- **One source of truth.** If README, AGENTS.md, and CLAUDE.md duplicate each other, they will diverge. Prefer one canonical file with the others importing/symlinking to it, and link to code or config rather than restating values.
- **Generate what can be generated** (CLI help, API reference from schemas/types, config tables) and check it in CI (`docs build`, link checker, `--check` mode) so drift fails a build instead of relying on memory.
- **Docs as part of "done."** A PR template checkbox or CI check that flags code changes without doc changes in sensitive areas is cheap and effective.
- Keep docs close to code (nested READMEs/AGENTS.md per package) when the content is package-specific.

## 5. Output

Produce a **doc-debt table** so the author can act quickly:

| Doc | Location | Stale or missing claim | Evidence | Fix |
|---|---|---|---|---|

Then list what's accurate and verified, so the reader knows the scope of the check. If the user wants fixes, edit the docs directly: minimal, factual diffs; don't rewrite voice or restructure beyond what's needed.

## Severity guidance

| Situation | Typical level |
|---|---|
| Quickstart/setup/build instructions that fail; docs that instruct something unsafe or destructive; undocumented breaking change | major–blocker |
| Stale command, path, env var, or example that will mislead; missing required config documentation; AGENTS.md giving wrong commands | major |
| Missing changelog entry; outdated screenshot; wordy or redundant doc; docstring gaps on public API | minor |
| Wording and formatting preferences | nit |
