# Data and API contract

Status: **PL1 implemented (2026-11-17); the teaching turn and artifact
generation wait for PL2/PL3.** Migration target:
`0005_personalized_learning` after `0004_practice_speaking_tests`. All DDL must
be SQLite-portable (the containerless empty→head test) and valid PostgreSQL 16
(the CI Alembic job). IDs are UUIDv7 (`db/uuid7.py`); timestamps are
`timestamptz` (TEXT ISO on SQLite).

**PL1 landed:** the six tables (§2), the `progress_event.kind` /
`abuse_bucket.endpoint_family` CHECK widenings, the retention jobs (§2.7),
`backend/personalized/{store,preferences,quota,retention,router}.py`, the
preferences + session + usage endpoints (§4.1–§4.9 minus artifacts), and the
voice prompt injection (§5). **PL3 landed (2026-11-18):** the artifact
endpoints API-PL-13/14 (`backend/personalized/artifact_router.py`), the
content-addressed cache + hard lint + status machine
(`backend/personalized/artifacts.py`), the D-PL-07 builder engine
(`backend/personalized/artifact_prompt.py`, fail-closed off until
`ZIVON_PERSONALIZED_ARTIFACT_BUILDS=true` with the route configured), the
headless render gate (`backend/personalized/artifact_sandbox.py`), and the
viewer host bridge (`frontend/assets/personalized-artifact.js` +
`web/templates/app/partials/artifact_viewer.html`). **Still spec, not code:**
the SSE turn endpoint behaviour beyond its honest `503 E-PL-MODEL-DOWN` stub
(§4.6's event catalogue is PL2), and the catalog coverage response body (§4.2
API-PL-04 answers `503 E-CONTENT-UNAVAILABLE` until the index exists). The
per-endpoint hourly sub-caps of the endpoint table
(preferences 10/h, delete/end 20/h) are enforced as the `personalized_ip`
20/min family in PL1; the families and windows live in `backend/abuse.py`.

**No paywall tables.** There is no `plan`, `subscription`, `payment`,
`entitlement`, `price`, or `invoice` table anywhere in this migration. Free
access is the product; quotas are counters, not entitlements.

---

## 1. Data classes and retention

New classes (continue the `docs/backend/data-classification.csv` numbering; the register
currently stops at **C20**, and `docs/backend/db-spec.md` already uses **C21** for the
student-account / catalogue / W4 table group, so these four start at C22):

| Class | Data | System of record | Sensitivity | Retention | Cold copy | Deletion |
|---|---|---|---|---|---|---|
| **C22** | Account personal instructions | hot DB `user_preferences` | child-authored free text; low volume | until cleared or account deleted | **never** | clear sets the value NULL; account delete cascades |
| **C23** | Personalized sessions + messages (teaching state, checks, mastery evidence, text) | hot DB `personalized_session` / `personalized_message` | child free text + learning evidence | **90 days** from `last_turn_at` (D-PL-05) | **never** | per-session hard delete; account delete cascades; TTL job |
| **C24** | Personalized artifacts (generated HTML, cached by content hash) | hot DB `personalized_artifact` | generated public content; **never** contains student text | referenced artifacts until 30 days unreferenced; failed 7 days | **never** | refcount job; operator purge; account delete drops references |
| **C25** | Personalization ops data (`personalized_usage`, `personalized_quota`) | hot DB | operational counts; no text | usage 90 days; quota current period | no | usage TTL 90 days; quota pruned after roll-up |

The four rows are added to `docs/backend/data-classification.csv` in the PL1 migration PR
(the same PR that creates the tables); this table is the declaration they must match.

The session/message rows are the only new **child free-text** store. Controls:
no raw audio, no logs, no cold copy, explicit export/delete, 90-day cap, and a
counsel flag before scale-up (`D-PL-05`).

---

## 2. Tables

### 2.1 `user_preferences`

One row per account; created lazily on first save.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `user_id` | text PK | ✗ | — | FK → `users(user_id)` ON DELETE CASCADE |
| `personal_instructions` | text | ✓ | NULL | ≤ 500 chars after normalization; `CHECK (length(personal_instructions) <= 500)` |
| `instructions_version` | int | ✗ | 0 | increments on every save/clear (cache-busting); clear keeps the row with `personal_instructions = NULL` |
| `created_at` | timestamptz | ✗ | now | |
| `updated_at` | timestamptz | ✗ | now | |

No index beyond the PK: the only query is by `user_id`. The row is included in
export; deletion cascades.

### 2.2 `personalized_session`

One row per saved conversation (learning or chat).

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `session_id` | text PK | ✗ | — | UUIDv7 |
| `user_id` | text | ✗ | — | FK → `users` ON DELETE CASCADE; index `(user_id, updated_at DESC)` |
| `parent_session_id` | text | ✓ | NULL | FK → `personalized_session(session_id)` ON DELETE SET NULL; set when a session is started after the 60-turn cap ("continue from your last session"). Display-only: no state or mastery carries over |
| `title` | text | ✗ | — | ≤ 120 chars; server-generated from chapter/concept, never from free text |
| `mode` | text | ✗ | 'learning' | CHECK ('learning','chat') |
| `class_level` | int | ✗ | — | CHECK 6–12 |
| `chapter_id` | text | ✗ | — | plain text (stable slug; survives a syllabus re-import); index `(user_id, chapter_id)` |
| `concept_ids` | json | ✗ | '[]' | JSON array of concept ids (target set) |
| `weakness_text` | text | ✓ | NULL | ≤ 500 chars, the student's words; never logged, never in titles |
| `stage` | text | ✗ | 'diagnose' | CHECK ('diagnose','teach','check','adapt','worked_example','advance','harder','board','mastery','done') |
| `difficulty_level` | int | ✗ | 1 | CHECK 1–4 |
| `status` | text | ✗ | 'active' | CHECK ('active','completed','abandoned') |
| `state` | json | ✗ | '{}' | the machine's memory (agent-and-rag §2.4); `schema_version` inside |
| `turn_count` | int | ✗ | 0 | CHECK ≥ 0 and ≤ 60 |
| `rag_index_version` | text | ✓ | NULL | index used at the last turn |
| `prompt_version` | text | ✗ | 'pl-1' | |
| `model` | text | ✓ | NULL | last model id (ops) |
| `created_at` / `updated_at` | timestamptz | ✗ | now | |
| `last_turn_at` | timestamptz | ✓ | NULL | drives the 90-day TTL and the list order |
| `completed_at` | timestamptz | ✓ | NULL | set at `done`/end |

Indexes: `(user_id, updated_at DESC)` for the list; `(user_id, status)`;
`(last_turn_at)` for the TTL job.

### 2.3 `personalized_message`

Append-only per session, one row per turn/event.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `message_id` | text PK | ✗ | — | UUIDv7 |
| `session_id` | text | ✗ | — | FK → `personalized_session` ON DELETE CASCADE |
| `turn_index` | int | ✗ | — | **message** sequence within the session (0, 1, 2 …): one value per row, so the UNIQUE holds even though one turn appends several rows. The logical turn number is `payload.turn_no`; UNIQUE `(session_id, turn_index)` |
| `client_turn_id` | text | ✓ | NULL | idempotency key; partial UNIQUE `(session_id, client_turn_id) WHERE client_turn_id IS NOT NULL` |
| `role` | text | ✗ | — | CHECK ('student','tutor','system_event') |
| `kind` | text | ✗ | — | CHECK ('text','check','check_result','artifact_ref','stage_change','diagnostic','summary') |
| `text` | text | ✓ | NULL | student/tutor visible text; ≤ 8,000 chars (a turn) |
| `payload` | json | ✗ | '{}' | structured turn (§4.6); the API serializer strips `answer_key` |
| `answer_key` | text | ✓ | NULL | server-only key for the open check; never serialized; set NULL once scored (the result payload carries `expected`) |
| `created_at` | timestamptz | ✗ | now | |

Index `(session_id, turn_index)`. The message row is the unit of export and
delete; no edits, no soft delete.

### 2.4 `personalized_artifact`

Content-addressed cache + build record.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `artifact_id` | text PK | ✗ | — | first 32 hex of the content hash |
| `content_hash` | text | ✗ | — | full SHA-256; UNIQUE |
| `kind` | text | ✗ | — | CHECK ('simulation','diagram') |
| `title` | text | ✗ | — | ≤ 120 chars |
| `spec` | json | ✗ | — | the validated artifact request |
| `html` | text | ✓ | NULL | the self-contained document; NULL until ready |
| `fallback` | json | ✓ | NULL | `{kind:'diagram' or 'text', svg?: …}` |
| `status` | text | ✗ | 'pending' | CHECK ('pending','ready','failed') |
| `failure_reason` | text | ✓ | NULL | CHECK in ('lint','render','timeout','budget','route','spec') when failed |
| `model` | text | ✓ | NULL | |
| `prompt_version` | text | ✗ | — | |
| `doctrine_hash` | text | ✗ | — | SHA-256 of the doctrine file |
| `schema_version` | int | ✗ | 1 | |
| `lint_version` | text | ✗ | 'pl-artifact-1' | bump when the artifact lint rules change |
| `lint_hits` | int | ✗ | 0 | count only (no rule text needed in the row) |
| `render_ms` | int | ✓ | NULL | headless gate duration |
| `created_at` / `ready_at` | timestamptz | ✗ / ✓ | now / NULL | |
| `last_used_at` | timestamptz | ✓ | NULL | refcount purge input |

Indexes: `(content_hash)` unique; `(status, last_used_at)` for the purge job.
No `user_id`: artifacts are shared public content. Access is authorized by a
message reference in one of the caller's sessions.

### 2.5 `personalized_usage`

Append-only per model call (the cost ledger).

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `usage_id` | text PK | ✗ | — | UUIDv7 |
| `user_id` | text | ✗ | — | FK → `users` ON DELETE CASCADE |
| `session_id` | text | ✓ | NULL | FK → `personalized_session` ON DELETE SET NULL |
| `turn_index` | int | ✓ | NULL | the logical turn number (`personalized_message.payload.turn_no`), for cost-per-turn joins |
| `stage` | text | ✓ | NULL | teach/decide/diagnostic/artifact |
| `model` | text | ✓ | NULL | |
| `input_tokens` / `output_tokens` / `cached_tokens` | int | ✓ | NULL | |
| `first_token_ms` / `latency_ms` | int | ✓ | NULL | |
| `artifact_build` | boolean | ✗ | false | |
| `cache_hit` | boolean | ✗ | false | |
| `outcome` | text | ✗ | 'ok' | CHECK ('ok','model_error','quota_blocked','rate_limited','artifact_failed','cancelled','rejected') |
| `created_at` | timestamptz | ✗ | now | |

Indexes: `(user_id, created_at DESC)`; `(created_at)` for the daily roll-up.
No text, no prompts, no student answers.

### 2.6 `personalized_quota`

Hot counters, same shape/atomicity discipline as `guard_counter`
(`guard/service.py`), scoped to a **00:00 IST** period.

| Column | Type | Null | Default | Notes |
|---|---|---|---|---|
| `period` | text | ✗ | — | `YYYY-MM-DD` in Asia/Kolkata |
| `scope` | text | ✗ | — | CHECK ('user','global') |
| `scope_key` | text | ✗ | — | user id or `'global'` |
| `turns_used` | int | ✗ | 0 | actualized |
| `turns_reserved` | int | ✗ | 0 | in-flight reservations |
| `artifact_used` | int | ✗ | 0 | |
| `artifact_reserved` | int | ✗ | 0 | |
| `state` | text | ✗ | 'ok' | CHECK ('ok','warn','exhausted') |
| `updated_at` | timestamptz | ✗ | now | |

PK `(period, scope, scope_key)`. A turn is admitted only if
`turns_used + turns_reserved < cap` in the same transaction that increments
`turns_reserved`; at `turn.done` the reservation moves to `turns_used`; at
`turn.error` it is released. The global row is updated in the same transaction
as the user row (both or neither). This is the race-free pattern from
`guard/service.py`, with one difference: the two rows commit together (a single
transaction), so the sum can never exceed either cap.

Caps come from config (`ZIVON_PERSONALIZED_*`), not from a table; a founder
change is an env/config change, not a migration.

### 2.7 Migration and registry

- `db/schema_personalized.py` — `PERSONALIZED_TABLES_0005`,
  `get_revision_0005_up_sql`, `get_revision_0005_down_sql` (drop in reverse
  dependency order: message, usage, session, quota, artifact, preferences).
- `db/schema.py::ALL_TABLES` gains the six names; `db/migrate.py` gains the
  revision after `0004_practice_speaking_tests`.
- `testing/backend/test_alembic_migrations.py` gains `0004→head` and
  `head→0004→head` cases; the CI `db-migrations` job runs the same on Postgres.
- The `progress_event.kind` CHECK gains `personalized_mastery` in the same revision. Both
  engines need a real change, not a comment: Postgres takes
  `ALTER TABLE progress_event DROP CONSTRAINT … / ADD CONSTRAINT … CHECK (…)`; SQLite cannot
  alter a CHECK, so 0005 **rebuilds** the table (create `progress_event_new`, copy, drop,
  rename, recreate both indexes) and the down migration reverses it. `db/schema.py`'s
  `progress_event` CHECK is updated in the same PR, so a fresh `upgrade head` and an upgraded
  0004 database agree (the drift gate is the idempotent second `upgrade head` plus the
  schema round-trip test). A `0004→head` test inserts a `personalized_mastery` row after the
  upgrade; that is the assertion that the CHECK actually changed.
- `backend/privacy.py` deletion cascade gains: `user_preferences` (cascade),
  `personalized_session` (cascade → messages), `personalized_usage` (cascade),
  `personalized_quota` rows for the user. Account deletion is hard; only the
  `users` tombstone remains (ADR-0029).
- Retention jobs (in `backend/privacy.py` or a new
  `backend/personalized/retention.py`, called by the existing `run_all_ttl_jobs`):
  1. sessions `last_turn_at < now() - 90d` → delete (cascade messages);
  2. artifacts `ready` and `last_used_at < now() - 30d` and no referencing
     message → delete;
  3. artifacts `failed` and `created_at < now() - 7d` → delete;
  4. usage `created_at < now() - 90d` → delete;
  5. quota periods older than yesterday → delete.

---

## 3. Entities / traceability

| Entity | Table(s) | NEED |
|---|---|---|
| `ENT-PL-Prefs` | `user_preferences` | `NEED-PL-01` account personal instructions |
| `ENT-PL-Session` | `personalized_session` | `NEED-PL-02` session state + resume |
| `ENT-PL-Message` | `personalized_message` | `NEED-PL-03` conversation history/export |
| `ENT-PL-Artifact` | `personalized_artifact` | `NEED-PL-06` artifact build/cache/viewer |
| `ENT-PL-Usage` | `personalized_usage` | `NEED-PL-08` cost/latency ledger |
| `ENT-PL-Quota` | `personalized_quota` | `NEED-PL-04` free-tier fairness |
| — (file index) | `runs/personalized-index/<version>/` | `NEED-PL-05` RAG retrieval |
| — (existing) | `question_bank`, `syllabus_chapter`, `concept` | `NEED-PL-09` bank-first items, coverage |

Every column above traces to one of these needs. No table is "just in case".

---

## 4. API contract

Base: `/v1/personalized` for sessions/artifacts/usage; `/v1/me/preferences` for
preferences. JSON, UTC ISO timestamps, the repo error envelope
(`{code, message_key, trace_id, retryable, retry_after?}`, backend-spec §6).

### 4.1 Auth, CSRF, rate limits (all endpoints)

- **Session:** opaque cookie `zivon_session` validated by `AuthService.resolve`
  (ADR-0029). No bearer token; no query-string tokens.
- **CSRF:** every `POST`/`PUT`/`DELETE` requires `X-CSRF-Token` derived by
  `AuthService.csrf_for`; a missing/invalid token is `403 E-AUTH-CSRF` and
  changes nothing. `GET` requires no CSRF.
- **Guest:** `401 E-AUTH-REQUIRED` for JSON; the HTML pages 303 to
  `/login?next=<path>` (web-shell §4).
- **Rate-limit families** (extend `backend/abuse.py`): `personalized_turn` (6/min),
  `personalized_create` (5/h), `personalized_read` (60/min), `personalized_ip` (20/min).
  The families do not exist yet: `classify_endpoint_family` currently maps every `/v1/*`
  path to the `api` family (30/min), so PL1 adds the mappings and the matching
  `BackendConfig` limits (window size per family, not just per-minute).
  `429 E-RATE-LIMIT` + `Retry-After`.
- **Body caps:** 8 KB for turn/preference bodies; 500 chars for the weakness and
  preferences; 2,000 chars for a follow-up message; 32 fields max.
- **Owner scoping:** every session/artifact query is scoped by `user_id` from
  the session, never from the URL. Another user's id is a **404** (not 403).

### 4.2 Endpoint table

| ID | Method | Path | Purpose | Quota/limit | Errors |
|---|---|---|---|---|---|
| `API-PL-01` | GET | `/v1/me/preferences` | read instructions + max length | read limit | 401 |
| `API-PL-02` | PUT | `/v1/me/preferences` | save (normalize + validate) | 10/h | 401, 403 CSRF, 422, 429 |
| `API-PL-03` | DELETE | `/v1/me/preferences` | clear | 10/h | 401, 403 |
| `API-PL-04` | GET | `/v1/personalized/catalog` | chapters with index coverage + tier | read limit | 401, 503 |
| `API-PL-05` | POST | `/v1/personalized/sessions` | start (chapter/concept/weakness/skip diagnostic) | 5/h; 5/day; quota | 401, 403 CSRF, 422, 403 `E-QUOTA-EXHAUSTED`, 503 `E-CONTENT-UNAVAILABLE` |
| `API-PL-06` | GET | `/v1/personalized/sessions` | list (cursor) | read limit | 401 |
| `API-PL-07` | GET | `/v1/personalized/sessions/{id}` | session + state + last 50 messages | read limit | 401, 404 |
| `API-PL-08` | DELETE | `/v1/personalized/sessions/{id}` | hard delete | 20/h | 401, 403, 404 |
| `API-PL-09` | GET | `/v1/personalized/sessions/{id}/export` | JSON attachment | 10/h | 401, 404 |
| `API-PL-10` | POST | `/v1/personalized/sessions/{id}/turns` | next turn (SSE; JSON fallback) | 6/min; 40/day; concurrency 2; global | 401, 403 CSRF, 404, 409 `E-PL-TURN-OPEN`, 403/503 `E-QUOTA-EXHAUSTED`, 429, 503 model |
| `API-PL-11` | POST | `/v1/personalized/sessions/{id}/end` | end + summary | 20/h | 401, 403, 404, 409 |
| `API-PL-12` | GET | `/v1/personalized/sessions/{id}/messages?before=&limit=` | earlier turns (≤ 50) | read limit | 401, 404 |
| `API-PL-13` | GET | `/v1/personalized/artifacts/{id}` | artifact HTML (sandbox headers) | read limit | 401, 404 |
| `API-PL-14` | GET | `/v1/personalized/artifacts/{id}/status` | pending/ready/failed | read limit | 401, 404 |
| `API-PL-15` | GET | `/v1/personalized/usage` | remaining turns/artifacts + reset | read limit | 401 |

### 4.3 Preferences

`GET /v1/me/preferences` → `200`:

```json
{"personal_instructions": "Explain step by step. Use Hinglish.",
 "max_chars": 500, "updated_at": "2026-11-17T12:00:00.000Z",
 "available": true}
```

`PUT` body `{"personal_instructions": "..."}` → `200` with the normalized value,
or `422`:

```json
{"code": "E-VALIDATION", "message_key": "error.preferences_rejected",
 "field": "personal_instructions",
 "reason": "too_long|contact_details|system_instruction|control_chars",
 "trace_id": "...", "retryable": false}
```

The previous value is untouched on any failure. `DELETE` → `204` (idempotent:
deleting an empty value is still 204).

### 4.4 Session create

`POST /v1/personalized/sessions`:

```json
{"chapter_id": "class-10-light-reflection-and-refraction",
 "concept_ids": ["class-10-...-spherical-mirrors"],
 "weakness_text": "I don't get why the image flips",
 "skip_diagnostic": false,
 "parent_session_id": null}
```

- `chapter_id` required unless `weakness_text` maps to exactly one chapter by a
  deterministic lexical/embedding match over the chapter and concept titles (no
  model call); ambiguous free text → `422` with the chapter picker hint (never a
  guess).
- `concept_ids` optional; must belong to the chapter.
- `skip_diagnostic` starts at the first concept, stage `teach`.
- Response `201`:

```json
{"session_id": "019...", "title": "Light – Reflection and Refraction · Spherical mirrors",
 "stage": "diagnose", "class_level": 10,
 "diagnostic": {"remaining": 3, "first_question": {"check_id": "chk-...", "kind": "mcq", "question": "...", "options": [...]}},
 "quota": {"turns_remaining": 39, "reset_at": "2026-11-17T18:30:00.000Z"}}
```

The first diagnostic question never contains the answer key.

### 4.5 List / detail / history

`GET /v1/personalized/sessions?status=active&limit=20&cursor=...` →

```json
{"items": [{"session_id": "...", "title": "...", "chapter_id": "...",
            "stage": "check", "status": "active",
            "updated_at": "...", "last_turn_at": "...",
            "turn_count": 9, "coverage": {"taught": 2, "total": 6},
            "deletes_at": "2027-02-15T..."}],
 "next": "cursor-or-null"}
```

The list never includes `weakness_text` or message text. `GET .../{id}` returns
the session state, the last 50 messages (oldest first), and `quota`; every
artifact reference carries `src` (the same-origin route, or the signed URL in
dedicated-origin mode) and `status`. `GET .../{id}/messages?before=<turn_index>&limit=50`
pages earlier.

### 4.6 Turns (SSE)

`POST /v1/personalized/sessions/{id}/turns` with the body in
[`agent-and-rag.md`](agent-and-rag.md) §3.2. Response headers:

```
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-store
X-Accel-Buffering: no
```

The event catalogue is agent-and-rag §3.2. A client that sends
`Accept: application/json` gets the assembled turn object instead (same fields).

Turn admission order (all before any model call):

1. session lock (a DB-level row lock where the engine supports it; optimistic `updated_at` compare on SQLite tests);
2. idempotency lookup by `client_turn_id` → replay the stored result; if the row
   exists but the turn is still in flight, return `409 E-PL-TURN-OPEN` (or replay
   the stream) — never start a second model call;
3. rate limit family;
4. quota reservation (user + global, one transaction);
5. state-machine transition validation (e.g. `answer` requires an open check);
6. retrieval;
7. model calls.

Any failure before the model calls releases the reservation and writes a
`quota_blocked`/`rate_limited`/`rejected` usage row only when a quota/rate
decision was made; validation failures write nothing.

### 4.7 End, export, delete

- `POST .../{id}/end` → `200 {status:"completed", summary:{...}}`; idempotent
  (ending a completed session returns the same summary).
- `GET .../{id}/export` → `Content-Disposition: attachment;
  filename="zivon-session-<id>.json"`, body:

```json
{"schema_version": 1, "exported_at": "...",
 "session": {"session_id": "...", "title": "...", "chapter_id": "...",
             "stage": "done", "status": "completed", "created_at": "...",
             "last_turn_at": "..."},
 "preferences": {"personal_instructions": "..."},
 "messages": [{"turn_index": 0, "role": "tutor", "kind": "text",
               "text": "...", "payload": {...}, "created_at": "..."}],
 "mastery": [{"concept_id": "...", "status": "mastered", "attempts": 4,
              "first_try_correct": 1, "levels_passed": [1,2,3]}],
 "artifacts": [{"artifact_id": "...", "kind": "simulation", "title": "..."}]}
```

No other user's data, no prompts, and no answer keys: a check that was **never submitted**
exports without its key, while a submitted check carries the `expected` value the student
already saw in the feedback.

- `DELETE .../{id}` → `204`; hard delete in one transaction: messages,
  session, artifact references (message rows cascade), usage `session_id` set
  NULL; the shared artifact rows remain for the refcount job.

### 4.8 Artifact fetch

`GET /v1/personalized/artifacts/{id}`:

- Same-origin mode: requires a session; the artifact must be referenced by a
  message in one of the caller's sessions, or the caller must be an admin
  (separate admin auth).
- Dedicated-origin mode: the session/detail serializer (and
  `turn.artifact.ready`) returns a signed `src` `?token=<HMAC>&exp=<unix>`
  (10-minute TTL, `artifact_id|user_id|exp`, constant-time verify, issued only
  after the reference check). The token is not a session credential and is never
  logged. The `src` is the only URL the viewer uses; there is no client-side URL
  construction.
- Returns the HTML with the headers in
  [`interactive-artifacts.md`](interactive-artifacts.md) §5.2.
- A `failed`/`pending` artifact returns `409 E-CONFLICT` with
  `{status, failure_reason}` (the client shows the fallback/loader).
- gzip is fine (the HTML is text); range requests are not offered.

### 4.9 Usage

`GET /v1/personalized/usage` →

```json
{"turns": {"used": 3, "cap": 40, "remaining": 37, "state": "ok"},
 "artifacts": {"used": 1, "cap": 12, "remaining": 11},
 "global": {"state": "ok"},
 "reset_at": "2026-11-17T18:30:00.000Z",
 "enabled": true}
```

`enabled:false` is the kill-switch read-only state; the UI disables Start.

### 4.10 Error additions

| Code | Status | Meaning | Student copy key |
|---|---|---|---|
| `E-QUOTA-EXHAUSTED` | 403 (user) / 503 (global) | daily turns or artifacts used up | `error.pl.quota_user` / `error.pl.quota_global` |
| `E-CONTENT-UNAVAILABLE` | 503 | index missing/stale or chapter unsupported | `error.pl.content` |
| `E-PL-TURN-OPEN` | 409 | a check is open; submit it first | `error.pl.turn_open` |
| `E-PL-MODEL-DOWN` | 503 | model route unavailable | `error.pl.model_down` |
| `E-PL-PREFS-REJECTED` | 422 | instructions rejected (reason field) | `error.pl.prefs_rejected` |

`E-RATE-LIMIT`, `E-AUTH-REQUIRED`, `E-AUTH-CSRF`, `E-NOT-FOUND`,
`E-VALIDATION`, `E-CONFLICT`, `E-SERVICE-UNAVAILABLE` already exist.

### 4.11 Reports (reuse, with two existing constraints)

Turn and artifact reports reuse `POST /v1/reports` (`backend/routes/student.py`) and
`problem_report`; no new endpoint and no schema change. Two constraints of that route are
binding here and must be honoured by PL4's UI:

- `category` must be one of the existing four (`wrong_physics`, `bad_translation`,
  `broken_sim`, `other`), so an artifact report sends **`broken_sim`** and a wrong-physics
  teaching report sends `wrong_physics`. A new `artifact` category would be a CHECK
  migration (not in 0005) — do not assume it.
- `course_id` is **required** (the handler also accepts `page_id`). A session carries a
  `chapter_id`, not always a course: send the chapter's published lesson course id when
  one exists, otherwise `personalized/<chapter_id>` as a non-catalogue namespace key, and
  the artifact/turn id in `block_id`. Reports stay optional-device-scoped as today; the
  account id is not added to the row.

---

## 5. Voice-tutor prompt assembly change (personal instructions)

### 5.1 What changes

| File | Change |
|---|---|
| `voice/brain_client.py` | `BrainRequest` gains `personal_block: str = ""`. `build_messages` puts the block in the **user-role** data section (before `PAGE CONTEXT`, in the same assembled user message), never as a `system` message — see §5.2 for why. |
| `voice/ws_api.py` | On the first `session.start` (or lazy at the first brain call), resolve the optional account cookie with `AuthService.resolve` (the monolith mounts auth). Store `account_user_id` on the session. Load preferences once per session (60 s cache), sanitize with the shared helper, set `BrainRequest.personal_block`. |
| `voice/config.py` | `ZIVON_VOICE_PERSONAL_INSTRUCTIONS_ENABLED` (default `true` once PL2 lands; `false` disables injection without touching the store). |
| `backend/personalized/personalization.py` | New shared helper: `normalize(text)`, `validate(text)`, `personal_block(text)`, `SAFETY_CORE` constant + `assert_safety_parity(prompt_a, prompt_b)` used by the test. |
| `voice/session.py` | No schema change; the account link is runtime state (like the snapshot). |

### 5.2 Rules

- **The voice path cannot use a second system message.** `_GeminiStreamFactory.__call__`
  (`voice/brain_client.py`) joins every `role == "system"` message into one
  `system_instruction` string and turns the rest into `user`/`model` contents. A second
  system message would therefore (a) merge into the same privileged instruction, and
  (b) promote student-authored text into the system slot — the opposite of the intended
  precedence. The block rides as a delimited **user-role** data section instead:
  `STUDENT-AUTHORED PREFERENCES (data, lower priority than the rules above): <<< … >>>`,
  placed before the page-context block. The PL (OpenAI-format) path keeps the real second
  system message (`messages[1]`), because that transport preserves roles.
- Guests: no cookie → no block; behaviour is byte-identical to today.
- Auth down: the voice session works without the block and logs a count (never
  the error text as student copy).
- The block is **not** stored in `voice_turn`; it is not a transcript.
- The block never contains session state, page context, or prior messages.
- A saved instruction change applies at the next turn (the 60 s cache bounds the
  staleness); the settings page says "from your next question", not
  "immediately".
- The safety-core parity test asserts the exact sentences are present in
  `voice/ws_api.py::TUTOR_SYSTEM_PROMPT` and
  `backend/personalized/prompts.py::TEACH_SYSTEM`.
- A voice assembly test asserts the personal block text appears **nowhere** in the
  joined `system_instruction` / `BrainRequest.system`, so the precedence claim cannot
  silently regress with a transport change.

### 5.3 Protocol impact

None. The WS message catalogue, binary framing, close codes, and the 4 s voice
budget are unchanged. The extra user-role section adds ≤ 500 chars (~125 tokens)
to a turn only when the student saved preferences.

---

## 6. Test seams (deterministic)

| Seam | How tests fake it |
|---|---|
| Model route | inject a fake `LLMManager`/stream factory (no network) — the same pattern as `testing/voice/mocks/` |
| Embedder | `FixtureEmbedder`-style hashing vectors for retrieval tests; a fixed index fixture |
| Clock/period | inject the IST period key so quota-reset tests are deterministic |
| Artifact renderer | a fake render report for the builder; Playwright only in the artifact/eval suites |
| Auth | SQLite in-memory + `AuthService` as in `testing/backend/web_auth_support.py` |
| CSV/export | compare JSON against a schema, not a golden blob (ids/timestamps vary) |

No test requires a key, a network call, or a live model.
