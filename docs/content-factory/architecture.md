# Content factory architecture (v1)

Status: implemented on 2026-11-01, branch `feature/content-factory-pipeline`.
Owner workstream: the build-time content factory. Voice runtime is out of scope here.

## What one command does

    python pipeline.py "Motion" [--class 9]

Given a chapter name, the factory: caches the public PDF library, finds the
chapter EXACTLY in the NCERT books, vector-searches every other book's index
for supplements, synthesizes a cited ground truth, edits it into a
self-contained lesson, lays it out as JSON blocks, reviews it (model + rules),
builds interactive elements, renders a static page, gates it on a
weak-hardware performance budget, fixes and re-tests in a loop, runs the code
reviewer, and only then links it into `frontend/` and regenerates the course
index.

## Stages

| # | Stage | Module | Model? | Output (runs/<run_id>/<stage>/output.json) |
|---|---|---|---|---|
| 00 | ingest | factory/ingest.py | code | per-book chapter index + page text cache |
| 01 | locate | factory/locate.py | code (embeddings) | source_pack: NCERT chapter text + supplement chunks with citations |
| 02 | synth | factory/agents.py | model | ground_truth (claims, equations, misconceptions, uncertain) |
| 03 | explain | factory/agents.py | model | lesson (self-contained prose) |
| 04 | draft | factory/agents.py | model | blocks (text / worked_example / check / reveal / diagram / simulation) |
| 05 | check | factory/agents.py + factory/checks.py | model + code | combined verdict; fatal = stop |
| 06 | interactive | factory/interactive.py | model, 1 req per simulation | page.js / page.css fragments (linted) |
| 07 | render | factory/render.py | code | staging site + manifest + courses.js |
| 08 | perf | factory/perf.py + testing/perf/harness.py | code (Chromium) | budget report; miss = stop (09 fixes) |
| 09 | fixloop | factory/fixloop.py | model, up to perf.fix_rounds | fixed topic files + history |
| 10 | review | factory/review.py | model + code | final verdict; fatal = stop |
| 11 | link | factory/link.py | code | copy into frontend/, regenerate courses.js, smoke test |

Mapping to the six agents in AGENTS.md: 00+01 = Curator; 02+03+04 = Synthesizer;
06 = Visual Builder; 08+09 = Performance Engineer; 05 = Comprehension & Fact
Reviewer; 10 = Code Reviewer.

## Interface between stages

Everything is files. Each stage writes `output.json` into its run directory and
the orchestrator also passes the objects in memory. A re-run of a later stage
alone reads the earlier stages' artifacts. Model-call evidence lives in
`<stage>/attempts/attempt-NN/{request,response,meta}.json` - every retry is on
disk, with the validator feedback that was sent back to the model.

## Failure semantics (no silent fallbacks)

- Any stage failure marks the run failed and raises; downstream stages never run.
- Model output must parse as JSON and validate against factory/schemas.py.
  Validation failures are retried with the error report fed back; after
  `server.max_attempts` the stage fails with SchemaError.
- Network errors / 429 / 5xx retry with backoff; any other HTTP error fails
  immediately with the server's body (a 400 about response_format tells you to
  set `server.json_mode=false`).
- Unknown config keys, missing class-evidence strings, wrong PDFs, ambiguous
  chapter names, answer-key mismatches, invented numbers, external URLs,
  inline scripts: all hard errors.
- The single sanctioned discovery behaviour: a 404 on a chapter of a catalog
  entry marked `chapters_verified: false` ends that book's chapter list at the
  last good file, prints it, and records `truncated_at` in the output. This
  exists because NCERT books simply end; it is loud, never silent.

## Traceability and accuracy rules

- The synthesizer only sees the source pack (stage 01 output). It cannot cite
  anything that is not in it.
- Every factual block cites ground-truth claim ids; 05-check enforces this in
  code (`factory/checks.py`), independent of the model reviewer.
- Numbers in worked-example/check answers must appear in the ground truth or
  the primary source text (invented-figure guard).
- The ground truth has a mandatory `uncertain` field - what the sources did
  not answer. It is carried into prompts so later stages do not resolve it by
  inventing.
- Block payloads live under `spec` everywhere (AGENTS.md format), which
  resolves the AGENTS.md-vs-TIMELINE.md schema contradiction.

## Privacy

The pipeline takes no learner data as input. The only learner-related setting
is `learner.class_level` (a number) and `learner.language`. Run artifacts
contain source text, prompts and model output only.

## Rendering and frontend layering

- Shared layer (hand-maintained, in repo): `frontend/assets/zivon.css`
  (doctrine tokens, components, local fonts), `frontend/assets/zivon.js`
  (quiz wiring, ZivonSim runtime, course list, pen-underline generator),
  `frontend/index.html` (courses page), `frontend/courses.js` (generated).
- Per-topic layer (generated): `frontend/courses/class-N-physics/<slug>/` -
  index.html, page.js, page.css, manifest.json.
- Pages carry a strict CSP (`default-src 'none'; connect-src 'none'; ...`),
  load JS only from `'self'`, bundle fonts locally, and make zero external
  calls. The linter enforces this mechanically.
- Simulations are model-written but constrained: one `ZivonSim.register(...)`
  skeleton per block, canvas 2D only, CSS scoped under the block's own class.

## Performance budgets

`testing/perf/profiles/*.json` are the tuning knobs (viewport, CPU throttle
rate, RAM ceiling, load/FCP budgets, FPS floor, core pinning). The default
shipping gate is `weak-android.json` (750 MB browser-tree RSS per the
founder's spec, 4x CPU throttling, 2 cores, load < 2 s). The harness measures
Navigation Timing, FCP/LCP, peak Chromium-tree RSS via psutil, and rAF FPS,
and fails on any console/page error.
