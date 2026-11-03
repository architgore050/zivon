# Runbook: first run and day-to-day operation

## One-time setup

    python -m venv .venv && source .venv/bin/activate
    pip install -r requirements.txt
    python -m playwright install chromium     # perf gate needs Chromium once

First run of stage 01 downloads the sentence-transformers model (~90 MB) and
first use of stage 07 launches Chromium. Everything after that is local.

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
   perf, repair live there).

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
- Run ids are deterministic per (chapter, class) - `motion-c9`. Re-triggering
  the same topic RESUMES the previous attempt (completed stages reused, zero
  model re-calls). Pass `--fresh` to wipe the previous attempt and generate the
  page from scratch (the "regenerate with new prompts" button).
- On a local ~20 tok/s model a full happy-path run costs roughly 3 big model
  calls (generate / check / review) plus one per simulation - budget tens of
  minutes. Catchers (04, 08, 10) only add time when a gate finds something.

## Re-runs, failures and debugging

- Gate failures are REPAIRED, not fatal: 03→04-repair, 07→08-fixloop and
  09→10-reviewfix each burn a bounded number of rounds (`repair.*_rounds`,
  `perf.fix_rounds`) inside the same run. A run only dies when a catcher runs
  out of rounds, an unfixable error appears, or a config/fingerprint guard
  fires. Upstream stages are never re-derived on a downstream failure.
- If a run dies, re-run the same command: completed stages are reused and the
  failed stage runs again. The fingerprint guard refuses to resume a run dir
  created under a different pipeline shape - it tells you to pass `--fresh`.
- Every run keeps full evidence in `runs/<run_id>/<stage>/`:
  `output.json` per stage; `attempts/attempt-NN/{request,response,meta}.json`
  for every model call including retries; stages that re-ran per repair round
  keep rounds separated (`attempts/round-01/attempt-NN/`, plus
  `03-check/combined-<round>.json` and `04-repair`/`10-reviewfix`
  `history.json`); `status.json` (per-stage state + fingerprint) and
  `run_report.json` at the run root.
- Re-run only some stages: `python pipeline.py "Motion" --stages 03-check,06-render`
  (upstream artifacts are read from the latest previous run that has them,
  copied into the new run, and the source run is printed - use `--run-id` to
  pin. Starting a subset too late - no run has the upstream output - fails
  with instructions).
- A failure prints the stage, the reason and the evidence directory. Start
  with `runs/<id>/<stage>/attempts/*/response.json` for model misbehaviour;
  for gate loops read the stage's `history.json` / `combined-*.json` to see
  exactly what the reviewer flagged and what the catcher changed.

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
