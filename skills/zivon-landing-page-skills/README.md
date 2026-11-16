# zivon-landing-page-skills

Designing Zivon's landing page as an **ad**, not a SaaS template: one promise,
one action, a chosen narrative spine, honest proof, and Field Notes base-doctrine
art direction.

## Scope

**In scope**

- The landing page (`/`) and any public hook page with a single conversion job:
  campaign pages, waitlist pages, the for-schools page, a class or subject launch
  page.
- The argument: audience, awareness stage, emotion, narrative spine, section
  order, headline and CTA copy, microcopy for every state.
- The first screen: composition, one pen annotation, real product artifacts,
  the 360 px ordering.
- Trust: claim ledgers, testimonials, "official" language, privacy copy, honest
  limitations.
- Motion, media, Core Web Vitals, and the low-end-Android budget as they apply
  to a page whose main job is to be read fast.
- Measurement and critique: the conversion event, the funnel, the qualitative
  tests, and the scored rubric.

**Out of scope — go elsewhere**

| Need | Owner |
|---|---|
| Lesson-page visual language, the voice dock, read-aloud, consent gate | `skills/zivon-frontend-product-skills/` + `docs/frontend/design-doctrine.md` §10 |
| Which features exist, which were killed, and why | `docs/product/` + `skills/zivon-product-design-skills/` |
| Route placement (static vs SSR), app shell, auth, dashboard | `skills/zivon-frontend-product-skills/` |
| Exam-content attribution, non-affiliation copy, publish gates | `docs/compliance/` |
| Backend contracts, events pipeline, data model | `docs/backend/`, `docs/specs/observability/` |
| SEO mechanics (canonicals, JSON-LD, sitemaps) | `skills/zivon-frontend-skills/seo-optimization.md` |
| Content generation, translation, narration | `skills/zivon-pipeline-engineering-skills/` |

This bundle does not add design tokens, does not rewrite the doctrine, and does
not decide product scope. Where it and the doctrine disagree, the doctrine wins.

## Layout

```
zivon-landing-page-skills/
├── SKILL.md                              entry point: stance, workflow, non-negotiables, map
├── README.md                             this file
├── references/
│   ├── audience-and-emotion.md           awareness stages, jobs, fears, objections, honest emotion
│   ├── narrative-frameworks.md           the default spine + PAS/AIDA/BAB/FAB/4U/StoryBrand as lenses
│   ├── page-anatomy.md                   section jobs, order as an argument, when to omit
│   ├── copywriting-and-microcopy.md      one promise, headline formulas, CTA and state copy
│   ├── art-direction.md                  §1–§9 applied, the §10 guard, composition, 360 px
│   ├── proof-and-trust.md                claim ledger, proof strength, testimonials, "official"
│   ├── motion-and-performance.md         scroll narrative, reduced motion, CWV, weak Android
│   ├── measurement.md                    events, funnel, qualitative tests, A/B rules
│   ├── critique-rubric.md                nine scored dimensions, blockers, verdict
│   ├── teardowns.md                      nine public pages, what to learn, what not to copy
│   └── sources.md                        dated source register, evidence vs practitioner opinion
├── templates/
│   ├── landing-brief.md                  the four framing sentences + banned appeals
│   ├── storyboard.md                     section -> claim -> evidence -> objection -> value test
│   ├── wireframe.md                      360 px and 1280 px composition grids
│   ├── copy-deck.md                      promise, variants, sections, states, meta
│   ├── hero-variants.md                  five strategies, what each tests, what result means
│   └── critique-sheet.md                 the scored review form
└── examples/
    └── zivon-landing-brief.md            a full worked Zivon brief, storyboard and hero set
```

## Read order

1. `SKILL.md` — the stance, the ten non-negotiables, the workflow.
2. `references/audience-and-emotion.md` — before anything is written.
3. `references/narrative-frameworks.md` — before anything is ordered.
4. `references/page-anatomy.md` — while storyboarding.
5. `references/copywriting-and-microcopy.md` — while writing.
6. `references/art-direction.md` — before the first visual decision.
7. `references/proof-and-trust.md` — before any claim ships.
8. `references/motion-and-performance.md` and `references/measurement.md` —
   before the build and before the test.
9. `references/critique-rubric.md` — before the PR.
10. `references/teardowns.md` and `references/sources.md` — as needed, never as
    authority over the doctrine or the product docs.

`examples/zivon-landing-brief.md` is the worked demonstration. Read it after
step 5, not before: it is one solution to the method, not the method.

## Provenance and sources

- **Brand authority:** `docs/frontend/design-doctrine.md` v1.6 (§1–§9 for every
  surface; §10 lesson-only) and `docs/frontend/design-doctrine-example.html`.
  The doctrine is founder-authored; this bundle interprets it and records any
  derivation (for example a web type scale) as a derivation for the founder's
  verdict, never as a new rule.
- **Product authority:** `docs/product/features.md`,
  `docs/product/decision-log.csv`, `docs/product/ui-element-inventory.csv`, and
  the frozen full-frontend plan (`tmp/full-frontend/FEATURE-MAP.md` F1/PUB-01,
  `REQUIREMENTS.md` §10.1). The `tmp/` files are workspace-local and not
  committed; if they are absent, use `docs/product/features.md` +
  `docs/specs/frontend/`. Those decisions are already made; this bundle does not
  re-open them.
- **Compliance authority:** `docs/compliance/` for NCERT attribution,
  CBSE non-affiliation, and user-facing notice copy.
- **External research:** eighteen sources fetched 2026-11-16, listed with URL,
  date, access status, and an evidence tag in
  [`references/sources.md`](references/sources.md). They are research and
  standards bodies (Nielsen Norman Group, W3C/WAI, web.dev, Baymard, and
  Lindgaard et al.), regulators and public-service guidance (FTC, GOV.UK), one
  vendor benchmark (Unbounce, labelled as such), and two practitioner frameworks
  (StoryBrand, Schwartz, labelled `[P]` everywhere they are used).
- **No third-party prose was copied.** Frameworks are summarised and attributed;
  teardown pages are linked and described, never reproduced.

## Maintenance

- `metadata.evidence_date` is the date the external claims were last checked.
- Re-verify before citing: Core Web Vitals thresholds, WCAG success-criterion
  levels, FTC rules, benchmark numbers, and every teardown URL. Numbers in this
  bundle carry their source date for exactly this reason.
- New research that contradicts a rule is a reason to change the rule and the
  source register together, in one PR.
- The validator gate:

```bash
python3 scripts/check_skills.py --strict --bundle skills/zivon-landing-page-skills
python3 -m unittest discover -s testing/skills -t .
```

## Changelog

| Version | Date | Change |
|---|---|---|
| 1.0 | 2026-11-16 | Initial bundle: stance, ten non-negotiables, value-addition test, argument chain, ten references, six templates, one worked example, nine teardowns, eighteen dated sources |
