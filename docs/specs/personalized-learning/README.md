# `docs/specs/personalized-learning/` — personalized learning + interactive artifacts

Status: **spec complete; PL1 implemented (2026-11-17) and PL2 implemented (2026-11-18);
PL3 in review, PL4–PL5 not started (2026-11-19).** This folder is the
buildable contract for the login-required personalized-learning surface, the
account-level personal instructions, saved conversations, and the sandboxed
interactive artifacts the teaching agent may generate. Product code lands only
through the workstreams in [`workstreams.md`](workstreams.md).

Founder correction that binds the whole folder (2026-11-17): **there is no
paywall and no payment in this prototype.** It is a pure free-tier prototype for
real student testing, and **login is required**. Rate limits and quotas protect
cost and fairness; there is no entitlement, plan, or subscription gate. Any
`plan` / `subscription` / `payment` / `entitlement` table or pricing change is
out of scope.

## Why this folder exists

The frozen full-frontend plan (2026-11-13) predates this feature. It names a
doubt tutor (`TUT-01…09`), doubt history (`TUT-05`), and a doubts screen
(`REQUIREMENTS.md` §10.19), but it does not specify a guided teaching loop, an
account-level personal-instruction field, or runtime-generated interactive
artifacts. This folder is the **feature-decision addendum + implementation
contract** for that extension. It does not edit
[`docs/product/features.md`](../../product/features.md) wholesale; the
decision-log addendum and feature cards live here and extend that document.

The extension preserves the repo's hard rules:

- Core (read / simulate / check) keeps working with personalization fully off
  (layer independence).
- Children are the users: private-by-default, no raw audio, no inferred
  behavioural profile, no dark patterns, deletion and export first-class.
- Content is grounded in NCERT / public-domain material and the P2 question
  bank; **no verbatim CBSE paper content** (`DEC-COMP-001` stays in force).
- Every model call goes through [`llm_manager/`](../../../llm_manager/README.md);
  no hand-rolled inference HTTP.
- The visual authority stays [`docs/frontend/design-doctrine.md`](../../frontend/design-doctrine.md);
  a screen that needs lesson-page devices files a DCR, it does not improvise.

## Scope

In scope:

1. **Personal instructions** — an account-level, student-authored text field in
   `/app/settings`, injected (lower priority than safety) into the lesson-page
   voice tutor and into personalized learning.
2. **Personalized learning** — a login-required `/app/personalized` hub and a
   teaching session: choose a chapter/concept or describe a weakness in free
   text; a short diagnostic; a teach → check → adapt loop; progressively harder
   questions up to board-style difficulty; per-concept mastery evidence; resume
   and history. "Coverage" means every concept of the chosen chapter is taught or
   explicitly skipped (which chapters exist is the index-coverage rule, D-PL-02).
3. **Saved conversations** — titled, chapter-tagged sessions with timestamps,
   resume, delete, and JSON export. Text/artifacts only; no raw audio.
4. **Interactive artifacts** — a self-contained HTML/JS simulation or diagram
   generated for a teaching turn, shown in a sandboxed viewer with a text /
   diagram fallback.
5. **Free-tier controls** — login required, per-user and global quotas, rate
   limits, artifact caching, cost logging, and an honest quota-exhausted state.
6. **Quality and security contracts** — the teaching state machine, the RAG
   contract, the threat model, eval cards `EV-PL-001…005`, and the PL1–PL5
   workstream split.

## Non-goals

- No payments, pricing page, Pro tier, trial, plan table, or entitlement logic.
- No general-purpose chat, coding help, or subjects other than academic Physics
  (Class 9–12, launch content Class 9/10).
- No voice input inside personalized learning in R1 (text-first); voice
  read-aloud is deferred (decision `PL-C-013`).
- No parent/teacher account, sharing, public profile, or public chat links
  (frozen plan #7; `PL-C-016`, `PL-C-017`).
- No inferred cross-session learner profile or difficulty model (`T5` stays
  killed; `PL-C-015`). Stored mastery is explicit evidence the student can see,
  export, and delete.
- No student-uploaded HTML, no model tool use, no web browsing, no arbitrary
  code execution (`PL-C-019`, `PL-C-020`).
- No verbatim CBSE questions in teaching or checks (`DEC-COMP-001`).
- No service-worker/offline authoring; the saved transcript is readable offline
  only from the browser cache and is labelled as such.

## Actors and jobs

| Actor | Description | Jobs served |
|---|---|---|
| **Student** (primary) | Class 9–12 Physics learner, signed in, often on a low-end Android phone in a shared room | `J1` ask a doubt · `J3` test myself · `J5` continue across sittings · **`J8`** "I know the chapter is weak but not which concept — diagnose me and lead me" · **`J9`** "build the visual for *my* confusion" |
| **Guardian** (secondary) | Allows a minor to use the site; reads the privacy copy | `J6` what is collected, how to erase it |
| **Content-ops admin** | Founder/operator watching cost, quality and abuse | `J7` one view of sessions, quota burn, artifact failures |

New jobs `J8`–`J10` and metrics `M8`–`M14` are defined in
[`feature-addendum.md`](feature-addendum.md) §3. They extend, not replace,
`docs/product/features.md` §2.

## Read order

| # | File | Read it for |
|---|---|---|
| 1 | [`README.md`](README.md) | Scope, actors, non-goals, status (this file) |
| 2 | [`feature-addendum.md`](feature-addendum.md) | The decision-log addendum, feature cards `PL-F1…F6`, jobs, metrics, tension deltas, UI element inventory |
| 3 | [`spec.md`](spec.md) | The full product flow: personal instructions, hub, diagnostic, teaching loop, chats, artifacts, quotas, and every screen state |
| 4 | [`agent-and-rag.md`](agent-and-rag.md) | Teaching state machine, prompt contract, two-phase turn, RAG corpus/index/retrieval/citations, DeepSeek routing, injection defense, eval hooks |
| 5 | [`interactive-artifacts.md`](interactive-artifacts.md) | Artifact spec/generation, sandbox + CSP, validation/review, cache/versioning/fallback |
| 6 | [`data-and-api.md`](data-and-api.md) | Tables, columns, indexes, retention, endpoints, auth/CSRF/quota, voice-prompt change |
| 7 | [`security-privacy.md`](security-privacy.md) | Threat model, controls, redaction rules, deletion, and the tests that prove each control |
| 8 | [`evals.md`](evals.md) | `EV-PL-001…005`: deterministic checkers, goldens, judges, log paths, cost |
| 9 | [`workstreams.md`](workstreams.md) | PL1–PL5 ownership, file boundaries, dependencies, integration points |
| 10 | [`decisions.md`](decisions.md) | Founder decisions — D-PL-05/07/09 accepted via ADR-0030 (2026-11-18); the rest open with recommendations, owners, and triggers |

Machine-readable companion: [`decision-log-addendum.csv`](decision-log-addendum.csv)
(same columns as `docs/product/decision-log.csv`).

## Dependencies on existing specs

| Area | Authority | What this folder consumes |
|---|---|---|
| Accounts, sessions, CSRF, deletion | [`docs/backend/adr/0029`](../../backend/adr/0029-accounts-and-session-cookies.md), [`identity-settings.md`](../frontend/identity-settings.md) | `users`, `auth_session`, `AuthService`, cookie/CSRF rules |
| App shell, guard, CSP, headers | [`web-shell.md`](../frontend/web-shell.md) | `/app` mount, `ShellContext`, 303-to-login guard, `no-store`/`noindex`, CSP string |
| Lesson content, blocks, source packs | [`architecture.md`](../../content-factory/architecture.md), [`blocks-schema.md`](../../content-factory/blocks-schema.md) | block types, manifest shape, citation/source-pack shape |
| Assessment bank | [`assessment.md`](../../content-factory/assessment.md), [`db-spec.md`](../../backend/db-spec.md) §4.19 | `question_bank`, concept ids, difficulty/marks, language variants |
| Voice tutor prompt + session | [`spec.md`](../voice-agent/spec.md) §6–§8, [`ws-contract.md`](../voice-agent/ws-contract.md) | system prompt, history window, credit guard, WS handshake |
| Model-call discipline | [`llm_manager/README.md`](../../../llm_manager/README.md) | streaming, inactivity/deadline, validation rounds, extra headers |
| Visual language | [`design-doctrine.md`](../../frontend/design-doctrine.md) §0–§10 | §1–§9 app surfaces; §10 is lesson-only |
| Compliance | [`docs/compliance/`](../../compliance/README.md) | blueprint-only rule, non-affiliation copy |
| Logging + evals | [`docs/specs/observability/`](../observability/README.md), [`docs/specs/evals/`](../evals/README.md) | `log_event` contract, instrumentation map, card/golden/store formats |

## Status and exit gate

**Spec status:** complete for build; PL1 implemented (2026-11-17), PL2 implemented
(2026-11-18), PL3 in review, PL4–PL5 not started (2026-11-19).
**Wave:** **W5.5** (post-W4, before W5 integration), recorded in
[`TIMELINE.md`](../../../TIMELINE.md).

**ADR gate: satisfied (2026-11-18).** [`ADR-0030`](../../backend/adr/0030-personalized-learning.md)
is accepted and records exactly what this gate required: (a) the runtime model route and its
secret boundary (`D-PL-07` — DeepSeek V4.1 Flash via the OpenCode API through the in-process
`llm_manager` OpenAI-format path, its own runtime secret, no paywall, login required), (b) the
artifact serving origin (`D-PL-09` — dedicated origin in production, same-origin acceptable for
local/compose, artifacts always sandboxed and never sharing the app origin), and (c) the
child-free-text retention class (`D-PL-05` — 90 days from last activity, no cold copy, explicit
export/delete, counsel review before any scale-up). The `D-PL-05/07/09` rows in
[`decisions.md`](decisions.md) are closed with that reference; the remaining founder decisions
stay open recommendations until the founder closes them. This folder still decides and
specifies everything else; it does not stand in for an ADR, and no open `D-PL-*` row may be
recorded as decided while it stays open.

Exit gate for W5.5 (the definition of done for the wave):

1. A signed-in Class 10 student starts from a free-text weakness, completes a
   3-question diagnostic, is taught a concept, answers a check, is adapted
   after a wrong answer, and reaches at least one L3 item — with citations on
   every teaching turn and mastery evidence visible at the end.
2. The same session resumes after a reload and after a sign-out/sign-in on the
   same account; history lists, exports, and deletes it.
3. An artifact renders in the sandbox with zero console errors, zero network
   requests, 360 px no-overflow, and a text fallback when the build is forced
   to fail.
4. A personal instruction saved in settings appears in the lesson-page tutor
   prompt (verified by a prompt-assembly test) and cannot override safety or
   grounding (verified by `EV-PL-004`).
5. `EV-PL-001…005` run deterministically in CI (`--suite smoke`) and the full
   suite records a run under `runs/evals/<date>/`.
6. Quotas hit their honest states: per-user exhausted, global exhausted, rate
   limited, and a cache hit that costs zero model calls.

## Folder conventions

- IDs are stable. `PL-F#` feature cards, `PL-C-###` decision-log rows,
  `EL-PL-##-###` elements, `SCR-PL-##` screens, `API-PL-##` endpoints,
  `EVT-PL-##` events, `DET-PL##` checker ids, `D-PL-##` open decisions.
- Evidence tags follow the repo convention: `[STRONG]`, `[MODERATE]`,
  `[WEAK]`, `[ASSUMPTION]`.
- Any number not measured in-repo is tagged `[ASSUMPTION]` and carries a
  calibration owner in [`decisions.md`](decisions.md).
- The docs contract test
  [`testing/docs/test_personalized_learning_spec.py`](../../../testing/docs/test_personalized_learning_spec.py)
  pins the required files, headings, decision recommendations, eval ids,
  workstreams, links, and the no-paywall rule. It runs in the existing
  path-guarded `testing/docs` CI loop; no workflow edit is needed.
