# Session log — 2026-11-02 — content factory review + fixes

Workstream: full review of the `feature/content-factory-pipeline` branch
(infra was reviewed separately by the founder), then fixing what the review
found - config placement first, then the architectural gaps. Granular
commits, CI-green at every step (unit suite 96 → 158 tests, ruff + mypy
clean throughout).

## Done

- **Config split (0268d73)**: `config.json` now holds only pipeline
  behaviour (learner/retrieval/limits/paths/perf/stage_overrides). All
  server wiring moved to the environment: `ZIVON_BASE_URL` + `ZIVON_MODEL`
  required (missing env is the tripwire; `CHANGE-ME` still fails fast),
  `ZIVON_API_KEY`, `ZIVON_JSON_MODE`, `ZIVON_TEMPERATURE`,
  `ZIVON_MAX_TOKENS`, `ZIVON_TIMEOUT_S`, `ZIVON_MAX_ATTEMPTS` optional.
  A `server` section in config.json is now a hard error with a migration
  hint. `.env.example` added; compose, the K8s run-Job, the Dockerfile
  example and the config docs follow.
- **Perf fix loop made reachable (41e80dd)**: stage 08 previously raised
  BudgetError and killed the run before 09-fixloop could ever repair
  anything - the Performance Engineer was unreachable. Topic-page misses
  now route to 09 with the report attached (fixable); landing-page misses
  stop the run immediately (the shared layer is hand-maintained). 09 starts
  from 08's report: rounds=0 (no model call, no extra Chromium launch) when
  perf passed. Also fixed HTML entity double-escaping when the fix loop
  rebuilds the page shell.
- **Artifact fallback for partial re-runs (952cacf)**: `--stages` re-runs
  promised "read upstream artifacts from the latest run dir" but crashed
  with FileNotFoundError instead. Now the latest previous run's
  `output.json` is copied into the current run (loudly, source printed);
  nothing available → typed `MissingArtifactError` with instructions.
- **Rule gaps closed (574255a)**: citation presence now enforced (fatal on
  uncited text/worked_example/check/reveal - the docs claimed this, the
  code did not); allowed citation source ids derived from the actual source
  pack instead of a hardcoded prefix list; `rule_numbers` matches whole
  numerals (`5` matches `5`/`5.0`, never `15`/`50`/`1.5`) and now also
  checks the correct option text of mcq checks.
- **Draft-time rule feedback (a642aa1)**: `LLMClient.call` gained an
  `extra_validator` hook; 04-draft wires the full rule checks into the
  model retry loop, so the model fixes its own violations instead of the
  run dying at 05-check. Draft prompt aligned with the rule: numbers must
  appear VERBATIM - "derivable" promised a check the code cannot do.
- **Perf harness pid fix (bec64e8)**: `_browser_pid` used to return the
  first chrome/chromium process on the machine - with the developer's own
  Chrome open it measured and pinned the wrong process tree. Now: snapshot
  before launch, pick the new headless main process. Unit-tested with a
  faked psutil (which caught a missing diff in the first draft).
- **zivon.js error painter (fb1ddc0)**: `wrapText` referenced an undefined
  `h` - every simulation crash handler threw `ReferenceError` on top of the
  original error. Verified fixed in node with a fake 2d context.
- **render cleanup (c52d9fb)**: dropped the unused `ground_truth` parameter
  from `render.run`.
- **PDF parser replaced (5026c62 + aab52c4)**: pypdf → pdfplumber (MIT;
  PyMuPDF rejected as AGPL in an unlicensed repo). `use_text_flow=True`
  follows content-stream order, which for born-digital textbooks IS reading
  order - superscripts stay inline ("9.8 m s -2") instead of being smeared
  mid-word. Ruled tables are detected, cut out of the flow text and
  re-appended as explicit `[table]` rows, so the Synthesizer sees cell
  structure instead of a flattened jumble; thin candidates (figure rules)
  are rejected. The old failure mode was demonstrated on a synthetic
  textbook page before the swap; the new behaviour is unit-tested (table +
  graph + superscript on one page). Known boundary recorded in
  architecture.md: text-layer extraction only - figure-borne content and
  borderless tables are out of scope for v1; `uncertain` carries the gaps.
- **Prompt review + improvements (9c29daa + 2b4b3ca)**: judged the 02-05
  prompting (contracts strong, craft average). Fixed: 02-synth now bans
  unit conversions / computed values in claims (closes the number-
  laundering hole where `rule_numbers` would bless a converted figure);
  claim quality defined; misconception search and the `uncertain`
  decision rule added; 03-explain got the tutor persona + TEACHING ORDER
  (observation -> define -> formalise) and must keep numbers verbatim;
  05-check and 10-review got adversarial framing ("assume there is at
  least one defect") and explicit severity calibration (fatal stops the
  run - the model must not invent its own scale). Each of 02/04/05 now
  shows one compact example labelled "SHAPE only - never reuse". New
  TestPromptPromises locks the load-bearing prompt lines with substring
  assertions (158 tests).
- Docs updated in the same commits they describe: config-reference,
  runbook, architecture (stage table, failure semantics, artifact
  fallback), blocks-schema (citation + verbatim-number rules), deployment
  kubernetes.md + docker.md, README.

## Not done / open

- The pipeline has still never run against a **real** inference server -
  everything so far is the mock. Day-4 priority: point `ZIVON_BASE_URL` /
  `ZIVON_MODEL` at the chosen Evon host and do the first real topic run.
- Draft-time rule feedback is proven with unit tests + fixture data; its
  behaviour with a real model (how often it needs a retry) is unmeasured.
- The prompt fixes (number-laundering ban, severity calibration, persona,
  shape examples) are locked by substring tests but their effect on a real
  Evon run - retry rates, claim quality, reviewer hit rate - is unmeasured;
  measure from `runs/<run_id>/<stage>/attempts/` on the first real runs.
- The perf harness pid logic is unit-tested against a fake psutil; the real
  launch diff runs in CI's integration job.

## Next

- First real-server run (Gate B day: kid testing happens on generated pages,
  so the pages must exist for real).
- Watch draft retry rates and fix-loop rounds in `runs/<run_id>/` after the
  first real runs; tune prompts/overrides from the evidence.
