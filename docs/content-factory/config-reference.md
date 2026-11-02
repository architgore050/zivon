# Configuration reference

Configuration has two layers, deliberately separate:

1. **`config.json` at the repo root** — the pipeline's *behaviour*: learner,
   retrieval, limits, paths, perf, stage_overrides. Committed, reviewable,
   identical on every machine. Validation is strict: unknown keys and wrong
   types are hard errors.
2. **Environment variables** — everything about *which inference server to
   talk to*. Per AGENTS.md ("configuration lives in environment variables")
   and the deployment rule (secrets enter runtime only), these never appear
   in any file, image, manifest, or run artifact. Missing required variables
   is the tripwire: the pipeline refuses to start without them.

Tests can point at another behaviour file with the `ZIVON_CONFIG` environment
variable; production always uses the repo root `config.json`.

## Server (environment variables)

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ZIVON_BASE_URL` | yes | — | OpenAI-format base, e.g. `http://127.0.0.1:8000/v1`. `/chat/completions` is appended. |
| `ZIVON_MODEL` | yes | — | Model name exactly as your server reports it (e.g. via `GET /v1/models`). |
| `ZIVON_API_KEY` | no | unset | The key itself. Unset = no Authorization header. Never written to any file or artifact. |
| `ZIVON_JSON_MODE` | no | `true` | Send `response_format: {"type": "json_object"}`. If your server rejects it you get a 400 with a hint to set this false — the pipeline never downgrades on its own. |
| `ZIVON_TEMPERATURE` | no | `0.2` | Default sampling temperature (per-stage override below). |
| `ZIVON_MAX_TOKENS` | no | `65536` | Default completion cap (per-stage override below). Huge on purpose: the server clamps it to remaining context. |
| `ZIVON_TIMEOUT_S` | no | `3600` | Per-request timeout. Huge on purpose: local single-slot models are slow; the Job deadline is the real backstop. |
| `ZIVON_MAX_ATTEMPTS` | no | `3` | Retries for network/429/5xx AND for schema-validation feedback loops. |

`.env.example` at the repo root documents the full set. A `server` section in
`config.json` is now a hard error with a migration hint — delete it.

## learner

| Key | Type | Meaning |
|---|---|---|
| `class_level` | int | 6-12. Drives prompts and the course folder (`class-9-physics`). |
| `language` | str | Only `"en"` in v1 (founder decision 2026-11-01). |

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
| `max_chars_ncert_to_model` | int | Cap on the NCERT chapter text sent to the synthesizer (64k-context models can raise this). |
| `max_chars_supplement_each` | int | Cap per supplement chunk. |
| `max_chars_supplement_total` | int | Cap on all supplements combined. |
| `max_chars_design_context` | int | Budget for the design block (doctrine + its example pages) injected into 04/06/10 by `factory/design.py`. Over-budget fails loudly with the numbers; never silently truncated. Shipped doctrine + examples ≈ 41k chars. |

## paths

All relative paths resolve against the repo root; absolute paths are allowed
(tests use them). `catalog`, `pdf_cache`, `text_cache`, `runs`, `frontend`,
`doctrine`, `doctrine_examples`. `doctrine_examples` is a glob: every file it
matches is injected into 06-interactive, so adding a new example page needs
no pipeline change (see architecture.md, "Design doctrine flow").

## perf

| Key | Type | Meaning |
|---|---|---|
| `profile` | str | Path to the perf profile JSON used by stages 08/09 (see `testing/content_factory/perf/profiles/`). |
| `fix_rounds` | int | Max model fix-and-retest rounds before the perf gate fails the run. |

## stage_overrides

Object keyed by stage id, values `{temperature?, max_tokens?}`, e.g.:

    "stage_overrides": {"02-synth": {"max_tokens": 8192}}

Valid stage ids: 00-ingest, 01-locate, 02-synth, 03-explain, 04-draft,
05-check, 06-interactive, 07-render, 08-perf, 09-fixloop, 10-review, 11-link.

Current committed value: `{}` — no per-stage caps. History: the first cluster
runs died at 02-synth — first `structured output was incomplete
(finish_reason=length)` (4096 too small: a whole-chapter ground truth plus
qwen's 5–10k THINKING tokens, which count against `max_tokens`), then read
timeouts once budgets grew. The fix (0.2.8) is to make the global knobs
effectively non-binding (`ZIVON_MAX_TOKENS=65536`, `ZIVON_TIMEOUT_S=3600`):
the server clamps completion to its remaining context (256k dev server), and
the run Job's `activeDeadlineSeconds` (2 h) is the real backstop. Per-stage
overrides remain the tool for the day a stage needs a *tighter* or *different*
budget (e.g. a future faster server, or a runaway stage) — not needed now.
