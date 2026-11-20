# Workstreams — PL1…PL5

Status: **PL1 implemented (2026-11-17); PL2 implemented (2026-11-18); PL3
implemented (2026-11-18); PL4 implemented (2026-11-19,
`docs/specs/frontend/personalized.md` is the landed contract); PL5's evals/security
slice is in review (2026-11-19 — `EV-PL-001…005` green key-free, the security
matrix tests, the key-free merge gate; the founder-local judge run stays open).**
PL3 landed against this
document's decide contract as the internal generation interface
(`ensure_artifact` + the `ArtifactBuilder` seam on
`app.state.personalized_artifact_builder`); PL2 wires it into the teaching turn.
This file is the
execution split for **W5.5** in [`TIMELINE.md`](../../../TIMELINE.md). Each
workstream is one agent-sized PR series; a PR never edits another workstream's
owned files without the owner's review.

Ordering rule: **PL1 and PL2 can start in parallel** (PL1 owns persistence/auth
and a fake agent; PL2 owns the agent/RAG behind an interface). **PL3 starts
after PL2's turn contract freezes**, **PL4 starts after PL1's APIs freeze**
(mock-friendly), **PL5 runs continuously** and is the merge gate. No workstream
touches the frozen lesson renderer, the factory stages, or the voice protocol.

---

## 1. Ownership map

| Workstream | Owns | Depends on | Blocks |
|---|---|---|---|
| **PL1** data/auth/preferences/chat/quota | `db/schema_personalized.py`, `db/schema.py` registry row, `db/migrate.py` revision, `backend/personalized/store.py`, `backend/personalized/router.py` (non-turn endpoints), `backend/personalized/quota.py`, `backend/personalized/preferences.py`, migration tests, `backend/privacy.py` cascade/retention | F0 accounts (ADR-0029), F0C shell, `backend/abuse.py`, `guard/` pattern | PL2 (persistence), PL4 (APIs) |
| **PL2** RAG/agent/DeepSeek/teaching loop | `backend/personalized/agent.py`, `prompts.py`, `state.py`, `rag.py`, `personalization.py`, `turn_router.py` (SSE), `scripts/build_personalized_index.py`, `runs/personalized-index/` build output (gitignored, on the sources PVC), agent tests | PL1 tables; `llm_manager`; P2 bank; lesson manifests; `factory/design.py`/`lint.py` reuse | PL3 (turn/artifact contract), PL4 (streaming), PL5 (evals 001/002) |
| **PL3** artifact generation/sandbox/review | `backend/personalized/artifacts.py`, `artifact_prompt.py`, `artifact_sandbox.py` (render gate), `evals/goldens/personalized/artifacts/`, the viewer template/JS (`web/templates/app/partials/artifact_viewer.html`, `frontend/assets/personalized-artifact.js`) | PL2 decide contract; `factory/interactive.py` skeleton; `factory/lint.py`; Playwright dev dependency | PL4 (viewer), PL5 (eval 003) |
| **PL4** frontend settings/hub/session/artifact viewer/history | `web/routes/personalized.py` (HTML), `web/templates/app/personalized_hub.html`, `personalized_session.html`, `web/templates/app/partials/personal_instructions.html`, one include line in `web/templates/app/settings.html` (F2 review), `frontend/assets/personalized.css`, `personalized.js`, `web/nav.py` entry, screen-state tests | PL1 APIs + PL2 stream contract; F0C shell; design doctrine; founder visual verdict | PL5 (UI states) |
| **PL5** evals/security/QA | `evals/cards/EV-PL-001…005.yaml`, `evals/checkers/personalized_checks.py`, `evals/goldens/personalized/*`, `testing/backend/test_personalized_*.py` security matrix, `testing/frontend/test_personalized_states.py`, `testing/docs/test_personalized_learning_spec.py`, the wave evidence | PL1–PL4 | the merge gate |

Shared files (one owner, review required):

| File | Owner | Who else may request a change |
|---|---|---|
| `db/schema.py` (`ALL_TABLES` + imports) | PL1 | PL5 (registry assertions) |
| `db/migrate.py` | PL1 | — |
| `backend/privacy.py` | PL1 | PL5 (deletion tests) |
| `web/nav.py` | PL4 | — |
| `web/templates/app/settings.html` | F2 → PL4 adds a partial include | PL4 (one line + partial) |
| `voice/brain_client.py`, `voice/ws_api.py` | PL2 (prompt injection) | voice owner review; no protocol change |
| `frontend/assets/zivon.*` | frontend kit owner | **never edited** by PL (lesson kit) |
| `.github/workflows/ci.yml` | CI owner | **not edited**; the existing `testing/docs` and `eval-smoke` loops pick the new suites up |
| `k8s/` | deployment owner | PL1/PL2 add env/secret keys only if a deployment PR is opened; the spec lists the keys |

---

## 2. PL1 — data, auth, preferences, chats, quota

**Goal:** the persistence and non-model API surface, with a fake agent seam so
the whole feature can be tested before the model route exists.

**Deliverables**

1. Migration `0005_personalized_learning` (six tables + the `progress_event.kind` CHECK,
   which needs the SQLite table rebuild and the Postgres constraint swap in
   `data-and-api.md` §2.7), down migration, SQLite/Postgres tests.
2. `backend/personalized/store.py`: owner-scoped CRUD, idempotency, export,
   hard delete, artifact refcount queries.
3. `backend/personalized/preferences.py`: normalize/validate/save/clear; the
   shared `personalization.py` helper (with PL2) including `SAFETY_CORE` and
   `personal_block`.
4. `backend/personalized/quota.py`: IST period, atomic reserve/actualize/release
   for user+global in one transaction, usage ledger writes.
5. Routes: preferences (`API-PL-01…03`), sessions (`05…09`, `12`, `15`), with
   auth/CSRF/rate limits/error envelope. The turn endpoint (`10`) is a stub that
   calls an injected `TurnEngine` protocol; PL2 fills it.
6. `backend/privacy.py`: cascade + retention jobs.
7. Tests: migration, preferences, IDOR, CSRF, delete/export, quota race,
   rate-limit, logging canary.

**Exit gate:** the API works end-to-end against a fake agent; no key, no
network; `EV-PL-004/005` smoke checks green; the migration chain is green on
SQLite and Postgres.

**Risks:** quota atomicity (solved by copying `guard/service.py` and committing
both rows together); retention deleting a live session (use `last_turn_at`, not
`updated_at`).

---

## 3. PL2 — RAG, agent, DeepSeek, teaching loop

**Goal:** the teaching brain and the stream, behind the PL1 interface. **Status: implemented 2026-11-18** (`state.py`, `prompts.py`, `rag.py`, `agent.py`, `turn_router.py`, `bank.py`, `scripts/build_personalized_index.py`; eval cards EV-PL-001/002 + checkers + goldens; the real-model manual run of §9's exit gate is still pending).

**Deliverables**

1. `state.py`: the state machine + invariants (`agent-and-rag.md` §2), pure
   functions, deterministic tests, no model import.
2. `prompts.py`: `SAFETY_CORE`, `TEACH_SYSTEM`, `DECIDE_SYSTEM`, the personal
   block, the language line, the citation contract; the parity test.
3. `rag.py`: index load/validate, scoped retrieval, hybrid rerank, lexical
   fallback, citation resolution, versioning; `scripts/build_personalized_index.py`
   (idempotent, manifest + hashes, refuses to overwrite a newer index without
   `--force`).
4. `agent.py`: `LLMManager` config (base/model/key/headers/timeouts/
   reasoning effort), the two-call turn, scoring adapter, error mapping,
   usage rows; the `x-opencode-session` header per session.
5. `turn_router.py`: SSE endpoint (`API-PL-10`), idempotent replay, JSON
   fallback, the event catalogue, the "in-progress turn" lock.
6. `voice/` injection: `BrainRequest.personal_block`, `build_messages` order,
   session-start account resolution, the 60 s cache, the enable flag.
7. Tests: state machine, prompt assembly, retrieval with a fixture embedder,
   citation resolution, SSE event sequence with a fake stream, error mapping,
   parity, voice injection include/exclude.

**Exit gate:** one chapter teaches end-to-end with a real model in a manual run;
`EV-PL-001/002` smoke green; the fake-model test suite green; p50/p90 latency
recorded in the PR.

**Risks:** two-call latency (fallback: single JSON call — `PL-C-006` revisit);
DeepSeek JSON-mode quirk (prompt contains "JSON"; validation rounds); first-token
time on the OpenCode route (measure, then tune effort/deadline).

---

## 4. PL3 — artifacts

**Status: implemented (2026-11-18).** Files:
`backend/personalized/{artifacts,artifact_prompt,artifact_sandbox,artifact_router}.py`,
`web/templates/app/partials/artifact_viewer.html`,
`frontend/assets/personalized-artifact.js`,
`evals/cards/EV-PL-003.yaml`,
`evals/checkers/personalized_checks.py`,
`evals/goldens/personalized/artifacts/`. Config: `ZIVON_PERSONALIZED_*`
(D-PL-07 route; builds fail-closed off until the route is configured).
Exit-gate evidence: the golden artifact passes lint + the render gate
(0 console errors, 0 network attempts, ~60 fps median, `ready` in ms), all 7
seeded defects fail with their expected lint rules, the red-team probe cannot
escape the opaque-origin sandbox, cache/refcount/purge and the API contract
are unit-tested, and `EV-PL-003` passes the smoke suite key-free.

**Goal:** the safest possible generated visual, with a fallback that always
works.

**Deliverables**

1. `artifact_prompt.py`: the Visual Builder prompt (doctrine + palette + claims
   + skeleton + output contract), the spec validator, the retry loop with lint
   feedback.
2. `artifacts.py`: content hash, cache lookup/store, status machine, refcount,
   purge hook, the `fallback` payload.
3. `artifact_sandbox.py`: the Playwright render gate (network aborted, console
   errors, overflow, fps, reduced motion) and the seeded-defect runner.
4. Viewer: `web/templates/app/partials/artifact_viewer.html` +
   `frontend/assets/personalized-artifact.js` (iframe attributes, postMessage
   validation, reload/expand/pause/report, watchdog).
5. Reuse `factory/lint.py` + `factory/design.py`; add the artifact-specific
   rules (forms/storage/parent/top-nav) as a thin wrapper, not a fork.
6. Tests + goldens: `EV-PL-003` deterministic + headless.

**Exit gate:** the golden artifact renders; all 7 seeded defects fail as
expected; the red-team artifact cannot escape; a forced failure shows the
fallback; cache hit costs zero model calls.

**Risks:** Playwright in the backend image (keep it a dev/test dependency, not
a runtime install; the render gate runs in CI and the build job, not on every
student request); iframe focus/Escape behaviour (manual a11y test).

---

## 5. PL4 — frontend

**Status: implemented 2026-11-19.** Files:
`web/routes/personalized.py` (hub/session/start/end/delete + the
`/app/settings/instructions` route), `web/personalized_views.py`,
`web/templates/app/personalized_hub.html`, `personalized_session.html`,
`app/partials/personal_instructions.html`, the one-line include + assets in
`app/settings.html`, the privacy-page row, the `Learn` nav entry
(`web/nav.py`), `frontend/assets/personalized.css`, `frontend/assets/personalized.js`.
The landed contract and the full state matrix:
`docs/specs/frontend/personalized.md`. Tests:
`testing/backend/test_personalized_web_pages.py`,
`testing/frontend/test_personalized_assets.py`,
`testing/frontend/test_personalized_session_island.py`. Deliberate
interpretations recorded there: the chapter picker is one native select
with per-class optgroups (the sketch's class tabs carried no extra
capability), and the session turn loop is island-only — a server-side
answer route would have duplicated PL2's admission order.

**Goal:** the hub, the session, the settings section, and the artifact viewer,
in the Field Notes base system, with every state.

**Deliverables**

1. `web/routes/personalized.py` + templates: hub, session, history rows,
   quota strip, end/summary.
2. Settings partial + one include line in `settings.html` (F2 review); the
   page's existing CSRF form pattern; the field's counter/validation copy.
3. `personalized.js`: the SSE client (fetch + `ReadableStream`, CSRF header,
   abort, reconnect-once), the check submit, the artifact postMessage bridge,
   the live region. No framework, no SPA, no inline script/style.
4. `personalized.css`: base §1–§9 cards, check chips, transcript rhythm,
   artifact box, 360 px layout, focus, reduced motion.
5. `web/nav.py` entry (`/app/personalized`, label "Learn"); the dashboard quick
   action only if F3's owner adds it in the same PR.
6. Screen-state tests for all 11 states per screen (`SCR-PL-01…05`), a11y
   (keyboard, labels, live regions), perf (soft budget), and the founder visual
   verdict record.

**Exit gate:** the founder's visual verdict is recorded (same-agent protocol);
all states reachable in tests; the page works at 360 px; no §10 device on the
app surface; a signed-in student can complete a session with the fake agent and
the real agent.

**Risks:** the session screen has no doctrine section (base §1–§9 only) — if
the founder wants the notebook look, that is a DCR (`D-PL-10`), not an
improvisation; a big transcript needs windowing (load earlier, not virtualize in
R1).

---

## 6. PL5 — evals, security, QA

**Status: the evals/security slice landed (2026-11-19):** cards/checkers/
goldens `EV-PL-001…005` (all green key-free, `llm_judge: null` with the
full-suite judge gap documented in `evals.md` §10), the 18 deterministic
security checkers, the golden fixtures (`instructions/` 15, `quota/` 6
scenarios + tenant/CSRF/next), the security matrix tests
(`testing/backend/test_personalized_security.py`), the checker
fault-detection tests (`testing/evals/test_personalized_eval_cards.py`), the
registry pins (25 cards, 72 checks), and the key-free merge gate
(`scripts/pl-smoke.sh`). **Still open in PL5:** the founder-local full-suite
judge run + the two judge authorships (§10 of evals.md), the PL4 screen-state
test file (`testing/frontend/test_personalized_states.py` lands with PL4's
frontend), and the wave-evidence review pass.

**Goal:** the merge gate and the evidence.

**Deliverables**

1. Cards/checkers/goldens `EV-PL-001…005` per [`evals.md`](evals.md).
2. The security matrix tests (`security-privacy.md` §10) in `testing/backend/`
   and `testing/frontend/`.
3. The docs contract test
   [`testing/docs/test_personalized_learning_spec.py`](../../../testing/docs/test_personalized_learning_spec.py)
   (already in this PR) kept green as the spec evolves.
4. The wave evidence: smoke + full run JSON under `runs/evals/<date>/`, the
   seeded-defect table, the founder verdict link, the latency/cost numbers.
5. The review pass with `skills/code-review/` lenses: architecture,
   implementation, security, tests, docs-sync, production-readiness,
   content-quality (builder prompt + teaching prompt).

**Exit gate:** W5.5 exit gate in [`README.md`](README.md) §Status, all six
items; no blocker findings; docs current.

---

## 7. Integration with existing surfaces

| Surface | Integration | Owner of the edit |
|---|---|---|
| `/app` shell + guard + CSP | new pages under the same guard. **Same-origin mode needs no CSP change**: `/app`'s `default-src 'self'` already governs `frame-src`, so the same-origin artifact URL is allowed, and `connect-src 'self'` already allows the SSE fetch. **Dedicated-origin mode needs one allow-list entry** — `frame-src https://artifacts.<domain>` (D-PL-09b) — which is an addition to the frame allow-list, not a relaxation of `script-src`/`connect-src` | PL4 (uses the contract), deployment (b) |
| Settings (`/app/settings`) | one included partial + route for the preferences form; the email/privacy rules unchanged | PL4 (partial), F2 (review) |
| Lesson dock / voice prompt | `BrainRequest.personal_block` + the account resolution; no protocol change | PL2 (voice review) |
| Lesson shell (F4) | one CTA on the lesson end (`Learn this chapter` → `/app/personalized?chapter=<id>`) and one on the chapter page; the lesson page itself stays static and guest-readable | F4 owner (link), PL4 (route) |
| Progress (F3) | mastery emitted as `progress_event(kind='personalized_mastery')`; F3 reads it, no new store | PL2 (emit), F3 (read) |
| Catalogue | `/v1/catalog` + index coverage for the picker; no catalogue schema change | PL1/PL2 (read-only) |
| P2 bank | bank-first selection; generated items never written to `question_bank` | PL2 |
| Admin dashboard | usage/artifact/quota panels are a follow-up (PL1 emits the data; the dashboard PR owns the UI) | PL1 (data), dashboard owner (UI) |
| Report path | artifact and turn reports reuse `/v1/reports` + `problem_report` with the constraints in `data-and-api.md` §4.11 (`category='broken_sim'`, a non-empty `course_id`) | PL4 (link), existing API |
| Privacy page | one row for personalized sessions + delete/export links | PL4 |
| CI | no workflow edit; `testing/docs`, `testing/backend`, `testing/frontend`, `eval-smoke` already pick the suites up | PL5 (verifies) |

---

## 8. Sequencing (a realistic W5.5)

```
week 1   PL1 schema+prefs+quota+stub APIs      PL2 state machine+prompts+RAG index
week 2   PL1 chat/export/delete+security tests PL2 agent+SSE (fake model)   PL4 hub/session skeleton
week 3   PL2 real-model tuning + voice inject  PL3 artifacts+viewer         PL4 settings+states
week 4   PL5 evals full + security matrix + founder verdict + wave evidence
```

Estimates are [ASSUMPTION]; the wave can ship with PL3 limited to one artifact
kind (simulation) and PL4's history search deferred.

---

## 9. Definition of done (per workstream)

- PL1: migration green; owner-scoped APIs; quota race test; delete/export test.
- PL2: state machine deterministic; one real session end-to-end; citations on
  every teaching turn; latency recorded.
- PL3: golden artifact + 7 defects + sandbox red-team + fallback.
- PL4: 11 states per screen; keyboard/screen-reader pass; 360 px; founder
  verdict.
- PL5: smoke green in CI; full run recorded; no blocker findings; docs current.

A PR that adds a model call without a quota reservation, a session endpoint
without owner scoping, or an artifact without lint is a blocker regardless of
tests.
