# Speak it back — explain-back hub, recorder, and history (F6)

Status: implementation contract for the W4 F6 slice (landed 2026-11-17, branch
`feature/w4-f6-speaking`, based on `main` @ `63ea560`). It describes code that
exists: `backend/speaking/`, `backend/routes/speaking.py`,
`web/speaking_views.py`, `web/routes/speaking.py`, the three app templates,
`frontend/assets/app-speaking.css` + `frontend/assets/app-speaking.js`, and the speaking rows already provided
by `backend/assessment/store.py` (W4 data foundation).

Consumes: `docs/specs/frontend/web-shell.md` (route/guard/template seam),
`docs/frontend/design-doctrine.md` §0–§9 (base Field Notes only; no §10 lesson
device), `docs/backend/db-spec.md` §4.19 (`speaking_prompt` /
`speaking_attempt`), `docs/content-factory/assessment.md` §4.5 (the authored
rubric), REQUIREMENTS §8.2/§9.5/§10.9/§10.10.

Out of scope and owned elsewhere: practice (F5), tests/series (F7), the lesson
voice dock (F4/EX1), UI translation, admin (F10). The dashboard quick-action
copy still says “Explain-back — not live yet”; changing `dashboard.html` is
F3's file (handoff recorded in §10).

## 1. Routes and code paths

| Route | Surface | Code |
|---|---|---|
| `/app/speaking` | SSR hub: chapter prompts, last attempt, start links | `web/routes/speaking.py`, `web/templates/app/speaking/hub.html` |
| `/app/speaking/{prompt_id}` | SSR recorder + one JS island | `web/routes/speaking.py`, `web/templates/app/speaking/recorder.html`, `frontend/assets/app-speaking.js` |
| `/app/speaking/history` | SSR attempt history + delete island | same route module, `web/templates/app/speaking/history.html` |
| `GET /v1/speaking/prompts` | JSON: servable prompts, answer material withheld | `backend/routes/speaking.py` |
| `POST /v1/speaking/attempts` | JSON: one transient WAV upload → transcript + rubric + model answer | same |
| `GET /v1/speaking/attempts` | JSON: owner’s attempts, newest first | same |
| `GET /v1/speaking/attempts/{id}` | JSON: one attempt + the prompt material it unlocks | same |
| `PATCH /v1/speaking/attempts/{id}` | JSON: save the self-check choice (additive to §9.5) | same |
| `DELETE /v1/speaking/attempts/{id}` | JSON: hard delete transcript + feedback | same |

The pages extend `base.html`, load `/assets/product.css`, then
`/assets/app.css` and `/assets/app-speaking.css`; the recorder and history also
load `/assets/app-speaking.js` with `defer`. The nav gains `Speak` in the same
PR that lands the route (`web/nav.py`). Pages are `noindex`, `no-store`, and
render no `zn-` lesson class.

## 2. JSON contracts

All endpoints are authenticated with the F0 account cookie. Every write
(`POST`, `PATCH`, `DELETE`) requires `X-CSRF-Token`; a missing/invalid token is
`403 E-AUTH-CSRF`. The `/v1/*` rate-limit family (30/min per IP hash) applies.

### 2.1 `GET /v1/speaking/prompts?chapter=&language=`

`language` is the pack vocabulary `en` | `hi` | `hi-Latn` (default `en`); an
unknown value is `422 E-LANGUAGE-INVALID`. `chapter` is optional.

```json
{"schema_version": 1, "language": "en", "count": 3,
 "items": [{"prompt_id": "spk-c9-motion-001", "language": "en",
            "chapter_id": "class-9-describing-motion-around-us",
            "class_level": 9, "concept_ids": ["…"],
            "prompt": "Explain the difference between distance and displacement…",
            "key_idea_count": 4,
            "rubric": {"max_duration_s": 45, "min_key_ideas": 3,
                       "pass_ratio": 0.6, "strong_ratio": 0.85},
            "version": 1}]}
```

`key_ideas` and `model_answer` are **never** in this payload: they are the
expected answer, and the list is readable before an attempt.

### 2.2 `POST /v1/speaking/attempts?prompt_id=&language=`

Body: **raw** `audio/wav` (not multipart), canonical 16 kHz mono PCM16. The
browser builds it from raw Web Audio PCM; the server never decodes a compressed
container. Headers:

| Header | Required | Meaning |
|---|---|---|
| `Content-Type: audio/wav` | yes | `audio/x-wav`, `audio/wave`, `application/octet-stream` also accepted |
| `X-CSRF-Token` | yes | F0 session-derived CSRF token |
| `X-Device-Id` | yes | the same UUID4 device pseudo id used by `PUT /v1/consent` |

The edge proxy allows this one path 4 MB and a 90 s read timeout
(`docker/nginx.conf` exact location `= /v1/speaking/attempts`: STT + the brain's
bounded deadline can exceed nginx's 60 s default); the route's own cap is
3,000,000 bytes (`413 E-SPEAKING-AUDIO-SIZE`). `client_body_buffer_size` is
8m there, i.e. larger than the 4m cap, so nginx proxies the upload from memory
and never spools audio to `client_body_temp_path` — "no audio is persisted" is
true at the edge, not only inside the route. Duration is 0.8–60 s and
≤ the prompt’s `max_duration_s + 5 s` (`422 E-SPEAKING-AUDIO`); no samples, a
wrong rate, stereo, or compressed audio is `422`/`415 E-SPEAKING-AUDIO`. Audio
is held in memory for one request, streamed to Prisma as 100 ms frames, and
dropped; no temporary file exists on either hop.

Success `200`:

```json
{"mock": false,
 "attempt": {"attempt_id": "…", "prompt_id": "…", "language": "en",
             "transcript": "…", "rubric_scores": {"ideas_present": 3,
             "ideas_total": 4, "ratio": 0.75, "band": "pass",
             "ideas": [{"idea_id": "…", "present": true, "evidence": "…"}]},
             "feedback": {"band": "pass", "label": "AI feedback",
                          "what_went_well": "…", "next_step": "…",
                          "model": "gemma-4-26b-a4b-it", "mock": false},
             "self_check": {}, "score": 75.0, "duration_ms": 38000,
             "created_at": "…Z"},
 "prompt": {"prompt_id": "…", "prompt": "…", "key_ideas": [{"idea_id": "…",
            "text": "…", "concept_id": "…"}], "model_answer": "…",
            "model_answer_source": {"book_id": "ncert-science-9",
                                     "section": "4.1.2", "example": "Fig. 4.4"}},
 "evaluation": {"band": "pass", "band_label": "Clear explanation",
                "band_note": "…", "ideas_present": 3, "ideas_total": 4,
                "ratio": 0.75,
                "key_ideas": [{"idea_id": "…", "text": "…",
                               "concept_id": "…", "present": true,
                               "evidence": "…"}],
                "what_went_well": "…", "next_step": "…", "mock": false},
 "evaluation_error": null, "notice": null}
```

Error states are honest, not fabricated:

| HTTP | Code | Meaning / UI |
|---|---|---|
| `403` | `E-CONSENT-REQUIRED` / `E-CONSENT-STALE` | no stored voice consent for this device, or an older notice version; the recorder reopens the gate. No frame was read. |
| `404` | `E-SPEAKING-PROMPT-UNKNOWN` | the prompt id is unknown, or (prompt, language) is not served (`draft`/`retired`); refused before the body is read, so no vendor call is made. |
| `429` | `E-QUOTA-EXHAUSTED` | the existing `CreditGuard` refused the reserve; STT was never called. |
| `422` | `E-SPEAKING-NO-SPEECH` | Prisma returned an empty final; no attempt row is written. |
| `503` | `E-SPEAKING-UNAVAILABLE` | STT or the tutor model is not configured (and mock mode is off). |
| `503` | `E-SERVICE-UNAVAILABLE` | Prisma/model transport failed, or the deployment has no credit guard; retryable, nothing saved, and an unmetered deployment never transcribes. |

If STT succeeds but the rubric call fails or returns an unusable verdict, the
**real transcript is still saved** and the response carries
`"evaluation": null`, `"evaluation_error": {"code": "E-SPEAKING-EVALUATION",
"retryable": true}`, and a `notice`. The UI labels that state; it never invents
a band.

### 2.3 Attempt reads, self-check, delete

- `GET /v1/speaking/attempts?prompt_id=&limit=` → `{schema_version, count,
  items:[attempt]}`; owner-scoped, newest first, `limit` 1–50.
- `GET /v1/speaking/attempts/{id}` → `{attempt, prompt}` where `prompt` is the
  full authored prompt (the attempt is the gate that unlocks the answer
  material). Unknown or someone else’s id → `404 E-NOT-FOUND`.
- `PATCH /v1/speaking/attempts/{id}` body `{"choice": "explained_fully" |
  "missed_a_part" | "practise_again"}` → `{attempt}`; any other value is
  `422 E-VALIDATION`. The store function is
  `set_speaking_self_check` (owner-scoped, bounded JSON). This is additive to
  REQUIREMENTS §9.5, which lists no PATCH; the recorder spec asks for a
  self-check, and it belongs to the saved attempt.
- `DELETE /v1/speaking/attempts/{id}` → `{"ok": true, "removed": true}`;
  a hard delete (no tombstone, no free text left). Repeat/unknown → `404`.

## 3. Pipeline: reused voice clients, no parallel vendor path

| Stage | Client | Config |
|---|---|---|
| STT | `voice.stt_client.SttClient` (Prisma v3.0 realtime) | the `ZIVON_VOICE_STT_*` family + `GNANI_PRISMA_API_KEY` |
| Rubric | `voice.brain_client.BrainClient` on the tutor model (Gemma 4 26B A4B via the Gemini API by default) | `ZIVON_VOICE_BRAIN_*` + `ZIVON_VOICE_GEMINI_API_KEY` |

`backend/speaking/pipeline.py` streams the upload as the voice loop’s 100 ms
PCM16 frames, sends `commit`, and waits for the final `transcript` event while
sending (full-duplex read). The rubric call is one bounded brain call with the
prompt, the authored key ideas, and the verbatim transcript in a delimited data
block. The model returns presence per key idea; `backend/speaking/rubric.py`
validates it and **computes the band in code** from the authored
`pass_ratio`/`strong_ratio`. The model never decides a score, and the UI never
shows a percentage — it shows `n of m key ideas` and a band label.

**Mock / test mode.** `ZIVON_SPEAKING_MOCK=1` makes the pipeline return a
clearly labelled sample transcript and a demo rubric (`mock: true` in the API,
a visible demo banner on the page, “Demo mode sample” evidence). It is refused
in every deployed environment — `ZIVON_ENV=cluster` (what
`k8s/28-backend-config.yaml` ships) and
`ZIVON_ENV=prod` (the promotion value) both count, and any other non-dev/test
value is treated as production too — with `speaking.mock.refused`, and the
shipped default is off. If the live credentials are absent and mock is off, the
route answers `503 E-SPEAKING-UNAVAILABLE`; it never fabricates a transcript.

**Credit guard.** The existing `guard.CreditGuard` is reserved **before** STT on
the same device scope as the voice gate: points =
`ceil(duration_s / ZIVON_VOICE_CREDIT_STT_SECONDS_PER_POINT)`, at least one.
The ledger records the actual seconds with `model=prisma`. The brain call is
the user-facing Gemini path and is not a Gnani credit. A refusal is
`429 E-QUOTA-EXHAUSTED` and STT is not called. The route fails closed when
`app.state.guard` is absent (`503 E-SERVICE-UNAVAILABLE`): a deployment defect
must not turn into an unmetered vendor path.

## 4. Consent and privacy

- The consent gate is the **existing device-scoped voice gate**, not a second
  one. The recorder reads `localStorage["zivon.consent"]` (the same key the
  lesson dock writes), shows the same notice copy plus one explain-back line,
  and records `granted`/`declined` through `PUT /v1/consent` with the page’s
  current `notice_version` and `consent_version`.
- The API **re-checks the stored row** before reading the body: latest
  `consent_record` for `X-Device-Id` must be `granted` with the current notice
  version. A missing or stale row is `403`; no frame is read.
- The mic button ships `disabled`; the island enables it only after the local
  state is `granted`, the browser supports capture, and the pipeline is
  available. With JavaScript off there is no capture path at all.
- **No audio is persisted.** `speaking_attempt` has no audio column; no file,
  object-storage key, or temporary path is created. The upload lives in memory
  for one request. The attempt row is transcript text + bounded rubric/feedback
  JSON + the self-check choice, owner-scoped and hard-deletable.
- Logs carry ids, counts, bands, and latency only. Transcript text, prompt
  text, and audio bytes are never fields (the instrumentation map’s required
  fields are enforced by review; `audio_*` field names are on the redaction
  denylist, which is why the request uses `duration_ms`/`upload_bytes`).

## 5. Screen states

### `/app/speaking` hub

| State | What the student sees |
|---|---|
| default | chapter-grouped prompt rows with key-idea count, language, last attempt, Start/Try again; a “last attempt” summary; “How explain-back works” disclosure |
| loading | n/a — SSR completes before bytes |
| empty | “No explain-back prompt is loaded for your class yet.” + catalogue link; no invented rows |
| partial | a prompt missing the requested language is shown in English with a visible “not loaded yet” note (also the case for Hinglish/Hindi) |
| error | panel `notice--error` + retry link; no prompt list |
| offline | n/a server-side; the browser’s offline page |
| permission-denied | guest → `303 /login?next=/app/speaking` |
| reduced-motion | no hub animation |
| untranslated | English UI copy; the prompt itself may be Hindi/Hinglish; a missing variant is disclosed |
| quota-exhausted | not a hub state; quota is enforced on submit and shown in the recorder |

### `/app/speaking/{prompt_id}` recorder

| State | What the student sees |
|---|---|
| default | prompt header, 45 s limit, disabled mic until consent/support, timer, waveform, status, result region, earlier attempts |
| loading | the island initializes after SSR; the mic stays disabled with a status line until then |
| empty (no attempt) | “Your feedback appears here after your first recording.”; key ideas and model answer are absent from the HTML |
| partial (evaluation failed) | transcript + model answer + “Your transcript is saved; the AI feedback could not be generated”; no invented band |
| error | coded states: mic denied / no device / busy / unsupported browser; upload/format/transport; each names what was and was not saved |
| prompt not served | an unknown, draft, or retired prompt renders the 404 “That prompt is not available” page — no recorder, no consent request, nothing captured |
| offline | the upload fails with “could not be sent … Nothing was saved”; no optimistic result |
| permission-denied | consent missing → in-flow gate; declined → “Voice is off on this device” + explicit review button (no re-nagging) |
| reduced-motion | the waveform still shows level (information), the pen-blue live bar is omitted; no transitions |
| untranslated | prompt language is labelled; missing variant note |
| quota-exhausted | “Voice is resting for today’s limit. Nothing was recorded.” |
| mock | a visible demo banner; result is labelled a sample |
| mic unavailable | STT unconfigured or no capture support: the mic is disabled with the reason and the consent card is not shown (no consent is asked for a microphone that cannot be used) |

### `/app/speaking/history`

| State | What the student sees |
|---|---|
| default | newest-first attempts: date, language, chapter, prompt, band, key-idea count, disclosure with transcript/feedback/model answer, Delete |
| loading | n/a — SSR |
| empty | “No explain-back attempt saved.” + prompt link |
| partial | an attempt whose prompt is no longer served (retired status, or the row is gone) keeps the stored transcript/feedback, shows “Prompt no longer served”, and withholds the model answer |
| error | panel error + retry; no invented attempts |
| offline | n/a server-side; delete failure is announced and nothing is optimistically dropped |
| permission-denied | `303 /login?next=/app/speaking/history` |
| reduced-motion | no animation |
| untranslated | English UI copy; attempt language shown |
| quota-exhausted | n/a |

## 6. Accessibility and 360 px

- One `<h1>`; landmarks and the skip link come from the shell.
- Mic button: native `<button>`, `aria-pressed` reflects recording, disabled
  state is real, 56 px min height.
- Timer is `aria-hidden` (a per-second live region would flood a screen
  reader); a visually hidden `role="status"` announces start / 10 seconds left
  / stop. The visible status line is `role="status" aria-live="polite"`.
- Waveform is a decorative `<canvas aria-hidden="true">`; every state that
  matters is in text.
- Result: band is text + colour, each key idea carries the words “Covered” /
  “Missing” (never colour alone); the AI-feedback tag is text.
- Keyboard: every control is native; delete confirms; focus moves to the result
  card (`tabindex="-1"`) when feedback arrives.
- 360 px: `.speak-layout` becomes one column at 960 px; rows stack at 480 px;
  targets ≥ 44 px; no horizontal overflow; `prefers-reduced-motion` removes the
  only transient accent.
- `docs/specs/frontend/state-matrix.md` APP-11–APP-13 carry the state rows.

## 7. Events

All server-side through `logging_manager` (rows in
`docs/specs/observability/instrumentation-map.csv`, component `speaking`):
`speaking.prompts.listed`, `speaking.attempt.started`, `.transcribed`,
`.evaluated`, `.evaluation_unavailable`, `.no_speech`, `.failed`, `.saved`,
`.self_check`, `.deleted`, `.ledger_failed`, `speaking.consent.blocked`,
`speaking.quota.blocked`, `speaking.mock.refused`. `.started` is emitted after
the quota reserve, so it counts attempts that will reach a vendor. No
transcript, prompt, or audio fields.

## 8. Tests

| Suite | Command | Covers |
|---|---|---|
| API + pages | `python3 -m unittest testing.backend.test_speaking_api -v` | prompt withholding, consent/stale/CSRF, device header, bounds, no-speech, evaluation fallback, mock, quota, owner-scoped get/patch/delete, all three pages, 404, a11y/360 static contracts |
| pipeline | `python3 -m unittest testing.backend.test_speaking_pipeline -v` | WAV parser/bounds, frame shape, credit points, rubric mapping/bands/fallbacks, fake Prisma transport, fake brain stream, mock mode and prod refusal |
| island | `python3 -m unittest testing.frontend.test_speaking_island -v` | real Chromium fake mic: consent gate, WAV upload shape/headers, result rendering, quota state, delete |
| map | `python3 -m unittest testing.observability.test_events -v` | every new event resolves to a row |

All key-free and offline (the browser test uses Chromium’s fake device).

## 9. Environment

| Variable | Default | Meaning |
|---|---|---|
| `ZIVON_SPEAKING_MOCK` | off | dev/test sample transcript + demo rubric; refused in `ZIVON_ENV=prod` |
| the `ZIVON_VOICE_STT_*`, `ZIVON_VOICE_BRAIN_*`, `GNANI_PRISMA_API_KEY`, `ZIVON_VOICE_GEMINI_API_KEY` family | shipped voice defaults | the same clients/config as the voice loop |

No new secret and no new dependency: the upload is raw WAV, so no
`python-multipart`; the STT/brain clients already ship in the backend image.

## 10. Known debt and handoffs

1. **Dashboard copy (F3).** `web/templates/app/dashboard.html` still says
   “Two steps are not live yet” and “Explain-back — not live yet”. The route and
   nav entry now exist; F3 owns that template and should link `/app/speaking`.
   The F3 test’s dead-route list was updated to stop treating `/app/speaking`
   as a 404.
2. **Rubric calibration.** The band is deterministic, but “present” is a model
   judgement. Before R1 this needs a small labelled set of explain-back
   transcripts per language (EN/HI/Hinglish) and a reviewer calibration pass;
   the current prompt is a contract, not a calibrated judge.
3. **Real-device verification.** The browser test uses Chromium’s fake device.
   Echo, background noise, and 45 s captures on a low-end Android need a live
   check with real Prisma credentials (founder/infra window); the code is the
   shipped voice clients, not a test double.
4. **Quota scope.** Speaking reserves on the device pseudo id (the same scope as
   the voice dock), because that is the existing guard key. When voice moves to
   account linking, unify the scope; a student on two devices currently has two
   device buckets, as with the dock.
5. **Reserve on failure.** The guard reserves before STT (the voice loop's
   order). If Prisma then fails, the one-point reservation is not refunded;
   the guard counter stays authoritative and the ledger records only completed
   calls. A refund helper is a guard-owned change if the accounting gap matters
   at higher volume.
6. **PATCH extension.** REQUIREMENTS §9.5 lists GET/POST/DELETE; the
   self-check needs a small PATCH. It is additive and documented here; if a
   later contract freeze forbids it, the self-check can be folded into the POST
   as a client pre-selection.
7. **Retention copy.** The consent notice says “short text transcripts expire
   after 7 days” (the voice-turn retention). `speaking_attempt` is kept until
   the student deletes it or the account is deleted (`db-spec` §4.19 retention
   table). The notice’s explain-back line discloses the difference; a unified
   retention statement belongs to the privacy copy owner.
