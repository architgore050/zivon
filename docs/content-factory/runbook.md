# Runbook: first run and day-to-day operation

## One-time setup

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m playwright install chromium     # perf gate needs Chromium once

First run of stage 01 downloads the sentence-transformers model (~90 MB) and
first use of stage 08 launches Chromium. Everything after that is local.

## Configure

Server settings live in the **environment**, never in files (AGENTS.md rule;
see `docs/content-factory/config-reference.md` and `.env.example`):

1. `export ZIVON_BASE_URL=http://127.0.0.1:8000/v1` and
   `export ZIVON_MODEL=<name as GET /v1/models reports it>` - missing either
   one is the tripwire that blocks startup. If your server needs a key:
   `export ZIVON_API_KEY=<key>` - the key value never goes into any file.
2. If the server rejects `response_format` with a 400, set
   `ZIVON_JSON_MODE=false` (the pipeline tells you exactly this; it never
   downgrades on its own).
3. Optional: per-stage `temperature` / `max_tokens` under `stage_overrides`
   in `config.json` (the behaviour file: learner, retrieval, limits, paths,
   perf live there).

## Verify the wiring before burning model time

    python -m unittest discover -s testing/content_factory/unit -t .        # fast
    python -m unittest testing.content_factory.integration.test_end_to_end  # full pipeline vs the mock server + real Chromium

The integration test runs the entire pipeline against a mock OpenAI-format
server with fixture PDFs and a fixture catalog. If that passes, your install
is correct end to end and the only remaining variable is your real model.

## Generate a topic

    python pipeline.py "Motion" --class 9

- The chapter name is searched by title inside every cached NCERT chapter PDF.
  Ambiguity is an error listing the candidates - pass `--class` to resolve.
- The page is written to `frontend/courses/class-9-physics/<slug>/` and listed
  on `frontend/index.html` automatically (stage 11).
- Open `frontend/index.html` in a browser (or `python3 -m http.server -d frontend`).

## Re-runs and debugging

- Every run keeps full evidence in `runs/<run_id>/<stage>/`:
  `output.json` per stage; `attempts/attempt-NN/{request,response,meta}.json`
  for every model call including retries; `status.json` and
  `run_report.json` at the run root.
- Re-run only some stages: `python pipeline.py "Motion" --stages 05-check,07-render`
  (upstream artifacts are read from the latest previous run that has them,
  copied into the new run, and the source run is printed - use `--run-id` to
  pin. Starting a subset too late - no run has the upstream output - fails
  with instructions).
- A failure prints the stage, the reason and the evidence directory. Start
  with `runs/<id>/<stage>/attempts/*/response.json` for model misbehaviour.

## Source library

- `sources/catalog.json` lists the books; `docs/source-catalog.md` is the
  human-readable mirror (a unit test keeps them in sync).
- PDFs cache under `sources/pdfs/` (gitignored). Manual-download books (OpenStax,
  Siyavula) must be placed by hand; the pipeline prints the exact path when missing.
- Add a source: catalog entry + doc row + `python -m unittest
  testing.content_factory.unit.test_catalog_sync`.

## Test harshness

Perf profiles are data: `testing/content_factory/perf/profiles/weak-android.json` (shipping
gate: 750 MB RAM, 4x CPU throttle, 2 cores, load < 2 s) and
`mid-laptop.json` (mild). Tune or add profiles freely; point `perf.profile`
in config.json at the gate you want. Standalone use:

    python -m testing.content_factory.perf.harness --url file:///path/to/page.html \
        --profile testing/content_factory/perf/profiles/weak-android.json
