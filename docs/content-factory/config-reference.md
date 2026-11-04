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

| Variable | Required | Default | Meaning |
|---|---|---|---|
| `ZIVON_BASE_URL` | yes | — | OpenAI-format base, e.g. `http://127.0.0.1:8000/v1`. `/chat/completions` is appended. |
| `ZIVON_MODEL` | yes | — | Model name exactly as your server reports it (e.g. via `GET /v1/models`). |
| `ZIVON_API_KEY` | no | unset | The key itself. Unset = no Authorization header. Never written to any file or artifact. |
| `ZIVON_JSON_MODE` | no | `true` | Send `response_format: {"type": "json_object"}`. If your server rejects it you get a 400 with a hint to set this false — the pipeline never downgrades on its own. |
| `ZIVON_TEMPERATURE` | no | `0.2` | Default sampling temperature (per-stage override below). |
| `ZIVON_TIMEOUT_S` | no | `3600` | Per-request timeout. Huge on purpose: local single-slot models are slow; the Job deadline is the real backstop. |
| `ZIVON_MAX_ATTEMPTS` | no | `3` | Retries for network/429/5xx AND for schema-validation feedback loops. |

**No completion cap (2026-11-04 founder decision):** the factory sends no
`max_tokens` at all. A measured `09-review` call spent 49,750 completion
tokens (mostly thinking) and then answered correctly - Qwen thinks a lot and
then gets things right, so any cap is a truncation risk. The server's own
context budget bounds answer length; `ZIVON_TIMEOUT_S` and the Job deadline
are the backstops. `.env.example` at the repo root documents the full set. A
`server` section in `config.json` is now a hard error with a migration hint -
delete it.

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
| `max_chars_ncert_to_model` | int | Cap on the NCERT chapter text sent to the model (120k chars — measured class-9 chapters run 19k–62k, so no chapter is truncated; the 256k-context server handles it. Raise further for long class 11–12 chapters if ever needed). |
| `max_chars_supplement_each` | int | Cap per supplement chunk. |
| `max_chars_supplement_total` | int | Cap on all supplements combined. |
| `max_chars_design_context` | int | Budget for the design block (doctrine + its example pages) injected by `factory/design.py`: doctrine text flows into 02/04; doctrine + lesson-page example flow into every stage that writes, reviews or fixes page code — 05/08/09/10 (founder rule, 2026-11-04). Over-budget fails loudly with the numbers; never silently truncated. Shipped doctrine + lesson example ≈ 36k chars; raised 48000 → 64000 on 2026-11-04 so the richer candidate lesson example 2 (full-chapter coverage, ≈ 43k chars) fits when the founder approves it; raised 64000 → 68000 the same day after the doctrine v1.3 rewrite (typed page + frame-adaptation rules, founder batch) grew the composed swap context to ≈ 66k — verified against the inference server's measured `n_ctx = 262144` tokens, which the worst case (120k-char source pack + 68k design + full generation) fits with room to spare. |

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
| `fix_rounds` | int | Max model fix-and-retest rounds before the perf gate fails the run. |

The default shipping profile (`weak-android.json`) has its load/FCP budgets
LOOSENED as of 2026-11-04 (6.0 s / 3.5 s) while first-generation diagnostics
are collected; RAM/FPS/throttle stay at founder spec. Rationale and the
re-tightening plan: `docs/content-factory/architecture.md` § Performance
budgets.

## repair

Catcher budgets (graph v2, 2026-11-03). Gate failures route to their catcher;
these knobs bound how many times a catcher may try before the run fails loudly.

| Key | Type | Meaning |
|---|---|---|
| `content_rounds` | int | Max regenerate-flagged-blocks + recheck rounds for 04-repair (triggered by any fatal/major issue from 03-check's model or rules). Minor issues never trigger a repair. |
| `code_rounds` | int | Max replace-files + re-lint + re-perf + re-review rounds for 10-reviewfix (triggered by a 09-review fail verdict). Only topic-local files may change (page.js / page.css). |

## Resume and fingerprint (no config key — behaviour to know)

Run ids are deterministic per (chapter, class). `status.json` stores a
fingerprint of `pipeline_version + chapter + class + model + learner +
retrieval + limits + repair`: editing any of those behaviour sections
invalidates existing run dirs on purpose — the pipeline refuses to resume a
mismatched dir and tells you to pass `--fresh` (or pick a new `--run-id`).
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
own context budget (256k dev server), `ZIVON_TIMEOUT_S` and the run Job's
`activeDeadlineSeconds` (2 h) bound the run. Per-stage `temperature` overrides
remain for the day a stage needs different sampling.
