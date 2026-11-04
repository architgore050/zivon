# Session log — 2026-11-04 — coverage contract + example framing + example lesson page 2 (founder follow-up batch, image 0.3.4)

## What we set out to fix

The founder's verdict on the regenerated Motion page: it "taught only the basics" — it
skipped chapter depth (momentum, the systems section) and skipped every practice question.
His hypothesis was PDF truncation. His asks: (1) make the prompting crystal-clear that the
example HTML is a **visual-styling reference only**, unrelated to required content; (2) build
a much better example — "example lesson page 2" — by reading the NCERT Motion chapter and
walking the pipeline steps personally, saved as a candidate that replaces the current
example only after his approval.

Our autopsy of `runs/motion-c9` + a one-shot peek pod reading the cached chapter text off
the `zivon-sources` PVC rejected the truncation hypothesis: ingestion was **complete**
(`ncert_text_truncated: False`, all 22 pages, 57,937 chars, every exercise 1–16 present).
The model saw the whole chapter and still wrote a thin page. The four real causes:

1. **Prompt caps in `02-generate`.** "3–6 lesson sections", "8–20 claims", checks "at least
   3", and — the killer — worked_example "do not compute new figures": a worked example
   could only restate numbers found verbatim in the source, which makes every NCERT
   numerical exercise structurally impossible. The model complied and skipped all of them.
2. **`rule_numbers` in `factory/checks.py`** fatal-flagged any answer numeral that did not
   appear verbatim in the ground truth. Computed answers were illegal by harness design.
3. **No coverage dimension in the reviewer rubrics.** `03-check` passed the thin page clean;
   `09-review` passed it with 1 major + 7 minor. Nothing in any gate asked "did the page
   teach the whole chapter?".
4. **Example bleed-through.** The 14.6 KB simple trilingual "Reflection of light" example
   was injected into 05/08/09/10 with no framing — its plain-simple content shaped what
   those stages considered a normal page.

## What we changed

1. **`02-generate` — the COVERAGE CONTRACT.** The goal is now the WHOLE chapter: inventory
   its titled sections, in-text questions (Pause & Ponder), worked examples and
   end-of-chapter exercises, then map every item to a block — a lesson section, a check, a
   worked_example or a reveal; nothing may be dropped. Section cap relaxed to "every titled
   section of the chapter gets its own lesson section (typically 5–10)", claims 8–20 →
   12–40, check floor driven by the chapter's own question inventory. worked_example
   rewritten: the problem statement VERBATIM from the source, the answer COMPUTED from
   those numbers (the old "do not compute new figures" survives only as the claims rule —
   no invented unit conversions inside claim text). The inventory doubles as a self-audit
   the model must run before emitting.
2. **`03-check` — two new review dimensions.** Item 6 RECOMPUTE: recompute every
   worked_example and numeric check; a wrong computed answer is fatal. Item 7 COVERAGE:
   omitting a chapter section, worked example or exercise is fatal. The fatal ladder was
   extended to name coverage omissions explicitly.
3. **`04-repair` can now ADD blocks.** A coverage omission is fixed by appending new blocks
   (new ids at the end, teach-then-test ordering, last added block a check) — matching
   `merge_blocks` append semantics — instead of only rewriting flagged blocks. A caught
   issue still goes to its own fixer; the whole pipeline is never re-run (founder law).
4. **`rule_numbers` rewritten — the guarantee split.** Problem/question-STATEMENT numerals
   are code-checked verbatim (whole-numeral match, no substring smuggling) — invented
   problem data is a harness-level fatal. Answer and option numerals are deliberately NOT
   code-checked: textbook exercises are meant to be computed, and derivability cannot be
   verified by string match. Their correctness is the reviewer's recompute job (fatal →
   04-repair).
5. **Example framing in `factory/design.py`.** The injected block now opens with
   "VISUAL STYLING REFERENCE ONLY" framing **before** the example bodies: the examples show
   how a finished page looks and how complete it is; their topic, facts and questions belong
   to an unrelated chapter and must never be reused or imitated; content coverage is
   dictated by the SOURCE MATERIAL.
6. **`max_chars_design_context` 48000 → 64000** (`config.json`) so the richer candidate
   example fits when approved (measured composed context 63,368 < 64,000).
7. **Doctrine §10 scope line corrected.** The old scope sentence described a lesson page as
   "a topic, its diagram, one simulation, one question" — itself a thin-page framing. It now
   reads "a chapter taught in full (its sections, diagrams, simulations, worked examples and
   practice questions)", plus an explicit sentence that the reference implementation is a
   styling-and-completeness reference, not a content template.
8. **Example lesson page 2 built by hand.** We read the actual chapter (NCERT Class 9
   Science 2025 ed, ch 6 "How Forces Affect Motion", 22 pages — full text extracted to a
   scratch file and mined for exact law statements, example statements and exercise
   statements) and wrote the page the pipeline *should* produce:
   `docs/frontend/candidates/design-doctrine-lesson-example-2.html` (≈ 43 KB). All 7 titled
   sections (6.1–6.7) each get a lesson section labelled with its NCERT section number;
   11 checks (P&P 3/4/6/7/9/10 + Revise 2/3/5/9/16 + the spacecraft final check); 11 worked
   examples (Ex 6.1 net force, 6.2 box+friction, 6.4 barbell 294 N, 6.5 block 0.4 m, 6.6
   car graph 3000 N, 6.8 gun recoil 0.4 vs 20 m s⁻², snake boat 18000 N, Revise 12 bullet
   500 N, 13 football 0.015 s, 14 rough patch 10 m, 1 friction=F) — problems verbatim,
   answers computed step-by-step; 3 sims (net-force lab, zero-friction thought experiment,
   recoil lab on Ex 6.8 numbers); 4 diagrams with **to-scale arrows** (the 10 N/6 N block
   directly answers last run's non-proportional-arrow flag); 1 reveal (how Activities
   6.3/6.4 found F = ma); misconceptions panel; glossary; At a Glance verbatim; an
   "explain out loud" list. Exercises 6/10/11/15 have garbled figure data in the PDF text
   layer and were skipped. Content is English-only with static language-bar markup (the
   shell's language bar is a Day-9 item; trilingual full-chapter content would blow the
   injection budget).
9. **Candidate quarantine.** The candidate lives in `docs/frontend/candidates/` — outside
   the `doctrine_examples` glob (`docs/frontend/design-doctrine-lesson*.html`) — so it
   reaches no run until the founder approves. Approval = move the file into `docs/frontend/`
   (the glob picks it up with zero pipeline changes; the budget already fits).

## Verified

- 211 unit + 10 frontend + 7 integration green (in-image run on the factory image, repo
  mounted). New/updated anchor tests: example framing lands before the example bodies; the
  coverage-contract anchors ride in the 02 prompt; the recompute + coverage gates ride in
  the 03 prompt; the repair ADD-blocks rule rides in the 04 prompt; `rule_numbers` accepts
  computed answers and still fatals invented problem data (tested via "73 m/s").
- Candidate page: HTML parses clean, `node --check` on its script passes, no `eval`, no
  inline event handlers, only external ref is the Google Fonts stylesheet (same pattern as
  the current example); composed design context with the candidate = 63,368 chars < 64,000.
- Frontend test suite scans only `frontend/` — the candidate directory cannot break it.
- Docs updated in the same batch: `docs/content-factory/architecture.md` (coverage contract,
  recompute gate, rule_numbers split, example-framing paragraph + candidate location),
  `docs/content-factory/config-reference.md` (64000 rationale), `docs/frontend/design-doctrine.md`
  (§10 scope + example-role sentence).

## What this deliberately does NOT do

- It does not replace the current example — the candidate waits for founder approval.
- It does not re-decide the agent graph — only prompt/doctrine/config text inside the
  frozen stage modules changed (architecture unchanged).
- It does not trigger a generation run — the `--fresh` Motion trigger is the founder's.
- It does not add a coverage *code* check: coverage is a reviewer dimension (a judgement
  against the source pack), while invented problem data stays a harness rule.

## Next

1. Founder reviews the candidate (open `docs/frontend/candidates/design-doctrine-lesson-example-2.html`
   in a browser) → approves (move into `docs/frontend/`) or amends.
2. Founder triggers `scripts/trigger-factory-run.sh "Motion" 9 --fresh` on image 0.3.4.
   Expect a longer run than last time: a full-coverage 02-generate output is bigger (the
   diagnosed attempt-01 already took 1629 s / 38,925 completion tokens); the 3600 s/request
   and 7200 s Job budgets stay, and schema-repair rounds re-emit the whole JSON.
3. After the run: `scripts/publish-frontend.sh` + `scripts/publish-artifacts.sh`; re-check
   the "text inside cards sitting outside the cards" symptom on the regenerated page.
