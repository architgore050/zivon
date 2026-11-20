# Security and privacy — threat model, controls, tests

Status: **controls implemented and the deterministic test matrix landed
(PL5, 2026-11-19); the model-level evals (`EV-PL-002/004` judges) run
founder-local per `evals.md` §10.** Owner workstream: PL5 with PL1
(API/auth), PL2 (model/RAG), PL3 (artifacts). This is a child-facing feature:
a control that cannot be tested is treated as absent.

Scope: the personalized-learning hub/session, personal instructions, saved
conversations, generated artifacts, quotas, and the voice-tutor
personal-instruction injection. Existing auth/session/CSRF controls from
ADR-0029 and the app-shell guard are reused, not re-specified.

---

## 1. Trust boundaries and principles

```
student browser ──cookie+CSRF──▶ backend (PL1) ──llm_manager──▶ model route
        │                              │
        │                              ├── hot DB (sessions/messages/prefs/quota)
        │                              └── RAG index (public content, file)
        │
        └──sandboxed iframe──▶ artifact document (opaque origin, no network)
```

1. **The model is untrusted.** Its output is data: schema-validated, citation-
   resolved, answer-key-stripped, linted, sandboxed. No model output is
   trusted to enforce a rule.
2. **Student text is untrusted.** It never becomes a system message, never
   becomes HTML, never becomes a log field, never becomes a file path.
3. **RAG content is untrusted-but-reviewed.** It is public source material, but
   it is machine-extracted and can contain instruction-like text. It rides in a
   delimited data block; citations are resolved by id, not by model claim.
4. **Least data.** No raw audio, no inferred profile, no contact details, no
   cross-student data, no cold copy of child free text.
5. **Secure by default.** Feature off until configured; fail closed on auth,
   schema, citation, and sandbox checks; honest error copy, never a silent
   fallback that hides a security decision.
6. **Every control has a test.** The matrix in §12 maps each control to a
   deterministic test or an eval.

---

## 2. Assets

| Asset | Where | Sensitivity | If lost/exposed |
|---|---|---|---|
| Personal instructions | hot DB | child free text, low volume | embarrassment, injection surface |
| Session messages / weakness text | hot DB | child free text + learning evidence | privacy harm, DPDP exposure |
| Mastery evidence | hot DB + progress events | learning record | inferred ability if aggregated — minimized |
| Artifacts | hot DB | generated code | XSS/exfiltration if rendered unsandboxed |
| Preferences/session ids | URLs/API | identifiers | IDOR if unscoped |
| Model API key | K8s Secret | credential | cost/abuse, data access |
| Usage/cost ledger | hot DB | operational | cost forecasting only |
| RAG index | file/volume | public content | poisoning if writable by a non-operator |

---

## 3. Threat model

Legend: **C** = control, **R** = residual risk, **T** = test (deterministic test
id or eval id). Severity is the pre-control rating.

| ID | Threat (STRIDE) | Vector | Impact | C | R | T |
|---|---|---|---|---|---|---|
| **T-PL-01** | Prompt injection → safety bypass (Tampering) | weakness text, follow-up, personal instructions, RAG chunk | unsafe/off-topic output; answer-key leak; false authority | precedence block; delimited data; no tools; schema validation; answer key server-only; save-time screen; `EV-PL-004` | model may still say something off-tone; no data/authority impact | `DET-PL04-INJECT`, `DET-PL04-KEY`, `EV-PL-004` |
| **T-PL-02** | Generated HTML XSS / parent-page takeover (Tampering/EoP) | artifact HTML/JS | steal session, deface app, exfiltrate | `sandbox="allow-scripts"` no same-origin; CSP header+meta; lint (incl. self-navigation); render gate (network + navigation assertions); no top-nav/forms/popups | a browser bug in sandbox/CSP | `DET-PL03-LINT`, `DET-PL03-SANDBOX`, `EV-PL-003` |
| **T-PL-03** | Data exfiltration from an artifact (Information disclosure) | `fetch`, `img src`, `WebSocket`, DNS, form action | leak page/session data to a third party | CSP `default-src 'none'; connect-src 'none'`; network-aborted render gate; opaque origin; no cookies | side channels (timing) — no data to leak in the doc | `DET-PL03-LINT`, `DET-PL03-RENDER` |
| **T-PL-04** | Cross-user data access / IDOR (Information disclosure) | guessing a session/artifact id; URL tampering | read/delete another child's session | owner-scoped queries from the session; UUIDv7; 404 not 403; artifact requires a reference in the caller's sessions | a bug in one route | `DET-PL05-IDOR`, `DET-PL05-ARTIFACT-REF` |
| **T-PL-05** | Child PII collection in free text (Privacy) | student types name/phone/school; instructions | PII stored, logged, or sent to a model | no solicitation copy; save-time contact-detail rejection; no PII in logs; 90-day cap; export/delete; no cold copy | a determined student can type a name in a message — minimization + retention, not prevention | `DET-PL04-PII`, `DET-PL05-LOGS`, `EV-PL-004` |
| **T-PL-06** | Saved-chat leakage (Information disclosure) | shared device, browser cache, open tab | another person reads the transcript | login guard; `Cache-Control: no-store` on HTML; `noindex`; no share links; sign-out; delete | a shared device left signed in (account-level, not fixable in-app) | `DET-PL05-HEADERS`, `DET-PL05-IDOR` |
| **T-PL-07** | RAG poisoning (Tampering) | malicious text in a source pack/lesson; a writable index | model repeats false/instruction-like content | index built only from reviewed sources; operator-only build; per-source hashes; data delimiters; citation resolution; `EV-PL-002` faithfulness judge | a compromised source PDF before ingest (factory-side) | `DET-PL02-PROVENANCE`, `EV-PL-002` |
| **T-PL-08** | Model/cost abuse (DoS) | scripted turns, many accounts, artifact spam | subscription exhausted; service down for real students | login; per-user/per-IP/global quotas; concurrency semaphore; body caps; cache; kill switch | coordinated multi-account abuse | `DET-PL05-QUOTA`, `DET-PL05-RATE`, `EV-PL-005` |
| **T-PL-09** | Deletion failure (Repudiation/Privacy) | delete/account delete leaves rows/artifacts | retention breach; guardian complaint | hard deletes in one transaction; cascade; artifact refcount; TTL jobs; export; deletion test | backup restore re-creates rows (no cold copy → not applicable) | `DET-PL05-DELETE`, `DET-PL05-EXPORT` |
| **T-PL-10** | Log/telemetry leak (Information disclosure) | message text in a log field or trace | child free text in logs | `log_event` allow-list; no text fields; redaction; no prompt/response logging; PR checklist | a future event adds a text field | `DET-PL05-LOGS` |
| **T-PL-11** | CSRF / session fixation (Spoofing) | cross-site form, stolen cookie | mutate preferences/sessions/turns | `X-CSRF-Token` on every write; `SameSite=Lax; HttpOnly; Secure`; rotation (ADR-0029) | an XSS in the app shell (separate control) | `DET-PL05-CSRF` |
| **T-PL-12** | Open redirect via `next` | crafted `next=//evil` | phishing after login | `safe_next_path` (same-origin path only), reused | none known | `DET-PL05-NEXT` |
| **T-PL-13** | Artifact build abuse (resource exhaustion) | `while(true)`, huge DOM, 10k controls | browser freeze / build cost | size/DOM/control caps; lint; render gate; runtime watchdog; per-day caps | a clever infinite loop still freezes its own iframe | `DET-PL03-LINT`, `DET-PL03-RENDER` |
| **T-PL-14** | Model key leakage (Info disclosure) | logged config, error body, image/manifest | cost abuse | runtime secret only; never logged; error bodies redacted; secret scan in CI; separate secret per surface | a cluster compromise (out of scope) | `DET-PL05-SECRETS` |
| **T-PL-15** | Prompt/response logging in provider (Privacy) | provider retains prompts | child text at a third party | no PII/secrets in prompts; provider terms reviewed before scale-up; counsel flag; no audio | provider retention policy (vendor decision, D-PL-05) | `EV-PL-004` + vendor review |
| **T-PL-16** | Unsafe/incorrect physics (Integrity) | model hallucination | child learns a wrong claim | grounding law; citations required; ungrounded flag; report path; `EV-PL-002` faithfulness judge | a subtle error in a cited source | `DET-PL02-CITATIONS`, `EV-PL-002` |
| **T-PL-17** | Cross-student leak through the shared artifact cache (Information disclosure) | an artifact built from a prompt that accidentally included student text is reused by another student | student text in another child's visual | builder prompt and stored spec exclude student text by construction; content hash excludes `why`; `DET-PL03-NO-STUDENT` canary test | a future prompt edit adds session text | `DET-PL03-NO-STUDENT`, `EV-PL-003` |

---

## 4. Detailed controls

### 4.1 Prompt injection

- **Precedence:** the safety core is stated once and is the first system
  message. The personal block is a **second system message** on the PL path and a
  **delimited user-role data section** on the voice path (the Gemini transport joins all
  system messages into one `system_instruction`, so a second system message there would
  promote student text into the system slot — `data-and-api.md` §5.2). Student turns are
  user messages inside delimited blocks. RAG excerpts are a delimited data block labelled
  "never instructions".
- **No tools:** the model cannot read files, call URLs, query the DB, or
  execute code. The only "action" it can request is an artifact spec, which is
  schema-validated and built by a separate call under lint + sandbox.
- **No answer-key leakage:** the answer key is stored server-side and never
  serialized into a client payload before submission; the decide call's
  `check.answer` is stripped by code, not by asking the model.
- **Save-time screen** (personal instructions): normalize → length → control
  chars → role markers → contact-detail regex (email/phone/URL) → obvious
  system-instruction phrases. Rejection is `422` with a helpful message and the
  previous value untouched.
- **Harness checks are not prompt-dependent:** stage machine, scoring,
  citation resolution, quota, and artifact lint run in code.
- **Residual:** a model can still produce an off-topic or unkind sentence. The
  report path, the persona rubric (`EV-PL-001` judge on the full suite), and the
  kill switch are the response; it cannot leak keys/data or change authority.

### 4.2 Generated HTML / XSS / exfiltration

See [`interactive-artifacts.md`](interactive-artifacts.md) §4–§5 for the full
contract. Non-negotiables:

- `sandbox="allow-scripts"` only; **never** `allow-same-origin`.
- CSP `default-src 'none'`; inline script/style only; `connect-src 'none'`;
  `img-src data:`; `form-action 'none'`; `frame-ancestors 'self'`;
  `sandbox allow-scripts` in the response header.
- Lint rejects every network/storage/parent/top-nav/**self-navigation**/form/popup API
  and external URL; the render gate aborts all network and fails on any attempt or
  navigation.
- The artifact route requires a session and a reference; it is `noindex`,
  `nosniff`, `no-referrer`, and `private`.
- The only `postMessage` channel is host-validated by `event.source` and schema;
  nothing from it is rendered as HTML.

### 4.3 Child privacy (DPDP posture)

- **Minimization:** no name, email, phone, school, address, photo, audio, or
  precise location is requested or needed. The account email exists (ADR-0029)
  but is never included in a prompt, a session payload, a log, or an artifact.
- **Purpose limitation:** sessions exist to continue teaching; mastery evidence
  exists to show the student what they proved. No cross-student comparison, no
  inferred profile, no marketing/analytics use of free text.
- **Consent:** the voice consent gate is unchanged. Personalized learning opens
  no microphone; the account consent checkbox at signup covers account data.
  The privacy page lists the new data class and retention.
- **Retention:** 90 days from last activity (D-PL-05); no cold copy; deletion
  and export are first-class; a guardian-facing explanation is on
  `/app/settings/privacy`.
- **Legal flag:** DPDP children's-data provisions and the guardian-consent
  posture need counsel before scale-up. This spec is not legal advice; it
  records the engineering posture and the flag (`D-PL-05`).

### 4.4 Cross-user leakage

- Session/artifact lookup derives `user_id` from the validated session, never
  from the request body/URL.
- Another user's id returns `404 E-NOT-FOUND` (no existence oracle).
- The list/detail/export/delete handlers share one owner-scope query helper; a
  route that bypasses it is a review blocker.
- Artifacts are shared by content hash but served only when a message in the
  caller's sessions references them (or admin auth).
- Tests: two users, A tries B's session id on every endpoint → 404; A cannot
  fetch an artifact only referenced by B.

### 4.5 Deletion and export

- Session delete: one transaction; messages cascade; artifact references drop;
  usage `session_id` set NULL (counts survive without the subject link).
- Account delete: `backend/privacy.py` cascade adds preferences, sessions
  (messages cascade), usage; quota rows for the user are deleted; the `users`
  tombstone remains (ADR-0029).
- TTL jobs are idempotent, log counts only, and run in the existing
  `run_all_ttl_jobs` path.
- Export returns only the owner's data, with a schema version, no prompt text,
  no internal ids that are not useful to the student.
- A deleted session cannot be resurrected by a retry: idempotency rows are
  deleted with the session; a late turn insert fails FK/404.

### 4.6 Logging redaction

Allowed fields: ids (hashed where the log is not the DB), chapter/concept ids,
stage, status, error code, latency/token buckets, cache hit, model id, prompt/
index version, counts. Never: message text, weakness text, instructions,
artifact HTML, check question/options, email, cookie, CSRF token, API key,
prompt text, raw provider response.

The logging test (`DET-PL05-LOGS`) runs a session through the fake model and
asserts that no emitted event payload value contains the seeded secret string
("PII_CANARY_7f3a") or the message text. It also asserts the event-key
allow-list.

### 4.7 Secrets

- `ZIVON_PERSONALIZED_API_KEY` lives in a K8s Secret (`zivon-personalized-env`),
  mounted only into the backend; never in the image, manifest, repo, or logs.
- Boot logs print `configured: true/false`, never a value.
- gitleaks + the CI secret scan are the standing gate; the spec adds no secret.
- The OpenCode session header is an opaque per-session id, not a credential.

### 4.8 Abuse and cost

- Auth required; per-user, per-IP, global quotas; concurrency semaphore; body
  caps; message length caps; artifact caps; cache.
- A turn is reserved before the model call and released on failure; a retry is
  idempotent by `client_turn_id`.
- The kill switch (`ZIVON_PERSONALIZED_ENABLED=false`) turns the feature into a
  read-only history view without touching lessons, practice, tests, or voice.
- An admin can purge a cached artifact and disable artifact builds without a
  deploy (config/env), with an audit row.

---

## 5. Security headers (PL surfaces)

Session/hub pages are part of the `/app` shell: the web-shell CSP/headers apply
(§5 there), including `connect-src 'self'`, `no-store`, `noindex`,
`frame-ancestors 'none'`. The SSE endpoint is same-origin and `no-store`. The
artifact route has its own strict policy (§4.2). The settings section inherits
the settings page headers.

No new third-party host, font, analytics, or CDN is introduced. The one host added anywhere is
the artifact origin in dedicated-origin mode (`D-PL-09b`), and its only shell-side effect is a
single `frame-src` allow-list entry — never a `script-src`/`connect-src` change.

---

## 6. Privacy copy obligations

The implementation must ship:

1. Settings section help + "don't include personal details" line (`spec.md` §1.3).
2. Privacy page row: "Personalized learning: your lessons, answers, and
   mastery notes; kept 90 days after your last visit; export or delete anytime."
3. Hub footer: AI-generated board-style practice, not official CBSE.
4. Session header: "Using your learning preferences · Edit" when active.
5. Artifact card: "Runs isolated — no network, no access to your account."
6. Quota copy with the reset time; no urgency.

Copy is English at R1 (shell debt); translation follows the UI-translation
workstream. No dark patterns: no pre-checked boxes, no "are you sure you want
to lose your progress" guilt, no hidden delete.

---

## 7. Deletion / retention matrix

| Data | Retention | Job | Account delete | Session delete | Export |
|---|---|---|---|---|---|
| `user_preferences` | until clear/account delete | — | cascade | n/a | yes |
| `personalized_session` | 90 d after last turn | `retention_sessions` | cascade | hard delete | yes |
| `personalized_message` | with session | cascade | cascade | cascade | yes |
| `personalized_artifact` | 30 d unreferenced; 7 d failed | `retention_artifacts` | refs dropped; row by job | refs dropped | id/kind/title |
| `personalized_usage` | 90 d | `retention_usage` | cascade | `session_id` NULL | no (ops) |
| `personalized_quota` | current + yesterday | `retention_quota` | user rows deleted | n/a | no (ops) |
| RAG index | per content version | rebuild/purge | n/a (public) | n/a | n/a |
| Logs | 7–30 d (existing) | existing | no free text | no free text | n/a |

---

## 8. Incident response (feature-specific)

| Incident | Immediate action | Evidence | Follow-up |
|---|---|---|---|
| Artifact escapes the sandbox | disable artifact builds (env), purge the hash, bump `lint_version` so the id (and URL) changes and browser caches cannot serve the old document | render/lint report, browser version | add the sample to `EV-PL-003`, sandbox review, CSP tightening |
| Model route abused / cost spike | flip the kill switch; lower global cap; rotate the key | usage ledger by user/hour | quota calibration, abuse report |
| Child PII found in a session/log | delete the row, confirm no log copy, notify the founder/counsel path | deletion audit row | copy/PII-screen review |
| Wrong physics in a teaching turn | report row → hide the turn? (turns are immutable; the session can be deleted by the student) → fix the prompt/index | message payload + citations | add a golden defect to `EV-PL-002` |
| Index poisoned | roll back to the previous index version; block new sessions | manifest diff | source review, rebuild |
| Deletion bug | stop the TTL job, fix forward, re-run; record in the deletion ledger | row counts | add a regression test |

---

## 9. Compliance flags (not legal advice)

- **DPDP / children:** the stored session text is child free text. The posture
  is minimization + 90-day retention + no cold copy + export/delete + no
  profiling. Counsel review is required before opening beyond the prototype
  test cohort (`D-PL-05`).
- **CBSE:** no verbatim paper content is used. Board-style generated items carry
  non-affiliation copy (DEC-COMP-002). No new compliance surface is created.
- **Vendor terms:** the model route's data-retention/training terms must be
  reviewed before scale-up; no audio is sent, and no PII is placed in prompts.
- **Age:** no age gate is added; the product's existing guardian/consent posture
  applies. A guardian-facing privacy explanation is required (see §6).

---

## 10. Test summary

| Test | Asserts |
|---|---|
| `DET-PL04-INJECT` | seeded instruction/weakness/RAG injections do not change the safety contract; output stays Physics; no system-instruction compliance; the personal block never enters `system_instruction` on the voice path |
| `DET-PL04-KEY` | no answer key reaches any client-bound payload before submission; the DB-only `answer_key` column is stripped by the serializer |
| `DET-PL04-PII` | contact-detail instructions are rejected; the previous value survives |
| `DET-PL05-IDOR` | every session endpoint returns 404 for another user's id |
| `DET-PL05-ARTIFACT-REF` | an artifact unreferenced by the caller is 404 |
| `DET-PL05-CSRF` | every write without/invalid CSRF is 403 and changes nothing |
| `DET-PL05-NEXT` | `next` values are same-origin paths only (`//host` falls back) |
| `DET-PL05-QUOTA` | concurrent turns never exceed the cap; failed turns release |
| `DET-PL05-RATE` | 429 + `Retry-After` on the family limits |
| `DET-PL05-DELETE` | session/account deletes remove every row and reference |
| `DET-PL05-EXPORT` | export contains the owner's data only; schema versioned |
| `DET-PL05-LOGS` | no event payload contains the canary text or free text |
| `DET-PL05-HEADERS` | `no-store`, `noindex`, CSP on the personalized signed-in surfaces (hub, session page hosting the artifact viewer, settings) plus the SSE contract; artifact headers strict (`DET-PL05-ARTIFACT-REF`) |
| `DET-PL03-*` | artifact lint/render/sandbox/cache/no-student-text/fallback (see `interactive-artifacts.md`) |
| `EV-PL-002/004` | model-level grounding and injection behaviour on the full suite |

The deterministic tests live with their owners (`testing/backend/`,
`testing/frontend/`, `testing/content_factory/` for lint reuse) and run
key-free. The model-level evals run through `evals/` with a mocked model in
smoke mode and the real route in the full suite (founder-local; `evals.md`
§10). The landing map, as of PL5 (2026-11-19):

| Test id | Where it lives |
|---|---|
| `DET-PL04-*` (NORMALIZE/PII/KEY/INJECT/PARITY/SAVE-PRIVACY) | `evals/checkers/personalized_checks.py` (card `EV-PL-004`) |
| `DET-PL05-*` (QUOTA/RATE/CSRF/IDOR/ARTIFACT-REF/DELETE/EXPORT/LOGS/HEADERS/NO-PAYWALL/NEXT/SECRETS) | `evals/checkers/personalized_checks.py` (card `EV-PL-005`) |
| The poisoned-RAG turn, turn-event privacy, provider-error hygiene, turn `no-store`, the `next` chain | `testing/backend/test_personalized_security.py` |
| The checker fault-detection mutations (tampered goldens, weakened screen, merged block, key leak, paywall table + web paywall copy, dropped shell/SSE headers, backslash-permitting `next`) | `testing/evals/test_personalized_eval_cards.py` |
| The quota race, release/retry arithmetic, retention jobs | `testing/backend/test_personalized_quota.py` |
| Session IDOR/CSRF/export/delete, list privacy, family 429 | `testing/backend/test_personalized_sessions.py` |
| Preferences screen/kill switch/previous-value-preserved | `testing/backend/test_personalized_preferences.py` |
| The log canary + the account-deletion cascade | `testing/backend/test_personalized_logging.py` |
| Artifact lint seeded defects, self-navigation/parent/storage/external-fetch rejection, the red-team probe, the canary no-student-text guard | `testing/backend/test_personalized_artifacts.py` + `EV-PL-003` |
| Voice block-out-of-system, the 60 s cache, the parity guard | `testing/voice/test_personal_instructions.py`, `testing/voice/test_prompt_safety_parity.py` |

The key-free merge gate for the whole stack is `bash scripts/pl-smoke.sh`;
the full-suite judge layer is the founder-local gate documented in
`evals.md` §10.
