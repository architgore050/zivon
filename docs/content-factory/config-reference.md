# config.json reference

`config.json` at the repo root is the single source of truth. Validation is
strict: unknown keys are errors. The committed file ships with
`server.model = "CHANGE-ME"` as a deliberate tripwire - the pipeline refuses to
start until you set it. Tests can point at another file with the `ZIVON_CONFIG`
environment variable; production always uses the repo root file.

## server

| Key | Type | Meaning |
|---|---|---|
| `base_url` | str | OpenAI-format base, e.g. `http://127.0.0.1:8000/v1`. `/chat/completions` is appended. |
| `api_key_env` | str \| null | NAME of the environment variable holding the key. The key value never enters any file or artifact. `null` = no Authorization header. |
| `model` | str | Model name exactly as your server reports it. `"CHANGE-ME"` blocks startup. |
| `json_mode` | bool | Send `response_format: {"type": "json_object"}`. If your server rejects it you get a 400 with a hint to set this false - the pipeline never downgrades silently. |
| `temperature` | float | Default sampling temperature (per-stage override below). |
| `max_tokens` | int | Default completion cap (per-stage override below). |
| `timeout_s` | number | Per-request timeout. Local models can be slow; 600 s default. |
| `max_attempts` | int | Retries for network/429/5xx AND for schema-validation feedback loops. |

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

## paths

All relative paths resolve against the repo root; absolute paths are allowed
(tests use them). `catalog`, `pdf_cache`, `text_cache`, `runs`, `frontend`,
`doctrine`, `doctrine_example`.

## perf

| Key | Type | Meaning |
|---|---|---|
| `profile` | str | Path to the perf profile JSON used by stages 08/09 (see `testing/perf/profiles/`). |
| `fix_rounds` | int | Max model fix-and-retest rounds before the perf gate fails the run. |

## stage_overrides

Object keyed by stage id, values `{temperature?, max_tokens?}`, e.g.:

    "stage_overrides": {"02-synth": {"max_tokens": 8192}}

Valid stage ids: 00-ingest, 01-locate, 02-synth, 03-explain, 04-draft,
05-check, 06-interactive, 07-render, 08-perf, 09-fixloop, 10-review, 11-link.
