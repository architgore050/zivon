# 2026-11-17 — Personalized learning spec (W5.5)

Branch `feature/personalized-learning-spec` (based on `main` @ `811e775`).
PR [#62](https://github.com/architgore050/zivon/pull/62) — docs-only, opened for
independent review; the review fixes are recorded at the end of this log.

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

## Independent review (2026-11-17) — fixes applied

Reviewed with `skills/code-review/` (architecture, security, tests, docs-sync,
production-readiness), the product/systems design method, the prompting skill, and the
evals/observability skill. Product consistency held: login-required personalized learning,
no paywall/plan/payment anywhere, guest-first lessons unchanged, and D-PL-01/05/06/07/11
are labelled recommendations. Fixes applied:

1. **Open decision recorded as settled (major).** `AGENTS.md` asserted the
   personalized-learning → DeepSeek/OpenCode route as current stack while `D-PL-07` is open;
   `TIMELINE.md` called it a "recorded decision". Both now label it a recommendation pending
   D-PL-07, and a docs test pins that labelling.
2. **Voice prompt-injection mechanism was wrong (major).** The spec said the personal
   instructions ride as a second **system** message on the voice path. The Gemini transport
   (`voice/brain_client.py::_GeminiStreamFactory`) joins every system message into one
   `system_instruction`, so that would merge into the privileged prompt and elevate student
   text. The voice path now uses a delimited user-role data section; the PL path keeps the
   real second system message; the test asserts the block never enters `system_instruction`.
3. **Artifact self-navigation (major).** `sandbox` allows a frame to navigate itself and CSP
   cannot stop it, so a generated artifact could replace itself with attacker content inside
   the trusted card (phishing). Lint now rejects `location`/`window.open`/`meta refresh`/
   `<base>`; the render gate asserts the committed URL never changes; the host treats a second
   load or a foreign `event.source` as a crash.
4. **`/app` CSP vs the dedicated artifact origin (major).** The shell has no `frame-src`, so
   `default-src 'self'` governs it: same-origin mode needs no change, dedicated-origin mode
   needs exactly one `frame-src` entry. The spec previously claimed "no CSP change".
5. **Report path contract (major).** `/v1/reports` requires a non-empty `course_id` and one of
   four categories; `category=artifact` would have been rejected. Artifact reports now send
   `broken_sim`, and the `course_id` mapping is specified.
6. **`progress_event.kind` CHECK (major).** "A documented CHECK migration" was not buildable:
   SQLite cannot alter a CHECK, so 0005 rebuilds the table and Postgres swaps the constraint;
   `db/schema.py` changes in the same PR and a test inserts the new kind.
7. **Data-class ids collided (minor).** The four new classes started at C21, already used in
   `db-spec.md`; they are now C22–C25, with the CSV rows added by the PL1 PR.
8. **Missing session link (minor).** "Continue from your last session" had no column: added
   `parent_session_id` (display-only) to the table and the create body.
9. **Shared artifact cache had no cross-student test (major).** Added `T-PL-17` and
   `DET-PL03-NO-STUDENT` (canary in the weakness/instructions never reaches the builder
   prompt, the stored spec, or the document).
10. **Contract drift (minor).** `turn_index` is the message sequence (the logical turn is
    `payload.turn_no`); event names now match the register and use `L1`/`L2` privacy classes;
    rate-limit families are documented as an `abuse.py` extension; artifact rate limited to one
    per 4 turns; title length 80→120; broken cross-references (`§5.4`, `security-privacy §7`,
    event list) fixed; `evals calibrate --stage pl` (not a CLI choice) replaced; stray
    editorial question-marks and a duplicated test row removed; `auth-required` added to the
    settings state table; P2 delta recorded.
11. **ADR gap (reported, not written).** No ADR covers the runtime route, the artifact origin,
    or the child-free-text retention class. Recorded in the folder README as an implementation
    gate (`ADR-0030`, the next free number) so the gap is not silent; it stays open until the
    founder answers D-PL-05/07/09.

Evidence: `python3 -m unittest discover -s testing/docs -t .` (49 tests OK, 3 new),
`ruff check .`, `ruff format --check .`, and `scripts/check_specs.py` all green.
