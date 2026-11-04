# Session log — 2026-11-01 — content factory v1

Workstream: the build-time content factory (this agent's lane). Posts, design
doctrine and its extension live elsewhere. Log named by date, per founder
decision (day numbering is still contradictory in the posts - see open items).

## Done

- Read every doc in the repo before writing code (AGENTS.md, README, TIMELINE,
  all four DECISIONS-and-RESEARCH docs, design doctrine + example HTML).
- **Content factory v1, end to end**: `pipeline.py "Motion" --class 9` runs
  12 stages - source ingest → exact NCERT chapter search + vector search over
  other books (sentence-transformers, local) → ground-truth synthesis →
  self-contained lesson edit → block draft → rule+model review → interactive
  build → render → weak-hardware perf gate → fix loop → code review → link
  into `frontend/`. Files are the only interface; every model call's request,
  response, retries and validator feedback land in `runs/<run_id>/`.
- **Source catalog** for classes 6-12: `sources/catalog.json` (machine) +
  `docs/source-catalog.md` (research + licensing + honest verification
  status). NCERT codes verified from indexed title-page text; chapter counts
  deliberately marked unverified with a loud, documented discovery rule.
  OpenStax/Siyavula are manual-placement entries (direct PDFs are behind
  dynamic buttons).
- **Frontend v0**: Field Notes courses page + generated topic pages. Shared
  layer (`zivon.css` placeholder from current doctrine tokens, `zivon.js`:
  quiz wiring, simulation runtime, pen-underline) + generated per-topic layer.
  Doctrine fonts (Bricolage Grotesque, Courier Prime, Caveat) bundled locally
  under OFL - pages make zero external calls and carry a strict CSP.
- **Weak-hardware perf harness** (`testing/perf/harness.py`): CPU throttling
  via CDP, optional core pinning, peak browser-tree RSS (750 MB ceiling per
  founder spec), load/FCP budgets, rAF FPS, console/page errors fail the run.
  Profiles are data files - harshness is tunable.
- **testing/**: 96 unit tests + 2 integration tests. The integration set runs
  the real orchestrator against an OpenAI-format mock server with fixture
  PDFs, including a scripted schema-retry, and the real Chromium for the perf
  gate. All green in this sandbox (Python 3.12, CPU torch, chromium).
- Visual check done: landing page and a generated topic page (every block
  type incl. live simulation) screenshot-reviewed; course card and pen
  underline render per doctrine.

## Decisions taken (documented in docs/content-factory/)

- Block payloads always under `spec` (AGENTS.md wins the schema contradiction).
- Chapter matching by title inside the PDFs, not by guessed chapter numbers -
  numbering drift cannot break content correctness; class label is verified
  from the prelims text at ingest.
- JSON mode forced on (founder choice), with a crash-plus-hint if the server
  rejects it - no silent downgrade.
- English-only material in v1; `learner.language` exists for later.

## Not done / open

- NCERT chapter counts unverified (sandbox cannot reach ncert.nic.in); first
  real run may need catalog fixes - ingest will say exactly which entry.
- Model quality against a real local Qwen is untested (no access to the
  inference server from here); the mock proves wiring only. Founder runs the
  first real chapter.
- Doctrine extension (other agent) will replace the placeholder `zivon.css`;
  class names and tokens are the contract.
- Broken doc references flagged earlier are still untouched, per instruction.
- Fonts: Caveat is wired for annotations but generated pages don't emit
  handwritten notes yet (annotation overlays need the doctrine agent's
  extended rules first).

## Next

1. Point config.json at the real server, run `pipeline.py "Motion" --class 9`,
   read the generated page critically (human edit rate is the metric).
2. Fix any catalog 404s ingest reports; flip `chapters_verified` to true as
   books verify.
3. Generate topics #2 and #3 unattended (TIMELINE Day-3 goal) and log edit rate.
