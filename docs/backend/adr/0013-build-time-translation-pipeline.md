# ADR-0013: Translation is a build-time reviewed pipeline (SC-01); no runtime translation (T8)
- Status: accepted (P1 build; P0 ships English + hinglish house-style chrome copy)
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing Stage-1 T8 (founder-confirmed second-layer pipeline)
- Driving NFRs / requirements: NFR-10 (bundle < 200 ms), NEED-016, F-WRP-LAN-01, layer independence

## Context
Lesson content is generated in English natively by the factory. Hindi (and the full Gnani set)
must arrive as reviewed, immutable bundles — not as a runtime translation call in the student path.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Build-time: factory translation stage → per-language reviewer gate → immutable `language_bundle` (mt_flag/reviewed_flag) → static delivery via ST-03** (adopted) | zero runtime latency/credits; quality gate mirrors the existing reviewer-graph pattern (verdict → bounded repair, no full re-run); bundles are cacheable forever | per-language credit + review cost at build; version matrix grows (page_version × locale) | P1 pipeline work | — |
| Runtime translation (Evon/Gemma translates on demand) | any-language-on-demand | adds LLM latency to a < 200 ms contract; burns voice-budget credits on content; unaudited translations of physics content reach children — fact-gate violation | medium | NFR-10, fact-review doctrine |
| Human translation only | highest quality | doesn't scale to 11 locales; no pipeline integration | high | product T2 scale intent |

## Decision
Build-time pipeline per SC-01 (handoff §7): machine translation with glossary-controlled glosses
(INF-047/049 — exam terms not translated), mt_flag shown once per page+language (INF-088), a
language ships only when its reviewer gate passes (`language_bundle.status='reviewed'` before
publish — db-spec §4.10).

## Consequences
Easier: student-side language switch is a static GET; translations inherit the factory's
resumability + evidence story (C4). Harder: publish flow now fans out per locale (live_pointer per
locale already supports it); narration regeneration per locale is a separate credit decision
(capacity-and-cost §5.2). Monitor: bundle 404 rate (fallback to English + INF-087 marker).

## Revisit trigger (measurable)
SC-01 build start (P1); or measured demand for a locale with zero bundle after 2 weeks of pilot.

## References
features.md T8; handoff §7 SC-01; db-spec §4.10; backend-spec §6.2 ST-03.
