# System gaps — Wave S2 (SP6-GAPS)

Wave S2 completeness sweep (SP6-GAPS, 2026-11-09) — run locally by the merge agent after the five S1 specs merged to main (WS1 BASE_SHA `add64e7`; this folder is WS2 on `main`).

- [`gap-register.md`](gap-register.md) — one row per gap: `GAP-###`, severity (blocker/major/minor), owner (EX0–EX8 / EX7 / founder-manual / post-challenge), status, and a contract-level mini-spec for every buildable gap. Anything discovered by walking the system as a student, an operator, and an attacker is registered here; nothing is silently overridden.
- [`wave-E-assignment.md`](wave-E-assignment.md) — the final Wave-E work split (which EX agent builds what, so execution agents never overlap).

This folder does not re-decide Stage-1 (`docs/product/`) or Stage-2 (`docs/backend/` ADR-0001–0016) decisions. Where a gap contradicts them, the row records the conflict and the revisit trigger instead.
