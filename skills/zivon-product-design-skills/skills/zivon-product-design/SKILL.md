---
name: zivon-product-design
description: Method for deciding WHICH features a learning product should have, then specifying each one at implementation granularity (feature → screen → element → data → API → event). Grounded in Rams, Nielsen, Mayer, PhET simulation research, physics-education research and voice-UI practice. Use whenever you must write, extend or review a feature list, PRD, UX spec, screen/element inventory, information inventory, or a frontend-to-backend traceability map for Zivon (the Physics voice tutor) or any product combining interactive simulations, translation, text-to-speech and a voice agent. Trigger even when the request is only "list the features", "what should the frontend show", "map every element", "what does the UI need from the backend", or "decide what to build". Use it BEFORE the systems-design skill - its output is that skill's input.
---

# Zivon Product Design

A method, not a template dump. It makes an agent **decide** which features add real
learning value, **cut** the rest with a recorded reason, and then **specify** each
survivor so precisely that a frontend and a backend can be built from the document
without asking the author anything.

Evidence tags used everywhere: `[STRONG]` replicated / large-sample research,
`[MODERATE]` credible but narrower or older, `[WEAK]` practitioner consensus,
`[ASSUMPTION]` ours - must be tested. Every principle in `references/` carries one.
This mirrors the repo's own `docs/frontend/design-doctrine.md` convention.

## When NOT to use this skill

- Visual styling, palette, type, lesson-page look: that is the repo's
  `docs/frontend/design-doctrine.md`. This skill never overrides it; if a feature
  needs a doctrine change, write a **Doc Change Proposal** (see Phase 8).
- Writing agent prompts for the content factory or tutor: use the repo's
  `skills/prompting-and-agent-design/`.
- Backend/DB/storage design: use the sibling `zivon-systems-design` skill, after
  this one.

## The pipeline (do the phases in order; each has an exit test)

| # | Phase | Output | Exit test |
|---|---|---|---|
| 0 | **Orient** - read repo docs, inventory what already exists (core is built) | Constraints + "already exists" table | You can state what is built vs. missing without guessing |
| 1 | **Principles brief** - pick the ≤10 principles that govern this product | Brief placed at the top of the final doc | Each principle names a concrete UI consequence and a test |
| 2 | **Users, jobs, moments** | Personas (student, parent/guardian, content-ops admin), JTBD, journey map, moments of truth | Every later feature can cite a job and a moment |
| 3 | **Capability long-list** across layers: Core, Wrapper (translation, TTS), Add-on (voice agent, personalization), cross-cutting (consent, safety, offline, a11y), ops/admin | 60-150 raw candidates, deliberately over-generated | Each layer has candidates; nothing is filtered yet |
| 4 | **Value filter** - gate every candidate (`references/02-feature-value-filter.md`) | Decision log: KEEP / MERGE / DEFER / KILL, each with reason + evidence tag | Killed items are recorded, not silently dropped |
| 5 | **Feature cards** for survivors (`templates/feature-card.md`) | One card per feature, stable IDs | Every card has job, metric, principles applied, acceptance criteria, states |
| 6 | **Screens → elements → information** (`references/03-granular-spec-method.md`) | Screen list, UI element inventory, information inventory, state matrix | Walk-through test: pick any pixel/word/sound a user can perceive - it has a row |
| 7 | **Traceability + backend handoff** | Matrix feature↔element↔info↔API need↔entity↔event; handoff list for the systems agent | Zero orphans in either direction |
| 8 | **Review** (`references/08-self-review-checklist.md`) | Heuristic evaluation, Mayer/PhET pass, child-safety pass, Doc Change Proposals | Checklist all green or each red item has an owner and a reason |

## Hard rules

1. **Decide, then specify.** No feature card exists without a surviving decision-log row.
2. **No orphans.** Every element traces to a feature; every feature to ≥1 job and ≥1 metric; every displayed datum to a source.
3. **Every datum has four properties**: source, format, localization rule, failure fallback.
4. **All states, not the happy path**: default, loading, empty, partial, error, offline, permission-denied, reduced-motion, untranslated, over-credit-budget.
5. **Subtract first.** Ask "what breaks if this is removed?" Prefer fewer, deeper features (Rams #10: as little design as possible).
6. **Layer independence.** Core works with every wrapper and add-on off. Wrappers work with the add-on off. A failing add-on never blocks reading, simulating or checking. This is a product rule *and* the key backend isolation boundary.
7. **Children are the users.** Defaults are private and safe; no dark patterns, ads, streaks-as-coercion or engagement maximizing; the metric is learning. Anything that tracks or profiles a child is flagged for legal review (see `references/06-india-context-a11y-privacy.md`).
8. **Low-end Android, low bandwidth, and a noisy room are the base case**, not edge cases (repo constraint).
9. **Never silently contradict the repo.** Read `AGENTS.md`, `TIMELINE.md`, `docs/DECISIONS-and-RESEARCH/`, `docs/frontend/design-doctrine.md`, `docs/content-factory/blocks-schema.md` first. Respect the P0/P1/P2 ladder and the "explicitly out of scope" list; if the user's brief now overrides it, say so openly.
10. **The document is a handoff.** A reader with no access to you must be able to build from it. Prefer tables with stable IDs over prose.

## Reference map - load only what the phase needs

| Need | File |
|---|---|
| Choose and phrase the governing principles | `references/01-principles-catalog.md` |
| Decide what to build / cut | `references/02-feature-value-filter.md` |
| Get to element-level granularity and traceability | `references/03-granular-spec-method.md` |
| Simulations, checks, pedagogy | `references/04-education-and-simulation-ux.md` |
| Voice agent, translation, TTS interaction design | `references/05-voice-translation-tts-ux.md` |
| India context, a11y, performance budgets, child data | `references/06-india-context-a11y-privacy.md` |
| Known product tensions the author must resolve | `references/07-zivon-tensions-to-resolve.md` |
| Final quality gate | `references/08-self-review-checklist.md` |
| Citations and verification status | `references/sources-and-evidence.md` |
| Fill-in templates | `templates/` |

## Combine with vendored skills (in `../../vendored/`)

Use them for the *mechanics* of a single artifact; use this skill for the *decisions*.
`define-jtbd-canvas`, `discover-journey-map`, `foundation-persona`,
`define-opportunity-tree`, `define-problem-statement`, `define-hypothesis` (Phases 2-4);
`deliver-user-stories`, `deliver-acceptance-criteria`, `deliver-edge-cases`,
`feature-forge` (EARS requirements; Phase 5); `develop-design-rationale` (Phase 4/8);
`measure-instrumentation-spec` (events, Phase 7); `deliver-prd` (only if a conventional PRD is also wanted).
Where a vendored skill's template conflicts with a hard rule above, the hard rule wins.
