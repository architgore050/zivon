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

1. `export ZIVON_BASE_URL=http://127.0.0.1:8080/v1` and
   `export ZIVON_MODEL=<name as GET /v1/models reports it>` - missing either
   one is the tripwire that blocks startup. If your server needs a key:
   `export ZIVON_API_KEY=<key>` - the key value never goes into any file.
   `ZIVON_BASE_URL` decides the topology: point it at the server directly
   (local host runs) or at the llm-manager node (`http://127.0.0.1:18090/v1`
   via `docker compose up -d llm-manager`; in the cluster the factory's
   ConfigMap already points at the llm-manager Service - see
   `docs/deployment/kubernetes.md`).
2. If the server rejects `response_format` with a 400, set
   `ZIVON_JSON_MODE=false` (the pipeline tells you exactly this; it never
   downgrades on its own). If it rejects `stream_options` with a 400, set
   `ZIVON_STREAM_USAGE=false` (same policy).
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
- `--class` is also the run's learner class; when omitted, the learner class
  is taken from the class of the chapter actually located (loud print).
  `config.json` carries no class at all (retired 2026-11-06). The page always
  lands in the course folder of the class its chapter belongs to - a class-11
  chapter builds under `class-11-physics/`, a `--class` with no matching book
  fails loudly.
- The page is written to `frontend/courses/class-9-physics/<slug>/` and listed
  on `frontend/index.html` automatically (stage 11).
- Open `frontend/index.html` in a browser (or `python3 -m http.server -d frontend`).
- Cluster runs: stage 11 lands the site on the `zivon-frontend` PVC (served live at
  the NodePort). After a run whose pages you want to keep, `scripts/publish-frontend.sh`
  mirrors the generated output (`courses/`, `courses.js`) back into the repo's
  `frontend/` - the versioned, standalone-deployable snapshot (git history holds
  the previous versions). If the PVC site is identical to the repo snapshot (the
  last run never reached stage 11-link), the script exits loudly with code 2
  instead of silently republishing an older topic.
- Run ids are deterministic per (chapter, class) - `motion-c9`. Re-triggering
  the same topic RESUMES the previous attempt (completed stages reused, zero
  model re-calls). Pass `--fresh` to wipe the previous attempt and generate the
  page from scratch (the "regenerate with new prompts" button).
- On a local ~20 tok/s model a full happy-path run costs roughly 3 big model
  calls (generate / check / review) plus one per simulation - budget tens of
  minutes. Catchers (04, 08, 10) only add time when a gate finds something.

## Re-runs, failures and debugging

- Gate failures are REPAIRED, not fatal: 03→04-repair, 07→08-fixloop and
  09→10-reviewfix each run a progress-aware catcher loop inside the same run
  (2026-11-06 founder decision): it keeps repairing while the severity-
  weighted issue score improves and stops at a genuine plateau
  (`repair.stall_rounds` no-improvement rounds in a row) or a generous safety
  cap (`repair.*_rounds`, `perf.fix_rounds`) — never at a blind small count.
  A fix that itself breaks a lint, touches a renderer-owned file, or regresses
  perf costs a round, not the run: the fixer repairs its own fix. A run only
  dies when a catcher plateaus or hits its cap (the failure names the reason,
  the round history and the remaining issues), an unfixable error appears, or
  a config/fingerprint guard fires. Upstream stages are never re-derived on a
  downstream failure.
- If a run dies, re-run the same command: completed stages are reused and the
  failed stage runs again — a catcher that plateaued re-runs with a FRESH
  round budget against the kept repaired draft. The fingerprint guard refuses
  to resume a run dir created under a different pipeline shape - it tells you
  to pass `--fresh`. (Pipeline version 6, 2026-11-06: all version-5 dirs are
  refused once because the catcher semantics changed; from now on, tuning the
  repair caps will NOT invalidate run dirs — caps are no longer in the
  fingerprint.)

## Reading the LIVE log (and what changed on 2026-11-07)
- Every run keeps full evidence in `runs/<run_id>/<stage>/`:
  `output.json` per stage; `attempts/attempt-NN/{request,response,meta}.json`
  for every model call including retries (`meta.json` carries latency, token
  usage, sampling, payload sizes, the streaming evidence added 2026-11-07
  (`stream`, `first_token_s`, `chunks_received`, `finish_reason`,
  `call_deadline_s`), and since 2026-11-08 an `outcome` line — a call that
  died mid-stream now writes meta.json too: last heartbeat + error class,
  not just request.json); stages that re-ran per repair round
  keep rounds separated (`attempts/round-01/attempt-NN/`, plus
  `03-check/combined-<round>.json` and `04-repair`/`10-reviewfix`
  `history.json`); 09-review namespaces its two calls (2026-11-08 split):
  `attempts/facts/attempt-NN/` and `attempts/design/attempt-NN/`, re-reviews
  as `attempts/round-01-facts/...`); `status.json` (per-stage state +
  fingerprint + `elapsed_s`) and `run_report.json` (aggregated
  `stage_durations_s`, `started_at`, `completed_at`, plus the 2026-11-08
  ledger rollups `model_call_stats` and `issues_found`) at the run root.
- Ledgers at the run root (2026-11-08): `calls_ledger.jsonl` (one line per
  model attempt: answered / rejected+reason / transport-failure, with
  latency, `first_token_s` as the thinking proxy, token usage, finish
  reason) and `issues_ledger.jsonl` (one line per reviewer-found issue:
  stage, call, severity, category, block, unverified flag). To answer
  "what are the agents actually failing at?" across runs:
  `scripts/publish-artifacts.sh` (mirror the PVC's runs/ to the host), then
  `python3 scripts/issue_report.py` — per-stage call stats (thinking
  seconds, max completion tokens, `length` cuts), issue counts by
  stage/severity/category, and recurring findings (same block+class across
  catcher rounds = the plateau signature).
- Every stage prints `[NN-stage] starting` / `[NN-stage] ok in Xs (detail)`;
  every model call is bracketed by `model call started (validation round
  i/N...)` / `finished in Xs (tokens...)`, and while a call blocks a
  heartbeat prints every 60 s: `still waiting on the model (Ns, N chunks
  received...)`. READ THE CHUNK COUNTER: a heartbeat with `0 chunks` means
  the model is still thinking (normal for a giant generation call); a
  heartbeat with growing chunk counts means tokens are streaming.
  `scripts/logs-factory-run.sh` tails the Job log.

### The 2026-11-07 transport diagnosis (why streaming + the deadline exist)

A run died at stage 10-reviewfix: the inference server kept generating tokens
for 3,592 s per attempt (77,921 then 131,445 then 199,056 tokens across
three transport tries) while the client sat silent and read-timed-out at
3,600 s each time. Root cause: `requests`' timeout is a per-read-operation
timeout, not a total cap - and a non-streaming response sends ZERO bytes
until generation ends, so a rambling generation was unkillable and every
retry re-bought the same lottery while the server's single slot burned. The
fix is structural: model calls now run through the shared `llm_manager`
module with streaming transport (inactivity between chunks = the honest
dead-server signal, and the heartbeat shows real chunk progress) plus a
total wall-clock deadline `ZIVON_CALL_DEADLINE_S` (7200 in the cluster) that
closes the stream mid-generation - which is what makes the server STOP and
frees its slot for the next try. The node topology (factory -> llm-manager
Service -> router -> server) and its knobs are documented in
`docs/content-factory/architecture.md`, "Model calls: the llm_manager node".

### Live-server probe (streaming + usage-in-stream support)

Before flipping `ZIVON_STREAM` / `ZIVON_STREAM_USAGE` on a NEW server, probe
it (NEVER while a factory run is live - the server is single-slot):

    curl -sN --max-time 120 http://127.0.0.1:8080/v1/chat/completions \
      -H 'Content-Type: application/json' \
      -d '{"model":"<ZIVON_MODEL>","messages":[{"role":"user","content":"Reply with exactly: OK"}],"stream":true,"stream_options":{"include_usage":true},"max_tokens":16}'

Read the answer: SSE `data: {...}` chunks with deltas? A final `data: [DONE]`?
A usage chunk (empty `choices`, `usage` object)? If the server answers 400
blaming `stream_options`, set `ZIVON_STREAM_USAGE=false` in `k8s/infra.env`
and re-apply. If it rejects `stream: true` outright, STOP - do not silently
fall back; the streaming semantics are the fix, a server without streaming
needs a decision, not a default.

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
