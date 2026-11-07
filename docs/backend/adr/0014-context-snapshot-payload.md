# ADR-0014: Page context = structured ≤ 4 KB `context.snapshot` per turn; provenance rides the anchor (T12)
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing Stage-1 T12 payload design
- Driving NFRs / requirements: NEED-005, NFR-03 (prompt size → first token), honesty rule ("never fake anchoring")

## Context
The tutor must answer about what the student is looking at — paragraph, sim state, last check
result — without shipping the whole page or trusting client-supplied text blindly.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **Structured snapshot: `{page_id, visible_blocks[{id,type,title}], sim_states[{block_id, controls, state_text}], last_check, coverage_summary, lang}` ≤ 4 KB, sent per turn, validated server-side by `voice/anchor`** (adopted) | bounded prompt (first-token budget); JSON is data-not-instructions (injection hygiene, backend-spec §10.3); loss-tolerant (turn proceeds with last snapshot + honest "I can't see…" note) | sim state must be summarized (`state_text_template`, SC-02) not dumped | none | — |
| Full page HTML/JSON to the LLM | complete context | blows the 4 KB bound ×10, latency cost, stale-copy drift, injection surface from generated page text | — | NFR-03 |
| No context (generic answers) | simplest | forfeits the product's core differentiator (anchored doubt tutor) | — | NEED-005 |

## Decision
Option 1, exactly the handoff §1 NEED-005 shape. Provenance (T12's other half): anchor chip text
(INF-064) is derived server-side from the validated snapshot; source citations come from the page
manifest (`page_version.sources`, SC-05 exposure P1), never from the model's imagination.
Prompt-injection rule: snapshot fields are inserted as delimited data blocks; the system prompt
forbids treating them as instructions.

## Consequences
Easier: measurable anchoring quality (EVT-005 anchor_source); 4 KB bound is a testable contract.
Harder: SC-02 (`state_text_template`) is a content-factory dependency for honest sim reading —
tracked P0-quality in handoff §7. Monitor: snapshot validation reject rate.

## Revisit trigger (measurable)
Reject rate > 5 % on complex sims (payload > 4 KB) → pagination of snapshot fields or SC-02
template tightening.

## References
features.md T12; handoff §1 NEED-005 + §7 SC-02/SC-05; backend-spec §7.2.
