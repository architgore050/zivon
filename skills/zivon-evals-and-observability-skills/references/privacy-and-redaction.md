# Privacy and redaction — child-data rules for logs and evals

Sources: `docs/specs/observability/spec.md` §4/§6, `logging-api.md` §6,
`logging_manager/redact.py`, `logging_manager/store.py`, `backend/routes/student.py`
(ingest/report validation), `evals/store.py` (kid-session validation),
`docs/backend/` (A-02, ADR-0011/0025). Verified 2026-11-14 at `main` @ `57147bb`.

Zivon's users are children. Privacy is an architecture constraint, not a logging preference:
the safe default is **no learner content in telemetry or eval artifacts**, and the harness
enforces it mechanically. A redaction violation is a review blocker, not a warning to triage
later.

## 1. The one-sentence rule

Log **what happened, to which ids, how long it took, and which enum it fell into** — never
what the child said, what the page said, what the model was asked, or what it answered.

## 2. Never in `fields` (key denylist)

Case-insensitive exact keys and prefixes (from `logging_manager/redact.py`):

```
transcript*  text       content    prompt     messages   response
completion   answer     page_html  code       patch      audio*
wav          pcm        speech*    utterance* cookie     token
secret       key        authorization
```

A hit is replaced with `[REDACTED:key-denylist]` and emits `log.redaction_violation`
(WARNING, `privacy_violation`) with `{event_ref, key, kind}` only. Deduplicated per call site
(first + every 100th), so a chatty bug does not flood the store.

"Just for debugging" is the canonical violation. If you need the words to debug, join the
event's `session_id`/`turn_id` to the transcript DB row (`transcript_row_id`, 7-day TTL) —
outside the log store.

## 3. Sanctioned reference fields

Checked before the denylist, so they are safe by name:

`transcript_row_id`, `artifact_path`, `block_id`, `topic`, `chapter`.

Also fine: `run_id`, `session_id`, `turn_id`, `request_id`, `client_session_id`,
`eval_run_id`, `course_id`, `class_level`, `stage`, `provider_code`, `reason_code`,
`error_kind`, `language_mix`, counts, durations, booleans, and enum strings.

Use `artifact_path` for build-time evidence paths (`runs/<run_id>/06-render/...`) — they are
not child data. Use `transcript_row_id` for a DB reference — never the transcript itself.

## 4. Allowed learner-shaped aggregates

Only numbers and enums:

`duration_ms`, `char_count`, `language_mix` (e.g. `hi-en`), `turn_count`, `partial_count`,
`attempts`, `correct` (bool), `interactions`, `dwell_bucket` (`<5s|5-30s|>30s`),
`duration_bucket` (`<2m|2-10m|>10m`), `error_kind` (`js|mic_permission|network|voice`).

Never a free-text string that could contain a name, a school, or a sentence the child said.
The ingest endpoint rejects a string longer than 256 characters and any forbidden key in a
frontend payload (see §5).

## 5. Frontend events

- Privacy class **L2** for the `EVT-F01..F12` rows: pseudonymous usage telemetry.
- Required properties are ids/enums (`topic`, `block_id`, `section_id`, `session_id`,
  `client_session_id`, `turn_id`, buckets). No transcript, no stack trace, no page text.
- Ingest (`POST /api/v1/events`) rejects keys in `FORBIDDEN_FREE_TEXT_PROP_KEYS`:
  `transcript`, `student_transcript`, `tutor_text`, `text`, `free_text`, `message`, `audio`,
  `raw_audio`, `pcm`, `wav`, `name`, `email`, `phone`, `prompt`, `utterance`; and any string
  value longer than 256 characters.
- Rejections emit `voice.events.ingest_rejected` (WARNING, `client_error`) with a count only —
  never the rejected payload. The spec/map declare sampling at 1/10; the current endpoint emits
  once per rejected batch. Verify the sampling status before treating the volume as a metric.
- The page must keep working when a beacon is dropped. Telemetry never blocks a turn.

## 6. Eval artifacts

- **Goldens are build-time content artifacts.** `expected.json`, `source_pack_meta.json`, and
  `artifact_ref.json` contain source provenance and invariants — no child data. Never put a
  kid quote, name, school, or audio/video path in a golden or a seeded defect.
- **Eval issue messages** may quote the source text or the generated page (that is the point of
  grounding). They must not quote a child. `evals_runs/` is gitignored; do not paste its
  contents into a public doc or PR comment beyond the aggregate summary.
- **Kid sessions** are the only eval artifact with a child-adjacent payload. `record_kid-test`
  validates it before writing:
  - forbidden keys: `name`, `student_name`, `child_name`, `full_name`, `first_name`,
    `last_name`, `email`, `phone`, `mobile`, `dob`, `date_of_birth`, `birth_date`, `age`,
    `school`, `school_name`, `address`, `ip`, `ip_address`, `device_id`, `aadhaar`;
  - `notes` may not contain an email or an Indian phone number;
  - no audio/video file path anywhere in the payload (`.wav/.mp3/.m4a/.ogg/.aac/.flac/.mp4/
    .webm/.mov`);
  - `session_code` matches `^kid-[a-z0-9-]+$`; `confusion_blocks` are `b-NN` ids.
- **Human-edit records** contain course/topic, line counts, and an edit ratio — no names, no
  page text. Keep `notes` free of PII.
- **Reports** (`POST /v1/reports`) are a separate path: the backend rejects `name`,
  `student_name`, `guardian_name`, `email`, `phone`, `mobile`, `contact`, `address`.

## 7. Deletion (DPDP, 24-hour guardian path)

`logging_manager.delete_subject(session_id)`:

1. deletes every hot `log_events` row for that pseudonymous session;
2. rewrites the fallback JSONL files without that session's rows;
3. writes exactly one `privacy.subject_deleted` L3 event with ids/counts, `status`, and `ok`;
4. reports failure honestly (an unreachable hot store yields `status=failed`,
   `error_class=store_error`), because a silent success misses the 24-hour SLA.

Transcripts live in their own DB rows with a 7-day TTL and raw audio is never referenced from
logs, so no second deletion path is needed. Do not invent one. Eval goldens are build-time and
contain no child data; deleting a subject does not require touching them.

## 8. Review blockers

Treat these as **blocker** findings:

- A denylisted key, learner text, prompt/response, or secret in a `fields` payload.
- A frontend event carrying free text, a transcript, or a stack trace.
- A kid-session payload with a forbidden PII key, an email/phone in `notes`, or an audio/video
  path.
- A golden or seeded defect containing a child's words or identity.
- A new deletion path that bypasses `delete_subject`, or a swallowed deletion failure.
- A redaction test weakened or removed to make a payload pass.

Treat these as **major**:

- A field that is technically allowed but unnecessary for the event's purpose (data
  minimisation).
- A `privacy_class` that is lower than the event's real sensitivity (e.g. an L3 audit event
  declared L1).
- A new learner-shaped aggregate that is not an enum or a number.

## 9. Safe examples

```python
# Good: ids, counts, enums, timing.
log_event(
    "voice.turn.e2e_latency",
    {"slowest_hop": "tts_first_audio", "stt_final_ms": 540, "language_mix": "hi-en"},
    latency_ms=3410,
)

# Good: a reference, not the words.
log_event(
    "voice.stt.final",
    {
        "transcript_row_id": row_id,
        "char_count": 84,
        "partial_count": 2,
        "language_mix": "hi-en",
    },
)

# Bad: the child's words, the prompt, and a secret-shaped value.
log_event("voice.stt.final", {"transcript": "sir yeh force kya hai", "prompt": "..."})
```

## 10. Verification

```bash
python -m unittest discover -s testing/observability -t .   # redaction + schema + map
python -m unittest discover -s testing/evals -t .           # kid-session + store validation
```

A local check of one payload:

```python
from logging_manager.redact import redact_fields

clean, violations = redact_fields({"transcript_row_id": "t-1", "text": "hello"})
assert clean["transcript_row_id"] == "t-1"
assert clean["text"] == "[REDACTED:key-denylist]"
assert violations == [("text", "key-denylist")]
```
