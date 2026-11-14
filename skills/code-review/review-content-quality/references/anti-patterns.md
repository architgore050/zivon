# Content-quality anti-patterns

Recurring failure shapes in generated learning content and the pipeline that produces it. Each entry gives the symptom, why it matters, how to detect it, the default severity, and the fix or gate that should prevent recurrence.

Quick index: [wrong key](#1-wrong-answer-key) · [off-chapter concept](#2-off-chapter-concept-scope-smuggling) · [missing explanation](#3-missing-explanation) · [broken visual](#4-broken-diagram-or-simulation) · [untranslated leak](#5-untranslated-leak-and-language-mirage) · [marks mismatch](#6-marks-or-section-mismatch) · [CBSE over-claim](#7-over-claiming-cbse-or-board-alignment) · [duplicate topic](#8-duplicate-topic) · [thin series](#9-thin-series) · [mixed versions](#10-mixed-pipeline-versions) · [citation theatre](#11-citation-theatre) · [invented numbers](#12-invented-numbers-and-unit-drift) · [answer leak](#13-answer-leak) · [tolerance abuse](#14-tolerance-abuse) · [paraphrase duplication](#15-paraphrase-duplication) · [eval theatre](#16-eval-theatre) · [readability cliff](#17-readability-cliff) · [placeholder leakage](#18-placeholder-leakage) · [stale catalogue](#19-stale-catalogue-or-sitemap) · [hidden debt](#20-hidden-content-debt)

## 1. Wrong answer key

**Symptom.** `answer_index` points to a distractor; `answer` text disagrees with `options[answer_index]`; a numeric key is off by a factor, sign, or unit; the explanation defends the wrong value.

**Why it matters.** A learner who reasons correctly is marked wrong and then taught the error. This is the highest-cost content defect because it directly rewards the wrong mental model.

**Detect.** Recompute every key from the chapter's stated equation with the numbers on the page. Check `answer == options[answer_index]` mechanically (`factory/checks.py::rule_answer_keys`). Compare against `evals/goldens/topics/*/expected.json` numerical anchors where they exist. Do not accept "the reviewer passed it" as evidence.

**Default severity.** Blocker.

**Fix / gate.** Correct the key and the explanation; add the item to the deterministic answer-key fixture; if the generator produced it, add the failure shape to `EV-SYN-002` / the seeded-defect corpus so the reviewer is calibrated on it.

## 2. Off-chapter concept (scope smuggling)

**Symptom.** A Motion page tests momentum; a Light page teaches refraction before reflection; a check uses a formula from the next chapter; a "background" sentence introduces a term the source pack never defines.

**Why it matters.** The grounding law says the source pack is the whole universe of the page. A learner cannot consult the next chapter, so the item is unfair; it also makes coverage look complete when it is not.

**Detect.** List the concepts in the chapter inventory and the concepts on the page. Diff them. Grep for the forbidden terms in the golden's `source_provenance.forbidden_smuggled_terms`. Read each check's stem and explanation, not just the lesson prose.

**Default severity.** Blocker when taught/tested as fact; major when a passing mention does not carry an answer.

**Fix / gate.** Remove or replace the concept; add the term to the golden's forbidden list; if it is a legitimate prerequisite, mark the prerequisite explicitly and cite the source that teaches it.

## 3. Missing explanation

**Symptom.** `explanation` is empty, one word ("Correct"), restates the answer ("It is 10 m/s"), or explains only the wrong option.

**Why it matters.** The product promises "Why?" feedback (F-COR-CHK-01). Without it, practice becomes a score, and a wrong answer stays a mystery.

**Detect.** Scan every check for `explanation` presence and length; read a sample for whether it names the concept and the step. A correct key with no explanation is still a defect.

**Default severity.** Major; minor if a short but genuinely explanatory sentence is present.

**Fix / gate.** Add a one-paragraph explanation that names the concept, the equation, and the step; require `explanation` in the item schema and in the deterministic coverage check.

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

## 6. Marks or section mismatch

**Symptom.** Section subtotals do not add to the paper total; an item's marks disagree with its type; a 3-mark question has a 1-mark answer space; the blueprint says five sections and the paper has four; choice rules are missing.

**Why it matters.** Marks are the contract with an exam-style learner. A wrong total makes the practice paper feel fake and makes time/score evidence unusable.

**Detect.** Sum every section and the whole paper; compare with the blueprint and the manifest; check each item's marks against its type; check duration against total marks.

**Default severity.** Major; blocker if the paper is published and a learner is scored on the wrong total.

**Fix / gate.** Correct the blueprint or the items; add a total/section assertion to the series manifest check (`EV-SER-001`/`EV-SER-002` when the card space exists).

## 7. Over-claiming CBSE or board alignment

**Symptom.** "Exact CBSE 2025 paper", "official CBSE questions", "CBSE-approved", "guaranteed board pattern" on generated items; "exact PYQ" on a paraphrased question; a generated series presented as a past paper.

**Why it matters.** It is a false claim about provenance and endorsement. It misleads a student about what they are practising and creates legal/consumer risk for the product.

**Detect.** Grep the pack/manifest/page for `official`, `exact`, `CBSE`, `board`, `approved`, `guaranteed`, `past paper`. For every hit, ask: is this actually a sourced past question with clearance, or is it generated? Check the series manifest's `source_policy`.

**Default severity.** Major; blocker for an official-endorsement or guaranteed-score claim.

**Fix / gate.** Use the approved wording ("close to the paper pattern", "built for practice", "not an official CBSE paper"); attribute real PYQs with source and clearance; add a copy-compliance checker to the series publish gate.

## 8. Duplicate topic

**Symptom.** Two catalogue entries point to the same chapter (for example `motion` and `how-forces-affect-motion` under Class 9); a stale model-titled directory survives beside the canonical slug; the same page appears under two titles; one chapter has two `manifest.json` files.

**Why it matters.** The catalogue becomes untrustworthy, search duplicates compete, and a learner can land on the older, lower-quality page. It also hides which pipeline version is actually live.

**Detect.** List `frontend/courses/*/*/manifest.json`; group by `course_id` + `chapter.number`/`chapter.title`; compare directory slugs with `courses.js` entries; check `factory/link.py`'s prune behaviour and the run's `--fresh` history.

**Default severity.** Major.

**Fix / gate.** Republish the chapter through the owning flow so the stale duplicate is pruned; add a catalogue uniqueness assertion; never hand-delete a page without the publish flow.

## 9. Thin series

**Symptom.** A full-paper series covers 4 of 7 chapters; a chapter has 3 questions against a 10-question bar; `AI Lesson` omits half the concepts; a series manifest claims counts the pack does not contain.

**Why it matters.** A series is a promise of coverage. A thin series gives false confidence and makes the coverage/SWOT evidence downstream meaningless.

**Detect.** Compare the series manifest with the chapter/concept inventory; count items per chapter and concept; check the declared minimum volume; sample the missing chapters to confirm they are truly absent, not just mis-tagged.

**Default severity.** Major.

**Fix / gate.** Generate the missing volume or lower the claim honestly; block publish on the coverage gate (`EV-SER-002`); record the gap in the manifest, not just the PR.

## 10. Mixed pipeline versions

**Symptom.** One catalogue contains pages with and without `lesson_title`; one page uses `page.css` while another uses the kit; one manifest lacks `locales_available`; one page's title is a model headline; `pipeline_version` differs across entries.

**Why it matters.** The shell and catalogue contracts are versioned. A mixed tree means some pages miss hooks, metadata, or locale fields; consumers cannot rely on one shape. The audit found this live (three manifests lack `lesson_title`, one has `chapter.title = "Grade"`, one has no `locales_available`).

**Detect.** Compare every manifest's `pipeline_version`, `lesson_title`, `locales_available`, `translation_status`, `narration`, and asset set. Check `courses.js` entries against the same fields.

**Default severity.** Major.

**Fix / gate.** Republish the affected topics at one `PIPELINE_VERSION` through the founder-triggered batch; add a homogeneity guard to the publish flow; do not hand-patch one page to look current.

## 11. Citation theatre

**Symptom.** A factual block has `citations: [{"claim_id": "claim-03"}]`, but claim-03 is a generic statement or a different topic; the claim id exists but the source passage does not support the sentence; every block cites the same claim.

**Why it matters.** It passes the mechanical citation rule while providing no grounding. A reviewer who counts citations instead of tracing them approves unsupported physics.

**Detect.** Follow three claims end to end: block → claim id → ground truth → source passage. Read the passage. If the support is indirect, say so. Check the prompt/ground truth for `uncertain` rather than invented resolution.

**Default severity.** Major; blocker if the unsupported sentence is a fact or an answer key.

**Fix / gate.** Fix the claim/sentence or cite the correct passage; add a quote-fidelity check to `EV-CUR-001`; do not add a citation to a block that should not exist.

## 12. Invented numbers and unit drift

**Symptom.** A worked-example problem uses `12 m/s` when the source only has `10 m/s`; a check answer converts km/h to m/s but labels it m/s; a step drops a factor of 2; a final answer is in the wrong unit.

**Why it matters.** The invented-number rule exists because a plausible number makes a fake problem look textbook-real. Unit drift makes a correct method look wrong.

**Detect.** `factory/checks.py::rule_numbers` for problem/question numerals (whole-numeral match); recompute answers; check every unit and conversion; compare with the golden's numerical anchors and tolerance.

**Default severity.** Blocker when the answer/unit is wrong; major when a problem number is invented but the method is sound.

**Fix / gate.** Replace the number with a source number or mark the item as generated practice with a stated source; add the item to `EV-SYN-003` (numeric/unit check) when available.

## 13. Answer leak

**Symptom.** The narration reads the check's answer/explanation; the answer is in an `aria-label`, a `data-answer-index` used visibly, or a `details` that is open by default; the explanation is visible before commit; a sim readout states the answer.

**Why it matters.** It destroys retrieval practice and makes the check decorative. Reading the answer aloud is especially bad because the student cannot "not look".

**Detect.** Check the speakable selection (`factory/narration/select.py`); inspect the rendered check before interaction; search the DOM for the answer text; confirm `answer_index` is not rendered as a visible attribute/hint.

**Default severity.** Blocker for narration/DOM leak on a shipped check; major for a hidden-but-fragile exposure.

**Fix / gate.** Remove the answer from the speakable selection and the pre-commit DOM; keep it in the post-commit explanation only; add a narration-answer assertion to the narration tests.

## 14. Tolerance abuse

**Symptom.** A numeric item accepts any answer because tolerance is huge or absent; a tightly rounded answer rejects the correct value; a tolerance is declared in the wrong unit.

**Why it matters.** A too-loose tolerance makes the check meaningless; a too-tight one marks a correct learner wrong. Both are assessment-integrity defects.

**Detect.** Read the tolerance and the expected value; compute the accepted interval; compare with the significant figures in the problem; check the golden's `tolerance_rel` default (0.02) and any item-specific override.

**Default severity.** Major.

**Fix / gate.** Declare a relative tolerance consistent with the data; test the boundary values; add the item to the numeric-check fixture.

## 15. Paraphrase duplication

**Symptom.** The same question appears twice with one word changed; a "new" series reuses the same item across papers without saying so; a practice pack has 18 items but only 9 distinct concepts/stems.

**Why it matters.** Volume looks higher than it is; a learner memorises the paraphrase, not the concept; series coverage claims become false.

**Detect.** Normalize stems (lowercase, strip punctuation/numbers) and compare; check item ids and source references; sample the repeated concept.

**Default severity.** Minor for two near-duplicates; major when the pack/series claims volume or coverage it does not have.

**Fix / gate.** Merge or replace duplicates; add a uniqueness check to the pack/series schema; record intentional reuse as reuse, not as new volume.

## 16. Eval theatre

**Symptom.** A prompt/checker PR has no eval card, or a card with only a judge and no deterministic checker; goldens are regenerated from the new output so the diff is green; calibration is not re-run after a reviewer change; the PR says "evals pass" without a run id.

**Why it matters.** The eval framework is the only cross-run evidence that content quality did not regress. A green check that cannot fail is worse than no check because it creates false confidence.

**Detect.** Read `evals/cards/*.yaml`; confirm the checker entrypoint exists and is referenced; confirm goldens are registered and not rewritten in the same PR; compare calibration recall/specificity with the baseline; look for a run id and `eval_summary.md`.

**Default severity.** Major; blocker if a release gate depends on a fabricated pass.

**Fix / gate.** Add the deterministic checker and a seeded defect; keep the golden unchanged unless the contract changed; attach the run id; run `python -m evals run --suite smoke --fail-on-regression`.

## 17. Readability cliff

**Symptom.** A Class 9 page uses postgraduate prose; a Hindi translation is formal Sanskritised Hindi a 14-year-old would not speak; a sentence has three nested clauses; a definition uses the term it is defining.

**Why it matters.** The product's job is to make Physics learnable. A correct sentence that the learner cannot parse is still a content failure.

**Detect.** Read one paragraph aloud; check sentence length and vocabulary against the class level; compare with the reference page; ask a real kid tester when the Gate B loop is available. For Hindi/Hinglish, check naturalness, not just script purity.

**Default severity.** Minor; major if the explanation is unusable or a key concept is unintelligible.

**Fix / gate.** Rewrite in plain class-level language; add a readability note to the generation prompt only if the failure recurs; do not turn a style preference into a blocker.

## 18. Placeholder leakage

**Symptom.** `zivon.local` in a production canonical/OG URL; "TODO" or a template string in a shipped page; `null`/`undefined`/`NaN` visible; a locale chip for a bundle that does not exist; a "coming soon" that has been coming for a release.

**Why it matters.** Placeholders are visible trust failures and sometimes broken links. A missing locale chip that lies is worse than an honest disabled state.

**Detect.** Grep the published tree for `zivon.local`, `undefined`, `NaN`, `TODO`, `TBD`, `FIXME`, `lorem`, `example.com`; open the page and read the header/footer; check `sitemap.xml`/`robots.txt` host.

**Default severity.** Major for a visible placeholder or broken canonical; minor for an internal-only template string.

**Fix / gate.** Regenerate from the publish flow with the real base URL; add a placeholder scan to the publish smoke; never hand-edit the generated file.

## 19. Stale catalogue or sitemap

**Symptom.** `courses.js` lists a topic whose page was removed; a localized hub links to the English page with no marker; `sitemap.xml` lists 5 URLs for 7 topics; `robots.txt` points at the wrong host; a new topic is missing from the catalogue.

**Why it matters.** Catalogue and sitemap are the discovery surface. A dead link or a missing topic makes the product look unfinished and breaks SEO.

**Detect.** Resolve every href in `courses.js`, every declared locale file, and every sitemap URL; compare the topic list with `find frontend/courses -name manifest.json`; check the published host is not a placeholder.

**Default severity.** Major; blocker if the primary route to a lesson 404s.

**Fix / gate.** Re-run the publish flow (`factory/link.py` + `scripts/publish-frontend.sh`) so `courses.js`, locale hubs, sitemap, and robots are regenerated; add the publish smoke (`EV-E2E-002`).

## 20. Hidden content debt

**Symptom.** The PR says "known issue, will fix later" with no owner, artifact, or reproduction; a defect is downgraded to a nit to get a green review; the debt lives only in a chat thread; a new TODO file appears instead of a `TIMELINE.md` entry.

**Why it matters.** The R1 gate permits content debt only when it is **measured and logged**. Hidden debt becomes invisible, then permanent.

**Detect.** Check the PR body, `TIMELINE.md`, and the run report. A debt entry needs: artifact, finding, severity, owner, reproduction, target. No owner or no reproduction = not logged.

**Default severity.** Major (the process defect is real even if the content issue is minor).

**Fix / gate.** Record the debt in `TIMELINE.md` or the PR body with the required fields; keep the intrinsic severity; do not create a new TODO file.
