# testing/ — test sets for everything the factory ships

Run from the repo root:

    # fast unit sets (no network, no browser; the embedder is a fixture)
    python -m unittest discover -s testing/unit -t .

    # full pipeline against the mock inference server + real headless Chromium
    # (needs: pip install -r requirements.txt && python -m playwright install chromium)
    python -m unittest testing.integration.test_end_to_end

    # the weak-hardware perf harness on any page
    python -m testing.perf.harness --url file://$PWD/frontend/index.html \
        --profile testing/perf/profiles/weak-android.json

## Layout

| Path | What it covers |
|---|---|
| `unit/test_config.py` | config validation: unknown keys, wrong types, sentinel model, env var resolution |
| `unit/test_schemas.py` | stage handoff schemas + the committed fixtures validate against them |
| `unit/test_checks.py` | rule checker: answer keys, citations, self-containment, invented numbers, SVG safety |
| `unit/test_lint.py` | hard lints: eval/Function/fetch/URL strings, external CSS/HTML refs, inline scripts |
| `unit/test_textops.py` | title normalisation/exact matching, chunking with overlap |
| `unit/test_retrieval.py` | per-page chunking, embedding cache invalidation, cosine top-k (FixtureEmbedder) |
| `unit/test_ingest.py` | ingest over file:// PDFs: class evidence, 404 policies, manual books; locate: exact match, ambiguity, class filter, supplements |
| `unit/test_render.py` | page HTML, CSP, manifest, staging layout, lint-gated render, courses.js |
| `unit/test_llm.py` | LLM client vs mock: artifacts on disk, retry feedback loops, error paths |
| `unit/test_perf_profile.py` | profile validation and budget verdict logic |
| `unit/test_catalog_sync.py` | catalog.json ↔ docs/source-catalog.md sync; class coverage 6-12 |
| `integration/test_end_to_end.py` | the REAL orchestrator as a subprocess: fixture PDFs → every stage → linked page; plus loud-failure test with a dead server |
| `mocks/openai_mock.py` | OpenAI-format mock keyed on the `[ZIVON STAGE: ...]` marker; supports scripted first-attempt failures |
| `mocks/fixtures/` | stage outputs + `make_pdfs.py` (hand-rolled minimal PDFs, reproducible) |
| `perf/harness.py` | the Performance Engineer's instrument (CPU throttle, RSS sampling, FPS, budgets) |
| `perf/profiles/*.json` | harshness tuning: `weak-android.json` (shipping gate), `mid-laptop.json` |

## What is NOT tested here

The quality of your real model's outputs. The mock proves the wiring, schemas,
rules, rendering, perf gate and linking; it cannot prove Qwen writes good
Physics. That is what stage 05-check, stage 10-review and the human edit rate
are for.
