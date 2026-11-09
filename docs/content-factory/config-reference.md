# Configuration reference

Configuration has two layers, deliberately separate:

1. **`config.json` at the repo root** — the pipeline's *behaviour*: learner,
   retrieval, limits, paths, perf, repair, stage_overrides. Committed,
   reviewable, identical on every machine. Validation is strict: unknown keys
   and wrong types are hard errors.
2. **Environment variables** — everything about *which inference server to
   talk to*. Per AGENTS.md ("configuration lives in environment variables")
   and the deployment rule (secrets enter runtime only), these never appear
   in any file, image, manifest, or run artifact. Missing required variables
   is the tripwire: the pipeline refuses to start without them.

Tests can point at another behaviour file with the `ZIVON_CONFIG` environment
variable; production always uses the repo root `config.json`.

## Server (environment variables)

Since 2026-11-07 model calls run through the shared `llm_manager` module
(streaming by default; see `llm_manager/README.md` and the architecture doc,
"Model calls: the llm_manager node"). The same variables configure BOTH
sides of the topology - the llm-manager node (its upstream is the inference
router in containers/cluster) and the factory (its upstream is the node in
the cluster, or the server directly on a local host):

    factory -> llm-manager node -> (inference router) -> inference server

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ZIVON_BASE_URL` | yes | — | OpenAI-format base, e.g. `http://127.0.0.1:8000/v1`. `/chat/completions` is appended. WHAT it points at depends on the plane: locally the server (or the node on `:18090`); in the cluster the llm-manager Service for the factory, and the router for the node (see `k8s/infra.env`). |
| `ZIVON_MODEL` | yes | — | Model name exactly as your server reports it (e.g. via `GET /v1/models`). |
| `ZIVON_API_KEY` | no | unset | The key itself. Unset = no Authorization header. Never written to any file or artifact. Read by BOTH the factory leg and the node's upstream leg. |
| `ZIVON_JSON_MODE` | no | `true` | Send `response_format: {"type": "json_object"}`. If your server rejects it you get a 400 with a hint to set this false — the pipeline never downgrades on its own. On the node this is node policy (a body `response_format` from a consumer is accepted for wire compatibility but ignored); in the cluster the knob is rendered into the llm-manager ConfigMap from `k8s/infra.env` — the 400 hint points THERE, not at the factory side. |
| `ZIVON_TEMPERATURE` | no | `0.2` | Default sampling temperature (per-stage override below). |
| `ZIVON_TIMEOUT_S` | no | `3600` | **SEMANTIC CHANGE 2026-11-07:** with streaming (the default) this is the maximum INACTIVITY between streamed chunks — a generating server keeps the call alive, a dead one is detected honestly after this many silent seconds. With `ZIVON_STREAM=false` it degrades to the classic per-read-operation timeout, which bounds nothing (a non-streaming response sends zero bytes until the end). Huge on purpose; `ZIVON_CALL_DEADLINE_S` (below) is the wall-clock backstop — there is NO wall-clock cap on the run Job itself (2026-11-06 founder decision). |
| `ZIVON_STREAM` | no | `true` | Streaming model calls. The honest-timeout path; disable only for a server without streaming support. |
| `ZIVON_STREAM_USAGE` | no | `true` | Ask for usage stats in the final stream chunk (`stream_options.include_usage`). If the server 400s on `stream_options` (the error message says exactly this), set `false`. Probe first — command in the runbook. |
| `ZIVON_CALL_DEADLINE_S` | no | `0` (= off) | Total wall-clock cap per model call. On breach the stream is CLOSED mid-generation (which makes the server stop generating and frees its slot) and the call fails with a TransportError naming the deadline. The cluster ships `7200` — generous by design; raise only deliberately. This is the fix for the 2026-11-07 runaway generation. |
| `ZIVON_CONNECT_TIMEOUT_S` | no | `10` | TCP connect timeout. |
| `ZIVON_MAX_ATTEMPTS` | no | `3` | Transport retries ONLY (connection errors, inactivity timeouts, 429, 5xx), exponential backoff from `ZIVON_BACKOFF_BASE_S`. In the cluster the factory ships `1` (see below). |
| `ZIVON_BACKOFF_BASE_S` | no | `2.0` | Exponential backoff base (2 → 4 → 8 … seconds). |
| `ZIVON_VALIDATION_ROUNDS` | no | `5` | The model's own repair budget per stage call: schema/JSON/length/rule failures are fed back (errors-as-context) and retried up to this many rounds, then SchemaError. Separate from the transport budget — the two never consume each other. |
| `ZIVON_HEARTBEAT_S` | no | `60` | In-flight heartbeat cadence (`still waiting on the model (Ns, N chunks received...)`). |

**No completion cap (2026-11-04 founder decision, unchanged):** the factory
sends no `max_tokens` at all. A measured `09-review` call spent 49,750
completion tokens (mostly thinking) and then answered correctly - Qwen thinks
a lot and then gets things right, so any cap is a truncation risk. The
2026-11-08 review split did NOT change this law: the measured thinking bloat
(24k–130k completion tokens per 09-review pass, one call killed mid-thinking)
was treated as a TASK-SIZE problem - 09-review is now two smaller calls - not
as a signal to cap thinking. Passage-level reasoning loops are the server's
domain: the Strata server's opt-in `reasoning_loop_recovery` guard is the
right lever there (see the dated entry in
`skills/prompting-and-agent-design/references/sources-and-evidence.md`).
`max_tokens` exists in `llm_manager.LLMConfig` as a CONSTRUCTOR-ONLY knob
with no environment variable, so only code can ever set it (a future
translator may; the factory never does). The server's own context budget,
`ZIVON_TIMEOUT_S` (inactivity) and `ZIVON_CALL_DEADLINE_S` (per-call wall
clock) are the backstops; the run Job itself has no deadline (2026-11-06
founder decision). `.env.example` at the repo root documents
the full set. A `server` section in `config.json` is a hard error with a
migration hint - delete it.

**In-cluster retry split (why the factory's `ZIVON_MAX_ATTEMPTS` is `1` in
its ConfigMap):** transport retries belong to the llm-manager node, which
already retries the upstream leg. If the factory also retried, one dead
upstream would fan out into node-attempts x factory-attempts calls. Local
runs that bypass the node keep the default `3`.

## Narration & Timbre (environment variables)

Stage 12-narration (build-time read-aloud, C-051) configures an external
PAID API and a money cap, so its knobs are environment-only like the server
variables. Full behaviour: `factory/narration/`, the architecture doc and
the runbook's "Narration builds" section.

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ZIVON_NARRATION_ENABLED` | no | `false` | Master switch. Off = the stage is a clean no-op (read-aloud stays unbuilt). In-cluster default ships `false` via `k8s/infra.env`. |
| `ZIVON_NARRATION_MODE` | no | `auto` | `auto` = live when a Timbre endpoint is configured, else mock (deterministic silence assets, labelled, never for the live site). `mock`/`live` force a mode. |
| `ZIVON_NARRATION_LANGS` | no | `en` | Comma-separated locales, validated against the ADR-0009 enum (10 Gnani codes + `hinglish`). Challenge-window builds narrate English; per-locale expansion is a post-challenge tranche decision. |
| `ZIVON_NARRATION_BUDGET_CREDITS` | no | `1500` | The A-15 one-time tranche `[ASSUMPTION]`, enforced refuse-before-exceed in LIVE mode against the cross-run ledger `runs/narration-budget.json` (the cumulative accrues LIVE Gnani spend only; mock builds are free and never refused). Raising it requires founder approval (A-15). |
| `ZIVON_NARRATION_REPAIR_ROUNDS` | no | `2` | Bounded repair-catcher rounds for failed blocks (0..5). Residual failures degrade read-aloud to the INF-089 disabled copy - they never fail the run. |
| `ZIVON_TIMBRE_BASE_URL` | for live | unset | Gnani Timbre v3.0 endpoint. Unset = mock mode under `auto`. |
| `ZIVON_TIMBRE_API_KEY` | for live | unset | The key itself - runtime secret, never written to files/artifacts. |
| `ZIVON_TIMBRE_TTS_PATH` | no | `/v1/tts` | Appended to the base URL. `[ASSUMPTION]`: the exact Gnani contract is a founder calibration item (like A-01) before the first live run. |
| `ZIVON_TIMBRE_VOICE` | no | provider default | Optional voice id. The ADR-0009/A-04 locale->language map (`en` -> `en-IN`, `hinglish` -> `hi-IN`, ...) is code; the voice choice is a calibration item. |
| `ZIVON_TIMBRE_CREDITS_PER_CHAR` | no | `1500/90000` (~0.0167) | Price estimate from the capacity model (90k chars ~ 1,500 credits). Tags bill as characters. Replace with dashboard prices when A-01 lands. |
| `ZIVON_TIMBRE_TIMEOUT_S` / `ZIVON_TIMBRE_CONNECT_TIMEOUT_S` | no | `120` / `10` | Read / connect timeouts for one synthesis call. |
| `ZIVON_TIMBRE_MAX_ATTEMPTS` / `ZIVON_TIMBRE_BACKOFF_BASE_S` | no | `3` / `2.0` | Transport retry budget + exponential backoff base (mirrors the server-call discipline; 429/5xx/transport retry, permanent 4xx raises immediately). |
| `ZIVON_FFMPEG_PATH` | no | PATH lookup | ffmpeg binary for the 24 kbps Opus encode (opus input passes through untouched). Missing ffmpeg = loud NarrationError. |
| `ZIVON_COLDSTORE_UPLOAD_CMD` / `ZIVON_COLDSTORE_READBACK_CMD` | for cold gate | unset | Operator command templates for the SYNC-01 P0 gate (`rclone copyto {src} b2:bucket/{dst}` style; `{src}`/`{dst}` are shell-quoted). Unset = the gate reports a loud SKIP. |
| `ZIVON_COLDSTORE_PREFIX` / `ZIVON_COLDSTORE_TIMEOUT_S` | no | `narration` / `120` | Cold key prefix / per-file command timeout. |

## learner

| Key | Type | Meaning |
|---|---|---|
| `language` | str | Only `"en"` in v1 (founder decision 2026-11-01). |

`learner.class_level` was **retired from config** (founder decision
2026-11-06): a config default for a per-run value is just a hardcode with
extra steps. The run's class comes from the `--class` flag, or - when it is
omitted - from the class of the chapter actually located by `01-locate`.
Prompts and the course folder (`class-N-physics`) follow that real class.
Putting `class_level` back into `config.json` is a hard error with a hint.

No other learner data may be configured - the pipeline must not learn anything
about the test participant.

## retrieval

| Key | Type | Meaning |
|---|---|---|
| `embedding_model` | str | sentence-transformers model name. Default `sentence-transformers/all-MiniLM-L6-v2` (~90 MB, downloaded once). |
| `device` | str | `cpu` or `cuda`. |
| `top_k` | int | Chunks fetched per book in the vector search. |
| `chunk_chars` | int | Chunk size in characters. |
| `chunk_overlap` | int | Overlap between chunks (must be < chunk_chars). |

Embeddings are cached per book under `sources/cache/embeddings/` and
invalidated automatically when chunks or the model change.

## limits

| Key | Type | Meaning |
|---|---|---|
| `max_chars_ncert_to_model` | int | Cap on the NCERT chapter text sent to the model (120k chars — measured class-9 chapters run 19k–62k, so no chapter is truncated; the 256k-context server handles it. Raise further for long class 11–12 chapters if ever needed). |
| `max_chars_supplement_each` | int | Cap per supplement chunk. |
| `max_chars_supplement_total` | int | Cap on all supplements combined. |
| `max_chars_design_context` | int | Budget for the design block (doctrine + its example pages) injected by `factory/design.py`: doctrine text flows into 02/04; doctrine + lesson-page example flow into every stage that writes, reviews or fixes page code — 05/08/09/10 (founder rule, 2026-11-04). Over-budget fails loudly with the numbers; never silently truncated. Shipped doctrine + lesson example ≈ 36k chars; raised 48000 → 64000 on 2026-11-04 so the richer candidate lesson example 2 (full-chapter coverage, ≈ 43k chars) fits when the founder approves it; raised 64000 → 68000 the same day after the doctrine v1.3 rewrite (typed page + frame-adaptation rules, founder batch) grew the composed swap context to ≈ 66k; raised 68000 → 80000 on 2026-11-05 when the founder's rebuilt example (sound layout code + the LessonKit alignment kit, ≈ 54k chars) replaced the live example and doctrine v1.4 flowed it - composed ≈ 78.4k; the founder's same-day second pass (doctrine v1.5) externalised the kit from the example (the examples glob is HTML-only, so the kit code never enters context) and brought the composed back to ≈ 68.7k - the cap stays 80000 as headroom for Day-9 doctrine growth. All raises verified against the inference server's measured `n_ctx = 262144` tokens: the worst case (120k-char source pack + 80k design + full generation) fits with room to spare. |

## paths

All relative paths resolve against the repo root; absolute paths are allowed
(tests use them). `catalog`, `pdf_cache`, `text_cache`, `runs`, `frontend`,
`doctrine`, `doctrine_examples`. `doctrine_examples` is a glob — narrowed on
2026-11-04 to lesson-page examples only (`docs/frontend/design-doctrine-lesson*.html`):
every match is injected into the stages that handle page code (05/08/09/10),
so adding a new lesson example needs no pipeline change. The main
(post/brand) example stays a docs asset and is deliberately out of factory
context (founder decision: its single-file demo style was bleeding into
generated pages). See architecture.md, "Design doctrine flow".

## perf

| Key | Type | Meaning |
|---|---|---|
| `profile` | str | Path to the perf profile JSON used by stages 07, 08 and 10 (see `testing/content_factory/perf/profiles/`; 10 re-measures it after each code fix). |
| `fix_rounds` | int | Safety cap on model fix-and-retest rounds for 08-fixloop (default 6). The loop is progress-aware: it stops earlier at a genuine plateau (`repair.stall_rounds` no-improvement retests). A fix that breaks lint or touches renderer-owned files consumes a round and is fed back as the next round's assignment. |

The default shipping profile (`weak-android.json`) has its load/FCP budgets
LOOSENED as of 2026-11-04 (6.0 s / 3.5 s) while first-generation diagnostics
are collected; RAM/FPS/throttle stay at founder spec. Rationale and the
re-tightening plan: `docs/content-factory/architecture.md` § Performance
budgets.

## repair

Catcher budgets (progress-aware redesign, founder decision 2026-11-06: the
pipeline is continuous improvement — a generous cap is a safety valve, the
real stopper is a state-aware plateau). Catchers keep repairing while the
severity-weighted blocking score (fatal=2, major=1) improves; they stop at
`stall_rounds` consecutive no-improvement rechecks (a genuine plateau — more
of the same repair won't help) or at the generous cap. A fix that itself
breaks a hard lint, touches a renderer-owned file, or regresses the perf
budget consumes a round and is fed back as the next round's assignment.

| Key | Type | Meaning |
|---|---|---|
| `content_rounds` | int (1..20) | Safety cap on regenerate-flagged-blocks + recheck rounds for 04-repair (triggered by any fatal/major issue from 03-check's model or rules). Minor issues never trigger a repair. |
| `code_rounds` | int (1..20) | Safety cap on replace-files + re-lint + re-perf + re-review rounds for 10-reviewfix (triggered by a 09-review fail verdict). Only topic-local files may change (page.js / page.css). |
| `stall_rounds` | int (1..10) | Consecutive no-improvement rechecks/re-reviews/retests that declare a plateau and stop the catcher (with the full history + resume hint). Applies to 04-repair, 08-fixloop and 10-reviewfix. |

## Resume and fingerprint (no config key — behaviour to know)

Run ids are deterministic per (chapter, class). `status.json` stores a
fingerprint of `pipeline_version + chapter + class + model + learner +
retrieval + limits`: editing any of those behaviour sections invalidates
existing run dirs on purpose — the pipeline refuses to resume a mismatched
dir and tells you to pass `--fresh` (or pick a new `--run-id`). Repair round
caps are NOT in the fingerprint (2026-11-06): they are runtime policy, not
artifact semantics, so tuning them never invalidates good generated work.
`--fresh` wipes the previous attempt for that topic before running.

## stage_overrides

Object keyed by stage id, values `{temperature?}`, e.g.:

    "stage_overrides": {"02-generate": {"temperature": 0.4}}

Valid stage ids: 00-ingest, 01-locate, 02-generate, 03-check, 04-repair,
05-interactive, 06-render, 07-perf, 08-fixloop, 09-review, 10-reviewfix,
11-link.

Current committed value: `{}` — no per-stage overrides. History: the first
cluster runs (graph v1 stage ids) died at 02-synth — first `structured output
was incomplete (finish_reason=length)` (4096 too small: a whole-chapter ground
truth plus qwen's 5–10k THINKING tokens, which count against `max_tokens`),
then read timeouts once budgets grew. The fix (0.2.8) made the global knobs
effectively non-binding (`ZIVON_MAX_TOKENS=65536`). The 2026-11-04 founder
decision goes further: **caps removed entirely** — no `max_tokens` is sent at
all (`ZIVON_MAX_TOKENS` retired from code and `infra.env` too). The server's
own context budget (256k dev server) and `ZIVON_TIMEOUT_S` bound the model
calls; the run itself carries no wall-clock cap (2026-11-06 founder decision:
a blind timer must not kill a progressing run). Per-stage `temperature` overrides
remain for the day a stage needs different sampling.
