# testing/content_factory/ — test sets for everything the factory ships

Run from the repo root:

    # fast unit sets (no network, no browser; the embedder is a fixture)
    python -m unittest discover -s testing/content_factory/unit -t .

    # full pipeline against the mock inference server + real headless Chromium
    # (needs: pip install -r requirements.txt && python -m playwright install chromium)
    python -m unittest testing.content_factory.integration.test_end_to_end

    # the weak-hardware perf harness on any page
    python -m testing.content_factory.perf.harness --url file://$PWD/frontend/index.html \
        --profile testing/content_factory/perf/profiles/weak-android.json

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
| `unit/test_agents_generate.py` | graph v2 prompts + wiring: one giant generation call (rules in its retry loop, grounding law), 03-check severity ladder + the LESSON in the reviewer's context (verifiable "taught before tested"), 04-repair prompt + merged-page rules, block merge/remove |
| `unit/test_artifacts.py` | run artifacts: previous-run fallback, resume plumbing (stage_ok, fingerprint, wipe_run/--fresh), stage timing lines + `elapsed_s` / `stage_durations_s` accounting |
| `unit/test_design.py` | live design doctrine loading, example glob, palette parsing from zivon.css |
| `unit/test_interactive.py` | Visual Builder wiring: per-sim calls, facts + doctrine in prompt, lint inside the retry loop |
| `unit/test_render.py` | page HTML, CSP, manifest, staging layout, lint-gated render, courses.js |
| `unit/test_llm.py` | LLM client vs mock: artifacts on disk (incl. timing/usage meta), retry feedback loops, per-round attempt separation, call start/finish log lines, error paths |
| `unit/test_perf_profile.py` | profile validation and budget verdict logic |
| `unit/test_perf_fixloop.py` | 07-perf → 08-fixloop routing: fixable vs unfixable BudgetError, bounded rounds, pedagogy guard |
| `unit/test_review.py` | Code Reviewer prompt (cited facts, drawn behaviour, live doctrine, honest framing + `unverified:` way-out) + the v2 contract: a fail verdict is RETURNED as the report (routing to 10-reviewfix), not raised |
| `unit/test_catalog_sync.py` | catalog.json ↔ docs/content-factory/source-catalog.md sync; class coverage 6-12 |
| `integration/test_end_to_end.py` | the REAL orchestrator as a subprocess: fixture PDFs → every stage → linked page; resume (re-trigger reuses completed stages), fingerprint guard, catcher routing (03→04, 09→10, bounded), observability asserts (stage lines, call brackets, per-stage `elapsed_s`), loud-failure test with a dead server |
| `mocks/openai_mock.py` | OpenAI-format mock keyed on the `[ZIVON STAGE: ...]` marker; supports scripted first-attempt failures per stage (per-test fixture dirs) |
| `mocks/fixtures/` | component fixtures (`gt/lesson/blocks.json`), the combined `02-generate.json`, gate reports, `repair_plan.json`, fix plans + `make_pdfs.py` (hand-rolled minimal PDFs, reproducible) |
| `perf/harness.py` | the Performance Engineer's instrument (CPU throttle, RSS sampling, FPS, budgets) |
| `perf/profiles/*.json` | harshness tuning: `weak-android.json` (shipping gate; load/FCP budgets loosened 2026-11-04, see architecture doc), `mid-laptop.json` |

## What is NOT tested here

The quality of your real model's outputs. The mock proves the wiring, schemas,
rules, rendering, perf gate and linking; it cannot prove Qwen writes good
Physics. That is what stage 03-check, stage 09-review and the human edit rate
are for.
