# Content factory architecture (v2)

Status: v1 implemented 2026-11-01; **graph v2 decided and implemented
2026-11-03** after the first measured runs (founder decisions: consolidate the
reasoning layer into one giant call; whatever agent catches an issue is the
one that fixes it; runs must be resumable). Branch `feature/content-factory-pipeline`.
Model calls were moved onto the shared **llm_manager** module with streaming
transport on 2026-11-07 (see "Model calls: the llm_manager node" below).
Owner workstream: the build-time content factory. Voice runtime is out of scope here.

## What one command does

    python pipeline.py "Motion" [--class 9] [--fresh]

Given a chapter name, the factory: caches the public PDF library, finds the
chapter EXACTLY in the NCERT books, vector-searches every other book's index
for supplements, generates the whole page (ground truth + lesson + blocks) in
ONE model call, reviews it against the sources (model + rules), builds
interactive elements, renders a static page, gates it on a weak-hardware
performance budget, runs the code reviewer, and only then links it into
`frontend/` and regenerates the course index. Every gate failure is repaired
by its paired catcher inside the same run — never by re-running the pipeline.

Run ids are deterministic per (chapter, class): re-triggering the same topic
RESUMES the previous attempt (completed stages are loaded from disk, not
re-derived). `--fresh` wipes the previous attempt and generates clean.

## Stages

| # | Stage | Module | Model? | Output (runs/<run_id>/<stage>/output.json) |
|---|---|---|---|---|
| 00 | ingest | factory/ingest.py | code | per-book chapter index + page text cache (reused across runs) |
| 01 | locate | factory/locate.py | code (embeddings) | source_pack: NCERT chapter text + supplement chunks with citations |
| 02 | generate | factory/agents.py | **ONE giant model call** (Curator+Synthesizer+Designer in one); rule checks run inside the retry loop; gets the live design doctrine + palette | {ground_truth, lesson, blocks} in one JSON object (schema `GENERATED`) |
| 03 | check | factory/agents.py + factory/checks.py | model + code | combined verdict + issues with a fixed severity ladder; blocking (fatal/major) routes to 04 |
| 04 | repair | factory/agents.py (catcher) | model, progress-aware loop: keeps going while the blocking score improves, stops at `repair.stall_rounds` no-progress rechecks or the `repair.content_rounds` cap | replacement blocks for the flagged issues only (merged by id); recheck per round |
| 05 | interactive | factory/interactive.py | model, 1 req per simulation; gets the cited claims + equations its physics must obey AND the live design doctrine + examples + palette; lint runs inside the retry loop | page.js / page.css fragments (linted) |
| 06 | render | factory/render.py | code | staging site + manifest + courses.js |
| 07 | perf | factory/perf.py + testing/content_factory/perf/harness.py | code (Chromium) | budget report; topic miss → routed to 08; landing-page miss = stop (hand-maintained, human fixes) |
| 08 | fixloop | factory/fixloop.py | model, progress-aware loop (stall detection + `perf.fix_rounds` cap); a fix that breaks lint or touches renderer-owned files costs a round, not the run; sees page specs + previous attempts + the live design doctrine + lesson-page example + palette (fix, don't restyle); must preserve what the page teaches | fixed topic files + history; rounds=0 (no model call) when 07 passed |
| 09 | review | factory/review.py | model + code; reviews the FINAL code against block specs, cited facts AND the live design doctrine + lesson-page example | final verdict report (a fail verdict routes to 10, it does not raise) |
| 10 | reviewfix | factory/reviewfix.py (catcher) | model, progress-aware loop (stall detection + `repair.code_rounds` cap); a fix that breaks lint or regresses perf is returned as the next round's assignment, not raised; sees doctrine + lesson-page example + palette so fixes land on the page's visual language | replacement topic files (page.js/page.css only) + history; re-lint + re-perf + re-review per round (sync to staging only when the round is clean) |
| 11 | link | factory/link.py | code | copy into frontend/, regenerate courses.js, smoke test |

Happy path costs 3 model calls + one per simulation (generate, check, review).
Catcher calls happen only when a gate finds something.

Mapping to the six agents in AGENTS.md: 00+01 = Curator; 02-generate =
Synthesizer (+ instructional design in the same call); 03 = Comprehension &
Fact Reviewer; 04-repair = the Synthesizer's fixers; 05 = Visual Builder;
07+08 = Performance Engineer; 09 = Code Reviewer; 10-reviewfix = the Code
Reviewer's fixers.

**Why the reviewers stay separate calls:** a reviewer that is also the author
rubbers-stamps its own work. 03 and 09 are independent model calls; only the
reasoning layer was consolidated. **Why sim code stays a separate per-sim
call (05):** its lint feedback loop is per-simulation — folding sim code into
the giant call would make every lint violation re-generate the whole page.

## Interface between stages

Everything is files. Each stage writes `output.json` into its run directory and
the orchestrator also passes the objects in memory. Resume: at each stage the
orchestrator checks `status.json` — a stage marked ok whose output.json exists
is loaded, not re-run. A re-run of a later stage alone reads the earlier
stages' artifacts: if this run lacks one, it is taken from the latest previous
run that has it, copied into this run's stage dir, and the source run is
printed (`--run-id` pins a specific run). Model-call evidence lives in
`<stage>/attempts/attempt-NN/{request,response,meta}.json` — every retry is on
disk, with the validator feedback that was sent back to the model. Catcher
loops re-run a stage within one run; those rounds are separated: a stage that
runs more than once writes its later rounds under
`attempts/<round-tag>/attempt-NN/` (e.g. `03-check/attempts/round-01/`) so no
round overwrites another's evidence, and each check round also lands as
`03-check/combined-<round>.json`.

**Fingerprint guard:** `status.json` carries a fingerprint of the run's inputs
(pipeline version, chapter, class, model, limits/retrieval/learner config).
Repair round caps are deliberately NOT in the payload (2026-11-06): they are
runtime policy, not artifact semantics — a draft repaired in 2 rounds is just
as valid under a more generous catcher, so tuning the caps must not invalidate
good generated work. Reopening a run whose fingerprint differs raises a
ConfigError telling the operator to pass `--fresh` (or pick another `--run-id`)
— stage artifacts of two different pipeline shapes are never mixed silently.

## Failure semantics (no silent fallbacks, no whole-pipeline re-runs)

- A gate failure routes to ITS catcher, inside the same run. Catchers are
  **progress-aware loops** (founder decision 2026-11-06 — the pipeline is
  continuous improvement, not a one-shot exam): they keep repairing while the
  severity-weighted blocking score (fatal=2, major=1) improves, and stop at a
  genuine plateau (`repair.stall_rounds` consecutive no-improvement rechecks)
  or a generous safety cap (`repair.content_rounds` / `repair.code_rounds` /
  `perf.fix_rounds`) — never at a blind small count. 03-check blocking issues
  (any fatal/major from model or rules) → 04-repair regenerates ONLY the
  flagged blocks → 03-check re-runs in full. 09-review fail → 10-reviewfix
  replaces topic files → 09 re-reviews. A topic-page perf miss from 07 is
  raised as a *fixable* BudgetError and handed to 08-fixloop (this routing
  predates v2 and is its template). An unfixable perf miss (the landing page /
  shared assets) stops the run immediately — the fix loops only touch
  topic-local files. A fix that itself breaks a hard lint, touches a
  renderer-owned file, or regresses the perf budget costs a ROUND, not the
  run: the exact failure is fed into the next round's prompt so the fixer
  repairs its own fix. When a catcher does stop (plateau or cap), it fails
  loudly with the round history, the reason, and the resume hint — re-trigger
  the same chapter+class and the catcher runs again with a fresh budget
  against the kept repaired draft.
- Upstream stages never re-run when a downstream gate complains: 02-generate's
  output is reused across check/repair rounds; a run that dies at 03 keeps its
  00-02 artifacts on disk and a re-trigger resumes from them. The factory Job
  has `backoffLimit: 0` — a Job-level whole-pod retry is never sanctioned;
  recovery is re-running the trigger script, which resumes.
- Model output must parse as JSON and validate against factory/schemas.py.
  Validation failures are retried with the error report fed back, each failure
  getting its own **validation round** (`ZIVON_VALIDATION_ROUNDS`, default 5) —
  a budget separate from the transport retries (`ZIVON_MAX_ATTEMPTS`, 2026-11-06
  founder decision: a thinking model is not expected to one-shot a giant JSON).
  After all validation rounds the stage fails with SchemaError. The feedback
  turn is compact by contract (2026-11-05): each violation is reported as
  `at '<path>': expected <what>, got <what arrived>` — never jsonschema's
  default message, which embeds the whole rejected instance (once a 55k-char
  repr of 70 blocks; the retry transcript ballooned 110k → 243k characters).
  The best-match violation plus up to 3 more are reported in ONE turn, so the
  model fixes every shape problem per retry instead of burning a 50-minute
  attempt per error. Only the LATEST rejected output is kept in full in the
  transcript; older ones are trimmed to a stub, so a chain of validation
  rounds cannot eat the server's context. Since 2026-11-07 this machinery
  lives in `llm_manager/validation.py` (reusable by any consumer); the
  factory adapter supplies the artifacts and the stage errors.
- 02-generate runs the code-side rule checks (factory/checks.py) inside the
  model retry loop: the model sees its own fatal/major rule violations
  (invented number, uncited factual block, broken answer key) and fixes them.
  03-check re-runs the same rules independently as a second gate, and 04-repair
  runs them on the MERGED page before anything proceeds. 05-interactive uses
  the same loop for its hard lints: a generated sim that breaks the JS/CSS
  contract is fed back to the model for repair, not raised straight away.
- 03-check severity ladder (calibrated 2026-11-03 after the first real run
  over-flagged trivia): fatal = contradicts the source or a wrong answer key,
  must quote the source passage; major = a Physics concept smuggled in from
  outside the chapter's source material, or the learner is misled; minor =
  everything else, including common-knowledge definitions the source does not
  spell out — advisory, never blocks. `unverified:` suspicions can never be
  filed as fatal/major. The reviewer is told to hunt REAL errors and pass a
  faithful draft — the v1 "assume there is at least one error" framing is gone.
- Network errors / inactivity timeouts / 429 / 5xx retry with backoff; any
  other HTTP error fails immediately with the server's body (a 400 about
  response_format tells you to set `ZIVON_JSON_MODE=false`, one about
  stream_options to set `ZIVON_STREAM_USAGE=false`).
- Unknown config keys, missing class-evidence strings, wrong PDFs, ambiguous
  chapter names, answer-key mismatches, invented numbers, external URLs,
  inline scripts: all hard errors.
- The single sanctioned discovery behaviour: a 404 on a chapter of a catalog
  entry marked `chapters_verified: false` ends that book's chapter list at the
  last good file, prints it, and records `truncated_at` in the output. This
  exists because NCERT books simply end; it is loud, never silent.

## Source extraction (stage 00)

Page text is extracted with pdfplumber (pdfminer engine), not raw pypdf:

- `use_text_flow=True` follows the content-stream order, which for
  born-digital textbooks (every catalog entry) IS the reading order: raised
  superscripts join their base line ("m s -2") instead of being smeared
  mid-word, and column furniture stays put.
- Ruled tables are detected (`find_tables`), cut out of the flow text
  (`outside_bbox`), and re-appended as explicit `[table]` blocks with
  `cell | cell` rows, so the generation call sees cell structure instead of a
  flattened jumble. Candidates with fewer than two non-empty rows are
  rejected as false positives (figure rules are not tables).
- Known boundary: extraction is text-layer only. Content that exists only
  inside figures (what a graph actually shows) and borderless tables are out
  of scope for v1; the mandatory `uncertain` field is the designated carrier
  for facts the sources did not answer in text.
- The pinned TLS chain for NCERT (`sources/certs/ncert.nic.in.pem`) holds only
  PUBLIC certificates — no private keys; safe for a public repo by design.
  Operational note: when NCERT renews its leaf certificate, refresh the bundle
  (fetch chain → replace file) or the polite retry path keeps failing.

## Chapter matching (stage 01)

The matching contract was rewritten 2026-11-05 after the founder's killed
class-11 run: the query "Motion in a Straight Line" silently built a LAWS OF
MOTION page. Two harness bugs caused it, not the model:

- EXACT means a TITLE CANDIDATE matches. Candidates are title-shaped lines
  from the chapter opener (the line after a `CHAPTER <number-or-word>` line,
  an inline `CHAPTER N Title`, or a standalone display-caps line like the
  real NCERT opener's `MOTION IN A STRAIGHT LINE 15` - trailing book-page
  numbers are stripped). Body prose can never claim an exact hit: the old
  code's blob fallback matched a Newton's-first-law sentence in the LAWS OF
  MOTION chapter, set `found = query` (which made it always "exact"), and
  that fake hit beat the real chapter's title match (whose trailing page
  number had broken its `==` comparison).
- A phrase that only appears in a chapter's BODY is a demoted PARTIAL: it can
  win only when no title matches anywhere, and it prints a loud warning
  naming the chapter and demanding the operator verify the pick. The source
  pack records `matched_via` (`title_line` / `body_phrase`) so the evidence
  says how the chapter was chosen.
- Ambiguity stays a hard error listing the candidates; the no-match error
  lists the library's chapter titles.

## Traceability and accuracy rules

- The generation call only sees the source pack (stage 01 output). It cannot
  cite anything that is not in it. Its prompt carries the grounding law: the
  model's own Physics knowledge "does NOT count" — a concept the chapter does
  not explain must not be taught, tested, or mentioned, "even if it is standard
  Physics"; the source material is the whole universe of the page. (This is the
  fix for the 2026-11-02 failure class: a Motion page built around mass/force,
  concepts of the NEXT chapter.)
- Every factual block cites ground-truth claim ids; 02-generate and 03-check
  enforce this in code (`factory/checks.py`), independent of the model
  reviewer. Citation source ids must come from the actual source pack.
- Numbers in worked-example PROBLEMS and check QUESTIONS must appear verbatim
  in the ground truth or the primary source text - whole-numeral match, no
  substring smuggling (invented-problem guard). Answers and options are
  deliberately NOT code-checked: textbook exercises are meant to be computed,
  and derivability cannot be verified by string match (the old verbatim-answer
  rule made every NCERT numerical impossible, which is why the 2026-11-04
  Motion page skipped all of them). The 03-check reviewer RECOMPUTES every
  worked_example and numeric check instead - a wrong computed answer is fatal
  there and routes to 04-repair.
- Coverage is a gate, not a hope (founder diagnosis 2026-11-04: the Motion
  page taught only the basics and skipped momentum, exercises and practice
  problems, although ingestion had delivered the whole chapter): 02-generate's
  prompt carries a COVERAGE CONTRACT (inventory the chapter's titled sections,
  in-text questions, worked examples and end-of-chapter exercises; map every
  item to a lesson section / check / worked_example / reveal - nothing may be
  dropped), 03-check reports omissions as fatal, and 04-repair fixes them by
  ADDING blocks (new ids appended at the end, teach-then-test, last added
  block a check) - never by re-running 02.
- The coverage budget, reconciled 2026-11-05: the block sequence holds 4-45
  blocks and the prompt states exactly that (schema `maxItems` and the prompt
  may never contradict each other - the original 18-block cap clashed with the
  coverage contract and a model squeezed between them wrote 70 blocks). When a
  chapter's inventory is larger than the budget, same-type repetitive drills
  fold into their most instructive instance: every concept and every exercise
  TYPE must appear; identical repetitions may share one block. 03-check's
  coverage gate uses the same type-level law.
- Simulations are physics, so the facts travel with them: 05 receives the
  block's cited claims plus every ground-truth equation ("FACTS THE
  SIMULATION MUST OBEY"), and 09-review re-checks the FINAL draw loop against
  the same facts after any 08-fixloop rewrite (03 only ever saw the draft
  blocks). A simulation that draws physically wrong behaviour is fatal at 09.
- The ground truth has a mandatory `uncertain` field - what the sources did
  not answer. It is carried into prompts so later stages do not resolve it by
  inventing.
- Block payloads live under `spec` everywhere (AGENTS.md format), which
  resolves the AGENTS.md-vs-TIMELINE.md schema contradiction.
- The 02-generate SHAPE example IS the contract (fixed 2026-11-05): it must
  show exactly what the GENERATED schema requires - `blocks` is an object
  whose single key `blocks` holds the ordered array (the wrapper is the
  canonical artifact shape across render/interactive/review). In the killed
  class-11 run the example showed a flat array while the schema required the
  wrapper; the model obeyed the example and died on validation twice. A unit
  test now pins the example's wrapper form and the prompt-stated budget to
  the schema's `maxItems`.
- Prompt WRITING follows `skills/prompting-and-agent-design/` (2026-11-04):
  generation prompts are goal + deliverable contract, not execution plans;
  reviewers get honest framing, an exact severity ladder and a way out
  (`unverified:` minor) instead of "assume there is a defect"; every guarantee
  code can enforce lives in code, and stage prompts carry only what each stage
  needs to judge - including the lesson text at 03-check, so "taught before
  tested" is verifiable.

## Model calls: the llm_manager node (2026-11-07)

Why this exists: on 2026-11-07 a factory run died at stage 10-reviewfix. The
inference server kept generating tokens for 3,592 s per attempt (77,921 then
131,445 then 199,056 tokens across three transport tries) while the client
sat silent and read-timed-out at 3,600 s each time. The old client's
`requests` timeout is a per-read-operation timeout, not a total cap, and a
non-streaming response sends zero bytes until generation ends - so a rambling
generation was unkillable, and every transport retry re-bought the same
lottery while the single server slot burned.

The fix is structural, and it lives in a standalone package plus its own
deployment node:

- **`llm_manager/` (library)** - the single, generalized model-call module:
  `config.py` (LLMConfig: every knob is an input variable), `client.py`
  (LLMManager: `complete()` / `stream()` / `stream_events()`),
  `validation.py` (parse + schema rounds with errors-as-context feedback),
  `errors.py`. It imports NOTHING from `factory/` (guarded by a test),
  prints nothing (observer hooks instead), never counts tokens locally (the
  server's reported usage only), and owns retry semantics itself
  (`max_retries=0` is mandatory on the underlying langchain client so there
  is exactly one retry policy).
- **`llm_manager/service/` (the node)** - the same package behind a small
  FastAPI app speaking plain OpenAI chat-completions (`POST
  /v1/chat/completions`, aggregated or SSE; `GET /healthz` is process-only
  and never calls the model). Policy lives on the node, not in request
  bodies: JSON mode and the model are the node's configured behavior, and a
  body `model` naming a DIFFERENT model is refused with a 400 that names both
  models (a mismatch is a misconfiguration; silently answering with the
  node's model would hide it). Shipped as its own slim image
  (`Dockerfile.llm-manager`, no torch/pdfplumber/playwright) and deployed as
  an isolated Deployment + Service (`k8s/16-llm-manager.yaml`, ClusterIP).

Call topology (who talks to whom):

    factory Job -> llm-manager Service -> inference-router (dev) -> server

Every consumer points its `ZIVON_BASE_URL` at the node and speaks OpenAI
format; the node is the only caller of the inference server. That is why a
future translation service needs zero new plumbing (same env contract), and
why the voice agent stays out of scope here (voice streaming is a different
domain).

**Streaming semantics (the honest timeouts):**

- Model calls stream by default (`ZIVON_STREAM=true`): bytes flow as tokens
  are generated. `ZIVON_TIMEOUT_S` therefore means the maximum INACTIVITY
  between chunks - a thinking model legitimately silent before its first
  token keeps the call alive only up to the inactivity bound; a dead server
  is detected honestly; a generating server is never mistaken for a hung
  one. With `stream=false` the old per-read-operation semantics apply (and
  bound nothing) - the non-streaming path is kept working, not shipped as
  the default.
- `ZIVON_CALL_DEADLINE_S` (cluster default 7200) is a total wall-clock cap
  per model call, checked on every chunk. On breach the stream is CLOSED
  mid-generation - closing the connection is what makes the server stop
  generating and frees its single slot - and a TransportError names the
  deadline and the chunk count. This is the knob that bounds a runaway
  generation even when every token keeps arriving on time.
- Transport retries (`ZIVON_MAX_ATTEMPTS`, exponential backoff
  `ZIVON_BACKOFF_BASE_S`) cover connection errors, inactivity timeouts, 429
  and 5xx. A retry restarts the WHOLE response; on the incremental API
  (`stream_events`) a failure after deltas were already delivered propagates
  instead of silently restarting (duplicated text is worse than a loud
  error).
- Retries live at the node: the factory's cluster ConfigMap ships
  `ZIVON_MAX_ATTEMPTS=1` for its leg because the node already retried the
  upstream leg - without that split, one dead upstream would fan out into
  node-attempts x factory-attempts calls.
- **Keepalives on the node's downstream leg (review fix 2026-11-07):** the
  Strata server streams thinking as `reasoning_content` deltas (probe-
  confirmed), and llm_manager deliberately does not re-emit them as content.
  A long thinking phase would therefore leave the node's SSE response silent
  while the upstream is healthily busy - so the node emits SSE comment
  keepalives (`: keepalive`) on its heartbeat cadence whenever the upstream
  yields nothing re-emittable. OpenAI-format parsers ignore comment lines per
  spec; the bytes keep the caller's inactivity timeout honest about what it
  is really waiting for.
- **Server-reported failure (terminal, message preserved):** an OpenAI-format
  server may answer HTTP 200 and put the failure INSIDE the stream as an SSE
  error payload (`{"error": {...}}` - llama.cpp context-overflow style; the
  node relays its own exhausted upstream exactly this way). The openai SDK
  raises a bare `openai.APIError` for such a payload; llm_manager maps it to
  a TransportError carrying the server's own words verbatim (they already
  name the fix when there is one) and does NOT retry - "the server says it
  failed" is terminal.

**Factory adapter (`factory/llm.py`):** a thin layer keeping every existing
contract - same public API, same artifacts
(`attempts/[<round_tag>/]attempt-NN/{request,response,meta}.json`, with
additive streaming evidence in meta.json: `stream`, `first_token_s`,
`chunks_received`, `call_deadline_s`, `finish_reason`), same error types
(llm_manager failures surface as the same ModelCallError / SchemaError with
their message shapes), same prints upgraded for streaming: the heartbeat now
shows REAL progress (`N chunks received`), so "thinking, no tokens yet" and
"streaming steadily" are visibly different states in the log. Validation
rounds run in-process via `llm_manager.validation.run_validation_rounds` -
only the LATEST rejected output stays in full in the retry transcript; older
ones are trimmed to 1200 chars (their full text is in the attempt artifacts).

No completion cap is ever sent (2026-11-04 founder decision, unchanged):
`max_tokens` is a constructor-only knob in LLMConfig with NO environment
variable - the factory never sets it; future consumers may, from code.

## Observability (2026-11-04, streaming upgrade 2026-11-07)

The 2026-11-04 stall diagnosis - a legitimate giant 02-generate call ran while
the log stayed silent for its whole duration - added a heartbeat layer. The
next slow run is diagnosable from the log alone:

- Every stage transition prints a live line: `[02-generate] starting` /
  `[02-generate] ok in 84.2s (claims=12 blocks=15)`.
- Every model call is bracketed: `model call started (validation round
  1/5...)`, then while it is in flight a heartbeat every 60 s (`still
  waiting on the model (60s, 42 chunks received...)`), then `model call
  finished in Xs (prompt_tokens=..., completion_tokens=...)`. A thinking
  model legitimately grinding for ten minutes now looks like work, not like
  a hang - and the chunk counter distinguishes "thinking, no tokens yet"
  from "streaming steadily".
- Rejected attempts print too (`attempt 2 rejected: ... -> retrying with the
  error fed back to the model`), so gate retries are visible.
- `meta.json` records `finish_reason` per attempt (2026-11-05; it used to be
  discarded, so a server-side context-limit truncation looked like a
  mysterious parse failure). A `length` cut is rejected with plain advice
  ("make the page more compact") instead of letting the model chase a broken
  JSON error.
- `status.json` stage entries carry `elapsed_s`; `run_report.json` aggregates
  `stage_durations_s` per stage (multi-round stages accumulate across rounds,
  resumed stages inherit their previous attempt's measurement) plus
  `started_at` / `completed_at`.

## Resume and freshness

- `python pipeline.py "Motion" --class 9` on a run that already exists (same
  chapter+class+fingerprint) resumes it: stages marked ok are skipped and their
  outputs reused; pending stages run. This is the sanctioned recovery for an
  infra kill (node reboot, OOM, manual `minikube stop`).
- `--fresh` wipes the previous run dir first — the operator's "regenerate this
  page from scratch" button (e.g. after prompt improvements).
- `--run-id` keeps parallel attempts of the same topic (each its own dir).
- In the cluster, `runs/` lives on the `zivon-sources` PVC (subPath `runs`), so
  stage artifacts — and every attempt's evidence — survive pod death.
- `PIPELINE_VERSION` (factory/stages.py) is part of the fingerprint. It is
  bumped whenever stage contracts change, so a run dir built under the old
  contract can never be resumed silently into new code — the guard refuses it
  and says to pass `--fresh`. It is 4 since 2026-11-05 (locate matching +
  generate blocks contract rewritten); version-3 run dirs, including the
  contaminated class-11 one, are refused by design.
- The learner class is per-run input, never config (founder decision
  2026-11-06): `config.json` carries no `learner.class_level` at all - a
  config default for a per-run value is a hardcode. `--class` pre-sets the
  class before the fingerprint; without it, `01-locate`'s chapter supplies it
  (loud print). Consequence: every version-4 run dir - built while a config
  default class leaked into its prompts and fingerprint - is refused on
  resume; re-trigger those chapters with `--fresh`.

## Privacy

The pipeline takes no learner data as input. The only learner-related config
left is `learner.language`; the learner CLASS is per-run input (`--class` or
the located chapter), never a stored value. Run artifacts contain source text,
prompts and model output only.

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

## Design doctrine flow (open-ended)

Visual style lives in exactly one place: `docs/frontend/design-doctrine.md`
and its lesson-page examples (`docs/frontend/design-doctrine-lesson*.html`).
The factory holds no design information in prompts or code - `factory/design.py` is the
single point where it touches design, and it hands the LIVE documents to the
model stages at build time. Founder rule (2026-11-04): anybody who reviews,
writes or edits page code gets the doctrine AND the lesson-page example; the
main (post/brand) example is out of factory context so its single-file demo
style cannot bleed into generated pages. The example block is labelled
"VISUAL STYLING REFERENCE ONLY" before the example bodies: the examples show
how a finished page LOOKS and how COMPLETE it is - their topic, facts and
questions belong to an unrelated chapter and must never be reused or imitated,
and content coverage is dictated by the source material, never by the
examples (founder diagnosis 2026-11-04: the old example's plain-simple
content was bleeding into generated pages). The candidate "example lesson
page 2" (full coverage of NCERT ch. 6) was superseded on 2026-11-05: the
founder had a stronger model rebuild it with sound layout code plus the
**LessonKit** alignment kit, and that file replaced the live example
(`docs/frontend/design-doctrine-lesson-example.html`); the candidates folder
was deleted. The kit is shell-owned: `frontend/assets/zivon.js` carries the
same LessonKit code, every generated page gets ruled-line alignment, baseline
normalisation and the title pen underline from the shell, and the loader
header tells the model the kit is shell-owned and must never be copied into
a page (doctrine v1.4, §10.2). The founder's same-day second pass (doctrine
v1.5) externalised the kit as `docs/frontend/lesson-kit.js` beside the example
(the example guards: no kit loaded, no page; the examples glob is HTML-only on
purpose, so the kit implementation never enters model context), ruled ONE
content-width token `--page-w` (47rem) with no per-block max-widths, and fixed
the vt-diagram labels and the recoil drawing.

- **02-generate** gets the doctrine document (its diagram rules govern the SVGs
  the generation specs) plus the parsed palette; diagrams no longer invent
  colours. The mechanical SVG element contract stays pinned; the doctrine's
  hand-drawn language is expressed with the allowed elements only.
- **05-interactive** gets the doctrine document, EVERY example page the glob
  finds, the palette, and a medium-translation bridge line: the shell (grid,
  cards, tape, controls) is renderer-built; the model fills one canvas
  simulation inside a paper card, reads the examples for the visual language
  and never copies their structure.
- **09-review** gets the doctrine document AND the lesson-page example, plus a
  checklist item: a clear doctrine violation is major; one that misleads the
  learner about what moves or what is correct is fatal.
- **08-fixloop** and **10-reviewfix** (2026-11-04) get doctrine + example +
  palette too: they rewrite page code, so they must fix toward the reference
  language, not drift from it while repairing.

Open-ended by construction: a doctrine edit flows into every future run with
zero pipeline changes, and a new lesson example file matching the glob joins
every code stage's context automatically. The palette is parsed verbatim from
`frontend/assets/zivon.css` (canvas code needs concrete hex values; page.css
uses the variables by name), so generated colours match the shell that
renders around them.

Budget: the composed block must fit `limits.max_chars_design_context`. If the
doctrine outgrows the model's context the pipeline fails loudly with the
numbers - it never silently truncates.

The shell itself (`render.py`, `zivon.css`) is the human-maintained
implementation of the doctrine. On 2026-11-04 the §10 lesson shell was pulled
forward from Phase 4 and ported; the founder's design batch the same day
retyped it per doctrine v1.3: `zivon.css` implements §10 for topic pages
(taped paper cards, typed Courier Prime body on a strict 36 px ruled rhythm,
Caveat only on titles/headings/annotation labels, clean diagram geometry,
fixed-height visual boxes), scoped so nothing leaks into the landing shell (§10
scope guard). The `handify_svg` hand-stroke pass in `render.py` was retired -
model diagram SVG renders exactly as authored; only annotation arrows may
carry hand strokes (now a prompt-side instruction in 02-generate). Frame
adaptation is a harness guarantee: the perf gate measures horizontal overflow
at each profile's viewport (360 px weak-android, 1280 px mid-laptop).
Remaining §10 items stay Day-9 work: the two-column page grid and the language
bar.

## Performance budgets

`testing/content_factory/perf/profiles/*.json` are the tuning knobs (viewport, CPU throttle
rate, RAM ceiling, load/FCP budgets, FPS floor, core pinning). The default
shipping gate is `weak-android.json` (750 MB browser-tree RSS per the
founder's spec, 4x CPU throttling, 2 cores). The harness measures
Navigation Timing, FCP/LCP, peak Chromium-tree RSS via psutil, and rAF FPS,
and fails on any console/page error.

**Loosened 2026-11-04 (founder decision):** the gate's load/FCP budgets are
raised (load 2.0 → 6.0 s, FCP 1.2 → 3.5 s) while the pipeline's first real
generation runs are being diagnosed - no generated page has yet been measured
against the tight numbers, and a strict-but-unmeasured gate would only add
repair rounds to the timing story. The 750 MB RAM ceiling, 24 fps floor under
4x throttle, and 2-core pinning stay at founder spec. Tighten load back
toward < 2 s at the Phase 4 frontend pass using measured numbers from 07-perf
reports.
