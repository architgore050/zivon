# Content-quality anti-patterns

Recurring failure shapes in generated learning content and the pipeline that produces it. Each entry gives the symptom, why it matters, how to detect it, the default severity, and the fix or gate that should prevent recurrence.

Quick index: [wrong key](#1-wrong-answer-key) · [off-chapter concept](#2-off-chapter-concept-scope-smuggling) · [missing explanation](#3-missing-explanation) · [broken visual](#4-broken-diagram-or-simulation) · [untranslated leak](#5-untranslated-leak-and-language-mirage) · [false provenance](#6-false-provenance-or-endorsement-claim) · [duplicate topic](#7-duplicate-topic) · [mixed versions](#8-mixed-pipeline-versions) · [citation theatre](#9-citation-theatre) · [invented numbers](#10-invented-numbers-and-unit-drift) · [answer leak](#11-answer-leak) · [tolerance mismatch](#12-tolerance-mismatch) · [paraphrase duplication](#13-paraphrase-duplication) · [eval theatre](#14-eval-theatre) · [readability cliff](#15-readability-cliff) · [placeholder leakage](#16-placeholder-leakage) · [stale catalogue](#17-stale-catalogue-or-sitemap) · [hidden debt](#18-hidden-content-debt)

## 1. Wrong answer key

**Symptom.** `answer_index` points to a distractor; `answer` text disagrees with `options[answer_index]`; a numeric key is off by a factor, sign, or unit; the explanation defends the wrong value.

**Why it matters.** A learner who reasons correctly is marked wrong and then taught the error. This is the highest-cost content defect because it directly rewards the wrong mental model.

**Detect.** Recompute every key from the chapter's stated equation with the numbers on the page. Check `answer == options[answer_index]` mechanically (`factory/checks.py::rule_answer_keys`). Compare against `evals/goldens/topics/*/expected.json` numerical anchors where they exist. Do not accept "the reviewer passed it" as evidence.

**Default severity.** Blocker.

**Fix / gate.** Correct the key and the explanation; add the check to the deterministic answer-key fixture; if the generator produced it, add the failure shape to `EV-SYN-002` / the seeded-defect corpus so the reviewer is calibrated on it.

## 2. Off-chapter concept (scope smuggling)

**Symptom.** A Motion page tests momentum; a Light page teaches refraction before reflection; a check uses a formula from the next chapter; a "background" sentence introduces a term the source pack never defines.

**Why it matters.** The grounding law says the source pack is the whole universe of the page. A learner cannot consult the next chapter, so the check is unfair; it also makes coverage look complete when it is not.

**Detect.** List the concepts in the chapter inventory and the concepts on the page. Diff them. Grep for the forbidden terms in the golden's `source_provenance.forbidden_smuggled_terms`. Read each check's stem and explanation, not just the lesson prose.

**Default severity.** Blocker when taught/tested as fact; major when a passing mention does not carry an answer.

**Fix / gate.** Remove or replace the concept; add the term to the golden's forbidden list; if it is a legitimate prerequisite, mark the prerequisite explicitly and cite the source that teaches it.

## 3. Missing explanation

**Symptom.** `explanation` is empty, one word ("Correct"), restates the answer ("It is 10 m/s"), or explains only the wrong option.

**Why it matters.** The product promises "Why?" feedback (F-COR-CHK-01). Without it, practice becomes a score, and a wrong answer stays a mystery.

**Detect.** Scan every check for `explanation` presence and length; read a sample for whether it names the concept and the step. A correct key with no explanation is still a defect.

**Default severity.** Major; minor if a short but genuinely explanatory sentence is present.

**Fix / gate.** Add a one-paragraph explanation that names the concept, the equation, and the step; require `explanation` in the check schema and in the deterministic coverage check.

## 4. Broken diagram or simulation

**Symptom.** SVG has `<script>`, `<style>`, an external URL, or a missing `aria-label`; the drawing shows a ball at the bottom of a slope when the caption says top; a graph is hand-placed instead of computed; the sim canvas is blank, throws, or has no readout; controls do not change anything.

**Why it matters.** A visual that contradicts the text teaches the wrong physics more effectively than text alone. A blank sim looks broken and erodes trust in the whole page.

**Detect.** Run `factory/lint.py::lint_js/lint_css/lint_html/lint_page_css_scope`; open the page and interact; compare the drawn behaviour with the cited facts and the block's `default_behaviour`; check `.zn-sim-read`, the description, reduced motion, and the error painter. For computed geometry, confirm the JS evaluates the equation per point rather than hard-coding coordinates.

**Default severity.** Blocker when the drawing or sim is physically wrong or the page cannot render; major for a missing readout/description or an accessibility defect.

**Fix / gate.** Fix the spec or `page.js`; route computed graphs to `simulation`; add the behaviour to the `09-review` facts check and the visual seeded-defect set; do not hand-edit generated `page.js` outside the owning stage.

## 5. Untranslated leak and language mirage

**Symptom.** A page claims `locales_available: ["en", "hi", "hi-Latn"]`, but a check stem, explanation, control label, or glossary line is still English; `hi-Latn` contains Devanagari; `hi` is mostly English; `translation_status.hi.status` is "verified" while fallback ids are non-empty; a localized route silently serves English with no marker.

**Why it matters.** A student who chose Hindi to think at speed hits English mid-sentence. A false "verified" flag is worse than an honest "partial" because it removes the student's ability to judge what they are reading.

**Detect.** Walk every `data-i18n` key; scan `hi-Latn` for `[\u0900-\u097F]`; compute the native-script ratio for `hi`; compare `translation_status.fallback_blocks` with the actual fallbacks; open each localized route and read a body block and a check. Check units/numerals/equations stayed untranslated.

**Default severity.** Major; blocker if the meaning is inverted or a physics term is mistranslated into a different concept.

**Fix / gate.** Translate the missing units or mark the locale `partial` with the fallback ids; fix the script; add a glossary entry; re-run `10b-transcheck`; never let a chip promise a locale the bundle does not deliver.

## 6. False provenance or endorsement claim

**Symptom.** "Official NCERT", "CBSE-approved", "board-approved", "exact past paper", or "guaranteed board pattern" on generated content; a page implies institutional endorsement it does not have.

**Why it matters.** It is a false claim about provenance and endorsement. It misleads a student about what they are reading and creates legal/consumer risk for the product.

**Detect.** Grep the page and manifest for `official`, `endorsed`, `CBSE`, `board`, `approved`, `guaranteed`, `past paper`. For every hit, ask: is this actually a sourced, cleared document, or is it generated? Check the footer attribution against `sources/catalog.json`.

**Default severity.** Major; blocker for an official-endorsement or guaranteed-score claim.

**Fix / gate.** State the source and licence plainly instead of borrowing authority; attribute real sources with clearance; add a copy-compliance assertion to the publish smoke.

## 7. Duplicate topic

**Symptom.** Two catalogue entries point to the same chapter (for example `motion` and `how-forces-affect-motion` under Class 9); a stale model-titled directory survives beside the canonical slug; the same page appears under two titles; one chapter has two `manifest.json` files.

**Why it matters.** The catalogue becomes untrustworthy, search duplicates compete, and a learner can land on the older, lower-quality page. It also hides which pipeline version is actually live.

**Detect.** List `frontend/courses/*/*/manifest.json`; group by `course_id` + `chapter.number`/`chapter.title`; compare directory slugs with `courses.js` entries; check `factory/link.py`'s prune behaviour and the run's `--fresh` history.

**Default severity.** Major.

**Fix / gate.** Republish the chapter through the owning flow so the stale duplicate is pruned; add a catalogue uniqueness assertion; never hand-delete a page without the publish flow.

## 8. Mixed pipeline versions

**Symptom.** One catalogue contains pages with and without `lesson_title`; one page uses `page.css` while another uses the kit; one manifest lacks `locales_available`; one page's title is a model headline; the run fingerprints that produced two pages differ.

**Why it matters.** The shell and catalogue contracts are versioned. A mixed tree means some pages miss hooks, metadata, or locale fields; consumers cannot rely on one shape. The audit found this live (three manifests lack `lesson_title`, one has `chapter.title = "Grade"`, one has no `locales_available`).

**Detect.** Compare every manifest's `lesson_title`, `locales_available`, `translation_status`, `narration`, and asset set. `pipeline_version` is in each run's fingerprint/`status.json` (`factory/stages.py::run_fingerprint`), not in the topic manifest; read it there. Check `courses.js` entries against the same fields.

**Default severity.** Major.

**Fix / gate.** Republish the affected topics at one `PIPELINE_VERSION` through the founder-triggered batch; add a homogeneity guard to the publish flow; do not hand-patch one page to look current.

## 9. Citation theatre

**Symptom.** A factual block has `citations: [{"claim_id": "claim-03"}]`, but claim-03 is a generic statement or a different topic; the claim id exists but the source passage does not support the sentence; every block cites the same claim.

**Why it matters.** It passes the mechanical citation rule while providing no grounding. A reviewer who counts citations instead of tracing them approves unsupported physics.

**Detect.** Follow three claims end to end: block → claim id → ground truth → source passage. Read the passage. If the support is indirect, say so. Check the prompt/ground truth for `uncertain` rather than invented resolution.

**Default severity.** Major; blocker if the unsupported sentence is a fact or an answer key.

**Fix / gate.** Fix the claim/sentence or cite the correct passage; add a quote-fidelity check to `EV-CUR-001`; do not add a citation to a block that should not exist.

## 10. Invented numbers and unit drift

**Symptom.** A worked-example problem uses `12 m/s` when the source only has `10 m/s`; a check answer converts km/h to m/s but labels it m/s; a step drops a factor of 2; a final answer is in the wrong unit.

**Why it matters.** The invented-number rule exists because a plausible number makes a fake problem look textbook-real. Unit drift makes a correct method look wrong.

**Detect.** `factory/checks.py::rule_numbers` for problem/question numerals (whole-numeral match); recompute answers; check every unit and conversion; compare with the golden's numerical anchors and tolerance.

**Default severity.** Blocker when the answer/unit is wrong; major when a problem number is invented but the method is sound.

**Fix / gate.** Replace the number with a source number or mark the problem as generated practice with a stated source; add a numeric/unit seeded defect to the eval suite.

## 11. Answer leak

**Symptom.** The narration reads the check's answer/explanation; the answer is in an `aria-label`, a visible `data-answer-index`, or a `details` that is open by default; the explanation is visible before commit; a sim readout states the answer.

**Why it matters.** It destroys retrieval practice and makes the check decorative. Reading the answer aloud is especially bad because the student cannot "not look".

**Detect.** Check the speakable selection (`factory/narration/select.py`); inspect the rendered check before interaction; search the DOM for the answer text; confirm `answer_index` is not rendered as a visible attribute/hint.

**Default severity.** Blocker for narration/DOM leak on a shipped check; major for a hidden-but-fragile exposure.

**Fix / gate.** Remove the answer from the speakable selection and the pre-commit DOM; keep it in the post-commit explanation only; add a narration-answer assertion to the narration tests.

## 12. Tolerance mismatch

**Symptom.** A numeric check rejects a correctly rounded answer; a reviewer demands a per-item tolerance the schema does not have; a tolerance is described in the wrong unit or conflated with the eval-golden tolerance.

**Why it matters.** The runtime tolerance is fixed (`Math.max(0.01, |expected| * 0.01)` in `frontend/assets/zivon.js`); the golden schema's `tolerance_rel` (default `0.02`) compares canonical numerical anchors. Treating one as the other produces a bogus finding in either direction.

**Detect.** Read the expected value and the accepted interval from the runtime rule; compare with the significant figures in the problem; check the golden's `tolerance_rel` separately and only for anchor comparisons.

**Default severity.** Major when a learner is marked wrong by the runtime; minor for a review comment that asks for a nonexistent field.

**Fix / gate.** Keep the runtime rule and the golden rule separate in the review; add the boundary value to the frontend numeric-check fixture; do not invent an item-level tolerance field.

## 13. Paraphrase duplication

**Symptom.** The same check appears twice with one word changed; a page has 18 checks but only 9 distinct concepts/stems; a "new" block is a paraphrase of an earlier one.

**Why it matters.** Volume looks higher than it is; a learner memorises the paraphrase, not the concept; coverage claims become false.

**Detect.** Normalize stems (lowercase, strip punctuation/numbers) and compare; check item ids and source references; sample the repeated concept.

**Default severity.** Minor for two near-duplicates; major when the page claims coverage it does not have.

**Fix / gate.** Merge or replace duplicates; add a uniqueness check to the check-set validation; record intentional repetition as repetition, not as new coverage.

## 14. Eval theatre

**Symptom.** A prompt/checker PR has no eval card, or a card with only a judge and no deterministic checker; goldens are regenerated from the new output so the diff is green; calibration is not re-run after a reviewer change; the PR says "evals pass" without a run id.

**Why it matters.** The eval framework is the only cross-run evidence that content quality did not regress. A green check that cannot fail is worse than no check because it creates false confidence.

**Detect.** Read `evals/cards/*.yaml`; confirm the checker entrypoint exists and is referenced; confirm goldens are registered and not rewritten in the same PR; compare calibration recall/specificity with the baseline; look for a run id and `eval_summary.md`.

**Default severity.** Major; blocker if a release gate depends on a fabricated pass.

**Fix / gate.** Add the deterministic checker and a seeded defect; keep the golden unchanged unless the contract changed; attach the run id; run `python -m evals run --suite smoke --fail-on-regression`.

## 15. Readability cliff

**Symptom.** A Class 9 page uses postgraduate prose; a Hindi translation is formal Sanskritised Hindi a 14-year-old would not speak; a sentence has three nested clauses; a definition uses the term it is defining.

**Why it matters.** The product's job is to make Physics learnable. A correct sentence that the learner cannot parse is still a content failure.

**Detect.** Read one paragraph aloud; check sentence length and vocabulary against the class level; compare with the reference page; ask a real kid tester when the Gate B loop is available. For Hindi/Hinglish, check naturalness, not just script purity.

**Default severity.** Minor; major if the explanation is unusable or a key concept is unintelligible.

**Fix / gate.** Rewrite in plain class-level language; add a readability note to the generation prompt only if the failure recurs; do not turn a style preference into a blocker.

## 16. Placeholder leakage

**Symptom.** `zivon.local` in a production canonical/OG URL; "TODO" or a template string in a shipped page; `null`/`undefined`/`NaN` visible; a locale chip for a bundle that does not exist; a "coming soon" that has been coming for a release.

**Why it matters.** Placeholders are visible trust failures and sometimes broken links. A missing locale chip that lies is worse than an honest disabled state.

**Detect.** Grep the published tree for `zivon.local`, `undefined`, `NaN`, `TODO`, `TBD`, `FIXME`, `lorem`, `example.com`; open the page and read the header/footer; check `sitemap.xml`/`robots.txt` host.

**Default severity.** Major for a visible placeholder or broken canonical; minor for an internal-only template string.

**Fix / gate.** Regenerate from the publish flow with the real base URL; add a placeholder scan to the publish smoke; never hand-edit the generated file.

## 17. Stale catalogue or sitemap

**Symptom.** `courses.js` lists a topic whose page was removed; a localized hub links to the English page with no marker; `sitemap.xml` lists 5 URLs for 7 topics; `robots.txt` points at the wrong host; a new topic is missing from the catalogue.

**Why it matters.** Catalogue and sitemap are the discovery surface. A dead link or a missing topic makes the product look unfinished and breaks SEO.

**Detect.** Resolve every href in `courses.js`, every declared locale file, and every sitemap URL; compare the topic list with `find frontend/courses -name manifest.json`; check the published host is not a placeholder.

**Default severity.** Major; blocker if the primary route to a lesson 404s.

**Fix / gate.** Re-run the publish flow (`factory/link.py` + `scripts/publish-frontend.sh`) so `courses.js`, locale hubs, sitemap, and robots are regenerated; the end-to-end page-quality card (`EV-E2E-001`) covers the published tree.

## 18. Hidden content debt

**Symptom.** The PR says "known issue, will fix later" with no owner, artifact, or reproduction; a defect is downgraded to a nit to get a green review; the debt lives only in a chat thread; a new TODO file appears instead of a `TIMELINE.md` entry.

**Why it matters.** `AGENTS.md` says `TIMELINE.md` is the only task list and pending work is merged into it; a TODO file is a second list that will drift. Unrecorded debt becomes invisible, then permanent.

**Detect.** Check the PR body, `TIMELINE.md`, and the run report. A debt entry needs: artifact, finding, severity, owner, reproduction, target. No owner or no reproduction = not logged.

**Default severity.** Major (the process defect is real even if the content issue is minor).

**Fix / gate.** Record the debt in `TIMELINE.md` or the PR body with the required fields; keep the intrinsic severity; do not create a new TODO file.
