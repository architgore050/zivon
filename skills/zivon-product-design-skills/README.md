# zivon-product-design-skills (bundle)

Skills for **deciding which features a learning product should have, and specifying each to implementation granularity.** Built for Zivon (voice-first Physics tutor: interactive simulations + translation + text-to-speech + voice agent + personalization), reusable for similar products.

## Read order for an agent

1. This README (2 min).
2. `skills/zivon-product-design/SKILL.md` - the method. **Always.**
3. Open `references/*` and `templates/*` only as the SKILL.md phase table directs.
4. `vendored/INDEX.md` - pick third-party skills for single artifacts (JTBD canvas, journey map, user stories, EARS requirements, instrumentation spec…).
5. When finished, hand the backend handoff list to the `zivon-systems-design-skills` bundle.

## Layout
```
zivon-product-design-skills/
├── README.md  NOTICE.md
├── skills/zivon-product-design/        ← original, Zivon-specific
│   ├── SKILL.md  README.md
│   ├── references/  01 principles · 02 value filter · 03 granular spec · 04 education+sim UX · 05 voice/translation/TTS UX
│   │                06 India/a11y/privacy · 07 tensions T1-T12 · 08 review checklist · sources-and-evidence
│   └── templates/   feature-card · ui-element-inventory.csv · information-inventory.csv · screen-state-matrix
│                    traceability-matrix.csv · decision-log.csv · design-principles-brief · backend-handoff
└── vendored/                           ← third-party, licences retained (see INDEX.md)
    ├── pm-skills/ (Apache-2.0)  define-jtbd-canvas · discover-journey-map · foundation-persona · define-opportunity-tree
    │                            define-problem-statement · define-hypothesis · deliver-user-stories · deliver-acceptance-criteria
    │                            deliver-edge-cases · deliver-prd · develop-design-rationale · measure-instrumentation-spec
    └── jeffallan-claude-skills/ (MIT)  feature-forge
```

## Install
Zivon convention: `skills/<name>/` with README + SKILL.md + references. Copy `skills/zivon-product-design/` to the repo's `skills/`; copy `vendored/` to `skills/vendored/` (or keep outside the repo if licence-notice overhead is unwanted). For Claude Code: place folders under `.claude/skills/`. **Update the Zivon `AGENTS.md` "Content creation skills" section and the README repo map in the same PR** (the repo's own "keep the map current" rule).

## What is deliberately *not* here
Visual style (use `docs/frontend/design-doctrine.md`), agent prompting (use `skills/prompting-and-agent-design/`), backend/storage design (sibling bundle).

## Verification status
Sources are tagged V (read), S (search snippet), C (canonical, from memory) in `skills/zivon-product-design/references/sources-and-evidence.md`. The PhET interface paper was read in full; DPDP law was read via secondary summaries only; WCAG 2.2 criteria numbers are from memory - verify before quoting.
