# Open questions & upstream reconciliation

Agent: SP5-FRONT · Every place this spec had to stand in for an artifact the
brief assumed exists, with the decision needed and the owner. The merge agent
reads this file FIRST. Items are ordered by blast radius.

| # | Question / conflict | What the spec did about it | Decision needed (owner) | Blocks |
|---|---|---|---|---|
| Q1 | The brief's BASE BRANCH `feature/backend-db-storage-spec` does not exist on origin (all remote refs checked). Patches chain from `origin/main` @ `0a43d95` instead. | Recorded here, in the folder README, and in the manifest (`base_branch`/`base_commit` + risks). Patches apply cleanly to `0a43d95` and likely apply with context fuzz to a post-Wave-0/S0 branch — replay-verified only against `0a43d95`. | Merge agent: apply onto the real post-Wave-0/S0 tip and re-verify replay; if the Wave-0/S0 agents created `docs/product/` + `docs/backend/` on that branch, run the §R procedure below before merging. | patch application |
| Q2 | The whole product-definition layer is absent on EVERY branch: `docs/product/features.md`, `ui-element-inventory.csv`, `information-inventory.csv`, `traceability-matrix.csv`, `decision-log.csv`, `backend-handoff.md`. The brief's "features doc already decides WHAT the product shows" is not currently true of this repo. | The spec keys to what IS binding (doctrine v1.6, kit catalog, blocks schema v1, deployment truth, the two skill bundles). All EL-/INF-/NEED-/EVT- ids are PROVISIONAL with a `source_ref` to the in-repo artifact each row derives from; `feature_id` carries `UNRESOLVED(features.md)`. No features invented beyond what the shell + doctrine already show; nothing from the brief's screen list was silently dropped (the voice dock and localized routes are spec'd as seams/hooks, not built). | Founder/merge agent: land the product-definition wave, then run §R. | the EL→F- hop of the walk-through test (spec.md §14.4 states this limitation) |
| Q3 | ADR-0007 (device pseudonym for locale persistence) referenced by the brief, absent everywhere. | Locale persistence spec'd as LOCAL-ONLY (`localStorage["zivon.lang"]`, no server write, no identifier) — the read/write site will not move when the ADR lands. | Founder: write ADR-0007 (device-pseudonym model); backend storage of preferences stays OUT until then. | locale persistence beyond device |
| Q4 | ADR-0009 (language list / localized routes) referenced by the brief, absent. DCR-001 (deferred locale work) is defined nowhere. | Language list taken from the doctrine's own §10.5 (English / हिन्दी / Hinglish) as the v1 truth; the `/{locale}/` route scheme, hreflang cluster and per-locale sitemap are SPEC'D BUT GATED (do-not-build). | Founder: write ADR-0009 (locale model + code list, aligned with SP2's model when it exists); then ungate seo-plan §3/spec §3.2. | localized routes, hreflang |
| Q5 | SP3's event contract absent (EVT- catalogue has no canonical home). Transport is ALSO blocked by the locked CSP (`connect-src 'none'`) — no same-origin sink may receive events today. | Client-side catalogue defined in spec.md §9 (each event: trigger, properties, privacy class); `ZivonEvents` queue ships with a NO-OP sink (console.debug behind a flag) so instrumentation is real without violating CSP; alignment with SP3 recorded as debt. | Founder: approve the scoped `connect-src 'self'` change request (one request covers events + voice WS); SP3: confirm/rename the catalogue. | event delivery (not collection) |
| Q6 | The brief binds the voice dock's degraded text fallback to features.md — absent. Doctrine §10.12 (voice dock directive) ALSO absent (verified against the file; §10 ends at 10.11) → DCR-002 standing guard honored: dock UI NOT designed, marked founder-gated in every file that touches it. | Fallback specified as client behavior from the layer-independence rule (G5): ws-client-contract.md §7. Dock integration seam (reserved region, lazy load, CSP request, WS client contract) spec'd; pixels/copy deliberately left to the founder. | Founder: author doctrine §10.12 (dock UI directive) + confirm the fallback product behavior. | any dock UI work |
| Q7 | Language string swaps are "shell-owned and land with i18n-aware content generation" (doctrine v1.6) — but no factory stage currently produces translated blocks, and no SP2 locale model exists to align with. | Spec'd the frontend side completely (chip behavior, untranslated = English + visible notice, never-translate list, per-page translation unit); the generation-side work item is flagged, not spec'd here (different agent's boundary). | Factory owner: i18n-aware generation stage; SP2: locale model. | the chips becoming real (v1 stub is honest about this) |
| Q8 | Perf budgets: the brief says enforce < 2 s; the founder's 2026-11-04 ruling loosened the gate to 6.0/3.5 s until real measurements exist (recorded inside the profile itself), re-tighten at Phase 4. | perf-budget-tests.md carries BOTH eras; thresholds live in the profile JSON so the re-tighten changes data, not tests. Font finding: ~940 KB variable TTFs is the dominant Era-2 blocker (spec C4). | Founder: Phase-4 re-tighten decision with measured data; decide whether field CWV data (needs §7's Search Console privacy call) is wanted or lab-only. | nothing today; Era-2 credibility |
| Q9 | Font subsetting/licensing: converting the four bundled TTFs to woff2 subsets creates DERIVED font files — the bundled faces are open-license fonts, but the exact license terms for derived/subset redistribution must be re-checked and `FONTS-LICENSE.md` kept truthful. | Spec C4 requires the license record to stay accurate; `test_font_payload_budget` guards the size win. | EX5-FRONT: verify each face's license permits subsetting/redistribution under the bundled license, update FONTS-LICENSE.md in the same change. | C4 |
| Q10 | Branding/domain: `ZIVON_PUBLIC_BASE_URL` (canonical/sitemap/OG) has no value until the hosting decision lands (TIMELINE ⬜ open); the 404 page and og-card are new founder-visible surfaces. | Everything derives from the single env var; generators are offline + idempotent; 404 + og-card spec'd as shell work items (C1, S1). | Founder: hosting/domain decision; review 404 copy + og-card art. | sitemap/canonical correctness (files generate, URLs stay relative-correct once the env lands) |

## §R — Reconciliation procedure for provisional ids (run when the features doc lands)

1. Join by `source_ref`: the canonical `ui-element-inventory.csv` (real EL- ids)
   and this folder's `component-inventory.csv` both name their binding artifact
   (doctrine § / kit component / block type / shell file). Rows whose
   source_ref matches describe the SAME element — remap is `EL-PROV → EL-CANON`
   in one pass; keep this folder's `component_name`/`file_location` (the
   implementation view) alongside the canonical id.
2. Canonical rows with NO source_ref match = elements the features doc adds
   beyond today's shell → they get NEW implementation rows here (that is new
   scope, wave EX5's, not a silent edit of this spec).
3. Provisional rows with NO canonical match after the join = candidates the
   features doc KILLED or renamed — flag, never delete silently (same rule the
   decision log uses for killed features).
4. Re-run `scripts/check_specs.py` after the remap — its orphan checks
   (used ⇒ defined, both directions) are the mechanical guard.
5. The INF-/NEED-/EVT- registers (spec.md §14) reconcile the same way against
   the canonical information inventory and SP3's contract.

## Deliberate non-decisions recorded

- The brief's "screen-state matrix states" list includes `partial` and
  `over-credit-budget` for components that cannot have them on a static page;
  state-matrix.md carries them as `n/a (reason)` rather than inventing states.
- No `TIMELINE.md` edit in this series: the Infra & Deployment task list is untouched (no infra
  changed — docs-only), per §6's "if infra changed" condition.
- No CI workflow, factory, or publish-script edit in this series: all such
  items are assignment-table rows (seo-plan §8) / integration notes, not edits.
