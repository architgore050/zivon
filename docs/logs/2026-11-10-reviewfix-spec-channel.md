# 2026-11-10 — Reviewfix spec-correction channel (PIPELINE_VERSION 8, 0.3.18) — + steps-shape harness guarantee (0.3.19)

## Done

- **Root-caused the failed run `factory-run-laws-of-motion-221519`** (`--fresh`, stalled at 10-reviewfix stall limit). Three layers, all real:
  1. **Disjoint surfaces:** 09-review gates the page the renderer drew (index.html), but the fixer may only write page.js/page.css. The flagged defects were BLOCK CONTENT (b-04 diagram: ball drawn at ground level instead of the slope top; friction arrow vertical where the physics says horizontal) — no fix the fixer could produce ever reached the reviewed artifact. Four rounds of improving page.js; index.html never changed; plateau.
  2. **Non-idempotent shell strip:** `_rebuild_html_if_needed`'s extract path re-joined nested shells on every rebuild (the feed's first lazy `index()` strip had produced them), so double headers/glossaries/footer could also never converge.
  3. **Operator:** the `--fresh` trigger wiped the prior good run's artifacts — sibling runs `200431`/`221405` had already published a good Laws of Motion; nothing to clean up, the wiped dir was the loss.
- **Fixed as one contract change (PIPELINE_VERSION 7 → 8):**
  - `FIX_PLAN` gained optional `blocks`: corrected FULL block objects (id+type+spec+citations), merged by id. **Simulation blocks excluded** — sim behaviour is page.js draw code (05/10 boundary); a sim spec edit costs a round, not the run.
  - `_rebuild_html_if_needed` re-renders the page body from the block specs by default (extract path is the fallback, and it is idempotent for nested shells now). index.html has exactly one writer.
  - Corrected draft is threaded everywhere: reviewfix output carries `"page"`; the 09/10 loop adopts it before each re-review; `stages._preferred_blocks` makes every resume/late-stage blocks load prefer 10-reviewfix's corrected page over 04-repair's merge over the raw 02-generate draft.
  - Prompt contract updated (reviewfix system + user prompts state the BLOCK-CONTENT rule; fixloop docstring notes the channel; reviewfix docstring rewritten).
- **Release ritual:** image tag 0.3.17 → 0.3.18 across Dockerfile, docker-compose.yml, `k8s/10/20/50`, `docs/deployment/{docker,kubernetes,cicd}.md` (+ `docs/specs/evals/spec.md` image refs). Build failed twice first — both build-env drift, not this fix:
  1. playwright ≥1.65 (float) bundles a Node driver linking `libatomic.so.1`, absent in slim; `playwright install --with-deps` must run the driver before enumerating deps → exit 127. Fixed: explicit `libatomic1` in the apt layer + the playwright step split into its own `RUN` layer (a playwright failure no longer re-downloads pip's wheels — each failed attempt had been re-downloading ~all of pip). Gotcha recorded in `docs/deployment/docker.md`.
  2. Host network flakiness (PyPI read timeout, `cdn.playwright.dev` `EAI_AGAIN`) — plain retry.
  Then: built `--network=host`, in-image smoke green, `minikube image load`, `apply-k8s.sh` re-applied; in-cluster startup suite `test-startup-084044` Complete — **307 unit + 11 frontend + 8 integration OK on 0.3.18**.
- CI note: the playwright float drift will eventually hit GitHub Actions builds too; if it does, pin playwright to the last known-good instead of chasing the driver's apt needs.
- **Tests:** new `TestReviewFixSpecChannel` (test_review.py) — caption correction rendered into index.html with a single shell + threaded draft, sim-spec edit rejected with feedback, renderer-owned file in plan rejected. New `TestSpecCorrectionChannel` (test_perf_fixloop.py) — merge-by-id, rebuild-without-nesting + idempotence, nested-shell collapse. Version pin test → 8. ruff/format/mypy clean on the diff.

## Not done / notes

- Host unittest suite keeps its pre-existing pdfplumber gaps (CI/in-image is the arbiter).
- Host `frontend/` snapshot still stale vs cluster (older 3 courses) — founder-side sync, not part of this fix.
- Failed Job `221519` left as evidence (Jobs are immutable); no cleanup needed.
- `docs/deployment/cicd.md` line ~49 references the image tags generally — kept its 0.3.17 mention as a dated note? NO: updated to 0.3.18 in the same PR (and to 0.3.19 for the steps-shape fix later the same day).

## Next

- **Model switch landed (2026-11-10, founder decision):** `stealth/crouton-alpha` revealed itself and is no longer free (also gone from the catalog). Factory now on `nvidia/nemotron-3-ultra-550b-a55b:free` — probed live first (exact free-route slug, 1M ctx, pricing 0, JSON mode honored, **real usage stats** — crouton's `usage: null` telemetry caveat was model-specific and is resolved), `apply-k8s.sh` re-run (ConfigMaps re-rendered, node rollout-restarted per gotcha 18, pod env verified), chain verified end-to-end through the node Service with streaming JSON mode. Config-only; PIPELINE_VERSION stays 8. Fallback recipe (local slow `qwen3.8-flash-next-iq3_xxs` via the router) written into the infra.env comment.
- Re-trigger Laws of Motion on 0.3.19 (NO `--fresh`; note the wiped dir makes it a fresh run in practice) AND the new brain; watch 03-check/09-review issue rates vs the crouton baseline — the free model is "famously kind of stupid" for code, the reviewer gates are the safety net.
- Founder-side: local network fix for the NCERT netblock, then the class-11 fresh re-trigger (v8 refuses old dirs).
- Watch the playwright float (`playwright>=1.45`) — the 1.65 libatomic drift hit the local build; CI is equally exposed.

---

## Same day, later — nemotron's first run died at 02-generate: steps shape (fixed, 0.3.19)

- **Failure:** fresh run `factory-run-laws-of-motion-090310` (the first run actually ON the new brain) crashed at 02-generate validation round 3: `rule_self_containment` hit `AttributeError: 'str' object has no attribute 'get'`. Evidence (mirrored `runs/laws-of-motion-c11/02-generate/attempts/attempt-03/`): the draft was accepted HTTP-side, but block **b-23** (one of 13 worked_example blocks) carried `"steps": {"title": ..., "detail": ...}` — ONE dict instead of the list of step dicts the prompt specifies. Python then iterated that dict (yielding its string KEYS) into `step.get(...)`.
- **Why the schema missed it:** `BLOCKS`'s per-item `spec` is untyped (`{"type": "object"}`) — the steps shape lived only in prompt prose (violating the repo's own "guarantees in the harness, not prose" rule). Attempts 1–2 died of OTHER schema misses (lesson `equations` extra key; missing blocks), so the model had already been told something was wrong each round and produced new shape violations — typical for a "kind of stupid" model: less good at conforming multi-shape JSON than crouton/qwen.
- **Fix (0.3.19, harness):** new `checks.rule_shapes` — `worked_example`/`reveal` `steps` must be a list of dicts, fatal; `run_all_rules` short-circuits after shapes so the later rules never reach the crash while the retry transcript lands the fix instruction (`... steps must be a list of {"title","detail"} objects`); the model then retries. Regression tests: `TestShapes` (4 tests: dict-steps fatal, missing steps fatal, run_all_rules no-crash short-circuit with the exact defect, list passes). ruff/format/mypy green. PIPELINE_VERSION stays 8 (no artifact contract change — invalid drafts were always invalid; now they get a named verdict instead of a crash).

## Same day, later still — OpenCode Go as the model route (0.3.19 factory, 0.1.1 node)

- **Why:** crouton (paid/absent), nemotron (shape crashes) — the founder's OpenCode Go subscription gives better inference through an OpenAI-compatible gateway: `https://opencode.ai/inference/go/openai/v1`, model `deepseek-v4.1-flash` (30-model catalog verified live).
- **Gateway requirements found by probing:** the gateway 400s with `MissingSessionID` unless the request carries a stable `x-opencode-session` header, and it asks clients to identify themselves in `User-Agent` rather than spoof an SDK. Both landed as generic knobs in `llm_manager`: `ZIVON_EXTRA_HEADERS` (JSON object, loud parse errors) and `ZIVON_USER_AGENT`, sent on the httpx client and ChatOpenAI `default_headers`; rendered into `zivon-llm-manager-config` by `apply-k8s.sh`; two new unit tests (`TestLLMConfigFromEnv`). Node image bumped **0.1.0 → 0.1.1**, built/loaded/applied.
- **Key handling (the command):** the Go key lives only in the runtime Secret — `kubectl create secret generic zivon-factory-env -n zivon --from-literal=ZIVON_API_KEY='<opencode-go-key>' --dry-run=client -o yaml | kubectl apply -f -`, then `bash scripts/apply-k8s.sh` (rollout-restarts the node per gotcha 18). The key was read from the local OpenCode credential store (never printed).
- **Verified live through the node Service:** non-streaming JSON mode → clean JSON + real usage stats; streaming → clean stop. Caveats on record: DeepSeek JSON mode needs the word "json" in the prompt (all factory prompts have it); Go docs gate DeepSeek behind workspace privacy Regions → Global (our workspace passes).
- **Still pending:** the Laws-of-Motion resume (02-generate was never ok, so the re-trigger re-runs it from scratch on the new route) and the class-11 NCERT-network re-trigger.

## Same day, last batch — identity, ordering, graph content, in-figure labels (PIPELINE_VERSION 9, 0.3.22)

Founder bug reports after the first Go-model run; every one fixed at the layer that owns it.

1. **Duplicate "Laws of Motion" pages + tagline titles.** Root cause: `render.run` derived the topic slug and page title from the MODEL's lesson headline, so each run could publish a new directory (`laws-of-motion` vs `laws-of-motion-from-aristotle-s-mistake`, the latter titled "Laws of Motion: From Aristotle's Mistake to Newton's Three Laws"). Fix: `chapter_display_title()` + slug from the located chapter (deterministic, "LAWS OF MOTION" → "Laws of Motion"); page `<title>`, `<h1>`, manifest `title` and directory follow the chapter; the model headline is retained as `lesson_title`. `factory/link.py` prunes stale duplicate dirs for the same course + chapter on publish.
2. **Catalogue ordering.** Sort was already chapter-number based; the appearance of "reversed" order came from only the newest manifest carrying `chapter_number` (chapter 4 jumped above unnumbered ch1–3). No code change beyond (1); regenerating the chapters with numbers restores textbook order.
3. **Graph content is a correctness check.** Added: 05-interactive FRAME law (axes recomputed from the current values every frame, ticks derived from the plot scale, quantity+unit labels) + GRAPH CONTENT law; 02-generate diagram CONTENT law (labels anchored to their element, arrow directions with N ⟂ surface and weight vertical, named angles actually drawn, no overlaps); 09-review design call judges graph content against the equations and checks page.js control→axis consistency. Grounded in the actual render defects from this run (misplaced "ball starts here" label, vertical N on the banked road, undrawn θ).
4. **In-figure text jumble** (founder correction: body prose was fine — the jumbled text was inside the visuals). `shots.py` keeps the focused capture (header + every diagram/sim/check at the three frames; body prose is deliberately not imaged — it burned image tokens for nothing). The fix is in the contracts: 05 gains the IN-FIGURE TEXT law (in-canvas labels must not overlap each other/axes/curve/apparatus, stay inside bounds, stay short) and the 09 design prompt names in-figure labels as ground truth to judge.
5. **"Re-trigger did not rewrite the output".** That is the resume contract: a completed run dir reuses every stage. `run_pipeline` now prints loudly that nothing is regenerated and points at `--fresh`.
