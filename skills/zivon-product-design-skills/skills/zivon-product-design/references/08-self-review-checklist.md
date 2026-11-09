# Self-review checklist - run before delivering

Mark each item ✅ / ❌(owner, reason). Do not deliver with silent ❌.

## A. Decision quality
- [ ] A decision log exists with KEEP/MERGE/DEFER/KILL and reasons; KILLs are visible.
- [ ] Every KEEP has job, mechanism + evidence tag, removal test, cost, risk, metric.
- [ ] Layer independence verified: Core usable with wrappers and add-ons off; add-on failure never blocks Core.
- [ ] Every tension T1-T12 (and any new one) has a recorded decision or an explicit "open - needs <owner>".
- [ ] P0/P1/P2/post-challenge tag on every feature; P0 matches the repo's ladder or the deviation is flagged to the founder.

## B. Principles
- [ ] The principles brief (≤10) is at the top, each with a UI consequence and a test.
- [ ] Nielsen heuristic walk done per screen; findings logged.
- [ ] Mayer pass: coherence, signaling, redundancy/modality, contiguity, segmenting, pre-training.
- [ ] PhET pass on every simulation surface (start still, ≤3×3 controls, 1-3 word labels, consistent representations, help on request only).
- [ ] Child-safety/privacy pass: consent, minimization, no profiling/tracking, honest copy.

## C. Granularity and traceability
- [ ] Walk-through test: pick 10 random perceivable things (a word, a number, a sound, a toast) - each has an element row, an information row if data-driven, and a feature.
- [ ] State matrix has no blank cells.
- [ ] Orphan checks (`03` §8) are green.
- [ ] Every information item has source, format, localization rule, fallback, PII class, retention hint.
- [ ] Every element lists a11y role/name/keyboard and i18n rule; every spoken element lists its spoken text.
- [ ] Every sim: non-drag alternative, text state mirror, reduced-motion behaviour.

## D. Handoff
- [ ] Backend handoff list present: capability needs, entities, realtime needs, events, volume hints, retention/consent hints.
- [ ] Needs are capabilities and data shapes, not invented endpoint names.
- [ ] Content-factory/schema change proposals listed separately with cost.
- [ ] Doc Change Proposals listed (e.g. fonts, language bar), each with the doc and section affected.
- [ ] No contradiction with `AGENTS.md`, `TIMELINE.md`, `design-doctrine.md`, `blocks-schema.md` unless flagged.

## E. Honesty
- [ ] Every claim of research support names its evidence tag and source; assumptions are labelled `[ASSUMPTION]`.
- [ ] Unknowns and facts you could not verify are listed in an "Open questions" section, not smoothed over.
