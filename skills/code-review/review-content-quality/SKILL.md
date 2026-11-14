---
name: review-content-quality
description: Content-quality lens for code review. Use when reviewing generated learning content or a content-pipeline change such as lesson pages and blocks, question banks, practice sets, tests and test series, translations and i18n bundles, narration assets, catalogue or publish output, or the prompts and checkers that produce them. Judges grounding and citations, answer keys and explanations, numeric tolerance and units, curriculum coverage and marks/section structure, language coverage and script policy, copy and claim compliance, technical page integrity (block IDs, links, CSP, no eval, accessibility), and eval/logging evidence. Use when the user asks whether this content is correct, asks to review a lesson, question paper, or series, asks whether translations are good, asks whether pipeline output regressed, or wants generated content checked before publishing.
metadata:
  owner: zivon
  version: "1.0"
  evidence_date: "2026-11-14"
---

# Content Quality Review

Generated learning content is data that a student will read, trust, and be tested on. A page can pass every schema check and still teach the wrong answer, test a concept the chapter never covered, or show an English sentence where a Hindi lesson promised Hindi. This lens reviews the **artifact and the pipeline that produced it**, not just the diff.

Findings use the shared format and severity scale from `code-review`. Read this whole skill before applying it; load the three references as the procedure points to them.

## When to apply

Use this lens when any of these is true:

| Signal | Examples |
|---|---|
| A generated or hand-authored **lesson** changes | `frontend/courses/**`, a re-render, a new block, a diagram/simulation, a lesson manifest |
| **Assessment** content appears or changes | question banks, practice items, answer keys, explanations, marks, difficulty, blueprints |
| A **test series** or paper manifest changes | volume, coverage, section structure, duration, claims about CBSE/board alignment |
| **Translations** change | `i18n/*.json`, `10a`–`10d` outputs, glossary, locale hubs, language bar strings |
| **Narration** changes | `frontend/audio/**`, `narration-manifest.json`, speakable-block selection, TTS tags |
| **Catalogue/publish** changes | `courses.js`, `catalogue.json`, sitemap, robots, locale hrefs, publish report |
| A **content-pipeline prompt, checker, golden, or reviewer rubric** changes | `factory/agents.py`, `factory/review.py`, `factory/checks.py`, `factory/lint.py`, `evals/checkers/**`, `evals/cards/**`, `evals/goldens/**` |
| The user asks whether content is correct, complete, teachable, localizable, or ready to publish | "review this chapter", "is this answer key right", "why does this page say Grade", "did translation regress" |

For a content-only PR, run this lens **before** the general implementation/tests pass: if the content is wrong, line-level code comments are secondary. Still run `review-security` when the content pipeline touches untrusted input, uploads, or HTML/JS generation, and `review-production-readiness` when publish, storage, or scheduling changes.

## When NOT to use this lens

Say so and route elsewhere; padding a review with the wrong lens wastes the author's attention.

- **Product decisions.** Whether a chapter, feature, language, or series should exist is already decided in `docs/product/features.md` and `TIMELINE.md`, with the frozen product decision log as the authority. Do not re-litigate it here; ask a question with a doc citation.
- **Visual design and doctrine.** Whether a page looks like the doctrine is the frontend/architecture review's job. This lens checks that the page renders, is accessible, and carries content correctly; it does not redesign it.
- **Pure code refactors with no content artifact.** A rename in `factory/` that provably cannot change output needs implementation/tests, not this lens.
- **Voice runtime behaviour.** Tutor replies, barge-in, latency, and credit guard are voice/eval concerns. A prompt change that alters tutor answers is in scope only through its eval card and golden evidence.
- **Marketing, build-in-public posts, and docs prose.** Use `skills/content-creation/` and `review-docs-sync`.
- **Infrastructure and deployment.** Use `review-production-readiness`.
- **A substitute for the factory's gates.** This lens samples evidence; it does not re-run the whole pipeline or replace `03-check`, `09-review`, `10b-transcheck`, or the eval suite.

## Evidence rules

1. **Read the artifact, not only the diff.** Generated content is the product. A prompt diff that looks reasonable can still produce a wrong answer key; a one-line manifest change can rename a chapter on the catalogue. Open the rendered page, the pack, or the run output.
2. **Recompute every number you can.** For every worked example and numeric check, redo the arithmetic from the chapter's stated equations. Do not trust the explanation, the answer text, or a previous reviewer's "looks right".
3. **Trace claims to the source pack.** A `claim-01` citation is not grounding by itself. Follow the claim id to the ground-truth claim and then to the passage in the source pack. A citation that exists but does not support the sentence is **citation theatre**, and it is a finding.
4. **Use deterministic evidence first.** Run the repo's checkers before judging prose: schema/rule checks, lints, translation checks, link checks, smoke evals. The deterministic-first funnel (`docs/specs/evals/spec.md`) exists so a model judge never papers over a code-detectable defect.
5. **Match the best reference, not the average.** The published tree is not homogeneous: check `pipeline_version` across manifests before treating any live page as the bar (`docs/content-factory/architecture.md`, "Resume and freshness"). Compare with the current-shape pages (`frontend/courses/class-9-physics/motion/`, `frontend/courses/class-11-physics/laws-of-motion/`) and the doctrine lesson example. Do not copy a defect because it is live.
6. **Never spend credits or run live models in review.** No `python pipeline.py`, no live Timbre synthesis, no live judge. Use existing run artifacts, goldens, fixtures, and `--mock`.
7. **Label confidence, and cite a location.** `confirmed` means you opened/recomputed it; `likely` means a strong reading; `suspected` is a question, not an accusation. For a structured artifact, cite the item id or JSON pointer when a line number is meaningless.
8. **Do not re-run a whole pipeline to prove a downstream defect.** The repo rule is gate → its catcher inside one run (`docs/content-factory/architecture.md`). A review that says "regenerate everything" is not a finding; name the stage that should have caught it.

## Review order

Content problems compound downward, so review top-down:

1. **Identity and scope.** Does the artifact match the chapter, class, board, language, and series it claims? Is the title the chapter title, not a label or a model headline?
2. **Grounding and answers.** Are the facts, answer keys, explanations, and numbers correct and traceable to the source pack?
3. **Coverage and structure.** Does it teach and test the whole chapter, in the right order and with the right marks?
4. **Language and localization.** Is every promised locale complete, script-correct, and honest about what is missing?
5. **Technical page integrity.** Does it render, link, pass CSP, work on a phone, without `eval`, external calls, or broken diagrams/simulations?
6. **Evidence.** Are the deterministic checks, eval run, run ledger, and content debt attached and current?

## The content-quality rubric

Score each dimension **0–3**, with one sentence of evidence. The score is a summary; it never overrides a single blocker. A wrong answer key is a blocker even if every other dimension is a 3.

| Dimension | 0 | 1 | 2 | 3 |
|---|---|---|---|---|
| **Grounding and factual accuracy** | Claims untraceable; contradicts the source; a later-chapter concept taught as fact | Some claims uncited; a minor unsupported detail; `uncertain` missing | Every factual block cites a claim; no contradiction; no off-chapter concept | Every claim traces to a source passage; `uncertain` carried honestly; the chapter is the whole universe of the page |
| **Assessment integrity** | Wrong answer key, no answer, no explanation | Correct answer but no or thin explanation; tolerance or units missing | One correct answer, explanation present, tolerance and units declared | Independent recompute matches; distractors address misconceptions; tolerance and significant figures justified |
| **Curriculum coverage and structure** | Required sections or exercise types missing; test-before-teach | One required type missing; ordering mostly right | Every titled section and exercise type represented; teach-before-test | Coverage maps to the chapter inventory; marks/section structure matches the blueprint; no padding |
| **Language and localization** | Silent English in a promised locale; script violation; meaning changed | Partial translation; glossary term missing; stiff machine prose | Complete strings, script-correct, terms consistent, honest availability flags | Native-quality phrasing; first-mention glossary; no untranslated leak; units and symbols untouched |
| **Technical page integrity** | Blank/broken page; `eval`, external call, or broken CSP; missing blocks | Serious accessibility defect; broken link; design regression | Valid IDs, CSP clean, no external calls, keyboard usable, sim fallback present | Zero console errors; reflow at 320/360 px; accessible names/roles; reduced-motion honoured |
| **Evidence and eval coverage** | No deterministic check; no run artifact; no eval card for the failure mode | Unit tests only; no content eval; evidence bundle incomplete | Deterministic checks plus smoke eval pass; evidence bundle attached | Seeded-defect calibration meets baseline; eval run id, ledger, and coverage report all current |

Interpretation: **16–18** content-ready (minors only); **11–15** ship with explicitly logged debt and named follow-ups; **6–10** request changes; **0–5** do not publish. Report the score next to the findings, and name the single change that would raise the lowest dimension the most.

## How to run the review

The full procedure, sampling rules, exact commands, and severity calibration are in [references/review-procedure.md](references/review-procedure.md). The short form:

1. **Classify the artifact** and write a three-line map: pipeline stage → artifact → gate that approved it → evidence on disk.
2. **Open the artifact** and read it as a student would, then as a marker would (answer keys, marks, units).
3. **Sample deliberately**: inspect every answer key and citation; stratify prose/pedagogy by concept, type, difficulty, and language; never take only the first N items.
4. **Run the deterministic checks** that cover the artifact and the stage.
5. **Compare with the reference page/golden** and the stage's contract.
6. **Classify severity**, apply the release-gate policy, and write the report with [templates/content-review-report.md](templates/content-review-report.md).

The checklist that every content PR must answer is in [references/content-quality-checklist.md](references/content-quality-checklist.md). The recurring failure patterns and their default severities are in [references/anti-patterns.md](references/anti-patterns.md).

## Reporting

Use the suite's finding format. The lens tag is `content-quality`.

```
[severity][content-quality][confidence] path/to/artifact:LINE: Issue in one sentence.
Why it matters: the concrete learner or publish consequence.
Fix: the specific change, with the stage or check that should prevent recurrence.
```

For structured JSON, cite the item id as well as the file: `content/practice/class-9-motion.json:1 (item q-07)`. One finding per root cause; group repeats ("same wrong key pattern in q-03, q-11, q-17") instead of writing three near-identical comments. Lead with the verdict and the top issue.

### Release gate versus review severity

The repo's R1 gate says technical breakage blocks and content-quality debt is logged (the frozen product decision log; the current gate state is recorded in `TIMELINE.md`). Keep the two ideas separate:

- **Review severity** is intrinsic: a wrong answer key is a blocker whether or not the batch is allowed to ship.
- **Merge/publish decision**: any blocker → request changes. A major → request changes unless the owner explicitly accepts it as logged debt, and the debt is recorded in `TIMELINE.md` (the only task list) or the PR body with artifact, owner, and reproduction. Factual errors, wrong answer keys, off-chapter teaching, and false CBSE claims **never** qualify as "logged debt": they mislead a learner or misstate what the product is.
- A blocker that is only a **pre-existing published defect** is still reported, but the PR is not blocked for it; name the owner and the publish action that fixes it.

## Worked example

**A. A real published identity defect.** Opening the Class 9 catalogue shows a card titled "Describing Motion Around Us"; the page it links to opens with "Grade":

```
[major][content-quality][confirmed] frontend/courses/class-9-physics/describing-motion-around-us/index.html:20: The lesson H1 is "Grade", a data-field value, not the chapter title.
Why it matters: a Class 9 learner's first sentence on the page is wrong, the browser tab says "Grade - Zivon", and the catalogue and page disagree about what the lesson is.
Fix: correct `chapter.title` at the source (stage 01/source pack), re-render through 06/10d, and add a publish assertion that `lesson_title` is present and `chapter.title` is not a label such as "Grade".
```

The same file's `manifest.json:8` carries `"title": "Grade"`; report both as one root cause, not two findings. This is a pre-existing published defect: on a new PR, request changes; on an unrelated PR, record it as debt with the publish owner.

**B. An illustrative PR adding a Class 9 practice pack.** The reviewer reads all 18 items for keys and samples 6 across difficulty bands:

```
[blocker][content-quality][confirmed] content/practice/class-9-motion.json:1 (item q-07): The key selects "25 m/s" for a car accelerating from rest at 2 m/s² for 5 s; v = u + at gives 10 m/s.
Why it matters: a learner who computes correctly is marked wrong, and the explanation repeats the error, so the misconception is taught rather than corrected.
Fix: set the key to "10 m/s", rewrite the explanation around v = u + at, and add this item to the deterministic answer-key fixture.
```

```
[major][content-quality][confirmed] content/practice/class-9-motion.json:1 (item q-15): `explanation` is empty.
Why it matters: the product promises "why?" feedback (F-COR-CHK-01); an item without it turns practice into a score, not a lesson.
Fix: add a one-paragraph explanation that names the concept and the step, or drop the item from the v1 pack.
```

```
[major][content-quality][confirmed] content/practice/class-9-motion.json:1 (items q-03..q-18, locale hi): Three items fall back to English while `translation_status.hi.status` is "verified" and `fallback_blocks` is empty.
Why it matters: the manifest claims a reviewed Hindi pack; a student sees English mid-set with no marker, which is the "language mirage" the translation spec forbids.
Fix: translate the three items, or set the status to `partial` and list the fallback ids; do not claim `verified` until the pack is complete.
```

Verdict: **Request changes** (one blocker). Rubric: grounding 2, assessment 0, coverage 2, language 1, technical 3, evidence 2. The single highest-leverage change is the answer-key check fixture: it would have caught q-07 before review.

## Severity guidance

| Situation | Typical level |
|---|---|
| Wrong answer key; fact contradicts the cited source; a later-chapter concept taught or tested as fact; the page teaches the wrong chapter's content; translation inverts a physics statement; answer read aloud by narration; page blank/broken; `eval`/external call/CSP break; a generated item claimed to be an official/endorsed CBSE paper | **blocker** |
| Identity-only title/chapter-label error; missing or empty explanation; a required chapter section or exercise type missing; marks/section totals wrong; untranslated leak in a promised locale; duplicate topic page; thin series volume; mixed pipeline versions in one catalogue; "exact paper"/"board-pattern" claim on generated items without official endorsement; serious accessibility defect; eval evidence missing for a new failure mode | **major** |
| Thin but correct explanation; glossary term missing; readability above the class level; awkward but faithful translation; weak caption; non-blocking a11y polish | **minor** |
| Typography, wording preference, layout taste with no learning or claim impact | **nit** |
| Unsettled product choice, missing context, or a suspected issue you cannot reproduce | **question** |
| A page, item, translation, or check that is notably clear, well-grounded, or honestly flagged | **praise** |

## Reference map

| Read this | When |
|---|---|
| [references/content-quality-checklist.md](references/content-quality-checklist.md) | Before signing off any content PR; it is the per-area checklist and evidence table |
| [references/review-procedure.md](references/review-procedure.md) | You need the artifact map, sampling rules, exact commands, or severity calibration |
| [references/anti-patterns.md](references/anti-patterns.md) | You see a familiar failure and want the detection/fix recipe and default severity |
| [templates/content-review-report.md](templates/content-review-report.md) | You are writing the report and want the suite-shaped skeleton |

## Contract sources

Read the contract for the artifact you are reviewing; do not invent a standard the repo already fixed.

- `AGENTS.md` — subject scope, grounding law, non-negotiables, definition of done.
- `docs/content-factory/architecture.md` — stages, gates, coverage contract, severity ladders, resume rules.
- `docs/content-factory/blocks-schema.md` — block IDs, per-type specs, ordering, localization contracts.
- `docs/content-factory/runbook.md` — operating the pipeline, reading artifacts, common failures.
- `docs/specs/evals/spec.md`, `docs/specs/evals/card-template.md`, `docs/specs/evals/golden-sets.md` — eval cards, deterministic-first funnel, goldens, seeded defects, thresholds.
- `docs/specs/translation/spec.md`, `docs/specs/translation/block-contract.md`, `docs/specs/translation/reviewer-rubric.md` — locale model, script rules, glossary, per-block translation, fallback flags.
- `docs/specs/gaps/gap-register.md` §GAP-015 — narration speakable rules, availability flag, audio manifest, budget.
- `docs/product/features.md` — F-COR-LES-01, F-COR-CHK-01, F-COR-SIM-01, F-COR-DIA-01, F-COR-PROV-01, F-WRP-LAN-01, F-WRP-TTS-01, F-OPS-MET-01.
- `docs/specs/frontend/shell-injection.md`, `docs/frontend/design-doctrine.md` — hooks and the visual reference the content must remain compatible with.
- `docs/specs/observability/instrumentation-map.csv` — the event rows that make a run auditable.
- `factory/lint.py`, `factory/checks.py`, `factory/review.py`, `factory/perf.py`, `evals/checkers/**`, `evals/cards/**` — the code that already enforces the mechanical rules.

## External evidence basis

The rubric is a synthesis, not a copy. Dated sources behind its claims:

- W3C, *Web Content Accessibility Guidelines (WCAG) 2.2*, W3C Recommendation, 12 December 2024 (`https://www.w3.org/TR/WCAG22/`): text alternatives, info and relationships, contrast, reflow at 320 CSS px, keyboard, labels/headings, target size, language of page/parts, name-role-value, status messages.
- NIST, *Artificial Intelligence Risk Management Framework (AI RMF 1.0)*, NIST AI 100-1, 26 January 2023 (`https://www.nist.gov/itl/ai-risk-management-framework`), and the *Generative AI Profile* (NIST AI 600-1, 26 July 2024): measure trustworthiness characteristics (valid and reliable, safe, accountable and transparent, explainable) and manage risk with evidence, not assertion.
- Ribeiro, Wu, Guestrin, Singh, *Beyond Accuracy: Behavioral Testing of NLP Models with CheckList*, ACL 2020 (`https://arxiv.org/abs/2005.04118`): minimum-functionality, invariance, and directional tests; deterministic behavioural tests before aggregate scores.
- Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, NeurIPS 2023 Datasets and Benchmarks (`https://arxiv.org/abs/2306.05685`): position, verbosity, and self-enhancement biases; judge agreement must be calibrated, never assumed.
- Rosenshine, *Principles of Instruction: Research-Based Strategies That All Teachers Should Know*, American Educator 36(1), Spring 2012, pp. 12–19, 39 (`https://www.aft.org/ae/spring2012/rosenshine`): small steps, worked examples, checks for understanding, and retrieval practice — the basis for teach-before-test and explanation requirements.

Curriculum coverage is judged against the repo's NCERT/public-domain source packs (`sources/catalog.json`, `docs/content-factory/source-catalog.md`), not against an external syllabus's remembered contents. Re-verify any perishable claim (board pattern, chapter numbering, marks scheme) at review time.

## Non-negotiables

- Never approve a wrong answer key or a factual contradiction because "the tests pass". Tests check mechanics; this lens checks meaning.
- Never let a model judge, a previous reviewer, or a confident explanation substitute for a recomputation or a source quote.
- Never require a live model, TTS, or paid call to review content; use artifacts and mocks.
- Never hide content debt in a PR description without an owner, artifact, and reproduction.
- Never re-litigate a frozen product decision in a review; cite the doc and ask.
- Never edit `factory/`, `frontend/`, or `evals/` merely to make a review pass. Report the defect; fixes go through the owning workstream and its gates.
