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
3. Optional: per-stage `temperature` under `stage_overrides`
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
- Cluster runs: stage 11 lands the site on the `zivon-frontend` PVC (served live at
  the NodePort). After a run whose pages you want to keep, `scripts/publish-frontend.sh`
  mirrors the generated output (`courses/`, `courses.js`) back into the repo's
  `frontend/` - the versioned, standalone-deployable snapshot (git history holds
  the previous versions).
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
  for every model call including retries (`meta.json` carries latency, token
  usage, sampling and payload sizes); stages that re-ran per repair round
  keep rounds separated (`attempts/round-01/attempt-NN/`, plus
  `03-check/combined-<round>.json` and `04-repair`/`10-reviewfix`
  `history.json`); `status.json` (per-stage state + fingerprint + `elapsed_s`)
  and `run_report.json` (aggregated `stage_durations_s`, `started_at`,
  `completed_at`) at the run root.
- Reading the LIVE log (added 2026-11-04 after a run looked frozen while the
  giant 02-generate call was actually running): every stage prints
  `[NN-stage] starting` / `[NN-stage] ok in Xs (detail)`; every model call is
  bracketed by `model call started` / `finished in Xs (tokens...)`, and while
  a call blocks a heartbeat prints every 60 s. A live heartbeat means the
  model is thinking/generating - wait; no stage line and no heartbeat means
  something else is wrong. `scripts/logs-factory-run.sh` tails the Job log.
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

- `sources/catalog.json` lists the books; `docs/content-factory/source-catalog.md` is the
  human-readable mirror (a unit test keeps them in sync).
- PDFs cache under `sources/pdfs/` (gitignored). Manual-download books (OpenStax,
  Siyavula) must be placed by hand; the pipeline prints the exact path when missing.
- Add a source: catalog entry + doc row + `python -m unittest
  testing.content_factory.unit.test_catalog_sync`.
- The cluster Jobs (k8s/20, k8s/50) set `HF_HUB_OFFLINE=1`: the embedder lives
  on the `zivon-hf-cache` PVC, so runs never round-trip to the HF Hub at
  startup (no more "unauthenticated requests to HF Hub" warnings, faster boot).
  If that PVC is ever wiped, drop the env or the model cannot re-download.

## Test harshness

Perf profiles are data: `testing/content_factory/perf/profiles/weak-android.json` (shipping
gate: 750 MB RAM, 4x CPU throttle, 2 cores; load/FCP budgets LOOSENED
2026-11-04 pending first real-generation measurements - see
`docs/content-factory/architecture.md` § Performance budgets) and
`mid-laptop.json` (mild). Tune or add profiles freely; point `perf.profile`
in config.json at the gate you want. Standalone use:

    python -m testing.content_factory.perf.harness --url file:///path/to/page.html \
        --profile testing/content_factory/perf/profiles/weak-android.json
