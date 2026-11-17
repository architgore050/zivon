# 2026-11-17 — Personalized learning spec (W5.5)

Branch `feature/personalized-learning-spec` (based on `main` @ `811e775`).
PR [#62](https://github.com/architgore050/zivon/pull/62) — docs-only, opened for
independent review, **not merged** by this agent.

## Done

- Wrote `docs/specs/personalized-learning/` (10 markdown files + the 30-row
  `decision-log-addendum.csv`): README, feature addendum, product flow, teaching
  state machine + RAG contract, artifact sandbox, data/API contract, 16-threat
  security model, `EV-PL-001…005`, PL1–PL5 workstreams, and D-PL-01…11 open
  founder decisions with recommendations.
- Recorded the binding founder correction: **free prototype, login required, no
  paywall/payment/plan/subscription/entitlement**; quotas are fairness/cost
  controls.
- Specified personalized learning on **DeepSeek V4.1 Flash via the OpenCode API
  key**, separate from the Gemma voice tutor and the factory credentials
  (D-PL-07); added the `AGENTS.md` routing row and clarified the factory row.
- Added the `AGENTS.md` docs map entry, the `TIMELINE.md` **W5.5** wave row +
  section (dependencies, exit gate, out-of-scope), and the `README.md` index row.
- Added `testing/docs/test_personalized_learning_spec.py` (required files and
  headings, relative links, decision recommendations, eval ids/checkers,
  workstreams, tables, no-paywall rule, AGENTS/TIMELINE pointers). It runs in
  the existing path-guarded `testing/docs` CI loop; no workflow edit.

## Decisions made in the spec (recommendations, founder answers pending)

- Login scope read as **this feature only**; the frozen guest-first lesson /
  practice / voice surfaces are unchanged (D-PL-11).
- One saved-conversation store (`personalized_session`) rather than a second
  `doubt` store; the dock's TUT-05 history can join it later (D-PL-09).
- 90-day retention for session text, no cold copy, export/delete first-class
  (D-PL-05); counsel review flagged before scale-up.
- Bank-first diagnostics/checks; generated items never enter `question_bank`
  (PL-T2).
- Artifacts: sandboxed iframe (`allow-scripts`, no same-origin), strict CSP,
  content-hash cache, signed short-TTL URL for a dedicated origin (PL-T4).
- Free-tier defaults: 40 turns/user/day, 6/min, 2 concurrent, 1,500 global/day,
  12 artifact builds/user/day (D-PL-01); DeepSeek p50 ≤ 6 s / p90 ≤ 15 s first
  text, 30 s hard deadline (D-PL-06).

## Not done

- No product code, migration, endpoint, template, or asset (spec only, by
  instruction).
- `evals/cards/EV-PL-*.yaml`, `evals/checkers/personalized_checks.py`, and the
  goldens are **specified but not authored** (PL5).
- No personalized RAG index build; no OpenCode latency probe; no founder
  answers to D-PL-01…11; no counsel review.
- No frontend example page or founder visual verdict (D-PL-10).

## Next

1. Founder answers the blocking decisions: D-PL-01 (quota numbers), D-PL-05
   (retention/counsel timing), D-PL-06 (latency/cost), D-PL-07 (routing
   confirmation), D-PL-11 (login scope).
2. PL1: migration `0005_personalized_learning`, preferences/quota/session
   APIs, deletion/retention, security tests.
3. PL2: state machine + prompts + RAG index builder + the OpenCode probe; then
   PL3 artifacts, PL4 frontend, PL5 evals.

## Evidence

- `python3 -m unittest discover -s testing/docs -t .` — 46 tests OK (19 new).
- `ruff check testing/docs/test_personalized_learning_spec.py` — clean.
- `ruff format --check docs/specs/personalized-learning/*.md` — clean.
- Relative links, table shapes, and ID registers checked by the new test.

## Notes

- The spec is not legal advice; DPDP/counsel flags are recorded in
  `security-privacy.md` §9 and D-PL-05.
- No secret was read into a file, printed, or committed. The PR was opened with
  the repository's existing credential helper.
