# ADR-0015: Credit guard = atomic two-dimension hot counters (global tranche + per-user cap) with a togglable profile row
- Status: accepted
- Date / deciders: 2026-11-07, Stage-2 systems session, implementing the founder config of 2026-11-07 (1 000/day global, 30/day per-user, normal↔demo profiles, logged toggle)
- Driving NFRs / requirements: NFR-14 (< 5 ms check, ≤ 5 s push), NFR-25 (≤ 2 % drift), NEED-009, capacity-and-cost §3 (binding constraint)

## Context
The guard must decide *before every turn* whether credits remain, on two independent dimensions,
without a read-then-write race, at 40 k metered calls/day, and must survive pod restarts.

## Options considered
| Option | Pros | Cons | Cost/ops burden | Fails which NFR? |
|---|---|---|---|---|
| **`guard_counter` hot rows: one `INSERT … ON CONFLICT … UPDATE … RETURNING` per turn reserving an estimated turn cost against both (period, global) and (period, device) rows; `guard_profile` singleton row for mode/limits; state pushed over WS** (adopted) | atomic in one statement (no race); crash-safe (counters live in U2, rebuilt exactly); demo toggle is one audited UPDATE; < 5 ms trivially | reservation is an estimate → over/under-count corrected by ledger reconciliation; multi-pod contention to watch | none beyond the table | — |
| Sum the ledger per check | exact | 40 k/day aggregations on the hot path; race between sum and decision | — | NFR-14 |
| In-memory counters only | fastest | lost on restart (credit over-burn), no cross-pod truth | — | NFR-25 |
| Gnani dashboard as the counter | external truth | API latency in the hot path; rate limits; no per-user concept | — | NFR-14/01 |

## Decision
Option 1. Reserve-before-turn with estimated cost (≈ 15 s STT + 600 chars TTS, A-07 figures);
actuals land in `credit_ledger`; nightly reconciliation closes the gap (≤ 2 %). Demo reserve
(~40 % of remaining programme budget) is a `reserved` bucket cap enforced in the same counter
logic. Profile flip: API-A4 → `guard_profile` UPDATE + `audit_log` row + `state` push ≤ 5 s.

## Consequences
Easier: guard logic is one function, testable; profiles are config not code. Harder: estimate
tuning (too high wastes budget, too low risks overshoot — bounded by reconciliation); counter
rows are the hottest table (pruned nightly). Monitor: counter-vs-ledger delta, warn-state
session starts.

## Revisit trigger (measurable)
Voice backend > 1 replica with counter contention (tuple lock waits visible), or estimate error
> 10 % median → move reservation to `SELECT … FOR UPDATE` batching or per-pod sharded counters.

## References
NEED-009 (founder config text); db-spec §4.5; backend-spec §8.4; features.md F-OPS-MET-01.
