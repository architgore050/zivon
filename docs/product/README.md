# Product design docs

Feature decisions and the implementation-granular FEATURES spec for Zivon. Produced with
`skills/zivon-product-design-skills/` (feature-decision suite); the final section of
`features.md` and `backend-handoff.md` are the input for the systems-design stage
(`skills/zivon-systems-design-skills/`).

| File | Contents |
|---|---|
| [`features.md`](features.md) | THE main doc: design-principles brief → personas/JTBD/journey → tension decisions (T1–T12) → feature cards → screen list → screen-state matrix → traceability summary → **backend handoff** (final section) |
| [`decision-log.csv`](decision-log.csv) | Every feature candidate (long-list) with KEEP / MERGE / DEFER / KILL + reason + evidence tag. Killed candidates are recorded, never silently dropped |
| [`ui-element-inventory.csv`](ui-element-inventory.csv) | Every perceivable UI element: ID, screen, feature, states, accessibility, fallback |
| [`information-inventory.csv`](information-inventory.csv) | Every displayed datum: ID, source, format, localization rule, failure fallback (all four mandatory) |
| [`traceability-matrix.csv`](traceability-matrix.csv) | feature ↔ element ↔ information ↔ backend need ↔ entity ↔ event |
| [`backend-handoff.md`](backend-handoff.md) | The handoff for the systems-design agent: NEED table, ENT? needs, realtime needs, EVT catalogue, volume hints, retention & consent hints, content-factory schema change proposals, Doc Change Proposals |

Rules that govern everything here (source of truth elsewhere, never re-decided here):
visual style = [`docs/frontend/design-doctrine.md`](../frontend/design-doctrine.md) (changes
go through a Doc Change Proposal, DCR-###); agent prompting =
[`skills/prompting-and-agent-design/`](../../skills/prompting-and-agent-design/); infra =
[`docs/deployment/`](../deployment/); scope ladder + gates = [`TIMELINE.md`](../../TIMELINE.md).

ID conventions (stable, never reused, never renumbered):
`F-###` feature · `SCR-###` screen · `EL-###` UI element · `INF-###` displayed information
item · `NEED-###` backend capability need · `ENT?-###` entity need · `EVT-###`
analytics/telemetry event · `T1–T12` tensions · `DCR-###` Doc Change Proposal.
