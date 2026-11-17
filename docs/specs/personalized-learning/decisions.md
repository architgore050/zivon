# Open founder decisions

Status: **11 open decisions, each with a recommendation (2026-11-17).**
Nothing in this list blocks writing the spec; PL1/PL2 can start on the
recommended defaults. A decision that changes a recommended number is a config
change, not a rewrite; one that changes the model route or the retention
posture is a recorded founder decision (also noted in `TIMELINE.md`).

Format: each decision states the question, the recommendation, why, the
alternatives, what it changes, who owns it, and the trigger to revisit. A
decision is **closed** when the founder's answer is written here and, when it
changes product behaviour, in `docs/product/decision-log.csv` or
`TIMELINE.md`.

Legend: `open — recommended` means the build proceeds on the recommendation
until the founder says otherwise.

---

## D-PL-01 — Free-tier quota numbers

**Question:** what are the per-user and global limits for personalized learning
in the free prototype?

**Recommendation:** 40 teaching turns/user/day; 6 turns/min; 2 concurrent turns;
5 new sessions/user/day; 12 artifact builds/user/day and 4 per session; 20
requests/min/IP; 1,500 turns/day globally; 8 concurrent model calls; 300
artifact builds/day. Warn at 15% remaining; reset at 00:00 IST.

**Why:** one session is roughly 15–25 turns, so 40 supports a full session plus
a second short one; 1,500 global turns ≈ 60–100 sessions/day, enough for a real
test cohort on one shared subscription; the per-minute and concurrency caps stop
a script from draining the route; artifact caps are tighter because a build is a
separate model call. The numbers are [ASSUMPTION] until two weeks of usage
(`M12`, `M13`) exist.

**Alternatives:** 20 turns/day (too tight for one diagnostic + a chapter);
100/user/day (one enthusiastic tester can exhaust the shared route); no global
cap (unsafe on a subscription).

**Changes:** `ZIVON_PERSONALIZED_*` env defaults, quota copy, `EV-PL-005`
goldens. No schema change.

**Owner:** founder. **Status:** open — recommended. **Revisit:** after 14 days
of real usage or if the OpenCode subscription's 5-hour limit is hit.

---

## D-PL-02 — RAG corpus scope

**Question:** which chapters/sources may personalized learning teach from in
R1?

**Recommendation:** all chapters whose source text is already cached **and**
whose syllabus entry exists, with two honest tiers: `lesson` (a published
lesson page exists) and `source` (NCERT source pack only). Class 9 and 10 are
the launch focus; Class 11/12 are listed only where the source cache covers
them. The P2 question bank supplies checks; the exam-paper metadata is
**never** a source. No third-party text is added.

**Why:** the prototype milestone is Class 9/10 content; offering every chapter
with a PDF but no reviewed lesson would overpromise quality. The tier badge is
honest and lets a Class 11 student use the loop where the source is cached.

**Alternatives:** only chapters with published lessons (safer, narrower);
all syllabus chapters (overpromises, some have no cached text); add supplementary
public-domain books now (more work, no clear learner need yet).

**Changes:** `scripts/build_personalized_index.py` input set, the hub picker,
`DET-PL02-PROVENANCE`, coverage reporting.

**Owner:** founder. **Status:** open — recommended. **Revisit:** when Class 11/12
lessons publish, or if a `source` tier session produces more ungrounded turns
than the `lesson` tier.

---

## D-PL-03 — Artifact generation limits

**Question:** how often may the agent build an interactive artifact, and how
large may it be?

**Recommendation:** at most 1 artifact per 4 teaching turns, 4 per session, 12
per user/day, 300 global/day; ≤ 120 KB HTML, ≤ 1,500 DOM nodes, ≤ 3 controls;
one build retry on a transient route error, **no** retry on a lint/render
failure; diagram fallback always present.

**Why:** artifacts are the most expensive and riskiest output (a full builder
call plus a headless render). The cap keeps the loop text-first and the cost
bounded; the size/DOM caps keep a weak Android phone smooth.

**Alternatives:** an artifact on every visual-worthy turn (cost + repetition);
no artifacts in R1 (loses the differentiator); a larger 250 KB cap (no measured
need).

**Changes:** decide-prompt budget rule, `personalized_artifact` job caps,
`EV-PL-003` goldens.

**Owner:** founder. **Status:** open — recommended. **Revisit:** if `M14`
(artifact success) is high and students interact with artifacts more than the
text, or if a build routinely times out.

---

## D-PL-04 — Personal instructions for all signed-in students

**Question:** is the personal-instructions field available to every signed-in
student, or gated (e.g. verified email, onboarding, age)?

**Recommendation:** **yes, to every signed-in student**, with no extra gate.
500-character cap, clearable, privacy copy, save-time PII/injection screen.

**Why:** it is the cheapest honest personalization (explicit, visible,
clearable) and the founder's correction says login is the only gate. Gating it
adds a step for no safety gain; the field itself cannot change safety rules.

**Alternatives:** verified-email only (slower onboarding, no safety gain);
hide it in onboarding (students won't find it); no field at all (repeat
corrections, no personalization).

**Changes:** settings visibility, `EV-PL-004` fixtures, copy.

**Owner:** founder. **Status:** open — recommended. **Revisit:** if abuse via
unverified accounts (D-PL-08) shows up in the first cohort.

---

## D-PL-05 — Saved-chat retention and the counsel flag

**Question:** how long are personalized sessions/messages kept, and when does
counsel review happen?

**Recommendation:** **90 days from last activity**, then hard delete (cascade
messages); no cold copy; export/delete anytime; a 7-day warning in the list at
day 83; account deletion cascades. Counsel review of the child free-text
posture **before** opening beyond the founder-supervised prototype cohort.

**Why:** the loop needs continuity across sittings (J10), but the data is child
free text; 90 days is the shortest window that supports a term of study without
turning into an archive. No cold copy keeps the "delete means delete" promise
simple. This is not legal advice; the DPDP children's-data question stays open.

**Alternatives:** 30 days (too short for a term, more support pain); keep until
account deletion (maximizes risk); 7 days like voice transcripts (breaks
resume).

**Changes:** `retention_sessions` job, privacy copy, export schema, `EV-PL-005`
delete tests, counsel brief.

**Owner:** founder + counsel. **Status:** open — recommended; **counsel review
is a blocker for scale-up, not for the prototype cohort.** **Revisit:** counsel
answer, or any guardian request that the 90-day window is too long.

---

## D-PL-06 — DeepSeek latency and cost budget

**Question:** what latency and spend budget does personalized learning get on
the OpenCode/DeepSeek route, and at what reasoning effort?

**Recommendation:** teach call `reasoning_effort=low`, first teaching text
p50 ≤ 6 s, p90 ≤ 15 s, hard deadline 30 s; decide call low effort, deadline
20 s; artifact build medium effort, deadline 120 s, async; per-turn input
≤ 12k tokens, output ≤ 1.2k; per-session cost logged (`M12`); one retry before
first text, then an honest error.

**Why:** the factory runs this model at high effort and measures multi-minute
calls; a teaching loop cannot wait minutes. Low effort + a small, well-scoped
prompt + streaming is the only way to hit a conversational p90; the deadline is
the honest bound, not a token cap (repo law). These numbers are [ASSUMPTION]
until PL2 measures the route.

**Alternatives:** high effort (too slow for a loop; keep it for the artifact
builder only); no deadline (a stuck turn hangs the session); a different model
(a recorded routing decision, not a tuning knob — D-PL-07).

**Changes:** `ZIVON_PERSONALIZED_*` timeouts/effort, decide/teach prompt length,
quota cost model, `EV-PL-001/002` budgets.

**Owner:** founder + PL2. **Status:** open — recommended. **Revisit:** after 100
real turns; if p90 > 20 s, collapse to one call (`PL-C-006`) or change the route
via a recorded decision.

---

## D-PL-07 — Model routing confirmation (personalized learning on DeepSeek)

**Question:** confirm that personalized learning is served by **DeepSeek V4.1
Flash via the OpenCode API key**, separate from the Gemma voice tutor and the
factory's credentials, and that the backend calls `llm_manager` in-process
rather than through the llm-manager node.

**Recommendation:** **yes to both.** Record it in `AGENTS.md`'s model-routing
table as a new surface ("Personalized learning (product runtime)") and keep
three separate routes/credentials: Gemini (voice), OpenCode-personalized
(runtime teaching), OpenCode-factory (build-time). Add the revisit trigger: a
second runtime consumer of the same route, or the backend must become
model-key-free → move to a dedicated node.

**Why:** long structured teaching calls on the Gemini key would contend with
the 4 s voice SLO; the OpenCode subscription already carries the model with
JSON mode, reasoning effort, and a documented gateway; in-process `llm_manager`
avoids an extra hop and supports per-turn streaming/affinity. This supersedes
the "internal content generation only — never user-facing" note **for this
surface only**, as a recorded founder decision.

**Alternatives:** Gemma/Gemini for teaching (SLO contention, one key for two
surfaces); the factory's key/config (shared blast radius); the llm-manager node
(extra hop, a second model deployment to operate).

**Changes:** `AGENTS.md` routing table, `k8s` secret name, PL2 config,
`security-privacy.md` §4.7.

**Owner:** founder. **Status:** open — recommended (the spec is written on this
assumption). **Revisit:** cost/latency breach, or a second consumer.

---

## D-PL-08 — Email-verification posture for personalized learning

**Question:** may an unverified-email account use personalized learning, and at
what quota?

**Recommendation:** **yes, at a lower cap** (20 turns/day instead of 40) until
the email is verified; no feature block, no nag modal; one line in the quota
strip ("Verify your email for 40 turns/day"). Verification is never required to
read history, export, or delete.

**Why:** login is the founder's only gate; verifying is a friction point for a
student on a shared device. A lower cap reduces trivial multi-account abuse
without locking a real student out.

**Alternatives:** block until verified (friction, support pain); same cap for
everyone (multi-account abuse is cheap); verify-only via Google (excludes
password accounts).

**Changes:** quota resolution (verified flag), copy, `EV-PL-005` fixtures.

**Owner:** founder. **Status:** open — recommended. **Revisit:** if abuse
through unverified accounts is measured, or if verification completion is high
enough to drop the distinction.

---

## D-PL-09 — One conversation store (TUT-05) and the artifact origin

**Question (two linked deployment/product choices):** (a) should the lesson
dock's doubt history (`TUT-05`) use the same `personalized_session` store as
personalized learning; (b) should artifacts be served from a dedicated origin
in production (`artifacts.<domain>`) rather than same-origin?

**Recommendation:** (a) **yes** — one store, `origin='lesson_dock'`, with the
same title/chapter/resume/delete/export; it avoids two chat stores with two
delete semantics and makes "your conversations" one screen. (b) **yes** — a
dedicated artifact origin in production; same-origin path is acceptable for
local/compose, and the iframe sandbox is unchanged either way.

**Why:** (a) the frozen plan's `TUT-05` and `REQUIREMENTS` §10.19 already
describe saved doubts; duplicating the tables would double the privacy surface.
(b) The sandbox protects the artifact from the parent; a separate origin
protects the parent from a future artifact-serving bug and keeps cookies off the
artifact host. It is a deployment decision, not a blocker for the prototype.

**Alternatives:** (a) a separate `doubt` table (two stores, two deletes);
(b) same-origin forever (acceptable but a weaker boundary).

**Changes:** (a) `personalized_session.origin` enum + a dock history entry point
(a follow-up PR, not W5.5 P0); (b) nginx/host + CSP `frame-ancestors` config.

**Owner:** founder (+ deployment for b). **Status:** open — recommended.
**Revisit:** before the dock history ships; before public launch for (b).

---

## D-PL-10 — Doctrine for the session screen and the founder visual verdict

**Question:** which visual system does the personalized session use — base
Field Notes §1–§9, or a lesson-notebook extension (§10-like) — and who gives
the verdict?

**Recommendation:** build the first example in **base §1–§9** (paper cards,
typed body, no ruled grid/taped cards/language bar) using the existing
`product.css` components; the founder gives the visual verdict through the
same-agent protocol. If the verdict asks for the notebook feel, file **DCR-003**
to `docs/frontend/design-doctrine.md` (a new section for personalized
surfaces), not an improvised copy of §10.

**Why:** §10 is explicitly lesson-page-only; a personalized session is a new
app surface. Reusing base components is honest and fast; a doctrine extension
needs the owner's pen. The artifact viewer itself is a lesson device (§10.6/7)
and follows the doctrine already.

**Alternatives:** copy §10 devices now (scope error; the doctrine owner has not
approved); make it a plain form (loses the teaching feel); wait for a doctrine
section before building (blocks the wave).

**Changes:** the PL4 example page, `personalized.css`, the founder verdict
record, possibly DCR-003.

**Owner:** founder (visual verdict), doctrine owner (DCR). **Status:** open —
recommended. **Revisit:** at the first PL4 example review.

---

## D-PL-11 — Login scope: personalized learning only, or the whole product

**Question:** the founder correction says "login is required" for the free
prototype. Does that mean login for this feature, or for the whole consumer
product (lessons, practice, tests, voice dock too)?

**Recommendation:** **this feature only.** Login is required for
`/app/personalized`, personal instructions, saved sessions, and export/delete.
The lesson pages, catalogue, voice dock, practice, speaking, and tests keep the
frozen guest-first model (frozen plan #4, `AUTH-08`): a guest can read a lesson
and ask a doubt without an account; signing in adds cross-device continuity.
The rest of the product is unchanged.

**Why:** the frozen plan is explicitly guest-first with an optional account;
locking the whole product behind login is a much larger acquisition change
that the founder did not ask for and that would break the existing lesson
surfaces and the demo path. The account is genuinely required for the new
feature (sessions, mastery, preferences), so the narrow reading satisfies the
correction without re-litigating the identity model.

**Alternatives:** login for the whole product (a deliberate acquisition/identity
decision, not a side effect); guest personalized sessions with local storage
(contradicts the correction and the account-scoped preferences).

**Changes:** `/login` gating, the guest banner, the lesson CTA, onboarding copy.

**Owner:** founder. **Status:** open — recommended (the spec is written on it).
**Revisit:** if the founder clarifies that "login is required" means the whole
prototype; then open a separate decision with the acquisition trade-off.

---

## Assumptions to verify at build (not founder decisions)

| Assumption | Why it matters | Verify by |
|---|---|---|
| `intfloat/multilingual-e5-small` ONNX runs in the backend image without torch and stays ≤ ~250 MB added | if not, the lexical fallback ships first (honest, lower quality) | PL2 image-size check + a retrieval quality spot check |
| The OpenCode gateway accepts `x-opencode-session` + `reasoning_effort=low` for this model | routing/latency | PL2 probe (the factory already probes this class) |
| `question_bank` covers enough Class 9/10 concepts for a 3-item diagnostic | generated items fill gaps; quality risk | PL2 coverage report per chapter |
| A 120 KB artifact is enough for the golden simulation | size cap | PL3 golden |
| The 90-day retention is acceptable to the prototype cohort | privacy posture | founder + counsel review (D-PL-05) |

## Decision history

| Date | Change |
|---|---|
| 2026-11-17 | Spec written; D-PL-01…11 opened with recommendations |
