# F-<LAYER>-<AREA>-<NN> - <Feature name>

| Field | Value |
|---|---|
| Layer | COR / WRP / ADD / XCT / OPS |
| One-sentence summary | (a Class-9 student's parent would understand it) |
| Priority | P0 / P1 / P2 / post-challenge  (repo ladder; say why) |
| Kano class | must-be / performance / delighter |
| Decision-log ref | cand-NNN |
| Job + moment | JTBD id · journey moment |
| Value hypothesis | "If we ship this, <who> will <behaviour>, shown by <metric>." |
| Success metric(s) / events | EVT-… → metric definition |
| Principles applied | 2-4, each: principle → the decision it caused |
| Evidence tag | STRONG / MODERATE / WEAK / ASSUMPTION |
| Depends on / blocks | feature ids |
| Layer-independence | what happens when this feature (or its model/vendor) is down |

## Behaviour (EARS, numbered, testable)
1. When …, the system shall …
2. While …, the system shall …
3. If …, then the system shall … (unhappy path)

## Acceptance criteria (Given / When / Then)
- AC-1 happy path
- AC-2 unhappy path
- AC-3 accessibility (keyboard / screen reader / reduced motion)
- AC-4 low-end device / poor network
- AC-5 localization (longest-language label, untranslated fallback)
- AC-6 privacy/consent (what is stored, who consented)

## States
| State | What the user sees/hears | Entry | Exit | Copy keys | Events |
|---|---|---|---|---|---|

## Surfaces
Screens/regions: SCR-…  ·  Elements: EL-… (list ids)  ·  Information: INF-… (list ids)

## Backend needs (capabilities, not endpoints)
| NEED id | Purpose | Caller (EL/feature) | Request shape | Response shape | Latency / freshness | Auth/consent | UI behaviour on failure |
|---|---|---|---|---|---|---|---|

## Entities and data
ENT?-… with the fields this feature reads/writes; retention/consent hints.

## Cost and risk
Bytes · CPU · network · battery · Gnani credits (STT sec / TTS chars / LLM tokens) · ops burden · content-factory burden · legal/safety flags.

## Open questions
- Q: … · owner: … · blocking? y/n
