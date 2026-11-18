# ADR-0030: Personalized learning — child-free-text retention, the DeepSeek/OpenCode model route, and the artifact origin

- Status: accepted (2026-11-18, founder decision)
- Date / deciders: 2026-11-18 · founder (the three decisions), recorded by the W5.5 PL1 ADR agent
- Driving requirements: `docs/specs/personalized-learning/` (README ADR gate; `decisions.md` D-PL-05/07/09; `data-and-api.md` §1/§4.8; `security-privacy.md` §4.3/§9; `interactive-artifacts.md` §5.3); the W5.5 founder correction (free prototype, no paywall, login required); `AGENTS.md` model routing; migration `0005_personalized_learning` (PL1, landed 2026-11-17)
- Scope note: this ADR records exactly the three decisions the personalized-learning spec's ADR gate names — the runtime model route and its secret boundary (`D-PL-07`), the artifact serving origin (`D-PL-09`), and the child-free-text retention class (`D-PL-05`) — plus the free-prototype scope that binds them. The remaining founder decisions (`D-PL-01/02/03/04/06/08/10/11`) stay open recommendations in `docs/specs/personalized-learning/decisions.md`.

## Context

W5.5 adds personalized learning to the product runtime: a login-required teach → check → adapt loop at `/app/personalized`, account-level personal instructions, saved conversations, and sandboxed generated artifacts. PL1 landed the data foundation on 2026-11-17 (migration `0005_personalized_learning`: the six tables, data classes C22–C25, the mastery/abuse-family CHECK widenings, the retention jobs, the D-PL-01 quota counters, and the voice-tutor personal-instruction injection). The teaching turn is an honest `503 E-PL-MODEL-DOWN` until PL2 wires the model route.

Three questions were deliberately left open by the spec because they are founder decisions, not engineering choices. The spec's README carried an explicit ADR gate: no PL1/PL2 merge treats them as decided without an accepted ADR. The founder answered all three on 2026-11-18; this record accepts them.

The context that forces each decision:

- **Children are the users.** `personalized_session`/`personalized_message` is the first child free-text store at rest in Zivon (class C23): weakness text, follow-ups, teaching transcripts, mastery evidence. ADR-0011 precludes child profiling by construction; ADR-0008 bars raw audio; ADR-0029 provides the account, deletion cascade, and export machinery this store rides on. DPDP children's-data provisions have not had counsel review — the engineering posture must be minimization, short retention, no cold copy, and explicit export/delete, with counsel review before any scale-up.
- **The runtime already has one model path with a hard SLO.** The voice tutor runs Gemma 4 26B A4B via the Gemini API under the ~4 s voice-turn budget (ADR-0017); the factory runs DeepSeek V4.1 Flash through its own OpenCode credentials at build time only. A 10–30 s structured teaching call on either path would contend with the voice SLO or blur two blast radii into one credential.
- **Artifacts are model-generated HTML that runs in the student's browser.** The sandbox contract (`interactive-artifacts.md` §5) keeps the document in an opaque origin (`sandbox="allow-scripts"`, never `allow-same-origin`; CSP `default-src 'none'`; lint + headless render gate). The remaining question is where that document is served from in production.
- **There is no paywall.** The founder correction of 2026-11-17 binds the whole wave: a pure free-tier prototype with login as the only gate. Quotas (the open recommendation `D-PL-01`) are fairness/cost counters, not entitlements; the migration contains no `plan`/`subscription`/`payment`/`entitlement` table and none may be added under this ADR.

## Options considered

**D-PL-05 — retention for child free text (sessions + messages):**

| Option | Pros | Cons |
|---|---|---|
| **90 days from last activity, hard delete, no cold copy — chosen** | supports a full term of study and resume; bounds the at-rest surface to one school term; "delete means delete" stays simple (no second copy to police); matches the shipped `retention_sessions` job | a guardian could ask why 90 days; needs the 7-day warning and export so nothing valuable vanishes silently |
| 30 days | smaller store | breaks a term-long study rhythm; more support pain; resume promise (J10) becomes unreliable |
| Keep until account deletion | simplest code | maximizes the exposure window for child free text; contradicts minimization |
| 7 days (the voice-transcript TTL) | consistency with voice | destroys resume and the teaching loop's continuity |
| 90 days + cold/analytics copy | enables longitudinal study of learning | a second copy of child free text is a new DPDP surface with no current need; rejected on principle |

**D-PL-07 — the model route for the teaching agent:**

| Option | Pros | Cons |
|---|---|---|
| **DeepSeek V4.1 Flash via the OpenCode API, through the in-process `llm_manager` OpenAI-format path, with its own runtime secret/config — chosen** | the subscription already carries the model with JSON mode, reasoning-effort control, and the `x-opencode-session` affinity header; streaming + deadlines + validation rounds come free from `llm_manager`; a separate secret isolates rotation/leak blast radius; in-process avoids a network hop for per-turn streaming | a second runtime consumer of the paid route to watch; the "internal content generation only — never user-facing" note is superseded for this surface and must be policed (no silent widening) |
| Gemma 4 / Gemini API for teaching | one fewer vendor | long structured teaching calls would contend with the 4 s voice SLO on one key; JSON-mode/effort control unproven there |
| The factory's OpenCode key/config | zero new config | shared blast radius: a factory rotation or a teaching spike takes down the other consumer |
| The llm-manager node (separate service) | one model-access chokepoint | an extra hop against a conversational deadline; a second deployment to operate; the node is scoped to factory/translator consumers |
| A different teaching model | could be cheaper/faster | a recorded routing decision with its own evaluation, not a tuning knob; no basis to reopen now |

**D-PL-09 — one conversation store and the artifact origin:**

| Option | Pros | Cons |
|---|---|---|
| **(a) One store — the lesson dock's `TUT-05` doubt history joins `personalized_session` (with `origin='lesson_dock'`) in a follow-up PR; (b) dedicated artifact origin `artifacts.<domain>` in production — chosen** | one chat store means one delete/export/retention semantics and one privacy surface; "your conversations" is one screen; a separate artifact hostname means a same-origin shell compromise cannot read artifact storage, cookies stay off the artifact host, and `frame-ancestors` can pin the embedding | (a) needs the `origin` enum widening and a dock entry point (follow-up PR, not W5.5 P0); (b) needs a deployment change (host + one `frame-src` allow-list entry) before public launch |

| Rejected alternative | Why |
|---|---|
| (a) A separate `doubt` table for the dock | two stores with two delete semantics; doubles the child-data surface the counsel review must cover |
| (b) Same-origin artifact serving forever | acceptable for local/compose (and shipped there), but a weaker boundary in production; the sandbox protects the artifact from the parent, not the parent from a future artifact-serving bug |
| (b) Third-party/static host for artifacts | a second copy of generated content to purge; the signed-URL route against the same backend is simpler and keeps the refcount authoritative |

## Decision

1. **D-PL-05 (accepted): personalized chats are retained 90 days from last activity, hard-deleted, with no cold copy, explicit export/delete, and counsel review before any scale-up.** Retention runs from `personalized_session.last_turn_at` (never `updated_at`); deletion cascades messages and is unrecoverable by design; artifacts follow their own classes (30 days unreferenced, 7 days failed; usage 90 days — all in the PL1 retention jobs and `ZIVON_PERSONALIZED_RETENTION_*` config). The hub warns at day 83 ("deletes in 7 days · export it"). Export and delete are first-class owner operations; account deletion cascades the store (ADR-0029 tombstone posture). No cold, analytics, or backup copy of session/message text may be created. Counsel review of the child free-text posture (DPDP children's provisions, vendor retention terms) is a blocker for opening personalized learning beyond the founder-supervised prototype cohort — not for the cohort itself.
2. **D-PL-07 (accepted): the personalized-learning teaching agent runs on DeepSeek V4.1 Flash via the OpenCode API, called through the in-process `llm_manager` OpenAI-format path (the library, not the llm-manager node), with its own runtime secret and config** (`ZIVON_PERSONALIZED_*`; the API key lives in the `zivon-personalized-env` K8s Secret, mounted only into the backend; `x-opencode-session` is an opaque per-session affinity id, not a credential). Three model paths stay separate — Gemini (voice tutor, ADR-0017), OpenCode-personalized (runtime teaching), OpenCode-factory (build-time) — and no path may use another's credentials or config. **No paywall: the surface is free, login-required, with no plan/subscription/payment/entitlement logic anywhere.** The teaching turn ships no model call outside this route (PL1 keeps the honest `503 E-PL-MODEL-DOWN` until PL2). This supersedes the "internal content generation only — never user-facing" routing note for this surface only, as a recorded founder decision.
3. **D-PL-09 (accepted): one conversation store later; a dedicated artifact origin in production.** (a) The lesson dock's saved doubts merge into `personalized_session` with `origin='lesson_dock'` in a follow-up PR (not W5.5 P0); until it lands, this feature owns only the personalized store. (b) Production serves artifacts from a dedicated origin (`artifacts.<domain>`, same backend, separate hostname), issued as 10-minute signed URLs after the caller's reference check (the host-only session cookie does not follow to the artifact host); same-origin serving stays acceptable for local/compose. **Artifacts remain sandboxed in every mode** — opaque origin, `allow-scripts` only, strict CSP, lint + render gate — and **must never share the app origin's privileges**; the app shell's only concession is one `frame-src` allow-list entry, never a `script-src`/`connect-src` relaxation.
4. **Free-prototype scope.** All three decisions serve the W5.5 founder correction: free access, login required, no payments. Quota/abuse counters (the open `D-PL-01` recommendations shipped in PL1 config) bound cost; the kill switch (`ZIVON_PERSONALIZED_ENABLED=false`) keeps the feature honest-degraded without touching lessons, practice, tests, or voice.

## Consequences

Easier: the privacy posture for child free text is fixed and testable (TTL job + cascade + export + no-copy); the route can be built in PL2 against a documented config surface with an isolated secret; the artifact boundary is a deployment task with a known shape; the docs contract tests and the ADR gate now agree.

Harder / accepted trade-offs:

- **A second runtime consumer of the paid OpenCode route.** The subscription is shared with build-time generation; quotas, caching, the usage ledger (`personalized_usage`), and the kill switch are the containment. Model-choice coupling to record: prompts and the decide/teach/artifact payload contracts (`agent-and-rag.md`), the `EV-PL-001…005` eval sets and goldens, the latency budgets (`D-PL-06`, still open), and the JSON-mode/reasoning-effort configuration are all tuned to this model. Reversal is cheap in code (a config + secret swap through the same `llm_manager` seam) but expensive in evidence (new goldens, latency numbers, and vendor-terms review), so a swap is a recorded founder decision, never a drive-by.
- **The route is in-process, so the backend carries a model secret.** Boot must refuse to enable the feature without base URL/key (loud, no silent default); the secret is never logged, printed, or baked. If the backend must become model-key-free, the node path reopens (see triggers).
- **90-day retention is an accepted privacy risk, not a legal clearance.** Counsel has not reviewed the DPDP children's-data posture; until counsel does, scale-up beyond the prototype cohort is blocked and no new free-text field may join the store without reopening this ADR.
- **The dedicated artifact origin is not yet deployed.** Same-origin + opaque-origin sandbox is the accepted interim posture (recorded, not silent); public launch requires the origin, the signed-URL path, and the one CSP entry to have shipped.
- **The dock merge (D-PL-09a) lands later**, so there is a window in which the dock has no saved-doubt history; that is the pre-existing product state, not a regression.

Monitor: retention job delete counts and any skipped deletion; `personalized_usage` daily totals vs the global caps; p50/p90 first-token latency once PL2 measures the route; secret-scan results for `ZIVON_PERSONALIZED_API_KEY`; artifact lint/render failure rates; quota-exhausted and `E-PL-MODEL-DOWN` rates.

## Revisit trigger (measurable)

- **Counsel answers the DPDP children's-data review**, or the founder opens personalized learning beyond the prototype cohort → re-examine the retention window and any copy obligations before the opening (D-PL-05).
- **A guardian deletion/retention complaint** or a deletion-job failure that leaves child rows → retention posture reopens; the deletion ledger records the incident.
- **A second runtime consumer of the same route, or a requirement that the backend become model-key-free** → move to the llm-manager node (a new ADR; the `D-PL-07` trigger already named in `agent-and-rag.md` §7.3).
- **Cost/latency breach after 100 real turns** (p90 > 20 s, or the subscription's usage window is hit repeatedly) → recorded routing or budget decision (`D-PL-06`), not a silent tuning change.
- **Provider terms change** (training/retention of prompts) before scale-up → vendor review reopens the route decision (`T-PL-15`).
- **The dock-history PR ships** → confirm the one-store merge (`D-PL-09a`); **before public launch** → the dedicated artifact origin must be live (`D-PL-09b`).

## References

- `docs/specs/personalized-learning/README.md` (the ADR gate this record satisfies), `decisions.md` (D-PL-05/07/09 closed here), `data-and-api.md` §1–§2 (classes C22–C25, retention jobs), §4.8 (artifact fetch/signed URL), `security-privacy.md` §4.3/§9 (child posture, counsel flag), `interactive-artifacts.md` §5 (sandbox + origin strategy), `agent-and-rag.md` §7 (route configuration)
- Migration `0005_personalized_learning` (`db/schema_personalized.py`, `alembic/versions/0005_personalized_learning.py`) — the six tables, the CHECK widenings, the cascade; `backend/personalized/retention.py` — the TTL jobs this ADR's retention decision executes
- `docs/backend/adr/0029-accounts-and-session-cookies.md` (account/deletion machinery), `docs/backend/adr/0011-no-child-profiling-by-construction.md`, `docs/backend/adr/0008-raw-audio-never-stored.md`, `docs/backend/adr/0017-brain-serving-path-gemma-gemini-api.md` (the voice route kept separate), `docs/backend/adr/0028-eval-judge-model-and-calibration.md` (the factory-side judge route, unchanged)
- `AGENTS.md` model-routing table (the personalized row flips from "recommended/open" to accepted in the same patch); `TIMELINE.md` W5.5 section
- `docs/backend/backend-spec.md` §6.5 (PL1 surface), §14 (ADR index); `docs/backend/db-spec.md` §4.20; `docs/backend/data-classification.csv` C22–C25
- `docs/compliance/` (blueprint-only rule unaffected; child-data/DPDP is out of scope there and carried here as the counsel flag)
